# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de dominios (spec 011, T18; RF-011-07; plan 011 D-32; RF-006-12, RF-008-52).

Una capa de polígonos de un GeoPackage se importa con el papel «dominios» de la importación de
capas de la 006 (``gis.import_vector``), sin cambiar ningún RF de la 006:

- ``gis.vector.field_columns``: los campos de la capa como columnas de la tabla del proyecto
  (texto, entero o real; el nombre, un identificador de GeoPackage; el original, su título);
  ``gis.vector.domains_from_features``: de cada Polygon o MultiPolygon, su número, sus anillos
  en planta tal como llegan y sus atributos (otra geometría se rechaza con su número);
- ``gis.store.ResultWriter.domains``: lo importado en ``gis_dom_<nombre>_<entrada8>``
  (``MULTIPOLYGON`` sin Z, con su número de entidad y los atributos como columnas), inmutable
  con su entrada: cambiarlo desde otra conexión aborta (RF-008-52);
- ``gis.store.load_domains``: cada entidad con su número, sus atributos y sus anillos;
- el trabajo ``gis_import_vector`` con el papel ``domains``: ``domains.npz`` y el hash de la
  tabla que será lo importado (``gis.store.table_digest`` con sus columnas).

Datos sintéticos: ``fases.gpkg``, escrito en la prueba en ``fuentes/`` (fuera del proyecto).
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.unit.gis.test_store import CRS, ImportCase
from tests.unit.workers.test_gis_layer_jobs import CRS_JSON, VERTICAL_JSON, _LayerJobCase

store = import_geoblender("gis.store")
provenance = import_geoblender("gis.provenance")
vector_mod = import_geoblender("gis.vector")
gis_content = import_geoblender("gis.content")
gis_jobs = import_geoblender("gis.jobs")
messages = import_geoblender("gis.messages")
builtin = import_geoblender("core.content.builtin")
base = import_geoblender("core.gpkg.base")
wkb = import_geoblender("core.gpkg.wkb")
readers = import_geoblender("core.content.readers")

LAYER = "fases"
SETTINGS = {"layer": LAYER, "role": "domains"}
WEST, SOUTH = 712_000.1, 4_412_000.3  # ninguna de las dos es exacta en binario


def _ring(*corners: tuple[float, float]) -> np.ndarray:
    """Un anillo cerrado con las esquinas relativas a (WEST, SOUTH)."""
    rows = [(WEST + x, SOUTH + y) for x, y in (*corners, corners[0])]
    return np.array(rows, dtype=np.float64)


# fid de la capa → (tipo, coordenadas, Fase, orden, superficie, foto)
FEATURES: dict[int, tuple[str, Any, Any, Any, Any, Any]] = {
    3: ("POLYGON", [_ring((0.0, 0.0), (50.25, 0.0), (50.25, 40.5), (0.0, 40.5)),
                    _ring((10.0, 10.0), (10.0, 20.0), (20.0, 20.0), (20.0, 10.0))],
        "Fase 1", 1, 1234.5678, b"\x89PNG"),
    7: ("MULTIPOLYGON", [[_ring((50.25, 0.0), (90.0, 0.0), (90.0, 40.5), (50.25, 40.5))],
                         [_ring((100.0, 0.0), (110.0, 0.0), (110.0, 5.0))]],
        "Fase 2", 2, None, None),
    12: ("POLYGON", [_ring((0.0, 40.5), (90.0, 40.5), (45.0, 80.0))], "Fase 3", 3, 0.1, None),
    20: ("POINT", np.array([WEST, SOUTH]), "Punto", 4, 1.0, None),
}
DOMAIN_FIDS = (3, 7, 12)


