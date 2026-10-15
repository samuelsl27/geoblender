# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de la importación de una base de RecMin con V-ref (spec 005 §5; T33:
RNF-005-05; plan 005 §5.6.5, §5.6.7 y §7, ``tests/rendimiento``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender en el PC de referencia
de la spec 001 §5, en disco local (``%TEMP%``), **con el motor de Access** (ACE de 64 bits:
``requires("ace", …)``; sin él, todo el módulo se omite con ``[ENTORNO] ace``). Cada cifra se
imprime en una línea ``RNF-005-05: …`` con el equipo y el intérprete (``tools/check.py`` las
recoge) y se compara con su presupuesto, sin relajarlo. El hash de una base de 100 MB por
``core_content_hash`` (RNF-008-11) es de la T43.

**Datos** (se generan y no se versionan): V-ref de ``tests/data/dh/sintetico.py`` (semilla
fija; spec 005 §5: 2.000 sondeos, 20.000 estaciones, 50.000 tramos de litología y 25.000
tramos con 20 elementos, 500.000 valores) como una base de RecMin con el esquema 12 de
``tests/data/dh/recmin/recmin_v12.sql`` (``tests.support.recmin.vref_script``: los mismos
números, los Single de RecMin en ``DESDE``, ``HASTA`` y cada ``ELEMENTO n``, «<LD» como el
valor negativo), creada en formato ACE por ``build_mdb.ps1`` con el motor
(``tests.support.recmin.vref_base``; la primera vez, alrededor de un minuto; después, del
almacén de las bases de las pruebas). Lo que se declara al importarla: EPSG:25830 y
EPSG:5782, azimut de cuadrícula y «−x = <x». El proyecto, nuevo, con la rejilla del proyecto
``gis_dtm_terreno`` (un MDT de 1 m con la superficie de ``tests/data/gis`` sobre la que están
las bocas) y la ventana de trabajo de las bocas.

- :class:`ImportTest`: importar la base **de principio a fin**, como lo hace Blender
  (``geoblender.dh_import_recmin_mdb``, ``bl/ops/dh.py``; plan §5.6.5): su lectura
  (``dh_import_recmin`` en proceso aparte: la copia verificada de la base, sus tablas con el
  extractor y su ``powershell.exe`` hijo, el hash de contenido de la fuente con
  ``io.recmin_mdb@1`` y lo leído), su aplicación (``dh_import_apply``: las filas de lo
  importado y su hash), su escritura por pasos (``drillholes.store.SourceWriter``: la entrada,
  lo importado, el informe y el original de la base), la base (``dh.build_base``) y su
  validación (``dh.validate`` con el MDT), desde que se empieza la operación hasta que se
  confirma la validación: ≤ 60 s (mediana de :data:`IMPORT_REPETITIONS`, cada una en un
  proyecto nuevo). Fuera de la medida: crear el proyecto y su MDT y la decisión de la persona
  sobre los códigos nuevos (se dan de alta, como propone «Importación pendiente»); las pausas
  de los temporizadores de Blender entre pasos son de RNF-005-06 (T32). RecMin no da la
  profundidad de los sondeos: la validación avisa de la deducida (DH-W16) en cada uno, y de
  nada más.
- :class:`CancelTest`: cancelar la lectura a mitad, con el ``powershell.exe`` hijo leyendo la
  base (como «Cancelar» en la barra de estado: ``JobRunner.cancel``), la para en ≤ 2 s, sin
  ningún proceso suyo vivo (el worker ni sus descendientes) y sin nada en el proyecto: la
  operación, cancelada con el motivo de la 004, y ninguna tabla de sondeos, ni entrada, ni
  original (:data:`CANCEL_REPETITIONS` veces, cada una en un proyecto nuevo).
