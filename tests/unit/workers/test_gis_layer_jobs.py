# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos de la topografía que añade la T29 (spec 006; RF-006-12, RF-006-14, RF-006-16,
RF-006-17, RF-006-26, RF-006-28; plan 006 §5.3.4 y §5.6.4).

- ``gis_import_vector``: una capa de un GeoPackage, copiado a ``in/`` con su ``-wal``, leída
  sobre una copia consolidada con el papel que declara la persona (puntos, líneas de rotura,
  curvas de nivel o contorno), con el ``ContentDigest`` de ``gis.gpkg_layer@1``;
- ``gis_import_points`` informa también de los puntos duplicados (RF-006-12);
- ``gis_tin_contours``: el TIN desde curvas de nivel de ``gis.tin_from_contours`` con
  ``PureTriangulator`` (o, con conflictos, solo ``conflicts.json``);
- ``gis_convert_surface``: una rejilla del proyecto en TIN o un TIN en la rejilla del
  proyecto (RF-006-17), con el hash de su salida.

Cada ``main(ctx)`` corre en el hilo, con el ``WorkerContext`` de la 004 y su envoltorio de
``workers/``; datos pequeños de ``tests/data/gis``.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.provenance_checks import source_changes, source_state
from tests.support.repo import ROOT

gis = import_geoblender("gis")
gis_jobs = import_geoblender("gis.jobs")
gis_content = import_geoblender("gis.content")
gis_store = import_geoblender("gis.store")
provenance = import_geoblender("gis.provenance")
gis_tin = import_geoblender("gis.tin")
contours_mod = import_geoblender("gis.contours")
points_mod = import_geoblender("gis.points")
vector_mod = import_geoblender("gis.vector")
geotiff = import_geoblender("gis.geotiff")
geotiff_reader = import_geoblender("gis.geotiff.reader")
georef = import_geoblender("core.georef")
core_gpkg = import_geoblender("core.gpkg")
readers = import_geoblender("core.content.readers")
csv_tables = import_geoblender("interop.csv_tables")
protocol = import_geoblender("jobs.protocol")
job_paths = import_geoblender("jobs.paths")
worker_api = import_geoblender("jobs.worker_api")

DATA = ROOT / "tests" / "data" / "gis"
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
CRS_JSON = {"epsg": 25830}
VERTICAL_JSON = {"epsg": 5782}
ORIGIN = georef.GeoOrigin(700000, 4400000, 0)
OPERATION_UID = "0f3c2a5e-7b1d-4c9e-8a6f-2d4b6c8e0a29"
LAYERS = {  # capa: papel, ajustes de lectura
    "puntos_z": ("points", {}),
    "roturas_z": ("breaklines", {}),
    "curvas_zm": ("contours", {"elevation_field": "cota"}),
    "contorno": ("boundary", {}),
}
POINT_SETTINGS = {"encoding": "utf-8", "separator": ";", "decimal": ",", "header_row": 0,
                  "columns": {"point_id": 0, "x": 1, "y": 2, "z": 3, "code": 4, "line": 5},
                  "line_kind": "hard"}


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    test.assertEqual((got.shape, got.dtype), (expected.shape, expected.dtype))
    test.assertTrue(np.array_equal(got.view(np.uint8), expected.view(np.uint8)))


def _circle(radius: float, z: float, count: int = 24) -> Any:
    angle = 2.0 * np.pi * np.arange(count) / count
    rows = np.column_stack([700050.0 + radius * np.cos(angle),
                            4400050.0 + radius * np.sin(angle), np.full(count, z)])
    return points_mod.Breakline(f"C{z:g}", np.vstack([rows, rows[:1]]))


