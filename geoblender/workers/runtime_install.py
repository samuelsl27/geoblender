# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``runtime_install``: instala el motor de cálculo en su carpeta parcial
(spec 004; HU-004-3, HU-004-4; RF-004-21, RF-004-24; plan 004 §5.4.7).

Siempre en un proceso aparte, con el Python de Blender (entorno ``blender``). Recibe la
petición de ``ComputeEnvironment.install_request`` (lock, origen, paquetes con su huella y
el consentimiento del usuario) y, en la línea de órdenes (``--path``, ``ctx.paths``), la
carpeta de los motores (``runtime``) y, con el almacén de ruedas, su carpeta
(``wheelhouse``). Pasos:

1. Borra la carpeta ``<lock_id>.partial`` que dejara un intento anterior cortado a la
   mitad: nunca se usa y se borra en el siguiente intento (spec §8).
2. Copia del almacén o descarga cada rueda en ``out/wheels`` comprobando su huella
   (``jobs.runtime.fetch_wheel``): otra huella es ``wheel_hash_mismatch``, antes de instalar
   nada (RF-004-21, RF-004-24).
3. ``out/requirements.txt`` con las huellas e instalación con ``jobs.runtime.run_pip_install``
   en ``<lock_id>.partial/site`` (la orden la construye solo ``jobs/runtime.py``); lo que
   escribe el instalador va a ``job.log``.
4. Pase lo que pase, borra las ruedas copiadas; si algo falla o se cancela, borra también
   ``<lock_id>.partial``: no queda ningún motor a medias (RF-004-21).

No adopta el motor: lo verifica (``runtime_check``) y lo adopta la cadena de instalación
(T28) con ``os.replace(<lock_id>.partial → <lock_id>)``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..jobs import runtime
from ..jobs.protocol import JobRequest, JsonValue
from ..jobs.worker_api import JobCancelled, WorkerContext

FETCH_SHARE = 0.5
"""Parte del avance que corresponde a traer las ruedas (el resto, a instalarlas)."""
CANCELLED_TEXT = "Instalación cancelada: no se ha instalado nada"
DONE_TEXT = "Paquetes instalados"


def main(ctx: WorkerContext) -> dict[str, JsonValue]:
    """Instala los paquetes de la petición en ``<runtime>/<lock_id>.partial/site`` y
    devuelve el resumen: ``lock_id``, origen y paquetes (nombre, versión y huella)."""
    task = runtime.install_task(ctx.request.params, ctx.paths, job=_job_name(ctx.request))
    if task.partial_path.exists():
        ctx.log("info", "Se borra una instalación anterior que quedó a medias")
        _remove_partial(task, strict=True)
    wheels_dir = ctx.output_path(runtime.WHEELS_DIR)
    total = sum(package.size for package in task.packages) or 1
    count = len(task.packages)
    try:
        fetched = 0
        for index, package in enumerate(task.packages, start=1):
            message = f"Rueda {index} de {count}: {package.filename}"
            ctx.progress(FETCH_SHARE * fetched / total, message)

            def advance(done: int, base: int = fetched, text: str = message) -> None:
                ctx.progress(FETCH_SHARE * (base + done) / total, text)

            runtime.fetch_wheel(package, task.source, wheels_dir, progress=advance,
                                cancelled=ctx.check_cancelled)
            fetched += package.size
        requirements = runtime.write_requirements(
            task.packages, ctx.output_path(runtime.REQUIREMENTS_FILE))
        task.site_dir.mkdir(parents=True)
        ctx.progress(FETCH_SHARE, runtime.INSTALLING_TEXT)
        sys.stderr.flush()
        runtime.run_pip_install(Path(sys.executable), wheels_dir, requirements, task.site_dir,
                                cancelled=ctx.check_cancelled, log=sys.stderr)
    except JobCancelled:
        _remove_partial(task, ctx=ctx)
        raise JobCancelled(CANCELLED_TEXT) from None
    except BaseException:
        _remove_partial(task, ctx=ctx)
        raise
    finally:
        runtime.remove_tree(wheels_dir)
    ctx.progress(1.0, DONE_TEXT)
    return {
        "lock_id": task.lock_id,
        "source": task.source.kind,
        "packages": [
            {"name": package.name, "version": package.version, "sha256": package.sha256}
            for package in task.packages
        ],
    }


def _remove_partial(
    task: runtime.InstallTask, *, ctx: WorkerContext | None = None, strict: bool = False
) -> None:
    """Borra ``<lock_id>.partial``. Si no se puede: antes de instalar (``strict``), el
    trabajo falla (``runtime_partial_busy``: el instalador no sustituiría lo que queda);
    después de un fallo, queda anotado y se borrará en el siguiente intento (nunca se
    usa)."""
    if runtime.remove_tree(task.partial_path):
        return
    if strict:
        raise runtime.install_failure("runtime_partial_busy", path=str(task.partial_path))
    if ctx is not None:
        ctx.log("warning", f"No se pudo borrar la instalación a medias {task.partial_path}; "
                           "se borrará en el siguiente intento")


def _job_name(request: JobRequest) -> str:
    label = request.label
    return label if isinstance(label, str) and label.strip() else request.worker
