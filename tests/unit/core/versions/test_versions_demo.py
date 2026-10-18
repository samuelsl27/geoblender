# SPDX-License-Identifier: GPL-3.0-or-later
"""La demostración de versiones y su proyecto (spec 009, T08; plan 009 §7.1; base de las pruebas
de A3 a A11 y del hito H1).

``tests/support/versions_demo.py`` amplía la demostración de la 008 (``provenance_demo``) con
los tipos de **versión** del código ``demo``, como los declarará un módulo de Geoblender (plan
§5.3.3):

- ``demo.pit``: lee el límite importado (un dato del proyecto) y la altura de banco
  ``demo.bench_height`` (parámetro de versión, D-19) y escribe, en su versión, una rejilla
  GeoTIFF del fondo del hueco, su malla npz y la tabla de sus bancos (las ubicaciones, con el
  código de la versión: ``rasters/demo_pit_grid_v01.tif``, D-34); se repite sola y se
  reproduce;
- ``demo.pit_volume``: lee la rejilla y da la cifra ``demo.pit_volume`` (m³), con
  ``figure_tolerance`` relativa 1e-12;
- ``demo.sketch``: la edición a mano de una capa de rampas editable en QGIS (no se repite ni se
  reproduce: queda «revisar a mano» si cambia lo que leyó);
- ``demo.design_from_parent``: lee lo congelado de la versión padre (``Use.frozen``, D-27).

``tests/support/versions_fixtures.py`` da el proyecto (la cadena de la demostración de la 008
sobre ``Limites_v1``, V01 y V02 en BORRADOR) y las ayudas de las pruebas que lo usan: congelar
por SQL, cambiar de estado, alterar un fichero, la lista de ficheros con sus huellas y el
contador de cambios de la base. Ninguno de los dos se empaqueta.
"""

from __future__ import annotations

import dataclasses
import math
import sqlite3
import unittest
from typing import Any
from unittest import mock

import numpy as np

from tests.support import provenance_demo as demo_support
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.demo_project import process_state
from tests.support.package import import_geoblender
from tests.support.provenance_readers import registered as readers_registered
from tests.support.repo import EXT, ROOT

contract = import_geoblender("core.provenance.contract")
lineage = import_geoblender("core.provenance.lineage")
stale = import_geoblender("core.provenance.stale")
params = import_geoblender("core.params")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
registry = import_geoblender("core.datasets.registry")
versions_read = import_geoblender("core.versions.read")
versions_model = import_geoblender("core.versions.model")
geotiff_reader = import_geoblender("gis.geotiff.reader")
gis_readers = import_geoblender("gis.content")
schema = import_geoblender("core.catalog.schema")
i18n = import_geoblender("core.i18n")

VERSION_TYPES = {
    # tipo: (se repite sola, se reproduce)
    "demo.pit": (True, True),
    "demo.pit_volume": (True, True),
    "demo.sketch": (False, False),
    "demo.design_from_parent": (True, True),
}
BENCH_REASON = "Banco de 12 m del diseño de V01"
CELL_M2 = 100.0
"""Las celdas de la rejilla del hueco: 10 × 10 m."""