"""

from __future__ import annotations

import dataclasses
import gc
import json
import math
import statistics
import sys
import tempfile
import time
import unittest
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np

from tests.data.dh import sintetico
from tests.support import dh_sets, recmin
from tests.support import gis_perf as perf
from tests.support import jobs_fixtures
from tests.support.core_fixtures import make_session, make_settings
from tests.support.dh_fakes import gis_surface
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.repo import EXTENSION_DIR
from tests.support.resources import is_available, requires, skip_reason

dh_content = import_geoblender("interop.dh_content")
recmin_schema = import_geoblender("interop.recmin.schema")
model = import_geoblender("drillholes.model")
dh_arrays = import_geoblender("drillholes.arrays")
dh_jobs = import_geoblender("drillholes.jobs")
dh_params = import_geoblender("drillholes.params")
provenance = import_geoblender("drillholes.provenance")
schema = import_geoblender("drillholes.schema")
store = import_geoblender("drillholes.store")
georef = import_geoblender("core.georef")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
inputs_mod = import_geoblender("core.inputs")
originals_mod = import_geoblender("core.inputs.originals")
dataset_registry = import_geoblender("core.datasets.registry")
operations = import_geoblender("core.provenance.operations")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
core_params = import_geoblender("core.params")
core_defs = import_geoblender("core.params.core_defs")
grid = import_geoblender("gis.grid")
raster = import_geoblender("gis.raster")
gis_crs = import_geoblender("gis.crs")
gis_jobs = import_geoblender("gis.jobs")
gis_provenance = import_geoblender("gis.provenance")
gis_store = import_geoblender("gis.store")
catalog = import_geoblender("jobs.catalog")
ingest = import_geoblender("jobs.ingest")
protocol = import_geoblender("jobs.protocol")
runner_mod = import_geoblender("jobs.runner")

IMPORT_BUDGET_S = 60.0  # RNF-005-05: la importación
CANCEL_BUDGET_S = 2.0  # RNF-005-05: la cancelación

# V-ref (spec 005 §5).
VREF_HOLES = 2_000
VREF_STATIONS = 20_000
VREF_LITHOLOGY = 50_000
VREF_VALUES = 500_000

IMPORT_REPETITIONS = 3  # cada una, un proyecto nuevo que se borra en seguida
CANCEL_REPETITIONS = 3
CANCEL_AT = 0.3
"""El avance de la lectura en que se cancela: a mitad de las tablas de la base (el extractor
va de 0,05 a 0,6), con su ``powershell.exe`` hijo leyendo."""
MAX_SUBPROCESS = 2  # los trabajos a la vez en proceso aparte de Blender (MAX_PARALLEL_DEFAULT)
POLL_S = 0.005  # sondeo del lanzador mientras espera un trabajo
PROCESS_POLL_S = 0.02  # lo que se espera entre dos miradas a los procesos del equipo
WAIT_S = 600.0  # plazo de seguridad: un trabajo colgado no cuelga la prueba
DECIMAL = ","  # el de los números escritos como texto (RecMin no tiene)
PROJECT_SURFACE = "terreno"  # la rejilla del proyecto con que se valida (gis_dtm_terreno)
DTM_STEP_M = 1.0
DTM_MARGIN_M = 20.0
WINDOW_MARGIN_M = 50.0
SUCCEEDED = "succeeded"
CANCELLED = "cancelled"
DEDUCED_DEPTH = "DH-W16"  # RecMin no da la profundidad: la validación avisa de la deducida
COUNTED = ("dh_collar", "dh_survey", "dh_lithology", "dh_assay", "dh_validation_issue")
"""Las tablas cuyas filas se comprueban tras la importación."""
PHASES = ("lectura", "aplicación", "lo importado", "base", "validación")
"""Las fases de la importación de principio a fin (véase el módulo), en su orden."""
MACHINE = perf.MACHINE


# --- Datos ---------------------------------------------------------------------------------


class _Data:
    """Lo que comparten las pruebas, creado una vez en :func:`setUpModule`."""

    folder: Path  # la carpeta temporal del módulo
    base: Path  # la base de RecMin con V-ref (ACE)
    xy: np.ndarray  # las X, Y de sus bocas (las de V-ref)
    dtm: Any
    window: Any


_DATA = _Data()


def setUpModule() -> None:
    """V-ref como base de RecMin en formato ACE (``build_mdb.ps1``) en una carpeta temporal
    del módulo (que se borra al final), su MDT y su ventana de trabajo."""
    if not is_available(recmin.ACE):
        raise unittest.SkipTest(skip_reason(recmin.ACE, recmin.ACE_HINT))
    stack = ExitStack()
    unittest.addModuleCleanup(stack.close)
    _DATA.folder = Path(stack.enter_context(tempfile.TemporaryDirectory(
        prefix="gb-dhm-", ignore_cleanup_errors=True)))
    tables = sintetico.vref_tables()
    _DATA.base = recmin.vref_base(_DATA.folder / "fuente", tables).path
    collars = tables["bocas.csv"].rows
    _DATA.xy = np.array([[float(row[1].replace(",", ".")), float(row[2].replace(",", "."))]
                         for row in collars])
    _DATA.dtm = _dtm(_DATA.xy)
    _DATA.window = _window(_DATA.xy)


def _dtm(xy: np.ndarray) -> Any:
    """Una rejilla de 1 m con la superficie de ``tests/data/gis`` (en los centros de las
    celdas) que cubre las bocas ``xy`` con margen."""
    west = math.floor(float(xy[:, 0].min()) - DTM_MARGIN_M)
    north = math.ceil(float(xy[:, 1].max()) + DTM_MARGIN_M)
    ncols = math.ceil(float(xy[:, 0].max()) + DTM_MARGIN_M - west)
    nrows = math.ceil(north - (float(xy[:, 1].min()) - DTM_MARGIN_M))
    cells = grid.Grid(west, north, DTM_STEP_M, DTM_STEP_M, ncols, nrows)
    east = west + (np.arange(ncols) + 0.5) * DTM_STEP_M
    northing = north - (np.arange(nrows) + 0.5) * DTM_STEP_M
    centres = np.column_stack((np.tile(east, nrows), np.repeat(northing, ncols)))
    values = gis_surface(centres).reshape(nrows, ncols)
    return raster.Raster(cells, values, dh_sets.H25830, dh_sets.V5782)


def _window(xy: np.ndarray) -> Any:
    return georef.Window(float(xy[:, 0].min()) - WINDOW_MARGIN_M,
                         float(xy[:, 1].min()) - WINDOW_MARGIN_M,
                         float(xy[:, 0].max()) + WINDOW_MARGIN_M,
                         float(xy[:, 1].max()) + WINDOW_MARGIN_M)


def _declaration() -> Any:
    """Lo que declara quien importa la base: EPSG:25830 y EPSG:5782, azimut de cuadrícula y
    «−x = <x» (la inclinación de RecMin, negativa hacia abajo, no se declara)."""
    return model.SourceDeclaration(
        crs=dh_sets.H25830, vertical=dh_sets.V5782, azimuth_ref=model.AzimuthRef.GRID,
        declination_deg=None, inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units={}, value_rules=model.ValueRules(decimal_mark=DECIMAL, negative_is_below_dl=True))


def _volume() -> str:
    return (f"{perf.count(VREF_HOLES)} sondeos, {perf.count(VREF_STATIONS)} estaciones, "
            f"{perf.count(VREF_LITHOLOGY)} tramos de litología y {perf.count(VREF_VALUES)} "
            f"valores; {perf.number(_DATA.base.stat().st_size / 1e6, 1)} MB")


# --- Lo que hace Blender (bl/ops/dh.py), sin Blender ----------------------------------------


def _recompute(request: Any) -> Any:  # pragma: no cover - nada se recalcula aquí
    raise AssertionError("no se recalcula en estas pruebas")


def _registrations(stack: ExitStack) -> None:
    """Lo que registra Blender al habilitar Geoblender y usa la importación (``bl/ops/dh.py``
    y ``bl/ops/gis.py``), en ``stack``, que lo quita al cerrarse: los tipos de operación de la
    005 y el de la rejilla del proyecto de la 006, los lectores de contenido (de la 005 y el de
    las tablas del proyecto), los parámetros (de ``core`` y de los sondeos) y los tipos de
    trabajo de la 005."""
    stack.enter_context(registered(
        *provenance.operation_defs({name: _recompute for name in provenance.REPEATABLE}),
        *gis_provenance.operation_defs({gis_provenance.RESAMPLE: _recompute},
                                       op_types=(gis_provenance.RESAMPLE,))))
    for reader in (builtin.GPKG_LAYER, *dh_content.CONTENT_READERS):
        if reader.id not in readers.READERS:
            readers.register_reader(reader)
            stack.callback(readers.unregister_reader, reader.id)
    for definitions in (core_defs.DEFINITIONS, dh_params.DEFINITIONS):
        if definitions[0].key not in core_params.DEFINITIONS:
            core_params.register_definitions(definitions)
            stack.callback(core_params.unregister_definitions, definitions[0].module)
    for info in dh_jobs.WORKER_INFOS:
        if info.name not in catalog.WORKERS:
            catalog.register_worker(info)
            stack.callback(catalog.unregister_worker, info.name)


def _new_project(folder: Path, *, surface: bool) -> tuple[Any, Any]:
    """Un proyecto nuevo en ``folder`` (EPSG:25830 y EPSG:5782, con la ventana de trabajo de
    V-ref) y, con ``surface``, su rejilla del proyecto ``gis_dtm_terreno`` (el MDT de 1 m de
    V-ref, escrita con la API de la 006 como la deja «Rejilla del proyecto desde un MDT»): el
    proyecto y el registro de la rejilla (``None`` sin ella)."""
    (folder / "proyectos").mkdir()
    window = _DATA.window
    settings = make_settings(window=(window.xmin, window.ymin, window.xmax, window.ymax))
    project = create.create_project(folder / "proyectos", settings, make_session(),
                                    userdata_mod.UserData(folder / "u")).project
    if not surface:
        return project, None
    try:
        handle = operations.begin_operation(project, gis_provenance.RESAMPLE, settings={},
                                            executor="blender")
        crs, vertical = gis_store.project_references(project)
        dtm = raster.Raster(_DATA.dtm.grid, _DATA.dtm.values, crs, vertical)
        with gis_store.ResultWriter(project, handle) as out:
            out.raster(PROJECT_SURFACE, dtm)
            out.commit(software=dict([gis_crs.crs_library()]))
        (found,) = gis_store.list_gis_datasets(project, families=(gis_provenance.PROJECT_GRID,))
    except BaseException:
        project.close()
        raise
    return project, found


def _runner(folder: Path, project: Any) -> Any:
    """El lanzador de trabajos de la importación, como el de Blender: dos a la vez en proceso
    aparte y uno en el hilo, con la carpeta del proyecto prohibida."""
    return runner_mod.JobRunner(jobs_root=folder / "trabajos", package_dir=EXTENSION_DIR,
                                blender_python=Path(sys.executable),
                                max_subprocess=MAX_SUBPROCESS,
                                forbidden_roots=[Path(project.root)])


def _drive[T](steps: Generator[Any, None, T] | Iterator[Any]) -> T | None:
    """Recorre los pasos ``steps`` seguidos (sin las pausas del temporizador de Blender) y da
    lo que devuelven."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


