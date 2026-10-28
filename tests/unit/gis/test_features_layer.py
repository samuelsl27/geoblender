# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de entidades (spec 012, T07; RF-012-01, RF-012-08, RF-012-26; plan 012 D-27;
RF-006-05, RF-006-12, RF-008-52).

Una capa de puntos, de líneas o de polígonos de un GeoPackage se importa con el papel
«entidades» de la importación de capas de la 006 (``gis.import_vector``), como los «dominios»
de la 011: de ahí salen las restricciones (RF-012-01), las infraestructuras de la búsqueda de
intocables (RF-012-08) y las marcas del cliente (RF-012-26).

- ``gis.vector.features_from_layer``: de cada entidad de la geometría de la capa (puntos, líneas
  o polígonos, simples o múltiples), su número, sus partes en planta tal como llegan y sus
  atributos de texto, enteros y reales (la fecha, como texto); otra geometría se rechaza con su
  número y un campo binario no se importa (con su aviso);
- ``gis.vector.transform_features``: las mismas entidades en otro CRS (la transformación de la
  006, ``gis.crs.transformation_for``), con sus atributos;
- ``gis.store.ResultWriter.features``: lo importado en ``gis_fea_<nombre>_<entrada8>``
  (``MULTIPOINT``, ``MULTILINESTRING`` o ``MULTIPOLYGON`` sin Z en el CRS del proyecto, con su
  número de entidad y los atributos como columnas), inmutable con su entrada;
- ``gis.store.load_features``: un dato ``gis_fea_`` con su geometría, y cada entidad con su
  número, sus atributos y sus partes absolutas;
- el trabajo ``gis_import_vector`` con el papel ``features``: ``features.npz`` con las
  coordenadas de la capa y el hash de la tabla que será lo importado o, si la capa está en otro
  CRS que el del proyecto, la marca ``reprojects`` (la orden la transforma al incorporarla).

Datos sintéticos: ``entidades.gpkg`` (EPSG:25830) y ``entidades_ed50.gpkg`` (EPSG:23030),
escritos en la prueba en ``fuentes/`` (fuera del proyecto).
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
from tests.unit.gis.test_store import CRS, VERTICAL, ImportCase
from tests.unit.workers.test_gis_layer_jobs import CRS_JSON, VERTICAL_JSON, _LayerJobCase

store = import_geoblender("gis.store")
provenance = import_geoblender("gis.provenance")
vector_mod = import_geoblender("gis.vector")
gis_crs = import_geoblender("gis.crs")
gis_content = import_geoblender("gis.content")
gis_jobs = import_geoblender("gis.jobs")
messages = import_geoblender("gis.messages")
builtin = import_geoblender("core.content.builtin")
base = import_geoblender("core.gpkg.base")
wkb = import_geoblender("core.gpkg.wkb")
georef = import_geoblender("core.georef")

ED50 = georef.load_catalog().horizontal(23030)
WEST, SOUTH = 699_700.1, 4_399_700.3  # ninguna de las dos es exacta en binario
FIELDS: tuple[tuple[str, str], ...] = (
    ("Nombre", "TEXT"), ("orden", "MEDIUMINT"), ("cota", "REAL"), ("fecha", "DATE"),
    ("foto", "BLOB"))
COLUMNS = [("Nombre", "nombre", "TEXT"), ("orden", "orden", "INTEGER"),
           ("cota", "cota", "DOUBLE"), ("fecha", "fecha", "TEXT")]
POINTS, LINES, POLYGONS = "torres", "lineas", "zonas"


def _xy(*pairs: tuple[float, float]) -> np.ndarray:
    """Vértices con las coordenadas relativas a (WEST, SOUTH)."""
    return np.array([(WEST + x, SOUTH + y) for x, y in pairs], dtype=np.float64)


def _ring(*corners: tuple[float, float]) -> np.ndarray:
    """Un anillo cerrado con las esquinas relativas a (WEST, SOUTH)."""
    return _xy(*corners, corners[0])


