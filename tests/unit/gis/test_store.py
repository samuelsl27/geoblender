# SPDX-License-Identifier: GPL-3.0-or-later
"""Resultados de las operaciones de la topografía en el proyecto (spec 006, T42; RF-006-08,
RF-006-26, RF-006-28; RF-008-17, RF-008-18, RF-008-19, RF-008-23; ADR-0025 §3 y §8; plan
006 §5.6.4 y §5.6.5; D20).

``gis.store.ResultWriter`` escribe lo que produce una operación de la 006 en un proyecto
sintético de esquema 2, con el ``OperationHandle`` de la 008:

- rejillas en ``rasters/`` (perfil ``project``), TIN en ``meshes/`` y curvas en una tabla
  ``gis_cnt_<nombre>`` de ``project.gpkg`` (plan §5.2.3: ``LINESTRING`` con Z y el SRS del
  proyecto);
- cada fichero se escribe en ``<fichero>.tmp-<sesión>``, reclamado con ``claim_paths`` junto
  a su destino, y al confirmar pasa a su sitio con ``os.replace`` (el anterior queda apartado
  hasta que la transacción se confirma); en esa transacción, las tablas y
  ``OperationHandle.complete`` con las ``DatasetSpec`` de ``gis.provenance`` y el
  ``ContentDigest`` de cada salida (el que daría su lector, o el que da el trabajo);
- un fallo o una cancelación antes de confirmar dejan la operación «fallida» o «cancelada»
  con su motivo, ningún dato, fichero ni tabla nuevos, y lo anterior intacto; un destino que
  otro programa tiene abierto, ``gis.raster_target_locked`` (sin ``__<hash8>``, D20);
- ``list_gis_datasets``, ``load_raster`` y ``load_tin`` leen lo registrado en ``gb_dataset``.

Las importaciones (T43; RF-006-04, RF-006-10, RF-006-12, RF-006-26; RF-008-07, RF-008-11,
RF-008-14, RF-008-52, RF-008-53, RF-008-54) declaran su entrada (``source_input`` y
``ResultWriter.declare_input``, con ``classify_import`` antes de escribir): lo importado
(``gis_src_``, ``gis_pts_``, ``gis_brk_``, ``gis_cnt_``, ``gis_bnd_``) queda inmutable, con
el uid corto de su entrada en su ubicación, y la entrada se registra con ``register_input``
en la misma transacción que ``complete``; el original del texto de puntos se guarda con
``store_originals_steps`` desde la copia verificada. Las fuentes están en ``fuentes/``, fuera
del proyecto, y no cambian.

Cada prueba crea su proyecto (``create_project`` con un reloj simulado), registra los
parámetros de ``gis``, los tipos de operación de ``gis.provenance`` que usa y los lectores que
faltan, y deja los registros como estaban.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import qgis, resources
from tests.support.core_fixtures import (
    FakeClock,
    FakePids,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered, snapshot
from tests.support.repo import ROOT
from tests.support.resources import requires
from tests.support.trees import age_folders

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
project_model = import_geoblender("core.project.model")
userdata_mod = import_geoblender("core.userdata")
core_params = import_geoblender("core.params")
operations = import_geoblender("core.provenance.operations")
dataset_registry = import_geoblender("core.datasets.registry")
orphans = import_geoblender("core.datasets.orphans")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
georef = import_geoblender("core.georef")
base = import_geoblender("core.gpkg.base")
wkb = import_geoblender("core.gpkg.wkb")
store = import_geoblender("gis.store")
provenance = import_geoblender("gis.provenance")
gis_content = import_geoblender("gis.content")
gis_params = import_geoblender("gis.params")
messages = import_geoblender("gis.messages")
grid_mod = import_geoblender("gis.grid")
raster_mod = import_geoblender("gis.raster")
tin_mod = import_geoblender("gis.tin")
contours_mod = import_geoblender("gis.contours")
geotiff = import_geoblender("gis.geotiff")
reader_mod = import_geoblender("gis.geotiff.reader")
worker_api = import_geoblender("jobs.worker_api")
inputs = import_geoblender("core.inputs")
input_model = import_geoblender("core.inputs.model")
encoder = import_geoblender("core.content.encoder")
core_defs = import_geoblender("core.params.core_defs")
prov_messages = import_geoblender("core.provenance.messages")
events = import_geoblender("core.project.events")
paths_mod = import_geoblender("core.paths")
hashing = import_geoblender("core.hashing")
csv_tables = import_geoblender("interop.csv_tables")
asc_mod = import_geoblender("gis.asc")
points_mod = import_geoblender("gis.points")
vector_mod = import_geoblender("gis.vector")

SESSION = make_session()
# El Blender que se abre en el mismo equipo después de cerrarse el de SESSION de golpe.
SESSION_A2 = make_session(session_uid="00000000-0000-4000-8000-0000000000a2", pid=5151)
TAG = "00000001"  # las 8 últimas cifras de la sesión de SESSION
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
PYPROJ = {"pyproj": "3.8.0"}
TRIANGULATOR = {"triangulator": "pure@1"}
TYPES = (provenance.RESAMPLE, provenance.TIN_FROM_POINTS, provenance.CONTOURS)
OPERATION_COLUMNS = ("status", "status_reason", "software", "message", "executor", "job_uid",
                     "settings")
DATA = ROOT / "tests" / "data" / "gis"
SOURCES = {  # lo que se copia a fuentes/ (fuera del proyecto)
    "f32_strip.tif": DATA / "geotiff" / "f32_strip.tif",
    "f64_strip.tif": DATA / "geotiff" / "f64_strip.tif",
    "f32_nocrs.tif": DATA / "geotiff" / "f32_nocrs.tif",
    "corner.asc": DATA / "asc" / "corner.asc",
    "corner.prj": DATA / "asc" / "corner.prj",
    "taludes.csv": DATA / "points" / "taludes.csv",
    "capas.gpkg": DATA / "gpkg" / "capas.gpkg",
}
ED50 = CATALOG.horizontal(23030)
POINT_COLUMNS = {"point_id": 0, "x": 1, "y": 2, "z": 3, "code": 4, "line": 5}
POINT_SETTINGS = {"encoding": "utf-8", "separator": ";", "decimal": ",", "header_row": 0,
                  "columns": POINT_COLUMNS, "line_kind": "hard"}
REASON = "La topografía entrega el MDT en ED50"
ORIGINAL_LIMIT = "core.original_copy_limit"
STATE_TABLES = ("gb_input", "gb_input_file", "gb_dataset", "gb_dataset_change")


def _recompute(request: Any) -> Any:  # pragma: no cover - ninguna prueba recalcula
    raise AssertionError("no se recalcula en estas pruebas")


def _raster(shift: float = 0.0) -> Any:
    """Una rejilla de 6 × 5 celdas de 1 m del proyecto (EPSG:25830 + EPSG:5782), con un
    hueco (NaN), un −0,0 y cotas que no son exactas en binario."""
    rows, cols = np.mgrid[0:5, 0:6]
    values = 800.0 + 0.5 * cols - 0.25 * rows + 0.001 * (rows * 6 + cols) + shift
    values[2, 3] = np.nan
    values[4, 5] = -0.0
    grid = grid_mod.Grid(700_010.0, 4_400_020.0, 1.0, 1.0, 6, 5)
    return raster_mod.Raster(grid, values, CRS, VERTICAL)


def _tin(lift: float = 0.0) -> Any:
    """Un TIN de 5 vértices y 4 triángulos antihorarios."""
    xy = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [2.0, 2.0]])
    xy += (700_010.0, 4_400_010.0)
    z = np.array([800.0, 801.0, 802.5, 801.5, 803.25]) + lift
    faces = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]], dtype=np.int32)
    return tin_mod.Tin(np.column_stack([xy, z]), faces, np.empty((0, 2), np.int32),
                       np.zeros(5, np.uint8), triangulator="pure@1")


def _lines(lift: float = 0.0) -> list[Any]:
    """Una curva abierta y otra cerrada (maestra), con coordenadas UTM con decimales."""
    first = np.array([[700_010.5, 4_400_011.0, 801.0], [700_012.0, 4_400_012.5, 801.0],
                      [700_013.5, 4_400_011.25, 801.0]])
    ring = np.array([[700_011.0, 4_400_011.0, 805.0], [700_013.0, 4_400_011.0, 805.0],
                     [700_013.0, 4_400_013.0, 805.0], [700_011.0, 4_400_013.0, 805.0]])
    first[:, 2] += lift
    ring[:, 2] += lift
    return [contours_mod.ContourLine(first, 801.0 + lift, False, False),
            contours_mod.ContourLine(ring, 805.0 + lift, True, True)]


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """Las mismas cotas bit a bit (NaN con NaN)."""
    test.assertEqual(got.shape, expected.shape)
    test.assertEqual(got.dtype, np.float64)
    test.assertTrue(np.array_equal(got.view(np.uint64), expected.view(np.uint64)))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StoreCase(unittest.TestCase):
    """Un proyecto nuevo por prueba con los parámetros de ``gis``, los tipos de operación
    ``gis.resample``, ``gis.tin_from_points`` y ``gis.contours`` y los lectores de las
    salidas."""

    def setUp(self) -> None:
        before = snapshot()
        readers_before = dict(readers.READERS)
        self.addCleanup(lambda: self.assertEqual(dict(readers.READERS), readers_before))
        self.addCleanup(lambda: self.assertEqual(snapshot(), before))
        core_params.register_definitions(gis_params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "gis")
        defs = provenance.operation_defs({name: _recompute for name in TYPES}, op_types=TYPES)
        self.enterContext(registered(*defs))
        for content_reader in (gis_content.GEOTIFF, builtin.NPZ_MESH, builtin.GPKG_LAYER):
            if content_reader.id not in readers.READERS:
                readers.register_reader(content_reader)
                self.addCleanup(readers.unregister_reader, content_reader.id)
        tmp = self.enterContext(project_tmp("gb-t42-"))
        parent = tmp / "p"
        parent.mkdir()
        self.tmp = tmp
        self.clock = FakeClock()
        self.userdata = userdata_mod.UserData(tmp / "u")
        self.project = create.create_project(parent, make_settings(), SESSION, self.userdata,
                                             clock=self.clock).project
        self.addCleanup(self.project.close)
        self.root = Path(self.project.root)

    # --- Ayudas -----------------------------------------------------------------------------

    def begin(self, op_type: str, **kw: Any) -> Any:
        kw.setdefault("settings", {"nombre": "prueba"})
        kw.setdefault("executor", "blender")
        return operations.begin_operation(self.project, op_type, **kw)

    def query(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def operation(self, uid: str) -> dict[str, Any]:
        row = self.query(f"SELECT {', '.join(OPERATION_COLUMNS)} FROM gb_operation "
                         "WHERE uid = ?", uid)[0]
        return dict(zip(OPERATION_COLUMNS, row, strict=True))

    def dataset(self, name: str) -> Any:
        with self.project.read() as conn:
            return dataset_registry.get(conn, name)

    def names(self) -> list[str]:
        return [row[0] for row in self.query("SELECT name FROM gb_dataset ORDER BY name")]

    def files(self) -> dict[str, str]:
        """El sha256 de cada fichero de ``rasters/`` y ``meshes/``, por su ruta."""
        found: dict[str, str] = {}
        for folder in ("rasters", "meshes"):
            for path in sorted((self.root / folder).rglob("*")):
                if path.is_file():
                    found[path.relative_to(self.root).as_posix()] = _sha(path)
        return found

    def tables(self) -> list[str]:
        return [row[0] for row in self.query(
            "SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'gis%' ORDER BY 1")]

    def read_hash(self, content_reader: Any, kind: str, path: Path,
                  settings: dict[str, Any] | None = None) -> str:
        """El hash de contenido que da ``content_reader`` al leer ``path`` como un dato (sin
        declaraciones)."""
        request = content_reader.request(kind, {}, {"main": path}, settings)
        return readers.read_content(content_reader, request).content_sha256

    def resample(self, name: str = "MDT Norte", raster: Any = None, **kw: Any) -> tuple[Any, Any]:
        """Una operación ``gis.resample`` que escribe ``raster`` como ``gis_dtm_<nombre>``."""
        handle = self.begin(provenance.RESAMPLE, settings={"method": "area_mean"},
                            params=["gis.resample.min_valid_fraction"])
        with store.ResultWriter(self.project, handle) as out:
            out.raster(name, _raster() if raster is None else raster)
            records = out.commit(software=PYPROJ, message=kw.get("message", "Remuestreo"))
        return handle, records

    def triangulate(self, name: str = "Topo 2026", tin: Any = None) -> tuple[Any, Any]:
        handle = self.begin(provenance.TIN_FROM_POINTS)
        with store.ResultWriter(self.project, handle) as out:
            out.tin(name, _tin() if tin is None else tin)
            records = out.commit(software=TRIANGULATOR, message="TIN de 4 triángulos")
        return handle, records

    def contour(self, name: str = "Curvas 1 m", lines: Any = None) -> tuple[Any, Any]:
        handle = self.begin(provenance.CONTOURS, params=["gis.contours.interval_m"])
        with store.ResultWriter(self.project, handle) as out:
            out.contours(name, _lines() if lines is None else lines)
            records = out.commit(message="2 curvas")
        return handle, records


class ResultsTest(StoreCase):
    def test_grid_is_a_dataset_with_the_hash_of_its_reader(self) -> None:
        """RF-006-08, RF-006-26, RF-008-17, RF-008-18: la rejilla queda en
        ``rasters/gis_dtm_<nombre>.tif`` con cada celda igual bit a bit (NaN y −0,0
        incluidos), como dato ``raster`` de ``gis`` con su EPSG y el hash que da
        ``gis.geotiff@1`` al leer el fichero; su operación, «hecha» con sus ajustes, sus
        parámetros, su ``software`` (pyproj), dónde se ejecutó y su mensaje; sin temporales
        ni rutas reclamadas al terminar."""
        raster = _raster()
        handle, records = self.resample(raster=raster, message="Remuestreo: 29 celdas")
        (record,) = records
        path = self.root / "rasters" / "gis_dtm_mdt_norte.tif"
        self.assertEqual(
            (record.name, record.module, record.kind, str(record.store), record.locator,
             record.reader, record.crs_epsg, record.operation_uid, record.immutable),
            ("gis_dtm_mdt_norte", "gis", "raster", "rasters", "rasters/gis_dtm_mdt_norte.tif",
             "gis.geotiff@1", 25830, handle.uid, False),
        )
        self.assertEqual(record.content_sha256,
                         self.read_hash(gis_content.GEOTIFF, "raster", path))
        source = reader_mod.read_geotiff(path)
        _same(self, source.values, raster.values)
        self.assertTrue(source.grid.same_geometry(raster.grid))
        self.assertEqual((source.declared_crs, source.declared_vertical), (CRS, VERTICAL))
        row = self.operation(handle.uid)
        self.assertEqual(
            (row["status"], json.loads(row["software"]), row["message"], row["executor"],
             json.loads(row["settings"])),
            ("done", PYPROJ, "Remuestreo: 29 celdas", "blender", {"method": "area_mean"}),
        )
        self.assertEqual(self.query("SELECT key FROM gb_operation_param WHERE operation_uid = ?",
                                    handle.uid), [("gis.resample.min_valid_fraction",)])
        self.assertEqual(self.query("SELECT role, content_sha256 FROM gb_operation_io WHERE "
                                    "operation_uid = ? AND direction = 'out'", handle.uid),
                         [("project_grid", record.content_sha256)])
        self.assertEqual(list(self.files()), ["rasters/gis_dtm_mdt_norte.tif"])
        self.assertEqual(operations.claimed_paths(self.project), frozenset())

    def test_tin_is_a_dataset_with_the_hash_of_its_reader(self) -> None:
        """RF-006-26, RF-008-17, RF-008-18: el TIN queda en ``meshes/gis_tin_<nombre>.npz``
        (plan §5.2.2) con su ``meta`` (EPSG del proyecto, su referencia vertical, el
        triangulador y la operación), como dato ``mesh`` con el hash que da
        ``core.npz_mesh@1``; la operación, con el triangulador en ``software``."""
        tin = _tin()
        handle, (record,) = self.triangulate(tin=tin)
        path = self.root / "meshes" / "gis_tin_topo_2026.npz"
        self.assertEqual((record.name, record.kind, record.locator, record.reader),
                         ("gis_tin_topo_2026", "mesh", "meshes/gis_tin_topo_2026.npz",
                          "core.npz_mesh@1"))
        self.assertEqual(record.content_sha256, self.read_hash(builtin.NPZ_MESH, "mesh", path))
        loaded = tin_mod.load_tin(path)
        for name in ("vertices", "faces", "constraint_edges", "vertex_source"):
            self.assertTrue(np.array_equal(getattr(loaded, name), getattr(tin, name)), name)
        self.assertEqual(
            {key: loaded.meta[key] for key in ("crs_epsg", "vertical", "triangulator",
                                                "operation_uid")},
            {"crs_epsg": 25830, "vertical": "EPSG:5782", "triangulator": "pure@1",
             "operation_uid": handle.uid},
        )
        self.assertEqual(json.loads(self.operation(handle.uid)["software"]), TRIANGULATOR)
        self.assertEqual(list(self.files()), ["meshes/gis_tin_topo_2026.npz"])

    def test_contours_are_a_table_with_z_and_the_project_srs(self) -> None:
        """RF-006-26, RF-008-17 (plan §5.2.3): las curvas quedan en ``gis_cnt_<nombre>``,
        capa ``LINESTRING`` con Z y el SRS del proyecto, con la referencia vertical en su
        descripción, una fila por curva (cota, maestra, cerrada y longitud) y la cerrada con
        su primer vértice repetido al final; el dato ``vector`` lleva el hash que da
        ``core.gpkg_layer@1`` al leer la tabla."""
        lines = _lines()
        handle, (record,) = self.contour(lines=lines)
        table = "gis_cnt_curvas_1_m"
        self.assertEqual((record.name, record.kind, str(record.store), record.locator,
                          record.reader, record.crs_epsg),
                         (table, "vector", "gpkg", table, "core.gpkg_layer@1", 25830))
        self.assertEqual(
            record.content_sha256,
            self.read_hash(builtin.GPKG_LAYER, "vector", self.project.database_path,
                           {"layer": table}),
        )
        (contents,) = self.query("SELECT data_type, srs_id, identifier, description, min_x, "
                                 "min_y, max_x, max_y FROM gpkg_contents WHERE table_name = ?",
                                 table)
        self.assertEqual(contents[:2], ("features", 25830))
        self.assertIn("Curvas 1 m", contents[2])
        self.assertIn("EPSG:5782", contents[3])
        self.assertEqual(contents[4:], (700_010.5, 4_400_011.0, 700_013.5, 4_400_013.0))
        self.assertEqual(self.query("SELECT column_name, geometry_type_name, srs_id, z, m FROM "
                                    "gpkg_geometry_columns WHERE table_name = ?", table),
                         [("geom", "LINESTRING", 25830, 1, 0)])
        rows = self.query(f'SELECT geom, elevation, is_index, closed, length_m FROM "{table}" '
                          "ORDER BY fid")
        self.assertEqual([row[1:] for row in rows],
                         [(line.elevation, int(line.is_index), int(line.closed), line.length_m)
                          for line in lines])
        geometries = [wkb.decode_geometry(row[0]) for row in rows]
        self.assertEqual([(g.geometry_type, g.srs_id, g.has_z) for g in geometries],
                         [("LINESTRING", 25830, True)] * 2)
        self.assertTrue(np.array_equal(geometries[0].coords, lines[0].xyz))
        self.assertTrue(np.array_equal(geometries[1].coords,
                                       np.vstack([lines[1].xyz, lines[1].xyz[:1]])))
        self.assertEqual(self.operation(handle.uid)["status"], "done")

    @requires(qgis.QGIS, qgis.QGIS_HINT)
    def test_gdal_lists_the_tables_with_z_and_srs(self) -> None:
        """RF-006-26 (plan §5.2.3): el GDAL de QGIS (``GEOBLENDER_QGIS_DIR``) lista la tabla
        de curvas como capa de líneas 3D con EPSG:25830 y sus dos entidades, sin avisos."""
        self.contour()
        self.project.close()
        result = qgis.run_tool("ogrinfo", "-ro", "-json", "-so",
                               str(self.project.database_path), "gis_cnt_curvas_1_m")
        output = qgis.output_of(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(result.stderr.strip(), "", output)
        (layer,) = json.loads(result.stdout)["layers"]
        (field,) = layer["geometryFields"]
        self.assertEqual((layer["name"], layer["featureCount"]), ("gis_cnt_curvas_1_m", 2))
        self.assertEqual(field["type"], "LineStringZ")
        self.assertEqual(field["coordinateSystem"]["projjson"]["id"],
                         {"authority": "EPSG", "code": 25830})

    def test_writing_the_same_content_again_gives_the_same_hash(self) -> None:
        """RF-008-17, RF-006-26: volver a escribir la rejilla, el TIN y las curvas con el
        mismo contenido (otra operación, el mismo nombre) da el mismo hash, el mismo dato
        con la operación nueva y ningún cambio de contenido; con otro contenido, otro hash
        y un cambio más (la tabla, sin filas de antes)."""
        writes: dict[str, tuple[Callable[..., Any], Callable[[], Any]]] = {
            "gis_dtm_mdt_norte": (lambda v: self.resample(raster=v), lambda: _raster(0.5)),
            "gis_tin_topo_2026": (lambda v: self.triangulate(tin=v), lambda: _tin(0.5)),
            "gis_cnt_curvas_1_m": (lambda v: self.contour(lines=v), lambda: _lines(0.5)),
        }
        firsts = {"gis_dtm_mdt_norte": _raster, "gis_tin_topo_2026": _tin,
                  "gis_cnt_curvas_1_m": _lines}
        for name, (write, changed) in writes.items():
            with self.subTest(dato=name):
                _, (first,) = write(firsts[name]())
                again, (second,) = write(firsts[name]())
                self.assertEqual((second.uid, second.content_sha256, second.operation_uid),
                                 (first.uid, first.content_sha256, again.uid))
                changes = "SELECT COUNT(*) FROM gb_dataset_change WHERE dataset_uid = ?"
                self.assertEqual(self.query(changes, first.uid), [(1,)])
                _, (third,) = write(changed())
                self.assertEqual(third.uid, first.uid)
                self.assertNotEqual(third.content_sha256, first.content_sha256)
                self.assertEqual(self.query(changes, first.uid), [(2,)])
        self.assertEqual(self.query('SELECT COUNT(*) FROM "gis_cnt_curvas_1_m"'), [(2,)])
        self.assertEqual(sorted(self.files()), ["meshes/gis_tin_topo_2026.npz",
                                                "rasters/gis_dtm_mdt_norte.tif"])


class FailureTest(StoreCase):
    def test_failure_before_committing_leaves_nothing(self) -> None:
        """RF-006-28, RF-008-19, RF-008-23: un error después de escribir los temporales, o
        al completar el registro (``software`` sin pyproj, rechazado ya con los ficheros en su
        sitio), deja la operación «fallida» con su motivo y ningún dato, fichero, temporal ni
        tabla nuevos; una rejilla que ya existía sigue con su contenido y su hash."""
        _, (kept,) = self.resample("Previa")
        before = self.files()
        handle = self.begin(provenance.RESAMPLE)
        with self.assertRaises(RuntimeError), store.ResultWriter(self.project, handle) as out:
            out.raster("MDT Norte", _raster())
            self.assertEqual(len(self.files()), 2)  # el temporal
            raise RuntimeError("el informe no se pudo componer")
        row = self.operation(handle.uid)
        self.assertEqual((row["status"], row["status_reason"]),
                         ("failed", "error durante la operación: RuntimeError: el informe no "
                                    "se pudo componer"))
        self.assertEqual(self.files(), before)

        handle = self.begin(provenance.RESAMPLE)
        with self.assertRaises(ValueError), store.ResultWriter(self.project, handle) as out:
            out.raster("Previa", _raster(1.0))
            out.raster("MDT Norte", _raster())
            out.commit(software={}, message="sin pyproj")
        row = self.operation(handle.uid)
        self.assertEqual(row["status"], "failed")
        self.assertIn("pyproj", row["status_reason"])
        self.assertEqual(self.files(), before)
        self.assertEqual(self.names(), ["gis_dtm_previa"])
        self.assertEqual(self.dataset("gis_dtm_previa").content_sha256, kept.content_sha256)

        handle = self.begin(provenance.CONTOURS)
        with self.assertRaises(ValueError), store.ResultWriter(self.project, handle) as out:
            out.contours("Curvas", _lines())
            out.commit(software={"numpy": "2.3.4"})
        self.assertEqual(self.operation(handle.uid)["status"], "failed")
        self.assertEqual(self.tables(), [])
        self.assertTrue(self.project.writable)
        self.assertEqual(operations.claimed_paths(self.project), frozenset())

    def test_cancelling_before_committing_leaves_nothing(self) -> None:
        """RF-006-28, RF-008-19: cancelar mientras se escribe una rejilla o se copia el
        resultado de un trabajo (``JobCancelled`` entre teselas o trozos) deja la operación
        «cancelada» con el motivo y nada escrito."""
        source = self.tmp / "trabajo" / "out" / "dtm.tif"
        source.parent.mkdir(parents=True)
        geotiff.GeoTiffIO().write(_raster(), source, profile="project")
        digest = gis_content.raster_digest(_raster(), {})
        attempts: dict[str, Callable[[Any], Any]] = {
            "escribir": lambda out: out.raster("MDT Norte", _raster(), cancelled=lambda: True),
            "copiar": lambda out: out.copy_file(provenance.PROJECT_GRID, "MDT Norte", source,
                                                content=digest, cancelled=lambda: True),
        }
        for what, attempt in attempts.items():
            with self.subTest(al=what):
                handle = self.begin(provenance.RESAMPLE)
                with (self.assertRaises(worker_api.JobCancelled),
                      store.ResultWriter(self.project, handle) as out):
                    attempt(out)
                row = self.operation(handle.uid)
                self.assertEqual(row["status"], "cancelled")
                self.assertTrue(row["status_reason"].startswith(
                    "cancelada durante la operación: Cancelado al "), row["status_reason"])
                self.assertEqual(self.files(), {})
                self.assertEqual(self.names(), [])

    def test_locked_target_keeps_the_previous_content(self) -> None:
        """RF-006-28 (plan §5.6.5, D20): si otro programa tiene abierta la rejilla (QGIS), la
        operación falla con ``gis.raster_target_locked`` sin escribir nada: el fichero y el
        dato siguen como estaban, no queda ningún temporal ni ``<nombre>__<hash8>.tif`` y el
        proyecto sigue en escritura."""
        if os.name != "nt":
            self.skipTest(resources.skip_reason(resources.WINDOWS, resources.WINDOWS_HINT))
        _, (kept,) = self.resample()
        before = self.files()
        target = self.root / "rasters" / "gis_dtm_mdt_norte.tif"
        handle = self.begin(provenance.RESAMPLE)
        with target.open("rb"), self.assertRaises(messages.GisError) as caught:
            with store.ResultWriter(self.project, handle) as out:
                out.raster("MDT Norte", _raster(2.0))
                out.commit(software=PYPROJ)
        error = caught.exception
        self.assertEqual((error.code, error.obj, error.field),
                         ("gis.raster_target_locked", "gis_dtm_mdt_norte.tif", "destino"))
        row = self.operation(handle.uid)
        self.assertEqual(row["status"], "failed")
        self.assertIn(str(error), row["status_reason"])
        self.assertEqual(self.files(), before)
        self.assertEqual(self.dataset("gis_dtm_mdt_norte").content_sha256, kept.content_sha256)
        self.assertTrue(self.project.writable)

    def test_target_taken_by_a_leftover_or_another_layer(self) -> None:
        """RF-008-19, RF-008-22: si en el sitio del resultado hay un fichero que no es de
        ese dato (un resto) o una capa que no es suya (de QGIS), ``gis.output_target_taken``
        antes de escribir nada: el fichero y la capa no cambian, la operación queda
        «fallida» y el proyecto sigue en escritura."""
        leftover = self.root / "rasters" / "gis_dtm_mdt_norte.tif"
        leftover.write_bytes(b"resto de una operacion interrumpida")
        handle = self.begin(provenance.RESAMPLE)
        with (self.assertRaises(messages.GisError) as caught,
              store.ResultWriter(self.project, handle) as out):
            out.raster("MDT Norte", _raster())
        self.assertEqual((caught.exception.code, caught.exception.value),
                         ("gis.output_target_taken", "rasters/gis_dtm_mdt_norte.tif"))
        self.assertEqual(leftover.read_bytes(), b"resto de una operacion interrumpida")
        self.assertEqual(self.operation(handle.uid)["status"], "failed")

        with self.project.write_transaction() as conn:
            base.create_feature_table(conn, "gis_cnt_de_qgis", "LINESTRING", 25830, True, [],
                                      "Capa de QGIS")
        handle = self.begin(provenance.CONTOURS)
        with (self.assertRaises(messages.GisError) as caught,
              store.ResultWriter(self.project, handle) as out):
            out.contours("De QGIS", _lines())
        self.assertEqual((caught.exception.code, caught.exception.value),
                         ("gis.output_target_taken", "gis_cnt_de_qgis"))
        self.assertEqual(self.query('SELECT COUNT(*) FROM "gis_cnt_de_qgis"'), [(0,)])
        self.assertEqual(self.names(), [])
        self.assertTrue(self.project.writable)


class TemporaryTest(StoreCase):
    def test_temporaries_are_claimed_and_leftovers_go_to_orphans(self) -> None:
        """RF-008-19, RF-008-22 (ADR-0025 §3 y §8): mientras la operación está en curso, el
        temporal ``<fichero>.tmp-<sesión>`` y el destino están reclamados y la comprobación de
        apertura no los aparta; si Blender se cierra de golpe, al abrir otra sesión el
        temporal, ya sin reclamar, va a ``orphans/`` (sin borrar nada)."""
        handle = self.begin(provenance.RESAMPLE)
        out = store.ResultWriter(self.project, handle)
        out.raster("MDT Norte", _raster())
        final = self.root / "rasters" / "gis_dtm_mdt_norte.tif"
        temporary = final.with_name(f"gis_dtm_mdt_norte.tif.tmp-{TAG}")
        self.assertEqual(store.temporary_path(self.project, final), temporary)
        self.assertEqual(list(self.files()), [f"rasters/{temporary.name}"])
        self.assertLessEqual({temporary, final}, set(operations.claimed_paths(self.project)))
        future = time.time_ns() + 10 * 10**9
        outcome = list(orphans.orphan_steps(self.project, write=True, started_at=future))[-1]
        self.assertEqual(outcome.result.moved, ())
        data = temporary.read_bytes()

        # Blender se cierra de golpe: ni confirma ni limpia.
        self.project.set_read_only(project_model.ReadOnlyCode.LOCK_LOST, "Blender se cerró")
        other = open_mod.open_project(self.root, SESSION_A2, self.userdata, clock=self.clock,
                                      pid_alive=FakePids({SESSION_A2.pid})).project
        self.addCleanup(other.close)
        self.assertTrue(other.writable)
        outcome = list(orphans.orphan_steps(other, write=True, started_at=future))[-1].result
        self.assertEqual([item.path for item in outcome.moved],
                         [f"rasters/{temporary.name}"])
        self.assertFalse(temporary.exists())
        moved = other.root / Path(outcome.moved[0].moved_to)
        self.assertEqual(moved.read_bytes(), data)


class JobOutputTest(StoreCase):
    def test_job_outputs_are_copied_with_their_digest(self) -> None:
        """RF-008-18, RF-008-20, RF-006-26: el resultado de un trabajo (``out/`` con su
        huella) se copia al proyecto con su temporal y se incorpora con ``ingest_job``: el
        dato lleva el ``ContentDigest`` que dio el trabajo, que es el que da su lector, y la
        operación su trabajo y su ejecutor; una copia que no casa con la huella del trabajo
        es ``gis.output_copy_mismatch`` y no escribe nada."""
        folder = self.tmp / "trabajo"
        source = folder / "out" / "dtm.tif"
        source.parent.mkdir(parents=True)
        geotiff.GeoTiffIO().write(_raster(), source, profile="project")
        digest = gis_content.raster_digest(_raster(), {})
        sha = _sha(source)
        outcome = operations.JobOutcome(
            "job-0042", "succeeded", "job_thread", label="Remuestreo", folder=folder,
            outputs=(operations.OutputPrint("out/dtm.tif", sha, "dtm",
                                            size=source.stat().st_size),),
        )
        handle = self.begin(provenance.RESAMPLE, executor="job_thread")
        with store.ResultWriter(self.project, handle) as out:
            out.copy_file(provenance.PROJECT_GRID, "MDT Norte", outcome.file("dtm"),
                          content=digest, sha256=sha)
            result = operations.ingest_job(self.project, handle, outcome, out.write,
                                           software=PYPROJ, message="Remuestreo en trabajo")
        (record,) = result.outputs
        path = self.root / "rasters" / "gis_dtm_mdt_norte.tif"
        self.assertEqual(record.content_sha256, digest.content_sha256)
        self.assertEqual(digest.content_sha256,
                         self.read_hash(gis_content.GEOTIFF, "raster", path))
        self.assertEqual(_sha(path), sha)
        row = self.operation(handle.uid)
        self.assertEqual((row["status"], row["executor"], row["job_uid"]),
                         ("done", "job_thread", "job-0042"))

        handle = self.begin(provenance.RESAMPLE, executor="job_thread")
        with (self.assertRaises(messages.GisError) as caught,
              store.ResultWriter(self.project, handle) as out):
            out.copy_file(provenance.PROJECT_GRID, "Otro", source, content=digest,
                          sha256="0" * 64)
        self.assertEqual(caught.exception.code, "gis.output_copy_mismatch")
        self.assertEqual(self.operation(handle.uid)["status"], "failed")
        self.assertEqual(list(self.files()), ["rasters/gis_dtm_mdt_norte.tif"])


class LoadTest(StoreCase):
    def test_list_and_load_what_is_registered(self) -> None:
        """RF-006-08 (plan §5.3.2, D-10): ``list_gis_datasets`` da los datos vivos de ``gis``
        desde ``gb_dataset`` (todos, por tipo o por familia); ``load_raster`` da la rejilla
        con las mismas celdas, el CRS y la referencia vertical del proyecto, y ``load_tin`` el
        TIN, por nombre o por su registro; un nombre que no está es ``gis.dataset_unknown`` y
        un dato de otro tipo, un error del programa."""
        raster = _raster()
        self.resample(raster=raster)
        self.triangulate()
        self.contour()
        listed = store.list_gis_datasets(self.project)
        self.assertEqual([record.name for record in listed],
                         ["gis_cnt_curvas_1_m", "gis_dtm_mdt_norte", "gis_tin_topo_2026"])
        self.assertEqual([r.name for r in store.list_gis_datasets(self.project, ("raster",))],
                         ["gis_dtm_mdt_norte"])
        self.assertEqual([r.name for r in store.list_gis_datasets(
            self.project, families=(provenance.TIN, provenance.CONTOUR_LINES))],
            ["gis_cnt_curvas_1_m", "gis_tin_topo_2026"])
        for ref in ("gis_dtm_mdt_norte", listed[1]):
            loaded = store.load_raster(self.project, ref)
            _same(self, loaded.values, raster.values)
            self.assertTrue(loaded.grid.same_geometry(raster.grid))
            self.assertEqual((loaded.crs, loaded.vertical), (CRS, VERTICAL))
        tin = store.load_tin(self.project, "gis_tin_topo_2026")
        self.assertTrue(np.array_equal(tin.vertices, _tin().vertices))
        with self.assertRaises(messages.GisError) as caught:
            store.load_raster(self.project, "gis_dtm_no_existe")
        self.assertEqual((caught.exception.code, caught.exception.value),
                         ("gis.dataset_unknown", "gis_dtm_no_existe"))
        with self.assertRaises(ValueError):
            store.load_raster(self.project, "gis_tin_topo_2026")
        with self.assertRaises(ValueError):
            store.load_tin(self.project, "gis_cnt_curvas_1_m")


class ProjectionTest(StoreCase):
    def test_project_grid_in_another_reference_is_a_program_error(self) -> None:
        """RF-006-08 (plan §5.2.1): una rejilla del proyecto (``gis_dtm_``) va en el CRS y la
        referencia vertical del proyecto; otra es un error del programa (no se escribe
        nada), y un TIN o unas curvas se escriben con los del proyecto."""
        self.assertEqual(store.project_references(self.project), (CRS, VERTICAL))
        other = _raster()
        foreign = raster_mod.Raster(other.grid, other.values, CATALOG.horizontal(23030),
                                    VERTICAL)
        handle = self.begin(provenance.RESAMPLE)
        with self.assertRaises(ValueError), store.ResultWriter(self.project, handle) as out:
            out.raster("MDT Norte", foreign)
        self.assertEqual(self.files(), {})
        self.assertEqual(self.operation(handle.uid)["status"], "failed")


# --- Importaciones y entradas (T43) ------------------------------------------------------------


def _rings(coords: Any) -> list[np.ndarray]:
    """Los anillos de una geometría de polígonos, en su orden (un anillo es una matriz)."""
    if isinstance(coords, np.ndarray):
        return [coords]
    return [ring for part in coords for ring in _rings(part)]


class ImportCase(StoreCase):
    """Un proyecto como el de ``StoreCase`` con las tres importaciones de ``gis.provenance``,
    los cinco lectores de ``gis`` y el lector de tablas de ``interop``, y las fuentes de
    ``tests/data/gis`` copiadas en ``fuentes/``, fuera del proyecto."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(*provenance.operation_defs({},
                                                                op_types=provenance.IMPORTS)))
        for content_reader in gis_content.CONTENT_READERS:
            if content_reader.id not in readers.READERS:
                readers.register_reader(content_reader)
                self.addCleanup(readers.unregister_reader, content_reader.id)
        previous = gis_content.use_table_reader(csv_tables.read_table)
        self.addCleanup(gis_content.use_table_reader, previous)
        if ORIGINAL_LIMIT not in core_params.DEFINITIONS:  # el límite de los originales
            core_params.register_definitions(core_defs.DEFINITIONS)
            self.addCleanup(core_params.unregister_definitions, "core")
        self.sources = self.tmp / "fuentes"
        self.sources.mkdir()
        for name, path in SOURCES.items():
            shutil.copyfile(path, self.sources / name)
        age_folders(self.sources)

    # --- Ayudas -----------------------------------------------------------------------------

    def source_spec(self, reader: Any, name: str, *files: str, crs: Any = CRS,
                    vertical: Any = VERTICAL, settings: dict[str, Any] | None = None) -> Any:
        """La entrada de ``files`` (de ``fuentes/``; el primero, el principal) que lee
        ``reader`` con sus CRS declarados: el ancla de cada fichero, su huella y el hash de
        contenido que da el lector con las declaraciones de la entrada (lo que da el trabajo
        de la importación)."""
        found = [self.sources / file for file in files]
        anchors = [inputs.locate_source(path, self.project, self.userdata,
                                        role="main" if index == 0 else "sidecar")
                   for index, path in enumerate(found)]
        prints = [input_model.SourcePrint(hashing.sha256_file(path), size=path.stat().st_size,
                                          mtime_ns=path.stat().st_mtime_ns) for path in found]
        declarations = store.source_declarations(reader.id, crs, vertical, settings)
        request = reader.request(reader.kinds[0], declarations,
                                 dict(zip(inputs.reader_roles(anchors), found, strict=True)),
                                 settings or {})
        return store.source_input(reader.id, name, files=anchors, file_prints=prints,
                                  digest=readers.read_content(reader, request), crs=crs,
                                  vertical=vertical, settings=settings)

    def import_grid(self, file: str, name: str = "MDT Norte", *, reader: Any = None,
                    sidecars: tuple[str, ...] = (), crs: Any = CRS, vertical: Any = VERTICAL,
                    previous_uid: str | None = None, reason: str | None = None,
                    software: Any = None) -> tuple[Any, Any, Any]:
        """``gis.import_dtm`` de ``fuentes/<file>``: su entrada y ``gis_src_<nombre>``.
        Devuelve la operación, sus resultados y lo registrado (o el ``Reuse``)."""
        reader = gis_content.GEOTIFF if reader is None else reader
        spec = self.source_spec(reader, name, file, *sidecars, crs=crs, vertical=vertical)
        read = asc_mod.read_asc if reader is gis_content.ASC else reader_mod.read_geotiff
        source = read(self.sources / file)
        raster = raster_mod.Raster(source.grid, source.values, crs, vertical)
        handle = self.begin(provenance.IMPORT_DTM, settings={"nombre": name})
        with store.ResultWriter(self.project, handle) as out:
            found = out.declare_input(spec, previous_uid=previous_uid, reason=reason)
            if isinstance(found, inputs.Reuse):
                return handle, out, found
            out.raster(name, raster, family=provenance.SOURCE_GRID)
            records = out.commit(software=software, message=f"MDT «{name}» importado")
        return handle, out, records

    def state(self) -> list[Any]:
        """Las entradas, los datos, sus cambios, los ficheros y las tablas del proyecto."""
        found: list[Any] = [self.query(f"SELECT * FROM {table} ORDER BY 1")
                            for table in STATE_TABLES]
        return [*found, self.files(), self.tables()]

    def last_operation(self) -> dict[str, Any]:
        (row,) = self.query("SELECT uid FROM gb_operation ORDER BY fid DESC LIMIT 1")
        return self.operation(row[0])

    def assert_no_absolute_paths(self) -> None:
        stored = [self.query(f"SELECT * FROM {table}") for table in (
            "gb_input", "gb_input_file", "gb_operation", "gb_dataset", "gb_event",
            "gpkg_contents")]
        self.assertEqual(paths_mod.find_absolute_paths(stored), [])

    def assert_protected(self, table: str, input_name: str) -> None:
        """Lo importado no se cambia desde otra conexión (QGIS): el rechazo lo dice."""
        conn = sqlite3.connect(str(self.project.database_path), timeout=2.0,
                               isolation_level=None)
        self.addCleanup(conn.close)
        for sql in (f'UPDATE "{table}" SET geom = geom', f'DELETE FROM "{table}"'):
            with self.subTest(tabla=table, sql=sql), \
                    self.assertRaises(sqlite3.IntegrityError) as caught:
                conn.execute(sql)
            self.assertIn(f"{table}: es lo importado de la entrada «{input_name}»: no se "
                          "modifica", str(caught.exception))

    def tag(self, entry: Any) -> str:
        return entry.uid.partition("-")[0]


