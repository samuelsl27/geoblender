# SPDX-License-Identifier: GPL-3.0-or-later
"""Las importaciones de sondeos como las hace Blender, sin Blender: lo común (spec 005; plan
005 §5.6.5 y §5.6.6).

:class:`ImportDriver` lanza los trabajos de la 004 de una importación en un ``JobRunner``
propio como ``core_provenance.launch_job`` (:meth:`~ImportDriver.submit`: la petición con su
operación y su proyecto, los arrays escritos en ``in/`` antes de lanzarlo y las rutas por la
línea de órdenes), los espera sondeando el lanzador (:meth:`~ImportDriver.wait` y
:meth:`~ImportDriver.wait_all`), lee lo que dieron (:meth:`~ImportDriver.outcome`, con dónde
corrió cada uno) y los da por incorporados (:meth:`~ImportDriver.release`). Tras escribir lo
importado, repite lo que hace ``bl/ops/dh.py`` con los pasos de cada escritura seguidos
(:func:`drive`), sin las pausas del temporizador de Blender: la base
(:meth:`~ImportDriver.build_base`: ``_build_base_steps`` y ``_base_steps``) y su validación
(:meth:`~ImportDriver.validate`: ``_validate_steps`` y ``_validated_steps``).

Lo usan la importación de una base de RecMin (``tests.support.recmin_import``: su
rendimiento, T33, y el banco de RecMin, T34) y la de las tablas CSV de V-ref
(``tests/rendimiento/test_dh_perf.py``, T31). :func:`registrations` registra lo que registra
Blender al habilitar Geoblender y usa la importación; :func:`new_runner`, el lanzador.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from collections import defaultdict
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.repo import EXTENSION_DIR

dh_content = import_geoblender("interop.dh_content")
model = import_geoblender("drillholes.model")
dh_jobs = import_geoblender("drillholes.jobs")
dh_params = import_geoblender("drillholes.params")
provenance = import_geoblender("drillholes.provenance")
schema = import_geoblender("drillholes.schema")
store = import_geoblender("drillholes.store")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
dataset_registry = import_geoblender("core.datasets.registry")
operations = import_geoblender("core.provenance.operations")
core_params = import_geoblender("core.params")
core_defs = import_geoblender("core.params.core_defs")
gis_crs = import_geoblender("gis.crs")
gis_jobs = import_geoblender("gis.jobs")
gis_provenance = import_geoblender("gis.provenance")
gis_store = import_geoblender("gis.store")
catalog = import_geoblender("jobs.catalog")
ingest = import_geoblender("jobs.ingest")
protocol = import_geoblender("jobs.protocol")
runner_mod = import_geoblender("jobs.runner")

MAX_SUBPROCESS = 2  # los trabajos a la vez en proceso aparte de Blender (MAX_PARALLEL_DEFAULT)
POLL_S = 0.005  # sondeo del lanzador mientras espera un trabajo
WAIT_S = 600.0  # plazo de seguridad: un trabajo colgado no cuelga la prueba
SUCCEEDED = "succeeded"


def _recompute(request: Any) -> Any:  # pragma: no cover - nada se recalcula aquí
    raise AssertionError("no se recalcula en estas pruebas")


def registrations(stack: ExitStack) -> None:
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


def new_runner(folder: Path, project: Any) -> Any:
    """El lanzador de trabajos de la importación, como el de Blender: dos a la vez en proceso
    aparte y uno en el hilo, con la carpeta del proyecto prohibida y sus trabajos en
    ``folder/trabajos``."""
    return runner_mod.JobRunner(jobs_root=folder / "trabajos", package_dir=EXTENSION_DIR,
                                blender_python=Path(sys.executable),
                                max_subprocess=MAX_SUBPROCESS,
                                forbidden_roots=[Path(project.root)])


def drive[T](steps: Generator[Any, None, T] | Iterator[Any]) -> T | None:
    """Recorre los pasos ``steps`` seguidos (sin las pausas del temporizador de Blender) y da
    lo que devuelven."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


