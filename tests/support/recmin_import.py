# SPDX-License-Identifier: GPL-3.0-or-later
"""La importación de una base de RecMin como la hace Blender, sin Blender (spec 005; plan 005
§5.6.5 y §5.6.7).

:class:`RecminImport` repite lo que hace ``geoblender.dh_import_recmin_mdb`` en
``bl/ops/dh.py`` (``start_order``, ``_read_job``, ``_after_reading``, ``_apply`` e
``_import_steps``) con los trabajos de la 004 en un ``JobRunner`` propio y los pasos de la
escritura seguidos, sin las pausas del temporizador de Blender: la operación
``dh.import_recmin`` «en curso» (``begin_operations``), la lectura de la base
(``dh_import_recmin`` en proceso aparte, con la base por ``paths``: su copia verificada, sus
tablas con el extractor y su ``powershell.exe`` hijo, el hash de contenido de la fuente con
``io.recmin_mdb@1`` y lo leído), su aplicación (``dh_import_apply``: las filas de lo
importado y su hash, con los códigos nuevos dados de alta, como propone «Importación
pendiente») y lo importado escrito por pasos en una transacción
(``drillholes.store.SourceWriter``: la entrada, lo importado, el informe y el original de la
base), con la regla bajo el límite de detección de la primera importación.

Lo usan el rendimiento de la importación de una base de RecMin
(``tests/rendimiento/test_dh_mdb_perf.py``, T33, que añade la base y su validación) y el
banco de RecMin (``tests/banco/recmin/``, T34). :func:`registrations` registra lo que
registra Blender al habilitar Geoblender y usa la importación; :func:`new_runner`, el
lanzador; :func:`drive`, los pasos de una escritura seguidos.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from collections.abc import Generator, Iterator, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.repo import EXTENSION_DIR

dh_content = import_geoblender("interop.dh_content")
recmin_schema = import_geoblender("interop.recmin.schema")
model = import_geoblender("drillholes.model")
dh_arrays = import_geoblender("drillholes.arrays")
dh_jobs = import_geoblender("drillholes.jobs")
dh_params = import_geoblender("drillholes.params")
provenance = import_geoblender("drillholes.provenance")
store = import_geoblender("drillholes.store")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
inputs_mod = import_geoblender("core.inputs")
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
DECIMAL = ","  # el de los números escritos como texto (RecMin no tiene)
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


class RecminImport:
    """La importación de la base ``path`` en ``project`` con el lanzador ``runner`` (véase el
    módulo), con lo que declara quien la importa (``declaration``, un
    ``drillholes.model.SourceDeclaration``), el separador decimal de sus ajustes
    (``decimal``) y, con ``accept_schema``, leída aunque su versión de esquema no sea 11 ni 12
    (lo que hace «Leer igualmente»). ``name``, el nombre de lo importado (por defecto, el de la
    base sin su extensión); ``job_label``, el principio del nombre de sus trabajos."""

    def __init__(self, project: Any, runner: Any, path: Path, declaration: Any, *,
                 decimal: str = DECIMAL, accept_schema: bool = False, name: str | None = None,
                 job_label: str = "Prueba") -> None:
        self.project = project
        self.runner = runner
        self.path = Path(path)
        self.name = self.path.stem if name is None else name
        self.declaration = declaration
        self.decimal = decimal
        self.accept_schema = accept_schema
        self.job_label = job_label
        self.crs, self.vertical = gis_store.project_references(project)
        self.software = dict([gis_crs.crs_library()])
        self.catalogs: Any = None  # los del proyecto al empezar la orden
        self.holes: Any = None  # sus sondeos con registros en cada tabla, al empezar
        self.handle: Any = None  # la operación dh.import_recmin
        self.read: Any = None  # el JobHandle y, terminado, el JobResult de su lectura
        self.found: Any = None  # el JobOutcome de su lectura
        self.spec: Any = None  # su entrada (InputSpec)
        self.applied: Any = None  # el JobHandle y, terminado, el JobResult de su aplicación
        self.item: Any = None  # la entrada escrita (store.SourceInput)
        self.report: dict[str, Any] = {}  # el informe de su lectura (report.json)
        self.workers: dict[str, str] = {}  # el tipo de cada trabajo lanzado, por su uid
        self.jobs: dict[str, str] = {}  # el ejecutor de cada tipo de trabajo

    # --- Lo común --------------------------------------------------------------------------

    def submit(self, handle: Any, worker: str, params: Mapping[str, Any], *,
               paths: Mapping[str, Path] | None = None,
               arrays: Mapping[str, np.ndarray] | None = None) -> Any:
        """Lanza el trabajo ``worker`` de la operación ``handle`` como
        ``core_provenance.launch_job``: la petición con la operación y el proyecto, ``arrays``
        escritos en ``in/`` antes de lanzarlo y ``paths`` por la línea de órdenes."""
        request = protocol.new_request(worker, label=f"{self.job_label}: {worker}",
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

    def import_source(self) -> None:
        """La importación entera (lectura, aplicación y escritura), hasta que se confirma lo
        importado."""
        self.begin()
        self.launch_read()
        self.read = self.wait(self.read)
        self.found = self.outcome(self.read)
        self.apply()
        self.write_source()

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
                    "decimal": self.decimal, **conventions}
        (self.handle,) = operations.begin_operations(
            self.project, provenance.IMPORT_RECMIN, settings=[settings],
            executor="job_process")

    def launch_read(self) -> Any:
        """Lanza la lectura de la base (``dh_import_recmin``, en proceso aparte) con la base
        por ``paths``; su ``JobHandle``."""
        params = {"name": self.name, "declaration": dh_jobs.declaration_json(self.declaration),
                  "settings": {"decimal": self.decimal}, "crs": gis_jobs.crs_json(self.crs),
                  "vertical": gis_jobs.vertical_json(self.vertical),
                  "project_holes": {table: list(names) for table, names in self.holes.items()},
                  "catalogs": dh_arrays.catalogs_json(self.catalogs),
                  "size": self.path.stat().st_size, "accept_schema": self.accept_schema}
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
        self.report = json.loads(
            self.found.file(dh_jobs.OUT_REPORT.role).read_text(encoding="utf-8"))
        writer = store.SourceWriter(self.project)
        self.item = writer.add(self.handle, self.spec, tables, name=self.name,
                               contents=contents, log=self.log_lines(self.report),
                               message=f"Base de sondeos de RecMin «{self.path.name}» importada",
                               interpreter=self.found.interpreter,
                               executor=self.found.executor, job_uid=self.read.job_uid)
        drive(writer.steps(software=self.software))
        parameters = core_params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            for key in dh_params.BELOW_DL_KEYS:
                parameters.ensure_default(
                    conn, key, geoblender_version=self.project.session.geoblender_version)
        verified = self.read.job_dir.inputs_dir / (gis_jobs.path_name("main") + self.path.suffix)
        drive(writer.originals(self.item, [verified]))
        self.release(self.read, self.applied)