class _LayerJobCase(unittest.TestCase):
    """Un trabajo de la T29 en el hilo con su envoltorio y las fuentes en ``fuentes/``."""

    def setUp(self) -> None:
        self.base = self.enterContext(_support.jobs_tmp(prefix="gb29j-"))
        self.sources = self.base / "fuentes"
        self.sources.mkdir()
        shutil.copyfile(DATA / "gpkg" / "capas.gpkg", self.sources / "capas.gpkg")
        shutil.copyfile(DATA / "points" / "errores.csv", self.sources / "errores.csv")
        self.inputs = self.base / "entradas"
        self.inputs.mkdir()
        self.enterContext(mock.patch.dict(readers._REGISTRY))
        self.addCleanup(gis_content.use_table_reader, gis_content.use_table_reader(None))
        before = source_state(self.sources)
        self.addCleanup(self._untouched, before)

    def _untouched(self, before: Any) -> None:
        changes = source_changes(before, source_state(self.sources))
        self.assertEqual(changes, [], "la carpeta de las fuentes cambió (RF-006-10)")

    def run_job(self, worker: str, params: dict, *, inputs: dict | None = None,
                paths: dict | None = None) -> tuple[dict, Any, Any]:
        request = protocol.new_request(worker, label=f"Prueba de {worker}", owner="gis",
                                       params=params, operation_uid=OPERATION_UID,
                                       environment="blender", timeout_s=600.0,
                                       grace_s=gis_jobs.CANCEL_GRACE_S)
        folder = job_paths.job_dir(self.base / "jobs", request.job_uid).create()
        copied = {name: folder.copy_input(path, name) for name, path in (inputs or {}).items()}
        protocol.write_request(folder, dataclasses.replace(request, inputs=copied))
        ctx = worker_api.WorkerContext(protocol.read_request(folder), folder,
                                       worker_api.QueueSink(), paths=paths)
        summary = import_geoblender(f"workers.{worker}").main(ctx)
        json.dumps(summary, allow_nan=False)
        found = sorted(path.relative_to(folder.path).as_posix()
                       for path in folder.outputs_dir.rglob("*") if path.is_file())
        self.assertEqual(found, sorted(ref.path for ref in ctx.outputs))
        self.assertNotIn(str(self.base).replace("\\", "/"),
                         (folder.path / job_paths.REQUEST_FILE).read_text("utf-8")
                         .replace("\\\\", "/"))
        return summary, ctx, folder

    @staticmethod
    def output(ctx: Any, folder: Any, role: str) -> Path:
        (ref,) = [ref for ref in ctx.outputs if ref.role == role]
        return folder.path / ref.path