def write_phases(path: Path) -> None:
    """``fases.gpkg``: la capa ``fases`` (geometría ``GEOMETRY`` en EPSG:25830, en la columna
    ``geometria``) con un campo de texto con mayúscula («Fase»), uno entero (``MEDIUMINT``,
    como los escribe QGIS), uno real y uno binario, y cuatro entidades de número 3, 7, 12 y 20:
    un polígono con un hueco, un multipolígono de dos partes, un triángulo y un punto."""
    conn = sqlite3.connect(path)
    try:
        base.create_base(conn, CRS)
        conn.execute('CREATE TABLE fases (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, '
                     'geometria GEOMETRY, "Fase" TEXT, orden MEDIUMINT, superficie REAL, '
                     'foto BLOB)')
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                     "description, srs_id) VALUES ('fases', 'features', 'Fases', '', 25830)")
        conn.execute("INSERT INTO gpkg_geometry_columns VALUES ('fases', 'geometria', "
                     "'GEOMETRY', 25830, 0, 0)")
        for fid, (kind, coords, *values) in FEATURES.items():
            conn.execute("INSERT INTO fases VALUES (?, ?, ?, ?, ?, ?)",
                         (fid, wkb.encode_geometry(kind, coords, 25830, False), *values))
        conn.commit()
    finally:
        conn.close()


def _polygons(fid: int) -> list[list[np.ndarray]]:
    """Los polígonos (cada uno, sus anillos) de la entidad ``fid`` tal como se escribieron."""
    kind, coords = FEATURES[fid][:2]
    return [coords] if kind == "POLYGON" else coords


def _same_rings(test: unittest.TestCase, got: Any, expected: Any) -> None:
    """Los mismos polígonos y anillos, bit a bit."""
    test.assertEqual([len(polygon) for polygon in got], [len(polygon) for polygon in expected])
    for polygon, wanted in zip(got, expected, strict=True):
        for ring, ring_expected in zip(polygon, wanted, strict=True):
            test.assertEqual(np.asarray(ring).dtype, np.float64)
            test.assertTrue(np.array_equal(np.asarray(ring).view(np.uint64),
                                           np.asarray(ring_expected).view(np.uint64)))


class FieldColumnsTest(unittest.TestCase):
    def test_fields_become_columns_of_the_project_table(self) -> None:
        """RF-011-07 (D-32): cada campo de texto, entero o real de la capa es una columna
        (``TEXT``, ``INTEGER`` o ``DOUBLE``; las fechas, texto; el lógico, entero) con un
        identificador de GeoPackage (en minúsculas, sin tildes; reservado o repetido, con
        «_2»); un campo binario no se importa."""
        fields = (("Fase", "TEXT"), ("orden", "MEDIUMINT"), ("Superficie m²", "REAL"),
                  ("geom", "TEXT(20)"), ("foto", "BLOB"), ("Alta", "DATE"),
                  ("activo", "BOOLEAN"), ("1ª fase", "TEXT"), ("fase_", "DOUBLE"),
                  ("FID", "INTEGER"))
        columns, skipped = vector_mod.field_columns(fields)
        self.assertEqual([(c.field, c.column, c.sql_type) for c in columns], [
            ("Fase", "fase", "TEXT"), ("orden", "orden", "INTEGER"),
            ("Superficie m²", "superficie_m2", "DOUBLE"), ("geom", "geom_2", "TEXT"),
            ("Alta", "alta", "TEXT"), ("activo", "activo", "INTEGER"),
            ("1ª fase", "f_1a_fase", "TEXT"), ("fase_", "fase_2", "DOUBLE"),
            ("FID", "fid_2", "INTEGER")])
        self.assertEqual(skipped, (("foto", "BLOB"),))
        for column in columns:
            base.ColumnDef(column.column, column.sql_type)  # un identificador válido
        self.assertEqual(vector_mod.field_columns(()), ((), ()))


