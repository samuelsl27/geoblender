# SPDX-License-Identifier: GPL-3.0-or-later
"""Un solo ``tools/check.py`` a la vez en el equipo (spec 006, T46; RNF-001-01,
RNF-007-01; RF-004-28).

Dos comprobaciones a la vez (la de la carpeta del proyecto y la de un *worktree*, o las de
dos sesiones) compiten por los procesadores: las dos tardan más y las pruebas de tiempo
fallan (``docs/trampas.md`` §4). ``tools/check.py`` toma al empezar este cerrojo del
equipo y lo suelta al terminar:

- Es un fichero, ``%LOCALAPPDATA%\\Geoblender\\check.lock`` (:func:`lock_path`; la variable
  ``GEOBLENDER_CHECK_LOCK`` lo cambia de sitio, p. ej. en las pruebas), común a todas las
  carpetas del código. El cerrojo es un bloqueo del sistema (``msvcrt.locking``) de un
  byte que está justo detrás de los datos: el sistema lo suelta si el proceso muere, así
  que el fichero que queda no estorba ni hay que borrarlo a mano.
- Quien lo tiene escribe al principio del fichero, en JSON y relleno con espacios hasta
  ``INFO_SIZE`` bytes, su pid, su carpeta y desde cuándo (:class:`Holder`), y lo deja en
  blanco al soltarlo; quien espera lo lee (esa zona no está bloqueada) para decir a quién
  espera (:func:`wait_message`).
- Quien espera lo intenta cada ``POLL_S`` segundos y avisa una vez por cada dueño
  distinto (si aún no se sabe quién es, tras ``UNKNOWN_AFTER_S``).
- Las órdenes que lanza ``check.py`` llevan ``GEOBLENDER_CHECK_LOCK_HELD`` con su pid: un
  ``check.py`` lanzado desde ellas no espera a su padre (no lo tomaría nunca), sino que
  sigue con el cerrojo de este (:meth:`CheckLock.acquire` con ``inherited``).

Solo Windows (``msvcrt``), como Geoblender. Solo biblioteca estándar (HER-01).
"""

from __future__ import annotations

import errno
import json
import msvcrt
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .layout import CHECK_LOCK_PARTS

ENV_LOCK = "GEOBLENDER_CHECK_LOCK"  # otra ruta del cerrojo (las pruebas)
ENV_HELD = "GEOBLENDER_CHECK_LOCK_HELD"  # en las órdenes de check.py: el pid que lo tiene
ENV_LOCAL_APPDATA = "LOCALAPPDATA"
LOCK_PARTS = CHECK_LOCK_PARTS  # bajo %LOCALAPPDATA%
SCHEMA = "geoblender.check-lock/1"
INFO_SIZE = 4096  # bytes de los datos de quien lo tiene, al principio del fichero
LOCK_OFFSET = INFO_SIZE  # el byte bloqueado, detrás de los datos (que se leen sin bloqueo)
POLL_S = 0.5  # cada cuánto lo intenta quien espera
UNKNOWN_AFTER_S = 2.0  # si no se sabe quién lo tiene, lo que se espera antes de avisar
WAIT_PREFIX = "ESPERANDO:"
_BUSY = (errno.EACCES, errno.EDEADLOCK)  # msvcrt.locking con el byte ya bloqueado
_NOBODY = object()  # quien espera aún no ha avisado de nadie


class LockProblem(Exception):
    """El cerrojo no se puede usar (no se sabe dónde va, o no se puede crear ni
    bloquear): el mensaje dice por qué."""


@dataclass(frozen=True)
class Holder:
    """Quién tiene el cerrojo: su pid, su carpeta (la raíz del código de ese ``check.py``)
    y desde cuándo (hora local, ``AAAA-MM-DD hh:mm:ss``)."""

    pid: int
    folder: str
    since: str


def lock_path(environ: Mapping[str, str]) -> Path:
    """El fichero del cerrojo: ``GEOBLENDER_CHECK_LOCK`` o
    ``%LOCALAPPDATA%\\Geoblender\\check.lock``; :class:`LockProblem` si no hay ninguna."""
    value = environ.get(ENV_LOCK, "").strip()
    if value:
        return Path(value)
    local = environ.get(ENV_LOCAL_APPDATA, "").strip()
    if not local:
        raise LockProblem(
            f"no se sabe dónde va el cerrojo del equipo: falta la variable "
            f"{ENV_LOCAL_APPDATA} (el perfil local del usuario de Windows); defina "
            f"{ENV_LOCK} con la ruta de su fichero"
        )
    return Path(local).joinpath(*LOCK_PARTS)


def wait_message(holder: Holder | None) -> str:
    """La línea que escribe quien espera, en español: a quién espera (o que no se sabe)."""
    if holder is None:
        who = "no se sabe cuál: aún no ha dicho su pid ni su carpeta"
    else:
        who = f"pid {holder.pid}, carpeta «{holder.folder}», desde {holder.since}"
    return (
        f"{WAIT_PREFIX} hay otro tools/check.py en marcha en este equipo ({who}). Dos a la "
        "vez se estorban (compiten por los procesadores y las pruebas de tiempo fallan): "
        "esta comprobación espera a que termine, y su tiempo se cuenta desde entonces."
    )