class ImportTest(ImportCase):
    def test_dtm_import_registers_its_input_with_its_crs_and_hash(self) -> None:
        """RF-006-26, RF-008-07, RF-008-52, RF-006-10, RF-008-14 (plan §5.6.3, D22): importar
        un GeoTIFF y un ASC con su ``.prj`` deja cada uno su entrada (de ``gis``, su lector,
        sus ficheros con su ancla relativa y su huella, sus CRS horizontal y vertical
        declarados, sus ajustes y el hash de contenido de su lector) y lo importado,
        ``gis_src_<nombre>``, en ``rasters/gis_src_<nombre>_<entrada8>.tif`` con las celdas de
        la fuente bit a bit, inmutable y con su entrada, de la misma operación «hecha»; del
        ráster no se guarda el original; la carpeta de la fuente no cambia y nada guarda una
        ruta absoluta."""
        cases = (("f32_strip.tif", (), gis_content.GEOTIFF, "MDT Norte", "mdt_norte"),
                 ("corner.asc", ("corner.prj",), gis_content.ASC, "MDT ASC", "mdt_asc"))
        locators = []
        for file, sidecars, reader, name, slug in cases:
            with self.subTest(fuente=file):
                with assert_source_untouched(self.sources):
                    spec = self.source_spec(reader, name, file, *sidecars)
                    handle, out, (record,) = self.import_grid(file, name, reader=reader,
                                                              sidecars=sidecars)
                    copies = self.tmp / "trabajo" / slug
                    copies.mkdir(parents=True)
                    for item in (file, *sidecars):
                        shutil.copyfile(self.sources / item, copies / item)
                    steps = list(out.originals([copies / item for item in (file, *sidecars)]))
                entry = out.input
                self.assertEqual(
                    (entry.name, entry.kind, entry.module, entry.reader, entry.layer,
                     entry.operation_uid, entry.status, entry.original),
                    (name, "raster", "gis", reader.id, None, handle.uid, "current",
                     "not_applicable"),
                )
                self.assertEqual((dict(entry.crs_h), dict(entry.crs_v), dict(entry.settings)),
                                 ({"epsg": 25830}, {"epsg": 5782}, {}))
                self.assertEqual(entry.digest, spec.digest)
                self.assertEqual([(item.source, item.sha256, item.size) for item in entry.files],
                                 [(source, printed.sha256, printed.size) for source, printed
                                  in zip(spec.files, spec.file_prints, strict=True)])
                self.assertEqual([str(item.role) for item in entry.files],
                                 ["main", *("sidecar" for _ in sidecars)])
                locator = f"rasters/gis_src_{slug}_{self.tag(entry)}.tif"
                locators.append(locator)
                self.assertEqual(
                    (record.name, record.kind, record.locator, record.reader, record.input_uid,
                     record.immutable, record.crs_epsg, record.operation_uid),
                    (f"gis_src_{slug}", "raster", locator, "gis.geotiff@1", entry.uid, True,
                     25830, handle.uid),
                )
                path = self.root / locator
                self.assertEqual(record.content_sha256,
                                 self.read_hash(gis_content.GEOTIFF, "raster", path))
                read = asc_mod.read_asc if reader is gis_content.ASC else reader_mod.read_geotiff
                _same(self, reader_mod.read_geotiff(path).values,
                      read(self.sources / file).values)
                self.assertEqual(self.operation(handle.uid)["status"], "done")
                self.assertEqual(self.query("SELECT role, item_uid FROM gb_operation_io WHERE "
                                            "operation_uid = ?", handle.uid),
                                 [("source_grid", record.uid)])
                self.assertEqual(steps[-1].result.state, "not_applicable")
        self.assertEqual(sorted(self.files()), sorted(locators))
        self.assertFalse((self.root / "originals").exists())
        self.assertEqual(operations.claimed_paths(self.project), frozenset())
        self.assert_no_absolute_paths()

    def test_points_keep_their_coordinates_and_the_csv_its_original(self) -> None:
        """RF-006-12, RF-006-26, RF-008-52, RF-008-53, RF-008-14: el CSV de los taludes («;»
        y coma decimal) deja su entrada ``table`` con sus ajustes (las columnas y el tipo de
        línea, contenido) y lo importado en ``gis_pts_<nombre>_<entrada8>`` (``POINT`` con Z)
        y ``gis_brk_…`` (``LINESTRING`` con Z) con el SRS declarado, las coordenadas en
        float64 sin alterar y su punto, su código y su fila o su línea; cambiar las dos tablas
        desde otra conexión aborta con el nombre de la entrada. Su original se guarda desde
        la copia verificada, con su huella, en ``originals/<entrada>/``; la fuente no
        cambia."""
        source = self.sources / "taludes.csv"
        verified = self.tmp / "trabajo" / "in" / "taludes.csv"
        verified.parent.mkdir(parents=True)
        with assert_source_untouched(self.sources):
            table = csv_tables.read_table(source, encoding="utf-8", separator=";", header_row=0)
            mapping = points_mod.ColumnMapping(x=1, y=2, z=3, point_id=0, code=4, line=5)
            points, lines, _report = points_mod.points_from_rows(
                table.columns, table.rows, mapping, ",", source=source.name,
                row_numbers=table.lines)
            spec = self.source_spec(gis_content.POINTS_TEXT, "Taludes", "taludes.csv",
                                    settings=POINT_SETTINGS)
            shutil.copyfile(source, verified)
            handle = self.begin(provenance.IMPORT_POINTS)
            with store.ResultWriter(self.project, handle) as out:
                self.assertIsInstance(out.declare_input(spec), inputs.New)
                out.points("Taludes", points)
                out.breaklines("Taludes", lines)
                pts, brk = out.commit(message="20 puntos y 4 líneas de rotura")
            steps = list(out.originals([verified]))
        entry = out.input
        self.assertEqual((entry.kind, entry.reader, dict(entry.settings),
                          entry.content_settings_keys),
                         ("table", "gis.points_text@1", POINT_SETTINGS, ("columns", "line_kind")))
        tag = self.tag(entry)
        self.assertEqual(
            [(r.name, r.locator, r.kind, r.immutable, r.input_uid, r.crs_epsg) for r in (pts, brk)],
            [("gis_pts_taludes", f"gis_pts_taludes_{tag}", "vector", True, entry.uid, 25830),
             ("gis_brk_taludes", f"gis_brk_taludes_{tag}", "vector", True, entry.uid, 25830)],
        )
        for record in (pts, brk):
            self.assertEqual(record.content_sha256, self.read_hash(
                builtin.GPKG_LAYER, "vector", self.project.database_path,
                {"layer": record.locator}))
        self.assertEqual(self.query(
            "SELECT table_name, geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns "
            "WHERE table_name LIKE 'gis%' ORDER BY 1"),
            [(brk.locator, "LINESTRING", 25830, 1, 0), (pts.locator, "POINT", 25830, 1, 0)])
        self.assertEqual((len(points), len(lines)), (20, 4))
        rows = self.query(f'SELECT geom, point_id, code, source_row FROM "{pts.locator}" '
                          "ORDER BY fid")
        self.assertTrue(np.array_equal(
            np.array([wkb.decode_geometry(row[0]).coords for row in rows]), points.xyz))
        self.assertEqual([row[1:] for row in rows],
                         list(zip(points.point_ids, points.codes, points.source_rows,
                                  strict=True)))
        rows = self.query(f'SELECT geom, line_id, hard, code FROM "{brk.locator}" ORDER BY fid')
        self.assertEqual([row[1:] for row in rows],
                         [(line.line_id, 1, line.code) for line in lines])
        for row, line in zip(rows, lines, strict=True):
            self.assertTrue(np.array_equal(wkb.decode_geometry(row[0]).coords, line.xyz))
        for record in (pts, brk):
            self.assert_protected(record.locator, "Taludes")
        sha = _sha(source)
        outcome = steps[-1].result
        stored = f"originals/{entry.uid}/taludes.csv"
        self.assertEqual((outcome.state, [(item.path, item.sha256) for item in outcome.files]),
                         ("stored", [(stored, sha)]))
        self.assertEqual(_sha(self.root / stored), sha)
        self.assertEqual(self.query("SELECT original_path, original_sha256 FROM gb_input_file "
                                    "WHERE input_uid = ?", entry.uid), [(stored, sha)])
        self.assertEqual(self.query("SELECT original FROM gb_input WHERE uid = ?", entry.uid),
                         [("stored",)])
        self.assert_no_absolute_paths()

    def test_layers_are_imported_with_their_role(self) -> None:
        """RF-006-12, RF-006-26, RF-008-52: dos capas del mismo GeoPackage, leídas de su
        copia, cada una con su entrada ``vector`` (``gis.gpkg_layer@1``, su capa y su papel,
        que es contenido): el contorno (``MultiPolygon`` 2D con un hueco y una isla) en
        ``gis_bnd_<nombre>_<entrada8>`` (``MULTIPOLYGON`` sin Z, papel «boundary») y las
        curvas (``LineString ZM`` con la cota en ``cota``), declaradas en ED50, como lo
        importado en ``gis_cnt_<nombre>_<entrada8>`` (con su cota, su geometría y el SRS
        declarado, que entra en ``gpkg_spatial_ref_sys``), protegidas; de una capa no se guarda
        el original; el GeoPackage no cambia."""
        verified = self.tmp / "trabajo" / "in"
        verified.mkdir(parents=True)
        with assert_source_untouched(self.sources):
            copy = vector_mod.copy_source(self.sources / "capas.gpkg", verified)
            boundary = vector_mod.read_layer(copy, "contorno")
            curves = vector_mod.read_layer(copy, "curvas_zm")
            lines = []
            for geometry, elevation in zip(curves.geometries, curves.attributes["cota"],
                                           strict=True):
                closed = bool(np.array_equal(geometry.coords[0], geometry.coords[-1]))
                lines.append(contours_mod.ContourLine(
                    geometry.coords[:-1] if closed else geometry.coords, float(elevation),
                    False, closed))
            imports: list[tuple[Any, ...]] = [
                ("Contorno", CRS, {"layer": "contorno", "role": "boundary"},
                 lambda out: out.boundary("Contorno", boundary.geometries)),
                ("Curvas", ED50,
                 {"layer": "curvas_zm", "role": "contours", "elevation_field": "cota"},
                 lambda out: out.contours("Curvas", lines)),
            ]
            found = []
            for name, crs, settings, write in imports:
                spec = self.source_spec(gis_content.GPKG_LAYER, name, "capas.gpkg", crs=crs,
                                        settings=settings)
                handle = self.begin(provenance.IMPORT_VECTOR)
                with store.ResultWriter(self.project, handle) as out:
                    out.declare_input(spec)
                    write(out)
                    (record,) = out.commit(message=f"Capa «{settings['layer']}» importada")
                steps = list(out.originals([copy]))
                found.append((out.input, record, steps[-1].result.state))
        (bnd_input, bnd, _), (cnt_input, cnt, _) = found
        self.assertEqual(
            [(entry.kind, entry.reader, entry.layer, entry.content_settings_keys, state)
             for entry, _record, state in found],
            [("vector", "gis.gpkg_layer@1", "contorno", ("role",), "not_applicable"),
             ("vector", "gis.gpkg_layer@1", "curvas_zm", ("elevation_field", "role"),
              "not_applicable")],
        )
        self.assertEqual(
            [(r.name, r.locator, r.immutable, r.input_uid, r.crs_epsg) for r in (bnd, cnt)],
            [("gis_bnd_contorno", f"gis_bnd_contorno_{self.tag(bnd_input)}", True,
              bnd_input.uid, 25830),
             ("gis_cnt_curvas", f"gis_cnt_curvas_{self.tag(cnt_input)}", True, cnt_input.uid,
              23030)],
        )
        self.assertEqual(self.query(
            "SELECT table_name, geometry_type_name, srs_id, z FROM gpkg_geometry_columns "
            "WHERE table_name LIKE 'gis%' ORDER BY 1"),
            [(bnd.locator, "MULTIPOLYGON", 25830, 0), (cnt.locator, "LINESTRING", 23030, 1)])
        self.assertEqual(self.query("SELECT organization, organization_coordsys_id, definition "
                                    "FROM gpkg_spatial_ref_sys WHERE srs_id = 23030"),
                         [("EPSG", 23030, ED50.wkt1)])
        (description,) = self.query("SELECT description FROM gpkg_contents WHERE table_name = ?",
                                    cnt.locator)
        self.assertIn("«Curvas»", description[0])
        self.assertIn("EPSG:5782", description[0])
        rows = self.query(f'SELECT geom, role FROM "{bnd.locator}" ORDER BY fid')
        self.assertEqual([row[1] for row in rows], ["boundary"] * len(boundary.geometries))
        for row, geometry in zip(rows, boundary.geometries, strict=True):
            got, expected = _rings(wkb.decode_geometry(row[0]).coords), _rings(geometry.coords)
            self.assertEqual(len(got), len(expected))
            self.assertTrue(all(np.array_equal(a, b) for a, b in zip(got, expected, strict=True)))
        rows = self.query(f'SELECT geom, elevation, closed FROM "{cnt.locator}" ORDER BY fid')
        self.assertEqual([row[1:] for row in rows],
                         [(line.elevation, int(line.closed)) for line in lines])
        for row, geometry in zip(rows, curves.geometries, strict=True):
            decoded = wkb.decode_geometry(row[0])
            self.assertEqual(decoded.srs_id, 23030)
            self.assertTrue(np.array_equal(decoded.coords, geometry.coords))
        for record, entry in ((bnd, bnd_input), (cnt, cnt_input)):
            self.assertEqual(record.content_sha256, self.read_hash(
                builtin.GPKG_LAYER, "vector", self.project.database_path,
                {"layer": record.locator}))
            self.assert_protected(record.locator, entry.name)
        self.assertFalse((self.root / "originals").exists())
        self.assert_no_absolute_paths()


