# SPDX-License-Identifier: GPL-3.0-or-later
"""Hash de un MDT grande e importación con el hash (spec 006, T45; RNF-008-11; RNF-006-01,
RNF-006-02 y RNF-006-08; S-4 de la 008; plan 006 §5.6.9).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el
PC de referencia de la spec 001 §5, en disco local (``%TEMP%``). Cada cifra se imprime en una
línea ``RNF-NNN-nn: …`` con el equipo y el intérprete (``tools/check.py`` las recoge) y se
compara con su presupuesto, sin relajarlo. Datos sintéticos generados aquí, sin versionar
(plan §7.1).

- RNF-008-11 (:class:`GeoTiffBigHashTest`): el arnés ``BigHashHarness`` de la 008
  (``tests/support/provenance_fixtures.py``, el de ``BigHashTest`` de
  ``tests/rendimiento/core/test_provenance_perf.py``) con ``gis.geotiff@1`` sobre un MDT
  sintético de 100 M celdas (10.000 × 10.000 de 1 m, float32 con DEFLATE y predictor 3, escrito
  por Geoblender: unos 195 MB), por el trabajo ``core_content_hash`` con la ruta en ``paths``:
  ≤ 45 s, un aviso de progreso cada ≤ 1 s y la cancelación a mitad en ≤ 2 s.
- RNF-006-01 (:class:`ImportJobTest`): importar el MDT de 3.399 × 3.309 celdas (el de T34,
  ``tests/support/gis_perf.py``) con el trabajo ``gis_read_raster`` completo, lanzado como lo
  lanza Blender (``JobRunner.submit`` con la ruta en ``paths``; el ejecutor lo elige su
  estimación, en proceso aparte): copia verificada a ``in/`` con su huella, lectura, hash de
  contenido de la fuente, escritura de la rejilla del proyecto y su hash, desde que se lanza
  hasta su resultado: ≤ 10 s con DEFLATE y ≤ 40 s con LZW (mediana de 5).
- RNF-006-08 (:class:`ImportJobTest`): el pico de memoria adicional de ese trabajo, con
  ``tracemalloc`` (también la de numpy) y la misma función en el hilo
  (``workers/gis_read_raster.py``, ``main``), con las dos compresiones: ≤ 1,5 GB.
- RNF-006-02 (:class:`ResampleJobTest`): la rejilla de 1,000 m (2,81 M celdas) con el trabajo
  ``gis_resample`` completo, como lo lanza Blender: la fuente importada copiada a ``in/`` (lo
  que hace ``bl`` antes de lanzarlo), lectura, media por área, escritura y hash de la rejilla:
  ≤ 10 s; desde la fuente declarada en ED50, en proceso aparte con ``--site`` a pyproj
  (D11: crea el servicio de CRS y comprueba su catálogo, rejilla ``es_ign_SPED2ETV2`` y 4 × 4
  subcentros): ≤ 60 s (mediana de 5).

En la red (recurso «red»: la carpeta de pruebas de ``GEOBLENDER_NET_TEST_DIR``, nunca la de
los expedientes ni la del espejo; sin ella, se omiten y quedan para H3), en una subcarpeta
temporal que se borra: :class:`NetworkBigHashTest`, el trabajo de hash del mismo MDT de
100 M celdas en ``Z:`` (el mismo hash que en local, un aviso de progreso cada ≤ 1 s y la
cancelación en ≤ 2 s; su duración se anota, sin presupuesto: RNF-008-11 lo fija en disco
local), y :class:`NetworkImportTest`, la importación del MDT de RNF-006-01 desde ``Z:`` (la
copia verificada lee la red; se anotan su duración y la del trabajo, mediana de 5).
"""

from __future__ import annotations

import dataclasses
import gc
import importlib.util
import shutil
import statistics
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import gis_perf as perf
from tests.support import network
from tests.support import provenance_fixtures as d13
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR
from tests.support.resources import requires

