# SPDX-License-Identifier: GPL-3.0-or-later
"""Cerrojo de un solo escritor, ``.lock`` (spec 002; RF-002-04, RF-002-09 a RF-002-12;
ADR-0006, ADR-0010; formato-proyecto §5.2; plan 002 §5.4 y §6).

Un proyecto lo escribe una sola sesión de Geoblender: la que tiene ``.lock``, un JSON sin
rutas con su sesión, equipo, usuario, proceso, hora de inicio, última marca de actividad,
versión de Geoblender y modo (``network``, ``local`` o ``checkout``).

- :func:`inspect` (no escribe), en este orden: sin fichero → ``FREE``; reserva de una
  copia local (``mode = checkout``) → ``RESERVED``; de esta sesión → ``OURS``; del mismo
  equipo con el proceso ya terminado → ``ORPHAN`` (Blender se cerró de golpe); marca de
  actividad más antigua que el umbral (30 min por defecto) → ``STALE``; si no,
  ``ACTIVE``. Un ``.lock`` que existe pero no se puede leer o no es JSON válido (otro
  equipo puede estar escribiéndolo) se relee 3 veces cada 100 ms y, si sigue así, es
  ``ACTIVE`` de titular desconocido: **nunca** ``FREE`` ni ``ORPHAN``. La reserva va
  antes que el huérfano: sobrevive a la sesión que sacó la copia, y solo se quita
  forzándola con aviso o al publicar.
- :func:`acquire`: creación **exclusiva** (``os.open`` con ``O_CREAT | O_EXCL``, atómica
  también sobre SMB), JSON, ``fsync`` y relectura de comprobación. Un huérfano se borra
  solo si su contenido no cambió desde que se leyó, y se reintenta; el anterior se
  devuelve para registrarlo (evento ``lock_orphan_replaced``). Con otra sesión,
  :class:`LockError` con su equipo, usuario y hora.
- :func:`force`: solo un cerrojo ``STALE`` o ``RESERVED``, y solo si su titular es el que
  vio el usuario al confirmar (si cambió, por ejemplo porque su sesión lo renovó, no se
  fuerza); el anterior se devuelve para el evento ``lock_forced``.
- :func:`heartbeat`: comprueba que el cerrojo sigue siendo de esta sesión y renueva su
  marca reescribiéndolo **en el sitio, sin truncar antes** (``r+``, ``seek(0)``, la misma
  longitud fija, ``truncate()`` después y ``fsync``): otro equipo nunca lo ve vacío.
  ``LOST`` si ya no es suyo (otra sesión lo forzó, no está o no se puede leer);
  ``FAILED`` si no se pudo comprobar por un error de disco o de red.
- :func:`release`: solo borra el cerrojo de esta sesión.

No se usan los bloqueos de SQLite ni ``msvcrt.locking``: no son fiables entre clientes
SMB y quedan colgados tras un cierre brusco (plan 002 §6). Las horas, en UTC (el umbral
de 30 min frente a una marca cada 5 min cubre los desfases de reloj entre equipos).
Límite declarado: entre comprobar el contenido de un cerrojo huérfano o forzado y
borrarlo pasan microsegundos sin exclusión entre equipos; Windows no deja borrar un
fichero que otro proceso tiene abierto, y la sesión que renueva su marca lo abre antes de
comprobarlo, así que una renovación en curso hace fallar el borrado.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import IO, Any

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
DEFAULT_STALE_MINUTES = 30  # preferencia de la extensión, de 10 a 1 440 (spec 002 §11)
STALE_MINUTES_RANGE = (10, 1440)
HEARTBEAT_INTERVAL_S = 300  # la marca de actividad, cada 5 min (RF-002-11)
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
    ORPHAN = "orphan"  # mismo equipo y proceso terminado: se sustituye
    RESERVED = "reserved"  # reserva de una copia local: se puede forzar con aviso
    STALE = "stale"  # sin renovar más que el umbral: se puede forzar con aviso
    ACTIVE = "active"


class LockCheck(Enum):
    """Resultado de :func:`heartbeat`."""

    OK = "ok"  # sigue siendo nuestro y se ha renovado
    LOST = "lost"  # ya no es nuestro (forzado, borrado o ilegible)
    FAILED = "failed"  # no se pudo comprobar (error de disco o de red)


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

    def idle(self, now: dt.datetime) -> dt.timedelta:
        """Tiempo desde la última marca de actividad."""
        return now - parse_utc(self.heartbeat_at)


def local_time(text: str) -> str:
    """Una hora UTC del cerrojo como la lee una persona: ``DD/MM/AAAA HH:MM`` en la hora
    local del equipo."""
    try:
        moment = parse_utc(text)
    except ValueError:
        return text
    return moment.astimezone().strftime("%d/%m/%Y %H:%M")


@dataclass(frozen=True)
class LockStatus:
    """Lo que :func:`inspect` vio: el estado, el titular (``None`` si no hay cerrojo o
    no se puede leer), los bytes leídos (para no sustituir nunca un cerrojo distinto del
    que se vio) y cuánto lleva sin renovarse."""

    state: LockState
    holder: LockInfo | None
    content: bytes | None
    idle: dt.timedelta | None = None

    @property
    def unknown_holder(self) -> bool:
        """Verdadero si hay un ``.lock`` que no se puede leer."""
        return self.content is not None and self.holder is None

    @property
    def can_force(self) -> bool:
        """Verdadero si se puede ofrecer forzarlo (caducado o reserva de copia)."""
        return self.state in (LockState.STALE, LockState.RESERVED) and self.holder is not None

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
        what = "reservado para una copia local de" if self.state is LockState.RESERVED else "lo tiene"
        return (
            f"{what} {holder.user} en {holder.host} desde {local_time(holder.started_at)} "
            f"(última actividad {local_time(holder.heartbeat_at)})"
        )

    def force_warning(self) -> str:
        """El aviso antes de forzar: quién lo tenía, desde cuándo y qué se perderá
        (RF-002-10); vacío si no se puede forzar."""
        if not self.can_force or self.holder is None:
            return ""
        holder = self.holder
        since = local_time(holder.started_at)
        if self.state is LockState.RESERVED:
            return (
                f"El proyecto está reservado para una copia local de {holder.user} en "
                f"{holder.host} desde {since}. Si fuerza la reserva, esa copia ya no se "
                "podrá publicar sobre el original y los cambios que tenga se perderán "
                "para el proyecto (seguirán solo en su copia)."
            )
        minutes = int(self.idle.total_seconds() // 60) if self.idle is not None else 0
        return (
            f"Lo tenía {holder.user} en {holder.host} desde {since}, y su última actividad "
            f"fue hace {minutes} min ({local_time(holder.heartbeat_at)}). Si esa sesión "
            "sigue abierta, lo que guarde en el proyecto a partir de ahora se perderá: "
            "pasará a solo lectura en su siguiente comprobación."
        )


@dataclass(frozen=True)
class Acquired:
    """Resultado de :func:`acquire` y :func:`force`: el cerrojo puesto y el anterior que
    se sustituyó, si lo hubo (eventos ``lock_orphan_replaced`` y ``lock_forced``)."""

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


def classify(
    holder: LockInfo,
    session: SessionInfo,
    *,
    now: dt.datetime,
    alive: PidAlive,
    stale_minutes: int = DEFAULT_STALE_MINUTES,
) -> LockState:
    """El estado de un cerrojo legible visto por ``session`` (orden del módulo)."""
    if holder.mode is LockMode.CHECKOUT:
        return LockState.RESERVED
    if holder.session_uid == session.session_uid:
        return LockState.OURS
    if holder.same_host(session) and not alive(holder.pid):
        return LockState.ORPHAN
    if holder.idle(now) > dt.timedelta(minutes=stale_minutes):
        return LockState.STALE
    return LockState.ACTIVE


def inspect(
    root: Path,
    session: SessionInfo,
    *,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = DEFAULT_STALE_MINUTES,
) -> LockStatus:
    """El estado del cerrojo de ``root`` visto por ``session``. No escribe nada."""
    content, holder = read_lock(root, clock=clock)
    if content is None:
        return LockStatus(LockState.FREE, None, None)
    if holder is None:
        return LockStatus(LockState.ACTIVE, None, content)
    now = clock.now()
    state = classify(holder, session, now=now, alive=pid_alive, stale_minutes=stale_minutes)
    return LockStatus(state, holder, content, holder.idle(now))


def remove_if_unchanged(root: Path, seen: bytes, *, clock: Clock = SYSTEM_CLOCK) -> bool:
    """Borra ``.lock`` solo si sus bytes siguen siendo ``seen`` (se comprueba antes de
    cada intento); verdadero si lo borró (o ya no estaba)."""
    path = lock_path(root)
    for attempt in range(REMOVE_ATTEMPTS):
        current = _read_bytes(path)
        if current is None:
            return True
        if current != seen:
            return False
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == REMOVE_ATTEMPTS - 1:
                raise
            clock.sleep(REMOVE_INTERVAL_S)
    return False


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


def _obj(root: Path) -> str:
    return f"Proyecto «{_project_name(root)}»"


def busy_error(root: Path, status: LockStatus) -> LockError:
    """El error de un proyecto que tiene otra sesión, con quién y desde cuándo (y, si se
    puede forzar, el aviso de qué se perderá)."""
    holder = status.holder
    context: dict[str, Any] = {"state": status.state.value}
    if holder is not None:
        context["holder"] = holder.to_dict()
    reason = "otra sesión de Geoblender tiene el proyecto abierto en escritura: se abre en solo lectura"
    if status.state is LockState.RESERVED:
        reason = "el original está reservado para una copia local: se abre en solo lectura"
    if status.can_force:
        reason += "; se puede forzar el cerrojo, con confirmación"
    elif status.unknown_holder:
        reason += (
            "; si está seguro de que nadie lo tiene abierto y el aviso persiste, cierre "
            "Geoblender en los demás equipos y vuelva a intentarlo"
        )
    return LockError(
        "core.lock_held",
        reason,
        obj=_obj(root),
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
    stale_minutes: int = DEFAULT_STALE_MINUTES,
) -> Acquired:
    """Pone el cerrojo de ``session`` en ``root``.

    Si ya es suyo, lo deja como está. Un huérfano se sustituye. :class:`LockError` si lo
    tiene otra sesión (también si está caducado o reservado: eso solo se fuerza con
    :func:`force`), si es ilegible, o si no se pudo escribir o comprobar.
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
                obj=_obj(root),
                field=LOCK_FILE,
                value=str(path),
            ) from exc
        if created:
            if _read_bytes(path) != content:
                raise LockError(
                    "core.lock_verify_failed",
                    "el cerrojo recién escrito no se lee igual (otro programa lo ha "
                    "cambiado); no se escribe en el proyecto",
                    obj=_obj(root),
                    field=LOCK_FILE,
                    value=str(path),
                )
            return Acquired(info, replaced)
        status = inspect(
            root, session, clock=clock, pid_alive=pid_alive, stale_minutes=stale_minutes
        )
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
        obj=_obj(root),
        field=LOCK_FILE,
        value=str(path),
    )