class ImportJobTest(ImportCase):
    def test_imports_from_a_job_register_their_input(self) -> None:
        """RF-008-20, RF-008-07, RF-008-53, RF-006-26: una importación hecha en un trabajo de
        la 004 se incorpora con ``ingest_job`` y ``ResultWriter.write``: la rejilla de origen
        que dejó en ``out/`` se copia con su huella a su ubicación con el uid de su entrada,
        registrada en la misma transacción, con el trabajo y su ejecutor; unos puntos (solo
        tablas) dejan también su entrada, y su original se guarda después desde la copia
        verificada del trabajo (``in/``)."""
        folder = self.tmp / "trabajo"
        produced = folder / "out" / "src.tif"
        produced.parent.mkdir(parents=True)
        source = reader_mod.read_geotiff(self.sources / "f32_strip.tif")
        raster = raster_mod.Raster(source.grid, source.values, CRS, VERTICAL)
        geotiff.GeoTiffIO().write(raster, produced, profile="project")
        digest = gis_content.raster_digest(raster, {})
        sha = _sha(produced)
        outcome = operations.JobOutcome(
            "job-0043", "succeeded", "job_thread", label="Importar MDT", folder=folder,
            outputs=(operations.OutputPrint("out/src.tif", sha, "source_grid",
                                            size=produced.stat().st_size),),
        )
        spec = self.source_spec(gis_content.GEOTIFF, "MDT Norte", "f32_strip.tif")
        handle = self.begin(provenance.IMPORT_DTM, executor="job_thread")
        with store.ResultWriter(self.project, handle) as out:
            out.declare_input(spec)
            out.copy_file(provenance.SOURCE_GRID, "MDT Norte", outcome.file("source_grid"),
                          content=digest, sha256=sha)
            result = operations.ingest_job(self.project, handle, outcome, out.write,
                                           message="MDT importado en un trabajo")
        (record,) = result.outputs
        entry = out.input
        self.assertEqual(
            (record.locator, record.input_uid, record.content_sha256, record.crs_epsg),
            (f"rasters/gis_src_mdt_norte_{self.tag(entry)}.tif", entry.uid,
             digest.content_sha256, 25830),
        )
        self.assertEqual(_sha(self.root / record.locator), sha)
        row = self.operation(handle.uid)
        self.assertEqual((row["status"], row["executor"], row["job_uid"]),
                         ("done", "job_thread", "job-0043"))

        verified = folder / "in" / "taludes.csv"
        verified.parent.mkdir()
        shutil.copyfile(self.sources / "taludes.csv", verified)
        table = csv_tables.read_table(verified, encoding="utf-8", separator=";", header_row=0)
        points, lines, _report = points_mod.points_from_rows(
            table.columns, table.rows,
            points_mod.ColumnMapping(x=1, y=2, z=3, point_id=0, code=4, line=5), ",",
            row_numbers=table.lines)
        spec = self.source_spec(gis_content.POINTS_TEXT, "Taludes", "taludes.csv",
                                settings=POINT_SETTINGS)
        outcome = operations.JobOutcome("job-0044", "succeeded", "job_thread",
                                        label="Importar puntos", folder=folder)
        handle = self.begin(provenance.IMPORT_POINTS, executor="job_thread")
        with store.ResultWriter(self.project, handle) as out:
            out.declare_input(spec)
            out.points("Taludes", points)
            out.breaklines("Taludes", lines)
            result = operations.ingest_job(self.project, handle, outcome, out.write,
                                           message="20 puntos y 4 líneas en un trabajo")
        self.assertEqual([record.name for record in result.outputs],
                         ["gis_pts_taludes", "gis_brk_taludes"])
        self.assertEqual(out.input.operation_uid, handle.uid)
        outcome = list(out.originals([verified]))[-1].result
        self.assertEqual((outcome.state, outcome.files[0].sha256),
                         ("stored", _sha(self.sources / "taludes.csv")))


