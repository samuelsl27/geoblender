# SPDX-License-Identifier: GPL-3.0-or-later
"""El final de un trabajo para incorporarlo a su operación (spec 008; RF-008-20; ADR-0004 R4;
plan 008 §5.3.1 y §5.4.7).

:func:`job_outcome` convierte el final de un trabajo (``runner.JobResult``) y su
``state.json`` (``records.read_record``) en el ``JobOutcome`` de ``core.provenance``, el objeto
de datos con el que ``core.provenance.ingest_job`` incorpora el resultado a la operación que lo
lanzó: ``core`` no importa ``jobs`` (ADR-0004 R4) y ``jobs`` sí importa ``core``. Lleva su
estado, su ejecutor (:data:`EXECUTORS`: en un hilo de Blender o en proceso aparte), su nombre,
su carpeta, la operación de su petición, sus resultados verificados con su huella, su resumen,
su error y, de ``state.json``, la procedencia técnica de su intérprete (tipo, versiones de
Python y de numpy, BLAS e identificador del motor de cálculo, ``lock_id``).

Lo usa ``bl`` al terminar un trabajo (``ingest_job_result``, T48): ``job_outcome`` →
``ingest_job`` → ``JobRunner.mark_ingested`` si se incorporó. Solo lee la carpeta del trabajo.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ..core.provenance.operations import Executor, JobOutcome, OutputPrint
from .paths import JobDir
from .records import read_record
from .runner import EXECUTOR_INPROCESS, EXECUTOR_SUBPROCESS, JobResult

EXECUTORS: Mapping[str, Executor] = MappingProxyType({
    EXECUTOR_INPROCESS: Executor.JOB_THREAD,
    EXECUTOR_SUBPROCESS: Executor.JOB_PROCESS,
})
"""El ejecutor de la operación (``gb_operation.executor``) por el del trabajo
(``state.json``): en un hilo de Blender o en proceso aparte."""


def job_outcome(result: JobResult, job_dir: JobDir) -> JobOutcome:
    """El ``JobOutcome`` del trabajo que terminó con ``result`` en la carpeta ``job_dir``
    (véase el módulo). :class:`TypeError` si no son un ``JobResult`` y un ``JobDir``;
    :class:`ValueError` si la carpeta es de otro trabajo o su ``state.json`` falta o no se
    puede leer (sin él no se conoce la procedencia técnica del trabajo) o el de un final que
    no es válido."""
    if not isinstance(result, JobResult):
        raise TypeError(f"job_outcome recibe el final de un trabajo (JobResult), no {result!r}")
    if not isinstance(job_dir, JobDir):
        raise TypeError(f"job_outcome recibe la carpeta del trabajo (JobDir), no {job_dir!r}")
    if job_dir.job_uid != result.job_uid:
        raise ValueError(f"la carpeta {job_dir.job_uid} no es la del trabajo {result.job_uid}")
    record = read_record(job_dir)
    if record is None:
        raise ValueError(f"no se puede leer el state.json del trabajo {result.job_uid}: sin él "
                         "no se conoce su procedencia técnica y no se incorpora")
    interpreter = None if record.interpreter is None else record.interpreter.to_json()
    return JobOutcome(
        result.job_uid, result.state, EXECUTORS[record.executor],
        label=record.label, folder=job_dir.path,
        outputs=tuple(OutputPrint(ref.path, ref.sha256, ref.role, size=ref.size)
                      for ref in result.outputs),
        summary=result.summary, interpreter=interpreter, error_code=result.error_code,
        error_text=result.error_text, operation_uid=record.operation_uid,
    )