# capa → (tipo de la capa, {fid: (tipo, coordenadas, Nombre, orden, cota, fecha, foto)})
LAYERS: dict[str, tuple[str, dict[int, tuple[Any, ...]]]] = {
    POINTS: ("GEOMETRY", {
        2: ("POINT", _xy((10.25, 20.5))[0], "Torre 1", 1, 812.25, "2025-01-20", None),
        4: ("MULTIPOINT", _xy((30.0, 40.125), (31.5, 41.75)), "Torres 2 y 3", 2, None,
            "2024-11-02", None),
        9: ("LINESTRING", _xy((0.0, 0.0), (5.0, 5.0)), "Una línea", 3, 1.0, None, None),
        11: ("POINT", _xy((60.0, 70.0))[0], None, None, 0.1, None, None),
    }),
    LINES: ("GEOMETRY", {
        1: ("LINESTRING", _xy((0.0, 0.0), (50.5, 10.25), (100.0, 0.0)), "Línea eléctrica",
            7, 15.5, "2023-05-30", b"\x89PNG"),
        3: ("MULTILINESTRING", [_xy((0.0, 50.0), (10.0, 60.0)),
                                _xy((20.0, 50.0), (30.0, 60.0), (40.0, 50.0))],
            "Camino", 8, None, None, None),
    }),
    POLYGONS: ("MULTIPOLYGON", {
        5: ("POLYGON", [_ring((0.0, 0.0), (50.25, 0.0), (50.25, 40.5), (0.0, 40.5)),
                        _ring((10.0, 10.0), (10.0, 20.0), (20.0, 20.0), (20.0, 10.0))],
            "Cementerio", 1, 900.0, "2025-01-20", None),
        6: ("MULTIPOLYGON", [[_ring((60.0, 0.0), (90.0, 0.0), (90.0, 40.5))],
                             [_ring((100.0, 0.0), (110.0, 0.0), (110.0, 5.0))]],
            "Arroyo", 2, None, "2025-02-01", None),
    }),
}
KINDS = {POINTS: "point", LINES: "line", POLYGONS: "polygon"}
TABLE_TYPES = {POINTS: "MULTIPOINT", LINES: "MULTILINESTRING", POLYGONS: "MULTIPOLYGON"}
KEPT = {POINTS: (2, 4, 11), LINES: (1, 3), POLYGONS: (5, 6)}


def write_features(path: Path, crs: Any = CRS) -> None:
    """El GeoPackage ``path`` (en ``crs``) con las tres capas de :data:`LAYERS`, como las de
    QGIS: ``fid`` entero, ``geom`` 2D y los campos de :data:`FIELDS` (texto, entero
    ``MEDIUMINT``, real, fecha y binario)."""
    conn = sqlite3.connect(path)
    try:
        base.create_base(conn, crs)
        columns = "".join(f', "{name}" {kind}' for name, kind in FIELDS)
        for layer, (geometry_type, features) in LAYERS.items():
            conn.execute(f'CREATE TABLE "{layer}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT '
                         f'NULL, geom {geometry_type}{columns})')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                         (layer, layer, crs.epsg))
            conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)",
                         (layer, geometry_type, crs.epsg))
            for fid, (kind, coords, *values) in features.items():
                conn.execute(f'INSERT INTO "{layer}" VALUES (?, ?, ?, ?, ?, ?, ?)',
                             (fid, wkb.encode_geometry(kind, coords, crs.epsg, False), *values))
        conn.commit()
    finally:
        conn.close()


def expected_parts(layer: str, fid: int) -> list[list[np.ndarray]]:
    """Las partes de la entidad ``fid`` tal como se escribieron: de cada parte, sus anillos
    (polígono), su camino (línea) o su punto ``(1, 2)``."""
    kind, coords = LAYERS[layer][1][fid][:2]
    if kind == "POINT":
        return [[np.asarray(coords)[None, :]]]
    if kind == "MULTIPOINT":
        return [[point[None, :]] for point in coords]
    if kind == "LINESTRING":
        return [[coords]]
    if kind == "MULTILINESTRING":
        return [[path] for path in coords]
    if kind == "POLYGON":
        return [list(coords)]
    return [list(polygon) for polygon in coords]


