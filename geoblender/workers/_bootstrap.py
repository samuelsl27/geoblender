# SPDX-License-Identifier: GPL-3.0-or-later
"""Arranque de un worker en un proceso aparte (spec 004; RF-004-01, RF-004-12, RF-004-13,
RF-004-15; plan 004 §5.3.3, §5.3.4 y §5.4.3).

El lanzador lo ejecuta con el Python de Blender, con la carpeta del trabajo como carpeta de
trabajo::

    python.exe -I -B -u <paquete>/workers/_bootstrap.py --package-dir <paquete>
        --job-dir <carpeta del trabajo> --kind blender

con la entrada estándar en una tubería (la vigilancia del padre), la salida estándar en otra
(el canal de eventos) y la salida de error en ``job.log``. Es un guion autónomo: hasta cargar
el paquete (paso 5) solo usa la biblioteca estándar, y es el único fichero de la extensión que
importa ``geoblender`` de forma absoluta (excepción de ARQ-09, plan 001). Pasos:

0. ``sys.dont_write_bytecode = True`` antes de cualquier otro import: defensa además de
   ``-B``, porque ``-I`` implica ``-E`` y no se lee ``PYTHONDONTWRITEBYTECODE`` (plan §2.1);
   ningún ``__pycache__`` aparece junto al paquete.
1. Lee los argumentos.
2. Canal: duplica la salida estándar original para los eventos y manda el descriptor 1 y
   ``sys.stdout`` a la salida de error: lo que impriman ``print()`` o una librería en C va a
   ``job.log`` (en UTF-8) y no ensucia el canal.
3. Vigilancia del padre: un hilo *daemon* lee la entrada estándar hasta su fin y entonces
   termina el proceso con el código 4: si Blender muere, Windows cierra la tubería
   (RF-004-13).
5. Carga el paquete por ruta (``importlib``) con el nombre ``geoblender``, sin añadir nada a
   ``sys.path`` (no expone las demás extensiones del usuario).
7. Evento ``start`` con el pid, el intérprete y las versiones de Python, numpy y BLAS
   (RF-004-15).
8. Lee la petición (``request.json``), importa ``geoblender.workers.<tipo>`` y llama a su
   ``main(ctx)`` con un ``WorkerContext`` que escribe en el canal.

Códigos de salida (plan §5.3.4): 0, terminado, con ``result.json`` y el evento ``result``;
2, ``JobFailed`` (o un ``JobError``) con su evento ``error``; 3, cancelación atendida, con el
evento ``cancelled``; 4, padre perdido; 5, comprobación de arranque fallida (argumentos,
paquete, petición ilegible o tipo de trabajo que no existe; con su evento ``error`` si el
canal ya funciona); 1, excepción no capturada, con la traza solo en ``job.log`` (también
``SystemExit``: un ``sys.exit`` del cálculo o de una librería no puede hacerse pasar por
otro de estos códigos; RF-004-12). Una caída nativa o un ``os._exit`` dan su propio
código.

Este arranque admite el intérprete ``blender``; ``--site`` y el entorno ``compute`` (pasos 4 y
6) llegan con el motor de cálculo.
"""

import sys

sys.dont_write_bytecode = True  # Paso 0: antes de cualquier otro import.

import argparse  # noqa: E402
import importlib  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
from collections.abc import Callable, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from types import ModuleType  # noqa: E402
from typing import IO, Any, NoReturn  # noqa: E402

PACKAGE_NAME = "geoblender"
WORKERS_PACKAGE = f"{PACKAGE_NAME}.workers"
KINDS: tuple[str, ...] = ("blender",)
"""Intérpretes que admite el arranque (``--kind``)."""

EXIT_OK = 0
EXIT_CRASHED = 1
EXIT_FAILED = 2
EXIT_CANCELLED = 3
EXIT_PARENT_LOST = 4
EXIT_STARTUP = 5

LOG_PREFIX = "Geoblender:"
"""Comienzo de las líneas que el arranque deja en ``job.log``."""
_WATCH_BYTES = 4096


class StartupError(Exception):
    """Una comprobación de arranque que falla antes de poder usar el paquete: el motivo va a
    ``job.log`` y el worker termina con :data:`EXIT_STARTUP`."""