gis = import_geoblender("gis")
gis_jobs = import_geoblender("gis.jobs")
gis_content = import_geoblender("gis.content")
gis_params = import_geoblender("gis.params")
gis_store = import_geoblender("gis.store")
dtm = import_geoblender("gis.dtm")
crs_mod = import_geoblender("gis.crs")
geotiff = import_geoblender("gis.geotiff")
georef = import_geoblender("core.georef")
readers = import_geoblender("core.content.readers")
dataset_model = import_geoblender("core.datasets.model")
registry = import_geoblender("adapters.registry")
catalog = import_geoblender("jobs.catalog")
protocol = import_geoblender("jobs.protocol")
job_paths = import_geoblender("jobs.paths")
records = import_geoblender("jobs.records")
runner_mod = import_geoblender("jobs.runner")
worker_api = import_geoblender("jobs.worker_api")
hash_worker = import_geoblender("workers.core_content_hash")
read_worker = import_geoblender("workers.gis_read_raster")

IMPORT_DEFLATE_BUDGET_S = 10.0  # RNF-006-01
IMPORT_LZW_BUDGET_S = 40.0  # RNF-006-01
MEMORY_BUDGET_BYTES = 1_500_000_000  # RNF-006-08: 1,5 GB
GRID_BUDGET_S = 10.0  # RNF-006-02
GRID_ED50_BUDGET_S = 60.0  # RNF-006-02

GRID_STEP = 1.0  # RNF-006-02: la rejilla de 1,000 m
GRID_CELLS = 1700 * 1655
EPSG_PROJECT = 25830
EPSG_ED50 = 23030
EPSG_VERTICAL = 5782
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(EPSG_PROJECT)
CRS_ED50 = CATALOG.horizontal(EPSG_ED50)
VERTICAL = CATALOG.vertical(EPSG_VERTICAL)
IO = geotiff.GeoTiffIO()
PROJECT = gis.WriteProfile.PROJECT
DELIVERABLE = gis.WriteProfile.DELIVERABLE

# El MDT de RNF-008-11: 10.000 × 10.000 celdas de 1 m (100 M), la misma superficie que el de
# RNF-006-01 (gis_perf.surface) con su ruido de 5 cm, en GeoTIFF float32 DEFLATE + predictor 3.
BIG_ROWS, BIG_COLS = d13.BIG_MDT_SHAPE
BIG_STEP = 1.0
BIG_NORTH = perf.SOUTH + BIG_ROWS * BIG_STEP
BIG_BAND_ROWS = 500  # filas por banda al generarlo
BIG_NAME = "mdt_100m.tif"
BIG_LABEL = (f"un MDT GeoTIFF de {BIG_ROWS * BIG_COLS // 1_000_000} M celdas "
             f"({perf.count(BIG_ROWS)} × {perf.count(BIG_COLS)}, float32 con DEFLATE y "
             "predictor 3)")

OPERATION_UID = "5d0c9a3e-1f2b-4c7d-9e8a-6b4f2c0d1e45"  # la operación de los trabajos
POLL_S = 0.005  # sondeo del lanzador mientras espera un trabajo
WAIT_S = 600.0  # plazo de seguridad: un trabajo colgado no cuelga la prueba
EXECUTORS = {runner_mod.EXECUTOR_SUBPROCESS: "en proceso aparte",
             runner_mod.EXECUTOR_INPROCESS: "en el hilo"}


def _seconds(value: float) -> str:
    return perf.number(value)


def _megabytes(path: Path) -> str:
    return perf.number(path.stat().st_size / 1e6, 1)


# --- Datos y lanzador, una vez para el módulo ---------------------------------------------------


class _Data:
    """Lo que comparten las pruebas, creado una vez en :func:`setUpModule`."""

    folder: Path
    big: Path  # el MDT de 100 M celdas (float32 DEFLATE + predictor 3)
    big_digest: Any = None  # su ContentDigest leído en el hilo (para comparar el de la red)
    deflate: Path  # el MDT de RNF-006-01, float32 DEFLATE + predictor 3
    lzw: Path  # las mismas teselas en LZW sin predictor
    imported: np.ndarray  # sus cotas tal como se importan (float32 → float64, NaN)
    imported_digest: Any  # el ContentDigest de la rejilla importada (el dato del proyecto)
    source: Path  # la fuente importada (perfil project) en EPSG:25830
    source_ed50: Path  # la misma, declarada en ED50
    target: Any  # la rejilla de 1 m desde la fuente en EPSG:25830
    expected_grid: np.ndarray  # sus cotas (media por área)
    target_ed50: Any  # la rejilla de 1 m en EPSG:25830 desde la de ED50
    site: Path  # la carpeta de pyproj para --site (las ruedas)
    runner: Any  # el JobRunner del módulo


