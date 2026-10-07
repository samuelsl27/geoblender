# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``runtime_check``: verifica el motor de cálculo (spec 004; HU-004-3;
RF-004-22, RF-004-25; plan 004 §5.4.7).

Siempre en un proceso aparte, en el entorno ``compute``: el Python de Blender con ``-I -S`` y,
como única carpeta de paquetes, la del motor que se verifica (el ``site_override`` del
lanzador: ``<lock_id>.partial/site`` recién instalada o la del motor instalado), que también
llega en la línea de órdenes (``--path site=…``, ``ctx.paths``). El arranque ya comprobó que
numpy se carga desde esa carpeta con la versión del lock (si no, el trabajo no llega aquí:
salida 5). La petición (``ComputeEnvironment.verify_request``) lleva el lock contra el que se
verifica.

``jobs.runtime.probe_environment`` comprueba la versión de cada paquete del lock, el origen de
numpy, su BLAS y la longitud máxima de ruta, y mide el producto 2000 × 2000. Lo medido y cada
problema van a ``job.log``; si hay alguno, el trabajo falla con el primero (su mensaje del
§8); si no, devuelve el resumen de la verificación. No adopta el motor ni anota nada: lo hace
la cadena del lanzador (``jobs.runtime.RuntimeSetup``).
"""

from __future__ import annotations

from ..jobs import runtime
from ..jobs.protocol import JobRequest, JsonValue
from ..jobs.worker_api import WorkerContext


def main(ctx: WorkerContext) -> dict[str, JsonValue]:
    """Verifica la carpeta ``site`` de la línea de órdenes contra el lock de la petición y
    devuelve el resumen (``runtime.probe_environment``)."""
    task = runtime.check_task(ctx.request.params, ctx.paths, job=_job_name(ctx.request))
    check = runtime.probe_environment(task.lock, task.site_dir, progress=ctx.progress)
    ctx.log("info", f"Verificación del motor de cálculo: {runtime.check_text(check)}")
    errors = runtime.check_errors(check)
    for error in errors:
        ctx.log("warning", error.text)
    if errors:
        raise errors[0]
    ctx.progress(1.0, runtime.CHECKED_TEXT)
    return check


def _job_name(request: JobRequest) -> str:
    label = request.label
    return label if isinstance(label, str) and label.strip() else request.worker
