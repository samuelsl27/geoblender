# SPDX-License-Identifier: GPL-3.0-or-later
"""Vuelta al diario clásico de una base que otro programa dejó en WAL, y copia privada
para leerla sin ensuciar (spec 002; RF-002-13, RF-002-17; plan 002 §5.4 y §6).

QGIS 4.2 pasa a WAL un GeoPackage local al empezar a editar y, al cerrar, deja la
cabecera en WAL; mientras lo tiene abierto, otra conexión no puede volverlo al diario
clásico (comprobado con QGIS 4.2.0 en la spec 002, §11).

- :func:`to_classic_journal`: ``locking_mode = EXCLUSIVE`` (así SQLite no usa memoria
  compartida, válido en red), ``journal_mode = DELETE`` (consolida el ``-wal`` en la base
  y lo borra), ``integrity_check`` = ok y ``locking_mode = NORMAL``. Si otro programa la
  tiene abierta, ``BUSY`` sin cambios. Tras consolidar se borra el ``-shm`` huérfano que
  deja un escritor que terminó sin cerrar (nadie más la tiene abierta: lo garantizó el
  cerrojo exclusivo). El evento ``wal_recovered`` lo registra quien llama, con
  ``wal_bytes``.
- :func:`private_copy`: abrir en solo lectura una base en WAL crearía ``-wal`` y ``-shm``
  junto a ella, e ``immutable=1`` puede leer datos a medias; se copia la base (con su
  ``-wal`` o su ``-journal``) a una carpeta privada, se consolida allí, se comprueba la
  integridad (hasta 3 intentos, por si otro programa escribía) y se lee la copia.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..errors import DatabaseError
from .connection import BUSY_RETRY_S, CLASSIC_JOURNAL, is_busy
from .header import read_header, side_file

PRIVATE_COPY_ATTEMPTS = 3
SIDE_SUFFIXES: tuple[str, ...] = ("-wal", "-shm", "-journal")
_OBJ = "Base de datos del proyecto"


class WalOutcome(Enum):
    """Resultado de :func:`to_classic_journal`."""

    CONVERTED = "converted"  # estaba en WAL y ya está en diario clásico
    ALREADY_CLASSIC = "already_classic"  # no había nada que hacer
    BUSY = "busy"  # otro programa la tiene abierta: sin cambios


@dataclass(frozen=True)
class WalRecovery:
    """Qué pasó y cuántos bytes tenía el ``-wal`` consolidado."""

    outcome: WalOutcome
    wal_bytes: int = 0


def _remove_orphan_shm(path: Path) -> None:
    """Borra el ``-shm`` de una base que ya está en diario clásico y sin ``-wal`` (solo
    lo usa el modo WAL); si Windows no deja, se queda (es inofensivo)."""
    shm = side_file(path, "-shm")
    if not shm.exists() or side_file(path, "-wal").exists():
        return
    if read_header(path).journal != "classic":
        return
    try:
        shm.unlink()
    except OSError:
        pass


def to_classic_journal(path: Path, timeout_s: float = 2.0) -> WalRecovery:
    """Devuelve ``path`` al diario clásico sin perder datos.

    ``ALREADY_CLASSIC`` sin abrir la base si ya lo está; ``BUSY`` sin cambios si otro
    programa la tiene abierta durante ``timeout_s``; ``CONVERTED`` si la ha consolidado
    (con ``integrity_check`` = ok; si no, :class:`DatabaseError`).
    """
    path = Path(path)
    header = read_header(path)
    if header.journal == "classic" and not header.has_wal:
        return WalRecovery(WalOutcome.ALREADY_CLASSIC)
    wal_file = side_file(path, "-wal")
    wal_bytes = wal_file.stat().st_size if wal_file.exists() else 0
    conn = sqlite3.connect(str(path), timeout=0, isolation_level=None)
    try:
        conn.execute("PRAGMA locking_mode = EXCLUSIVE")
        deadline = time.perf_counter() + timeout_s
        while True:
            try:
                mode = str(conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0])
                break
            except sqlite3.OperationalError as exc:
                if not is_busy(exc):
                    raise
                if time.perf_counter() >= deadline:
                    return WalRecovery(WalOutcome.BUSY, wal_bytes)
                time.sleep(BUSY_RETRY_S)
        if mode.lower() != CLASSIC_JOURNAL:
            return WalRecovery(WalOutcome.BUSY, wal_bytes)
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise DatabaseError(
                "core.gpkg_integrity",
                f"la comprobación de integridad da «{integrity}» tras consolidar el WAL: "
                "restaure una copia de seguridad del proyecto",
                obj=_OBJ,
                field="integridad",
                value=str(path),
            )
        conn.execute("PRAGMA locking_mode = NORMAL")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()  # suelta el cerrojo
    finally:
        conn.close()
    _remove_orphan_shm(path)
    return WalRecovery(WalOutcome.CONVERTED, wal_bytes)


def _remove_copy(target: Path) -> None:
    for candidate in (target, *(side_file(target, s) for s in SIDE_SUFFIXES)):
        if candidate.exists():
            candidate.unlink()


def _consolidated(target: Path) -> bool:
    """Consolida la copia en diario clásico (deshace un diario caliente o vuelca el WAL)
    y dice si queda íntegra."""
    try:
        conn = sqlite3.connect(str(target), isolation_level=None)
        try:
            mode = str(conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0])
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False
    return mode.lower() == CLASSIC_JOURNAL and integrity == "ok"


def private_copy(path: Path, private_dir: Path) -> Path:
    """Copia ``path`` (con su ``-wal`` o su ``-journal``) a ``private_dir``, la consolida
    en diario clásico y devuelve la ruta de la copia; la original no cambia.

    Una copia anterior en ``private_dir`` se sustituye. :class:`DatabaseError` si tras
    ``PRIVATE_COPY_ATTEMPTS`` intentos la copia no queda íntegra.
    """
    path, private_dir = Path(path), Path(private_dir)
    private_dir.mkdir(parents=True, exist_ok=True)
    target = private_dir / path.name
    for _attempt in range(PRIVATE_COPY_ATTEMPTS):
        _remove_copy(target)
        shutil.copyfile(path, target)
        for suffix in ("-wal", "-journal"):
            source = side_file(path, suffix)
            if source.exists():
                shutil.copyfile(source, side_file(target, suffix))
        if _consolidated(target):
            _remove_orphan_shm(target)
            return target
    _remove_copy(target)
    raise DatabaseError(
        "core.gpkg_private_copy",
        f"no se ha podido leer una copia íntegra tras {PRIVATE_COPY_ATTEMPTS} intentos: "
        "otro programa la está escribiendo; ciérrelo y vuelva a intentarlo",
        obj=_OBJ,
        field="copia privada",
        value=str(path),
    )