class _Importer:
    """La importación de la base de V-ref en ``project`` con el lanzador ``runner``, como la
    hace ``bl/ops/dh.py`` con una base de RecMin (``start_order``, ``_after_reading``,
    ``_apply``, ``_import_steps``, ``_build_base_steps``, ``_base_steps``, ``_validate_steps``
    y ``_validated_steps``): sus pasos seguidos, con la hora en que acaba cada fase
    (:data:`PHASES`). ``surface``: la rejilla del proyecto con que se valida."""

    def __init__(self, project: Any, runner: Any, surface: Any) -> None:
        self.project = project
        self.runner = runner
        self.surface = surface
        self.path = _DATA.base
        self.name = self.path.stem
        self.declaration = _declaration()
        self.crs, self.vertical = gis_store.project_references(project)
        self.software = dict([gis_crs.crs_library()])
        self.catalogs: Any = None  # los del proyecto al empezar la orden
        self.holes: Any = None  # sus sondeos con registros en cada tabla, al empezar
        self.handle: Any = None  # la operación dh.import_recmin
        self.read: Any = None  # el JobHandle y, terminado, el JobResult de su lectura
        self.found: Any = None  # el JobOutcome de su lectura
        self.spec: Any = None  # su entrada (InputSpec)
        self.applied: Any = None  # el JobHandle y, terminado, el JobResult de su aplicación
        self.marks: list[float] = []
        self.workers: dict[str, str] = {}  # el tipo de cada trabajo lanzado, por su uid
        self.jobs: dict[str, str] = {}  # el ejecutor de cada tipo de trabajo

    # --- Lo común --------------------------------------------------------------------------

    def submit(self, handle: Any, worker: str, params: Mapping[str, Any], *,
               paths: Mapping[str, Path] | None = None,
               arrays: Mapping[str, np.ndarray] | None = None) -> Any:
        """Lanza el trabajo ``worker`` de la operación ``handle`` como
        ``core_provenance.launch_job``: la petición con la operación y el proyecto, ``arrays``
        escritos en ``in/`` antes de lanzarlo y ``paths`` por la línea de órdenes."""
        request = protocol.new_request(worker, label=f"Rendimiento de {worker}",
                                       owner=handle.definition.module, params=dict(params),
                                       project_uid=handle.project_uid, operation_uid=handle.uid,
                                       grace_s=dh_jobs.CANCEL_GRACE_S)
        job: Any = request
        if arrays:
            folder = self.runner.prepare(request)
            prepared = protocol.read_request(folder)
            written = {name: folder.write_array(name, array) for name, array in arrays.items()}
            protocol.write_request(folder, dataclasses.replace(
                prepared, inputs={**dict(prepared.inputs), **written}))
            job = folder
        self.workers[request.job_uid] = worker
        return self.runner.submit(job, paths=paths)

    def wait(self, handle: Any) -> Any:
        """Espera a que termine el trabajo ``handle`` sondeando el lanzador; su ``JobResult``.
        Falla si no termina bien."""
        deadline = time.perf_counter() + WAIT_S
        while handle.result() is None:
            if time.perf_counter() > deadline:
                raise AssertionError(f"el trabajo no termina en {WAIT_S:.0f} s")
            self.runner.poll()
            time.sleep(POLL_S)
        result = handle.result()
        if result.state != SUCCEEDED:
            raise AssertionError(f"un trabajo terminó «{result.state}»: {result.error_code} "
                                 f"{result.error_text}")
        return result

    def outcome(self, result: Any) -> Any:
        outcome = ingest.job_outcome(result, result.job_dir)
        self.jobs[self.workers[result.job_uid]] = str(outcome.executor)
        return outcome

    def release(self, *results: Any) -> None:
        """Da por incorporados los trabajos de ``results`` (se borran sus entradas y sus
        resultados), como ``core_provenance.release_job``."""
        for result in results:
            self.runner.mark_ingested(result.job_uid)

    def mark(self) -> None:
        self.marks.append(time.perf_counter())

    def run(self) -> list[float]:
        """La importación entera; la hora en que acaba cada fase (``time.perf_counter``)."""
        self.begin()
        self.launch_read()
        self.read = self.wait(self.read)
        self.found = self.outcome(self.read)
        self.mark()
        self.apply()
        self.mark()
        self.write_source()
        self.mark()
        self.build_base()
        self.mark()
        self.validate()
        self.mark()
        return self.marks

    # --- La lectura (start_order, _read_job) ------------------------------------------------

    def begin(self) -> None:
        """La operación ``dh.import_recmin`` de la base, «en curso» (``begin_each``: una sola
        transacción), con los catálogos y los sondeos del proyecto al empezar."""
        with self.project.read() as conn:
            self.catalogs = store.read_catalogs(conn)
            self.holes = store.holes_by_table(conn)
        conventions = self.declaration.conventions()
        conventions["sentinels"] = ";".join(conventions["sentinels"])
        settings = {"name": self.name, "file": self.path.name, "reader": provenance.RECMIN_MDB,
                    "decimal": DECIMAL, **conventions}
        (self.handle,) = operations.begin_operations(
            self.project, provenance.IMPORT_RECMIN, settings=[settings],
            executor="job_process")

    def launch_read(self) -> Any:
        """Lanza la lectura de la base (``dh_import_recmin``, en proceso aparte) con la base
        por ``paths``; su ``JobHandle``."""
        params = {"name": self.name, "declaration": dh_jobs.declaration_json(self.declaration),
                  "settings": {"decimal": DECIMAL}, "crs": gis_jobs.crs_json(self.crs),
                  "vertical": gis_jobs.vertical_json(self.vertical),
                  "project_holes": {table: list(names) for table, names in self.holes.items()},
                  "catalogs": dh_arrays.catalogs_json(self.catalogs),
                  "size": self.path.stat().st_size, "accept_schema": False}
        self.read = self.submit(self.handle, dh_jobs.IMPORT_RECMIN, params,
                                paths={gis_jobs.path_name("main"): self.path})
        return self.read

    # --- La aplicación (_after_reading, _apply) ---------------------------------------------

    def input_spec(self) -> Any:
        found = self.found.summary["source"]
        main = found["files"]["main"]
        anchor = inputs_mod.locate_source(self.path, self.project, self.project.userdata,
                                          role="main")
        prints = [inputs_mod.SourcePrint(main["sha256"], size=main["size"],
                                         mtime_ns=main["mtime_ns"])]
        return provenance.input_spec(
            provenance.RECMIN_MDB, self.name, files=[anchor], file_prints=prints,
            digest=gis_jobs.digest_of(found["digest"]), declaration=self.declaration,
            role=None, mapping=None, settings={})

    def apply(self) -> None:
        """La base clasificada (una entrada nueva) y aplicada con los códigos nuevos dados de
        alta (``dh_import_apply``, con lo leído por ruta), hasta que termina."""
        summary = self.found.summary
        if summary.get("needs_confirmation"):
            raise AssertionError(f"la base pide confirmación: {summary['needs_confirmation']}")
        self.spec = self.input_spec()
        with self.project.read() as conn:
            found = inputs_mod.classify_import(conn, self.spec)
        if not isinstance(found, inputs_mod.New):
            raise AssertionError(f"«{self.path.name}» no es una entrada nueva: {found}")
        counts = dict(summary.get("counts") or {})
        imported = sum(int(dict(table).get("imported", 0)) for table in counts.values())
        params = {"name": self.name, "crs": gis_jobs.crs_json(self.crs), "keep_holes": [],
                  "replace_holes": {str(table): list(names) for table, names in
                                    dict(summary.get("existing_tables") or {}).items()},
                  "register_codes": dict(summary.get("register_codes") or {}),
                  "taken_colors": [code.color for code in self.catalogs.lithology],
                  "count": imported + 1}
        self.applied = self.wait(self.submit(
            self.handle, dh_jobs.IMPORT_APPLY, params,
            paths={dh_jobs.INPUT_SOURCE: self.found.file(dh_jobs.OUT_SOURCE.role)}))

    # --- Lo importado (_import_steps) -------------------------------------------------------

    def log_lines(self, report: Mapping[str, Any]) -> list[Any]:
        """El informe de la base en ``dh_import_log``: los recuentos de cada tabla de RecMin,
        cada registro rechazado y los avisos (``_log_lines`` de una base de RecMin)."""
        lines = [store.LogLine.summary(str(table), int(found.get("read", 0)),
                                       int(found.get("imported", 0)),
                                       int(found.get("rejected", 0)))
                 for table, found in dict(report.get("counts") or {}).items()]
        lines += [store.LogLine.rejection(model.Rejection(*item))
                  for item in report.get("rejected", ())]
        lines += [store.LogLine.warning(recmin_schema.SOURCE_LABEL, str(text))
                  for text in report.get("warnings", ())]
        return lines

    def write_source(self) -> None:
        """Lo importado por pasos en una transacción (``SourceWriter``), la regla bajo el
        límite de detección de la primera importación y el original de la base desde la copia
        verificada de su lectura; los trabajos, incorporados."""
        applied = self.outcome(self.applied)
        tables: dict[str, Any] = {}
        contents: dict[str, Any] = {}
        for name, output in dict(applied.summary["outputs"]).items():
            role = name.removeprefix("dh_src_")
            tables[role] = dh_jobs.read_table_output(applied.file(name), name)
            contents[role] = gis_jobs.digest_of(output["digest"])
        report = json.loads(self.found.file(dh_jobs.OUT_REPORT.role).read_text(encoding="utf-8"))
        writer = store.SourceWriter(self.project)
        item = writer.add(self.handle, self.spec, tables, name=self.name, contents=contents,
                          log=self.log_lines(report),
                          message=f"Base de sondeos de RecMin «{self.path.name}» importada",
                          interpreter=self.found.interpreter, executor=self.found.executor,
                          job_uid=self.read.job_uid)
        _drive(writer.steps(software=self.software))
        parameters = core_params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            for key in dh_params.BELOW_DL_KEYS:
                parameters.ensure_default(
                    conn, key, geoblender_version=self.project.session.geoblender_version)
        verified = self.read.job_dir.inputs_dir / (gis_jobs.path_name("main") + self.path.suffix)
        _drive(writer.originals(item, [verified]))
        self.release(self.read, self.applied)

    # --- La base (_build_base_steps, _base_steps) --------------------------------------------

    def build_base(self) -> Any:
        """``dh.build_base`` desde lo importado vigente: leído por pasos, sus arrays por partes
        (``drillholes.jobs.packed_parts``), su trabajo ``dh_build_base`` y la base escrita por
        pasos (``BaseWriter``); su ``JobOutcome``."""
        with self.project.read() as conn:
            sources = store.live_sources(conn)
            has_log = dataset_registry.get(conn, store.IMPORT_LOG) is not None
        uses = [operations.Use(dataset.name, "source") for source in sources
                for dataset in source.datasets.values()]
        if has_log:
            uses.append(operations.Use(store.IMPORT_LOG, "imports"))
        handle = operations.begin_operation(self.project, provenance.BUILD_BASE, settings={},
                                            inputs=uses, executor="job_thread")
        entries: list[dict[str, Any]] = []
        loose: dict[str, Any] = {}
        rows = 0
        with self.project.read() as conn:
            for number, source in enumerate(sources, start=1):
                entry = _drive(store.source_entry_steps(conn, source))
                name = f"e{number}"
                for arrays in dh_jobs.packed_parts(name, {table: getattr(entry, table)
                                                          for table in model.TABLES},
                                                   entry.catalogs):
                    loose.update(arrays)
                rows += sum(len(getattr(entry, table)) for table in model.TABLES)
                entries.append({"input": name, "uid": entry.input_uid, "label": entry.label,
                                "declaration": dh_jobs.declaration_json(entry.declaration)})
        params = {"crs": gis_jobs.crs_json(self.crs),
                  "vertical": gis_jobs.vertical_json(self.vertical),
                  "project_uid": self.project.uid, "entries": entries, "count": rows + 1}
        if dh_jobs.needs_site(dh_jobs.BUILD_BASE, params):
            raise AssertionError("V-ref no necesita transformar nada")
        result = self.wait(self.submit(handle, dh_jobs.BUILD_BASE, params, arrays=loose))
        outcome = self.outcome(result)
        writer = store.BaseWriter(self.project, handle)
        for name in schema.BASE_TABLES:
            writer.table(name, dh_jobs.read_table_output(outcome.file(name), name),
                         content=gis_jobs.digest_of(outcome.summary["outputs"][name]["digest"]))
        _drive(writer.steps(software=self.software, message="Base de los sondeos",
                            interpreter=outcome.interpreter, executor=outcome.executor,
                            job_uid=result.job_uid))
        self.release(result)
        return outcome

    # --- La validación (_validate_steps, _validated_steps) -----------------------------------

    def validate(self) -> Any:
        """``dh.validate`` con la rejilla del proyecto: la base leída por pasos, sus arrays por
        partes, su trabajo ``dh_validate`` (el MDT por ruta: lo copia el trabajo) y
        ``dh_validation_issue`` escrita; su ``JobOutcome``."""
        surface = self.surface
        uses = [operations.Use(table, provenance.OUTPUT_ROLES[table])
                for table in schema.BASE_TABLES]
        uses.append(operations.Use(surface.name, "terrain"))
        handle = operations.begin_operation(
            self.project, provenance.VALIDATE, settings={"surface": surface.name},
            inputs=uses, params=list(dh_params.VALIDATION_KEYS), executor="job_thread")
        with self.project.read() as conn:
            dset = _drive(store.read_steps(conn))
        loose: dict[str, Any] = {}
        for arrays in dh_jobs.packed_parts(dh_jobs.INPUT_BASE,
                                           {table: getattr(dset, table)
                                            for table in model.TABLES}, dset.catalogs):
            loose.update(arrays)
        resolved = {param.key: param.value for param in handle.params}
        thresholds = {key.rpartition(".")[2]: resolved[key]
                      for key in dh_params.VALIDATION_KEYS}
        rows = sum(len(getattr(dset, table)) for table in model.TABLES)
        params = {"crs": gis_jobs.crs_json(dset.crs),
                  "vertical": gis_jobs.vertical_json(dset.vertical),
                  "thresholds": thresholds,
                  "work_window": gis_jobs.window_json(self.project.window),
                  "count": rows + 1}
        dem = Path(self.project.root, *surface.locator.split("/"))
        result = self.wait(self.submit(handle, dh_jobs.VALIDATE, params, arrays=loose,
                                       paths={dh_jobs.INPUT_DEM: dem}))
        outcome = self.outcome(result)
        name = store.VALIDATION_TABLE
        writer = store.BaseWriter(self.project, handle)
        writer.table(name, dh_jobs.read_table_output(outcome.file(name), name),
                     content=gis_jobs.digest_of(outcome.summary["outputs"][name]["digest"]))
        _drive(writer.steps(message="Validación de la base de los sondeos",
                            interpreter=outcome.interpreter, executor=outcome.executor,
                            job_uid=result.job_uid))
        self.release(result)
        return outcome


