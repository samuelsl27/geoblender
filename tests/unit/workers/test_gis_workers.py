# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos de la topografía (spec 006, T26; RF-006-28, RF-006-26; RF-008-09, RF-008-20;
plan 006 §5.3.4 y §5.6.4; ADR-0010).

Lo pesado de la 006 va a los trabajos de la 004 (``gis/jobs.py``: un ``WorkerInfo`` con su
estimador y su función ``run`` por tipo, y un envoltorio ``workers/gis_*.py`` de la misma
función que registra antes los lectores de ``gis``). Aquí:

- cada ``main(ctx)`` con el ``WorkerContext`` de la 004 (en el hilo, como el ejecutor en hilo)
  deja sus salidas en ``out/`` con su huella sha256 y, en su resumen, el ``ContentDigest`` de
  la fuente (importaciones: el mismo que da ``core_content_hash``) y de cada fichero que será
  un dato del proyecto, con los lectores de T40, y las huellas de la fuente;
- cancelar a mitad (también con todo escrito, justo antes de terminar) deja ``out/`` sin
  resultados; un fallo explicado (``GisError``) es un ``JobFailed`` con su código y su texto;
- la petición nunca lleva una ruta: las fuentes van aparte (``--path``) y lo del proyecto,
  copiado a ``in/`` (ARQ-11);
- una reproyección va a proceso aparte con ``--site`` (las ruedas: pyproj) y se cancela en
  ≤ 2 s; ``jobs/`` no importa ``gis`` (ARQ-07).

