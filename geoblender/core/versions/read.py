# SPDX-License-Identifier: GPL-3.0-or-later
"""Lecturas de las versiones y sus revisiones, sin escribir nada (spec 009; RF-009-01,
RF-009-03, RF-009-10; plan 009 §5.3.1 y D-25).

Cada función recibe una conexión cualquiera a la base del proyecto (de lectura, o la de una
transacción de escritura, en la que ve lo aún sin confirmar) y solo hace ``SELECT``: no mueve el
contador de cambios de la base. No importa ``core.provenance`` (que la usará para las
operaciones de versión y la cascada) ni nada que la importe: solo :mod:`.model` (ARQ-08).

- :func:`versions`, :func:`version`: las versiones, por número de código, y una, por su uid o
  su código.
- :func:`revision`, :func:`revisions`, :func:`open_revision`, :func:`last_frozen`: una
  revisión por su uid; las de una versión, por número; la abierta, y la última congelada.
- :func:`current_version`: la VIGENTE (solo puede haber una, D-3); :func:`default_active`: la
  versión activa por defecto (D-25), la VIGENTE o, si no hay, el BORRADOR más reciente.
- :func:`dataset_versions`: la versión de cada dato (``''``, del proyecto; RF-009-05).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from .model import Revision, RevisionState, Version, VersionStatus

_CHUNK = 500
"""Uids por consulta (``IN (…)``)."""

_VERSION_COLUMNS = (
    "uid, code, feature, title, status, parent_uid, parent_revision_uid, request, "
    "reason_created, reason_closed, created_at, created_by, status_changed_at, "
    "status_changed_by, modified_at"
)
_REVISION_COLUMNS = (
    "uid, version_uid, number, state, reason, created_at, created_by, closed_at, closed_by, "
    "snapshot_dir, snapshot_sha256, snapshot_bytes, geoblender_version, accepted, altered_at, "
    "altered_detail"
)
_BY_NUMBER = "ORDER BY CAST(substr(code, 2) AS INTEGER), code"


def _version(row: Sequence[Any]) -> Version:
    values = list(row)
    values[4] = VersionStatus(values[4])
    return Version(*values)


def _revision(row: Sequence[Any]) -> Revision:
    values = list(row)
    values[3] = RevisionState(values[3])
    return Revision(*values)


def versions(conn: sqlite3.Connection) -> tuple[Version, ...]:
    """Las versiones del proyecto, por número de código (V01, V02… V10… V100)."""
    rows = conn.execute(f"SELECT {_VERSION_COLUMNS} FROM gb_version {_BY_NUMBER}").fetchall()
    return tuple(_version(row) for row in rows)


def version(conn: sqlite3.Connection, uid_or_code: str) -> Version | None:
    """La versión de uid o de código ``uid_or_code``; ``None`` si no hay ninguna."""
    row = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM gb_version WHERE uid = ? OR code = ?",
        (uid_or_code, uid_or_code),
    ).fetchone()
    return None if row is None else _version(row)


def revision(conn: sqlite3.Connection, uid: str) -> Revision | None:
    """La revisión de uid ``uid``; ``None`` si no hay ninguna."""
    row = conn.execute(f"SELECT {_REVISION_COLUMNS} FROM gb_revision WHERE uid = ?",
                       (uid,)).fetchone()
    return None if row is None else _revision(row)


def revisions(conn: sqlite3.Connection, version_uid: str) -> tuple[Revision, ...]:
    """Las revisiones de la versión ``version_uid``, por número (r1, r2…)."""
    rows = conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM gb_revision WHERE version_uid = ? ORDER BY number",
        (version_uid,),
    ).fetchall()
    return tuple(_revision(row) for row in rows)


def open_revision(conn: sqlite3.Connection, version_uid: str) -> Revision | None:
    """La revisión abierta de la versión (la tiene toda BORRADOR o VIGENTE; RF-009-06);
    ``None`` en una SUPERADO o DESCARTADO."""
    row = conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM gb_revision WHERE version_uid = ? AND state = ?",
        (version_uid, RevisionState.OPEN.value),
    ).fetchone()
    return None if row is None else _revision(row)


def last_frozen(conn: sqlite3.Connection, version_uid: str) -> Revision | None:
    """La última revisión congelada de la versión; ``None`` si no tiene ninguna."""
    row = conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM gb_revision WHERE version_uid = ? AND state = ? "
        "ORDER BY number DESC LIMIT 1",
        (version_uid, RevisionState.FROZEN.value),
    ).fetchone()
    return None if row is None else _revision(row)


def current_version(conn: sqlite3.Connection) -> Version | None:
    """La versión VIGENTE; ``None`` si no hay ninguna."""
    row = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM gb_version WHERE status = ?",
        (VersionStatus.VIGENTE.value,),
    ).fetchone()
    return None if row is None else _version(row)


def dataset_versions(conn: sqlite3.Connection, uids: Iterable[str]) -> dict[str, str]:
    """La versión de cada dato de ``uids`` (su uid; ``''``, del proyecto); los que el proyecto
    no tiene no salen (RF-009-05)."""
    wanted = list(dict.fromkeys(uids))
    found: dict[str, str] = {}
    for start in range(0, len(wanted), _CHUNK):
        part = wanted[start:start + _CHUNK]
        marks = ", ".join("?" for _ in part)
        found.update(
            (str(uid), str(version_uid)) for uid, version_uid in conn.execute(
                f"SELECT uid, version_uid FROM gb_dataset WHERE uid IN ({marks})", part)
        )
    return found


def default_active(conn: sqlite3.Connection) -> Version | None:
    """La versión activa cuando la sesión no tiene ninguna (D-25): la VIGENTE; si no hay, el
    BORRADOR creado más recientemente; si tampoco, ``None`` («Sin versión»)."""
    current = current_version(conn)
    if current is not None:
        return current
    row = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM gb_version WHERE status = ? "
        "ORDER BY created_at DESC, fid DESC LIMIT 1",
        (VersionStatus.BORRADOR.value,),
    ).fetchone()
    return None if row is None else _version(row)