def _project_stack(stack: ExitStack, *, surface: bool) -> tuple[Path, Any, Any, Any]:
    """Una carpeta temporal con un proyecto nuevo y su lanzador, que ``stack`` cierra y borra:
    la carpeta, el proyecto, la rejilla del proyecto (``None`` sin ``surface``) y el
    lanzador."""
    folder = Path(stack.enter_context(tempfile.TemporaryDirectory(
        prefix="gb-dhm-p-", ignore_cleanup_errors=True)))
    project, found = _new_project(folder, surface=surface)
    stack.callback(project.close)
    runner = _runner(folder, project)
    stack.callback(runner.shutdown)
    return folder, project, found, runner


def _rows(project: Any, tables: Sequence[str]) -> dict[str, int]:
    with project.read() as conn:
        return {table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                for table in tables}


# --- La importación de principio a fin -------------------------------------------------------


@requires(recmin.ACE, recmin.ACE_HINT)
class ImportTest(unittest.TestCase):
    """RNF-005-05: importar la base de RecMin con V-ref de principio a fin."""

    times: list[float]
    phases: list[list[float]]
    jobs: dict[str, str]
    counts: dict[str, int]  # las filas de la base y de las incidencias tras la última
    statuses: list[tuple[str, str, int]]  # sus operaciones, por tipo y estado
    issues: list[tuple[str, str, int]]  # sus incidencias, por código y nivel

    @classmethod
    def setUpClass(cls) -> None:
        """:data:`IMPORT_REPETITIONS` importaciones de la base, cada una en un proyecto nuevo
        con su MDT; de la última se anotan las filas y las operaciones."""
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        _registrations(stack)
        cls.times, cls.phases = [], []
        for _number in range(IMPORT_REPETITIONS):
            with ExitStack() as run_stack:
                _folder, project, found, runner = _project_stack(run_stack, surface=True)
                importer = _Importer(project, runner, found)
                gc.collect()
                start = time.perf_counter()
                marks = importer.run()
                cls.times.append(marks[-1] - start)
                cls.phases.append([end - begin for begin, end
                                   in zip([start, *marks[:-1]], marks, strict=True)])
                cls.jobs = importer.jobs
                cls.counts = _rows(project, COUNTED)
                with project.read() as conn:
                    cls.statuses = conn.execute(
                        "SELECT op_type, status, count(*) FROM gb_operation "
                        "GROUP BY op_type, status ORDER BY op_type").fetchall()
                    cls.issues = conn.execute(
                        "SELECT code, level, count(*) FROM dh_validation_issue "
                        "GROUP BY code, level ORDER BY code").fetchall()

    def test_import_vref_database_end_to_end(self) -> None:
        """RNF-005-05: importar la base de RecMin con V-ref de principio a fin (su lectura con
        el extractor y el hash de la fuente, su aplicación con el de lo importado, su escritura
        con el original, la base con su hash y su validación con el MDT) en ≤ 60 s (mediana
        de :data:`IMPORT_REPETITIONS`); el proyecto queda con la base de V-ref entera, cada
        operación hecha y, de la validación, solo la profundidad deducida de cada sondeo."""
        phases = [statistics.median(run[index] for run in self.phases)
                  for index in range(len(PHASES))]
        shown = ", ".join(f"{name} {perf.number(value)} s"
                          for name, value in zip(PHASES, phases, strict=True))
        executors = ", ".join(f"{worker} {executor}" for worker, executor
                              in sorted(self.jobs.items()))
        perf.report(f"RNF-005-05: importar una base de RecMin con V-ref de principio a fin "
                    f"({_volume()}; {shown}; trabajos: {executors}; {MACHINE}): "
                    f"{perf.median_line(self.times)}, presupuesto "
                    f"{perf.number(IMPORT_BUDGET_S, 0)} s")
        self.assertEqual(self.counts, dict(zip(COUNTED, (
            VREF_HOLES, VREF_STATIONS, VREF_LITHOLOGY, VREF_VALUES, VREF_HOLES), strict=True)))
        self.assertEqual(self.issues, [(DEDUCED_DEPTH, "warning", VREF_HOLES)])
        self.assertEqual(self.statuses, [("dh.build_base", "done", 1),
                                         ("dh.import_recmin", "done", 1),
                                         ("dh.validate", "done", 1),
                                         ("gis.resample", "done", 1)])
        self.assertLessEqual(statistics.median(self.times), IMPORT_BUDGET_S)