_DATA = _Data()


def _write_big(path: Path) -> Path:
    """El MDT de 100 M celdas, generado por bandas y escrito con el escritor de Geoblender
    (perfil ``deliverable``: float32, teselas de 256, DEFLATE y predictor 3)."""
    grid = gis.Grid(perf.WEST, BIG_NORTH, BIG_STEP, BIG_STEP, BIG_COLS, BIG_ROWS)
    values = np.empty(grid.shape, np.float64)
    east = perf.WEST + (np.arange(BIG_COLS) + 0.5) * BIG_STEP
    rng = np.random.default_rng(perf.SEED + 11)
    for top in range(0, BIG_ROWS, BIG_BAND_ROWS):
        rows = np.arange(top, min(BIG_ROWS, top + BIG_BAND_ROWS))
        north = BIG_NORTH - (rows + 0.5) * BIG_STEP
        values[rows[0]:rows[-1] + 1] = (perf.surface(east[None, :], north[:, None])
                                        + rng.normal(0.0, perf.NOISE_M, (len(rows), BIG_COLS)))
    IO.write(gis.Raster(grid, values, CRS, VERTICAL), path, profile=DELIVERABLE)
    return path


def setUpModule() -> None:
    """Los datos de todas las pruebas, en una carpeta temporal que se borra al final, y el
    lanzador de trabajos con los tipos de la 006 y los lectores de su trabajo de hash."""
    stack = ExitStack()
    unittest.addModuleCleanup(stack.close)
    folder = Path(stack.enter_context(tempfile.TemporaryDirectory(
        prefix="gb-gis-hash-", ignore_cleanup_errors=True)))
    _DATA.folder = folder
    stack.enter_context(mock.patch.dict(readers._REGISTRY))
    stack.callback(gis_content.use_table_reader, gis_content.use_table_reader(None))
    hash_worker.register_readers()
    stack.enter_context(mock.patch.dict(catalog._REGISTRY))
    for info in gis_jobs.WORKER_INFOS:
        if info.name not in catalog.WORKERS:
            catalog.register_worker(info)
    _DATA.big = _write_big(folder / BIG_NAME)
    grid = perf.mdt_grid()
    values = perf.mdt_values()
    _DATA.deflate = folder / "mdt_deflate.tif"
    IO.write(gis.Raster(grid, values, CRS, VERTICAL), _DATA.deflate, profile=DELIVERABLE)
    _DATA.lzw = folder / "mdt_lzw.tif"
    perf.lzw_copy(_DATA.deflate, _DATA.lzw)
    imported = values.astype(np.float32).astype(np.float64)  # lo que da leer el entregable
    _DATA.imported = imported
    source = gis.Raster(grid, imported, CRS, VERTICAL)
    _DATA.imported_digest = gis_content.raster_digest(source,
                                                      dataset_model.DATASET_DECLARATIONS)
    _DATA.source = folder / "gis_src_25830.tif"
    IO.write(source, _DATA.source, profile=PROJECT)
    _DATA.source_ed50 = folder / "gis_src_23030.tif"
    IO.write(gis.Raster(grid, imported, CRS_ED50, VERTICAL), _DATA.source_ed50,
             profile=PROJECT)
    _DATA.target = gis.aligned_grid(grid.extent, GRID_STEP)
    expected, _report = gis.resample_to_grid(source, _DATA.target,
                                             method=gis.choose_method(grid, _DATA.target))
    _DATA.expected_grid = expected.values
    service = registry.crs_service()
    transform = crs_mod.transformation_for(crs_mod.Declaration("ED50", CRS_ED50, VERTICAL),
                                           CRS, VERTICAL, service=service)
    _DATA.target_ed50 = gis.aligned_grid(perf.extent_in(transform, grid), GRID_STEP)
    _DATA.site = Path(importlib.util.find_spec("pyproj").origin).resolve().parents[1]
    project = folder / "proyecto"
    project.mkdir()
    _DATA.runner = runner_mod.JobRunner(
        jobs_root=folder / "trabajos", package_dir=EXTENSION_DIR,
        blender_python=Path(sys.executable), max_subprocess=2, forbidden_roots=[project])
    stack.callback(_DATA.runner.shutdown)


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """Las mismas cotas bit a bit (NaN donde no hay dato)."""
    test.assertEqual(got.shape, expected.shape)
    test.assertTrue(np.array_equal(got, expected, equal_nan=True))


