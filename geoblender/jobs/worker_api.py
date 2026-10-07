# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que usa la función de dominio de un trabajo en los dos ejecutores (spec 004;
RF-004-05, RF-004-09, RF-004-12; plan 004 §5.2.3, §5.3.1, §5.3.4 y §5.4.5).

- :class:`WorkerContext`: lo que recibe ``run(ctx)`` (``WorkerInfo.run`` y ``main`` de
  ``workers/<tipo>.py``), igual en el hilo de Blender y en el proceso aparte: la petición y
  la carpeta del trabajo, sus entradas (:meth:`~WorkerContext.input_path`), dónde escribir
  los resultados (:meth:`~WorkerContext.output_path`, siempre dentro de ``out/``), el avance
  (:meth:`~WorkerContext.progress`), las notas del registro (:meth:`~WorkerContext.log`), la
  cancelación (:meth:`~WorkerContext.check_cancelled`) y la declaración de cada resultado con
  su huella sha256 (:meth:`~WorkerContext.add_output`, RF-004-05).
- Sumideros de eventos (:class:`EventSink`): :class:`StreamSink`, el canal del protocolo (el
  stdout original del worker en proceso aparte, plan §5.4.3), y :class:`QueueSink`, la cola
  que vacía el lanzador para el ejecutor en hilo. Los dos aceptan exactamente los mismos
  eventos (mismo seguimiento en los dos ejecutores, RF-004-03).
- :class:`JobCancelled`: el trabajo atendió la cancelación (salida 3 en proceso aparte;
  «Cancelado», o «Tiempo agotado» si la pidió el tiempo máximo).
- :class:`JobFailed`: el cálculo falló por una causa que se explica al usuario (salida 2 y
  evento ``error`` en proceso aparte; «Fallido» en los dos ejecutores), con su código, su
  ``msgid`` en inglés, sus valores y su texto en español (RF-004-12).
- Para los ejecutores: :func:`interpreter_info`, lo que cuenta el evento ``start`` (pid,
  intérprete y versiones de Python, numpy y BLAS; RF-004-15), y
  :meth:`WorkerContext.finish`, el cierre de un trabajo que terminó bien (``result.json`` y
  evento ``result``), iguales en el arranque del proceso aparte y en el hilo.

**Avance** (plan §5.2.3): como mucho un evento cada :data:`PROGRESS_INTERVAL_S` s (10 por
segundo). El que llega antes de tiempo se retiene (solo el más reciente) y sale en cuanto
toca, en la siguiente llamada al contexto (``progress``, ``log`` o ``check_cancelled``), y
siempre al acabar: :meth:`~WorkerContext.flush` o :meth:`~WorkerContext.emit`, que el
ejecutor llama antes de su evento final. Así el último avance llega siempre.

**Cancelación** (RF-004-09, plan §5.4.5): la piden el centinela ``cancel`` de la carpeta del
trabajo (lo crea el lanzador; se mira en disco como mucho cada :data:`CANCEL_POLL_S` s) y,
en el ejecutor en hilo, su ``threading.Event`` (el aviso del hilo, que se ve al momento).
Una cancelación vista no se deshace.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import platform
import queue
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import IO, Any, Protocol

from ..core.paths import RESERVED_NAMES
from .messages import JobError
from .paths import INPUTS_DIR, OUTPUTS_DIR, PARTIAL_SUFFIX, JobDir

# ``_relative_problem``: la misma regla de «dentro de in/ u out/» que la petición y OutputRef.
from .protocol import (
    JobEvent,
    JobRequest,
    JsonValue,
    OutputRef,
    _relative_problem,
    encode_event,
    plain_json,
)
from .records import INTERPRETER_KINDS