# --- La cancelación a mitad ------------------------------------------------------------------


def _cancelled_read(project: Any, runner: Any) -> dict[str, Any]:
    """Lanza la lectura de la base en ``project`` y la cancela en cuanto su avance llega a
    :data:`CANCEL_AT` (``JobRunner.cancel``, como «Cancelar» en la barra de estado); la
    operación queda como la deja Blender (``ingest_job_result``: cancelada con el motivo de la
    004) y el trabajo, incorporado. Lo que tardó en parar (``stopped``: hasta su
    ``JobResult``) y en no quedar vivo el worker ni ningún descendiente suyo (``exited``), los
    descendientes vivos al cancelar (``children``) y al final (``alive``), el avance en que se
    canceló, su estado, si dejó algo en ``out/`` y lo que queda en el proyecto."""
    importer = _Importer(project, runner, None)
    before = jobs_fixtures.processes()
    importer.begin()
    handle = importer.launch_read()
    deadline = time.perf_counter() + WAIT_S
    while handle.result() is None and handle.frac < CANCEL_AT:
        if time.perf_counter() > deadline:
            raise AssertionError(f"la lectura no avanza en {WAIT_S:.0f} s")
        runner.poll()
        time.sleep(POLL_S)
    frac = handle.frac
    pid = handle.pid
    children = jobs_fixtures.descendants(before, jobs_fixtures.processes(), [pid])
    asked = time.perf_counter()
    runner.cancel(handle.job_uid)
    while handle.result() is None:
        if time.perf_counter() - asked > WAIT_S:
            raise AssertionError(f"la lectura no para en {WAIT_S:.0f} s")
        runner.poll()
        time.sleep(POLL_S)
    stopped = time.perf_counter() - asked
    while True:
        alive = jobs_fixtures.descendants(before, jobs_fixtures.processes(), [pid])
        if jobs_fixtures.pid_alive(pid):
            alive[pid] = "worker"
        exited = time.perf_counter() - asked
        if not alive or exited > WAIT_S:
            break
        time.sleep(PROCESS_POLL_S)
    result = handle.result()
    outputs = sorted(path.name for path in result.job_dir.outputs_dir.iterdir())
    operations.ingest_job(project, importer.handle,
                          ingest.job_outcome(result, result.job_dir), ())
    runner.mark_ingested(result.job_uid)
    with project.read() as conn:
        tables = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name GLOB 'dh_*' "
            "ORDER BY name")]
        statuses = conn.execute("SELECT op_type, status, status_reason FROM gb_operation "
                                "ORDER BY fid").fetchall()
        inputs = conn.execute("SELECT count(*) FROM gb_input").fetchone()[0]
    originals = Path(project.root, originals_mod.ORIGINALS_DIR)
    kept = sorted(path.name for path in originals.rglob("*")) if originals.exists() else []
    return {"frac": frac, "stopped": stopped, "exited": exited, "state": result.state,
            "children": children, "alive": alive, "outputs": outputs, "tables": tables,
            "statuses": statuses, "inputs": inputs, "originals": kept}