# --- Los trabajos, como los lanza Blender -------------------------------------------------------


@dataclasses.dataclass
class _Run:
    """Un trabajo terminado: lo que tardó desde que se lanzó (con la copia de ``in/`` que hace
    ``bl``) hasta su resultado, lo que tardó su copia verificada de la fuente con su huella
    (de su primer aviso de copia al primero de lectura, con la hora del worker; ``None`` si no
    copia), su resultado y su ejecutor."""

    seconds: float
    copy_s: float | None
    result: Any
    executor: str

    def output(self, role: str) -> Path:
        (ref,) = [ref for ref in self.result.outputs if ref.role == role]
        return self.result.job_dir.path / ref.path


def _run_job(worker: str, params: dict[str, Any], *, paths: dict[str, Path] | None = None,
             inputs: dict[str, Path] | None = None, site: Path | None = None) -> _Run:
    """Lanza ``worker`` con el lanzador del módulo como ``bl`` (``core_provenance.launch_job``:
    preparar, copiar lo del proyecto a ``in/``, ``submit`` con las rutas de la fuente y, si
    reproyecta, ``--site``) y espera su resultado sondeando el lanzador. Falla si el trabajo no
    termina bien. Quien llama da el trabajo por incorporado (:func:`_release`)."""
    runner = _DATA.runner
    started = time.perf_counter()
    request = protocol.new_request(worker, label=f"Rendimiento de {worker}", owner="gis",
                                   params=params, operation_uid=OPERATION_UID,
                                   grace_s=gis_jobs.CANCEL_GRACE_S)
    folder = runner.prepare(request)
    if inputs:
        copied = {name: folder.copy_input(path, name) for name, path in inputs.items()}
        protocol.write_request(folder, dataclasses.replace(protocol.read_request(folder),
                                                           inputs=copied))
    handle = runner.submit(folder, paths=paths, site_override=site)
    events: list[Any] = []
    while handle.result() is None:
        if time.perf_counter() - started > WAIT_S:
            handle.cancel()
            raise AssertionError(f"el trabajo {worker} no termina en {WAIT_S:.0f} s")
        for update in runner.poll():
            if update.job_uid == handle.job_uid:
                events.extend(update.events)
        if handle.result() is None:
            time.sleep(POLL_S)
    seconds = time.perf_counter() - started
    result = handle.result()
    if result.state != "succeeded":
        raise AssertionError(f"el trabajo {worker} terminó «{result.state}»: "
                             f"{result.error_code} {result.error_text}")
    progress = [event for event in events if event.type == "progress"]
    copying = [event.ts for event in progress if event.msg == gis_jobs.COPYING_TEXT]
    reading = [event.ts for event in progress
               if event.msg != gis_jobs.COPYING_TEXT and event.frac > 0.0]
    copied_at = min(reading) - min(copying) if copying and reading else None
    executor = records.read_record(handle.job_dir).executor
    return _Run(seconds, copied_at, result, EXECUTORS.get(executor, executor))


def _release(run: _Run) -> None:
    """Da el trabajo por incorporado: se borran sus copias y sus resultados."""
    _DATA.runner.mark_ingested(run.result.job_uid)


