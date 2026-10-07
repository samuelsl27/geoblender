# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro del estado de los trabajos: ``state.json`` (spec 004; RF-004-12, RF-004-13,
RF-004-15; plan 004 §5.2.4, §5.3.1 y §5.4.5).

``state.json`` (esquema ``geoblender.job_state/1``) es el resumen de un trabajo que deja
Blender en su carpeta: tipo, nombre, dueño, proyecto y operación de origen, estado,
ejecutor, intérprete con las versiones de Python, numpy y BLAS, proceso, horas de cola,
inicio y fin (UTC ISO 8601), duración en s, código de salida, error (código, ``msgid``,
valores y texto en español), cancelación, resultados con su huella, último evento e
incorporación. El registro completo lo forman además ``request.json``, ``events.jsonl`` y
``job.log`` (RF-004-15).

- :class:`JobRecord` y sus partes (:class:`InterpreterInfo`, :class:`ErrorInfo`,
  :class:`CancelInfo`), siempre válidos: se comprueban al crearlos (:class:`ValueError`).
- :func:`write_record`: escritura atómica (temporal, ``fsync`` y ``os.replace``; si otro
  programa tiene el fichero abierto, reintenta): un corte deja el estado anterior intacto.
  **Sin rutas absolutas**, porque la carpeta de trabajos puede estar dentro del proyecto
  (plan §5.2.4): cada ruta absoluta de un texto queda en su último nombre
  (:func:`without_absolute_paths`).
- :func:`read_record` y :func:`scan`: leen sin escribir; un ``state.json`` que falta no
  cuenta, y uno ilegible tampoco (con un aviso en el registro de Python).
- :func:`mark_interrupted` (al abrir un proyecto, RF-004-13): lo que su ``state.json`` deja
  «En cola» o «En curso» y no está en el lanzador lo dejó así un Blender que se cayó; queda
  «Interrumpido» con la hora de su último evento.

Solo escribe Blender (el lanzador); el worker nunca toca ``state.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..core.timeutil import format_utc, parse_utc
from .messages import JobError
from .paths import EVENTS_FILE, LOG_FILE
from .protocol import (
    JOB_UID_PATTERN,
    MAX_EVENT_BYTES,
    WORKER_NAME_PATTERN,
    JobEvent,
    JobFolder,
    JobRequest,
    JsonValue,
    OutputRef,
    folder_path,
    plain_json,
)

LOGGER = logging.getLogger("geoblender.jobs")

RECORD_SCHEMA = "geoblender.job_state/1"
RECORD_FILE = "state.json"
NOTE_KEY = "note"
"""Clave de las notas del lanzador en ``events.jsonl`` (los eventos llevan ``v`` y ``t``)."""
LOG_PREFIX = "Geoblender (lanzador):"
"""Comienzo de las líneas que el lanzador añade a ``job.log`` al finalizar un trabajo."""
EVENTS_TAIL_BYTES = 2 * MAX_EVENT_BYTES
"""Lo que se lee del final de ``events.jsonl`` para buscar su último evento: cabe entera la
línea más larga que admite el protocolo."""

JOB_STATES: tuple[str, ...] = (
    "queued", "running", "succeeded", "failed", "cancelled", "timed_out", "interrupted",
)
"""Estados de un trabajo: En cola, En curso, Terminado, Fallido, Cancelado, Tiempo agotado
e Interrumpido."""
ACTIVE_STATES: frozenset[str] = frozenset({"queued", "running"})
FINAL_STATES: frozenset[str] = frozenset(JOB_STATES) - ACTIVE_STATES
EXECUTORS: tuple[str, ...] = ("inprocess", "subprocess")
INTERPRETER_KINDS: tuple[str, ...] = ("blender", "compute", "external")
CANCEL_REASONS: tuple[str, ...] = ("user", "timeout", "shutdown")

ELIDED = "…"
"""Lo que sustituye a la parte de una ruta absoluta que no se guarda."""

_REPLACE_ATTEMPTS = 5
_REPLACE_PAUSE_S = 0.02