def expected_values(layer: str) -> dict[str, tuple[Any, ...]]:
    """Los atributos de las entidades que se importan, por columna (sin la foto)."""
    rows = [LAYERS[layer][1][fid][2:6] for fid in KEPT[layer]]
    return {column: tuple(row[index] for row in rows)
            for index, (_field, column, _kind) in enumerate(COLUMNS)}


def _same_parts(test: unittest.TestCase, got: Any, expected: Any) -> None:
    """Las mismas partes y coordenadas, bit a bit, en float64 ``(k, 2)``."""
    test.assertEqual([len(part) for part in got], [len(part) for part in expected])
    for part, wanted in zip(got, expected, strict=True):
        for array, array_expected in zip(part, wanted, strict=True):
            array = np.asarray(array)
            test.assertEqual((array.dtype, array.ndim, array.shape[-1]), (np.float64, 2, 2))
            test.assertTrue(np.array_equal(array.view(np.uint64),
                                           np.asarray(array_expected).view(np.uint64)))


def _transform() -> Any:
    """La transformación de la 006 de ED50 (EPSG:23030) al CRS del proyecto (el servicio de
    CRS de verdad, pyproj con la rejilla del IGN), en planta: la misma referencia vertical a
    los dos lados."""
    found = gis_crs.transformation_for(gis_crs.Declaration("ED50", ED50, VERTICAL), CRS,
                                       VERTICAL)
    assert found is not None
    return found


class FeaturesFromLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = self.enterContext(_tmp())
        self.source = self.tmp / "fuentes" / "entidades.gpkg"
        self.source.parent.mkdir()
        write_features(self.source)

    def test_each_geometry_with_its_attributes(self) -> None:
        """RF-012-01, RF-012-08, RF-012-26 (D-27): una capa de puntos, una de líneas y una de
        polígonos dan su geometría (``point``, ``line``, ``polygon``; la de la capa o, si es
        ``GEOMETRY``, la de su primera entidad), cada entidad con su número, sus partes en
        planta bit a bit (un multipunto, un punto por parte) y sus atributos de texto, enteros,
        reales y la fecha como texto; la entidad de otra geometría se rechaza con su número y
        el campo binario no se importa, con su aviso. La capa no cambia."""
        with assert_source_untouched(self.source.parent):
            copy = vector_mod.copy_source(self.source, self.tmp / "copia")
            for layer in LAYERS:
                with self.subTest(capa=layer):
                    features = vector_mod.read_layer(copy, layer)
                    found, report = vector_mod.features_from_layer(features)
                    self.assertEqual((found.kind, found.geometry_type, found.fids),
                                     (KINDS[layer], TABLE_TYPES[layer], KEPT[layer]))
                    self.assertEqual(len(found), len(KEPT[layer]))
                    self.assertEqual([(c.field, c.column, c.sql_type) for c in found.columns],
                                     COLUMNS)
                    self.assertEqual(dict(found.values), expected_values(layer))
                    self.assertEqual(found.titles, {"nombre": "Nombre"})
                    for parts, fid in zip(found.parts, KEPT[layer], strict=True):
                        _same_parts(self, parts, expected_parts(layer, fid))
                    rejected = [(item.row, item.code) for item in report.rejected]
                    self.assertEqual(rejected, [(9, "gis.feature_role_mismatch")]
                                     if layer == POINTS else [])
                    if rejected:
                        self.assertIn("entidades", report.rejected[0].reason)
                    self.assertEqual(report.warnings, (messages.render(
                        "gis.feature_field_skipped", layer=layer, value="foto",
                        kind="BLOB"),))
                    self.assertEqual(report.read, len(LAYERS[layer][1]))
                    feature = found.feature(0)
                    self.assertEqual((feature.fid, dict(feature.attributes)),
                                     (KEPT[layer][0], {column: values[0] for column, values
                                                       in expected_values(layer).items()}))
                    self.assertIs(feature.parts, found.parts[0])

    def test_transform_moves_every_vertex_and_keeps_the_rest(self) -> None:
        """RF-006-05 (D-27): ``transform_features`` lleva cada vértice con la transformación
        de la 006 (la X y la Y; la cota, cero, no cuenta) y conserva la geometría, los números,
        las partes y los atributos; la capa leída no cambia."""
        copy = vector_mod.copy_source(self.source, self.tmp / "copia")
        found, _report = vector_mod.features_from_layer(vector_mod.read_layer(copy, POLYGONS))
        before = [np.array(array) for part in found.parts for ring in part for array in ring]
        transform = _transform()
        moved = vector_mod.transform_features(found, transform)
        self.assertEqual((moved.kind, moved.fids, moved.columns, dict(moved.values)),
                         (found.kind, found.fids, found.columns, dict(found.values)))
        for parts, parts_before in zip(moved.parts, found.parts, strict=True):
            for part, part_before in zip(parts, parts_before, strict=True):
                for ring, ring_before in zip(part, part_before, strict=True):
                    xyz = np.column_stack([ring_before, np.zeros(len(ring_before))])
                    self.assertTrue(np.array_equal(ring, transform.apply(xyz)[:, :2]))
                    shift = ring - ring_before
                    self.assertTrue(np.all((shift[:, 0] < -100.0) & (shift[:, 0] > -120.0)))
                    self.assertTrue(np.all((shift[:, 1] < -195.0) & (shift[:, 1] > -220.0)))
        after = [array for part in found.parts for ring in part for array in ring]
        for array, kept in zip(after, before, strict=True):
            self.assertTrue(np.array_equal(array, kept))


