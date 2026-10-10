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

Cada prueba crea su proyecto (``create_project`` con un reloj simulado), registra los
parámetros de ``gis``, tres tipos de operación de ``gis.provenance`` y los lectores que
faltan, y deja los registros como estaban.
"""

from __future__ import annotations

import hashlib
import json
import os
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
from tests.support.provenance_contract import registered, snapshot
from tests.support.resources import requires

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


if __name__ == "__main__":
    unittest.main()