def expected_benches(bench_m: float, benches: int = 3, berm_m: float = 25.0,
                     top_z: float = 500.0) -> list[tuple[int, float, float, float]]:
    """Los bancos del hueco sobre ``Limites_v1`` (500 × 350 m desde (700 000,25; 4 400 000,5),
    celdas de 10 m), contados aquí celda a celda: la celda de centro a ``d`` m del borde baja
    ``min(benches, ⌊d / berm_m⌋)`` bancos; el banco ``b`` es el área de las que bajan al menos
    ``b`` (banco, cota de su fondo, área en m² y volumen en m³)."""
    depth: dict[int, int] = {}
    for column in range(50):
        for row in range(35):
            x, y = 5.0 + 10.0 * column, 5.0 + 10.0 * row
            edge = min(x, 500.0 - x, y, 350.0 - y)
            down = min(benches, int(edge // berm_m))
            for level in range(1, down + 1):
                depth[level] = depth.get(level, 0) + 1
    return [(level, top_z - level * bench_m, depth[level] * CELL_M2,
             bench_m * depth[level] * CELL_M2) for level in range(1, benches + 1)]


class VersionsDemoRegistrationTest(unittest.TestCase):
    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-009-05, RF-009-11, RF-009-24 (plan §5.3.3 y §7.1): la demostración de versiones
        registra la de la 008 y sus cuatro tipos de versión (``scope="version"``; los que se
        repiten, con su recálculo; los que se reproducen, con su función de reproducir y
        ``demo.pit_volume`` con su tolerancia relativa 1e-12; la edición a mano, sin ninguna),
        su cifra ``demo.pit_volume`` en m³, su parámetro de versión ``demo.bench_height`` (m) y
        el lector de GeoTIFF de ``gis`` si no estaba; al quitarla, todo queda como estaba (y lo
        que ya estaba registrado, también)."""
        before = process_state()
        demo = vdemo.VersionsDemo()
        demo.register()
        try:
            self.assertIsInstance(demo, demo_support.Demo)
            for op_type, (repeatable, reproducible) in VERSION_TYPES.items():
                with self.subTest(op_type=op_type):
                    definition = contract.OPERATIONS[op_type]
                    self.assertEqual((definition.scope, definition.repeatable,
                                      definition.recompute is not None,
                                      definition.reproduce is not None),
                                     ("version", repeatable, repeatable, reproducible))
            self.assertEqual(contract.OPERATIONS["demo.pit_volume"].figure_tolerance,
                             contract.Tolerance(relative=1e-12))
            for op_type in ("demo.pit", "demo.sketch", "demo.design_from_parent"):
                self.assertIsNone(contract.OPERATIONS[op_type].figure_tolerance)
            for op_type in demo_support.OPERATION_TYPES:  # los de la 008, de proyecto
                self.assertEqual(contract.OPERATIONS[op_type].scope, "project")
            figure = contract.FIGURES["demo.pit_volume"]
            self.assertEqual((figure.unit, figure.label_msgid), ("m3", "Demo pit volume"))
            bench = params.DEFINITIONS["demo.bench_height"]
            self.assertEqual((bench.scope, bench.unit, bench.default, str(bench.kind)),
                             ("version", "m", 10.0, "HIPÓTESIS"))
            self.assertEqual(params.DEFINITIONS["demo.production"].scope, "project")
            self.assertIs(readers.READERS[gis_readers.GEOTIFF.id], gis_readers.GEOTIFF)
            self.assertIs(readers.READERS[builtin.NPZ_MESH.id], builtin.NPZ_MESH)
            self.assertEqual(i18n.translate("es", "Demo pit volume"),
                             "Volumen del hueco (demostración)")
            self.assertEqual(i18n.translate("es", "Demo boundary area"),
                             "Área del límite (demostración)")
            with self.assertRaises(RuntimeError):
                demo.register()
        finally:
            demo.unregister()
        self.assertEqual(process_state(), before)
        demo.unregister()  # idempotente
        self.assertEqual(process_state(), before)

        # Con el lector de GeoTIFF ya registrado (por bl), no lo quita al irse.
        with readers_registered(gis_readers.GEOTIFF):
            held = process_state()
            with vdemo.VersionsDemo().registered():
                self.assertIs(readers.READERS[gis_readers.GEOTIFF.id], gis_readers.GEOTIFF)
            self.assertEqual(process_state(), held)
        self.assertEqual(process_state(), before)

    def test_failed_registration_leaves_nothing(self) -> None:
        """RF-008-17 (plan §7.1): si falla a medias el registro de un tipo de versión, la
        demostración quita lo que ya había registrado (también lo de la 008) y deja pasar el
        error."""
        before = process_state()
        original = contract.register_operation

        def fail_late(definition: Any) -> None:
            if definition.op_type == "demo.design_from_parent":
                raise ValueError("fallo de prueba")
            original(definition)

        with mock.patch.object(contract, "register_operation", side_effect=fail_late), \
                self.assertRaisesRegex(ValueError, "fallo de prueba"):
            vdemo.VersionsDemo().register()
        self.assertEqual(process_state(), before)

    def test_demo_stays_out_of_the_package(self) -> None:
        """RF-001-02 (plan §7.1): la demostración y su proyecto están fuera de ``geoblender/``
        (lo único que se empaqueta) y ``demo`` sigue sin ser un código de módulo."""
        package = (ROOT / EXT).resolve()
        for module in (vdemo, fixtures):
            path = ROOT / "tests" / "support" / f"{module.__name__.rpartition('.')[2]}.py"
            self.assertTrue(path.is_file(), path)
            self.assertFalse(path.resolve().is_relative_to(package), path)
        self.assertNotIn("demo", schema.MODULE_CODES)


class VersionsChainTest(fixtures.VersionsProjectCase):
    """El proyecto de la demostración: la cadena de la 008, V01 y V02 en BORRADOR."""

    def own_bench(self, version: str, value: float) -> Any:
        """``demo.bench_height`` propio de ``version`` (``value`` m)."""
        return self.write(lambda conn: self.store.create(
            conn, vdemo.BENCH_HEIGHT, value, kind="ADOPTADO", source="Diseño de la versión",
            source_kind="document", decided_by="Samuel (IMGA)", reason=BENCH_REASON,
            version=version))

    def test_project_of_the_fixture(self) -> None:
        """RF-009-01 (plan §7.1): el proyecto de las pruebas tiene la cadena de la
        demostración de la 008 hecha (el límite importado, sus seis operaciones de proyecto y
        sus cifras) y las versiones V01 y V02 en BORRADOR con su r1 abierta, y ningún dato de
        versión; cada prueba trabaja en su copia."""
        self.assertEqual(self.boundary, "core_imported_limites_v1")
        self.assertEqual(list(self.chain), ["boundary", "area", "digitize", "years", "detect",
                                            "filter", "balance"])
        done = self.query("SELECT uid, status, scope, revision_uid FROM gb_operation "
                          "ORDER BY fid")
        self.assertEqual({uid for uid, *_ in done}, set(self.chain.values()))
        self.assertEqual({(status, scope, revision) for _uid, status, scope, revision in done},
                         {("done", "project", "")})
        self.assertClose(self.demo.current_figure(self.project, "demo.boundary_area").value,
                         12.0)
        found = self.read(versions_read.versions)
        self.assertEqual([(v.code, str(v.status), v.uid) for v in found],
                         [("V01", "BORRADOR", self.v1.uid), ("V02", "BORRADOR", self.v2.uid)])
        for version in found:
            revision = self.read(lambda conn, v=version: versions_read.open_revision(conn, v.uid))
            self.assertEqual(revision.number, 1)
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE version_uid <> ''"),
                         [(0,)])
        self.assertTrue(self.project.writable)
        self.assertTrue(self.root.is_relative_to(self.folder))

    def test_pit_and_volume_in_v01(self) -> None:
        """RF-009-05, RF-009-24, D-19, D-34 (plan §7.1, la cadena de la demostración): en V01,
        con su altura de banco propia (12 m), ``demo.pit`` deja en V01 una rejilla, una malla y
        una tabla (ubicaciones con ``_v01``) con su hash, su lector y su procedencia (el límite
        importado del proyecto y el parámetro de V01), y ``demo.pit_volume`` la cifra
        ``demo.pit_volume`` = 3 182 celdas·banco × 12 m × 100 m² = 3 818 400 m³, igual a la suma
        de la tabla, con su procedencia hasta la entrada ``Limites_v1``; en V02 (el banco del
        proyecto, 10 m) los mismos nombres son otros datos (``_v02``) y otra cifra, y lo de V01
        no cambia."""
        own = self.own_bench("V01", 12.0)
        pit = self.demo.pit(self.project, "V01")
        r1 = self.read(lambda conn: versions_read.open_revision(conn, self.v1.uid))
        self.assertEqual((pit.version_uid, pit.revision_uid), (self.v1.uid, r1.uid))
        self.assertEqual(self.query("SELECT scope, revision_uid FROM gb_operation WHERE uid = ?",
                                    (pit.uid,)), [("version", r1.uid)])
        (boundary,) = pit.inputs
        self.assertEqual((boundary.name, boundary.role, boundary.frozen),
                         (self.boundary, "boundary", None))
        self.assertEqual(self.query(
            "SELECT key, parameter_uid, scope, rev, value FROM gb_operation_param "
            "WHERE operation_uid = ?", (pit.uid,)),
            [("demo.bench_height", own.uid, "version", 1, "12.0")])
        self.assertEqual(dict(pit.settings), {"benches": 3, "berm_m": 25.0, "step_m": 10.0,
                                              "top_z": 500.0})

        found = self.query(
            "SELECT name, kind, store, locator, reader, crs_epsg, qgis_editable, operation_uid "
            "FROM gb_dataset WHERE version_uid = ? ORDER BY fid", (self.v1.uid,))
        self.assertEqual(found, [
            ("demo_pit_grid", "raster", "rasters", "rasters/demo_pit_grid_v01.tif",
             "gis.geotiff@1", 25830, 0, pit.uid),
            ("demo_pit_mesh", "mesh", "meshes", "meshes/demo_pit_mesh_v01.npz",
             "core.npz_mesh@1", 25830, 0, pit.uid),
            ("demo_pit_benches", "table", "gpkg", "demo_pit_benches_v01",
             "core.gpkg_layer@1", None, 0, pit.uid),
        ])
        records = {name: self.record(name, "V01") for name, *_ in found}
        with self.project.read() as conn:
            for name, record in records.items():
                with self.subTest(dataset=name):
                    self.assertEqual(
                        registry.content_digest(conn, self.project, record).content_sha256,
                        record.content_sha256)
            self.assertIsNone(registry.get(conn, "demo_pit_grid"))  # no es del proyecto

        grid = geotiff_reader.read_geotiff(self.root / "rasters" / "demo_pit_grid_v01.tif",
                                           max_cells=10_000)
        self.assertEqual((grid.grid.west, grid.grid.north, grid.grid.dx, grid.grid.dy,
                          grid.grid.ncols, grid.grid.nrows),
                         (700_000.25, 4_400_350.5, 10.0, 10.0, 50, 35))
        self.assertEqual((grid.declared_crs.epsg, float(grid.values.max()),
                          float(grid.values.min())), (25830, 500.0, 464.0))
        with np.load(self.root / "meshes" / "demo_pit_mesh_v01.npz",
                     allow_pickle=False) as mesh:
            vertices, faces = mesh["vertices"], mesh["faces"]
            self.assertEqual((vertices.shape, vertices.dtype, faces.shape),
                             ((1750, 3), np.dtype(np.float64), (2 * 49 * 34, 3)))
            self.assertEqual(vertices[0].tolist(), [700_005.25, 4_400_345.5, 500.0])
            self.assertEqual(int(faces.max()), 1749)
        benches = expected_benches(12.0)
        self.assertEqual(benches, [(1, 488.0, 142_600.0, 1_711_200.0),
                                   (2, 476.0, 100_000.0, 1_200_000.0),
                                   (3, 464.0, 75_600.0, 907_200.0)])
        self.assertEqual(self.query('SELECT bench, floor_z, area_m2, volume_m3 FROM '
                                    '"demo_pit_benches_v01" ORDER BY fid'), benches)

        volume = self.demo.pit_volume(self.project, "V01")
        self.assertEqual(volume.revision_uid, r1.uid)
        self.assertEqual([(item.uid, item.role) for item in volume.inputs],
                         [(records["demo_pit_grid"].uid, "pit_grid")])
        (figure,), _warnings = self.demo.figures(self.project, volume.uid)
        self.assertEqual((figure.key, figure.unit, str(figure.kind), figure.label),
                         ("demo.pit_volume", "m3", "CALCULADO", "Volumen del hueco (demostración)"))
        self.assertEqual(figure.value, 3_818_400.0)
        self.assertEqual(figure.value, math.fsum(row[3] for row in benches))
        tree = lineage.lineage(self.project, figure.uid)
        self.assertEqual(list(tree.operations), [volume.uid, pit.uid, self.chain["boundary"]])
        self.assertEqual([used.key for used in tree.operations[pit.uid].params],
                         ["demo.bench_height"])
        self.assertEqual(tree.operations[pit.uid].params[0].scope, "version")
        self.assertEqual([link.name for link in tree.inputs.values()], ["Limites_v1"])

        # V02, con el banco del proyecto: los mismos nombres, otros datos y otra cifra.
        before = {name: record.content_sha256 for name, record in records.items()}
        self.demo.pit(self.project, "V02")
        volume2 = self.demo.pit_volume(self.project, "V02")
        (figure2,), _ = self.demo.figures(self.project, volume2.uid)
        self.assertEqual(figure2.value, math.fsum(row[3] for row in expected_benches(10.0)))
        self.assertEqual(figure2.value, 3_182_000.0)
        self.assertEqual(self.query("SELECT name, locator FROM gb_dataset WHERE version_uid = ? "
                                    "ORDER BY fid", (self.v2.uid,)),
                         [("demo_pit_grid", "rasters/demo_pit_grid_v02.tif"),
                          ("demo_pit_mesh", "meshes/demo_pit_mesh_v02.npz"),
                          ("demo_pit_benches", "demo_pit_benches_v02")])
        self.assertEqual({name: self.record(name, "V01").content_sha256 for name in records},
                         before)
        self.assertNotEqual(self.record("demo_pit_grid", "V02").uid,
                            records["demo_pit_grid"].uid)

    def test_pit_needs_a_version_and_the_project_crs(self) -> None:
        """RF-009-05, RF-009-04 (constitución: el CRS no se supone): ``demo.pit`` sin versión
        se rechaza con ``core.version_required``, y en una versión DESCARTADO con su texto,
        sin escribir nada; un límite en otro CRS que el del proyecto no se usa."""
        with self.project.read() as conn:
            record = registry.get(conn, self.boundary)
            self.assertEqual(self.demo._extent(conn, record, 25830),
                             (700_000.25, 4_400_000.5, 700_500.25, 4_400_350.5))
            with self.assertRaisesRegex(ValueError, "EPSG:4326, no en el CRS del proyecto"):
                self.demo._extent(conn, dataclasses.replace(record, crs_epsg=4326), 25830)
        with self.assertRaises(versions_model.VersionError) as caught:
            self.demo.pit(self.project, None)
        self.assertEqual(caught.exception.code, "core.version_required")
        self.set_status(self.v2, "DESCARTADO", "No sigue")
        with self.assertRaises(versions_model.VersionError) as caught:
            self.demo.pit(self.project, "V02")
        self.assertEqual(str(caught.exception),
                         "V02 está en estado DESCARTADO: cree una versión nueva a partir de ella")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE scope = 'version'"),
                         [(0,)])
        self.assertFalse((self.root / "rasters" / "demo_pit_grid_v02.tif").exists())

    def test_sketch_needs_review_when_its_input_changes(self) -> None:
        """RF-008-27, RF-009-05 (plan §7.1): ``demo.sketch`` es la edición a mano de una capa
        de rampas (líneas en EPSG:25830, editable en QGIS) de su versión, que lee la tabla de
        bancos del hueco; no se repite sola, así que cuando ``demo.pit`` vuelve a escribir esa
        tabla con otro contenido (dos bancos en vez de tres), queda «revisar a mano» (y nada
        más); antes, nada está obsoleto."""
        self.demo.pit(self.project, "V01")
        sketch = self.demo.sketch(self.project, "V01")
        layer = self.record("demo_sketch", "V01")
        self.assertEqual((layer.kind, str(layer.store), layer.locator, layer.qgis_editable,
                          layer.crs_epsg), ("vector", "gpkg", "demo_sketch_v01", True, 25830))
        self.assertEqual(self.query("SELECT geometry_type_name, srs_id FROM "
                                    "gpkg_geometry_columns WHERE table_name = ?",
                                    ("demo_sketch_v01",)), [("LINESTRING", 25830)])
        self.assertEqual(self.query('SELECT ramp, bench FROM "demo_sketch_v01" ORDER BY fid'),
                         [(ramp, bench) for ramp, bench, _line in vdemo.DEFAULT_RAMPS])
        self.assertEqual(stale.counts(self.project).obsolete, 0)

        self.demo.pit(self.project, "V01", benches=2)
        self.assertEqual(stale.counts(self.project).review, 1)
        with self.project.read() as conn:
            self.assertEqual(stale.review_operations(conn), frozenset({sketch.uid}))
        self.assertEqual(
            [(item.item_kind, item.name, item.op_type, item.review)
             for item in stale.stale_items(self.project).items
             if item.operation_uid == sketch.uid],
            [("dataset", "demo_sketch", "demo.sketch", True),
             ("operation", "demo.sketch", "demo.sketch", True)])
        self.assertEqual(self.record("demo_sketch", "V01").content_sha256,
                         layer.content_sha256)

    def test_design_from_parent_takes_the_frozen_pit(self) -> None:
        """RF-009-01, D-27 (plan §7.1): congelada V01.r1 con su tabla de bancos, V03 (que parte
        de V01.r1) diseña con lo congelado (``Use.frozen``): su tabla ``demo_design_v03`` son
        los bancos de r1 ensanchados un 10 %, con el hash congelado anotado; cuando V01 cambia
        la tabla en r2, V03 sigue leyendo r1, de su instantánea; sin ella, lo dice."""
        self.demo.pit(self.project, "V01")
        benches = self.record("demo_pit_benches", "V01")
        r1 = self.freeze(self.v1, [(benches, "produced")])
        v3 = self.new_version("desde_v01", "Desde V01", parent=self.v1.uid)
        self.assertEqual(v3.parent_revision_uid, r1)
        design = self.demo.design_from_parent(self.project, "V03", frozen=r1)
        (used,) = design.inputs
        self.assertEqual((used.uid, used.content_sha256, used.frozen, used.role),
                         (benches.uid, benches.content_sha256, r1, "parent_pit"))
        rows = [(bench, floor, area * 1.1, volume * 1.1)
                for bench, floor, area, volume in expected_benches(10.0)]
        self.assertEqual(self.query('SELECT bench, floor_z, area_m2, volume_m3 FROM '
                                    '"demo_design_v03" ORDER BY fid'), rows)
        self.assertEqual(self.record("demo_design", "V03").locator, "demo_design_v03")

        # V01 cambia su tabla en r2; lo congelado en r1, en su instantánea (como la deja T13).
        frozen_rows = self.query('SELECT bench, floor_z, area_m2, volume_m3 FROM '
                                 '"demo_pit_benches_v01" ORDER BY fid')
        self.demo.pit(self.project, "V01", benches=2)
        path, layer = self.query("SELECT snapshot_path, snapshot_layer FROM gb_revision_item "
                                 "WHERE revision_uid = ?", (r1,))[0]
        self.assertEqual((path, layer), ("snapshots/V01.r1/V01.r1.gpkg", "demo_pit_benches_v01"))
        snapshot = self.root / path
        with self.assertRaisesRegex(ValueError, "«demo_pit_benches» congelado en V01.r1"):
            self.demo.design_from_parent(self.project, "V03", frozen=r1)
        snapshot.parent.mkdir(parents=True)
        with sqlite3.connect(snapshot) as conn:
            conn.execute(f'CREATE TABLE "{layer}" (fid INTEGER PRIMARY KEY, bench INTEGER, '
                         "floor_z DOUBLE, area_m2 DOUBLE, volume_m3 DOUBLE)")
            conn.executemany(f'INSERT INTO "{layer}" (bench, floor_z, area_m2, volume_m3) '
                             "VALUES (?, ?, ?, ?)", frozen_rows)
        conn.close()
        self.demo.design_from_parent(self.project, "V03", frozen=r1)
        self.assertEqual(self.query('SELECT bench, floor_z, area_m2, volume_m3 FROM '
                                    '"demo_design_v03" ORDER BY fid'), rows)


class FixturesTest(fixtures.VersionsProjectCase):
    def test_helpers(self) -> None:
        """RF-009-02, RF-009-03 (plan §7.1): las ayudas del proyecto de versiones. Leer (las
        versiones, los datos, la lista de ficheros) no mueve el contador de cambios de la base
        y una escritura sí; la lista de ficheros da tamaño, huella y fecha sin la base, su
        diario ni la cabecera; alterar un fichero cambia su huella sin cambiar su tamaño ni su
        fecha, y deshacerlo lo deja como estaba; congelar por SQL anota lo producido por la
        versión, y declarar VIGENTE V01 y después V02 deja V01 SUPERADO, como en E1."""
        self.demo.pit(self.project, "V01")
        counter = self.change_counter()
        listed = self.files()
        self.read(versions_read.versions)
        self.record("demo_pit_grid", "V01")
        self.assertEqual((self.change_counter(), self.files()), (counter, listed))
        self.assertNotIn("project.gpkg", listed)
        self.assertNotIn("manifest.json", listed)
        self.assertEqual(listed["rasters"], "carpeta")
        size, sha, mtime = listed["rasters/demo_pit_grid_v01.tif"]
        undo = fixtures.alter_file(self.root / "rasters" / "demo_pit_grid_v01.tif")
        size2, sha2, mtime2 = self.files()["rasters/demo_pit_grid_v01.tif"]
        self.assertEqual((size2, mtime2), (size, mtime))
        self.assertNotEqual(sha2, sha)
        undo()
        self.assertEqual(self.files(), listed)

        r1 = self.freeze(self.v1)
        self.assertEqual(self.query("SELECT item_uid, part, copied FROM gb_revision_item WHERE "
                                    "revision_uid = ? ORDER BY fid", (r1,)),
                         [(self.record(name, "V01").uid, "produced", 1) for name in
                          ("demo_pit_grid", "demo_pit_mesh", "demo_pit_benches")])
        self.assertGreater(self.change_counter(), counter)
        self.set_status(self.v1, "VIGENTE")
        self.freeze(self.v2)
        self.set_status(self.v2, "VIGENTE")
        self.assertEqual([(v.code, str(v.status)) for v in self.read(versions_read.versions)],
                         [("V01", "SUPERADO"), ("V02", "VIGENTE")])


if __name__ == "__main__":
    unittest.main()