PROGRESS_INTERVAL_S = 0.1
"""Mínimo entre dos eventos de avance enviados: como mucho 10 por segundo (plan §5.2.3)."""
CANCEL_POLL_S = 0.05
"""Cada cuánto, como mucho, se mira en disco el centinela ``cancel`` (el aviso del hilo se
mira siempre): un cálculo que comprueba sin parar no castiga el disco, y la cancelación se ve
en ≤ 50 ms (RF-004-09 pide parar en ≤ 2 s)."""
CANCELLED_TEXT = "Se pidió parar el trabajo"
"""Texto de :class:`JobCancelled` cuando lo lanza el contexto (el worker puede dar otro más
preciso: «Cancelado en el trozo 11 de 20»)."""
_HASH_BLOCK = 1 << 20
"""Bloque de lectura al calcular la huella de un resultado (1 MiB)."""
UNKNOWN_BLAS = "unknown"
"""La BLAS de un numpy que no dice cuál usa."""

type _EventQueue = queue.Queue[JobEvent] | queue.SimpleQueue[JobEvent]


class JobCancelled(Exception):
    """El trabajo paró porque se le pidió (RF-004-09). El texto, si lo hay, dice dónde
    («Cancelado en el trozo 11 de 20») y va al registro."""


class JobFailed(Exception):
    """Fallo de un cálculo explicado al usuario (RF-004-12): ``code`` (identificador
    estable en inglés, ``"engine_missing_orientation"``), ``msgid`` (inglés, con sus
    marcadores), ``values`` (JSON, para mostrarlo en otro idioma) y ``text`` (español, ya
    relleno), que es también ``str(error)``. Nunca lleva una traza de Python: la traza va
    al registro (``job.log``)."""

    def __init__(
        self,
        code: str,
        *,
        msgid: str,
        text: str,
        values: Mapping[str, JsonValue] | None = None,
    ) -> None:
        for name, value in (("code", code), ("msgid", msgid), ("text", text)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"el fallo de un trabajo necesita {name} (texto no vacío)")
        copied = plain_json({} if values is None else values, "values")
        if not isinstance(copied, dict):
            raise ValueError("los valores (values) del fallo no son un objeto JSON")
        self.code = code
        self.msgid = msgid
        self.text = text
        self.values: dict[str, JsonValue] = copied
        super().__init__(text)

    @classmethod
    def from_error(cls, error: JobError) -> JobFailed:
        """El fallo con el código, el ``msgid``, los valores y el texto de un
        :class:`~.messages.JobError` del catálogo de los trabajos (``request_invalid``…)."""
        return cls(error.code, msgid=error.msgid, text=error.text, values=error.values)


# --- Intérprete ---------------------------------------------------------------------------


def interpreter_info(kind: str) -> dict[str, JsonValue]:
    """Lo que el evento ``start`` cuenta del intérprete que ejecuta el trabajo (plan §5.2.3;
    RF-004-15): ``pid``, ``kind`` (``blender``, ``compute`` o ``external``; otro es
    :class:`ValueError`), la versión de Python y las de numpy y su BLAS (las dos ``None`` si
    numpy no se puede importar en este intérprete)."""
    if kind not in INTERPRETER_KINDS:
        raise ValueError(
            f"el tipo de intérprete «{kind}» no es uno de {', '.join(INTERPRETER_KINDS)}"
        )
    numpy_version: str | None = None
    blas: str | None = None
    try:
        import numpy as np
    except ImportError:
        pass
    else:
        numpy_version = str(np.__version__)
        blas = blas_name(np)
    return {
        "pid": os.getpid(),
        "kind": kind,
        "python": platform.python_version(),
        "numpy": numpy_version,
        "blas": blas,
    }


def blas_name(np: Any) -> str:
    """El nombre de la BLAS del numpy ``np`` según ``numpy.show_config`` (``auto`` en el de
    Blender, ``scipy-openblas`` en el del motor), o :data:`UNKNOWN_BLAS` si no lo dice."""
    try:
        name = np.show_config(mode="dicts")["Build Dependencies"]["blas"]["name"]
    except Exception:  # noqa: BLE001 - cualquier numpy sin esa información
        return UNKNOWN_BLAS
    return name if isinstance(name, str) and name else UNKNOWN_BLAS


# --- Sumideros de eventos ------------------------------------------------------------------


class EventSink(Protocol):
    """Adónde van los eventos de un trabajo: el canal del proceso aparte o la cola del
    ejecutor en hilo."""

    def send(self, event: JobEvent) -> None: ...