class ImportVectorJobTest(_LayerJobCase):
    def test_each_role_reads_its_layer_with_its_digest(self) -> None:
        """RF-006-12, RF-006-26, RF-008-09: ``gis_import_vector`` copia el GeoPackage a
        ``in/`` (``--path``), lee la capa con su papel y deja puntos, líneas de rotura, curvas
        (con su cota) o el contorno con las coordenadas de la capa bit a bit, su informe y el
        ``ContentDigest`` de ``gis.gpkg_layer@1`` con las declaraciones (el CRS, el de la capa;
        el datum, el declarado)."""
        source = self.sources / "capas.gpkg"
        copy = vector_mod.copy_source(source, self.base / "copia")
        for layer, (role, extra) in LAYERS.items():
            with self.subTest(capa=layer):
                settings = {"layer": layer, "role": role, **extra}
                params = {"reader": gis_content.GPKG_LAYER.id, "name": layer,
                          "settings": settings, "crs": None, "vertical": VERTICAL_JSON,
                          "size": source.stat().st_size}
                summary, ctx, folder = self.run_job(
                    gis_jobs.IMPORT_VECTOR, params,
                    paths={gis_jobs.path_name("main"): source})
                features = vector_mod.read_layer(copy, layer)
                self.assertEqual((summary["crs"], summary["vertical"], summary["role"]),
                                 (CRS_JSON, VERTICAL_JSON, role))
                self.assertEqual(summary["read"], features.report.read)
                declarations = gis_store.source_declarations(gis_content.GPKG_LAYER.id, CRS,
                                                             VERTICAL, settings)
                request = gis_content.GPKG_LAYER.request("vector", declarations,
                                                         {"main": source}, settings)
                self.assertEqual(gis_jobs.digest_of(summary["source"]["digest"]),
                                 readers.read_content(gis_content.GPKG_LAYER, request))
                output = self.output(ctx, folder, gis_jobs.LAYER_OUTPUTS[role].role)
                if role == "points":
                    expected, _report = points_mod.points_from_features(features)
                    got = gis_jobs.read_points(output)
                    _same(self, got.xyz, expected.xyz)
                    self.assertEqual(got.point_ids, expected.point_ids)
                elif role == "breaklines":
                    expected, _report = points_mod.breaklines_from_features(features)
                    got = gis_jobs.read_lines(output)
                    self.assertEqual(len(got), len(expected))
                    for line, wanted in zip(got, expected, strict=True):
                        _same(self, line.xyz, wanted.xyz)
                elif role == "contours":
                    expected, _report = contours_mod.contours_from_features(
                        features, elevation_field="cota")
                    got = gis_jobs.read_contours(output)
                    self.assertEqual([line.elevation for line in got], [806.0, 816.0])
                    for line, wanted in zip(got, expected, strict=True):
                        _same(self, line.xyz, wanted.xyz)
                else:
                    expected, _report = points_mod.polygons_from_features(features)
                    got = gis_jobs.read_polygons(output)
                    self.assertEqual(len(got), len(expected))
                    for polygon_list, wanted in zip(got, expected, strict=True):
                        for polygon, rings in zip(polygon_list, wanted, strict=True):
                            for ring, ring_expected in zip(polygon, rings, strict=True):
                                _same(self, ring, np.ascontiguousarray(ring_expected[:, :2]))
                report = json.loads(self.output(ctx, folder, "report").read_text("utf-8"))
                self.assertEqual(report["read"], features.report.read)
                # T50 (RNF-006-09): el hash de la tabla que será lo importado, como la
                # escribirá la orden (gis.store.table_digest), calculado en el trabajo.
                family = provenance.layer_family(role)
                rows = {"points": lambda: gis_store.point_rows(got, CRS.epsg),
                        "breaklines": lambda: gis_store.breakline_rows(got, CRS.epsg),
                        "contours": lambda: gis_store.contour_rows(got, CRS.epsg),
                        "boundary": lambda: gis_store.boundary_rows(
                            gis_jobs.read_boundary(output, CRS.epsg), (), CRS.epsg)}[role]()
                self.assertEqual(
                    summary["outputs"][gis_jobs.LAYER_OUTPUTS[role].role]["digest"],
                    gis_jobs.digest_json(gis_store.table_digest(family, rows, CRS)))

    def test_pending_wal_and_undeclared_datum(self) -> None:
        """RF-006-12, RF-006-10, RF-006-04: con un ``-wal`` pendiente junto a la fuente, el
        trabajo lo copia con ella y lee también lo que solo está en él (las 4 roturas y las 3
        del ``-wal``); sin datum vertical declarado, o con una capa que no está, falla
        explicado sin dejar nada en ``out/``."""
        from tests.unit.gis.test_vector_read import WAL_LINES, _killed_writer

        source = self.base / "wal" / "capas.gpkg"
        source.parent.mkdir()
        shutil.copyfile(self.sources / "capas.gpkg", source)
        _killed_writer(source, [core_gpkg.encode_geometry("LINESTRING", line, 25830, True)
                                for line in WAL_LINES])
        settings = {"layer": "roturas_z", "role": "breaklines"}
        params = {"reader": gis_content.GPKG_LAYER.id, "name": "Roturas",
                  "settings": settings, "crs": CRS_JSON, "vertical": VERTICAL_JSON,
                  "size": source.stat().st_size}
        paths = {gis_jobs.path_name("main"): source}
        summary, ctx, folder = self.run_job(gis_jobs.IMPORT_VECTOR, params, paths=paths)
        lines = gis_jobs.read_lines(self.output(ctx, folder, "breaklines"))
        self.assertEqual(len(lines), 7)
        for line, wanted in zip(lines[4:], WAL_LINES, strict=True):
            _same(self, line.xyz, wanted)
        self.assertEqual(sorted(path.name for path in folder.inputs_dir.iterdir()),
                         ["source_main.gpkg", "source_main.gpkg-wal"])
        for changed, code in (({"vertical": None}, "gis.vertical_undeclared"),
                              ({"settings": {"layer": "no_existe", "role": "points"}},
                               "gis.layer_not_found")):
            with self.subTest(fallo=code), self.assertRaises(worker_api.JobFailed) as caught:
                self.run_job(gis_jobs.IMPORT_VECTOR, {**params, **changed}, paths=paths)
            self.assertEqual(caught.exception.code, code)