_RECORD_FIELDS: tuple[str, ...] = (
    "schema", "job_uid", "worker", "label", "owner", "project_uid", "operation_uid", "state",
    "executor", "interpreter", "pid", "queued_at", "started_at", "ended_at", "duration_s",
    "exit_code", "error", "cancel", "outputs", "last_event_at", "ingested_at",
)
_INTERPRETER_FIELDS: tuple[str, ...] = ("kind", "python", "numpy", "blas", "lock_id")
_ERROR_FIELDS: tuple[str, ...] = ("code", "msgid", "values", "text")
_CANCEL_FIELDS: tuple[str, ...] = ("requested_at", "reason", "forced")


@dataclass(frozen=True, slots=True, kw_only=True)
class InterpreterInfo:
    """El intérprete que ejecutó el trabajo: ``kind`` (``blender``, ``compute`` o
    ``external``) y las versiones de Python, numpy y BLAS y el ``lock_id`` del motor de
    cálculo (``None`` si no se conocen o no aplican)."""

    kind: str
    python: str | None = None
    numpy: str | None = None
    blas: str | None = None
    lock_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in INTERPRETER_KINDS:
            raise ValueError(
                f"el tipo de intérprete {_shown(self.kind)} no es uno de "
                f"{', '.join(INTERPRETER_KINDS)}"
            )
        for name in _INTERPRETER_FIELDS[1:]:
            _check_optional_text(getattr(self, name), f"interpreter.{name}")

    def to_json(self) -> dict[str, JsonValue]:
        return {name: getattr(self, name) for name in _INTERPRETER_FIELDS}

    @classmethod
    def from_json(cls, data: object) -> InterpreterInfo:
        return cls(**_fields(data, _INTERPRETER_FIELDS, "interpreter"))


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorInfo:
    """El error de un trabajo «Fallido» (RF-004-12): ``code`` del §8 de la spec (o el
    propio del cálculo), ``msgid`` en inglés, ``values`` (JSON) y ``text`` en español."""

    code: str
    msgid: str
    values: Mapping[str, JsonValue] = field(default_factory=dict)
    text: str

    def __post_init__(self) -> None:
        for name in ("code", "msgid", "text"):
            if not _filled(getattr(self, name)):
                raise ValueError(f"error.{name} {_shown(getattr(self, name))} está vacío")
        if not isinstance(self.values, Mapping):
            raise ValueError(f"error.values no es un objeto JSON ({_shown(self.values)})")
        object.__setattr__(self, "values", plain_json(self.values, "error.values"))

    @classmethod
    def from_job_error(cls, error: JobError) -> ErrorInfo:
        """El error de un :class:`~.messages.JobError` (código, ``msgid``, valores y texto
        en español)."""
        return cls(code=error.code, msgid=error.msgid, values=error.values, text=error.text)

    def to_json(self) -> dict[str, JsonValue]:
        return {"code": self.code, "msgid": self.msgid,
                "values": plain_json(self.values, "error.values"), "text": self.text}

    @classmethod
    def from_json(cls, data: object) -> ErrorInfo:
        return cls(**_fields(data, _ERROR_FIELDS, "error"))


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelInfo:
    """La cancelación de un trabajo: hora en que se pidió (UTC), motivo (``user``,
    ``timeout`` o ``shutdown``) y si hubo que terminar el proceso (``forced``,
    RF-004-10)."""

    requested_at: str
    reason: str
    forced: bool = False

    def __post_init__(self) -> None:
        _check_time(self.requested_at, "cancel.requested_at", optional=False)
        if not isinstance(self.reason, str) or self.reason not in CANCEL_REASONS:
            raise ValueError(
                f"el motivo de cancelación {_shown(self.reason)} no es uno de "
                f"{', '.join(CANCEL_REASONS)}"
            )
        if not isinstance(self.forced, bool):
            raise ValueError(f"cancel.forced {_shown(self.forced)} no es verdadero ni falso")

    def to_json(self) -> dict[str, JsonValue]:
        return {"requested_at": self.requested_at, "reason": self.reason,
                "forced": self.forced}

    @classmethod
    def from_json(cls, data: object) -> CancelInfo:
        return cls(**_fields(data, _CANCEL_FIELDS, "cancel"))