class _Parser(argparse.ArgumentParser):
    """Los argumentos que no valen son :class:`StartupError` (``argparse`` saldría con 2,
    que es el código de ``JobFailed``)."""

    def error(self, message: str) -> NoReturn:
        raise StartupError(f"argumentos del arranque que no valen: {message}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Paso 1: ``--package-dir``, ``--job-dir`` y ``--kind`` (:data:`KINDS`)."""
    parser = _Parser(prog="_bootstrap.py", add_help=False, allow_abbrev=False)
    parser.add_argument("--package-dir", required=True)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--kind", required=True, choices=KINDS)
    return parser.parse_args(list(argv))


def open_channel() -> IO[str]:
    """Paso 2: el canal de eventos es una copia del descriptor 1 original (la tubería del
    lanzador); el descriptor 1 y ``sys.stdout`` pasan a ser la salida de error (``job.log``),
    en UTF-8."""
    try:
        channel = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n", buffering=1)
        os.dup2(2, 1)
    except OSError as exc:
        raise StartupError(f"no se puede abrir el canal de eventos: {exc}") from None
    if sys.__stdout__ is not None:
        _utf8(sys.__stdout__)
    sys.stdout = sys.stderr
    return channel


def watch_parent() -> threading.Thread:
    """Paso 3: hilo *daemon* que termina el proceso con :data:`EXIT_PARENT_LOST` cuando se
    acaba la entrada estándar (el padre la cerró o murió)."""
    thread = threading.Thread(
        target=_wait_for_parent, name="geoblender-parent-watch", daemon=True
    )
    thread.start()
    return thread


def _wait_for_parent() -> None:
    # Lee el descriptor 0 directamente, sin ``sys.stdin``: su cerrojo, retenido por un hilo
    # daemon, haría fallar el cierre del intérprete.
    try:
        while os.read(0, _WATCH_BYTES):
            pass
    except OSError as exc:
        note(f"no se vigila al proceso padre: su entrada estándar no se puede leer ({exc})")
        return
    note(f"el proceso padre ya no está (fin de la entrada estándar): el worker termina con "
         f"el código {EXIT_PARENT_LOST}")
    os._exit(EXIT_PARENT_LOST)


def load_package(package_dir: Path) -> ModuleType:
    """Paso 5: carga ``<package_dir>/__init__.py`` como el paquete ``geoblender``, por ruta y
    sin tocar ``sys.path``."""
    init = package_dir / "__init__.py"
    if not init.is_file():
        raise StartupError(f"no está el paquete de Geoblender en {package_dir} (falta "
                           "__init__.py)")
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME, init, submodule_search_locations=[str(package_dir)]
    )
    if spec is None or spec.loader is None:
        raise StartupError(f"no se puede cargar {init} como el paquete {PACKAGE_NAME}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(PACKAGE_NAME, None)
        raise
    return module


def run_job(job_dir: str, kind: str, channel: IO[str]) -> int:
    """Pasos 7 y 8, con el paquete ya cargado: evento ``start``, petición, tipo de trabajo y
    ``main(ctx)``. Devuelve el código de salida (plan §5.3.4); una excepción no prevista
    sale de aquí (código 1)."""
    from geoblender.jobs import protocol, worker_api
    from geoblender.jobs.messages import JobError

    sink = worker_api.StreamSink(channel)
    info = worker_api.interpreter_info(kind)
    note(
        f"arranque del worker: pid {info['pid']}, intérprete {kind}, Python {info['python']}, "
        f"numpy {info['numpy'] or 'no disponible'}, BLAS {info['blas'] or 'no disponible'}"
    )
    sink.send(protocol.JobEvent.start(info))
    try:
        folder = _job_folder(job_dir)
        request = protocol.read_request(folder)
        main = _worker_main(request.worker)
    except JobError as exc:
        note(f"comprobación de arranque fallida ({exc.code}): {exc.text}")
        sink.send(protocol.JobEvent.error(exc.code, msgid=exc.msgid, msg=exc.text,
                                          values=exc.values))
        return EXIT_STARTUP
    note(f"trabajo {request.job_uid}: tipo {request.worker}, «{request.label}»")
    ctx = worker_api.WorkerContext(request, folder, sink)
    try:
        summary = main(ctx)
    except worker_api.JobCancelled as exc:
        ctx.emit(protocol.JobEvent.cancelled(str(exc)))
        note(f"cancelado: {exc}")
        return EXIT_CANCELLED
    except (worker_api.JobFailed, JobError) as exc:
        failed = (exc if isinstance(exc, worker_api.JobFailed)
                  else worker_api.JobFailed.from_error(exc))
        ctx.emit(protocol.JobEvent.error(failed.code, msgid=failed.msgid, msg=failed.text,
                                         values=failed.values))
        note(f"fallido ({failed.code}): {failed.text}")
        return EXIT_FAILED
    ctx.finish(summary)
    return EXIT_OK


def _job_folder(job_dir: str) -> Any:
    """La carpeta del trabajo (``JobDir``); una que no es la de un trabajo es
    ``request_invalid``."""
    from geoblender.jobs.messages import JobError
    from geoblender.jobs.paths import JobDir

    path = Path(job_dir)
    try:
        return JobDir(path)
    except ValueError as exc:
        raise JobError("request_invalid", job=path.name or job_dir, detail=str(exc)) from None


def _worker_main(name: str) -> Callable[[Any], Any]:
    """``main`` de ``geoblender.workers.<name>``; ``worker_unknown`` si el módulo no existe o
    no la tiene. Un módulo que existe pero falla al importarse es un fallo del worker."""
    from geoblender.jobs.messages import JobError

    module_name = f"{WORKERS_PACKAGE}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise JobError("worker_unknown", worker=name) from None
    main = getattr(module, "main", None)
    if not callable(main):
        raise JobError("worker_unknown", worker=name)
    return main


def note(text: str) -> None:
    """Una línea del arranque en ``job.log`` (la salida de error)."""
    stream = sys.stderr
    if stream is None:
        return
    try:
        print(f"{LOG_PREFIX} {text}", file=stream, flush=True)
    except (OSError, ValueError):
        pass


def _utf8(stream: Any) -> None:
    """Escribe ``stream`` en UTF-8 (sin ``-X utf8``, Windows usaría la página de códigos)."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    """Los pasos del arranque; devuelve el código de salida."""
    _utf8(sys.stderr)
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        channel = open_channel()
    except StartupError as exc:
        note(f"{exc}; el worker termina con el código {EXIT_STARTUP}")
        return EXIT_STARTUP
    watch_parent()
    try:
        load_package(Path(args.package_dir))
        code = run_job(args.job_dir, args.kind, channel)
    except StartupError as exc:
        note(str(exc))
        code = EXIT_STARTUP
    except (Exception, SystemExit):
        # También ``sys.exit`` del cálculo o de una librería: con su propio código se haría
        # pasar por una cancelación (3), por la pérdida del padre (4)… (RF-004-12).
        note("excepción no capturada en el worker:")
        traceback.print_exc()
        code = EXIT_CRASHED
    try:
        channel.close()
    except OSError:
        pass
    note(f"el worker termina con el código {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