class ReuseTest(ImportCase):
    def test_same_file_is_reused_and_another_crs_substitutes(self) -> None:
        """RF-008-54, RF-008-11, RF-008-52, RF-006-04: importar otra vez el mismo GeoTIFF con
        los mismos ajustes avisa y reutiliza su entrada: la importación queda «cancelada» con
        el aviso, con su evento, y nada escrito. Declarado en ED50 es una sustitución: sin
        decir a qué entrada sustituye se rechaza sin escribir nada; con ella y el motivo, la
        entrada nueva la sustituye, la anterior y lo importado de ella quedan «sustituidos»
        con su ubicación, su fichero y su hash, y lo importado nuevo toma su nombre en otra
        ubicación. Sin CRS declarado no se clasifica (``core.input_crs_missing``): nunca se
        supone."""
        _, first_out, (first,) = self.import_grid("f32_nocrs.tif")
        entry = first_out.input
        first_sha = _sha(self.root / first.locator)
        before = self.state()

        handle, out, found = self.import_grid("f32_nocrs.tif")
        self.assertIsInstance(found, inputs.Reuse)
        self.assertEqual((found.input.uid, out.reused, out.input), (entry.uid, found, None))
        self.assertIn("«MDT Norte» ya está registrada con el mismo contenido", found.text)
        row = self.operation(handle.uid)
        self.assertEqual((row["status"], row["status_reason"]), ("cancelled", found.text))
        with self.project.read() as conn:
            reused = events.read_events(conn, events.EventKind.INPUT_REUSED)
        self.assertEqual([event.entity_uid for event in reused], [entry.uid])
        self.assertEqual(self.state(), before)

        spec = self.source_spec(gis_content.GEOTIFF, "MDT Norte", "f32_nocrs.tif", crs=ED50)
        found = store.classify_source(self.project, spec)
        self.assertIsInstance(found, inputs.Substitute)
        self.assertEqual(found.input.uid, entry.uid)
        self.assertIn("EPSG:25830 → EPSG:23030", found.describe())
        handle = self.begin(provenance.IMPORT_DTM)
        with (self.assertRaises(prov_messages.ProvenanceError) as caught,
              store.ResultWriter(self.project, handle) as out):
            out.declare_input(spec)
        self.assertEqual(caught.exception.code, "core.input_substitution_required")
        self.assertEqual(self.operation(handle.uid)["status"], "failed")
        self.assertEqual(self.state(), before)

        _, out, (second,) = self.import_grid("f32_nocrs.tif", crs=ED50,
                                             previous_uid=entry.uid, reason=REASON)
        new = out.input
        self.assertEqual((new.previous_uid, dict(new.crs_h), dict(new.crs_v)),
                         (entry.uid, {"epsg": 23030}, {"epsg": 5782}))
        with self.project.read() as conn:
            old = inputs.get(conn, entry.uid)
        self.assertEqual((old.status, old.status_reason), ("superseded", REASON))
        kept = self.dataset(first.uid)
        self.assertEqual((kept.status, kept.locator, kept.content_sha256),
                         ("superseded", first.locator, first.content_sha256))
        self.assertEqual(_sha(self.root / first.locator), first_sha)
        self.assertEqual((second.name, second.crs_epsg, second.input_uid),
                         ("gis_src_mdt_norte", 23030, new.uid))
        self.assertEqual(second.locator, f"rasters/gis_src_mdt_norte_{self.tag(new)}.tif")
        self.assertEqual(sorted(self.files()), sorted([first.locator, second.locator]))

        undeclared = self.source_spec(gis_content.GEOTIFF, "Sin CRS", "f32_nocrs.tif",
                                      crs=None)
        with self.assertRaises(prov_messages.ProvenanceError) as caught:
            store.classify_source(self.project, undeclared)
        self.assertEqual(caught.exception.code, "core.input_crs_missing")