def _import_params(source: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    """Los parámetros y las rutas del trabajo ``gis_read_raster`` de importar ``source``, los
    de la orden de importar un MDT (``gis.dtm``) con el límite de celdas por defecto."""
    planned = dtm.plan_import(source, name="MDT de rendimiento", crs=CRS, vertical=VERTICAL)
    limit = int(gis_params.default("gis.import.max_cells"))
    return dtm.job_params(planned, max_cells=limit), dtm.job_paths(planned)


def _resample_params(source: Path, crs: Any, target: Any) -> dict[str, Any]:
    """Los parámetros del trabajo ``gis_resample`` a la rejilla ``target`` del proyecto (los
    de ``bl/ops/gis.py``: método automático y los valores por defecto del proyecto)."""
    return {"name": "Rejilla de rendimiento", "source_crs": gis_jobs.crs_json(crs),
            "source_vertical": gis_jobs.vertical_json(VERTICAL),
            "target_crs": gis_jobs.crs_json(CRS),
            "target_vertical": gis_jobs.vertical_json(VERTICAL),
            "target": gis_jobs.grid_json(target), "method": "auto",
            "min_valid_fraction": float(gis_params.default("gis.resample.min_valid_fraction")),
            "supersample": int(gis_params.default("gis.reproject.supersample")),
            "size": source.stat().st_size}


def _repeat(action: Any) -> tuple[list[float], list[_Run]]:
    """:data:`gis_perf.REPETITIONS` trabajos seguidos, con la basura recogida antes de cada
    uno (cada uno, incorporado al terminar, salvo el último, que incorpora quien llama tras
    comprobarlo)."""
    runs: list[_Run] = []
    for _ in range(perf.REPETITIONS):
        if runs:
            _release(runs[-1])
        gc.collect()
        runs.append(action())
    return [run.seconds for run in runs], runs


# --- RNF-008-11: el hash de 100 M celdas --------------------------------------------------------


def _big_source(path: Path, where: str) -> Any:
    declarations = gis_store.source_declarations(gis_content.GEOTIFF.id, CRS, VERTICAL, {})
    return d13.BigSource({"main": path}, "raster", declarations, {}, f"{BIG_LABEL}{where}")


class GeoTiffBigHashTest(d13.BigHashHarness, unittest.TestCase):
    """RNF-008-11 con ``gis.geotiff@1``: el MDT GeoTIFF de 100 M celdas en disco local, por
    el trabajo de hash ``core_content_hash`` (el arnés de la 008, S-4)."""

    reader = gis_content.GEOTIFF
    budget_s = d13.BIG_HASH_BUDGET_S

    @classmethod
    def make_source(cls, folder: Path) -> d13.BigSource:
        return _big_source(_DATA.big, "")

    @classmethod
    def report(cls, text: str) -> None:
        perf.report(f"{text} [{perf.MACHINE}]")


def _local_big_digest() -> Any:
    """El ``ContentDigest`` del MDT de 100 M celdas en disco local, leído en el hilo (una vez)."""
    if _DATA.big_digest is None:
        source = _big_source(_DATA.big, "")
        request = gis_content.GEOTIFF.request("raster", source.declarations, source.files, {})
        _DATA.big_digest = readers.read_content(gis_content.GEOTIFF, request)
    return _DATA.big_digest


@requires(network.NET, network.NET_HINT)
class NetworkBigHashTest(d13.BigHashHarness, unittest.TestCase):
    """El trabajo de hash del mismo MDT de 100 M celdas en la carpeta de pruebas de la red
    (``Z:``): se anota lo que tarda (RNF-008-11 solo fija los 45 s en disco local; para H3), con
    el mismo hash que en local, un aviso de progreso cada ≤ 1 s y la cancelación en ≤ 2 s."""

    reader = gis_content.GEOTIFF
    budget_s = d13.BIG_HASH_BUDGET_S
    upload_s: float = 0.0

    @classmethod
    def make_source(cls, folder: Path) -> d13.BigSource:
        remote = cls._big_stack.enter_context(network.net_tmp("gb-006-hash-"))
        started = time.perf_counter()
        target = Path(shutil.copyfile(_DATA.big, remote / BIG_NAME))
        cls.upload_s = time.perf_counter() - started
        return _big_source(target, " en la red")

    @classmethod
    def report(cls, text: str) -> None:
        perf.report(f"{text} [{perf.MACHINE}]")

    def test_big_hash(self) -> None:
        """RNF-008-11 (en la red, para H3): el hash de contenido del MDT de 100 M celdas en
        ``Z:`` por el trabajo de hash da el mismo que en disco local, con un aviso de progreso
        cada ≤ 1 s; lo que tarda se anota."""
        clock = d13.ProgressClock()
        digest, _copy_s = self.hash_source(progress=clock.tick)
        total, gap = clock.finish()
        self.assertEqual(digest, _local_big_digest())
        self.report(
            f"{self.requirement}: hash de contenido de {self.source.label} ({self._size()}, "
            f"subido en {_seconds(self.upload_s)} s) con {self.reader.id}: {_seconds(total)} s "
            f"(sin presupuesto en la red: se anota para H3), {clock.ticks} avisos de progreso, "
            f"el mayor hueco {_seconds(gap)} s (presupuesto de los avisos 1 s)")
        self.assertLessEqual(gap, self.progress_gap_s)


# --- RNF-006-01 y RNF-006-08: importar con el trabajo completo ----------------------------------


def _import_in_thread(source: Path, root: Path) -> dict[str, Any]:
    """El trabajo ``gis_read_raster`` de importar ``source`` en el hilo (``main`` de su
    envoltorio con el ``WorkerContext`` de la 004, como el ejecutor en hilo), en una carpeta
    de trabajo nueva bajo ``root``."""
    params, paths = _import_params(source)
    request = protocol.new_request(gis_jobs.READ_RASTER, label="Rendimiento en el hilo",
                                   owner="gis", params=params, operation_uid=OPERATION_UID,
                                   environment="blender", timeout_s=WAIT_S,
                                   grace_s=gis_jobs.CANCEL_GRACE_S)
    folder = job_paths.job_dir(root, request.job_uid).create()
    protocol.write_request(folder, request)
    ctx = worker_api.WorkerContext(request, folder, worker_api.QueueSink(), paths=paths)
    return read_worker.main(ctx)


class ImportJobTest(unittest.TestCase):
    """RNF-006-01 y RNF-006-08: importar el MDT de 11,2 M celdas con el trabajo completo."""

    def check_import(self, source: Path, label: str, budget: float) -> None:
        params, paths = _import_params(source)
        times, runs = _repeat(lambda: _run_job(gis_jobs.READ_RASTER, params, paths=paths))
        last = runs[-1]
        try:
            summary = last.result.summary
            written = IO.read(last.output(gis_jobs.OUT_SOURCE_GRID.role))
            _same(self, written.values, _DATA.imported)
            self.assertEqual(summary["source"]["reader"], gis_content.GEOTIFF.id)
            self.assertEqual(
                gis_jobs.digest_of(summary["outputs"][gis_jobs.OUT_SOURCE_GRID.role]["digest"]),
                _DATA.imported_digest)
        finally:
            _release(last)
        copies = [run.copy_s for run in runs if run.copy_s is not None]
        perf.report(
            f"RNF-006-01: importar un MDT GeoTIFF float32 de {perf.count(perf.MDT_COLS)} × "
            f"{perf.count(perf.MDT_ROWS)} celdas (11,2 M; {_megabytes(source)} MB) con {label}"
            f" con el trabajo gis_read_raster completo, {last.executor} (copia verificada, "
            f"lectura, hash de la fuente, escritura de la rejilla del proyecto y su hash; "
            f"{perf.MACHINE}): {perf.median_line(times)}; copia verificada, mediana "
            f"{_seconds(statistics.median(copies))} s; presupuesto {perf.number(budget, 0)} s")
        self.assertEqual(len(copies), len(runs))
        self.assertLessEqual(statistics.median(times), budget)

    def test_import_deflate(self) -> None:
        """RNF-006-01: el MDT de 3.399 × 3.309 celdas float32 en DEFLATE + predictor 3 se
        importa con el trabajo ``gis_read_raster`` completo (copia verificada, lectura, hash de
        la fuente, escritura y hash de la rejilla del proyecto), lanzado como en Blender, en
        ≤ 10 s (mediana de 5), con las cotas float32 del fichero y el hash de la rejilla."""
        self.check_import(_DATA.deflate, "DEFLATE + predictor 3", IMPORT_DEFLATE_BUDGET_S)

    def test_import_lzw(self) -> None:
        """RNF-006-01: el mismo MDT en LZW sin predictor (el LZW más lento) se importa con el
        trabajo completo en ≤ 40 s (mediana de 5), con las mismas cotas que el DEFLATE."""
        self.check_import(_DATA.lzw, "LZW sin predictor", IMPORT_LZW_BUDGET_S)

    def test_import_memory(self) -> None:
        """RNF-006-08: el pico de memoria adicional del trabajo de importar el MDT de
        RNF-006-01 (la misma función, en el hilo; ``tracemalloc``, con la memoria de numpy) es
        ≤ 1,5 GB, con DEFLATE y con LZW."""
        for source, label in ((_DATA.deflate, "DEFLATE"), (_DATA.lzw, "LZW")):
            with self.subTest(compresion=label):
                root = _DATA.folder / f"hilo_{source.stem}"
                summary: dict[str, Any] = {}
                peak = perf.peak_bytes(
                    lambda source=source, root=root: summary.update(
                        _import_in_thread(source, root)))
                shutil.rmtree(root, ignore_errors=True)
                perf.report(
                    f"RNF-006-08: pico de memoria adicional del trabajo de importar el MDT de "
                    f"RNF-006-01 con {label} (gis_read_raster en el hilo, con la copia y los "
                    f"hashes; tracemalloc; {perf.MACHINE}): {perf.number(peak / 1e9, 2)} GB, "
                    f"presupuesto 1,5 GB")
                self.assertEqual(summary["valid_cells"], int(np.isfinite(_DATA.imported).sum()))
                self.assertGreater(peak, perf.MDT_COLS * perf.MDT_ROWS * 8)  # al menos el ráster
                self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


# --- RNF-006-02: la rejilla del proyecto con el trabajo completo --------------------------------


class ResampleJobTest(unittest.TestCase):
    """RNF-006-02: la rejilla de 1,000 m (2,81 M celdas) con el trabajo ``gis_resample``."""

    def test_grid_from_source(self) -> None:
        """RNF-006-02: desde la fuente de 0,5 m importada (EPSG:25830), la rejilla de 1 m de
        1.700 × 1.655 celdas con la media por área se hace con el trabajo ``gis_resample``
        completo (la fuente copiada a ``in/``, lectura, remuestreo, escritura y hash), lanzado
        como en Blender, en ≤ 10 s (mediana de 5)."""
        params = _resample_params(_DATA.source, CRS, _DATA.target)
        times, runs = _repeat(lambda: _run_job(gis_jobs.RESAMPLE, params,
                                               inputs={gis_jobs.INPUT_SOURCE: _DATA.source}))
        last = runs[-1]
        try:
            written = IO.read(last.output(gis_jobs.OUT_PROJECT_GRID.role))
            _same(self, written.values, _DATA.expected_grid)
            self.assertFalse(last.result.summary["reprojected"])
        finally:
            _release(last)
        grid = _DATA.target
        perf.report(
            f"RNF-006-02: rejilla de 1,000 m ({perf.count(grid.ncols)} × {perf.count(grid.nrows)}"
            f" = {perf.count(grid.ncols * grid.nrows)} celdas) desde el MDT de 0,5 m importado, "
            f"media por área, con el trabajo gis_resample completo, {last.executor} (copia a "
            f"in/, lectura, remuestreo, escritura y hash; {perf.MACHINE}): "
            f"{perf.median_line(times)}, presupuesto {perf.number(GRID_BUDGET_S, 0)} s")
        self.assertEqual(grid.ncols * grid.nrows, GRID_CELLS)
        self.assertLessEqual(statistics.median(times), GRID_BUDGET_S)

    def test_grid_from_ed50(self) -> None:
        """RNF-006-02: desde la fuente de 0,5 m declarada en ED50 (EPSG:23030), la rejilla de
        1 m en EPSG:25830 se hace con el trabajo ``gis_resample`` completo en proceso aparte
        con ``--site`` a pyproj (crea el servicio de CRS, la transformación del IGN
        ``es_ign_SPED2ETV2`` de 0,2 m y 4 × 4 subcentros por celda) en ≤ 60 s (mediana de 5)."""
        params = _resample_params(_DATA.source_ed50, CRS_ED50, _DATA.target_ed50)
        self.assertTrue(gis_jobs.needs_site(gis_jobs.RESAMPLE, params))
        times, runs = _repeat(lambda: _run_job(
            gis_jobs.RESAMPLE, params, inputs={gis_jobs.INPUT_SOURCE: _DATA.source_ed50},
            site=_DATA.site))
        last = runs[-1]
        try:
            summary = last.result.summary
            self.assertTrue(summary["reprojected"])
            transform = summary["transform"]
        finally:
            _release(last)
        cells = summary["cells"]
        supersample = params["supersample"]
        perf.report(
            f"RNF-006-02: rejilla de 1,000 m desde ED50 con el trabajo gis_resample completo, "
            f"{last.executor} con --site ({perf.count(_DATA.target_ed50.ncols)} × "
            f"{perf.count(_DATA.target_ed50.nrows)} = {perf.count(cells)} celdas, "
            f"{supersample} × {supersample} subcentros: {perf.count(cells * supersample ** 2)} "
            f"puntos; {transform['summary']}; {perf.MACHINE}): {perf.median_line(times)}, "
            f"presupuesto {perf.number(GRID_ED50_BUDGET_S, 0)} s")
        self.assertEqual(last.executor, EXECUTORS[runner_mod.EXECUTOR_SUBPROCESS])
        self.assertIn("es_ign_SPED2ETV2", transform["summary"])
        self.assertGreater(summary["valid_cells"], 0.95 * GRID_CELLS)
        self.assertLessEqual(statistics.median(times), GRID_ED50_BUDGET_S)


# --- En la red: la importación desde Z: --------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkImportTest(unittest.TestCase):
    """La importación del MDT de RNF-006-01 (DEFLATE) con la fuente en la carpeta de pruebas
    de la red: la copia verificada lee ``Z:``. Se anotan lo que tarda la copia y el trabajo
    (mediana de 5), para H3."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            remote = cls.stack.enter_context(network.net_tmp("gb-006-import-"))
            cls.remote = Path(shutil.copyfile(_DATA.deflate, remote / _DATA.deflate.name))
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def test_import_from_the_network(self) -> None:
        """RNF-006-01 (en la red, para H3): importar el MDT de 3.399 × 3.309 celdas en DEFLATE
        con la fuente en ``Z:`` da la misma rejilla del proyecto que en local; se anotan la
        copia verificada desde la red y el trabajo completo (mediana de 5)."""
        params, paths = _import_params(self.remote)
        times, runs = _repeat(lambda: _run_job(gis_jobs.READ_RASTER, params, paths=paths))
        last = runs[-1]
        try:
            summary = last.result.summary
            self.assertEqual(
                gis_jobs.digest_of(summary["outputs"][gis_jobs.OUT_SOURCE_GRID.role]["digest"]),
                _DATA.imported_digest)
        finally:
            _release(last)
        copies = [run.copy_s for run in runs if run.copy_s is not None]
        perf.report(
            f"RNF-006-01: importar el MDT de 3.399 × 3.309 celdas en DEFLATE "
            f"({_megabytes(self.remote)} MB) desde la carpeta de pruebas de la red con el "
            f"trabajo gis_read_raster completo, {last.executor} ({perf.MACHINE}): "
            f"{perf.median_line(times)}; copia verificada desde la red, mediana "
            f"{_seconds(statistics.median(copies))} s (mín. {_seconds(min(copies))}, máx. "
            f"{_seconds(max(copies))}); sin presupuesto en la red: se anota para H3")
        self.assertEqual(len(copies), len(runs))


if __name__ == "__main__":
    unittest.main()