class ImportDriver:
    """Los trabajos de una importación de sondeos en ``project`` con el lanzador ``runner``
    (véase el módulo). ``job_label``: el principio del nombre de sus trabajos."""

    def __init__(self, project: Any, runner: Any, *, job_label: str = "Prueba") -> None:
        self.project = project
        self.runner = runner
        self.job_label = job_label
        self.crs, self.vertical = gis_store.project_references(project)
        self.software = dict([gis_crs.crs_library()])
        self.workers: dict[str, str] = {}  # el tipo de cada trabajo lanzado, por su uid
        self.names: dict[str, str] = {}  # de qué es cada trabajo lanzado (su fichero…)
        self.executors: dict[str, str] = {}  # dónde corrió cada trabajo leído, por su uid
        self.jobs: dict[str, str] = {}  # dónde corrió el último trabajo leído de cada tipo

    # --- Los trabajos -----------------------------------------------------------------------

    def submit(self, handle: Any, worker: str, params: Mapping[str, Any], *, name: str = "",
               paths: Mapping[str, Path] | None = None,
               arrays: Mapping[str, np.ndarray] | None = None) -> Any:
        """Lanza el trabajo ``worker`` de la operación ``handle`` (de ``name``: su fichero o
        lo que sea; por defecto, nada) como ``core_provenance.launch_job``: la petición con la
        operación y el proyecto, ``arrays`` escritos en ``in/`` antes de lanzarlo y ``paths``
        por la línea de órdenes; su ``JobHandle``."""
        request = protocol.new_request(worker, label=f"{self.job_label}: {worker}",
                                       owner=handle.definition.module, params=dict(params),
                                       project_uid=handle.project_uid, operation_uid=handle.uid,
                                       grace_s=dh_jobs.CANCEL_GRACE_S)
        job: Any = request
        if arrays:
            folder = self.runner.prepare(request)
            prepared = protocol.read_request(folder)
            written = {key: folder.write_array(key, array) for key, array in arrays.items()}
            protocol.write_request(folder, dataclasses.replace(
                prepared, inputs={**dict(prepared.inputs), **written}))
            job = folder
        self.workers[request.job_uid] = worker
        self.names[request.job_uid] = name
        return self.runner.submit(job, paths=paths)

    def wait_all(self, handles: Sequence[Any]) -> list[Any]:
        """Espera a que terminen los trabajos ``handles`` sondeando el lanzador; sus
        ``JobResult``, en su orden. Falla si alguno no termina bien."""
        deadline = time.perf_counter() + WAIT_S
        while any(handle.result() is None for handle in handles):
            if time.perf_counter() > deadline:
                raise AssertionError(f"los trabajos no terminan en {WAIT_S:.0f} s")
            self.runner.poll()
            time.sleep(POLL_S)
        results = [handle.result() for handle in handles]
        for result in results:
            if result.state != SUCCEEDED:
                raise AssertionError(f"un trabajo terminó «{result.state}»: "
                                     f"{result.error_code} {result.error_text}")
        return results

    def wait(self, handle: Any) -> Any:
        """Espera a que termine el trabajo ``handle``; su ``JobResult``. Falla si no termina
        bien."""
        (result,) = self.wait_all([handle])
        return result

    def outcome(self, result: Any) -> Any:
        """Lo que dio el trabajo de ``result`` (``JobOutcome``); anota dónde corrió."""
        outcome = ingest.job_outcome(result, result.job_dir)
        self.executors[result.job_uid] = str(outcome.executor)
        self.jobs[self.workers[result.job_uid]] = str(outcome.executor)
        return outcome

    def executors_text(self) -> str:
        """Dónde corrió cada trabajo leído, por tipo y en el orden en que se lanzaron: «tipo
        ejecutor» si todos los de un tipo corrieron en el mismo y, si no, cada ejecutor con
        los nombres de sus trabajos («dh_import_apply job_process (análisis), job_thread
        (bocas, desviaciones)»); los tipos, separados por «; »."""
        found: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for job_uid, worker in self.workers.items():
            if job_uid in self.executors:
                found[worker][self.executors[job_uid]].append(self.names[job_uid])
        parts = []
        for worker, executors in found.items():
            if len(executors) == 1:
                ((executor, names),) = executors.items()
                count = f" ×{len(names)}" if len(names) > 1 else ""
                parts.append(f"{worker} {executor}{count}")
            else:
                parts.append(f"{worker} " + ", ".join(
                    f"{executor} ({', '.join(names)})" for executor, names in executors.items()))
        return "; ".join(parts)

    def release(self, *results: Any) -> None:
        """Da por incorporados los trabajos de ``results`` (se borran sus entradas y sus
        resultados), como ``core_provenance.release_job``."""
        for result in results:
            self.runner.mark_ingested(result.job_uid)

    # --- La base (_build_base_steps, _base_steps) --------------------------------------------

    def build_base(self) -> Any:
        """``dh.build_base`` desde lo importado vigente: la operación «en curso» con lo que
        consume, lo importado leído por pasos, sus arrays por partes
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
                entry = drive(store.source_entry_steps(conn, source))
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
            raise AssertionError("la base no necesita transformar nada en estas pruebas")
        result = self.wait(self.submit(handle, dh_jobs.BUILD_BASE, params, name="base",
                                       arrays=loose))
        outcome = self.outcome(result)
        writer = store.BaseWriter(self.project, handle)
        for name in schema.BASE_TABLES:
            writer.table(name, dh_jobs.read_table_output(outcome.file(name), name),
                         content=gis_jobs.digest_of(outcome.summary["outputs"][name]["digest"]))
        drive(writer.steps(software=self.software, message="Base de los sondeos",
                           interpreter=outcome.interpreter, executor=outcome.executor,
                           job_uid=result.job_uid))
        self.release(result)
        return outcome

    # --- La validación (_validate_steps, _validated_steps) -----------------------------------

    def validate(self, surface: Any) -> Any:
        """``dh.validate`` con la rejilla del proyecto ``surface`` (su registro; ``None``, sin
        ninguna): la operación «en curso» con lo que consume y sus parámetros, la base leída
        por pasos, sus arrays por partes, su trabajo ``dh_validate`` (el MDT por ruta: lo
        copia el trabajo) y ``dh_validation_issue`` escrita; su ``JobOutcome``."""
        uses = [operations.Use(table, provenance.OUTPUT_ROLES[table])
                for table in schema.BASE_TABLES]
        if surface is not None:
            uses.append(operations.Use(surface.name, "terrain"))
        handle = operations.begin_operation(
            self.project, provenance.VALIDATE,
            settings={"surface": None if surface is None else surface.name},
            inputs=uses, params=list(dh_params.VALIDATION_KEYS), executor="job_thread")
        paths: dict[str, Path] = {}
        if surface is not None:
            paths[dh_jobs.INPUT_DEM] = Path(self.project.root, *surface.locator.split("/"))
        with self.project.read() as conn:
            dset = drive(store.read_steps(conn))
        loose: dict[str, Any] = {}
        for arrays in dh_jobs.packed_parts(dh_jobs.INPUT_BASE,
                                           {table: getattr(dset, table)
                                            for table in model.TABLES}, dset.catalogs):
            loose.update(arrays)
        resolved = {param.key: param.value for param in handle.params}
        thresholds = {key.rpartition(".")[2]: resolved[key]
                      for key in dh_params.VALIDATION_KEYS}
        window = self.project.window
        rows = sum(len(getattr(dset, table)) for table in model.TABLES)
        params = {"crs": gis_jobs.crs_json(dset.crs),
                  "vertical": gis_jobs.vertical_json(dset.vertical),
                  "thresholds": thresholds,
                  "work_window": None if window is None else gis_jobs.window_json(window),
                  "count": rows + 1}
        result = self.wait(self.submit(handle, dh_jobs.VALIDATE, params, name="validación",
                                       arrays=loose, paths=paths or None))
        outcome = self.outcome(result)
        name = store.VALIDATION_TABLE
        writer = store.BaseWriter(self.project, handle)
        writer.table(name, dh_jobs.read_table_output(outcome.file(name), name),
                     content=gis_jobs.digest_of(outcome.summary["outputs"][name]["digest"]))
        drive(writer.steps(message="Validación de la base de los sondeos",
                           interpreter=outcome.interpreter, executor=outcome.executor,
                           job_uid=result.job_uid))
        self.release(result)
        return outcome
