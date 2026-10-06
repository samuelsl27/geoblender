# SPDX-License-Identifier: GPL-3.0-or-later
"""Cabecera de una base SQLite y ficheros junto a ella (spec 002; RF-002-16, RF-002-17;
plan 002 §5.4).

Se lee sin abrir la base con SQLite (``open`` en modo binario de lectura): no crea ni
toca ningún fichero. Los bytes 18 y 19 de la cabecera (versiones de escritura y de
lectura del formato) valen 1 en diario clásico y 2 en WAL; una base que QGIS dejó en WAL
lo sigue diciendo aunque ya no haya ``-wal``. Junto a ella se miran ``-wal``, ``-shm`` y
``-journal`` (un ``-journal`` no vacío es un diario caliente: una transacción a medias que
hay que deshacer antes de leer).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..errors import DatabaseError

SQLITE_MAGIC = b"SQLite format 3\x00"
HEADER_SIZE = 100
CLASSIC_VERSION = 1  # bytes 18 y 19: diario clásico (rollback journal)
WAL_VERSION = 2  # bytes 18 y 19: WAL

Journal = Literal["classic", "wal"]
_OBJ = "Base de datos del proyecto"


@dataclass(frozen=True)
class SqliteHeader:
    """Lo que dicen la cabecera y los ficheros que acompañan a la base."""

    path: Path
    journal: Journal
    write_version: int
    read_version: int
    has_wal: bool
    has_shm: bool
    has_journal: bool
    has_hot_journal: bool

    @property
    def needs_recovery(self) -> bool:
        """Verdadero si la base no está limpia en diario clásico: cabecera WAL, un
        ``-wal`` o un diario caliente. Entonces no se lee en el sitio (se lee una copia
        privada) ni se escribe sin devolverla antes al diario clásico."""
        return self.journal == "wal" or self.has_wal or self.has_hot_journal


def side_file(path: Path, suffix: str) -> Path:
    """El fichero ``<base><suffix>`` (``-wal``, ``-shm``, ``-journal``) de la base."""
    return Path(f"{path}{suffix}")


def read_header(path: Path) -> SqliteHeader:
    """La cabecera de ``path`` y sus ficheros acompañantes, sin abrirla con SQLite.

    :class:`DatabaseError` si no existe o no es una base SQLite.
    """
    path = Path(path)
    try:
        with path.open("rb") as handle:
            head = handle.read(HEADER_SIZE)
    except FileNotFoundError as exc:
        raise DatabaseError(
            "core.gpkg_missing",
            "no existe; compruebe la ruta del proyecto",
            obj=_OBJ,
            field="fichero",
            value=str(path),
        ) from exc
    except OSError as exc:
        raise DatabaseError(
            "core.gpkg_unreadable",
            f"no se puede leer ({exc.strerror or exc})",
            obj=_OBJ,
            field="fichero",
            value=str(path),
        ) from exc
    if len(head) < HEADER_SIZE or not head.startswith(SQLITE_MAGIC):
        raise DatabaseError(
            "core.gpkg_not_sqlite",
            "no es una base de datos SQLite (ni, por tanto, un GeoPackage)",
            obj=_OBJ,
            field="fichero",
            value=str(path),
        )
    write_version, read_version = head[18], head[19]
    versions = {write_version, read_version}
    if versions == {CLASSIC_VERSION}:
        journal: Journal = "classic"
    elif versions <= {CLASSIC_VERSION, WAL_VERSION}:
        journal = "wal"
    else:
        raise DatabaseError(
            "core.gpkg_header_unknown",
            "la cabecera tiene una versión de formato que SQLite no define (bytes 18 y 19)",
            obj=_OBJ,
            field="cabecera",
            value=f"{write_version}/{read_version}",
        )
    journal_file = side_file(path, "-journal")
    has_journal = journal_file.is_file()
    return SqliteHeader(
        path=path,
        journal=journal,
        write_version=write_version,
        read_version=read_version,
        has_wal=side_file(path, "-wal").is_file(),
        has_shm=side_file(path, "-shm").is_file(),
        has_journal=has_journal,
        has_hot_journal=has_journal and journal_file.stat().st_size > 0,
    )
