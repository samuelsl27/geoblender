# SPDX-License-Identifier: GPL-3.0-or-later
"""Cerrojo de un solo escritor, ``.lock`` (spec 002; RF-002-04, RF-002-09; ADR-0006,
ADR-0010; formato-proyecto §5.2; plan 002 §5.4 y §6).

Un proyecto lo escribe una sola sesión de Geoblender: la que tiene ``.lock``, un JSON sin
rutas con su sesión, equipo, usuario, proceso, hora de inicio, última marca de actividad,
versión de Geoblender y modo (``network``, ``local`` o ``checkout``).

- :func:`inspect` (no escribe): sin fichero → ``FREE``; de esta sesión → ``OURS``; del
  mismo equipo con el proceso ya terminado → ``ORPHAN`` (Blender se cerró de golpe); si
  no, ``ACTIVE``. Un ``.lock`` que existe pero no se puede leer o no es JSON válido (otro
  equipo puede estar escribiéndolo) se relee 3 veces cada 100 ms y, si sigue así, es
  ``ACTIVE`` de titular desconocido: **nunca** ``FREE`` ni ``ORPHAN``.
- :func:`acquire`: creación **exclusiva** (``os.open`` con ``O_CREAT | O_EXCL``, atómica
  también sobre SMB), JSON, ``fsync`` y relectura de comprobación. Un huérfano se borra
  solo si su contenido no cambió desde que se leyó, y se reintenta; el anterior se
  devuelve para registrarlo (evento ``lock_orphan_replaced``). Con otra sesión activa,
  :class:`LockError` con su equipo, usuario y hora.
- :func:`release`: solo borra el cerrojo de esta sesión.

No se usan los bloqueos de SQLite ni ``msvcrt.locking``: no son fiables entre clientes
SMB y quedan colgados tras un cierre brusco (plan 002 §6). Las horas, en UTC (el margen
del umbral cubre los desfases de reloj entre equipos). El contenido se rellena con
espacios hasta una longitud fija (:data:`LOCK_SIZE`) para que la marca de actividad se
pueda reescribir en el sitio sin truncar antes.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..errors import LockError
from ..sysinfo import SessionInfo, pid_alive
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc, parse_utc

LOCK_FILE = ".lock"
LOCK_SIZE = 1024  # bytes: el JSON se rellena con espacios hasta aquí
REREADS = 3  # relecturas de un .lock ilegible
REREAD_INTERVAL_S = 0.1
ACQUIRE_ATTEMPTS = 3
REMOVE_ATTEMPTS = 5  # Windows no deja borrar un fichero que otro proceso está leyendo
REMOVE_INTERVAL_S = 0.05
_FIELDS = (
    "session_uid",
    "host",
    "user",
    "pid",
    "started_at",
    "heartbeat_at",
    "geoblender_version",
    "mode",
)

PidAlive = Callable[[int], bool]


class LockMode(Enum):
    """Para qué tiene la sesión el cerrojo."""

    NETWORK = "network"  # escritura directa en una carpeta de red
    LOCAL = "local"  # escritura en disco local (o en una copia local)
    CHECKOUT = "checkout"  # reserva del original para una copia local


class LockState(Enum):
    """Estado del cerrojo visto por una sesión."""

    FREE = "free"
    OURS = "ours"
    ORPHAN = "orphan"
    ACTIVE = "active"


@dataclass(frozen=True)
class LockInfo:
    """El contenido de ``.lock`` (formato-proyecto §5.2)."""

    session_uid: str
    host: str
    user: str
    pid: int
    started_at: str
    heartbeat_at: str
    geoblender_version: str
    mode: LockMode

    @classmethod
    def new(cls, session: SessionInfo, mode: LockMode, clock: Clock = SYSTEM_CLOCK) -> LockInfo:
        """El cerrojo que pondría ``session`` ahora."""
        now = format_utc(clock.now())
        return cls(
            session.session_uid,
            session.host,
            session.user,
            session.pid,
            now,
            now,
            session.geoblender_version,
            mode,
        )

    def to_dict(self) -> dict[str, Any]:
        """El JSON del cerrojo (sin rutas)."""
        return {
            "session_uid": self.session_uid,
            "host": self.host,
            "user": self.user,
            "pid": self.pid,
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            "geoblender_version": self.geoblender_version,
            "mode": self.mode.value,
        }

    @classmethod
    def from_dict(cls, data: object) -> LockInfo:
        """El cerrojo de un JSON leído; ``ValueError`` si no tiene la forma esperada."""
        if not isinstance(data, Mapping) or set(_FIELDS) - set(data):
            raise ValueError("al cerrojo le faltan campos")
        texts = [data[name] for name in _FIELDS if name != "pid"]
        pid = data["pid"]
        if not all(isinstance(value, str) and value for value in texts):
            raise ValueError("el cerrojo tiene un campo de texto vacío o no textual")
        if not isinstance(pid, int) or isinstance(pid, bool):
            raise ValueError("el PID del cerrojo no es un entero")
        parse_utc(data["started_at"])
        parse_utc(data["heartbeat_at"])
        return cls(
            str(data["session_uid"]),
            str(data["host"]),
            str(data["user"]),
            pid,
            str(data["started_at"]),
            str(data["heartbeat_at"]),
            str(data["geoblender_version"]),
            LockMode(data["mode"]),
        )

    def same_host(self, session: SessionInfo) -> bool:
        """Verdadero si el cerrojo es de este equipo (sin distinguir mayúsculas)."""
        return self.host.casefold() == session.host.casefold()


def _local_time(text: str) -> str:
    try:
        moment = parse_utc(text)
    except ValueError:
        return text
    return moment.astimezone().strftime("%d/%m/%Y %H:%M")


@dataclass(frozen=True)
class LockStatus:
    """Lo que :func:`inspect` vio: el estado, el titular (``None`` si no hay cerrojo o
    no se puede leer) y los bytes leídos (para no sustituir nunca un cerrojo distinto del
    que se vio)."""

    state: LockState
    holder: LockInfo | None
    content: bytes | None

    @property
    def unknown_holder(self) -> bool:
        """Verdadero si hay un ``.lock`` que no se puede leer."""
        return self.content is not None and self.holder is None

    def describe(self) -> str:
        """Quién tiene el cerrojo, en español (hora local)."""
        if self.state is LockState.FREE:
            return "nadie tiene el proyecto abierto en escritura"
        if self.holder is None:
            return (
                "lo tiene una sesión de titular desconocido (el fichero .lock no se puede "
                "leer: puede estar escribiéndolo otro equipo)"
            )
        holder = self.holder
        return (
            f"lo tiene {holder.user} en {holder.host} desde {_local_time(holder.started_at)} "
            f"(última actividad {_local_time(holder.heartbeat_at)})"
        )


@dataclass(frozen=True)
class Acquired:
    """Resultado de :func:`acquire`: el cerrojo puesto y, si se sustituyó un huérfano,
    el anterior (para el evento ``lock_orphan_replaced``)."""

    info: LockInfo
    replaced: LockInfo | None = None


def lock_path(root: Path) -> Path:
    """``<proyecto>/.lock``."""
    return Path(root) / LOCK_FILE


def encode_lock(info: LockInfo) -> bytes:
    """El cerrojo en UTF-8, rellenado con espacios hasta :data:`LOCK_SIZE` (más largo si
    el contenido no cabe) y con un salto de línea final."""
    payload = json.dumps(info.to_dict(), ensure_ascii=False).encode("utf-8")
    padding = max(LOCK_SIZE - len(payload) - 1, 0)
    return payload + b" " * padding + b"\n"


def decode_lock(content: bytes) -> LockInfo:
    """El cerrojo de unos bytes leídos; ``ValueError`` si no es un cerrojo válido."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("el cerrojo no es UTF-8") from exc
    if not text.strip():
        raise ValueError("el cerrojo está vacío")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"el cerrojo no es JSON válido ({exc})") from exc
    return LockInfo.from_dict(data)


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except PermissionError:
        return b""  # otro proceso lo tiene abierto en exclusiva: ilegible por ahora