class DomainLayerTest(ImportCase):
    """La capa ``fases`` de ``fuentes/fases.gpkg`` en el proyecto de ``ImportCase``."""

    def setUp(self) -> None:
        super().setUp()
        write_phases(self.sources / "fases.gpkg")

    def read(self) -> tuple[Any, Any, Any]:
        copy = vector_mod.copy_source(self.sources / "fases.gpkg", self.tmp / "copia")
        features = vector_mod.read_layer(copy, LAYER)
        domains, report = vector_mod.domains_from_features(features)
        return features, domains, report

    def test_domain_layer_is_imported_with_its_attributes(self) -> None:
        """RF-011-07, RF-006-12, RF-008-52 (D-32): la capa ``fases`` (un campo de texto «Fase»,
        uno entero y uno real) importada con el papel «dominios» deja su entrada ``vector``
        (``gis.gpkg_layer@1``, su capa y el papel, que es contenido) y lo importado en
        ``gis_dom_fases_<entrada8>``: ``MULTIPOLYGON`` sin Z en el SRS de la capa, una fila por
        polígono o multipolígono con su número de entidad, sus anillos bit a bit y sus atributos
        como columnas (el original, su título en ``gpkg_data_columns``); el punto, rechazado con
        su número, y el campo binario, sin importar con su aviso. El hash de la tabla es el de
        ``table_digest`` con sus columnas; cambiarla desde otra conexión aborta con el nombre de
        la entrada, y ``load_domains`` da cada entidad con su número, sus atributos y sus
        anillos. El GeoPackage no cambia."""
        with assert_source_untouched(self.sources):
            features, domains, report = self.read()
            spec = self.source_spec(gis_content.GPKG_LAYER, "Fases", "fases.gpkg",
                                    settings=SETTINGS)
            handle = self.begin(provenance.IMPORT_VECTOR)
            with store.ResultWriter(self.project, handle) as out:
                out.declare_input(spec)
                self.assertIsNone(out.domains("Fases", domains))
                (record,) = out.commit(message="Capa «fases» importada")
        # Lo leído de la capa.
        self.assertEqual(domains.fids, DOMAIN_FIDS)
        self.assertEqual(len(domains), 3)
        self.assertEqual([(c.field, c.column, c.sql_type) for c in domains.columns],
                         [("Fase", "fase", "TEXT"), ("orden", "orden", "INTEGER"),
                          ("superficie", "superficie", "DOUBLE")])
        self.assertEqual(dict(domains.values), {"fase": ("Fase 1", "Fase 2", "Fase 3"),
                                                "orden": (1, 2, 3),
                                                "superficie": (1234.5678, None, 0.1)})
        for polygons, fid in zip(domains.polygons, DOMAIN_FIDS, strict=True):
            _same_rings(self, polygons, _polygons(fid))
        self.assertEqual([(item.row, item.code) for item in report.rejected],
                         [(20, "gis.feature_role_mismatch")])
        self.assertIn("dominios", report.rejected[0].reason)
        self.assertEqual(report.read, 4)
        self.assertEqual(report.warnings, (messages.render(
            "gis.domain_field_skipped", layer=LAYER, value="foto", kind="BLOB"),))
        self.assertIn("«foto»", report.warnings[0])
        # La entrada y lo importado.
        entry = out.input
        tag = self.tag(entry)
        self.assertEqual((entry.kind, entry.reader, entry.layer, dict(entry.settings),
                          entry.content_settings_keys),
                         ("vector", "gis.gpkg_layer@1", LAYER, SETTINGS, ("role",)))
        locator = f"gis_dom_fases_{tag}"
        self.assertEqual(
            (record.name, record.kind, record.locator, record.reader, record.immutable,
             record.input_uid, record.crs_epsg, record.operation_uid),
            ("gis_dom_fases", "vector", locator, "core.gpkg_layer@1", True, entry.uid, 25830,
             handle.uid))
        self.assertEqual(self.query("SELECT role, item_uid FROM gb_operation_io WHERE "
                                    "operation_uid = ? AND direction = 'out' AND item_kind = "
                                    "'dataset'", handle.uid), [("domains", record.uid)])
        self.assertEqual(self.query(
            "SELECT geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns WHERE "
            "table_name = ?", locator), [("MULTIPOLYGON", 25830, 0, 0)])
        self.assertEqual([row[1:3] for row in self.query(f'PRAGMA table_info("{locator}")')],
                         [("fid", "INTEGER"), ("geom", "MULTIPOLYGON"), ("fase", "TEXT"),
                          ("orden", "INTEGER"), ("superficie", "DOUBLE")])
        (identifier,) = self.query("SELECT identifier FROM gpkg_contents WHERE table_name = ?",
                                   locator)
        self.assertEqual(identifier[0], f"Dominios: Fases ({locator})")
        self.assertEqual(self.query("SELECT column_name, name FROM gpkg_data_columns WHERE "
                                    "table_name = ?", locator), [("fase", "Fase")])
        rows = self.query(f'SELECT fid, geom, fase, orden, superficie FROM "{locator}" '
                          "ORDER BY fid")
        self.assertEqual([(row[0], *row[2:]) for row in rows],
                         [(3, "Fase 1", 1, 1234.5678), (7, "Fase 2", 2, None),
                          (12, "Fase 3", 3, 0.1)])
        for row in rows:
            geometry = wkb.decode_geometry(row[1])
            self.assertEqual((geometry.geometry_type, geometry.has_z, geometry.srs_id),
                             ("MULTIPOLYGON", False, 25830))
            _same_rings(self, geometry.coords, _polygons(row[0]))
        digest = store.table_digest(provenance.DOMAINS, store.domain_rows(domains, CRS.epsg),
                                    CRS, columns=domains.column_defs)
        self.assertEqual(record.content_sha256, digest.content_sha256)
        self.assertEqual(record.content_sha256, self.read_hash(
            builtin.GPKG_LAYER, "vector", self.project.database_path, {"layer": locator}))
        self.assert_protected(locator, "Fases")
        # Lo importado, leído de vuelta.
        loaded = store.load_domains(self.project, "gis_dom_fases")
        self.assertEqual([item.fid for item in loaded], list(DOMAIN_FIDS))
        self.assertEqual([dict(item.attributes) for item in loaded],
                         [{"fase": "Fase 1", "orden": 1, "superficie": 1234.5678},
                          {"fase": "Fase 2", "orden": 2, "superficie": None},
                          {"fase": "Fase 3", "orden": 3, "superficie": 0.1}])
        for item in loaded:
            _same_rings(self, item.polygons, _polygons(item.fid))
            self.assertEqual(len(item.rings), sum(len(p) for p in _polygons(item.fid)))
        self.assertEqual([item.fid for item in store.load_domains(self.project, record)],
                         list(DOMAIN_FIDS))
        # T23 (RF-011-07): los campos que pueden nombrar los dominios, con su título.
        self.assertEqual(store.domain_fields(self.project, "gis_dom_fases"),
                         (("fase", "Fase"), ("orden", "orden"), ("superficie", "superficie")))
        with self.assertRaises(messages.GisError) as caught:
            store.load_domains(self.project, "gis_dom_otra")
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        self.assertEqual(features.report.read, 4)
        self.assert_no_absolute_paths()