def _parse(data: bytes) -> Holder | None:
    """Los datos de quien lo tiene, o ``None`` si están en blanco o no se entienden."""
    try:
        found = json.loads(data.decode("utf-8").strip() or "null")
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(found, dict) or found.get("schema") != SCHEMA:
        return None
    pid, folder, since = found.get("pid"), found.get("carpeta"), found.get("desde")
    if (not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(folder, str)
            or not isinstance(since, str)):
        return None
    return Holder(pid, folder, since)


def read_holder(path: Path) -> Holder | None:
    """Quién tiene el cerrojo de ``path``, según lo que escribió (``None`` si no hay nadie,
    si aún no lo ha escrito o si el fichero no existe o no se puede leer)."""
    # Sin búfer: un open() de Python leería 8 KiB de golpe, y pasar por el byte
    # bloqueado (LOCK_OFFSET) hace fallar la lectura entera.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_BINARY)
    except OSError:
        return None
    try:
        return CheckLock._read(fd)
    finally:
        os.close(fd)


class CheckLock:
    """El cerrojo del fichero ``path`` para el ``check.py`` de la carpeta ``folder``.

    :meth:`acquire` lo toma (esperando si otro lo tiene) y :meth:`release` lo suelta;
    ``owner`` es el pid del ``check.py`` que lo tiene: este, o su padre si lo heredó.
    """

    def __init__(self, path: Path, folder: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.folder = str(folder)
        self.owner: int | None = None
        self._fd: int | None = None

    def _open(self) -> int:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_BINARY, 0o666)
        except OSError as exc:
            raise LockProblem(
                f"no se puede crear el cerrojo del equipo «{self.path}»: {exc}"
            ) from exc

    def _try_lock(self, fd: int) -> bool:
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in _BUSY:
                return False
            raise LockProblem(
                f"no se puede bloquear el cerrojo del equipo «{self.path}»: {exc}"
            ) from exc
        return True

    @staticmethod
    def _read(fd: int) -> Holder | None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            return _parse(os.read(fd, INFO_SIZE))
        except OSError:
            return None

    @staticmethod
    def _write(fd: int, data: bytes) -> None:
        """Escribe ``data`` al principio del fichero, rellena con espacios hasta
        ``INFO_SIZE`` bytes (vacía, deja en blanco quién lo tiene)."""
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, data[: INFO_SIZE - 1].ljust(INFO_SIZE - 1) + b"\n")

    def _write_holder(self) -> None:
        """Escribe al principio del fichero quién lo tiene: este proceso."""
        if self._fd is None:
            return
        data = json.dumps(
            {"schema": SCHEMA, "pid": os.getpid(), "carpeta": self.folder,
             "desde": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False,
        ).encode("utf-8")
        self._write(self._fd, data)

    def acquire(
        self,
        *,
        inherited: str | None = None,
        on_wait: Callable[[Holder | None], object] | None = None,
        poll_s: float | None = None,
        unknown_after_s: float = UNKNOWN_AFTER_S,
        sleep: Callable[[float], object] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> bool:
        """Toma el cerrojo y escribe quién lo tiene; si otro lo tiene, llama a ``on_wait``
        (una vez por cada dueño distinto; con ``None`` si tras ``unknown_after_s`` aún no se
        sabe quién es) y lo vuelve a intentar cada ``poll_s`` (``POLL_S``) segundos.
        Verdadero si lo tiene este proceso; falso si lo tiene el ``check.py`` del que este
        desciende (``inherited``: el valor de ``GEOBLENDER_CHECK_LOCK_HELD``, su pid), y
        entonces ni se espera ni se toma. :class:`LockProblem` si no se puede usar."""
        wait = POLL_S if poll_s is None else poll_s
        fd = self._open()
        started = clock()
        announced: object = _NOBODY
        try:
            while not self._try_lock(fd):
                holder = self._read(fd)
                if (holder is not None and inherited is not None
                        and inherited.strip() == str(holder.pid)):
                    os.close(fd)
                    self.owner = holder.pid
                    return False
                if holder is not None and holder.pid != announced:
                    announced = holder.pid
                    if on_wait is not None:
                        on_wait(holder)
                elif holder is None and announced is _NOBODY and (
                        clock() - started >= unknown_after_s):
                    announced = None
                    if on_wait is not None:
                        on_wait(None)
                sleep(wait)
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        self.owner = os.getpid()
        try:
            self._write_holder()
        except OSError:
            pass  # sin sus datos, quien espere dirá que no se sabe quién lo tiene
        return True

    def release(self) -> None:
        """Deja en blanco quién lo tiene y lo suelta; si no lo tiene, no hace nada."""
        fd, self._fd = self._fd, None
        self.owner = None
        if fd is None:
            return
        try:
            self._write(fd, b"")
            os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # al cerrar el fichero, el sistema lo suelta igual
        finally:
            os.close(fd)