def read_lock(root: Path, *, clock: Clock = SYSTEM_CLOCK) -> tuple[bytes | None, LockInfo | None]:
    """Los bytes y el titular de ``.lock``: ``(None, None)`` si no existe; ``(bytes,
    None)`` si sigue ilegible tras :data:`REREADS` relecturas cada
    :data:`REREAD_INTERVAL_S` s."""
    path = lock_path(root)
    content = _read_bytes(path)
    rereads = 0
    while content is not None:
        try:
            return content, decode_lock(content)
        except ValueError:
            if rereads == REREADS:
                return content, None
        rereads += 1
        clock.sleep(REREAD_INTERVAL_S)
        content = _read_bytes(path)
    return None, None


def read_holder(root: Path, *, clock: Clock = SYSTEM_CLOCK) -> LockInfo | None:
    """El titular del cerrojo, o ``None`` si no hay o no se puede leer."""
    return read_lock(root, clock=clock)[1]


def classify(holder: LockInfo, session: SessionInfo, *, alive: PidAlive) -> LockState:
    """El estado de un cerrojo legible visto por ``session``."""
    if holder.session_uid == session.session_uid:
        return LockState.OURS
    if holder.same_host(session) and not alive(holder.pid):
        return LockState.ORPHAN
    return LockState.ACTIVE