class ImportPointsDuplicatesTest(_LayerJobCase):
    def test_points_report_their_duplicates(self) -> None:
        """RF-006-12: el informe de ``gis_import_points`` dice los puntos duplicados (a ≤ 1 mm
        en planta de otro anterior): en ``errores.csv``, P 7 (se fundiría) y P 9 (en
        conflicto)."""
        source = self.sources / "errores.csv"
        params = {"reader": gis_content.POINTS_TEXT.id, "name": "Errores",
                  "settings": POINT_SETTINGS, "crs": CRS_JSON, "vertical": VERTICAL_JSON,
                  "size": source.stat().st_size, "tol_xy": 0.001, "tol_z": 0.01}
        summary, ctx, folder = self.run_job(gis_jobs.IMPORT_POINTS, params,
                                            paths={gis_jobs.path_name("main"): source})
        report = json.loads(self.output(ctx, folder, "report").read_text("utf-8"))
        self.assertEqual((summary["duplicates"], report["duplicates"]), (2, 2))


class TinContoursJobTest(_LayerJobCase):
    def test_tin_from_contours_and_its_conflicts(self) -> None:
        """RF-006-16, RF-006-26, RF-006-14: ``gis_tin_contours`` da el TIN de
        ``tin_from_contours`` con ``PureTriangulator`` (vértices, triángulos y origen de cada
        vértice bit a bit; el % de planos antes y después en el informe) con el ``meta`` de la
        operación y su hash de ``core.npz_mesh@1``; dos curvas que se cruzan a distinta cota
        dejan solo ``conflicts.json``."""
        contours = [_circle(30.0, 850.0), _circle(20.0, 855.0), _circle(10.0, 860.0)]
        spots = points_mod.PointSet(np.array([[700050.0, 4400050.0, 863.0]]), ("A1",), ("",),
                                    (2,))
        gis_jobs.write_lines(self.inputs / "lines.npz", contours)
        gis_jobs.write_points(self.inputs / "points.npz", spots)
        params = {"name": "Cerro", "origin": gis_jobs.origin_json(ORIGIN), "crs": CRS_JSON,
                  "vertical": VERTICAL_JSON, "densify_m": 5.0, "max_passes": 3,
                  "max_flat_pct": 1.0, "tol_xy": 0.001, "tol_z": 0.01,
                  "duplicate_policy": "ask", "count": 80}
        inputs = {"lines": self.inputs / "lines.npz", "points": self.inputs / "points.npz"}
        summary, ctx, folder = self.run_job(gis_jobs.TIN_CONTOURS, params, inputs=inputs)
        tin = gis_tin.load_tin(self.output(ctx, folder, "tin"))
        expected, report = gis.tin_from_contours(
            contours, spot_heights=spots, triangulator=gis.PureTriangulator(), origin=ORIGIN,
            densify_m=5.0, max_passes=3, max_flat_pct=1.0, name="Cerro")
        _same(self, tin.vertices, expected.vertices)
        _same(self, tin.faces, expected.faces)
        _same(self, tin.vertex_source, expected.vertex_source)
        self.assertEqual((tin.meta["operation_uid"], tin.meta["triangulator"]),
                         (OPERATION_UID, "pure@1"))
        self.assertEqual(summary["triangulator"], "pure@1")
        found = json.loads(self.output(ctx, folder, "report").read_text("utf-8"))
        self.assertEqual((found["flat_pct_before"], found["flat_pct"]),
                         (report.flat_pct_before, report.flat_pct))
        self.assertEqual(gis_jobs.digest_of(summary["outputs"]["tin"]["digest"]),
                         gis_content.tin_digest(tin, tin.meta, {}))
        crossing = points_mod.Breakline("X870", np.array([[700050.0, 4400000.0, 870.0],
                                                          [700050.0, 4400100.0, 870.0]]))
        gis_jobs.write_lines(self.inputs / "crossing.npz", [*contours, crossing])
        summary, ctx, folder = self.run_job(gis_jobs.TIN_CONTOURS, params,
                                            inputs={"lines": self.inputs / "crossing.npz"})
        self.assertGreater(summary["conflicts"], 0)
        error = gis_jobs.read_conflicts(self.output(ctx, folder, "conflicts"))
        self.assertEqual(error.code, "gis.constraint_conflicts")
        self.assertEqual([ref.role for ref in ctx.outputs], ["conflicts"])