def force(
    root: Path,
    session: SessionInfo,
    mode: LockMode,
    seen_holder: LockInfo,
    *,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = DEFAULT_STALE_MINUTES,
) -> Acquired:
    """Sustituye un cerrojo caducado o reservado por el de ``session``, solo si su
    titular sigue siendo ``seen_holder`` (el que vio el usuario al confirmar).

    :class:`LockError` con ``core.lock_changed`` si el titular cambió, o con
    ``core.lock_not_forceable`` si ya no está caducado ni reservado (su sesión lo
    renovó). Devuelve el anterior en ``replaced``.
    """
    status = inspect(root, session, clock=clock, pid_alive=pid_alive, stale_minutes=stale_minutes)
    if status.holder is not None and status.holder.session_uid == seen_holder.session_uid:
        if not status.can_force:
            raise LockError(
                "core.lock_not_forceable",
                "su sesión lo ha renovado o ya no está caducado ni reservado: no se fuerza; "
                "el proyecto sigue en solo lectura",
                obj=_obj(root),
                field="cerrojo",
                shown=status.describe(),
                context={"state": status.state.value},
            )
    if status.holder != seen_holder or status.content is None:
        raise LockError(
            "core.lock_changed",
            "el cerrojo ha cambiado desde que se mostró el aviso: no se fuerza; vuelva a "
            "abrir el proyecto para ver quién lo tiene ahora",
            obj=_obj(root),
            field="cerrojo",
            shown=status.describe(),
            context={"state": status.state.value},
        )
    if not remove_if_unchanged(root, status.content, clock=clock):
        raise LockError(
            "core.lock_changed",
            "el cerrojo ha cambiado mientras se forzaba: no se fuerza; vuelva a intentarlo",
            obj=_obj(root),
            field="cerrojo",
            shown=status.describe(),
        )
    acquired = acquire(
        root, session, mode, clock=clock, pid_alive=pid_alive, stale_minutes=stale_minutes
    )
    return Acquired(acquired.info, seen_holder)