class StreamSink:
    """El canal del protocolo: cada evento, una línea JSON en UTF-8
    (:func:`~.protocol.encode_event`) escrita entera y vaciada al momento (``flush``), para
    que el lector del lanzador la reciba sin esperar. En el worker en proceso aparte es el
    stdout original duplicado (plan §5.4.3); vale un flujo binario o uno de texto (UTF-8 y
    «\\n»). Se puede usar desde varios hilos: las líneas no se mezclan. Un evento que no cabe
    en el canal (más de ``MAX_EVENT_BYTES``) es :class:`ValueError` y no se escribe nada."""

    def __init__(self, stream: IO[bytes] | IO[str]) -> None:
        self._stream = stream
        self._text = isinstance(stream, io.TextIOBase)
        self._lock = threading.Lock()

    def send(self, event: JobEvent) -> None:
        line = encode_event(event)
        data: bytes | str = line.decode("utf-8") if self._text else line
        with self._lock:
            self._stream.write(data)  # type: ignore[arg-type]
            self._stream.flush()


class QueueSink:
    """La cola del ejecutor en hilo: los eventos tal cual (:class:`~.protocol.JobEvent`),
    en orden, para que el lanzador los recoja al sondear (:meth:`drain`). Comprueba cada
    evento como el canal (:func:`~.protocol.encode_event`): lo que el canal no admite
    tampoco pasa por aquí (:class:`ValueError`), así los dos ejecutores se comportan igual."""

    def __init__(self, events: _EventQueue | None = None) -> None:
        """``events``: la cola que se llena (una nueva si falta)."""
        self.queue: _EventQueue = queue.SimpleQueue() if events is None else events

    def send(self, event: JobEvent) -> None:
        encode_event(event)
        self.queue.put(event)

    def drain(self) -> list[JobEvent]:
        """Los eventos que hay en la cola, en orden, sin esperar."""
        found: list[JobEvent] = []
        while True:
            try:
                found.append(self.queue.get_nowait())
            except queue.Empty:
                return found


# --- Contexto -----------------------------------------------------------------------------