@dataclass(frozen=True, slots=True, kw_only=True)
class JobRecord:
    """El estado de un trabajo (``state.json``, ``geoblender.job_state/1``, plan §5.2.4).

    Las horas son textos UTC ISO 8601 con «Z» (``core.timeutil.format_utc``); la duración,
    en s. ``outputs`` son los resultados verificados (:class:`~.protocol.OutputRef`).
    Ningún campo es una ruta absoluta.
    """

    job_uid: str
    worker: str
    label: str
    owner: str
    project_uid: str | None = None
    operation_uid: str | None = None
    state: str = "queued"
    executor: str
    interpreter: InterpreterInfo | None = None
    pid: int | None = None
    queued_at: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float | None = None
    exit_code: int | None = None
    error: ErrorInfo | None = None
    cancel: CancelInfo | None = None
    outputs: tuple[OutputRef, ...] = ()
    last_event_at: str | None = None
    ingested_at: str | None = None
    schema: str = RECORD_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RECORD_SCHEMA:
            raise ValueError(f"el esquema {_shown(self.schema)} no es «{RECORD_SCHEMA}»")
        if not isinstance(self.job_uid, str) or not JOB_UID_PATTERN.fullmatch(self.job_uid):
            raise ValueError(
                f"el identificador {_shown(self.job_uid)} no es AAAAMMDD_HHMMSS_xxxxxx"
            )
        if not isinstance(self.worker, str) or not WORKER_NAME_PATTERN.fullmatch(self.worker):
            raise ValueError(f"el tipo de trabajo {_shown(self.worker)} no es válido")
        for name in ("label", "owner"):
            if not _filled(getattr(self, name)):
                raise ValueError(f"{name} {_shown(getattr(self, name))} está vacío")
        for name in ("project_uid", "operation_uid"):
            value = getattr(self, name)
            if value is not None and not _filled(value):
                raise ValueError(f"{name} {_shown(value)} no es un texto ni vacío")
        _check_choice(self.state, JOB_STATES, "el estado")
        _check_choice(self.executor, EXECUTORS, "el ejecutor")
        _check_instance(self.interpreter, InterpreterInfo, "interpreter")
        if self.pid is not None and (not _is_int(self.pid) or self.pid <= 0):
            raise ValueError(f"pid {_shown(self.pid)} no es un número de proceso")
        _check_time(self.queued_at, "queued_at", optional=False)
        for name in ("started_at", "ended_at", "last_event_at", "ingested_at"):
            _check_time(getattr(self, name), name)
        if self.duration_s is not None:
            if not _is_number(self.duration_s) or not math.isfinite(self.duration_s) or (
                self.duration_s < 0
            ):
                raise ValueError(f"duration_s {_shown(self.duration_s)} no es una duración")
            object.__setattr__(self, "duration_s", float(self.duration_s))
        if self.exit_code is not None and not _is_int(self.exit_code):
            raise ValueError(f"exit_code {_shown(self.exit_code)} no es un entero")
        _check_instance(self.error, ErrorInfo, "error")
        _check_instance(self.cancel, CancelInfo, "cancel")
        if not isinstance(self.outputs, list | tuple) or not all(
            isinstance(item, OutputRef) for item in self.outputs
        ):
            raise ValueError("outputs no es una lista de OutputRef")
        object.__setattr__(self, "outputs", tuple(self.outputs))

    @property
    def is_active(self) -> bool:
        """En cola o en curso."""
        return self.state in ACTIVE_STATES

    @property
    def is_final(self) -> bool:
        """Terminado, fallido, cancelado, con el tiempo agotado o interrumpido."""
        return self.state in FINAL_STATES

    @classmethod
    def from_request(
        cls, request: JobRequest, *, executor: str, queued_at: dt.datetime | None = None
    ) -> JobRecord:
        """El registro de un trabajo que entra en la cola: de la petición, el
        identificador, el tipo, el nombre, el dueño, el proyecto y la operación; la hora de
        entrada, ``queued_at`` (UTC; la actual si falta)."""
        moment = dt.datetime.now(dt.UTC) if queued_at is None else queued_at
        return cls(
            job_uid=request.job_uid,
            worker=request.worker,
            label=request.label,
            owner=request.owner,
            project_uid=request.project_uid,
            operation_uid=request.operation_uid,
            state="queued",
            executor=executor,
            queued_at=format_utc(moment),
        )

    def to_json(self) -> dict[str, JsonValue]:
        """La forma JSON del registro, con las claves en el orden de plan §5.2.4."""
        data: dict[str, JsonValue] = {}
        for name in _RECORD_FIELDS:
            value = getattr(self, name)
            if isinstance(value, InterpreterInfo | ErrorInfo | CancelInfo):
                value = value.to_json()
            elif name == "outputs":
                value = [output.to_json() for output in value]
            data[name] = value
        return data

    @classmethod
    def from_json(cls, data: object) -> JobRecord:
        """El registro de su forma JSON; :class:`ValueError` si no es un objeto, le sobra o
        le falta un campo, o no cumple."""
        values = _fields(data, _RECORD_FIELDS, "state.json")
        for name, part in (("interpreter", InterpreterInfo), ("error", ErrorInfo),
                           ("cancel", CancelInfo)):
            if values[name] is not None:
                values[name] = part.from_json(values[name])
        outputs = values["outputs"]
        if not isinstance(outputs, list):
            raise ValueError(f"outputs no es una lista ({_shown(outputs)})")
        values["outputs"] = tuple(OutputRef.from_json(item) for item in outputs)
        return cls(**values)