class FeatureStoreTest(ImportCase):
    """Las capas de ``fuentes/entidades.gpkg`` en el proyecto de ``ImportCase``."""

    def setUp(self) -> None:
        super().setUp()
        write_features(self.sources / "entidades.gpkg")
        write_features(self.sources / "entidades_ed50.gpkg", ED50)

    def _import(self, file: str, layer: str, name: str, *, crs: Any = CRS,
                transform: Any = None) -> tuple[Any, Any, Any]:
        copy = vector_mod.copy_source(self.sources / file, self.tmp / "copia" / name)
        found, _report = vector_mod.features_from_layer(vector_mod.read_layer(copy, layer))
        if transform is not None:
            found = vector_mod.transform_features(found, transform)
        settings = {"layer": layer, "role": "features"}
        spec = self.source_spec(gis_content.GPKG_LAYER, name, file, crs=crs, settings=settings)
        handle = self.begin(provenance.IMPORT_VECTOR)
        with store.ResultWriter(self.project, handle) as out:
            out.declare_input(spec)
            self.assertIsNone(out.features(name, found))
            (record,) = out.commit(message=f"Capa «{layer}» importada")
        return found, out.input, record

    def test_three_layers_are_imported_with_their_attributes(self) -> None:
        """RF-012-01, RF-012-08, RF-012-26, RF-006-12, RF-008-52 (D-27): cada capa importada con
        el papel «entidades» deja su entrada (``gis.gpkg_layer@1``, su capa y el papel) y lo
        importado en ``gis_fea_<nombre>_<entrada8>``: ``MULTIPOINT``, ``MULTILINESTRING`` o
        ``MULTIPOLYGON`` sin Z en el CRS del proyecto, una fila por entidad con su número, sus
        partes bit a bit y sus atributos como columnas (el original, su título); su hash, el de
        ``table_digest``; inmutable, y ``load_features`` da su geometría y cada entidad con su
        número, sus atributos y sus partes absolutas. El GeoPackage no cambia."""
        with assert_source_untouched(self.sources):
            for layer in LAYERS:
                with self.subTest(capa=layer):
                    name = f"Entidades {layer}"
                    found, entry, record = self._import("entidades.gpkg", layer, name)
                    locator = f"gis_fea_entidades_{layer}_{self.tag(entry)}"
                    self.assertEqual(
                        (record.name, record.kind, record.locator, record.reader,
                         record.immutable, record.input_uid, record.crs_epsg),
                        (f"gis_fea_entidades_{layer}", "vector", locator, "core.gpkg_layer@1",
                         True, entry.uid, 25830))
                    self.assertEqual((entry.reader, dict(entry.settings),
                                      entry.content_settings_keys),
                                     ("gis.gpkg_layer@1", {"layer": layer, "role": "features"},
                                      ("role",)))
                    self.assertEqual(self.query(
                        "SELECT geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns "
                        "WHERE table_name = ?", locator), [(TABLE_TYPES[layer], 25830, 0, 0)])
                    self.assertEqual(
                        [row[1:3] for row in self.query(f'PRAGMA table_info("{locator}")')],
                        [("fid", "INTEGER"), ("geom", TABLE_TYPES[layer]), ("nombre", "TEXT"),
                         ("orden", "INTEGER"), ("cota", "DOUBLE"), ("fecha", "TEXT")])
                    (identifier,) = self.query(
                        "SELECT identifier FROM gpkg_contents WHERE table_name = ?", locator)
                    self.assertEqual(identifier[0], f"Entidades: {name} ({locator})")
                    self.assertEqual(self.query(
                        "SELECT column_name, name FROM gpkg_data_columns WHERE table_name = ?",
                        locator), [("nombre", "Nombre")])
                    digest = store.table_digest(
                        provenance.FEATURES, store.feature_rows(found, CRS.epsg), CRS,
                        columns=found.column_defs, geometry_type=found.geometry_type)
                    self.assertEqual(record.content_sha256, digest.content_sha256)
                    self.assertEqual(record.content_sha256, self.read_hash(
                        builtin.GPKG_LAYER, "vector", self.project.database_path,
                        {"layer": locator}))
                    self.assert_protected(locator, name)
                    self.assertEqual(store.dataset_references(self.project, record),
                                     (CRS, VERTICAL))
                    loaded = store.load_features(self.project, record.name)
                    self.assertEqual((loaded.kind, loaded.geometry_type, loaded.fids),
                                     (KINDS[layer], TABLE_TYPES[layer], KEPT[layer]))
                    self.assertEqual([(c.field, c.column, c.sql_type) for c in loaded.columns],
                                     COLUMNS)
                    self.assertEqual(dict(loaded.values), expected_values(layer))
                    for index, fid in enumerate(KEPT[layer]):
                        feature = loaded.feature(index)
                        self.assertEqual(feature.fid, fid)
                        _same_parts(self, feature.parts, expected_parts(layer, fid))
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE name LIKE "
                                    "'gis_fea_%' AND immutable = 1"), [(3,)])
        self.assert_no_absolute_paths()

    def test_ed50_layer_is_stored_in_the_project_crs(self) -> None:
        """RF-006-05, RF-012-01 (D-27): la capa en ED50, transformada con la 006, queda en el
        CRS del proyecto (la tabla, su dato y sus referencias) aunque su entrada declare
        EPSG:23030; ``load_features`` da las coordenadas transformadas, bit a bit."""
        with assert_source_untouched(self.sources):
            found, entry, record = self._import("entidades_ed50.gpkg", POLYGONS, "Zonas ED50",
                                                crs=ED50, transform=_transform())
        self.assertEqual(dict(entry.crs_h), {"epsg": 23030})
        self.assertEqual(record.crs_epsg, 25830)
        self.assertEqual(self.query("SELECT srs_id FROM gpkg_geometry_columns WHERE "
                                    "table_name = ?", record.locator), [(25830,)])
        self.assertEqual(store.dataset_references(self.project, record), (CRS, VERTICAL))
        store.require_project_references(self.project, record)
        loaded = store.load_features(self.project, record)
        self.assertEqual(loaded.fids, KEPT[POLYGONS])
        for parts, wanted in zip(loaded.parts, found.parts, strict=True):
            _same_parts(self, parts, wanted)
        with self.assertRaises(messages.GisError) as caught:
            store.load_features(self.project, "gis_fea_otra")
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")