class WorkerContext:
    """Lo que recibe la función de un trabajo, ``run(ctx) -> resumen`` (plan §5.3.1), en los
    dos ejecutores.

    ``request`` es la petición y ``job_dir`` su carpeta (un :class:`~.paths.JobDir` o su
    ruta, que tiene que ser la del ``job_uid`` de la petición: :class:`ValueError` si no).
    ``sink`` recibe los eventos (:class:`StreamSink` o :class:`QueueSink`); ``cancel_event``
    es el aviso del hilo del ejecutor en hilo (en proceso aparte, ``None``: basta el
    centinela). ``clock`` es el reloj monótono del límite de avances y de la mirada al
    centinela (las pruebas lo sustituyen). ``paths``: las rutas absolutas que el trabajo
    necesita fuera de su carpeta, por nombre (``JobRunner.submit(..., paths=…)``; en proceso
    aparte llegan por la línea de órdenes, ``--path``): :attr:`paths`.

    Sus métodos se pueden llamar desde varios hilos del cálculo.
    """

    def __init__(
        self,
        request: JobRequest,
        job_dir: JobDir | os.PathLike[str] | str,
        sink: EventSink,
        *,
        cancel_event: threading.Event | None = None,
        clock: Callable[[], float] = time.monotonic,
        paths: Mapping[str, str | os.PathLike[str]] | None = None,
    ) -> None:
        folder = job_dir if isinstance(job_dir, JobDir) else JobDir(Path(job_dir))
        if folder.job_uid != request.job_uid:
            raise ValueError(
                f"la carpeta {folder.job_uid} no es la del trabajo {request.job_uid}"
            )
        named: dict[str, Path] = {}
        for name, value in (paths or {}).items():
            if not isinstance(name, str) or not name or not isinstance(value, str | os.PathLike):
                raise ValueError(f"la ruta del trabajo {name!r} = {value!r} no vale")
            named[name] = Path(value)
        self._paths: Mapping[str, Path] = MappingProxyType(named)
        self._request = request
        self._job_dir = folder
        self._sink = sink
        self._cancel_event = cancel_event
        self._clock = clock
        self._lock = threading.RLock()
        self._last_progress_at: float | None = None
        self._held: tuple[float, str] | None = None
        self._last_sent_ts: float | None = None
        self._last_look_at: float | None = None
        self._cancelled = False
        self._outputs: dict[str, OutputRef] = {}

    @property
    def request(self) -> JobRequest:
        """La petición del trabajo."""
        return self._request

    @property
    def job_dir(self) -> JobDir:
        """La carpeta del trabajo."""
        return self._job_dir

    @property
    def paths(self) -> Mapping[str, Path]:
        """Las rutas absolutas del trabajo fuera de su carpeta, por nombre (solo lectura;
        vacío si no tiene)."""
        return self._paths

    @property
    def outputs(self) -> tuple[OutputRef, ...]:
        """Los resultados declarados con :meth:`add_output`, en el orden en que se declararon
        por primera vez (los del evento ``result``)."""
        with self._lock:
            return tuple(self._outputs.values())

    # --- Entradas y resultados --------------------------------------------------------

    def input_path(self, name: str) -> Path:
        """El fichero de la entrada ``name`` de la petición (``in/<name>.npy``…). Una entrada
        que la petición no declara, o declarada pero sin fichero, es :class:`JobFailed`
        ``request_invalid``, que nombra el trabajo y la entrada."""
        relative = self._request.inputs.get(name) if isinstance(name, str) else None
        if relative is None:
            raise self._invalid(f"no declara la entrada «{name}» que pide el cálculo")
        if not isinstance(relative, str) or _relative_problem(relative, INPUTS_DIR) is not None:
            raise self._invalid(f"la entrada «{name}» = {relative} no está dentro de "
                                f"{INPUTS_DIR}/")
        path = self._job_dir.path.joinpath(*relative.replace("\\", "/").split("/"))
        if not path.is_file():
            raise self._invalid(f"falta el fichero de la entrada «{name}» ({relative})")
        return path

    def output_path(self, filename: str | os.PathLike[str]) -> Path:
        """Dónde escribir el resultado ``filename`` (un nombre o una ruta relativa con «/» o
        «\\»): siempre dentro de ``out/`` de la carpeta del trabajo, cuyas subcarpetas crea.
        Lo que saldría de ``out/`` (``..``, absoluta, unidad, red, «:») o no es un nombre de
        fichero válido en Windows (vacío, reservado, con «.» o espacio al final, con
        ``<>"|?*``) es :class:`ValueError` y no se crea nada."""
        text = _as_text(filename)
        relative = None if text is None else OUTPUTS_DIR + "/" + text.replace("\\", "/")
        if relative is None or _relative_problem(relative, OUTPUTS_DIR) is not None or any(
            _reserved(part) for part in relative.split("/")
        ):
            raise ValueError(
                f"el resultado {filename!r} del trabajo {self._job_dir.job_uid} saldría de "
                f"{OUTPUTS_DIR}/ o no es un nombre de fichero válido: use un nombre o una ruta "
                f"relativa dentro de {OUTPUTS_DIR}/"
            )
        path = self._job_dir.path.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def add_output(self, path: str | os.PathLike[str], role: str) -> OutputRef:
        """Declara el resultado ``path`` (absoluto, o relativo a la carpeta del trabajo:
        ``"out/sum.npy"``) con su papel ``role`` para el módulo dueño, y devuelve su
        :class:`~.protocol.OutputRef` con la huella sha256 y el tamaño de lo que hay ahora en
        el fichero (RF-004-05; el lanzador lo comprobará antes de dar el trabajo por
        terminado). Un fichero fuera de ``out/`` o sin papel es :class:`ValueError`; uno que
        no existe, ``FileNotFoundError``; una carpeta, ``IsADirectoryError``. Declarar otra
        vez el mismo resultado (reescrito) deja la huella nueva en su sitio."""
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"el resultado {path} no tiene papel (role)")
        relative = self._relative_output(path)
        absolute = self._job_dir.path.joinpath(*relative.split("/"))
        if absolute.is_dir():
            raise IsADirectoryError(f"el resultado {relative} es una carpeta, no un fichero")
        if not absolute.is_file():
            raise FileNotFoundError(
                f"el resultado {relative} del trabajo {self._job_dir.job_uid} no existe"
            )
        digest, size = _sha256(absolute)
        ref = OutputRef(relative, digest, size, role)
        with self._lock:
            self._outputs[relative.casefold()] = ref
        return ref

    # --- Avance, registro y cancelación -------------------------------------------------

    def progress(self, frac: float, msg: str = "") -> None:
        """Avance ``frac`` (0–1; fuera, se acota) con su mensaje en español («Trozo 9 de
        20»); NaN o lo que no es un número es :class:`ValueError`. Como mucho 10 eventos por
        segundo: uno que llega antes de tiempo se retiene y sale después (siempre el más
        reciente; el último, al acabar). Después comprueba la cancelación
        (:meth:`check_cancelled`)."""
        checked = JobEvent.progress(frac, msg)  # comprueba frac y msg antes de nada
        with self._lock:
            now = self._clock()
            if self._due(now):
                self._held = None
                self._send_progress(checked.frac, checked.msg, now)
            else:
                self._held = (checked.frac, checked.msg)
        self.check_cancelled()

    def log(self, level: str, msg: str) -> None:
        """Una nota para el registro (``debug``, ``info``, ``warning`` o ``error``; otro
        nivel es :class:`ValueError`). No adelanta el avance retenido antes de tiempo."""
        event = JobEvent.log(level, msg)
        with self._lock:
            self._send_held_if_due()
            self._send(event)

    def check_cancelled(self) -> None:
        """:class:`JobCancelled` si se pidió parar el trabajo (RF-004-09): el aviso del hilo
        o el centinela ``cancel`` de su carpeta (mirado como mucho cada
        :data:`CANCEL_POLL_S` s). Envía además el avance retenido si ya toca."""
        if self._held is not None:
            with self._lock:
                self._send_held_if_due()
        if self._cancel_requested():
            raise JobCancelled(CANCELLED_TEXT)

    # --- Para los ejecutores --------------------------------------------------------------

    def flush(self) -> None:
        """Envía el avance retenido, si lo hay, sin esperar: el último avance llega siempre.
        Lo llama el ejecutor al acabar (también :meth:`emit`)."""
        with self._lock:
            if self._held is not None:
                frac, msg = self._held
                self._held = None
                self._send_progress(frac, msg, self._clock())

    def emit(self, event: JobEvent) -> JobEvent:
        """Envía un evento del ejecutor (``start``, ``result``, ``error``, ``cancelled``)
        por el mismo sumidero, después del avance retenido (:meth:`flush`), y devuelve el
        evento enviado: si se creó antes que el último enviado, sale con la hora de su envío
        (las horas del canal no retroceden)."""
        if not isinstance(event, JobEvent):
            raise TypeError(f"no es un evento: {type(event).__name__}")
        with self._lock:
            self.flush()
            return self._send(event)

    def finish(self, summary: Mapping[str, JsonValue] | None = None) -> JobEvent:
        """Cierra un trabajo que terminó bien (lo llama el ejecutor cuando vuelve ``run``):
        el evento ``result`` con los resultados declarados (:attr:`outputs`) y el resumen
        ``summary`` (JSON; ``None``, vacío), que deja antes en ``result.json`` de la carpeta
        del trabajo (UTF-8 sin BOM, sustituyendo de forma atómica) y envía después del último
        avance (:meth:`emit`). Lo devuelve. Un resumen que no es un objeto JSON, o un evento
        que no cabe en el canal, es :class:`ValueError` y no se escribe ni se envía nada
        (plan §5.2.1 y §5.4.3, paso 8)."""
        event = JobEvent.result(self.outputs, summary)  # comprueba el resumen
        encode_event(event)  # y que quepa en el canal, antes de escribir o enviar nada
        with self._lock:
            self.flush()
            event = self._stamped(event)
            text = json.dumps(event.to_json(), ensure_ascii=False, indent=2,
                              allow_nan=False)
            target = self._job_dir.result_file
            temporary = target.with_name(target.name + PARTIAL_SUFFIX)
            try:
                with temporary.open("w", encoding="utf-8", newline="\n",
                                    errors="backslashreplace") as handle:
                    handle.write(text + "\n")
                os.replace(temporary, target)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            return self._send(event)

    # --- Ayudas -------------------------------------------------------------------------

    def _due(self, now: float) -> bool:
        last = self._last_progress_at
        return last is None or now - last >= PROGRESS_INTERVAL_S

    def _stamped(self, event: JobEvent) -> JobEvent:
        """``event``, o una copia con la hora actual si se creó antes que el último enviado:
        las horas del canal no retroceden (RF-004-15: eventos en orden de llegada)."""
        last = self._last_sent_ts
        if last is None or event.ts >= last:
            return event
        return dataclasses.replace(event, ts=max(time.time(), last))

    def _send(self, event: JobEvent) -> JobEvent:
        """Envía ``event`` (con su hora corregida si hace falta, :meth:`_stamped`) y lo
        devuelve. Se llama con el cerrojo tomado."""
        event = self._stamped(event)
        self._sink.send(event)
        self._last_sent_ts = event.ts
        return event

    def _send_progress(self, frac: float, msg: str, now: float) -> None:
        # Con la hora del envío: las horas del canal no retroceden.
        self._send(JobEvent.progress(frac, msg))
        self._last_progress_at = now

    def _send_held_if_due(self) -> None:
        if self._held is not None:
            now = self._clock()
            if self._due(now):
                frac, msg = self._held
                self._held = None
                self._send_progress(frac, msg, now)

    def _cancel_requested(self) -> bool:
        if self._cancelled:
            return True
        event = self._cancel_event
        if event is not None and event.is_set():
            self._cancelled = True
            return True
        now = self._clock()
        last = self._last_look_at
        if last is None or now - last >= CANCEL_POLL_S:
            self._last_look_at = now
            if os.path.exists(self._job_dir.cancel_file):
                self._cancelled = True
        return self._cancelled

    def _relative_output(self, path: str | os.PathLike[str]) -> str:
        """``path`` como ruta relativa con «/» dentro de ``out/`` de la carpeta del trabajo;
        :class:`ValueError` si no lo está."""
        text = _as_text(path)
        if text is None:
            raise ValueError(f"el resultado {path!r} no es una ruta")
        base = Path(os.path.normpath(self._job_dir.path))
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = base / candidate
        try:
            relative = Path(os.path.normpath(candidate)).relative_to(base).as_posix()
        except ValueError:
            raise ValueError(
                f"el resultado {text} no está dentro de la carpeta del trabajo "
                f"{self._job_dir.job_uid}"
            ) from None
        if _relative_problem(relative, OUTPUTS_DIR) is not None:
            raise ValueError(
                f"el resultado {text} no está dentro de {OUTPUTS_DIR}/ de la carpeta del "
                f"trabajo {self._job_dir.job_uid}"
            )
        return relative

    def _invalid(self, detail: str) -> JobFailed:
        return JobFailed.from_error(JobError("request_invalid", job=self._job_name(),
                                             detail=detail))

    def _job_name(self) -> str:
        for candidate in (self._request.label, self._request.worker, self._request.job_uid):
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return "?"


def _as_text(value: object) -> str | None:
    """``value`` como texto si es un texto o una ruta de texto; si no, ``None``."""
    if isinstance(value, str):
        return value
    if isinstance(value, os.PathLike):
        inner = os.fspath(value)
        return inner if isinstance(inner, str) else None
    return None


def _reserved(part: str) -> bool:
    """Si ``part`` es un nombre reservado de Windows (``nul``, ``CON.txt``, ``com1``…)."""
    return part.split(".", 1)[0].strip().upper() in RESERVED_NAMES


def _sha256(path: Path) -> tuple[str, int]:
    """Huella sha256 y tamaño en bytes de lo leído de ``path``, por bloques."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(_HASH_BLOCK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size