def write_record(job_dir: JobFolder, record: JobRecord) -> None:
    """Escribe ``state.json`` en la carpeta del trabajo (que ya existe y se llama como su
    ``job_uid``; si no, :class:`ValueError`, o el ``OSError`` de no poder escribir), en
    UTF-8 sin BOM con LF, sin rutas absolutas (:func:`without_absolute_paths`), de forma
    atómica: ``state.json.tmp``, ``fsync`` y ``os.replace``, reintentando unas veces si otro
    programa tiene abierto el fichero. Si algo falla, el estado anterior queda intacto, se
    borra el temporal y se lanza el error."""
    if not isinstance(record, JobRecord):
        raise ValueError(f"no es un registro de trabajo: {type(record).__name__}")
    folder = folder_path(job_dir)
    if folder.name != record.job_uid:
        raise ValueError(
            f"la carpeta {folder.name} no es la del trabajo {record.job_uid}: el registro "
            "va en la carpeta de su trabajo"
        )
    data = without_absolute_paths(record.to_json())
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        payload = text.encode("utf-8")
    except UnicodeEncodeError:
        payload = (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("ascii")
    target = folder / RECORD_FILE
    temporary = folder / f"{RECORD_FILE}.tmp"
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_record(job_dir: JobFolder) -> JobRecord | None:
    """El registro de ``state.json`` de la carpeta del trabajo, o ``None`` si no existe. Uno
    que no se puede leer, no es JSON en UTF-8 sin BOM, no es un registro válido o es de otro
    trabajo tampoco cuenta (``None``) y deja un aviso en el registro de Python. No escribe
    nada."""
    folder = folder_path(job_dir)
    path = folder / RECORD_FILE
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        LOGGER.warning("No se puede leer %s del trabajo %s: %s", RECORD_FILE, folder.name,
                       exc.strerror or exc)
        return None
    try:
        record = JobRecord.from_json(json.loads(raw.decode("utf-8"),
                                                parse_constant=_reject_constant))
    except (ValueError, TypeError, RecursionError) as exc:
        LOGGER.warning("El %s del trabajo %s no es válido y no cuenta: %s", RECORD_FILE,
                       folder.name, exc)
        return None
    if record.job_uid != folder.name:
        LOGGER.warning("El %s de la carpeta %s es del trabajo %s y no cuenta", RECORD_FILE,
                       folder.name, record.job_uid)
        return None
    return record


def scan(jobs_root: Path) -> list[JobRecord]:
    """Los registros de la raíz de trabajos, por identificador (es decir, por fecha de
    creación): los de las carpetas ``AAAAMMDD_HHMMSS_xxxxxx`` con un ``state.json`` válido
    (:func:`read_record`). Una raíz que no existe no tiene ninguno. No escribe nada."""
    try:
        entries = sorted(Path(jobs_root).iterdir(), key=lambda entry: entry.name)
    except (FileNotFoundError, NotADirectoryError):
        return []
    found: list[JobRecord] = []
    for entry in entries:
        if not JOB_UID_PATTERN.fullmatch(entry.name) or not entry.is_dir():
            continue
        record = read_record(entry)
        if record is not None:
            found.append(record)
    return found


def mark_interrupted(jobs_root: Path, *, active_uids: Iterable[str]) -> list[str]:
    """Al abrir un proyecto (plan §5.4.5; RF-004-13): deja «Interrumpido»
    (``job_interrupted``) cada trabajo de ``jobs_root`` cuyo ``state.json`` dice «En cola» o
    «En curso» y que no está entre ``active_uids`` (los que lleva el lanzador): lo dejó así
    un Blender que se cayó. Devuelve sus identificadores, por orden.

    Con su último evento: ``last_event_at`` pasa a ser la hora del último evento de su
    ``events.jsonl`` (si es posterior a la que tenía), y el trabajo termina (``ended_at``) en
    lo último que se sabe de él: la última línea con hora de ``events.jsonl`` (evento o nota
    del lanzador) o, sin ella, su inicio o su entrada en la cola. Su duración va desde el
    inicio hasta ahí (vacía si no llegó a arrancar), sin código de salida; la cancelación
    que tuviera se conserva. Se añade al registro la nota final en ``events.jsonl`` y una
    línea en ``job.log``. Un trabajo cuyo ``state.json`` no se puede escribir se queda como
    estaba (con un aviso en el registro de Python) y no se devuelve.

    ``active_uids``: colección de textos (:class:`TypeError` si es un texto suelto o lleva
    otra cosa). Una raíz que no existe no tiene nada que marcar."""
    active = as_uid_set(active_uids, "active_uids")
    root = Path(jobs_root)
    marked: list[str] = []
    for record in scan(root):
        if not record.is_active or record.job_uid in active:
            continue
        folder = root / record.job_uid
        last_event, last_line = _last_times(folder / EVENTS_FILE)
        known = [parse_utc(text) for text in (record.queued_at, record.started_at,
                                              record.last_event_at) if text is not None]
        ended = max([*known, *(t for t in (last_event, last_line) if t is not None)])
        last_event_at = record.last_event_at
        if last_event is not None and (
            last_event_at is None or last_event > parse_utc(last_event_at)
        ):
            last_event_at = format_utc(last_event)
        duration = (None if record.started_at is None
                    else max(0.0, (ended - parse_utc(record.started_at)).total_seconds()))
        error = ErrorInfo.from_job_error(JobError("job_interrupted", job=record.label))
        interrupted = replace(
            record, state="interrupted", ended_at=format_utc(ended), duration_s=duration,
            exit_code=None, error=error, last_event_at=last_event_at,
        )
        try:
            write_record(folder, interrupted)
        except (OSError, ValueError) as exc:
            LOGGER.warning("No se pudo dejar «Interrumpido» el trabajo %s: %s",
                           record.job_uid, exc)
            continue
        _append_line(folder / EVENTS_FILE, (json.dumps(
            {NOTE_KEY: "finished", "ts": time.time(), "state": "interrupted",
             "exit_code": None, "error": error.code, "orphan": True},
            ensure_ascii=False,
        ) + "\n").encode("utf-8"))
        before = "«En curso»" if record.state == "running" else "«En cola»"
        _append_line(folder / LOG_FILE, (
            f"{LOG_PREFIX} el trabajo termina «Interrumpido» (sin proceso): constaba "
            f"{before} y Blender se cerró sin finalizarlo; se marcó al abrir el proyecto: "
            f"{error.text}\n"
        ).encode("utf-8"))
        marked.append(record.job_uid)
    return marked


def as_uid_set(values: Iterable[str], what: str = "los identificadores") -> frozenset[str]:
    """Los identificadores de trabajo de ``values`` (una colección de textos) como conjunto;
    :class:`TypeError` si ``values`` es un texto suelto (se iterarían sus letras) o lleva
    algo que no es un texto. ``what`` nombra el argumento en el error."""
    if isinstance(values, str | bytes) or not isinstance(values, Iterable):
        raise TypeError(f"{what} debe ser una colección de identificadores, no "
                        f"{type(values).__name__}")
    found = frozenset(values)
    wrong = [value for value in found if not isinstance(value, str)]
    if wrong:
        raise TypeError(f"{what} lleva valores que no son identificadores: {wrong[0]!r}")
    return found


def _last_times(path: Path) -> tuple[dt.datetime | None, dt.datetime | None]:
    """La hora del último evento de ``events.jsonl`` y la de su última línea con hora
    (evento o nota del lanzador), leyendo solo su final (:data:`EVENTS_TAIL_BYTES`). Las
    líneas rotas, las que no son JSON y las horas que no valen no cuentan; un fichero que
    falta o no se puede leer no tiene ninguna."""
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - EVENTS_TAIL_BYTES)
            stream.seek(start)
            tail = stream.read()
    except OSError:
        return None, None
    lines = tail.split(b"\n")
    if start > 0:
        lines = lines[1:]  # la primera puede estar cortada
    last_event: dt.datetime | None = None
    last_line: dt.datetime | None = None
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            continue
        if not isinstance(data, dict):
            continue
        if NOTE_KEY in data:
            moment = _moment(data.get("ts"))
        else:
            try:
                moment = _moment(JobEvent.from_json(data).ts)
            except (ValueError, TypeError, RecursionError):
                continue
            if moment is not None and last_event is None:
                last_event = moment
        if moment is not None and last_line is None:
            last_line = moment
        if last_event is not None:
            break  # las notas anteriores al último evento ya no cambian nada
    return last_event, last_line