def inspect(
    root: Path,
    session: SessionInfo,
    *,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
) -> LockStatus:
    """El estado del cerrojo de ``root`` visto por ``session``. No escribe nada."""
    content, holder = read_lock(root, clock=clock)
    if content is None:
        return LockStatus(LockState.FREE, None, None)
    if holder is None:
        return LockStatus(LockState.ACTIVE, None, content)
    state = classify(holder, session, alive=pid_alive)
    return LockStatus(state, holder, content)


def _remove_file(path: Path, clock: Clock) -> None:
    for attempt in range(REMOVE_ATTEMPTS):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == REMOVE_ATTEMPTS - 1:
                raise
            clock.sleep(REMOVE_INTERVAL_S)


def remove_if_unchanged(root: Path, seen: bytes, *, clock: Clock = SYSTEM_CLOCK) -> bool:
    """Borra ``.lock`` solo si sus bytes siguen siendo ``seen``; verdadero si lo borró
    (o ya no estaba)."""
    path = lock_path(root)
    current = _read_bytes(path)
    if current is None:
        return True
    if current != seen:
        return False
    _remove_file(path, clock)
    return True


def _create(path: Path, content: bytes) -> bool:
    """Crea ``path`` en exclusiva con ``content``; falso si ya existía."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError:
        return False
    try:
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        try:
            path.unlink()  # lo acabamos de crear nosotros: no es de nadie más
        except OSError:
            pass
        raise
    return True


def _project_name(root: Path) -> str:
    name = Path(root).name
    return name[: -len(".gbproj")] if name.endswith(".gbproj") else name


def busy_error(root: Path, status: LockStatus) -> LockError:
    """El error de un proyecto que tiene otra sesión, con quién y desde cuándo."""
    holder = status.holder
    context: dict[str, Any] = {"state": status.state.value}
    if holder is not None:
        context["holder"] = holder.to_dict()
    return LockError(
        "core.lock_held",
        "otra sesión de Geoblender tiene el proyecto abierto en escritura: se abre en "
        "solo lectura",
        obj=f"Proyecto «{_project_name(root)}»",
        field="cerrojo",
        shown=status.describe(),
        context=context,
    )


def acquire(
    root: Path,
    session: SessionInfo,
    mode: LockMode,
    *,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
) -> Acquired:
    """Pone el cerrojo de ``session`` en ``root``.

    Si ya es suyo, lo deja como está. Un huérfano se sustituye. :class:`LockError` si lo
    tiene otra sesión (o uno ilegible), o si no se pudo escribir o comprobar.
    """
    path = lock_path(root)
    replaced: LockInfo | None = None
    for _attempt in range(ACQUIRE_ATTEMPTS):
        info = LockInfo.new(session, mode, clock)
        content = encode_lock(info)
        try:
            created = _create(path, content)
        except OSError as exc:
            raise LockError(
                "core.lock_write_failed",
                f"no se ha podido crear el cerrojo ({exc.strerror or exc}); compruebe "
                "que la carpeta del proyecto se puede escribir",
                obj=f"Proyecto «{_project_name(root)}»",
                field=LOCK_FILE,
                value=str(path),
            ) from exc
        if created:
            if _read_bytes(path) != content:
                raise LockError(
                    "core.lock_verify_failed",
                    "el cerrojo recién escrito no se lee igual (otro programa lo ha "
                    "cambiado); no se escribe en el proyecto",
                    obj=f"Proyecto «{_project_name(root)}»",
                    field=LOCK_FILE,
                    value=str(path),
                )
            return Acquired(info, replaced)
        status = inspect(root, session, clock=clock, pid_alive=pid_alive)
        if status.state is LockState.OURS and status.holder is not None:
            return Acquired(status.holder, replaced)
        if status.state is LockState.FREE:
            continue  # se liberó entre medias
        if status.state is LockState.ORPHAN and status.content is not None:
            if remove_if_unchanged(root, status.content, clock=clock):
                replaced = status.holder
            continue
        raise busy_error(root, status)
    raise LockError(
        "core.lock_contended",
        f"no se ha podido poner el cerrojo tras {ACQUIRE_ATTEMPTS} intentos: otra sesión "
        "lo está cambiando a la vez; vuelva a intentarlo",
        obj=f"Proyecto «{_project_name(root)}»",
        field=LOCK_FILE,
        value=str(path),
    )


def release(root: Path, session: SessionInfo, *, clock: Clock = SYSTEM_CLOCK) -> bool:
    """Borra el cerrojo si es de ``session``; verdadero si lo borró. Uno ajeno o
    ilegible no se toca."""
    content, holder = read_lock(root, clock=clock)
    if content is None or holder is None or holder.session_uid != session.session_uid:
        return False
    return remove_if_unchanged(root, content, clock=clock)