class ConvertSurfaceJobTest(_LayerJobCase):
    def test_grid_to_tin_and_back(self) -> None:
        """RF-006-17, RF-006-26: ``gis_convert_surface`` lleva una rejilla del proyecto a un
        TIN (el de ``raster_to_tin``, con el ``meta`` de la operación) y ese TIN a la rejilla
        (la de ``tin_to_raster``: la ida y vuelta da las mismas cotas), cada uno con el hash
        de su lector."""
        found = geotiff_reader.read_geotiff(DATA / "geotiff" / "f64_strip.tif")
        raster = gis.Raster(found.grid, found.values, CRS, VERTICAL)
        geotiff.GeoTiffIO().write(raster, self.inputs / "source.tif", profile="project")
        params = {"direction": "grid_to_tin", "name": "MDT", "crs": CRS_JSON,
                  "vertical": VERTICAL_JSON, "count": raster.values.size}
        summary, ctx, folder = self.run_job(gis_jobs.CONVERT_SURFACE, params,
                                            inputs={"source": self.inputs / "source.tif"})
        tin = gis_tin.load_tin(self.output(ctx, folder, "tin"))
        expected = gis_tin.raster_to_tin(raster, name="MDT")
        _same(self, tin.vertices, expected.vertices)
        _same(self, tin.faces, expected.faces)
        self.assertEqual(tin.meta["operation_uid"], OPERATION_UID)
        self.assertEqual(gis_jobs.digest_of(summary["outputs"]["tin"]["digest"]),
                         gis_content.tin_digest(tin, tin.meta, {}))
        shutil.copyfile(self.output(ctx, folder, "tin"), self.inputs / "source.npz")
        params = {"direction": "tin_to_grid", "name": "MDT", "crs": CRS_JSON,
                  "vertical": VERTICAL_JSON, "target": gis_jobs.grid_json(raster.grid),
                  "count": raster.values.size}
        summary, ctx, folder = self.run_job(gis_jobs.CONVERT_SURFACE, params,
                                            inputs={"source": self.inputs / "source.npz"})
        grid = geotiff_reader.read_geotiff(self.output(ctx, folder, "project_grid"))
        back = gis_tin.tin_to_raster(tin, raster.grid, crs=CRS, vertical=VERTICAL)
        _same(self, grid.values, back.values)
        valid = np.isfinite(back.values)
        self.assertLessEqual(float(np.max(np.abs(back.values[valid]
                                                 - raster.values[valid]))), 1e-6)
        self.assertEqual(
            gis_jobs.digest_of(summary["outputs"]["project_grid"]["digest"]),
            gis_content.raster_digest(gis.Raster(grid.grid, grid.values, CRS, VERTICAL), {}))


if __name__ == "__main__":
    unittest.main()
