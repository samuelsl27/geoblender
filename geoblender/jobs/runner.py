# SPDX-License-Identifier: GPL-3.0-or-later
"""Lanzador de los trabajos en segundo plano: :class:`JobRunner` (spec 004; RF-004-01,
RF-004-03 a RF-004-05, RF-004-09 a RF-004-13, RF-004-15 a RF-004-17; plan 004 §5.3.1,
§5.3.3, §5.3.4, §5.4.1, §5.4.2, §5.4.5 y §5.4.6).

Cada trabajo corre en proceso aparte o en un hilo de Blender según su tipo
(``policy.choose_executor``, RF-004-03): en hilo solo lo estimado en ≤ 5 s con función
``run``, con ``inprocess.InProcessExecutor``; el resto, en proceso aparte. Los dos tienen el
mismo seguimiento, cancelación y registro (al final de este texto, lo propio del hilo).

Ciclo de vida de un trabajo en proceso aparte:

- :meth:`JobRunner.prepare`: completa la petición con lo que declara su tipo de trabajo
  (entorno y tiempo máximo), la valida (``protocol.validate_request``, con la raíz del
  proyecto prohibida) y, solo si vale, crea su carpeta con ``request.json`` y ``state.json``
  «En cola». El módulo dueño escribe después sus entradas en ``in/``.
- :meth:`JobRunner.submit`: pone el trabajo en la cola (FIFO) y vuelve sin esperarlo, con
  un :class:`JobHandle`; si hay hueco (``max_subprocess`` workers a la vez, 2 por defecto;
  RF-004-04), lo lanza al momento; si no, queda «En cola» y arranca, por orden de llegada,
  en cuanto otro acaba::

      <python de Blender> -I -B -u <paquete>/workers/_bootstrap.py --package-dir <paquete>
          --job-dir <carpeta> --kind blender

  (``interpreter.build_command`` con el intérprete de ``interpreter.resolve_interpreter``:
  en el entorno ``compute``, el intérprete externo si está configurado o, si no, el Python
  de Blender con ``-I -S`` y el motor de cálculo; sin motor listo, el trabajo queda
  «Fallido» ``runtime_missing`` sin proceso; RF-004-25, RF-004-26), con la carpeta del
  trabajo como carpeta de trabajo, la entrada estándar en una tubería
  que el lanzador mantiene abierta (si Blender muere, el worker lo ve y termina), la salida
  estándar como canal de eventos y la de error en ``job.log``, y el entorno de Blender sin
  variables ``PYTHON*`` ni ``PIP_*`` y con los hilos de BLAS repartidos entre los workers
  que pueden correr a la vez (``interpreter.child_env``). Las rutas absolutas viajan en
  la línea de órdenes, nunca en la petición. Justo después de lanzarlo, el worker entra en
  su propio *Job Object* (``winjob.JobObject``, ``KILL_ON_JOB_CLOSE``): los procesos que
  lance entran con él, y terminarlo los termina a todos. Si no se puede asignar, el worker
  se termina al momento y el trabajo queda «Fallido» (``interpreter_failed``).
- Un hilo lector *daemon* por proceso lee el canal (``protocol.EventDecoder``), añade a
  ``events.jsonl`` cada evento, en orden de llegada, y cada línea que no lo es como nota
  (``{"note": "invalid_line", …}``; el trabajo sigue, spec §8), y deja los eventos en una
  cola para el sondeo.
- :meth:`JobRunner.poll`: no bloquea (lo llama el temporizador de Blender). Vacía la cola de
  cada trabajo en curso y, cuando su proceso terminó y el canal se cerró, lo finaliza: estado
  según el código de salida (plan §5.3.4), comprobación de cada resultado declarado (existe
  dentro de ``out/`` y casa con su huella sha256: si no, «Fallido» con ``output_missing`` u
  ``output_hash_mismatch``, RF-004-05), ``state.json`` atómico con el registro completo
  (RF-004-15), cierre de su *Job Object* (termina lo que el worker dejara vivo) y, por
  último, ``on_finish`` con su :class:`JobResult`. Después arranca de la cola lo que quepa.
- :meth:`JobRunner.snapshots` y :meth:`JobRunner.active_count`: cómo está cada trabajo
  (:class:`JobSnapshot`: nombre, estado, avance, último mensaje, duración, intérprete y
  error) y cuántos están en cola o en curso; es lo que muestra la interfaz (RF-004-06,
  RF-004-07). :meth:`JobRunner.stored_snapshots` añade para la lista de trabajos los que
  ya están en las carpetas de trabajos sin ser de este lanzador (de otra sesión o de antes
  de desactivar Geoblender), tras dejar «Interrumpido» los que constaban activos
  (RF-004-08, RF-004-13).
- :meth:`JobRunner.cancel` (o :meth:`JobHandle.cancel`): uno en cola queda «Cancelado» sin
  arrancar; a uno en curso se le crea el centinela ``cancel`` y el worker para en su
  siguiente punto de control (RF-004-09). Si sigue vivo al vencer su plazo de gracia
  (``grace_s`` de la petición), :meth:`JobRunner.poll` termina su *Job Object* (el worker y
  sus hijos) y la cancelación consta como forzada (RF-004-10). Pedida la cancelación, el
  trabajo acaba «Cancelado» y lo que entregue el worker se descarta. Cancelar dos veces, o
  un trabajo ya terminado, no hace nada (``False``).
- Tiempo máximo (RF-004-11): el ``timeout_s`` de la petición (:meth:`JobRunner.prepare`
  pone el de su tipo de trabajo, 3600 s si no declara otro), contado desde que arranca su
  proceso. Si :meth:`JobRunner.poll` lo ve en marcha pasado ese tiempo y nadie pidió
  pararlo, le pide parar como en una cancelación (motivo ``timeout``, con el mismo plazo de
  gracia) y el trabajo acaba «Tiempo agotado» (``job_timeout``, con el tiempo máximo en el
  mensaje), forzado o no.
- Fallos (RF-004-12): el trabajo queda «Fallido» con el código del plan §5.3.4 y su
  mensaje en español, nunca con una traza (la del worker está en ``job.log``): el error
  que informa el worker (salida 2 o 5, con el texto de su evento ``error`` en una línea),
  ``worker_crashed`` con cualquier otra salida, ``protocol_no_result`` si sale con 0 sin
  resultado, y sin proceso si el intérprete no arranca o si la petición de una carpeta ya
  preparada deja de valer antes de lanzarla (``worker_unknown``…). Nada de eso se propaga
  al proceso de Blender.
- Cierre (RF-004-13): :meth:`JobRunner.shutdown`, al cerrarse Blender o desactivarse
  Geoblender, deja «Interrumpido» lo que hay en la cola, pide parar (motivo ``shutdown``)
  a los trabajos en curso, espera hasta 1 s y termina el *Job Object* de los que siguen
  vivos; todo en ≤ 3 s, y después no admite trabajos nuevos. Si el proceso de Blender
  muere de golpe, Windows cierra el *handle* de cada *Job Object* y termina el worker con
  todo lo que lanzó; la vigilancia del padre del arranque (fin de la entrada estándar,
  salida 4) es la segunda capa. El registro de un trabajo así se cierra «Interrumpido» al
  reabrir el proyecto (``records.mark_interrupted``).
- Incorporación (RF-004-16): cuando el módulo dueño confirma que incorporó los resultados,
  :meth:`JobRunner.mark_ingested` lo anota en ``state.json`` y borra las entradas y los
  resultados de la carpeta (``cleanup.release``); queda el registro.
- Limpieza (RF-004-17): :meth:`JobRunner.purge` borra las carpetas de los trabajos
  terminados (``cleanup.purge``) sin tocar nunca los que lleva activos, y los borrados salen
  de su lista.

En hilo (``executor = "inprocess"``): la función ``run`` del tipo de trabajo corre en un
hilo *daemon* (``inprocess.InProcessExecutor``), sin proceso propio (``pid`` vacío), con
los mismos eventos, que :meth:`JobRunner.poll` recoge de su cola y añade a
``events.jsonl``, y el mismo estado final según su código (el de la tabla del plan
§5.3.4). Hay ``max_inprocess`` huecos de hilo (1 por defecto) aparte de los de proceso;
la cola es por orden de llegada dentro de cada ejecutor. Un hilo no se puede matar: si
sigue en marcha al vencer su plazo de gracia, el trabajo queda «Cancelado» (o «Tiempo
agotado») forzado y el hilo se **abandona**: lo que entregue después se descarta, y su
hueco se libera cuando acaba. :meth:`JobRunner.shutdown` lo espera como a un proceso
(hasta 1 s) y después lo abandona: queda «Interrumpido» y no retiene el cierre.

Los hilos de este módulo son *daemon*: nunca retienen el cierre de Blender. Solo el lanzador
escribe ``state.json``, ``events.jsonl`` y, al final, sus avisos en ``job.log``.

:meth:`JobRunner.reconfigure` cambia el máximo de workers en proceso aparte, el intérprete
externo y la raíz de los trabajos sin parar el lanzador.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import enum
import hashlib
import json
import math
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from ..core.timeutil import format_utc
from . import catalog, cleanup, interpreter, policy, winjob
from .inprocess import InProcessExecutor
from .messages import JobError, one_line
from .paths import LOG_FILE, JobDir, job_dir
from .protocol import (
    EventDecoder,
    InvalidLine,
    JobEvent,
    JobRequest,
    JsonValue,
    OutputRef,
    encode_event,
    read_request,
    validate_request,
    write_request,
)
from .records import (
    ACTIVE_STATES,
    INTERPRETER_KINDS,
    LOG_PREFIX,
    LOGGER,
    NOTE_KEY,
    CancelInfo,
    ErrorInfo,
    InterpreterInfo,
    JobRecord,
    last_progress,
    mark_interrupted,
    read_record,
    scan,
    write_record,
)

WORKER_FLAGS: tuple[str, ...] = interpreter.BLENDER_FLAGS
"""Banderas del Python de Blender para un worker del entorno ``blender`` (plan §5.3.3;
``interpreter.BLENDER_FLAGS``)."""
BOOTSTRAP_PARTS: tuple[str, ...] = interpreter.BOOTSTRAP_PARTS
"""El arranque de los workers dentro del paquete (se lanza por ruta: ``jobs`` no importa
``workers``)."""
INTERPRETER_KIND = interpreter.KIND_BLENDER
"""El intérprete de los trabajos en hilo (el de Blender)."""


class _Keep(enum.Enum):
    KEEP = "keep"


KEEP = _Keep.KEEP
"""Valor por defecto de ``external_python`` en :meth:`JobRunner.reconfigure`: no cambiarlo
(``None`` lo quita)."""
REJECTED_EXECUTOR = "subprocess"
"""El ejecutor que consta en el registro de un trabajo rechazado al lanzarlo sin haber
pasado por :meth:`JobRunner.prepare` (sin tipo de trabajo no se puede elegir otro)."""

# Códigos de salida del worker (plan §5.3.4; los mismos que ``workers/_bootstrap.py``).
EXIT_OK = 0
EXIT_CRASHED = 1
EXIT_FAILED = 2
EXIT_CANCELLED = 3
EXIT_PARENT_LOST = 4
EXIT_STARTUP = 5
EXIT_TERMINATED = 137
"""El código de salida con que el lanzador termina el *Job Object* de un worker que sigue
vivo al vencer su plazo de gracia (128 + 9, el de un proceso matado en POSIX): distinto de
los del arranque y del 1 de ``Popen.kill``, así ``state.json`` dice quién lo terminó."""

DEFAULT_MAX_SUBPROCESS = 2
"""Workers en proceso aparte a la vez (D-2; plan §5.4.2)."""
DEFAULT_MAX_INPROCESS = 1
"""Trabajos en hilo a la vez (D-2; plan §5.4.2), contando los hilos abandonados que siguen
vivos."""
EXECUTOR_SUBPROCESS = "subprocess"
EXECUTOR_INPROCESS = "inprocess"
KILL_WAIT_S = 5.0
"""Lo que se espera a un worker terminado a la fuerza antes de seguir sin él."""
SHUTDOWN_TIMEOUT_S = 3.0
"""Lo que tarda como mucho :meth:`JobRunner.shutdown` por defecto (plan §5.4.5)."""
SHUTDOWN_STOP_WAIT_S = 1.0
"""Lo que :meth:`JobRunner.shutdown` espera a que los workers atiendan la petición de parar
antes de terminar sus *Job Objects* (plan §5.4.5)."""

CREATION_FLAGS = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                  | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
"""Sin consola emergente al lanzar ``python.exe`` desde la interfaz y con prioridad por
debajo de la normal: la interfaz conserva la CPU (plan §5.3.3 y §6)."""

READ_BYTES = 1 << 16
"""Lo que pide el hilo lector en cada lectura del canal."""
CHANNEL_DRAIN_S = 1.0
"""Lo que se espera a que se cierre el canal después de que termine el proceso (un nieto
puede retenerlo); pasado ese plazo, el trabajo se finaliza con lo recibido."""
MAX_LOGGED_INVALID = 50
"""Líneas del canal que no son eventos que se repiten como aviso en ``job.log`` (en
``events.jsonl`` están todas)."""
_HASH_BLOCK = 1 << 20

_STATE_TEXT: Mapping[str, str] = {
    "queued": "En cola", "running": "En curso", "succeeded": "Terminado",
    "failed": "Fallido", "cancelled": "Cancelado", "timed_out": "Tiempo agotado",
    "interrupted": "Interrumpido",
}
MARKED_AT_LIST = "al abrir la lista de trabajos"
"""Cuándo se marca «Interrumpido» lo que :meth:`JobRunner.stored_snapshots` encuentra en
cola o en curso sin estar en el lanzador (se dice en su ``job.log``)."""

_REASON_TEXT: Mapping[str, str] = {
    "user": "a petición del usuario", "timeout": "por su tiempo máximo",
    "shutdown": "al cerrarse Geoblender",
}


@dataclass(frozen=True, slots=True)
class JobResult:
    """El final de un trabajo (plan §5.3.1): su estado final, los resultados verificados
    (vacío si no terminó bien), el resumen del worker, el código y el texto en español del
    error (``None`` si terminó bien), la duración en s (``None`` si no llegó a arrancar) y
    su carpeta."""

    job_uid: str
    state: str
    outputs: tuple[OutputRef, ...]
    summary: Mapping[str, JsonValue]
    error_code: str | None
    error_text: str | None
    duration_s: float | None
    job_dir: JobDir


@dataclass(frozen=True, slots=True)
class JobUpdate:
    """Lo que cambió en un trabajo desde el sondeo anterior: su estado, su avance (0–1) y su
    último mensaje, los eventos recibidos en orden y, solo en el sondeo en que llega a un
    estado final, su :class:`JobResult`."""

    job_uid: str
    state: str
    frac: float
    message: str
    events: tuple[JobEvent, ...] = ()
    result: JobResult | None = None

    @property
    def finished(self) -> bool:
        """Si el trabajo llegó en este sondeo a su estado final."""
        return self.result is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class JobSnapshot:
    """Cómo está ahora un trabajo del lanzador (plan §5.3.1; :meth:`JobRunner.snapshots`):
    lo que muestran la barra de estado y la lista de trabajos (RF-004-06, RF-004-07). Es una
    foto: no cambia con el trabajo.

    ``name``: su nombre visible (``label`` de la petición). ``frac`` (0–1) y ``message``: su
    último avance y su último mensaje (al acabar mal, el texto de su error). ``duration_s``:
    en curso, lo que lleva desde que arrancó; al acabar, su duración; ``None`` si no llegó a
    arrancar. ``interpreter``: el que lo ejecuta (``None`` en la cola). ``error``: el del §8
    si no terminó bien. ``cancel_requested``: si se pidió pararlo (el usuario, su tiempo
    máximo o el cierre). ``log_file``: su ``job.log`` (puede no existir aún), el que abre la
    lista de trabajos (RF-004-08). ``ingested``: si el módulo dueño ya incorporó sus
    resultados (:meth:`JobRunner.mark_ingested`); la lista solo ofrece descartar los que
    no. ``folder``: su carpeta. ``stored``: si no es de este lanzador, sino un trabajo
    guardado en una carpeta de trabajos (de otra sesión de Blender o de antes de
    desactivar Geoblender, :meth:`JobRunner.stored_snapshots`): su foto sale de su
    ``state.json`` y este lanzador no lo puede cancelar."""

    job_uid: str
    name: str
    worker: str
    state: str
    executor: str
    frac: float
    message: str
    duration_s: float | None
    interpreter: InterpreterInfo | None
    error: ErrorInfo | None
    cancel_requested: bool
    log_file: Path | None = None
    ingested: bool = False
    folder: Path | None = None
    stored: bool = False

    @property
    def active(self) -> bool:
        """Si está en cola o en curso."""
        return self.state in ACTIVE_STATES


def stored_snapshot(record: JobRecord, folder: Path) -> JobSnapshot:
    """La foto de un trabajo guardado en la carpeta ``folder`` con el registro ``record``
    (su ``state.json``), que no es de este lanzador (RF-004-08): nombre, tipo, estado,
    ejecutor, duración, intérprete, error, cancelación e incorporación, de su registro; su
    último avance y su último mensaje, de ``events.jsonl`` (``records.last_progress``;
    completo si terminó bien; si no terminó bien, el mensaje es el texto de su error, como
    en los de la sesión); su ``job.log`` y su carpeta. No escribe nada."""
    folder = Path(folder)
    progress = last_progress(folder)
    frac, message = progress if progress is not None else (0.0, "")
    if record.state == "succeeded":
        frac = 1.0
    elif record.error is not None:
        message = record.error.text
    return JobSnapshot(
        job_uid=record.job_uid, name=record.label, worker=record.worker, state=record.state,
        executor=record.executor, frac=frac, message=message, duration_s=record.duration_s,
        interpreter=record.interpreter, error=record.error,
        cancel_requested=record.cancel is not None, log_file=folder / LOG_FILE,
        ingested=record.ingested_at is not None, folder=folder, stored=True,
    )


class JobHandle:
    """Lo que devuelve :meth:`JobRunner.submit`: el seguimiento de un trabajo. Sus datos
    cambian al sondear (:meth:`JobRunner.poll`)."""

    __slots__ = ("_job", "_runner")

    def __init__(self, job: _Job, runner: JobRunner) -> None:
        self._job = job
        self._runner = runner

    @property
    def job_uid(self) -> str:
        return self._job.folder.job_uid

    @property
    def job_dir(self) -> JobDir:
        return self._job.folder

    @property
    def state(self) -> str:
        """``queued``, ``running`` o el estado final."""
        return self._job.state

    @property
    def frac(self) -> float:
        """El avance, 0–1."""
        return self._job.frac

    @property
    def message(self) -> str:
        """El último mensaje del trabajo (avance o error), en español."""
        return self._job.message

    @property
    def pid(self) -> int | None:
        """El proceso del worker (``None`` si no llegó a arrancar o si corre en un hilo de
        Blender: no tiene proceso propio)."""
        return self._job.record.pid

    def result(self) -> JobResult | None:
        """El :class:`JobResult` si el trabajo ya llegó a su estado final; si no, ``None``."""
        return self._job.result

    def cancel(self) -> bool:
        """Pide parar el trabajo (:meth:`JobRunner.cancel`)."""
        return self._runner.cancel(self.job_uid)

    def __repr__(self) -> str:
        return f"JobHandle({self.job_uid}, {self.state})"


class JobRunner:
    """El lanzador de los trabajos (plan §5.3.1).

    ``jobs_root``: la raíz de trabajos (``paths.resolve_jobs_root``; se crea si falta).
    ``package_dir``: la carpeta del paquete ``geoblender`` que cargan los workers (la que
    tiene ``workers/_bootstrap.py``). ``blender_python``: el ``python.exe`` de Blender.
    ``runtime``: el motor de cálculo (``interpreter.ComputeRuntime``; ``None``, ninguno: los
    trabajos ``compute`` quedan «Fallido» ``runtime_missing``, RF-004-25).
    ``external_python``: el intérprete externo (ruta completa, si no :class:`ValueError`)
    que ejecuta los trabajos ``compute`` en lugar del motor (RF-004-26); ``None``, ninguno.
    ``max_subprocess`` y ``max_inprocess``: trabajos a la vez en proceso aparte (2) y en hilo
    (1); los demás esperan en la cola, por orden de llegada (RF-004-04; enteros ≥ 1, si no
    :class:`ValueError`). ``forbidden_roots``: rutas que ninguna petición puede contener (la
    raíz del proyecto, RF-004-02). ``clock``: reloj monótono de las duraciones y los
    plazos. :meth:`reconfigure` cambia después el máximo de procesos, el intérprete externo,
    la raíz y las rutas prohibidas.

    Sus métodos se llaman desde el hilo de Blender; los hilos lectores solo llenan colas y
    ``events.jsonl``, y los de los trabajos en hilo, su cola y su ``job.log``.
    """

    def __init__(
        self,
        *,
        jobs_root: Path,
        package_dir: Path,
        blender_python: Path,
        runtime: interpreter.ComputeRuntime | None = None,
        external_python: Path | None = None,
        max_subprocess: int = DEFAULT_MAX_SUBPROCESS,
        max_inprocess: int = DEFAULT_MAX_INPROCESS,
        forbidden_roots: Sequence[Path] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        _check_maximum(max_subprocess, "max_subprocess")
        _check_maximum(max_inprocess, "max_inprocess")
        external = _external_python(external_python)
        root = _absolute_root(jobs_root)
        package = Path(package_dir)
        bootstrap = package.joinpath(*BOOTSTRAP_PARTS)
        if not bootstrap.is_file():
            raise ValueError(
                f"«{package}» no es el paquete de Geoblender: falta "
                f"{'/'.join(BOOTSTRAP_PARTS)}"
            )
        self._jobs_root = root
        self._package_dir = package
        self._blender_python = Path(blender_python)
        self._runtime = runtime
        self._external_python = external
        self._forbidden_roots: tuple[Path, ...] = tuple(Path(p) for p in forbidden_roots)
        self._max_subprocess = max_subprocess
        self._max_inprocess = max_inprocess
        self._clock = clock
        self._lock = threading.RLock()
        self._jobs: dict[str, _Job] = {}
        self._queue: collections.deque[_Job] = collections.deque()
        self._running: dict[str, _Job] = {}
        self._abandoned: list[InProcessExecutor] = []
        """Hilos abandonados (su trabajo ya tiene su final) que ocupan su hueco hasta que
        acaban."""
        self._to_report: list[_Job] = []
        self._closed = False

    @property
    def jobs_root(self) -> Path:
        return self._jobs_root

    @property
    def forbidden_roots(self) -> tuple[Path, ...]:
        """Las rutas que ninguna petición puede contener (la raíz del proyecto abierto,
        RF-004-02)."""
        return self._forbidden_roots

    @property
    def runtime(self) -> interpreter.ComputeRuntime | None:
        """El motor de cálculo de los trabajos ``compute`` (``None``: ninguno)."""
        return self._runtime

    @property
    def external_python(self) -> Path | None:
        """El intérprete externo de los trabajos ``compute`` (RF-004-26; ``None``:
        ninguno)."""
        return self._external_python

    @property
    def max_subprocess(self) -> int:
        """Workers en proceso aparte a la vez (RF-004-04)."""
        return self._max_subprocess

    @property
    def max_inprocess(self) -> int:
        """Trabajos en hilo a la vez (RF-004-04), contando los hilos abandonados que siguen
        vivos."""
        return self._max_inprocess

    @property
    def closed(self) -> bool:
        """Si ya se cerró (:meth:`shutdown`): no admite trabajos nuevos."""
        return self._closed

    def reconfigure(
        self,
        *,
        max_subprocess: int | None = None,
        external_python: Path | None | _Keep = KEEP,
        jobs_root: Path | None = None,
        forbidden_roots: Iterable[Path] | None = None,
    ) -> None:
        """Cambia la configuración sin parar el lanzador (al cambiar las preferencias o el
        proyecto; RF-004-04, RF-004-18, RF-004-26). Lo que se deja en ``None`` no cambia,
        salvo ``external_python`` (que no cambia si se omite).

        - ``max_subprocess``: workers en proceso aparte a la vez. Si sube, arranca al
          momento de la cola, por orden de llegada, lo que ahora quepa; si baja, los que
          están en curso siguen hasta acabar y los de la cola esperan a que haya menos en
          curso que el nuevo máximo. Los hilos de BLAS de los workers que arranquen desde
          ahora se reparten con él (:func:`.interpreter.blas_threads_for`).
        - ``external_python``: el intérprete externo (ruta completa) de los trabajos
          ``compute`` que arranquen desde ahora; ``None`` lo quita (vuelven al motor de
          cálculo). Lo sondea antes quien lo configura (``interpreter.probe_external``).
        - ``jobs_root``: la raíz de los trabajos que se preparen desde ahora; los ya
          preparados siguen en su carpeta.
        - ``forbidden_roots``: las rutas que no pueden contener las peticiones que se
          preparen o se lancen desde ahora (la raíz del proyecto abierto; ninguna sin
          proyecto, RF-004-02); rutas completas.

        Un valor que no vale es :class:`ValueError` y no cambia nada, tampoco los demás de
        la misma llamada."""
        if max_subprocess is not None:
            _check_maximum(max_subprocess, "max_subprocess")
        external = (None if external_python is KEEP
                    else _external_python(external_python))
        root = None if jobs_root is None else _absolute_root(jobs_root)
        forbidden = None if forbidden_roots is None else _absolute_roots(forbidden_roots)
        with self._lock:
            if external_python is not KEEP:
                self._external_python = external
            if root is not None:
                self._jobs_root = root
            if forbidden is not None:
                self._forbidden_roots = forbidden
            if max_subprocess is not None:
                self._max_subprocess = max_subprocess
                self._start_queued()

    # --- Preparar y lanzar -------------------------------------------------------------

    def prepare(self, request: JobRequest) -> JobDir:
        """Crea la carpeta del trabajo de ``request`` con su ``request.json`` y su
        ``state.json`` «En cola», y la devuelve (RF-004-01). El entorno es el más exigente
        entre el de la petición y el que exige su tipo de trabajo
        (``policy.resolve_environment``); sin tiempo máximo, toma el de su tipo. Una
        petición que no vale
        (``worker_unknown``, ``request_invalid``, ``request_path_outside_job``…) es
        :class:`~.messages.JobError` y no se crea nada (RF-004-02)."""
        if not isinstance(request, JobRequest):
            raise TypeError(f"se esperaba un JobRequest, no {type(request).__name__}")
        info = self._worker_info(request)
        environment = policy.resolve_environment(info, request)
        timeout_s = info.default_timeout_s if request.timeout_s is None else request.timeout_s
        if (environment, timeout_s) != (request.environment, request.timeout_s):
            request = dataclasses.replace(request, environment=environment,
                                          timeout_s=timeout_s)
        validate_request(request, catalog=catalog.WORKERS,
                         forbidden_roots=self._forbidden_roots)
        executor = self._executor(info, request)
        folder = job_dir(self._jobs_root, request.job_uid).create()
        try:
            write_request(folder, request)
            write_record(folder, JobRecord.from_request(request, executor=executor))
        except BaseException:
            shutil.rmtree(folder.path, ignore_errors=True)
            raise
        return folder

    def submit(
        self,
        job: JobDir | JobRequest,
        *,
        on_finish: Callable[[JobResult], object] | None = None,
        paths: Mapping[str, Path] | None = None,
        site_override: Path | None = None,
    ) -> JobHandle:
        """Pone el trabajo en la cola y vuelve sin esperarlo (RNF-004-01); si hay hueco,
        lo lanza al momento, en proceso aparte o en un hilo según su tipo de trabajo
        (RF-004-03). ``job`` es una carpeta de :meth:`prepare` (con sus entradas ya
        escritas) o una petición, que se prepara antes (si no vale,
        :class:`~.messages.JobError` y no se crea nada). La petición de la carpeta se lee y
        se valida otra vez: si no se puede leer, :class:`~.messages.JobError`; si ya no vale
        (su tipo de trabajo dejó de existir, o se tocó su ``request.json``), el trabajo
        queda «Fallido» con su código (``worker_unknown``…) sin arrancar ningún proceso
        (RF-004-12, spec §8). Si el intérprete no se puede arrancar, el trabajo queda
        «Fallido» (``interpreter_not_found`` o ``interpreter_failed``). ``on_finish`` se
        llama una vez, desde :meth:`poll`, con su :class:`JobResult`; sus errores no se
        propagan. ``paths``: las rutas absolutas que el trabajo necesita fuera de su carpeta,
        por nombre (``ComputeEnvironment.install_paths``): no van en la petición sino en la
        línea de órdenes (``--path``; en hilo, en su contexto), y el worker las ve en
        ``WorkerContext.paths``; un nombre o una ruta que no valen
        (``interpreter.check_paths``) son :class:`ValueError` sin crear nada.
        ``site_override``: la carpeta ``site`` con la que arranca su intérprete
        (``interpreter.resolve_interpreter``; ruta completa, si no :class:`ValueError` sin
        crear nada): en el entorno ``compute``, el Python de Blender sobre esa carpeta aunque
        el motor no esté listo ni se use el intérprete externo (la verificación de un motor
        recién instalado en ``<lock_id>.partial/site``, plan §5.4.7). Con el lanzador ya
        cerrado (:meth:`shutdown`), :class:`RuntimeError` sin crear nada."""
        self._check_open()
        job_paths = interpreter.check_paths({} if paths is None else paths)
        override = _site_override(site_override)
        folder = self.prepare(job) if isinstance(job, JobRequest) else job
        if not isinstance(folder, JobDir):
            raise TypeError(f"se esperaba un JobDir o un JobRequest, no {type(job).__name__}")
        with self._lock:
            self._check_open()
            if folder.job_uid in self._jobs:
                raise ValueError(f"el trabajo {folder.job_uid} ya se lanzó")
            request = read_request(folder)
            try:
                info = self._worker_info(request)
                validate_request(request, catalog=catalog.WORKERS,
                                 forbidden_roots=self._forbidden_roots)
            except JobError as exc:
                return self._reject(folder, request, exc, on_finish)
            executor = self._executor(info, request)
            record = read_record(folder)
            fresh = record is None or record.state != "queued"
            if fresh:
                record = JobRecord.from_request(request, executor=executor)
            elif record.executor != executor:
                # Su tipo de trabajo cambió desde prepare: manda el de ahora.
                record = dataclasses.replace(record, executor=executor)
                fresh = True
            item = _Job(request, folder, record, on_finish)
            item.paths = job_paths
            item.site_override = override
            if executor == EXECUTOR_INPROCESS:
                item.run = info.run
            self._jobs[folder.job_uid] = item
            if fresh:
                self._save(item)
            self._queue.append(item)
            self._start_queued()
            return JobHandle(item, self)

    def cancel(self, job_uid: str) -> bool:
        """Pide parar el trabajo ``job_uid`` (RF-004-09) y dice si la petición tuvo efecto.

        En cola: queda «Cancelado» al momento, sin arrancar. En curso: se crea su centinela
        ``cancel`` (el worker para en su siguiente punto de control; en hilo, además, se
        activa su aviso) y la cancelación consta en ``state.json``; si al vencer su plazo de
        gracia sigue vivo, :meth:`poll` lo termina con sus hijos (RF-004-10) o, en hilo, lo
        abandona: queda «Cancelado» y lo que entregue se descarta. ``False``, sin cambiar
        nada, si ya se pidió, si ya terminó (aunque :meth:`poll` aún no lo haya finalizado) o
        si no es de este lanzador (spec §8: idempotente)."""
        with self._lock:
            item = self._jobs.get(job_uid)
            if item is None or item.record.cancel is not None:
                return False
            if item.state == "queued":
                self._queue.remove(item)
                item.record = dataclasses.replace(item.record, cancel=_cancel_info("user"))
                self._finish(item, state="cancelled", exit_code=None, duration_s=None,
                             error=_error("job_cancelled", job=item.name, forced=False))
                return True
            if item.state != "running" or not item.alive():
                return False
            self._request_cancel(item, "user")
            return True

    def shutdown(self, *, timeout_s: float = SHUTDOWN_TIMEOUT_S) -> None:
        """Cierra el lanzador al cerrarse Blender o desactivarse Geoblender (RF-004-13) en
        ≤ ``timeout_s`` s (plan §5.4.5):

        - los trabajos de la cola quedan «Interrumpido» sin arrancar;
        - a los que están en curso se les pide parar (centinela ``cancel``, motivo
          ``shutdown``), se espera hasta :data:`SHUTDOWN_STOP_WAIT_S` a que paren y se
          termina el *Job Object* de los que siguen vivos (el worker y lo que lanzó; la
          cancelación consta forzada); un trabajo en hilo que sigue en marcha se abandona
          (no se puede terminar ni se espera más: es *daemon* y no retiene el cierre);
        - todos quedan «Interrumpido» (``job_interrupted``) en su ``state.json``, con su
          entrada estándar y su *Job Object* cerrados.

        Un trabajo cuyo proceso ya había terminado solo acaba con su propio estado, y uno
        al que ya se había pedido parar (el usuario o su tiempo máximo) acaba «Cancelado» o
        «Tiempo agotado». Los finales se cuentan en el siguiente :meth:`poll`, que llama a
        sus ``on_finish``: aquí no se llama a ninguno. Después, :meth:`submit` no admite
        trabajos nuevos; cerrar otra vez no hace nada."""
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, int | float)
                or not math.isfinite(timeout_s) or timeout_s <= 0):
            raise ValueError(f"timeout_s {timeout_s!r} no es un número de segundos > 0")
        # Espera de verdad: se mide con el reloj del sistema, no con ``clock``.
        deadline = time.monotonic() + timeout_s
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while self._queue:
                item = self._queue.popleft()
                item.record = dataclasses.replace(item.record,
                                                  cancel=_cancel_info("shutdown"))
                self._finish(item, state="interrupted", exit_code=None, duration_s=None,
                             error=_error("job_interrupted", job=item.name))
            running = list(self._running.values())
            for item in running:
                if item.record.cancel is None and item.alive():
                    self._request_cancel(item, "shutdown")
            stop_wait = min(SHUTDOWN_STOP_WAIT_S, timeout_s)
            _wait_for_exit(running, time.monotonic() + stop_wait)
            for item in running:
                if item.alive() and not item.terminated:
                    self._force_stop(item, shutdown_wait_s=stop_wait)
            _wait_for_exit(running, deadline, channels=True)
            for item in running:
                self._close_at_shutdown(item)

    def mark_ingested(self, job_uid: str) -> float:
        """El módulo dueño confirma que incorporó los resultados del trabajo ``job_uid``
        (RF-004-16): la hora queda en su ``state.json`` (``ingested_at``, la primera vez) y se
        borran sus entradas y sus resultados (``cleanup.release``); quedan ``request.json``,
        ``events.jsonl``, ``job.log``, ``result.json`` y ``state.json``. Devuelve los MB
        liberados (0 si ya se habían borrado: confirmar otra vez no hace nada más).

        Un trabajo que este lanzador no lanzó (de otra sesión) se busca en la raíz de
        trabajos. :class:`ValueError` sin borrar nada si ``job_uid`` no es un identificador,
        si no hay ningún trabajo con él (o su ``state.json`` no se puede leer), si aún está
        en cola o en curso (aunque haya acabado, hasta que :meth:`poll` lo finalice) o si su
        hilo abandonado sigue en marcha (aún podría escribir en ``out/``)."""
        with self._lock:
            item = self._jobs.get(job_uid)
            if item is not None:
                folder, record = item.folder, item.record
                if item.thread is not None and item.thread.alive and record.is_final:
                    raise ValueError(f"el trabajo {job_uid} terminó, pero su hilo sigue en "
                                     "marcha: sus resultados no se borran hasta que acabe")
            else:
                folder = job_dir(self._jobs_root, job_uid)
                found = read_record(folder)
                if found is None:
                    raise ValueError(f"no hay ningún trabajo {job_uid} con su registro en "
                                     f"«{self._jobs_root}»")
                record = found
            if not record.is_final:
                raise ValueError(f"el trabajo {job_uid} sigue «{record.state}»: no se puede "
                                 "dar por incorporado")
            if record.ingested_at is None:
                record = dataclasses.replace(record, ingested_at=format_utc(_now()))
                write_record(folder, record)
                if item is not None:
                    item.record = record
            return cleanup.release(folder)

    def purge(
        self,
        *,
        older_than_days: float | None,
        all_finished: bool = False,
        only: Iterable[str] | None = None,
        now: dt.datetime | None = None,
        jobs_root: Path | None = None,
    ) -> cleanup.CleanupReport:
        """Borra las carpetas de los trabajos terminados de la raíz de trabajos
        (``cleanup.purge``, RF-004-17): los que terminaron hace más de ``older_than_days``
        días, todos (``all_finished``) o, con ``only``, solo esos (el «Descartar» de la
        lista, RF-004-08). ``jobs_root``: otra raíz donde borrar (la de un trabajo guardado
        que salió en :meth:`stored_snapshots`; si falta, la de este lanzador). Nunca borra
        uno que este lanzador lleve activo: en cola, en curso, terminado sin contar aún en
        un :meth:`poll` (su ``on_finish`` no ha llegado) o con su hilo abandonado en marcha
        (aún podría escribir en su carpeta). Los borrados salen de :meth:`snapshots`.
        Devuelve el ``CleanupReport`` (MB liberados); un argumento que no vale es
        :class:`ValueError` o :class:`TypeError` sin borrar nada."""
        root = None if jobs_root is None else _absolute_root(jobs_root)
        with self._lock:
            busy = {job_uid for job_uid, item in self._jobs.items()
                    if item.state in ACTIVE_STATES
                    or (item.thread is not None and item.thread.alive)}
            busy.update(item.folder.job_uid for item in self._to_report)
            report = cleanup.purge(self._jobs_root if root is None else root,
                                   older_than_days=older_than_days,
                                   all_finished=all_finished, active=busy, only=only,
                                   now=now)
            for job_uid in report.removed:
                self._jobs.pop(job_uid, None)
            return report

    # --- Seguimiento ---------------------------------------------------------------------

    def poll(self) -> list[JobUpdate]:
        """Lo que cambió en cada trabajo desde el sondeo anterior, sin bloquear: los eventos
        recibidos y, de los que terminaron, su final (plan §5.4.2). Pide parar los que
        superaron su tiempo máximo (RF-004-11), termina los que siguen vivos al vencer su
        plazo de gracia (RF-004-10), finaliza los trabajos cuyo proceso terminó, arranca de
        la cola lo que quepa y llama a los ``on_finish`` después de dejar su
        ``state.json``."""
        updates: list[JobUpdate] = []
        finished: list[_Job] = []
        with self._lock:
            for item in list(self._running.values()):
                update = self._poll_job(item)
                if update is not None:
                    updates.append(update)
            self._start_queued()
            for item in self._to_report:
                updates.append(item.update(final=True))
                finished.append(item)
            self._to_report.clear()
        for item in finished:
            self._notify(item)
        return updates

    def snapshots(self) -> list[JobSnapshot]:
        """Una :class:`JobSnapshot` de cada trabajo de este lanzador, por orden de llegada
        (RF-004-06, RF-004-07): los activos y los que ya acabaron. Refleja lo visto en el
        último :meth:`poll`; no sondea."""
        with self._lock:
            now = self._clock()
            return [item.snapshot(now) for item in self._jobs.values()]

    def active_count(self) -> int:
        """Cuántos trabajos de este lanzador están en cola o en curso (RF-004-06)."""
        with self._lock:
            return sum(1 for item in self._jobs.values() if item.state in ACTIVE_STATES)

    def locks_in_use(self) -> set[str]:
        """Los ``lock_id`` de los motores de cálculo que usan sus trabajos en curso (los
        ``compute`` lanzados con un motor): la limpieza de los motores anteriores no los
        borra (``runtime.ComputeEnvironment.remove_stale``, RF-004-27)."""
        with self._lock:
            return {item.interp.lock_id for item in self._jobs.values()
                    if item.state in ACTIVE_STATES and item.interp is not None
                    and item.interp.lock_id is not None}

    def stored_snapshots(self, *, extra_roots: Iterable[Path] = ()) -> list[JobSnapshot]:
        """Los trabajos guardados que no son de este lanzador (RF-004-08, RF-004-13): los de
        su raíz de trabajos y los de ``extra_roots`` (la de sin proyecto, con los de
        diagnóstico), de otra sesión de Blender o de antes de desactivar Geoblender. Lo
        llama la lista de trabajos al abrirse, no el registro.

        Primero deja «Interrumpido» en cada raíz lo que su ``state.json`` deja en cola o en
        curso y este lanzador no lleva (``records.mark_interrupted``: lo dejó así un
        Blender que se cayó). Después lee los registros (``records.scan``) y devuelve una
        foto de cada uno (:func:`stored_snapshot`), por identificador (fecha de creación),
        sin los de este lanzador (que ya están en :meth:`snapshots`) y sin repetir una raíz
        ni un trabajo. Una raíz que no existe no tiene ninguno (no se crea); una que no es
        una ruta completa es :class:`ValueError` sin marcar ni leer nada."""
        extras = [_absolute_root(root) for root in extra_roots]
        with self._lock:
            known = frozenset(self._jobs)
            roots = [self._jobs_root, *extras]
        found: dict[str, JobSnapshot] = {}
        seen: set[str] = set()
        for root in roots:
            key = os.path.normcase(os.path.abspath(root))
            if key in seen:
                continue
            seen.add(key)
            mark_interrupted(root, active_uids=known, occasion=MARKED_AT_LIST)
            for record in scan(root):
                if record.job_uid not in known and record.job_uid not in found:
                    found[record.job_uid] = stored_snapshot(record, root / record.job_uid)
        return [found[job_uid] for job_uid in sorted(found)]

    # --- Ayudas --------------------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("el lanzador de trabajos ya está cerrado: no admite trabajos "
                               "nuevos")

    def _reject(
        self,
        folder: JobDir,
        request: JobRequest,
        error: JobError,
        on_finish: Callable[[JobResult], object] | None,
    ) -> JobHandle:
        """Un trabajo ya preparado cuya petición no vale al lanzarlo queda «Fallido» con el
        código de ``error``, sin proceso: su ``state.json`` deja de decir «En cola», y
        ``on_finish`` se llama en el siguiente :meth:`poll`, como con cualquier final."""
        record = read_record(folder)
        if record is None or record.state != "queued":
            record = JobRecord.from_request(request, executor=REJECTED_EXECUTOR)
        item = _Job(request, folder, record, on_finish)
        self._jobs[folder.job_uid] = item
        self._finish(item, state="failed", exit_code=None, duration_s=None,
                     error=ErrorInfo.from_job_error(error))
        return JobHandle(item, self)

    def _worker_info(self, request: JobRequest) -> catalog.WorkerInfo:
        info = catalog.WORKERS.get(request.worker)
        if info is None:
            raise JobError("worker_unknown", worker=request.worker)
        return info

    def _executor(self, info: catalog.WorkerInfo, request: JobRequest) -> str:
        """``inprocess`` o ``subprocess`` según el tipo de trabajo (RF-004-03, plan
        §5.4.1)."""
        return policy.choose_executor(info, request)

    def _interpreter_for(
        self, request: JobRequest, site_override: Path | None = None
    ) -> interpreter.Interpreter:
        """El intérprete del trabajo según su entorno, el motor de cálculo, el intérprete
        externo y su ``site_override`` (plan §5.3.3); :class:`~.messages.JobError`
        ``runtime_missing`` si necesita el motor y no está listo (RF-004-25, RF-004-26)."""
        assert request.environment is not None  # validate_request lo exige
        return interpreter.resolve_interpreter(
            request.environment, blender_python=self._blender_python, runtime=self._runtime,
            external_python=self._external_python, site_override=site_override,
        )

    def _child_env(self) -> dict[str, str]:
        """El entorno de un worker que arranca ahora (plan §5.3.3): el de Blender sin
        variables ``PYTHON*`` ni ``PIP_*`` y con los hilos de BLAS repartidos entre los
        ``max_subprocess`` workers que pueden correr a la vez, si el usuario no los
        fijó."""
        return interpreter.child_env(
            os.environ, blas_threads=interpreter.blas_threads_for(self._max_subprocess)
        )

    def _start_queued(self) -> None:
        """Arranca de la cola, por orden de llegada, lo que quepa (RF-004-04): cada
        ejecutor tiene sus huecos (``max_subprocess`` en proceso aparte y
        ``max_inprocess`` en hilo, contando los hilos abandonados que siguen vivos), y un
        trabajo que espera su hueco no retiene a los del otro ejecutor."""
        if not self._queue:
            return
        self._abandoned = [executor for executor in self._abandoned if executor.alive]
        busy = {EXECUTOR_SUBPROCESS: 0, EXECUTOR_INPROCESS: len(self._abandoned)}
        for running in self._running.values():
            busy[running.record.executor] += 1
        limits = {EXECUTOR_SUBPROCESS: self._max_subprocess,
                  EXECUTOR_INPROCESS: self._max_inprocess}
        waiting: list[_Job] = []
        while self._queue:
            item = self._queue.popleft()
            executor = item.record.executor
            if busy[executor] >= limits[executor]:
                waiting.append(item)
                continue
            self._launch(item)
            if item.folder.job_uid in self._running:
                busy[executor] += 1
        self._queue.extend(waiting)

    def _launch(self, item: _Job) -> None:
        """Arranca el worker de ``item`` dentro de su *Job Object*: ``state.json`` «En
        curso», nota en ``events.jsonl`` y hilo lector. Si no arranca, lo deja «Fallido» sin
        proceso; si no entra en su *Job Object*, lo termina y lo deja «Fallido». Un trabajo
        en hilo, con :meth:`_launch_thread`."""
        if item.record.executor == EXECUTOR_INPROCESS:
            self._launch_thread(item)
            return
        try:
            interp = self._interpreter_for(item.request, item.site_override)
        except JobError as exc:  # sin motor de cálculo listo (RF-004-25)
            self._finish(item, state="failed", exit_code=None, duration_s=None,
                         error=ErrorInfo.from_job_error(exc))
            return
        item.interp = interp
        folder = item.folder
        command = interpreter.build_command(interp, package_dir=self._package_dir,
                                            job_dir=folder.path, paths=item.paths)
        started_wall = _now()
        try:
            with folder.log_file.open("ab") as log:
                item.started_at = self._clock()
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    cwd=folder.path,
                    env=self._child_env(),
                    creationflags=CREATION_FLAGS,
                )
        except OSError as exc:
            code = ("interpreter_not_found" if isinstance(exc, FileNotFoundError)
                    else "interpreter_failed")
            self._finish(item, state="failed", exit_code=None, duration_s=None,
                         error=_error(code, path=str(interp.python),
                                      detail=exc.strerror or str(exc)))
            return
        item.process = process
        try:
            item.job_object = _contain(process.pid)
        except OSError as exc:
            self._abort_uncontained(item, exc)
            return
        item.record = dataclasses.replace(
            item.record, state="running", started_at=format_utc(started_wall),
            pid=process.pid,
            interpreter=InterpreterInfo(kind=interp.kind, lock_id=interp.lock_id),
        )
        item.state = "running"
        self._running[folder.job_uid] = item
        self._save(item)
        item.events_log.note("launched", executor=item.record.executor,
                             interpreter=interp.kind, pid=process.pid)
        item.reader = _Reader(item, self._clock)
        item.reader.start()

    def _launch_thread(self, item: _Job) -> None:
        """Arranca el trabajo de ``item`` en un hilo *daemon* de Blender
        (``InProcessExecutor``): ``state.json`` «En curso» sin proceso propio y nota en
        ``events.jsonl``. Si no se puede arrancar el hilo, lo deja «Fallido»."""
        assert item.run is not None
        folder = item.folder
        executor = InProcessExecutor(item.request, folder, item.run, clock=self._clock,
                                     paths=item.paths)
        started_wall = _now()
        item.started_at = self._clock()
        item.thread = executor
        item.record = dataclasses.replace(
            item.record, state="running", started_at=format_utc(started_wall), pid=None,
            interpreter=InterpreterInfo(kind=INTERPRETER_KIND),
        )
        item.state = "running"
        self._running[folder.job_uid] = item
        self._save(item)
        item.events_log.note("launched", executor=EXECUTOR_INPROCESS,
                             interpreter=INTERPRETER_KIND, thread=executor.name)
        try:
            executor.start()
        except RuntimeError as exc:  # el sistema no da más hilos
            item.thread = None
            self._finish(item, state="failed", exit_code=None, duration_s=None,
                         error=_error("interpreter_failed", path=str(self._blender_python),
                                      detail=f"no se pudo arrancar el hilo del trabajo "
                                             f"({exc})"))

    def _abort_uncontained(self, item: _Job, exc: OSError) -> None:
        """El worker no entró en su *Job Object*: sin él no se podría terminar con sus
        hijos, así que se termina al momento y el trabajo queda «Fallido»
        (``interpreter_failed`` con el motivo; plan §8)."""
        process = item.process
        assert process is not None
        try:
            process.kill()
        except OSError:
            pass
        try:
            exit_code: int | None = process.wait(timeout=KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            exit_code = None
        item.channel_closed = True  # sin hilo lector: se pueden cerrar las dos tuberías
        item.record = dataclasses.replace(item.record, pid=process.pid)
        reason = exc.strerror or str(exc)
        python = self._blender_python if item.interp is None else item.interp.python
        self._finish(item, state="failed", exit_code=exit_code, duration_s=None,
                     error=_error("interpreter_failed", path=str(python),
                                  detail=f"no se pudo asignar el worker a su Job Object "
                                         f"({reason})"))

    def _request_cancel(self, item: _Job, reason: str, **details: JsonValue) -> None:
        """Pide parar un trabajo en curso: centinela ``cancel`` (si no se puede crear, el
        plazo de gracia lo terminará igual) y, en hilo, su aviso; cancelación en
        ``state.json`` y nota en ``events.jsonl`` (con ``details``), después de los eventos
        que ya envió. Desde ahora corre su plazo de gracia."""
        if item.thread is not None:
            self._pump(item)
        try:
            item.folder.cancel_file.touch(exist_ok=True)
        except OSError:
            LOGGER.exception("No se pudo crear el centinela de cancelación del trabajo %s",
                             item.folder.job_uid)
        if item.thread is not None:
            item.thread.cancel()
        item.cancel_at = self._clock()
        item.record = dataclasses.replace(item.record, cancel=_cancel_info(reason))
        self._save(item)
        item.events_log.note("cancel_requested", reason=reason, grace_s=item.request.grace_s,
                             **details)

    def _enforce_timeout(self, item: _Job) -> None:
        """Si el trabajo sigue en marcha pasado su tiempo máximo desde que arrancó su
        proceso y nadie ha pedido pararlo, se le pide parar como en una cancelación, con
        motivo ``timeout``; acabará «Tiempo agotado» (RF-004-11)."""
        if item.record.cancel is not None or item.started_at is None:
            return
        timeout = item.request.timeout_s
        if timeout is None or self._clock() - item.started_at <= timeout:
            return
        self._request_cancel(item, "timeout", timeout_s=timeout)

    def _enforce_grace(self, item: _Job) -> None:
        """Si el worker sigue vivo al vencer el plazo de gracia de su cancelación, termina
        su *Job Object* (él y sus hijos) y la cancelación queda forzada (RF-004-10)."""
        cancel = item.record.cancel
        if cancel is None or item.cancel_at is None or item.terminated:
            return
        grace = item.request.grace_s
        if self._clock() - item.cancel_at < grace:
            return
        self._force_stop(item, grace_s=grace)

    def _force_stop(self, item: _Job, **wait: float) -> None:
        """Termina el *Job Object* de un trabajo al que se pidió parar y sigue vivo (el
        worker y sus hijos): la cancelación queda forzada en ``state.json`` y la nota
        ``terminated`` dice cuánto se esperó (``grace_s``, al vencer el plazo de gracia,
        RF-004-10; ``shutdown_wait_s``, al cerrar el lanzador, RF-004-13). Un hilo no se
        puede terminar: se abandona (lo que envíe desde ahora se descarta y su hueco sigue
        ocupado hasta que acabe), con la nota ``abandoned``; el trabajo se finaliza en
        cuanto se recogen los eventos que ya envió."""
        cancel = item.record.cancel
        assert cancel is not None
        item.terminated = True
        item.shutdown_wait_s = wait.get("shutdown_wait_s")
        thread = item.thread
        if thread is not None:
            thread.abandon()
            self._abandoned.append(thread)
            self._pump(item)
        else:
            self._terminate(item)
        item.record = dataclasses.replace(item.record,
                                          cancel=dataclasses.replace(cancel, forced=True))
        self._save(item)
        if thread is not None:
            item.events_log.note("abandoned", reason=cancel.reason, **wait)
        else:
            item.events_log.note("terminated", reason=cancel.reason, **wait,
                                 exit_code=EXIT_TERMINATED)

    def _terminate(self, item: _Job) -> None:
        """Termina el *Job Object* del trabajo: el worker y todos sus descendientes. Sin
        *Job Object* (fuera de Windows) o si Windows no lo termina, al menos el worker."""
        job_object = item.job_object
        if job_object is not None:
            try:
                job_object.terminate(EXIT_TERMINATED)
                return
            except OSError:
                LOGGER.exception("No se pudo terminar el Job Object del trabajo %s",
                                 item.folder.job_uid)
        if item.process is not None:
            try:
                item.process.kill()
            except OSError:
                pass

    def _poll_job(self, item: _Job) -> JobUpdate | None:
        if item.thread is not None:
            return self._poll_thread(item)
        reader = item.reader
        process = item.process
        assert reader is not None and process is not None
        closed = reader.closed.is_set()  # antes de vaciar: lo que llegó antes ya está
        item.pending_events.extend(self._take(item, reader.drain()))
        exit_code = process.poll()
        if exit_code is not None:
            item.mark_exit(self._clock(), _now())
            seen = item.exit_seen_at if item.exit_seen_at is not None else self._clock()
            if closed or self._clock() - seen >= CHANNEL_DRAIN_S:
                if not closed:
                    # Un nieto retiene el canal: se finaliza con lo recibido.
                    item.pending_events.extend(self._take(item, reader.drain()))
                    item.events_log.note("channel_open", seconds=CHANNEL_DRAIN_S)
                self._finalize(item, exit_code, channel_closed=closed)
                return None  # se cuenta con los finalizados, en este mismo sondeo
        else:
            self._enforce_timeout(item)
            self._enforce_grace(item)
        if not item.pending_events:
            return None
        return item.update(final=False)

    def _poll_thread(self, item: _Job) -> JobUpdate | None:
        """El sondeo de un trabajo en hilo: recoge sus eventos y, si acabó, lo finaliza con
        su código; si no, aplica su tiempo máximo y su plazo de gracia, y si lo abandona al
        vencer este, lo finaliza sin código («Cancelado» o «Tiempo agotado», forzado)."""
        thread = item.thread
        assert thread is not None
        done = thread.finished  # antes de vaciar: lo que envió antes de acabar ya está
        self._pump(item)
        if done:
            self._finalize_thread(item)
            return None
        self._enforce_timeout(item)
        self._enforce_grace(item)
        if item.terminated:
            self._finalize(item, None, channel_closed=True)
            return None
        if not item.pending_events:
            return None
        return item.update(final=False)

    def _pump(self, item: _Job) -> None:
        """Los eventos que envió un trabajo en hilo: a ``events.jsonl``, en orden, y al
        trabajo (para el siguiente :class:`JobUpdate`)."""
        thread = item.thread
        assert thread is not None
        events = thread.drain()
        for event in events:
            item.events_log.event(event)
        item.pending_events.extend(self._take(item, events))

    def _finalize_thread(self, item: _Job) -> None:
        """Finaliza un trabajo en hilo que acabó, con su código y la hora en que acabó."""
        thread = item.thread
        assert thread is not None and thread.ended_at is not None
        assert thread.ended_wall is not None
        item.mark_exit(thread.ended_at, thread.ended_wall)
        self._finalize(item, thread.exit_code, channel_closed=True)

    def _close_at_shutdown(self, item: _Job) -> None:
        """Finaliza en el cierre un trabajo que estaba en curso, con los eventos que hayan
        llegado (plan §5.3.4; «Interrumpido» si se le pidió parar por el cierre). Si su
        proceso no terminó a tiempo, queda sin código de salida: al finalizar se cierra su
        *Job Object*, que lo termina, y su entrada estándar. Un hilo que sigue en marcha
        (ya abandonado) también queda sin código."""
        if item.thread is not None:
            done = item.thread.finished
            self._pump(item)
            if done:
                self._finalize_thread(item)
            else:
                self._finalize(item, None, channel_closed=True)
            return
        reader = item.reader
        process = item.process
        assert reader is not None and process is not None
        closed = reader.closed.is_set()  # antes de vaciar: lo que llegó antes ya está
        item.pending_events.extend(self._take(item, reader.drain()))
        exit_code = process.poll()
        if exit_code is not None:
            item.mark_exit(self._clock(), _now())
        if not closed:
            item.events_log.note("channel_open", reason="shutdown")
        self._finalize(item, exit_code, channel_closed=closed)

    def _take(self, item: _Job, items: Iterable[JobEvent | InvalidLine]) -> list[JobEvent]:
        """Los eventos de ``items`` (las líneas inválidas ya están en ``events.jsonl``),
        aplicados al trabajo."""
        events: list[JobEvent] = []
        for entry in items:
            if isinstance(entry, InvalidLine):
                item.invalid_count += 1
                if len(item.invalid) < MAX_LOGGED_INVALID:
                    item.invalid.append(entry)
                continue
            events.append(entry)
            self._observe(item, entry)
        return events

    def _observe(self, item: _Job, event: JobEvent) -> None:
        item.last_event_at = format_utc(dt.datetime.fromtimestamp(event.ts, dt.UTC))
        match event.type:
            case "start":
                launched = item.record.interpreter
                item.record = dataclasses.replace(
                    item.record,
                    interpreter=_interpreter(
                        event.info, lock_id=None if launched is None else launched.lock_id
                    ),
                    last_event_at=item.last_event_at,
                )
                self._save(item)
            case "progress":
                if event.frac is not None:
                    item.frac = event.frac
                if event.msg:
                    item.message = event.msg
            case "result":
                item.result_event = event
            case "error":
                item.error_event = event
                item.message = event.msg or item.message
            case "cancelled":
                item.cancelled_event = event
                item.message = event.msg or item.message

    def _finalize(self, item: _Job, exit_code: int | None, *, channel_closed: bool) -> None:
        """Estado según el código de salida (plan §5.3.4), resultados verificados
        (RF-004-05), ``state.json`` y avisos en ``job.log`` (RF-004-15). Con el canal aún
        abierto, su lectura no se toca: cerrarla bloquearía hasta que el hilo lector
        vuelva."""
        item.channel_closed = channel_closed
        exit_at = item.exit_seen_at if item.exit_seen_at is not None else self._clock()
        duration = max(0.0, exit_at - (item.started_at or exit_at))
        state, error = _outcome(item, exit_code)
        outputs: tuple[OutputRef, ...] = ()
        if state == "succeeded" and item.result_event is not None:
            try:
                verify_outputs(item.folder, item.result_event.outputs, job=item.name)
            except JobError as exc:
                state, error = "failed", ErrorInfo.from_job_error(exc)
            else:
                outputs = item.result_event.outputs
        self._finish(item, state=state, exit_code=exit_code, duration_s=duration,
                     error=error, outputs=outputs, ended=item.exit_wall)

    def _finish(
        self,
        item: _Job,
        *,
        state: str,
        exit_code: int | None,
        duration_s: float | None,
        error: ErrorInfo | None,
        outputs: tuple[OutputRef, ...] = (),
        ended: dt.datetime | None = None,
    ) -> None:
        """Deja ``item`` en su estado final: ``state.json``, nota de fin, avisos en
        ``job.log`` y su :class:`JobResult`, que se cuenta en el siguiente :meth:`poll`."""
        ended_wall = ended or _now()
        item.record = dataclasses.replace(
            item.record, state=state, ended_at=format_utc(ended_wall), duration_s=duration_s,
            exit_code=exit_code, error=error, outputs=outputs,
            last_event_at=item.last_event_at,
        )
        if state == "succeeded":
            item.frac = 1.0
        elif error is not None:
            item.message = error.text
        item.state = state
        self._save(item)
        item.events_log.note("finished", state=state, exit_code=exit_code,
                             error=None if error is None else error.code)
        item.events_log.close()
        self._append_log(item, exit_code, duration_s)
        item.release_job_object()
        item.close_pipes()
        summary = item.result_event.summary if state == "succeeded" and item.result_event else {}
        item.result = JobResult(
            job_uid=item.folder.job_uid, state=state, outputs=outputs, summary=summary,
            error_code=None if error is None else error.code,
            error_text=None if error is None else error.text,
            duration_s=duration_s, job_dir=item.folder,
        )
        self._running.pop(item.folder.job_uid, None)
        self._to_report.append(item)

    def _save(self, item: _Job) -> None:
        """``state.json`` del trabajo; si no se puede escribir, queda en el registro de
        Python y el trabajo sigue (su estado en memoria es el bueno)."""
        try:
            write_record(item.folder, item.record)
        except (OSError, ValueError):
            LOGGER.exception("No se pudo escribir el estado del trabajo %s",
                             item.folder.job_uid)

    def _append_log(self, item: _Job, exit_code: int | None, duration_s: float | None) -> None:
        """Al final de ``job.log`` (el worker ya terminó: nadie más escribe en él), los
        avisos de las líneas del canal que no eran eventos y el estado final."""
        lines = [
            f"{LOG_PREFIX} aviso: el worker escribió en su canal una línea que no es un "
            f"evento ({entry.reason}): {entry.text}"
            for entry in item.invalid
        ]
        omitted = item.invalid_count - len(item.invalid)
        if omitted > 0:
            lines.append(f"{LOG_PREFIX} aviso: {omitted} líneas más del canal no eran "
                         "eventos (están en events.jsonl)")
        cancel = item.record.cancel
        if cancel is not None:
            reason = _REASON_TEXT[cancel.reason]
            if cancel.reason == "timeout" and item.request.timeout_s is not None:
                reason += f" de {_seconds_text(item.request.timeout_s)} s"
            lines.append(f"{LOG_PREFIX} se pidió cancelar el trabajo {reason} "
                         f"({cancel.requested_at})")
            if cancel.forced and item.thread is not None:
                waited = (f"al cerrarse Geoblender, el trabajo en hilo seguía en marcha tras "
                          f"esperarlo {_seconds_text(item.shutdown_wait_s)} s"
                          if item.shutdown_wait_s is not None else
                          f"el trabajo en hilo seguía en marcha al vencer su plazo de gracia "
                          f"de {_seconds_text(item.request.grace_s)} s")
                lines.append(f"{LOG_PREFIX} {waited}: un hilo no se puede terminar; se deja "
                             "acabar solo y lo que entregue se descarta")
            elif cancel.forced and item.shutdown_wait_s is not None:
                lines.append(
                    f"{LOG_PREFIX} al cerrarse Geoblender, el worker seguía vivo tras "
                    f"esperarlo {_seconds_text(item.shutdown_wait_s)} s: se terminó con sus "
                    f"procesos hijos (código {EXIT_TERMINATED})"
                )
            elif cancel.forced:
                lines.append(
                    f"{LOG_PREFIX} el worker seguía vivo al vencer su plazo de gracia de "
                    f"{_seconds_text(item.request.grace_s)} s: se terminó con sus procesos "
                    f"hijos (código {EXIT_TERMINATED})"
                )
        seconds = "" if duration_s is None else f" en {duration_s:.2f} s".replace(".", ",")
        if item.thread is not None:
            code = "en hilo, " + ("sin acabar" if exit_code is None else f"código {exit_code}")
        else:
            code = "sin proceso" if exit_code is None else f"código de salida {exit_code}"
        final = f"{LOG_PREFIX} el trabajo termina «{_STATE_TEXT[item.state]}» ({code}){seconds}"
        if item.record.error is not None:
            final += f": {item.record.error.text}"
        lines.append(final)
        try:
            with item.folder.log_file.open("a", encoding="utf-8", errors="replace") as log:
                log.write("".join(line + "\n" for line in lines))
        except OSError:
            LOGGER.exception("No se pudo completar el registro del trabajo %s",
                             item.folder.job_uid)

    def _notify(self, item: _Job) -> None:
        callback = item.on_finish
        if callback is None or item.result is None:
            return
        try:
            callback(item.result)
        except Exception:  # noqa: BLE001 - un on_finish que falla no tumba el sondeo
            LOGGER.exception("Falló el aviso de fin (on_finish) del trabajo %s",
                             item.folder.job_uid)


def verify_outputs(folder: JobDir, outputs: Iterable[OutputRef], *, job: str) -> None:
    """Comprueba cada resultado declarado (RF-004-05): que es un fichero que existe dentro
    de ``out/`` de la carpeta del trabajo (también tras resolver enlaces) y que su sha256 y
    su tamaño son los declarados. :class:`~.messages.JobError` ``output_missing`` u
    ``output_hash_mismatch`` (con la ruta relativa y el trabajo ``job``) en el primero que
    no cumple."""
    try:
        out_root = folder.outputs_dir.resolve(strict=True)
    except OSError:
        out_root = None
    for ref in outputs:
        path = folder.path.joinpath(*ref.path.split("/"))
        try:
            real = path.resolve(strict=True)
        except OSError:
            raise JobError("output_missing", path=ref.path, job=job) from None
        if out_root is None or not real.is_relative_to(out_root) or not real.is_file():
            raise JobError("output_missing", path=ref.path, job=job)
        try:
            digest, size = _sha256(real)
        except OSError:
            raise JobError("output_missing", path=ref.path, job=job) from None
        if digest != ref.sha256 or size != ref.size:
            raise JobError("output_hash_mismatch", path=ref.path, job=job)


# --- Un trabajo del lanzador ----------------------------------------------------------------


class _Job:
    """Lo que el lanzador sabe de un trabajo."""

    def __init__(
        self,
        request: JobRequest,
        folder: JobDir,
        record: JobRecord,
        on_finish: Callable[[JobResult], object] | None,
    ) -> None:
        self.request = request
        self.folder = folder
        self.record = record
        self.on_finish = on_finish
        self.state = record.state
        self.frac = 0.0
        self.message = ""
        self.process: subprocess.Popen[bytes] | None = None
        self.interp: interpreter.Interpreter | None = None
        """El intérprete con que se lanzó su proceso."""
        self.paths: Mapping[str, Path] = {}
        """Las rutas del trabajo fuera de su carpeta (``submit(..., paths=…)``)."""
        self.site_override: Path | None = None
        """La carpeta ``site`` de su intérprete (``submit(..., site_override=…)``)."""
        self.run: catalog.WorkerRun | None = None
        """La función del tipo de trabajo, si va en hilo."""
        self.thread: InProcessExecutor | None = None
        self.job_object: winjob.JobObject | None = None
        self.cancel_at: float | None = None
        self.terminated = False
        self.shutdown_wait_s: float | None = None
        self.reader: _Reader | None = None
        self.events_log = _EventsLog(folder.events_file)
        self.started_at: float | None = None
        self.exit_seen_at: float | None = None
        self.exit_wall: dt.datetime | None = None
        self.last_event_at: str | None = None
        self.result_event: JobEvent | None = None
        self.error_event: JobEvent | None = None
        self.cancelled_event: JobEvent | None = None
        self.invalid: list[InvalidLine] = []
        self.invalid_count = 0
        self.pending_events: list[JobEvent] = []
        self.channel_closed = False
        self.result: JobResult | None = None
        self._exit_lock = threading.Lock()

    @property
    def name(self) -> str:
        """El nombre del trabajo en los mensajes."""
        label = self.request.label
        return label if isinstance(label, str) and label.strip() else self.folder.job_uid

    def alive(self) -> bool:
        """Si su proceso sigue vivo o, en hilo, si su trabajo aún no ha acabado."""
        if self.thread is not None:
            return not self.thread.finished
        return self.process is not None and self.process.poll() is None

    def mark_exit(self, clock_now: float, wall_now: dt.datetime) -> None:
        """Apunta cuándo terminó el proceso (la primera vez que se ve)."""
        with self._exit_lock:
            if self.exit_seen_at is None:
                self.exit_seen_at = clock_now
                self.exit_wall = wall_now

    def update(self, *, final: bool) -> JobUpdate:
        events = tuple(self.pending_events)
        self.pending_events.clear()
        return JobUpdate(self.folder.job_uid, self.state, self.frac, self.message, events,
                         self.result if final else None)

    def snapshot(self, now: float) -> JobSnapshot:
        """La foto del trabajo a la hora ``now`` del reloj del lanzador."""
        record = self.record
        duration: float | None
        if self.state not in ACTIVE_STATES:
            duration = record.duration_s
        elif self.started_at is not None:
            duration = max(0.0, now - self.started_at)
        else:
            duration = None
        return JobSnapshot(
            job_uid=self.folder.job_uid, name=self.name, worker=self.request.worker,
            state=self.state, executor=record.executor, frac=self.frac,
            message=self.message, duration_s=duration, interpreter=record.interpreter,
            error=record.error, cancel_requested=record.cancel is not None,
            log_file=self.folder.log_file, ingested=record.ingested_at is not None,
            folder=self.folder.path,
        )

    def release_job_object(self) -> None:
        """Cierra el *Job Object* del worker (ya terminado): con ``KILL_ON_JOB_CLOSE``,
        Windows termina lo que el worker dejara vivo (RF-004-13)."""
        job_object, self.job_object = self.job_object, None
        if job_object is not None:
            job_object.close()

    def close_pipes(self) -> None:
        """Cierra la tubería de la entrada estándar y, si el hilo lector ya acabó, la del
        canal (cerrarla mientras lee bloquearía hasta que vuelva)."""
        process = self.process
        if process is None:
            return
        streams = [process.stdin]
        if self.channel_closed:
            streams.append(process.stdout)
        for stream in streams:
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


class _EventsLog:
    """``events.jsonl`` de un trabajo: los eventos recibidos, en orden, y las notas del
    lanzador, una línea JSON en UTF-8 cada uno, escritas enteras y vaciadas al momento. Lo
    usan el hilo lector y el lanzador (con cerrojo). Un fallo al escribir queda en el
    registro de Python una vez y no para el trabajo."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._handle: IO[bytes] | None = None
        self._closed = False
        self._failed = False

    def event(self, event: JobEvent) -> None:
        self._write(encode_event(event))

    def note(self, kind: str, **fields: JsonValue) -> None:
        data: dict[str, Any] = {NOTE_KEY: kind, "ts": time.time(), **fields}
        self._write((json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n")
                    .encode("utf-8", "backslashreplace"))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            handle, self._handle = self._handle, None
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass

    def _write(self, line: bytes) -> None:
        with self._lock:
            if self._closed or self._failed:
                return
            try:
                if self._handle is None:
                    self._handle = self._path.open("ab")
                self._handle.write(line)
                self._handle.flush()
            except OSError:
                self._failed = True
                LOGGER.exception("No se pudo escribir %s", self._path.name)


class _Reader:
    """Hilo lector *daemon* del canal de un worker: decodifica lo que llega, lo añade a
    ``events.jsonl`` y lo deja en una cola; al cerrarse el canal, espera al proceso y apunta
    cuándo terminó."""

    def __init__(self, item: _Job, clock: Callable[[], float]) -> None:
        self._item = item
        self._clock = clock
        self._queue: queue.SimpleQueue[JobEvent | InvalidLine] = queue.SimpleQueue()
        self.closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"geoblender-job-{item.folder.job_uid}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def drain(self) -> list[JobEvent | InvalidLine]:
        found: list[JobEvent | InvalidLine] = []
        while True:
            try:
                found.append(self._queue.get_nowait())
            except queue.Empty:
                return found

    def _run(self) -> None:
        item = self._item
        process = item.process
        assert process is not None and process.stdout is not None
        stream = process.stdout
        decoder = EventDecoder()
        try:
            while data := stream.read1(READ_BYTES):
                self._handle(decoder.feed(data))
        except (OSError, ValueError):
            pass  # el canal se cerró desde fuera
        finally:
            try:
                self._handle(decoder.close())
            except ValueError:
                pass
            self.closed.set()
        try:
            process.wait()
        except OSError:
            return
        item.mark_exit(self._clock(), _now())

    def _handle(self, items: list[JobEvent | InvalidLine]) -> None:
        log = self._item.events_log
        for entry in items:
            if isinstance(entry, JobEvent):
                log.event(entry)
            else:
                log.note("invalid_line", text=entry.text, reason=entry.reason)
            self._queue.put(entry)


# --- Ayudas ---------------------------------------------------------------------------------


def _outcome(item: _Job, exit_code: int | None) -> tuple[str, ErrorInfo | None]:
    """El estado final según el código de salida y los eventos (plan §5.3.4). Pedida la
    cancelación, con cualquier salida, «Tiempo agotado» si la pidió el tiempo máximo (con
    él en el mensaje, RF-004-11), «Interrumpido» si la pidió el cierre del lanzador
    (RF-004-13) y si no «Cancelado» (forzado si hubo que terminarlo): lo que entregara el
    worker se descarta, como en el hilo (spec §8). Sin código de salida (un proceso que no
    terminó a tiempo en el cierre), «Interrumpido»."""
    name = item.name
    cancel = item.record.cancel
    if cancel is not None:
        if cancel.reason == "timeout":
            return "timed_out", _error("job_timeout", job=name,
                                       seconds=item.request.timeout_s)
        if cancel.reason == "shutdown":
            return "interrupted", _error("job_interrupted", job=name)
        return "cancelled", _error("job_cancelled", job=name, forced=cancel.forced)
    if exit_code is None:
        return "interrupted", _error("job_interrupted", job=name)
    if exit_code == EXIT_OK:
        if item.result_event is not None:
            return "succeeded", None
        return "failed", _error("protocol_no_result", job=name)
    if exit_code == EXIT_CANCELLED:
        return "cancelled", _error("job_cancelled", job=name, forced=False)
    if exit_code == EXIT_PARENT_LOST:
        return "interrupted", _error("job_interrupted", job=name)
    if exit_code in (EXIT_FAILED, EXIT_STARTUP) and item.error_event is not None:
        event = item.error_event
        assert event.code is not None and event.msgid is not None
        # El texto lo manda el worker: al usuario llega en una línea y sin traza (RF-004-12).
        return "failed", ErrorInfo(code=event.code, msgid=event.msgid, values=event.values,
                                   text=one_line(event.msg) or event.code)
    return "failed", _error("worker_crashed", job=name, exit_code=exit_code)


def _error(code: str, **values: object) -> ErrorInfo:
    return ErrorInfo.from_job_error(JobError(code, **values))


def _check_maximum(value: object, name: str) -> None:
    """Un máximo de trabajos a la vez: entero ≥ 1 (:class:`ValueError` si no)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} {value!r} no es un entero ≥ 1")


def _absolute_root(jobs_root: Path) -> Path:
    """La raíz de trabajos como ruta completa (:class:`ValueError` si no lo es)."""
    root = Path(jobs_root)
    if not root.is_absolute():
        raise ValueError(f"la raíz de trabajos «{root}» no es una ruta completa")
    return root


def _absolute_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
    """Las rutas prohibidas como rutas completas (:class:`ValueError` si alguna no lo es)."""
    found = tuple(Path(root) for root in roots)
    for root in found:
        if not root.is_absolute():
            raise ValueError(f"la ruta prohibida «{root}» no es una ruta completa")
    return found


def _wait_for_exit(items: Iterable[_Job], until: float, *, channels: bool = False) -> None:
    """Espera, como mucho hasta ``until`` (``time.monotonic``), a que terminen los procesos
    de ``items`` y, con ``channels``, a que sus hilos lectores vean el canal cerrado. A un
    trabajo en hilo se le espera a que acabe, salvo si ya se abandonó."""
    for item in items:
        if item.thread is not None:
            if not item.terminated:
                item.thread.wait(max(0.0, until - time.monotonic()))
            continue
        process = item.process
        assert process is not None
        try:
            process.wait(timeout=max(0.0, until - time.monotonic()))
        except subprocess.TimeoutExpired:
            continue
        if channels and item.reader is not None:
            item.reader.closed.wait(max(0.0, until - time.monotonic()))


def _cancel_info(reason: str) -> CancelInfo:
    """La cancelación pedida ahora por ``reason`` (``user``, ``timeout`` o ``shutdown``)."""
    return CancelInfo(requested_at=format_utc(_now()), reason=reason, forced=False)


def _contain(pid: int) -> winjob.JobObject | None:
    """El *Job Object* nuevo del worker ``pid``, ya asignado (plan §5.3.3). Fuera de
    Windows, ``None``: entonces solo se puede terminar el worker, no sus hijos.
    :class:`OSError` si no se puede asignar."""
    if not winjob.supported():
        return None
    job_object = winjob.JobObject()
    try:
        job_object.assign(pid)
    except BaseException:
        job_object.close()
        raise
    return job_object


def _seconds_text(value: float) -> str:
    """Segundos como los lee una persona en español: «1», «2,5»."""
    return f"{value:g}".replace(".", ",")


def _interpreter(info: Mapping[str, JsonValue], *, lock_id: str | None = None
                 ) -> InterpreterInfo:
    """El intérprete que contó el evento ``start`` (con el ``lock_id`` del motor con que se
    lanzó); lo que no es un texto no se guarda."""
    kind = info.get("kind")

    def text(name: str) -> str | None:
        value = info.get(name)
        return value if isinstance(value, str) and value else None

    return InterpreterInfo(
        kind=kind if isinstance(kind, str) and kind in INTERPRETER_KINDS else INTERPRETER_KIND,
        python=text("python"), numpy=text("numpy"), blas=text("blas"), lock_id=lock_id,
    )


def _external_python(path: Path | None) -> Path | None:
    """El intérprete externo como ruta completa (``None``: ninguno; :class:`ValueError` si
    no es una ruta completa)."""
    if path is None:
        return None
    exe = Path(path)
    if not exe.is_absolute():
        raise ValueError(f"el intérprete externo «{exe}» no es una ruta completa")
    return exe


def _site_override(path: Path | None) -> Path | None:
    """La carpeta ``site`` de ``submit`` como ruta completa (``None``: ninguna;
    :class:`ValueError` si no es una ruta completa)."""
    if path is None:
        return None
    if not isinstance(path, str | os.PathLike) or not Path(path).is_absolute():
        raise ValueError(f"la carpeta site {path!r} no es una ruta completa")
    return Path(path)


def _sha256(path: Path) -> tuple[str, int]:
    """Huella sha256 y tamaño en bytes de ``path``, leído por bloques."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(_HASH_BLOCK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