@requires(recmin.ACE, recmin.ACE_HINT)
class CancelTest(unittest.TestCase):
    """RNF-005-05: cancelar la importación de la base de RecMin a mitad de su lectura."""

    runs: list[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        """:data:`CANCEL_REPETITIONS` lecturas de la base, cada una en un proyecto nuevo,
        canceladas a mitad; de cada una se anota lo que tardó en parar y en no quedar ningún
        proceso suyo, y cómo quedó el proyecto."""
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        _registrations(stack)
        cls.runs = []
        for _number in range(CANCEL_REPETITIONS):
            with ExitStack() as run_stack:
                _folder, project, _found, runner = _project_stack(run_stack, surface=False)
                cls.runs.append(_cancelled_read(project, runner))

    def test_cancel_at_half_within_two_seconds(self) -> None:
        """RNF-005-05: cancelar a mitad la lectura de la base (con su ``powershell.exe`` hijo
        leyéndola) la para en ≤ 2 s y en ≤ 2 s no queda vivo ni el worker ni ningún proceso
        que descienda de él, en cada una de las :data:`CANCEL_REPETITIONS`."""
        stopped = [run["stopped"] for run in self.runs]
        exited = [run["exited"] for run in self.runs]
        at = ", ".join(f"{100 * run['frac']:.0f} %" for run in self.runs)
        perf.report(f"RNF-005-05: cancelar a mitad la lectura de una base de RecMin con V-ref "
                    f"({_volume()}; canceladas al {at} de la lectura, con su powershell.exe "
                    f"hijo; {MACHINE}): parada en "
                    f"{', '.join(perf.number(value) for value in stopped)} s y sin ningún "
                    f"proceso suyo vivo en {', '.join(perf.number(value) for value in exited)} "
                    f"s, presupuesto {perf.number(CANCEL_BUDGET_S, 0)} s")
        for run in self.runs:
            self.assertEqual(run["state"], CANCELLED)
            self.assertIn("powershell.exe", {name.casefold() for name
                                             in run["children"].values()})
            self.assertEqual(run["alive"], {})
            self.assertLessEqual(run["stopped"], CANCEL_BUDGET_S)
            self.assertLessEqual(run["exited"], CANCEL_BUDGET_S)

    def test_cancel_leaves_nothing_in_the_project(self) -> None:
        """RNF-005-05, RF-005-04: la lectura cancelada no deja nada: el trabajo, sin
        resultados en ``out/``; el proyecto, sin ninguna tabla de sondeos, ninguna entrada ni
        ningún original, y la importación, cancelada con el motivo de la 004."""
        for run in self.runs:
            self.assertEqual(run["outputs"], [])
            self.assertEqual(run["tables"], [])
            self.assertEqual(run["inputs"], 0)
            self.assertEqual(run["originals"], [])
            ((op_type, status, reason),) = run["statuses"]
            self.assertEqual((op_type, status), (provenance.IMPORT_RECMIN, CANCELLED))
            self.assertTrue(reason)


if __name__ == "__main__":
    unittest.main()