class ImportFailureTest(ImportCase):
    def test_failure_while_registering_the_input_leaves_nothing(self) -> None:
        """RF-006-28, RF-008-19, RF-008-07: otra fuente con el nombre lógico de una entrada
        activa se rechaza al declararla (``core.input_name_taken``, antes de escribir nada); y
        si la transacción que registra la entrada falla (un ``software`` que la importación no
        declara, ya con el fichero en su sitio), la importación queda «fallida» con su motivo
        y ni la entrada, ni lo importado, ni su fichero, ni un temporal quedan en el proyecto,
        que sigue en escritura; lo importado antes no cambia."""
        self.import_grid("f32_strip.tif")
        before = self.state()
        spec = self.source_spec(gis_content.GEOTIFF, "MDT Norte", "f64_strip.tif")
        handle = self.begin(provenance.IMPORT_DTM)
        with (self.assertRaises(prov_messages.ProvenanceError) as caught,
              store.ResultWriter(self.project, handle) as out):
            out.declare_input(spec)
        self.assertEqual(caught.exception.code, "core.input_name_taken")
        row = self.last_operation()
        self.assertEqual(row["status"], "failed")
        self.assertIn("MDT Norte", row["status_reason"])
        self.assertEqual(self.state(), before)

        with self.assertRaises(ValueError):
            self.import_grid("f64_strip.tif", name="MDT Sur", software={"pyproj": "3.8.0"})
        self.assertEqual(self.last_operation()["status"], "failed")
        self.assertEqual(self.state(), before)
        self.assertTrue(self.project.writable)
        self.assertEqual(operations.claimed_paths(self.project), frozenset())


