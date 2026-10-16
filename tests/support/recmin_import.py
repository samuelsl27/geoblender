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
banco de RecMin (``tests/banco/recmin/``, T34). Lo común de una importación de sondeos (los
trabajos, la base y su validación) está en ``tests.support.dh_import``; de allí vienen
también :func:`registrations` (lo que registra Blender al habilitar Geoblender y usa la
importación), :func:`new_runner` (el lanzador) y :func:`drive` (los pasos de una escritura
seguidos).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.support.dh_import import ImportDriver, drive, new_runner, registrations
from tests.support.package import import_geoblender

recmin_schema = import_geoblender("interop.recmin.schema")
model = import_geoblender("drillholes.model")
dh_arrays = import_geoblender("drillholes.arrays")
dh_jobs = import_geoblender("drillholes.jobs")
dh_params = import_geoblender("drillholes.params")
provenance = import_geoblender("drillholes.provenance")
store = import_geoblender("drillholes.store")
inputs_mod = import_geoblender("core.inputs")
operations = import_geoblender("core.provenance.operations")
core_params = import_geoblender("core.params")
gis_jobs = import_geoblender("gis.jobs")

__all__ = ["DECIMAL", "RecminImport", "drive", "new_runner", "registrations"]

DECIMAL = ","  # el de los números escritos como texto (RecMin no tiene)


class RecminImport(ImportDriver):
    """La importación de la base ``path`` en ``project`` con el lanzador ``runner`` (véase el
    módulo), con lo que declara quien la importa (``declaration``, un
    ``drillholes.model.SourceDeclaration``), el separador decimal de sus ajustes
    (``decimal``) y, con ``accept_schema``, leída aunque su versión de esquema no sea 11 ni 12
    (lo que hace «Leer igualmente»). ``name``, el nombre de lo importado (por defecto, el de la
    base sin su extensión); ``job_label``, el principio del nombre de sus trabajos."""

    def __init__(self, project: Any, runner: Any, path: Path, declaration: Any, *,
                 decimal: str = DECIMAL, accept_schema: bool = False, name: str | None = None,
                 job_label: str = "Prueba") -> None:
        super().__init__(project, runner, job_label=job_label)
        self.path = Path(path)
        self.name = self.path.stem if name is None else name
        self.declaration = declaration
        self.decimal = decimal
        self.accept_schema = accept_schema
        self.catalogs: Any = None  # los del proyecto al empezar la orden
        self.holes: Any = None  # sus sondeos con registros en cada tabla, al empezar
        self.handle: Any = None  # la operación dh.import_recmin
        self.read: Any = None  # el JobHandle y, terminado, el JobResult de su lectura
        self.found: Any = None  # el JobOutcome de su lectura
        self.spec: Any = None  # su entrada (InputSpec)
        self.applied: Any = None  # el JobHandle y, terminado, el JobResult de su aplicación
        self.item: Any = None  # la entrada escrita (store.SourceInput)
        self.report: dict[str, Any] = {}  # el informe de su lectura (report.json)

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
        self.read = self.submit(self.handle, dh_jobs.IMPORT_RECMIN, params, name=self.name,
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
            self.handle, dh_jobs.IMPORT_APPLY, params, name=self.name,
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
