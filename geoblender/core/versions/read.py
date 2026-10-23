# SPDX-License-Identifier: GPL-3.0-or-later
"""Lecturas de las versiones y sus revisiones, sin escribir nada (spec 009; RF-009-01,
RF-009-03, RF-009-10; plan 009 §5.3.1 y D-25).

Cada función recibe una conexión cualquiera a la base del proyecto (de lectura, o la de una
transacción de escritura, en la que ve lo aún sin confirmar) y solo hace ``SELECT``: no mueve el
contador de cambios de la base. Al cargarse no importa ``core.provenance`` (que la usa para las
operaciones de versión y la cascada) ni nada que la importe: solo :mod:`.model` (ARQ-08);
:func:`version_figures` lo importa al llamarla.

- :func:`versions`, :func:`version`: las versiones, por número de código, y una, por su uid o
  su código.
- :func:`revision`, :func:`revisions`, :func:`open_revision`, :func:`last_frozen`: una
  revisión por su uid; las de una versión, por número; la abierta, y la última congelada.
- :func:`current_version`: la VIGENTE (solo puede haber una, D-3); :func:`default_active`: la
  versión activa por defecto (D-25), la VIGENTE o, si no hay, el BORRADOR más reciente.
- :func:`dataset_versions`: la versión de cada dato (``''``, del proyecto; RF-009-05);
  :func:`dataset_titles`, también su título, para la vista (T22; RF-009-30, RF-009-22).
- :func:`version_figures`: las cifras vigentes de una versión, las de su última revisión
  congelada (D-9), o las «en curso» (RF-009-20).
- :func:`snapshot_index`: el inventario de lo congelado para la cabecera (``manifest.json``).
- :func:`has_versions` y :func:`latest_revisions` (T18; RF-009-10, plan A11): si la base tiene
  versiones (un proyecto del esquema 2 abierto en solo lectura, no) y la revisión que se enseña
  con cada versión («● V10.r2»: la abierta o, si ya no tiene, la última).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from .model import (
    SNAPSHOT_MANIFEST,
    Revision,
    RevisionState,
    Version,
    VersionStatus,
    revision_label,
)

if TYPE_CHECKING:
    from ..provenance.figures import FigureRecord

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


def dataset_titles(conn: sqlite3.Connection, uids: Iterable[str]) -> dict[str, tuple[str, str]]:
    """La versión (su uid; ``''``, del proyecto) y el título (``''`` sin título) de cada dato de
    ``uids``, lo que necesita la vista (spec 009, T22; RF-009-30, RF-009-22; plan A11, D-36): la
    colección de su versión y el título en su nombre generado. Los que el proyecto no tiene no
    salen; en una base sin versiones (un proyecto del esquema 2 abierto en solo lectura),
    ninguno."""
    wanted = list(dict.fromkeys(uids))
    found: dict[str, tuple[str, str]] = {}
    if not wanted or not has_versions(conn):
        return found
    for start in range(0, len(wanted), _CHUNK):
        part = wanted[start:start + _CHUNK]
        marks = ", ".join("?" for _ in part)
        rows = conn.execute(
            f"SELECT uid, version_uid, title FROM gb_dataset WHERE uid IN ({marks})", part)
        found.update((str(uid), (str(owner), title or "")) for uid, owner, title in rows)
    return found


_FROZEN_FIGURES = (  # por el índice único de gb_revision_item y el uid de gb_figure
    "SELECT {columns} FROM gb_figure WHERE uid IN (SELECT item_uid FROM gb_revision_item "
    "WHERE revision_uid = ? AND item_kind = 'figure' AND part = 'produced') ORDER BY fid"
)


def version_figures(conn: sqlite3.Connection, version_uid: str, *,
                    frozen: bool = True) -> tuple[FigureRecord, ...]:
    """Las cifras de la versión ``version_uid`` (uid o código; ninguna si no está), en el orden
    en que se registraron (RF-009-20, D-9; plan A4 (5)):

    - ``frozen`` (por defecto): las **vigentes**, las de su última revisión congelada, tal como
      quedaron anotadas al congelarla (``gb_revision_item``, ``figure``, ``produced``);
      ninguna si no tiene ninguna congelada. Las de una VIGENTE con una revisión abierta son
      estas, no las «en curso»;
    - si no, las **«en curso»**: la vigente hoy de cada clave y ámbito entre las de sus
      operaciones (``core.provenance.lineage.figures_in``), también si se registraron en una
      revisión ya congelada y nada las ha rehecho.

    Nunca las de otra versión, ni las de la versión de la que parte (D-10; error 32)."""
    # Aquí, no al cargar: core.provenance importa este módulo (ARQ-08).
    from ..provenance import figures as records
    from ..provenance.lineage import figures_in

    found = version(conn, version_uid)
    if found is None:
        return ()
    if not frozen:
        return figures_in(conn, found.uid)
    revision = last_frozen(conn, found.uid)
    if revision is None:
        return ()
    rows = conn.execute(_FROZEN_FIGURES.format(columns=records.RECORD_COLUMNS), (revision.uid,))
    return tuple(records.FigureRecord.from_row(row) for row in rows)


_FROZEN_REVISIONS = (  # por el índice único de gb_version.uid; las congeladas son pocas
    "SELECT r.uid, v.code, r.number, r.snapshot_dir, r.snapshot_sha256, r.closed_at "
    "FROM gb_revision AS r CROSS JOIN gb_version AS v ON v.uid = r.version_uid "
    "WHERE r.state = 'frozen' ORDER BY CAST(substr(v.code, 2) AS INTEGER), v.code, r.number"
)

type InventoryEntry = dict[str, str]


def snapshot_index(conn: sqlite3.Connection) -> tuple[InventoryEntry, ...] | None:
    """El inventario de la cabecera del proyecto (``manifest.json``; plan §5.2.4,
    formato-proyecto §2): una entrada por revisión congelada, por versión y número, con su
    etiqueta (``revision``, «V10.r2»), su uid, la ruta de su manifiesto (relativa al proyecto),
    su huella (``sha256``) y cuándo se congeló (``frozen_at``). ``None`` si el proyecto no tiene
    revisiones que leer (un esquema anterior al 3, abierto en solo lectura): entonces la
    cabecera conserva el que tenía."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'gb_revision'").fetchone() is None:
        return None
    return tuple(
        {"revision": revision_label(str(code), int(number)), "revision_uid": str(uid),
         "manifest": f"{snapshot_dir}/{SNAPSHOT_MANIFEST}", "sha256": str(sha256),
         "frozen_at": str(frozen_at)}
        for uid, code, number, snapshot_dir, sha256, frozen_at in conn.execute(_FROZEN_REVISIONS)
    )


def has_versions(conn: sqlite3.Connection) -> bool:
    """Si la base de ``conn`` tiene versiones que leer (``gb_version``: el esquema 3 o
    posterior); un proyecto del esquema 2 abierto en solo lectura, no."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gb_version'"
    ).fetchone() is not None


def latest_revisions(conn: sqlite3.Connection) -> dict[str, Revision]:
    """La revisión que se enseña con cada versión (el control 8, «● V10.r2»; RF-009-10, plan
    A11), por uid de versión: la abierta o, si ya no tiene ninguna (SUPERADO, DESCARTADO), la
    de número mayor. Una versión sin revisiones no está. Una sola consulta: las revisiones son
    pocas."""
    found: dict[str, Revision] = {}
    for row in conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM gb_revision ORDER BY version_uid, number"
    ):
        revision = _revision(row)
        kept = found.get(revision.version_uid)
        if kept is None or kept.state is not RevisionState.OPEN:
            found[revision.version_uid] = revision
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