def _moment(ts: object) -> dt.datetime | None:
    """La hora UTC de ``ts`` (segundos desde 1970), o ``None`` si no es una hora."""
    if not _is_number(ts) or not math.isfinite(ts):
        return None
    try:
        return dt.datetime.fromtimestamp(ts, dt.UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _append_line(path: Path, line: bytes) -> None:
    """Añade ``line`` al final de ``path`` en su propia línea (si el fichero quedó cortado
    sin «\\n», primero lo cierra); si no se puede, solo un aviso en el registro de
    Python."""
    try:
        with path.open("a+b") as stream:
            size = stream.seek(0, os.SEEK_END)
            if size:
                stream.seek(size - 1)
                if stream.read(1) != b"\n":
                    line = b"\n" + line
            stream.seek(0, os.SEEK_END)
            stream.write(line)
    except OSError as exc:
        LOGGER.warning("No se pudo completar %s: %s", path.name, exc.strerror or exc)


# --- Sin rutas absolutas ----------------------------------------------------------------

# Un nombre de una ruta de Windows (sin separadores, espacios ni los caracteres que Windows
# no admite; las comillas latinas cierran una ruta citada en un mensaje).
_NAME = r"[^\\/\s:*?\"<>|«»]+"
# La raíz de una ruta absoluta: una unidad (``C:\``, también tras ``\\?\``) o un servidor
# de red (``\\nas``, ``\\?\UNC\nas``); no la «//» de una URL (``https://``).
_ROOT = (
    r"(?<![A-Za-z0-9])(?:[\\/]{2}[?.][\\/])?[A-Za-z]:(?=[\\/])"
    rf"|(?<![:\w\\/])[\\/]{{2}}(?:[?.][\\/](?:UNC[\\/])?)?{_NAME}"
)
_ROOT_PATTERN = re.compile(_ROOT, re.IGNORECASE)
# En un texto, una ruta acaba en el primer espacio: nunca se come las palabras de detrás.
_ABSOLUTE_PATH = re.compile(rf"(?:{_ROOT})(?:[\\/]+{_NAME})*[\\/]*", re.IGNORECASE)
# Un texto que es entero una ruta absoluta, con espacios dentro de sus nombres.
_WHOLE_PATH = re.compile(rf"(?:{_ROOT})(?:[\\/]+[^\\/:*?\"<>|\r\n]*)*", re.IGNORECASE)


def without_absolute_paths(data: JsonValue) -> JsonValue:
    """Copia de ``data`` (JSON) sin rutas absolutas de Windows en sus textos (las claves no
    se tocan): cada una queda en su último nombre tras «…» (``…\\python.exe``; ``…`` si no
    tiene nombre). Un texto que es entero una ruta conserva su último nombre aunque tenga
    espacios, y donde aparece dentro de otro texto se sustituye igual; en lo demás, una
    ruta acaba en el primer espacio. Las rutas relativas y las URL quedan tal cual."""
    wholes: dict[str, str] = {}
    for text in _strings(data):
        candidate = text.strip()
        if _WHOLE_PATH.fullmatch(candidate):
            wholes[candidate] = _elide(candidate)
    ordered = sorted(wholes, key=len, reverse=True)

    def clean(text: str) -> str:
        for original in ordered:
            if original in text:
                text = text.replace(original, wholes[original])
        return _ABSOLUTE_PATH.sub(lambda match: _elide(match.group(0)), text)

    return _map_strings(data, clean)


def _elide(path: str) -> str:
    """``…\\<último nombre>`` de una ruta absoluta (con su separador)."""
    root = _ROOT_PATTERN.match(path)
    rest = path[root.end():] if root else path
    names = [name for name in re.split(r"[\\/]+", rest) if name]
    if not names:
        return ELIDED
    separator = "/" if "/" in rest and "\\" not in rest else "\\"
    return f"{ELIDED}{separator}{names[-1]}"


def _strings(data: JsonValue) -> Iterator[str]:
    stack: list[JsonValue] = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _map_strings(data: JsonValue, change: Callable[[str], str]) -> JsonValue:
    if isinstance(data, str):
        return change(data)
    if isinstance(data, dict):
        return {key: _map_strings(value, change) for key, value in data.items()}
    if isinstance(data, list):
        return [_map_strings(value, change) for value in data]
    return data


# --- Ayudas -----------------------------------------------------------------------------


def _replace(source: Path, target: Path) -> None:
    """``os.replace`` con unos reintentos si Windows no deja sustituir ``target`` porque
    otro programa (un antivirus, un lector) lo tiene abierto."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_PAUSE_S)


def _fields(data: object, names: tuple[str, ...], where: str) -> dict[str, object]:
    """Los campos ``names`` de ``data`` (un objeto JSON con esos campos y ninguno más)."""
    if not isinstance(data, Mapping):
        raise ValueError(f"{where} no es un objeto JSON ({_shown(data)})")
    missing = [name for name in names if name not in data]
    extra = sorted(str(name) for name in data if name not in names)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"falta{'n' if len(missing) > 1 else ''} {', '.join(missing)}")
        if extra:
            parts.append(f"sobra{'n' if len(extra) > 1 else ''} {', '.join(extra)}")
        raise ValueError(f"{where}: {'; '.join(parts)}")
    return {name: data[name] for name in names}


def _check_time(value: object, name: str, *, optional: bool = True) -> None:
    if value is None and optional:
        return
    try:
        parse_utc(value)  # type: ignore[arg-type]
    except ValueError:
        raise ValueError(f"{name} {_shown(value)} no es una hora UTC ISO 8601 con «Z»") from None


def _check_choice(value: object, choices: tuple[str, ...], what: str) -> None:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{what} {_shown(value)} no es uno de {', '.join(choices)}")


def _check_instance(value: object, kind: type, name: str) -> None:
    if value is not None and not isinstance(value, kind):
        raise ValueError(f"{name} no es un {kind.__name__} ({_shown(value)})")


def _check_optional_text(value: object, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} {_shown(value)} no es un texto")


def _filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _shown(value: object) -> str:
    if isinstance(value, str):
        return f"«{value}»"
    return repr(value)


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} no es JSON")