Datos sintéticos de ``tests/data/gis`` (T01), pequeños: cada trabajo en el hilo tarda
centésimas. La reproyección en proceso aparte se lanza al empezar el módulo y la recoge
``SubprocessTest``.
"""

import ast
import dataclasses
import importlib.util
import json
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.provenance_checks import source_changes, source_state
from tests.support.repo import EXTENSION_DIR, ROOT

gis_jobs = import_geoblender("gis.jobs")
gis = import_geoblender("gis")
gis_content = import_geoblender("gis.content")
gis_dtm = import_geoblender("gis.dtm")
gis_store = import_geoblender("gis.store")
gis_tin = import_geoblender("gis.tin")
geotiff = import_geoblender("gis.geotiff")
geotiff_reader = import_geoblender("gis.geotiff.reader")
asc_mod = import_geoblender("gis.asc")
xyz_mod = import_geoblender("gis.xyz_grid")
points_mod = import_geoblender("gis.points")
georef = import_geoblender("core.georef")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
encoder = import_geoblender("core.content.encoder")
checks = import_geoblender("core.provenance.checks")
csv_tables = import_geoblender("interop.csv_tables")
catalog = import_geoblender("jobs.catalog")
content_hash = import_geoblender("jobs.content_hash")
protocol = import_geoblender("jobs.protocol")
job_paths = import_geoblender("jobs.paths")
policy = import_geoblender("jobs.policy")
runner_mod = import_geoblender("jobs.runner")
interpreter = import_geoblender("jobs.interpreter")
worker_api = import_geoblender("jobs.worker_api")
job_messages = import_geoblender("jobs.messages")
records = import_geoblender("jobs.records")

DATA = ROOT / "tests" / "data" / "gis"
SOURCES = {
    "f32_strip.tif": DATA / "geotiff" / "f32_strip.tif",
    "f32_nocrs.tif": DATA / "geotiff" / "f32_nocrs.tif",
    "corner.asc": DATA / "asc" / "corner.asc",
    "corner.prj": DATA / "asc" / "corner.prj",
    "grid.xyz": DATA / "xyz" / "grid.xyz",
    "taludes.csv": DATA / "points" / "taludes.csv",
    "errores.csv": DATA / "points" / "errores.csv",
    "capas.gpkg": DATA / "gpkg" / "capas.gpkg",  # T29: gis_import_vector
}
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
UTM31 = CATALOG.horizontal(25831)
CRS_JSON = {"epsg": 25830}
VERTICAL_JSON = {"epsg": 5782}
ORIGIN = georef.GeoOrigin(700000, 4400000, 0)
OPERATION_UID = "0f3c2a5e-7b1d-4c9e-8a6f-2d4b6c8e0a13"
POINT_COLUMNS = {"point_id": 0, "x": 1, "y": 2, "z": 3, "code": 4, "line": 5}
POINT_SETTINGS = {"encoding": "utf-8", "separator": ";", "decimal": ",", "header_row": 0,
                  "columns": POINT_COLUMNS, "line_kind": "hard"}
CANCEL_BUDGET_S = 2.0  # RF-006-28 (RF-004-09): cancelar para en ≤ 2 s
REPROJECTING = 0.25  # avance de gis_resample ya dentro de la reproyección (tramo 0,2–0,85)
WAIT_S = 60.0  # plazo de seguridad: un trabajo colgado no cuelga la prueba
EXPECTED_WORKERS = ("gis_read_raster", "gis_resample", "gis_import_points", "gis_tin_prepare",
                    "gis_triangulate", "gis_tin_finish", "gis_contours", "gis_validate",
                    "gis_export", "gis_view_arrays", "gis_import_vector", "gis_tin_contours",
                    "gis_convert_surface")  # los tres últimos, de la T29

_STATE: dict = {}


def _sha(path: Path) -> str:
    return _support.sha256_file(path)


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """Los mismos valores bit a bit (NaN con su carga incluidos)."""
    test.assertEqual(got.shape, expected.shape)
    test.assertEqual(got.dtype, expected.dtype)
    test.assertTrue(np.array_equal(got.view(np.uint8), expected.view(np.uint8)))


def _read_digest(reader: object, kind: str, path: Path, declarations: dict | None = None,
                 settings: dict | None = None) -> object:
    """El ``ContentDigest`` que da ``reader`` al leer ``path`` en el hilo."""
    request = reader.request(kind, declarations or {}, {"main": path}, settings or {})
    return readers.read_content(reader, request)


def _hash_job(base: Path, reader: object, kind: str, files: dict, declarations: dict,
              settings: dict) -> dict:
    """Lo que da el trabajo ``core_content_hash`` de la 008 para esa fuente (en el hilo)."""
    request = checks.HashRequest("uid-fuente", "fuente", reader.id, kind, declarations,
                                 settings, files, encoder.NORMALIZER, 1)
    job = content_hash.new_job(request)
    folder = job_paths.job_dir(base / "hash", job.job_uid).create()
    ctx = worker_api.WorkerContext(job, folder, worker_api.QueueSink(),
                                   paths=content_hash.job_paths(request))
    found = content_hash.run(ctx)
    return {key: found[key] for key in ("data_sha256", "content_sha256", "normalizer",
                                        "reader")}


def _digest_of(summary_digest: dict) -> object:
    return gis_jobs.digest_of(summary_digest)


OVERRIDE = float(geotiff_reader.read_geotiff(SOURCES["f32_strip.tif"]).values[0, 0])


def _overridden(path: Path) -> object:
    """``f32_strip.tif`` leído con el sin dato forzado a :data:`OVERRIDE`."""
    source = geotiff_reader.read_geotiff(path)
    values = np.where(source.values == OVERRIDE, np.nan, source.values)
    return dataclasses.replace(source, values=values)


def _project_raster() -> object:
    """La rejilla de ``f32_strip.tif`` como un dato del proyecto (EPSG:25830 + 5782)."""
    source = geotiff_reader.read_geotiff(SOURCES["f32_strip.tif"])
    return gis.Raster(source.grid, source.values, CRS, VERTICAL)


def _taludes() -> tuple:
    table = csv_tables.read_table(SOURCES["taludes.csv"], encoding="utf-8", separator=";",
                                  header_row=0)
    mapping = points_mod.ColumnMapping(x=1, y=2, z=3, point_id=0, code=4, line=5)
    return points_mod.points_from_rows(table.columns, table.rows, mapping, ",",
                                       source="Taludes", row_numbers=table.lines)


def _errores() -> tuple:
    table = csv_tables.read_table(SOURCES["errores.csv"], encoding="utf-8", separator=";",
                                  header_row=0)
    mapping = points_mod.ColumnMapping(x=1, y=2, z=3, point_id=0, code=4, line=5)
    return points_mod.points_from_rows(table.columns, table.rows, mapping, ",",
                                       source="Errores", row_numbers=table.lines)


def setUpModule() -> None:
    tmp = _support.jobs_tmp(prefix="gb26-")
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    sources = base / "fuentes"
    sources.mkdir()
    for name, path in SOURCES.items():
        shutil.copyfile(path, sources / name)
    inputs = base / "entradas"
    inputs.mkdir()
    raster = _project_raster()
    geotiff.GeoTiffIO().write(raster, inputs / "source.tif", profile="project")
    points, lines, _report = _taludes()
    gis_jobs.write_points(inputs / "points.npz", points)
    gis_jobs.write_lines(inputs / "lines.npz", lines)
    conflicts, conflict_lines, _report = _errores()
    gis_jobs.write_points(inputs / "conflicts_points.npz", conflicts)
    gis_jobs.write_lines(inputs / "conflicts_lines.npz", conflict_lines)
    prepared = gis_tin.prepare_tin(points, lines, name="Taludes")
    gis_jobs.write_tin_input(inputs / "prepared.npz", prepared)
    xy = georef.world_to_local(prepared.prepared.xyz[:, :2], ORIGIN)
    faces = gis.PureTriangulator().triangulate(xy, prepared.prepared.edges)
    np.save(inputs / "faces.npy", faces, allow_pickle=False)
    boundary = [np.array([[700005.0, 4400005.0], [700075.0, 4400005.0],
                          [700075.0, 4400045.0], [700005.0, 4400045.0]])]
    gis_jobs.write_regions(inputs / "regions.npz", boundary, [])
    tin, _report = gis.build_tin(points, lines, triangulator=gis.PureTriangulator(),
                                 origin=ORIGIN, name="Taludes")
    gis_tin.save_tin(tin, inputs / "source.npz", {"crs_epsg": 25830, "vertical": "EPSG:5782",
                                                  "operation_uid": OPERATION_UID})
    project = base / "proyecto"
    project.mkdir()
    _STATE.update(base=base, sources=sources, inputs=inputs, raster=raster, points=points,
                  lines=lines, boundary=boundary, project=project,
                  before=source_state(sources))
    registry = mock.patch.dict(readers._REGISTRY)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    unittest.addModuleCleanup(gis_content.use_table_reader,
                              gis_content.use_table_reader(None))
    _launch_reprojections()


def _launch_reprojections() -> None:
    """Lanza en proceso aparte, con ``--site`` a la carpeta de pyproj (``.deps/site``, la de
    las pruebas), una reproyección grande de EPSG:25831 a EPSG:25830 (con 4 × 4 subcentros por
    celda, unos 27 M de puntos), que ``SubprocessTest`` cancela a mitad."""
    site = Path(importlib.util.find_spec("pyproj").origin).resolve().parents[1]
    base = _STATE["base"] / "proceso"
    base.mkdir()
    registry = mock.patch.dict(catalog._REGISTRY)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    for info in gis_jobs.WORKER_INFOS:
        catalog.register_worker(info)
    service = import_geoblender("adapters.registry").crs_service()
    source = SubprocessTest.source_raster()
    center = service.transformer(UTM31, VERTICAL, CRS, VERTICAL).apply(
        np.array([[287200.0, 4429200.0, 0.0]]))[0]
    west, north = float(np.floor(center[0])) - 50.0, float(np.floor(center[1])) + 50.0
    small = gis.Grid(west, north, 4.0, 4.0, 25, 25)
    big = gis.Grid(west - 600.0, north + 600.0, 1.0, 1.0, 1300, 1300)
    geotiff.GeoTiffIO().write(source, _STATE["inputs"] / "utm31.tif", profile="project")
    project = base / "proyecto"
    project.mkdir()
    runner = runner_mod.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                  blender_python=Path(sys.executable), max_subprocess=2,
                                  forbidden_roots=[project])
    unittest.addModuleCleanup(runner.shutdown)
    geotiff.GeoTiffIO().write(source, base / "source.tif", profile="project")
    commands: dict = {}
    real_build = interpreter.build_command

    def build(*args, **kwargs):
        command = real_build(*args, **kwargs)
        commands[Path(kwargs["job_dir"]).name] = command
        return command

    handles = {}
    with mock.patch.object(runner_mod.interpreter, "build_command", side_effect=build):
        params = {"name": "MDT grande", **reprojection_params(big, "area_mean")}
        request = protocol.new_request(gis_jobs.RESAMPLE, label="Reproyección grande",
                                       owner="gis", params=params, operation_uid=OPERATION_UID,
                                       grace_s=gis_jobs.CANCEL_GRACE_S)
        folder = runner.prepare(request)
        request = dataclasses.replace(
            protocol.read_request(folder),
            inputs={"source": folder.copy_input(base / "source.tif", "source")})
        protocol.write_request(folder, request)
        handles["grande"] = runner.submit(folder, site_override=site)
    _STATE["subprocess"] = {"runner": runner, "handles": handles, "commands": commands,
                            "site": site, "small": small, "service": service, "base": base,
                            "source": source}


def reprojection_params(grid: object, method: str) -> dict:
    """Los parámetros de una reproyección de EPSG:25831 a la rejilla ``grid`` en EPSG:25830."""
    return {"source_crs": {"epsg": 25831}, "source_vertical": VERTICAL_JSON,
            "target_crs": CRS_JSON, "target_vertical": VERTICAL_JSON,
            "target": gis_jobs.grid_json(grid), "method": method, "supersample": 4}


def tearDownModule() -> None:  # noqa: D103 - comprobación final de las fuentes
    changes = source_changes(_STATE["before"], source_state(_STATE["sources"]))
    if changes:
        raise AssertionError(f"la carpeta de las fuentes cambió (RF-006-10): {changes}")


class _JobCase(unittest.TestCase):
    """Un trabajo de la 006 en el hilo, con el ``WorkerContext`` de la 004 y su envoltorio
    (``workers/<tipo>.py``, ``main``)."""

    def setUp(self) -> None:
        self.root = _STATE["base"] / "hilo" / self.id().rpartition(".")[2]
        self.root.mkdir(parents=True)

    def prepare(self, worker: str, params: dict, *, inputs: dict | None = None,
                operation_uid: str | None = OPERATION_UID) -> object:
        """La carpeta del trabajo ``worker`` con su ``request.json`` y sus entradas en
        ``in/`` (copiadas con ``JobDir.copy_input``, como lo del proyecto)."""
        request = protocol.new_request(worker, label=f"Prueba de {worker}", owner="gis",
                                       params=params, operation_uid=operation_uid,
                                       environment="blender", timeout_s=600.0,
                                       grace_s=gis_jobs.CANCEL_GRACE_S)
        folder = job_paths.job_dir(self.root / "jobs", request.job_uid).create()
        copied = {name: folder.copy_input(_STATE["inputs"] / file, name)
                  for name, file in (inputs or {}).items()}
        request = dataclasses.replace(request, inputs=copied)
        protocol.write_request(folder, request)
        return folder

    def context(self, folder: object, *, paths: dict | None = None, sink: object = None,
                cancel: threading.Event | None = None) -> object:
        request = protocol.read_request(folder)
        return worker_api.WorkerContext(request, folder, sink or worker_api.QueueSink(),
                                        cancel_event=cancel, paths=paths)

    def run_job(self, worker: str, params: dict, *, inputs: dict | None = None,
                paths: dict | None = None, operation_uid: str | None = OPERATION_UID,
                ) -> tuple[dict, object, object]:
        """Ejecuta ``main(ctx)`` del envoltorio y comprueba lo común: cada resultado
        declarado está en ``out/`` con su huella, no hay otro, y la petición no lleva
        ninguna ruta (ARQ-11)."""
        folder = self.prepare(worker, params, inputs=inputs, operation_uid=operation_uid)
        ctx = self.context(folder, paths=paths)
        summary = import_geoblender(f"workers.{worker}").main(ctx)
        json.dumps(summary, allow_nan=False)  # JSON del canal
        found = sorted(path.relative_to(folder.path).as_posix()
                       for path in folder.outputs_dir.rglob("*") if path.is_file())
        self.assertEqual(found, sorted(ref.path for ref in ctx.outputs))
        for ref in ctx.outputs:
            with self.subTest(resultado=ref.path):
                file = folder.path / ref.path
                self.assertEqual((ref.sha256, ref.size), (_sha(file), file.stat().st_size))
        text = (folder.path / job_paths.REQUEST_FILE).read_text("utf-8")
        base = str(_STATE["base"])
        for shown in (base, base.replace("\\", "/"), json.dumps(base)[1:-1]):
            self.assertNotIn(shown, text)
        return summary, ctx, folder

    @staticmethod
    def output(ctx: object, folder: object, role: str) -> Path:
        (ref,) = [ref for ref in ctx.outputs if ref.role == role]
        return folder.path / ref.path


class ImportJobsTest(_JobCase):
    def test_read_raster_imports_each_format_with_its_digest(self) -> None:
        """RF-006-28, RF-006-26, RF-006-08, RF-008-09, RF-008-20 (plan §5.3.4 y §5.6.4):
        ``gis_read_raster`` copia la fuente a ``in/`` (``--path``, nunca en la petición), la
        lee con su importador y deja ``out/source.tif`` (perfil ``project``, con las celdas
        de la fuente bit a bit) con su huella; su resumen trae el ``ContentDigest`` de la
        fuente, el mismo que da ``core_content_hash`` con las mismas declaraciones, el de la
        rejilla escrita (el que da ``gis.geotiff@1`` al leerla) y las huellas de cada fichero
        de la fuente (sha256, tamaño y fecha). GeoTIFF, ASC con su ``.prj`` (compuesto) y XYZ
        en malla. RF-006-06, RNF-006-09 (T54): y ``out/samples.npy``, las posiciones con que la
        orden compara sus cotas con la rejilla del proyecto, las de ``gis.dtm.vertical_samples``
        sobre la rejilla escrita, bit a bit (el hilo de Blender ya no la vuelve a leer)."""
        sources = _STATE["sources"]
        cases = {
            "geotiff": (gis_content.GEOTIFF, {"main": sources / "f32_strip.tif"}, {},
                        lambda path: geotiff_reader.read_geotiff(path)),
            "asc": (gis_content.ASC, {"main": sources / "corner.asc",
                                      "prj": sources / "corner.prj"},
                    {"nodata_override": None}, lambda path: asc_mod.read_asc(path)),
            "xyz": (gis_content.XYZ_GRID, {"main": sources / "grid.xyz"},
                    {"separator": " ", "decimal": "."},
                    lambda path: xyz_mod.read_xyz_grid(path, separator=" ", decimal=".")),
            # Con el sin dato forzado a la cota de la celda del noroeste: esas celdas, NaN.
            "forzado": (gis_content.GEOTIFF, {"main": sources / "f32_strip.tif"},
                        {"nodata_override": OVERRIDE}, _overridden),
        }
        for label, (reader, files, settings, read) in cases.items():
            with self.subTest(formato=label):
                params = {"reader": reader.id, "name": f"MDT {label}", "settings": settings,
                          "crs": CRS_JSON, "vertical": VERTICAL_JSON,
                          "size": files["main"].stat().st_size}
                paths = {gis_jobs.path_name(role): path for role, path in files.items()}
                summary, ctx, folder = self.run_job(gis_jobs.READ_RASTER, params, paths=paths)
                written = self.output(ctx, folder, gis_jobs.OUT_SOURCE_GRID.role)
                self.assertEqual(written.name, gis_jobs.OUT_SOURCE_GRID.file)
                expected = read(files["main"])
                got = geotiff_reader.read_geotiff(written)
                _same(self, got.values, expected.values)
                self.assertTrue(got.grid.same_geometry(expected.grid))
                self.assertEqual((got.declared_crs, got.declared_vertical), (CRS, VERTICAL))
                declarations = gis_store.source_declarations(reader.id, CRS, VERTICAL,
                                                             settings)
                source = summary["source"]
                self.assertEqual(source["reader"], reader.id)
                self.assertEqual(source["declarations"], declarations)
                self.assertEqual(source["digest"],
                                 _hash_job(self.root, reader, "raster", files, declarations,
                                           settings))
                self.assertEqual(
                    {role: (item["sha256"], item["size"], item["mtime_ns"])
                     for role, item in source["files"].items()},
                    {role: (_sha(path), path.stat().st_size, path.stat().st_mtime_ns)
                     for role, path in files.items()})
                self.assertEqual((summary["crs"], summary["vertical"]),
                                 (CRS_JSON, VERTICAL_JSON))
                output = summary["outputs"][gis_jobs.OUT_SOURCE_GRID.role]
                self.assertEqual(output["file"], f"out/{gis_jobs.OUT_SOURCE_GRID.file}")
                self.assertEqual(_digest_of(output["digest"]),
                                 _read_digest(gis_content.GEOTIFF, "raster", written))
                self.assertEqual(summary["grid"], gis_jobs.grid_json(expected.grid))
                samples = self.output(ctx, folder, gis_jobs.OUT_SAMPLES.role)
                self.assertEqual(samples.name, gis_jobs.OUT_SAMPLES.file)
                _same(self, gis_jobs.read_samples(samples), gis_dtm.vertical_samples(
                    gis.Raster(got.grid, got.values, CRS, VERTICAL)))
                # Las copias verificadas de la fuente se quedan en in/ (el original, T43).
                self.assertEqual(sorted(p.name for p in folder.inputs_dir.iterdir()),
                                 sorted(f"{gis_jobs.path_name('main')}{path.suffix}"
                                        for path in files.values()))

    def test_read_raster_notes_name_the_user_files(self) -> None:
        """RF-006-04, RF-006-08, RF-004-12 (T52; constitución, principio 10):
        ``gis_read_raster`` lee copias (``in/source_main…``), pero sus notas y sus fallos
        nombran los ficheros del usuario. Sin ``prj_crs`` (la orden no reconoció el
        ``.prj``), la nota del ``.prj`` con «mdt05.prj» y «mdt05.asc»; con él (lo que la
        orden reconoció con el servicio de CRS), ninguna nota. La de PixelIsPoint de un
        GeoTIFF, con «vuelo.tif»; el fallo de un XYZ que no es una malla, con «malla.xyz»."""
        delivered = self.root / "entregas"
        delivered.mkdir()
        for name, relative in (("mdt05.asc", "asc/corner.asc"), ("mdt05.prj", "asc/corner.prj"),
                               ("vuelo.tif", "geotiff/f32_pixelispoint.tif"),
                               ("malla.xyz", "xyz/irregular.xyz")):
            shutil.copyfile(DATA / relative, delivered / name)
        main, prj = gis_jobs.path_name("main"), gis_jobs.path_name("prj")
        asc_params = {"reader": gis_content.ASC.id, "name": "MDT05", "settings": {},
                      "crs": CRS_JSON, "vertical": VERTICAL_JSON}
        asc_paths = {main: delivered / "mdt05.asc", prj: delivered / "mdt05.prj"}
        unrecognised = gis.messages.render("gis.prj_unidentified", file="mdt05.asc",
                                           prj="mdt05.prj")
        for label, extra, notes in (("sin reconocer", {}, [unrecognised]),
                                    ("reconocido", {"prj_crs": CRS_JSON}, [])):
            with self.subTest(prj=label):
                summary, _ctx, _folder = self.run_job(gis_jobs.READ_RASTER,
                                                      {**asc_params, **extra}, paths=asc_paths)
                self.assertEqual(summary["notes"], notes)
                self.assertEqual(summary["crs"], CRS_JSON)
        tif_params = {"reader": gis_content.GEOTIFF.id, "name": "Vuelo", "settings": {},
                      "crs": None, "vertical": VERTICAL_JSON}
        summary, _ctx, _folder = self.run_job(gis_jobs.READ_RASTER, tif_params,
                                              paths={main: delivered / "vuelo.tif"})
        self.assertIn(gis.messages.render("gis.pixel_is_point", file="vuelo.tif"),
                      summary["notes"])
        self.assertFalse([note for note in summary["notes"] if "source_main" in note])
        xyz_params = {"reader": gis_content.XYZ_GRID.id, "name": "Malla",
                      "settings": {"decimal": "."}, "crs": CRS_JSON, "vertical": VERTICAL_JSON}
        folder = self.prepare(gis_jobs.READ_RASTER, xyz_params)
        ctx = self.context(folder, paths={main: delivered / "malla.xyz"})
        with self.assertRaises(worker_api.JobFailed) as caught:
            import_geoblender("workers.gis_read_raster").main(ctx)
        self.assertEqual(caught.exception.code, "gis.xyz_not_grid")
        self.assertIn("«malla.xyz»", caught.exception.text)
        self.assertNotIn("source_main", caught.exception.text)

    def test_read_raster_says_where_its_cells_with_data_fall(self) -> None:
        """RF-006-08, RF-002-26 (T51; spec §8, «MDT que sale de la ventana de trabajo o a más
        de 8 km del GeoOrigin»): el resumen de ``gis_read_raster`` trae la extensión de las
        celdas con dato (``data_extent``) y, con el GeoOrigin del proyecto en la petición
        (``origin``, que la orden pasa si la fuente está en el CRS horizontal del proyecto),
        el informe de ``core.georef.precision_report`` de sus centros (``precision``); sin
        él, ninguno. ``f32_strip.tif`` (64 × 48 celdas de 1 m con un hueco interior): su
        extensión, la de la rejilla; con el GeoOrigin junto a su esquina, dentro de ±8 km;
        con uno 8 km al oeste, sus 3 060 centros con dato pasan de 8 000 m."""
        source = _STATE["sources"] / "f32_strip.tif"
        expected = geotiff_reader.read_geotiff(source)
        valid = np.isfinite(expected.values)
        xx, yy = expected.grid.centers()
        centres = np.column_stack([xx[valid], yy[valid]])
        params = {"reader": gis_content.GEOTIFF.id, "name": "MDT", "settings": {},
                  "crs": CRS_JSON, "vertical": VERTICAL_JSON}
        paths = {gis_jobs.path_name("main"): source}
        far = georef.GeoOrigin(692_000, 4_400_000, 0)
        for label, origin in (("sin GeoOrigin", None), ("cerca", ORIGIN), ("a 8 km", far)):
            with self.subTest(origen=label):
                extra = {} if origin is None else {"origin": gis_jobs.origin_json(origin)}
                summary, _ctx, _folder = self.run_job(gis_jobs.READ_RASTER,
                                                      {**params, **extra}, paths=paths)
                self.assertEqual(gis_jobs.window_of(summary["data_extent"]),
                                 expected.grid.extent)
                if origin is None:
                    self.assertNotIn("precision", summary)
                    continue
                report = gis_jobs.precision_of(summary["precision"])
                self.assertEqual(report, georef.precision_report(centres, origin))
                self.assertEqual(report.within_limit, origin is ORIGIN)
        self.assertEqual(report.points_outside, 3_060)

    def test_import_points_gives_points_and_breaklines(self) -> None:
        """RF-006-28, RF-006-12, RF-006-26, RF-008-09 (plan §5.3.4): ``gis_import_points``
        lee la copia del texto con la correspondencia de columnas y deja ``points.npz``,
        ``lines.npz`` (coordenadas ABSOLUTAS en float64 bit a bit) y ``report.json`` con su
        huella; el ``ContentDigest`` de la fuente es el de ``core_content_hash``. Los
        envoltorios registran los lectores de ``gis`` y su lector de tablas."""
        source = _STATE["sources"] / "taludes.csv"
        params = {"reader": gis_content.POINTS_TEXT.id, "name": "Taludes",
                  "settings": POINT_SETTINGS, "crs": CRS_JSON, "vertical": VERTICAL_JSON,
                  "size": source.stat().st_size}
        with mock.patch.dict(readers._REGISTRY, clear=True):
            gis_content.use_table_reader(None)
            summary, ctx, folder = self.run_job(
                gis_jobs.IMPORT_POINTS, params, paths={gis_jobs.path_name("main"): source})
            self.assertTrue({r.id for r in gis_content.CONTENT_READERS} <= set(readers.READERS))
            self.assertIs(gis_content.table_reader(), csv_tables.read_table)
        points = gis_jobs.read_points(self.output(ctx, folder, gis_jobs.OUT_POINTS.role))
        lines = gis_jobs.read_lines(self.output(ctx, folder, gis_jobs.OUT_LINES.role))
        expected_points, expected_lines, report = _taludes()
        _same(self, points.xyz, expected_points.xyz)
        self.assertEqual((points.point_ids, points.codes, points.source_rows),
                         (expected_points.point_ids, expected_points.codes,
                          expected_points.source_rows))
        self.assertEqual(len(lines), len(expected_lines))
        for got, expected in zip(lines, expected_lines, strict=True):
            _same(self, got.xyz, expected.xyz)
            self.assertEqual((got.line_id, got.hard, got.code, got.source_rows),
                             (expected.line_id, expected.hard, expected.code,
                              expected.source_rows))
        saved = json.loads(self.output(ctx, folder, gis_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved, gis_jobs.plain(report))
        self.assertEqual((summary["points"], summary["lines"]), (20, 4))
        # T35: los textos de los ficheros de paso van en UTF-8 (de una vez si son ASCII).
        odd = points_mod.PointSet(expected_points.xyz[:2], ("Ñ-1", "2"), ("Talud ñ", ""), (5, 6))
        gis_jobs.write_points(self.root / "odd.npz", odd)
        back = gis_jobs.read_points(self.root / "odd.npz")
        self.assertEqual((back.point_ids, back.codes, back.source_rows),
                         (odd.point_ids, odd.codes, odd.source_rows))
        declarations = gis_store.source_declarations(gis_content.POINTS_TEXT.id, CRS, VERTICAL,
                                                     POINT_SETTINGS)
        gis_content.use_table_reader(csv_tables.read_table)
        self.assertEqual(summary["source"]["digest"],
                         _hash_job(self.root, gis_content.POINTS_TEXT, "table",
                                   {"main": source}, declarations, POINT_SETTINGS))
        # T50 (RNF-006-09): el hash de las dos tablas que serán lo importado (las de
        # gis.store.table_digest, el que da el registro al escribirlas), calculado aquí.
        provenance = import_geoblender("gis.provenance")
        for output, family, rows in (
                (gis_jobs.OUT_POINTS, provenance.POINTS,
                 gis_store.point_rows(expected_points, CRS.epsg)),
                (gis_jobs.OUT_LINES, provenance.BREAKLINES,
                 gis_store.breakline_rows(expected_lines, CRS.epsg))):
            with self.subTest(tabla=family):
                self.assertEqual(summary["outputs"][output.role]["digest"],
                                 gis_jobs.digest_json(gis_store.table_digest(family, rows, CRS)))

    def test_explained_failures_and_bad_requests(self) -> None:
        """RF-006-28, RF-006-04, RF-004-12: un fallo para el usuario (un GeoTIFF sin CRS ni
        CRS declarado) es un ``JobFailed`` con el código de ``gis`` y su texto en español, y
        ``out/`` queda vacía; una petición que no vale (lector desconocido, rejilla
        destino mal formada, sin la ruta de la fuente) es ``request_invalid``; una fuente que
        cambia mientras se copia, ``source_changed``."""
        source = _STATE["sources"] / "f32_nocrs.tif"
        params = {"reader": gis_content.GEOTIFF.id, "name": "Sin CRS", "settings": {},
                  "crs": None, "vertical": VERTICAL_JSON}
        folder = self.prepare(gis_jobs.READ_RASTER, params)
        ctx = self.context(folder, paths={gis_jobs.path_name("main"): source})
        with self.assertRaises(worker_api.JobFailed) as caught:
            import_geoblender("workers.gis_read_raster").main(ctx)
        self.assertEqual(caught.exception.code, "gis.crs_undeclared")
        self.assertIn("Sin CRS", caught.exception.text)
        self.assertEqual(list(folder.outputs_dir.iterdir()), [])
        good = {**params, "crs": CRS_JSON}
        main = gis_jobs.path_name("main")
        for worker, bad, paths in (
                (gis_jobs.READ_RASTER, {**params, "reader": "gis.nada@1"}, {main: source}),
                (gis_jobs.RESAMPLE, {"name": "x", "target": {"west": 1}}, {}),
                (gis_jobs.READ_RASTER, good, {})):
            with self.subTest(trabajo=worker, peticion=bad):
                folder = self.prepare(worker, bad, inputs={"source": "source.tif"})
                ctx = self.context(folder, paths=paths)
                with self.assertRaises(job_messages.JobError) as caught:
                    import_geoblender(f"workers.{worker}").main(ctx)
                self.assertEqual(caught.exception.code, "request_invalid")
                self.assertEqual(list(folder.outputs_dir.iterdir()), [])
        stamps = iter([(1, 1), (2, 2)])  # la fuente antes y después de copiarla
        folder = self.prepare(gis_jobs.READ_RASTER, good)
        ctx = self.context(folder, paths={main: source})
        with (mock.patch.object(gis_jobs, "_stamp", side_effect=lambda path: next(stamps)),
              self.assertRaises(job_messages.JobError) as caught):
            import_geoblender("workers.gis_read_raster").main(ctx)
        self.assertEqual(caught.exception.code, "source_changed")
        self.assertEqual(list(folder.outputs_dir.iterdir()), [])


class SurfaceJobsTest(_JobCase):
    def grid_params(self, **extra: object) -> dict:
        return {"name": "MDT Norte", "crs": CRS_JSON, "vertical": VERTICAL_JSON,
                "count": 3072, **extra}

    def test_resample_without_reprojection(self) -> None:
        """RF-006-28, RF-006-11 (plan §5.3.4): ``gis_resample`` con el mismo CRS remuestrea la
        rejilla copiada a ``in/`` a la del proyecto (media por área de 1 m a 2 m) y deja
        ``grid.tif`` (las celdas de ``resample_to_grid`` bit a bit) y ``report.json``, con el
        hash de la rejilla escrita; su estimación lo deja en el hilo."""
        raster = _STATE["raster"]
        target = gis.aligned_grid(raster.grid.extent, 2.0)
        params = {"name": "MDT Norte", "source_crs": CRS_JSON, "source_vertical": VERTICAL_JSON,
                  "target_crs": CRS_JSON, "target_vertical": VERTICAL_JSON,
                  "target": gis_jobs.grid_json(target), "method": "auto",
                  "min_valid_fraction": 1.0, "supersample": 4, "size": 30000}
        self.assertFalse(gis_jobs.reprojects(params))
        self.assertFalse(gis_jobs.needs_site(gis_jobs.RESAMPLE, params))
        summary, ctx, folder = self.run_job(gis_jobs.RESAMPLE, params,
                                            inputs={"source": "source.tif"})
        expected, report = gis.resample_to_grid(raster, target, method="area_mean",
                                                min_valid_fraction=1.0)
        written = self.output(ctx, folder, gis_jobs.OUT_PROJECT_GRID.role)
        _same(self, geotiff_reader.read_geotiff(written).values, expected.values)
        saved = json.loads(self.output(ctx, folder, gis_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved, gis_jobs.plain(report))
        output = summary["outputs"][gis_jobs.OUT_PROJECT_GRID.role]
        self.assertEqual(_digest_of(output["digest"]),
                         _read_digest(gis_content.GEOTIFF, "raster", written))
        self.assertEqual(_digest_of(output["digest"]), gis_content.raster_digest(expected, {}))

    def test_resample_with_reprojection(self) -> None:
        """RF-006-05, RF-006-28 (plan §5.3.4): ``gis_resample`` con otro CRS reproyecta con el
        servicio de CRS (pyproj, ``adapters.registry``): ``grid.tif`` es la rejilla de
        ``reproject_to_grid`` bit a bit, con su hash, y el resumen cuenta la transformación
        (cambio de huso: precisión 0 m); no tiene estimación (proceso aparte, D11) y pide
        ``--site``."""
        launched = _STATE["subprocess"]
        small, service = launched["small"], launched["service"]
        params = {"name": "MDT", **reprojection_params(small, "bilinear")}
        self.assertTrue(gis_jobs.needs_site(gis_jobs.RESAMPLE, params))
        self.assertIsNone(gis_jobs.WORKER_INFOS_BY_NAME[gis_jobs.RESAMPLE].estimate_s(params))
        summary, ctx, folder = self.run_job(gis_jobs.RESAMPLE, params,
                                            inputs={"source": "utm31.tif"})
        expected, report = gis.reproject_to_grid(
            launched["source"], small,
            transform=service.transformer(UTM31, VERTICAL, CRS, VERTICAL),
            inverse=service.transformer(CRS, VERTICAL, UTM31, VERTICAL), target_crs=CRS,
            target_vertical=VERTICAL, method="bilinear", supersample=4, name="MDT")
        written = self.output(ctx, folder, gis_jobs.OUT_PROJECT_GRID.role)
        _same(self, geotiff_reader.read_geotiff(written).values, expected.values)
        output = summary["outputs"][gis_jobs.OUT_PROJECT_GRID.role]
        self.assertEqual(_digest_of(output["digest"]), gis_content.raster_digest(expected, {}))
        self.assertEqual((summary["reprojected"], summary["transform"]["accuracy_m"]),
                         (True, 0.0))
        saved = json.loads(self.output(ctx, folder, gis_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved, gis_jobs.plain(report))

    def test_contours_validate_export_and_view_of_a_grid(self) -> None:
        """RF-006-28, RF-006-18, RF-006-23, RF-006-24, RF-006-22 (plan §5.3.4): con la rejilla
        del proyecto copiada a ``in/``, ``gis_contours`` deja las curvas de
        ``contours_from_raster`` (bit a bit), ``gis_validate`` el informe de
        ``validate_raster``, ``gis_export`` el GeoTIFF entregable que escribe ``GeoTiffIO``
        (los mismos bytes) y ``gis_view_arrays`` las mallas de vista y de los niveles de
        detalle."""
        raster = _STATE["raster"]
        params = self.grid_params(interval_m=1.0, base_m=0.0, index_every_m=5.0,
                                  index_offset_m=0.0, simplify_m=0.0, min_length_m=0.0)
        summary, ctx, folder = self.run_job(gis_jobs.CONTOURS, params,
                                            inputs={"source": "source.tif"})
        lines = gis_jobs.read_contours(self.output(ctx, folder, gis_jobs.OUT_CONTOURS.role))
        expected = gis.contours_from_raster(raster, interval_m=1.0, name="MDT Norte")
        self.assertEqual((summary["contours"], len(lines)), (len(expected), len(expected)))
        for got, line in zip(lines, expected, strict=True):
            _same(self, got.xyz, line.xyz)
            self.assertEqual((got.elevation, got.is_index, got.closed),
                             (line.elevation, line.is_index, line.closed))

        window = {"xmin": 700000.0, "ymin": 4400000.0, "xmax": 700064.0, "ymax": 4400048.0}
        summary, ctx, folder = self.run_job(
            gis_jobs.VALIDATE, self.grid_params(window=window, z_range=[-500.0, 5000.0]),
            inputs={"source": "source.tif"})
        report = gis.validate_raster(raster, window=georef.Window(**window),
                                     z_range=(-500.0, 5000.0))
        saved = json.loads(self.output(ctx, folder, gis_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved, gis_jobs.plain(report))

        summary, ctx, folder = self.run_job(gis_jobs.EXPORT, self.grid_params(),
                                            inputs={"source": "source.tif"})
        reference = self.root / "entregable.tif"
        geotiff.GeoTiffIO().write(raster, reference, profile="deliverable")
        self.assertEqual(_sha(self.output(ctx, folder, gis_jobs.OUT_EXPORT.role)),
                         _sha(reference))

        summary, ctx, folder = self.run_job(gis_jobs.VIEW_ARRAYS,
                                            self.grid_params(lod_steps=[2.0, 5.0]),
                                            inputs={"source": "source.tif"})
        meshes = gis_jobs.read_mesh(self.output(ctx, folder, gis_jobs.OUT_MESH.role))
        expected = {None: gis.surface_mesh_from_raster(raster)}
        for step, level in gis.lod_rasters(raster, [2.0, 5.0]).items():
            expected[step] = gis.surface_mesh_from_raster(level)
        self.assertEqual(sorted(meshes, key=str), sorted(expected, key=str))
        for step, mesh in expected.items():
            _same(self, meshes[step].vertices, mesh.vertices)
            _same(self, meshes[step].faces, mesh.faces)
        self.assertEqual(summary["levels"], [2.0, 5.0])

    def test_contours_and_validation_of_a_tin(self) -> None:
        """RF-006-28, RF-006-18, RF-006-23: las curvas y la validación de un TIN del proyecto
        (``in/source.npz``) son las de ``contours_from_tin`` y ``validate_tin``."""
        tin = gis_tin.load_tin(_STATE["inputs"] / "source.npz")
        params = self.grid_params(interval_m=0.5)
        summary, ctx, folder = self.run_job(gis_jobs.CONTOURS, params,
                                            inputs={"source": "source.npz"})
        lines = gis_jobs.read_contours(self.output(ctx, folder, gis_jobs.OUT_CONTOURS.role))
        expected = gis.contours_from_tin(tin, interval_m=0.5, name="MDT Norte")
        self.assertEqual(len(lines), len(expected))
        for got, line in zip(lines, expected, strict=True):
            _same(self, got.xyz, line.xyz)
        window = {"xmin": 699990.0, "ymin": 4399990.0, "xmax": 700090.0, "ymax": 4400060.0}
        summary, ctx, folder = self.run_job(gis_jobs.VALIDATE, self.grid_params(window=window),
                                            inputs={"source": "source.npz"})
        saved = json.loads(self.output(ctx, folder, gis_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved, gis_jobs.plain(
            gis.validate_tin(tin, window=georef.Window(**window))))


class TinJobsTest(_JobCase):
    def test_tin_chain_gives_the_tin_of_build_tin(self) -> None:
        """RF-006-28, RF-006-13, RF-006-15, RF-006-26 (plan §5.3.4 y §5.6.4): la cadena
        ``gis_tin_prepare`` → ``gis_triangulate`` (``PureTriangulator``) → ``gis_tin_finish``
        da el TIN de ``build_tin`` con el mismo triangulador (vértices, triángulos, aristas
        obligatorias y origen bit a bit, y el mismo informe), con su contorno; ``tin.npz``
        lleva el ``meta`` del proyecto y de la operación de la petición y su hash es el que
        da ``core.npz_mesh@1``."""
        params = {"name": "Taludes", "tol_xy": None, "tol_z": None, "duplicate_policy": "ask",
                  "count": 44}
        summary, ctx, folder = self.run_job(gis_jobs.TIN_PREPARE, params,
                                            inputs={"points": "points.npz", "lines": "lines.npz"})
        prepared_path = self.output(ctx, folder, gis_jobs.OUT_PREPARED.role)
        prepared = gis_jobs.read_tin_input(prepared_path)
        expected = gis_tin.prepare_tin(_STATE["points"], _STATE["lines"], name="Taludes")
        for name in ("xyz", "edges", "vertex_source"):
            _same(self, getattr(prepared.prepared, name), getattr(expected.prepared, name))
        self.assertEqual(summary["vertices"], len(expected.prepared.xyz))
        shutil.copyfile(prepared_path, self.root / "prepared.npz")

        origin = {"x0": ORIGIN.x0, "y0": ORIGIN.y0, "z0": ORIGIN.z0}
        summary, ctx, folder = self.run_job(gis_jobs.TRIANGULATE,
                                            {"name": "Taludes", "origin": origin, "count": 44},
                                            inputs={"prepared": "prepared.npz"})
        faces = np.load(self.output(ctx, folder, gis_jobs.OUT_FACES.role), allow_pickle=False)
        self.assertEqual(summary["triangulator"], gis.PureTriangulator.name)

        params = {"name": "Taludes", "origin": origin, "triangulator": summary["triangulator"],
                  "max_edge_m": None, "crs": CRS_JSON, "vertical": VERTICAL_JSON,
                  "count": 44}
        summary, ctx, folder = self.run_job(
            gis_jobs.TIN_FINISH, params,
            inputs={"prepared": "prepared.npz", "faces": "faces.npy",
                    "regions": "regions.npz"})
        tin = gis_tin.load_tin(self.output(ctx, folder, gis_jobs.OUT_TIN.role))
        built, report = gis.build_tin(_STATE["points"], _STATE["lines"],
                                      triangulator=gis.PureTriangulator(), origin=ORIGIN,
                                      boundary=_STATE["boundary"], name="Taludes")
        _same(self, faces.astype(np.int32), np.load(_STATE["inputs"] / "faces.npy"))
        for name in ("vertices", "faces", "constraint_edges", "vertex_source"):
            _same(self, getattr(tin, name), getattr(built, name))
        self.assertEqual((tin.meta["operation_uid"], tin.meta["crs_epsg"],
                          tin.meta["vertical"]), (OPERATION_UID, 25830, "EPSG:5782"))
        saved = json.loads(self.output(ctx, folder, gis_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved, gis_jobs.plain(report))
        written = self.output(ctx, folder, gis_jobs.OUT_TIN.role)
        self.assertEqual(_digest_of(summary["outputs"][gis_jobs.OUT_TIN.role]["digest"]),
                         _read_digest(builtin.NPZ_MESH, "mesh", written))

        folder = self.prepare(gis_jobs.TIN_FINISH, params,
                              inputs={"prepared": "prepared.npz", "faces": "faces.npy"},
                              operation_uid=None)
        with self.assertRaises(job_messages.JobError) as caught:
            gis_jobs.run_tin_finish(self.context(folder))
        self.assertEqual(caught.exception.code, "request_invalid")

    def test_conflicts_go_to_their_report_without_a_tin(self) -> None:
        """RF-006-14, RF-006-28 (plan §5.3.4): con conflictos de cota sin resolver
        (``errores.csv``, política «preguntar»), ``gis_tin_prepare`` no deja
        ``prepared.npz`` sino ``conflicts.json`` con cada conflicto (posición y cotas, y su
        texto en español), que ``read_conflicts`` vuelve a dar como el ``ConflictError`` del
        dominio."""
        params = {"name": "Errores", "tol_xy": None, "tol_z": None, "duplicate_policy": "ask"}
        summary, ctx, folder = self.run_job(
            gis_jobs.TIN_PREPARE, params,
            inputs={"points": "conflicts_points.npz", "lines": "conflicts_lines.npz"})
        self.assertEqual([ref.role for ref in ctx.outputs], [gis_jobs.OUT_CONFLICTS.role])
        points, lines, _report = _errores()
        with self.assertRaises(gis.ConflictError) as caught:
            gis_tin.prepare_tin(points, lines, name="Errores")
        found = gis_jobs.read_conflicts(self.output(ctx, folder, gis_jobs.OUT_CONFLICTS.role))
        self.assertEqual((found.code, found.text, found.texts()),
                         (caught.exception.code, caught.exception.text,
                          caught.exception.texts()))
        self.assertEqual(summary["conflicts"], len(caught.exception.conflicts))


class CancelTest(_JobCase):
    """Cancelar a mitad deja ``out/`` sin resultados (RF-006-28, RF-004-09)."""

    def cases(self) -> dict:
        sources = _STATE["sources"]
        main = gis_jobs.path_name("main")
        grid = {"name": "MDT", "crs": CRS_JSON, "vertical": VERTICAL_JSON}
        target = gis.aligned_grid(_STATE["raster"].grid.extent, 2.0)
        origin = {"x0": ORIGIN.x0, "y0": ORIGIN.y0, "z0": ORIGIN.z0}
        return {
            gis_jobs.READ_RASTER: (
                {"reader": gis_content.GEOTIFF.id, "name": "MDT", "settings": {},
                 "crs": CRS_JSON, "vertical": VERTICAL_JSON},
                {}, {main: sources / "f32_strip.tif"}),
            gis_jobs.RESAMPLE: (
                {"name": "MDT", "source_crs": CRS_JSON, "source_vertical": VERTICAL_JSON,
                 "target_crs": CRS_JSON, "target_vertical": VERTICAL_JSON,
                 "target": gis_jobs.grid_json(target), "method": "auto"},
                {"source": "source.tif"}, {}),
            gis_jobs.IMPORT_POINTS: (
                {"reader": gis_content.POINTS_TEXT.id, "name": "Taludes",
                 "settings": POINT_SETTINGS, "crs": CRS_JSON, "vertical": VERTICAL_JSON},
                {}, {main: sources / "taludes.csv"}),
            gis_jobs.TIN_PREPARE: (
                {"name": "Taludes", "duplicate_policy": "ask"},
                {"points": "points.npz", "lines": "lines.npz"}, {}),
            gis_jobs.TRIANGULATE: ({"name": "Taludes", "origin": origin},
                                   {"prepared": "prepared.npz"}, {}),
            gis_jobs.TIN_FINISH: (
                {"name": "Taludes", "origin": origin, "triangulator": "pure@1",
                 "crs": CRS_JSON, "vertical": VERTICAL_JSON},
                {"prepared": "prepared.npz", "faces": "faces.npy"}, {}),
            gis_jobs.CONTOURS: ({**grid, "interval_m": 1.0}, {"source": "source.tif"}, {}),
            gis_jobs.VALIDATE: (
                {**grid, "window": {"xmin": 700000.0, "ymin": 4400000.0, "xmax": 700064.0,
                                    "ymax": 4400048.0}},
                {"source": "source.tif"}, {}),
            gis_jobs.EXPORT: (grid, {"source": "source.tif"}, {}),
            gis_jobs.VIEW_ARRAYS: ({**grid, "lod_steps": [2.0, 5.0]}, {"source": "source.tif"},
                                   {}),
            # Los de la T29.
            gis_jobs.IMPORT_VECTOR: (
                {"reader": gis_content.GPKG_LAYER.id, "name": "Roturas",
                 "settings": {"layer": "roturas_z", "role": "breaklines"},
                 "crs": CRS_JSON, "vertical": VERTICAL_JSON},
                {}, {main: sources / "capas.gpkg"}),
            gis_jobs.TIN_CONTOURS: (
                {"name": "Taludes", "origin": origin, "crs": CRS_JSON,
                 "vertical": VERTICAL_JSON}, {"lines": "lines.npz"}, {}),
            gis_jobs.CONVERT_SURFACE: ({**grid, "direction": "grid_to_tin"},
                                       {"source": "source.tif"}, {}),
        }

    def test_cancel_midway_leaves_out_without_results(self) -> None:
        """RF-006-28 (RF-004-09; spec 006 §8 «Cancelación o fallo a mitad»): en cada trabajo,
        cancelar en mitad del cálculo, o con todo escrito justo antes de terminar, para el
        trabajo (``JobCancelled``) y deja ``out/`` vacía: ningún resultado a medias ni
        entero."""
        cases = self.cases()
        self.assertEqual(sorted(cases), sorted(EXPECTED_WORKERS))
        for worker, (params, inputs, paths) in cases.items():
            for threshold in (0.5, 1.0):
                with self.subTest(trabajo=worker, cancelar_en=threshold):
                    cancel = threading.Event()
                    seen: list[float] = []

                    class Sink:
                        def send(self, event: object, cancel=cancel, seen=seen,
                                 threshold=threshold) -> None:
                            if event.type == "progress":
                                seen.append(event.frac)
                                if event.frac >= threshold:
                                    cancel.set()

                    folder = self.prepare(worker, params, inputs=inputs)
                    ctx = self.context(folder, paths=paths, sink=Sink(), cancel=cancel)
                    with (mock.patch.object(worker_api, "PROGRESS_INTERVAL_S", 0.0),
                          self.assertRaises(worker_api.JobCancelled)):
                        import_geoblender(f"workers.{worker}").main(ctx)
                    self.assertTrue(cancel.is_set())
                    self.assertEqual(list(folder.outputs_dir.iterdir()), [])
                    if threshold == 1.0:
                        self.assertEqual(seen[-1], 1.0)


class WorkerInfoTest(unittest.TestCase):
    def test_worker_infos_and_their_wrappers(self) -> None:
        """RF-006-28 (plan §5.3.4; plan 004 §5.3.1): los trece tipos de trabajo de la 006
        (tres de la T29), en el entorno de Blender, automáticos salvo ``gis_triangulate`` (siempre en proceso
        aparte), con su función ``run`` de ``gis/jobs.py`` y su nombre visible traducido;
        cada uno tiene su envoltorio ``workers/<tipo>.py`` con ``main``. Una reproyección no
        tiene estimación (va a proceso aparte) y pide ``--site``; lo demás estima su
        duración con lo que dice la petición."""
        infos = gis_jobs.WORKER_INFOS
        self.assertEqual(tuple(info.name for info in infos), EXPECTED_WORKERS)
        self.assertEqual(gis_jobs.WORKER_NAMES, EXPECTED_WORKERS)
        texts = import_geoblender("core.i18n").load_messages()
        for info in infos:
            with self.subTest(trabajo=info.name):
                self.assertIsInstance(info, catalog.WorkerInfo)
                self.assertEqual(info.environment, "blender")
                self.assertEqual(info.policy, "subprocess" if info.name == gis_jobs.TRIANGULATE
                                 else "auto")
                self.assertTrue(callable(info.run) and callable(info.estimate_s))
                self.assertTrue(texts.get(info.label_msgid))
                self.assertTrue((EXTENSION_DIR / "workers" / f"{info.name}.py").is_file())
                self.assertTrue(callable(import_geoblender(f"workers.{info.name}").main))
                self.assertIsNone(info.estimate_s({}))
        resample = gis_jobs.WORKER_INFOS_BY_NAME[gis_jobs.RESAMPLE]
        grid = {"west": 0.0, "north": 100.0, "dx": 1.0, "dy": 1.0, "ncols": 10, "nrows": 10}
        same = {"source_crs": CRS_JSON, "source_vertical": VERTICAL_JSON, "target": grid,
                "target_crs": CRS_JSON, "target_vertical": VERTICAL_JSON, "size": 1000}
        other = {**same, "source_crs": {"epsg": 25831}}
        self.assertLess(resample.estimate_s(same), policy.INPROCESS_MAX_ESTIMATED_S)
        self.assertIsNone(resample.estimate_s(other))
        self.assertEqual((gis_jobs.reprojects(other), gis_jobs.needs_site(gis_jobs.RESAMPLE,
                                                                            other)),
                         (True, True))
        self.assertFalse(gis_jobs.needs_site(gis_jobs.CONTOURS, other))
        for worker, request in ((gis_jobs.RESAMPLE, same), (gis_jobs.RESAMPLE, other)):
            job = protocol.new_request(worker, label="x", owner="gis", params=request)
            self.assertEqual(policy.choose_executor(resample, job),
                             "subprocess" if gis_jobs.reprojects(request) else "inprocess")

    def test_request_values_round_trip(self) -> None:
        """RF-006-04, RF-006-28 (plan §5.3.4): lo que va en la petición y en el resumen es
        JSON y vuelve igual: el CRS y la referencia vertical (EPSG, local con su nota,
        altura elipsoidal ETRS89), la rejilla, el GeoOrigin y el hash; lo que no es una de
        ellas, ``ValueError`` (``request_invalid`` en el trabajo). Los informes, en JSON sin
        NaN (como texto)."""
        local = CATALOG.local_vertical("NP-0 del plano 3")
        ellipsoidal = import_geoblender("gis.crs").ELLIPSOIDAL_ETRS89
        for vertical in (VERTICAL, local, ellipsoidal):
            shown = gis_jobs.vertical_json(vertical)
            self.assertEqual(gis_jobs.vertical_of(json.loads(json.dumps(shown))), vertical)
        self.assertEqual(gis_jobs.vertical_json(ellipsoidal), {"ellipsoidal": 4937})
        self.assertEqual(gis_jobs.crs_of(gis_jobs.crs_json(CRS)), CRS)
        self.assertIsNone(gis_jobs.crs_of(None))
        grid = gis.Grid(700000.0, 4400048.0, 1.0002942907592702, 0.5, 64, 96)
        self.assertTrue(gis_jobs.grid_of(json.loads(json.dumps(gis_jobs.grid_json(grid))))
                        .same_geometry(grid))
        self.assertEqual(gis_jobs.origin_of(gis_jobs.origin_json(ORIGIN)), ORIGIN)
        digest = gis_content.raster_digest(_STATE["raster"], {})
        self.assertEqual(gis_jobs.digest_of(gis_jobs.digest_json(digest)), digest)
        for parse, value in ((gis_jobs.crs_of, {"epsg": 4326}), (gis_jobs.crs_of, 25830),
                             (gis_jobs.vertical_of, {"ellipsoidal": 4979}),
                             (gis_jobs.grid_of, {"west": 0.0}),
                             (gis_jobs.origin_of, {"x0": 1})):
            with self.subTest(valor=value), self.assertRaises((ValueError, TypeError)):
                parse(value)
        self.assertEqual(gis_jobs.plain({"a": (float("nan"), np.float64(1.5), np.int32(2)),
                                         "b": [float("inf")], "c": None}),
                         {"a": ["nan", 1.5, 2], "b": ["inf"], "c": None})

    def test_jobs_does_not_import_gis(self) -> None:
        """ARQ-07, ADR-0004 R5 (plan §5.3.4): ``jobs/`` no importa ``gis`` (ni nada de
        dominio): ``bl/ops/gis.py`` registra los tipos con ``jobs.catalog.register_worker``
        y nada de la 006 se añade a ``jobs/``."""
        for path in sorted((EXTENSION_DIR / "jobs").glob("*.py")):
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    module = (node.module or "").split(".")[0]
                    with self.subTest(fichero=path.name, importa=node.module):
                        self.assertNotEqual(module if node.level == 2 else "", "gis")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("gis", alias.name.split("."))
            self.assertNotIn("gis_", "".join(
                line for line in path.read_text("utf-8").splitlines()
                if line.lstrip().startswith(("import", "from"))))


class SubprocessTest(unittest.TestCase):
    """Una reproyección grande en proceso aparte, con ``--site`` (las ruedas: pyproj), lanzada
    al empezar el módulo (:func:`_launch_reprojections`; arranca mientras corren las pruebas en
    el hilo) y cancelada a mitad."""

    @classmethod
    def setUpClass(cls) -> None:
        launched = _STATE["subprocess"]
        runner, handles = launched["runner"], launched["handles"]
        events: dict = {}
        asked: dict = {}
        deadline = time.monotonic() + WAIT_S
        while any(handle.result() is None for handle in handles.values()):
            if time.monotonic() > deadline:
                raise AssertionError("las reproyecciones no terminan")
            for update in runner.poll():
                events.setdefault(update.job_uid, []).extend(update.events)
            big_events = events.get(handles["grande"].job_uid, [])
            if "grande" not in asked and any(  # ya reproyectando: después de leer la fuente
                    e.type == "progress" and e.frac > REPROJECTING for e in big_events):
                asked["grande"] = time.time()
                runner.cancel(handles["grande"].job_uid)
            time.sleep(0.02)
        cls.handles, cls.events, cls.asked = handles, events, asked
        cls.commands, cls.site = launched["commands"], launched["site"]
        cls.base = launched["base"]

    @staticmethod
    def source_raster() -> object:
        """Una rejilla de 100 × 100 celdas de 4 m en EPSG:25831 (+ 5782): un plano."""
        grid = gis.Grid(287000.0, 4429400.0, 4.0, 4.0, 100, 100)
        x, y = grid.centers()
        values = 800.0 + 0.01 * (x - 287000.0) - 0.02 * (y - 4429000.0)
        return gis.Raster(grid, values, UTM31, VERTICAL)

    def test_reprojection_runs_in_a_subprocess_with_the_wheels(self) -> None:
        """RF-006-05, RF-006-28 (plan §2 y §5.3.4; D11): una reproyección va a proceso aparte
        (sin estimación), con ``--site`` a las ruedas: allí carga pyproj y reproyecta (su avance
        pasa del de leer la fuente); la petición no lleva ninguna ruta ni el proyecto
        (ARQ-11)."""
        handle = self.handles["grande"]
        record = records.read_record(handle.job_dir)
        self.assertEqual(record.executor, runner_mod.EXECUTOR_SUBPROCESS)
        command = self.commands[handle.job_uid]
        at = command.index("--site")
        self.assertEqual(Path(command[at + 1]), self.site)
        text = (handle.job_dir.path / job_paths.REQUEST_FILE).read_text("utf-8")
        base = str(self.base)
        for shown in (base, base.replace("\\", "/"), json.dumps(base)[1:-1]):
            self.assertNotIn(shown, text)
        self.assertIsNone(json.loads(text)["project_uid"])
        self.assertTrue(any(event.type == "progress" and event.frac > REPROJECTING
                            for event in self.events[handle.job_uid]))

    def test_reprojection_cancels_within_two_seconds(self) -> None:
        """RF-006-28 (RF-004-09; D11): cancelar una reproyección grande en curso (ya con
        avance) la para en ≤ 2 s, sin resultado y con ``out/`` vacía."""
        handle = self.handles["grande"]
        self.assertEqual(handle.state, "cancelled", handle.message)
        events = self.events[handle.job_uid]
        types = [event.type for event in events]
        self.assertNotIn("result", types)
        cancelled = [event for event in events if event.type == "cancelled"]
        took = (cancelled[0].ts if cancelled else time.time()) - self.asked["grande"]
        self.assertLessEqual(took, CANCEL_BUDGET_S)
        self.assertEqual(list(handle.job_dir.outputs_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