class FeatureJobTest(_LayerJobCase):
    def _run(self, file: str, crs: Any) -> tuple[Path, dict, Any, Any]:
        source = self.base / "capas" / file
        source.parent.mkdir(exist_ok=True)
        write_features(source, crs)
        settings = {"layer": POLYGONS, "role": "features"}
        params = {"reader": gis_content.GPKG_LAYER.id, "name": "Zonas", "settings": settings,
                  "crs": None, "vertical": VERTICAL_JSON, "size": source.stat().st_size,
                  "target_crs": CRS_JSON}
        with assert_source_untouched(source.parent):
            summary, ctx, folder = self.run_job(gis_jobs.IMPORT_VECTOR, params,
                                                paths={gis_jobs.path_name("main"): source})
        return source, summary, ctx, folder

    def _check(self, source: Path, got: Any) -> None:
        copy = vector_mod.copy_source(source, self.base / "copia" / source.stem)
        expected, _report = vector_mod.features_from_layer(vector_mod.read_layer(copy,
                                                                                 POLYGONS))
        self.assertEqual((got.kind, got.fids, got.columns, dict(got.values)),
                         (expected.kind, expected.fids, expected.columns,
                          dict(expected.values)))
        for parts, wanted in zip(got.parts, expected.parts, strict=True):
            _same_parts(self, parts, wanted)

    def test_job_reads_the_layer_with_the_digest_of_its_table(self) -> None:
        """RF-012-01, RF-006-12, RF-006-26 (D-27): ``gis_import_vector`` con el papel
        ``features`` y la capa en el CRS del proyecto (``target_crs``) deja ``features.npz``
        con cada entidad (su número, sus partes bit a bit y sus atributos) y el hash de la tabla
        que será lo importado (``table_digest`` con sus columnas y su tipo, T50); el informe
        dice el campo binario sin importar."""
        source, summary, ctx, folder = self._run("entidades.gpkg", CRS)
        self.assertEqual((summary["crs"], summary["role"], summary["read"], summary["count"],
                          summary["rejected"], summary["reprojects"]),
                         (CRS_JSON, "features", 2, 2, 0, False))
        got = gis_jobs.read_features(self.output(ctx, folder, "features"))
        self._check(source, got)
        self.assertEqual(summary["outputs"]["features"]["digest"], gis_jobs.digest_json(
            store.table_digest(provenance.FEATURES, store.feature_rows(got, CRS.epsg), CRS,
                               columns=got.column_defs, geometry_type=got.geometry_type)))
        report = json.loads(self.output(ctx, folder, "report").read_text("utf-8"))
        self.assertEqual(len(report["warnings"]), 1)

    def test_job_marks_an_ed50_layer_to_transform(self) -> None:
        """RF-006-05, RF-012-01 (D-27): la misma capa en ED50 (el CRS, el de la capa) sale tal
        cual, con ``reprojects`` y sin el hash de su tabla: la orden la transforma con la 006 al
        incorporarla (``transform_features``) y la hashea su registro."""
        source, summary, ctx, folder = self._run("entidades_ed50.gpkg", ED50)
        self.assertEqual((summary["crs"], summary["count"], summary["reprojects"]),
                         ({"epsg": 23030}, 2, True))
        self.assertNotIn("digest", summary["outputs"]["features"])
        self._check(source, gis_jobs.read_features(self.output(ctx, folder, "features")))


def _tmp() -> Any:
    from tests.support.jobs_fixtures import jobs_tmp

    return jobs_tmp(prefix="gb127-")


if __name__ == "__main__":
    unittest.main()