def _open_for_update(path: Path) -> IO[bytes]:
    """Abre el cerrojo para leerlo y reescribirlo en el sitio (``r+b``)."""
    return path.open("r+b")


def heartbeat(root: Path, session: SessionInfo, *, clock: Clock = SYSTEM_CLOCK) -> LockCheck:
    """Renueva la marca de actividad del cerrojo de ``session`` en el sitio (sin truncar
    antes). ``LOST`` si ya no es suyo; ``FAILED`` si hubo un error de disco o de red."""
    path = lock_path(root)
    try:
        with _open_for_update(path) as handle:
            content = handle.read()
            try:
                holder = decode_lock(content)
            except ValueError:
                return LockCheck.LOST
            if holder.session_uid != session.session_uid:
                return LockCheck.LOST
            renewed = replace(holder, heartbeat_at=format_utc(clock.now()))
            handle.seek(0)
            handle.write(encode_lock(renewed))
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
    except FileNotFoundError:
        return LockCheck.LOST
    except OSError:
        return LockCheck.FAILED
    return LockCheck.OK


def release(root: Path, session: SessionInfo, *, clock: Clock = SYSTEM_CLOCK) -> bool:
    """Borra el cerrojo si es de ``session``; verdadero si lo borró. Uno ajeno o
    ilegible no se toca."""
    content, holder = read_lock(root, clock=clock)
    if content is None or holder is None or holder.session_uid != session.session_uid:
        return False
    return remove_if_unchanged(root, content, clock=clock)
