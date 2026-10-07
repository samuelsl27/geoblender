# SPDX-License-Identifier: GPL-3.0-or-later
"""Ejecutor en hilo de los trabajos cortos: :class:`InProcessExecutor` (spec 004;
RF-004-03, RF-004-09, RF-004-12, RF-004-13; plan 004 §5.1, §5.4.1 y §5.4.5).

Lo que se estima en ≤ 5 s y tiene función de dominio (``WorkerInfo.run``) corre dentro de
Blender, en un hilo *daemon*, con el mismo seguimiento, cancelación y registro que en un
proceso aparte (RF-004-03). Es el equivalente en hilo de ``workers/_bootstrap.py`` (pasos 7
y 8 del plan §5.4.3), y llama a la misma función ``run(ctx)`` que envuelve
``workers/<tipo>.py``, sin importar ``workers/`` ni el dominio (ARQ-07: la recibe del
registro de tipos de trabajo).

- Contexto: un ``WorkerContext`` con una cola de eventos (``QueueSink``) que vacía el
  lanzador al sondear, y el aviso del hilo (``threading.Event``) además del centinela
  ``cancel`` (RF-004-09).
- Eventos: ``start`` (pid de Blender, intérprete ``blender`` y versiones de Python, numpy y
  BLAS), los del cálculo y su final: ``result`` (con ``result.json``), ``cancelled`` o
  ``error``, igual que el arranque del proceso aparte.
- Código (los del plan §5.3.4, para que el lanzador decida el estado con la misma tabla):
  0, terminado; 2, :class:`~.worker_api.JobFailed` (o un ``JobError``) con su evento
  ``error``; 3, cancelación atendida; 1, excepción no prevista (también ``SystemExit``),
  con la traza solo en ``job.log`` (RF-004-12).
- ``job.log``: las líneas del arranque, del trabajo, del final y la traza de una excepción,
  con el prefijo :data:`LOG_PREFIX`. Lo que el cálculo imprima con ``print()`` no llega
  aquí: en un hilo no se puede separar de la salida de Blender.

Un hilo no se puede matar (plan §5.4.5): si no atiende la cancelación, al vencer su plazo
de gracia (o al cerrar el lanzador) el lanzador lo **abandona** (:meth:`abandon`): el
trabajo queda en su estado final, y lo que el hilo envíe o escriba en ``job.log`` desde
entonces se descarta, así como su resultado (no escribe ``result.json``). Como es
*daemon*, nunca retiene el cierre de Blender (RF-004-13).
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path

from .messages import JobError
from .paths import JobDir
from .protocol import JobEvent, JobRequest, JsonValue
from .records import LOGGER
from .worker_api import (
    JobCancelled,
    JobFailed,
    QueueSink,
    WorkerContext,
    interpreter_info,
)

type WorkerRun = Callable[[WorkerContext], Mapping[str, JsonValue]]
"""``run(ctx) -> resumen JSON``: la función de dominio de un tipo de trabajo."""

# Los códigos del arranque del proceso aparte (plan §5.3.4; ``workers/_bootstrap.py``).
EXIT_OK = 0
EXIT_CRASHED = 1
EXIT_FAILED = 2
EXIT_CANCELLED = 3

INTERPRETER_KIND = "blender"
"""El intérprete de un trabajo en hilo: el de Blender."""
THREAD_NAME_PREFIX = "geoblender-inprocess-"
"""Comienzo del nombre del hilo de un trabajo (le sigue su ``job_uid``)."""
LOG_PREFIX = "Geoblender (hilo):"
"""Comienzo de las líneas que el ejecutor en hilo deja en ``job.log``."""


class _ThreadSink(QueueSink):
    """La cola de eventos del hilo, que deja de admitirlos cuando el lanzador lo abandona
    (se comprueban igual, como en el canal)."""

    def __init__(self, abandoned: threading.Event) -> None:
        super().__init__()
        self._abandoned = abandoned

    def send(self, event: JobEvent) -> None:
        if self._abandoned.is_set():
            return
        super().send(event)


class InProcessExecutor:
    """Ejecuta ``run(ctx)`` del trabajo ``request`` (carpeta ``folder``, la de su
    ``job_uid``: :class:`ValueError` si no) en un hilo *daemon* de Blender.

    ``clock`` es el reloj monótono del lanzador: con él se apunta cuándo acabó
    (:attr:`ended_at`). Lo usa el lanzador desde su hilo: :meth:`start`, :meth:`drain`,
    :meth:`cancel`, :meth:`abandon`, :meth:`wait` y las propiedades.
    """

    def __init__(
        self,
        request: JobRequest,
        folder: JobDir,
        run: WorkerRun,
        *,
        clock: Callable[[], float] = time.monotonic,
        paths: Mapping[str, Path] | None = None,
    ) -> None:
        """``paths``: las rutas del trabajo fuera de su carpeta (``WorkerContext.paths``)."""
        if not callable(run):
            raise TypeError(
                f"la función del trabajo {request.job_uid} no se puede llamar "
                f"({type(run).__name__})"
            )
        self._request = request
        self._folder = folder
        self._run = run
        self._clock = clock
        self._cancel = threading.Event()
        self._abandoned = threading.Event()
        self._done = threading.Event()
        self._log_lock = threading.Lock()
        self._sink = _ThreadSink(self._abandoned)
        self._ctx = WorkerContext(request, folder, self._sink, cancel_event=self._cancel,
                                  paths=paths)
        self.exit_code: int | None = None
        """El código del final (los del plan §5.3.4); ``None`` mientras no acaba."""
        self.ended_at: float | None = None
        """Cuándo acabó, con ``clock``."""
        self.ended_wall: dt.datetime | None = None
        """Cuándo acabó, en UTC."""
        self._thread = threading.Thread(
            target=self._main, name=THREAD_NAME_PREFIX + request.job_uid, daemon=True
        )

    @property
    def name(self) -> str:
        """El nombre del hilo: :data:`THREAD_NAME_PREFIX` y el ``job_uid``."""
        return self._thread.name

    @property
    def finished(self) -> bool:
        """Si el trabajo acabó: todo lo que envió está ya en la cola."""
        return self._done.is_set()

    @property
    def alive(self) -> bool:
        """Si el hilo sigue vivo (puede seguir después de abandonarlo)."""
        return self._thread.is_alive()

    @property
    def abandoned(self) -> bool:
        """Si el lanzador lo abandonó (:meth:`abandon`)."""
        return self._abandoned.is_set()

    def start(self) -> None:
        """Arranca el hilo."""
        self._thread.start()

    def drain(self) -> list[JobEvent]:
        """Los eventos que envió el trabajo desde la última vez, en orden, sin esperar."""
        return self._sink.drain()

    def cancel(self) -> None:
        """Pide parar el trabajo: el contexto lo ve en su siguiente ``progress`` o
        ``check_cancelled`` (RF-004-09). El centinela ``cancel`` lo crea el lanzador."""
        self._cancel.set()

    def wait(self, timeout_s: float | None = None) -> bool:
        """Espera, como mucho ``timeout_s`` s, a que el trabajo acabe; dice si acabó."""
        return self._done.wait(timeout_s)

    def abandon(self) -> None:
        """El lanzador deja de seguir el trabajo (no atendió la cancelación, o se cierra el
        lanzador): desde ahora, lo que envíe o escriba en ``job.log`` se descarta, y su
        resultado también. El hilo sigue hasta que acabe solo."""
        with self._log_lock:
            self._abandoned.set()
        self._cancel.set()

    # --- El hilo ------------------------------------------------------------------------

    def _main(self) -> None:
        code = EXIT_CRASHED
        try:
            code = self._execute()
        except (Exception, SystemExit):
            # También ``sys.exit`` del cálculo: en un hilo no sale de Blender, y con su
            # propio código se haría pasar por otro final (RF-004-12).
            self._note("excepción no capturada en el trabajo:\n" + traceback.format_exc()
                       .rstrip("\n"))
            code = EXIT_CRASHED
        finally:
            self.exit_code = code
            self.ended_at = self._clock()
            self.ended_wall = dt.datetime.now(dt.UTC)
            self._note(f"el trabajo termina con el código {code}")
            self._done.set()

    def _execute(self) -> int:
        """Los pasos 7 y 8 del arranque (plan §5.4.3), en el hilo: evento ``start``,
        ``run(ctx)`` y su final. Devuelve el código; una excepción no prevista sale de
        aquí."""
        request = self._request
        ctx = self._ctx
        info = interpreter_info(INTERPRETER_KIND)
        self._note(
            f"arranque del trabajo en un hilo de Blender: pid {info['pid']}, intérprete "
            f"{INTERPRETER_KIND}, Python {info['python']}, numpy "
            f"{info['numpy'] or 'no disponible'}, BLAS {info['blas'] or 'no disponible'}"
        )
        ctx.emit(JobEvent.start(info))
        self._note(f"trabajo {request.job_uid}: tipo {request.worker}, «{request.label}»")
        try:
            summary = self._run(ctx)
        except JobCancelled as exc:
            ctx.emit(JobEvent.cancelled(str(exc)))
            self._note(f"cancelado: {exc}")
            return EXIT_CANCELLED
        except (JobFailed, JobError) as exc:
            failed = exc if isinstance(exc, JobFailed) else JobFailed.from_error(exc)
            ctx.emit(JobEvent.error(failed.code, msgid=failed.msgid, msg=failed.text,
                                    values=failed.values))
            self._note(f"fallido ({failed.code}): {failed.text}")
            return EXIT_FAILED
        if self._abandoned.is_set():
            return EXIT_OK  # el trabajo ya tiene su final: el resultado se descarta
        ctx.finish(summary)
        return EXIT_OK

    def _note(self, text: str) -> None:
        """Una línea (o varias) en ``job.log``, salvo si el lanzador ya lo abandonó."""
        lines = "".join(f"{LOG_PREFIX} {line}\n" if index == 0 else f"{line}\n"
                        for index, line in enumerate(text.split("\n")))
        with self._log_lock:
            if self._abandoned.is_set():
                return
            try:
                with self._folder.log_file.open("a", encoding="utf-8",
                                                errors="replace") as log:
                    log.write(lines)
            except OSError:
                LOGGER.exception("No se pudo escribir el registro del trabajo %s",
                                 self._request.job_uid)