class SourceInputTest(unittest.TestCase):
    """``source_input`` sin proyecto: lo que declara una importación de la 006."""

    FILES = (input_model.SourceFile("fuentes/mdt.tif", "main", "original"),)
    PRINTS = (input_model.SourcePrint("0" * 64, size=10, mtime_ns=1),)

    def spec(self, reader_id: str, *, crs: Any = CRS, vertical: Any = VERTICAL,
             settings: dict[str, Any] | None = None, declarations: Any = None) -> Any:
        kind = provenance.input_kind(reader_id)
        if declarations is None:
            declarations = store.source_declarations(reader_id, crs, vertical, settings)
        data = "ab" * 32
        digest = encoder.ContentDigest(data, encoder.content_sha256(kind, declarations, data),
                                       encoder.NORMALIZER, reader_id)
        return store.source_input(reader_id, "MDT", files=self.FILES, file_prints=self.PRINTS,
                                  digest=digest, crs=crs, vertical=vertical, settings=settings)

    def test_settings_of_each_reader_and_what_is_content(self) -> None:
        """RF-006-26, RF-008-07, RF-006-04 (plan §5.6.2 y §5.6.3): la entrada de una
        importación de ``gis`` lleva su tipo (el de su lector), sus CRS declarados (EPSG, una
        referencia local o la altura elipsoidal) y, de sus ajustes, solo los de lectura de su
        lector; son contenido el sin dato forzado, las columnas, el tipo de línea, el papel y
        el campo de cota; un CRS sin declarar queda sin declarar (lo rechaza el registro). Un
        ajuste de otro lector, un papel de capa que no es de la 006, una capa o unas columnas
        que faltan, un lector que no es de una importación de la 006 o un hash con otras
        declaraciones son errores del programa."""
        spec = self.spec("gis.geotiff@1", settings={"nodata_override": -32768.0})
        self.assertEqual((spec.kind, spec.module, spec.layer, spec.content_settings_keys),
                         ("raster", "gis", None, ("nodata_override",)))
        self.assertEqual(dict(spec.declarations), {
            "conventions": {"nodata_override": -32768.0},
            "crs_h": {"epsg": 25830}, "crs_v": {"epsg": 5782}})
        local = CATALOG.local_vertical("NP-0 del plano 3")
        self.assertEqual(dict(self.spec("gis.xyz_grid@1", vertical=local).crs_v),
                         {"local": "NP-0 del plano 3"})
        ellipsoidal = import_geoblender("gis.crs").ELLIPSOIDAL_ETRS89
        self.assertEqual(dict(self.spec("gis.asc@1", vertical=ellipsoidal).crs_v),
                         {"ellipsoidal": 4937})
        self.assertIsNone(self.spec("gis.geotiff@1", crs=None).crs_h)
        layer = self.spec("gis.gpkg_layer@1", settings={"layer": "curvas", "role": "contours",
                                                        "elevation_field": "cota"})
        self.assertEqual((layer.kind, layer.layer, layer.content_settings_keys),
                         ("vector", "curvas", ("elevation_field", "role")))
        text = self.spec("gis.points_text@1", settings=POINT_SETTINGS)
        self.assertEqual((text.kind, text.content_settings_keys),
                         ("table", ("columns", "line_kind")))
        for reader_id, settings in (
            ("gis.geotiff@1", {"separator": ";"}),
            ("gis.gpkg_layer@1", {"role": "contours"}),
            ("gis.gpkg_layer@1", {"layer": "curvas", "role": "huecos"}),
            ("gis.points_text@1", {"encoding": "utf-8", "separator": ";", "decimal": ","}),
        ):
            with self.subTest(lector=reader_id, ajustes=settings), \
                    self.assertRaises(ValueError):
                self.spec(reader_id, settings=settings)
        with self.assertRaises(ValueError):
            self.spec("core.gpkg_layer@1")
        with self.assertRaises(ValueError):
            self.spec("gis.geotiff@1", declarations={"conventions": {}, "crs_h": None,
                                                     "crs_v": None})


if __name__ == "__main__":
    unittest.main()