class DomainJobTest(_LayerJobCase):
    def test_job_reads_the_domain_layer_with_the_digest_of_its_table(self) -> None:
        """RF-011-07, RF-006-12, RF-006-26 (D-32): ``gis_import_vector`` con el papel
        ``domains`` deja ``domains.npz`` con cada entidad (su número, sus anillos bit a bit y
        sus atributos) y el hash de la tabla que será lo importado (``table_digest`` con sus
        columnas, T50), y su informe dice el punto rechazado y el campo binario sin
        importar."""
        source = self.base / "capas" / "fases.gpkg"
        source.parent.mkdir()
        write_phases(source)
        params = {"reader": gis_content.GPKG_LAYER.id, "name": "Fases", "settings": SETTINGS,
                  "crs": None, "vertical": VERTICAL_JSON, "size": source.stat().st_size}
        with assert_source_untouched(source.parent):
            summary, ctx, folder = self.run_job(gis_jobs.IMPORT_VECTOR, params,
                                                paths={gis_jobs.path_name("main"): source})
        self.assertEqual((summary["crs"], summary["role"], summary["read"], summary["count"],
                          summary["rejected"]), (CRS_JSON, "domains", 4, 3, 1))
        copy = vector_mod.copy_source(source, self.base / "copia")
        expected, _report = vector_mod.domains_from_features(vector_mod.read_layer(copy, LAYER))
        got = gis_jobs.read_domains(self.output(ctx, folder, "domains"))
        self.assertEqual((got.fids, got.columns, dict(got.values)),
                         (expected.fids, expected.columns, dict(expected.values)))
        for polygons, wanted in zip(got.polygons, expected.polygons, strict=True):
            _same_rings(self, polygons, wanted)
        self.assertEqual(
            summary["outputs"]["domains"]["digest"],
            gis_jobs.digest_json(store.table_digest(
                provenance.DOMAINS, store.domain_rows(got, CRS.epsg), CRS,
                columns=got.column_defs)))
        report = json.loads(self.output(ctx, folder, "report").read_text("utf-8"))
        self.assertEqual([item["row"] for item in report["rejected"]], [20])
        self.assertEqual(len(report["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
