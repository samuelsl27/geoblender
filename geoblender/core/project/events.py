# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de eventos del proyecto, ``gb_event`` (spec 002; RF-002-04, RF-002-06,
RF-002-10, RF-002-12, RF-002-17, RF-002-20, RF-002-27; formato-proyecto §3.10; plan 002
§5.2).

Auditoría para personas: fecha UTC, «usuario@equipo», sesión, tipo, mensaje en español y
datos en JSON. La tabla es de solo inserción (disparadores) y solo la escribe una conexión
de Geoblender (``gb_writer()``). Ningún evento lleva una ruta absoluta (RF-002-18): el
mensaje y los datos se comprueban antes de escribir.

Lo que ocurre sin poder escribir en el proyecto (solo lectura, un fallo de escritura, el
cerrojo perdido) no va aquí: va al registro técnico de la extensión (:func:`log_event`).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..paths import find_absolute_paths
from ..sysinfo import SessionInfo

LOGGER = logging.getLogger("geoblender.core.project")


class EventKind(Enum):
    """Tipos de evento (``gb_event.kind``): los de la spec 002 y los de la procedencia de la
    008 (plan 008 §5.2.3), que se añaden con la tarea que los registra."""

    CREATE = "create"
    OPEN = "open"
    CLOSE = "close"
    LOCK_ORPHAN_REPLACED = "lock_orphan_replaced"
    LOCK_FORCED = "lock_forced"
    LOCK_LOST = "lock_lost"
    WRITE_FAILED = "write_failed"
    WAL_RECOVERED = "wal_recovered"
    MANIFEST_REWRITTEN = "manifest_rewritten"
    MIGRATION = "migration"
    MIGRATION_FAILED = "migration_failed"
    MOVE_ORIGIN = "move_origin"
    CHECKOUT = "checkout"
    PUBLISH = "publish"
    # Spec 008: una operación «en curso» de una sesión que perdió el cerrojo (RF-008-19) y una
    # cuyo trabajo se borró sin incorporarlo (RF-008-23).
    OPERATION_INTERRUPTED = "operation_interrupted"
    OPERATION_NOT_INGESTED = "operation_not_ingested"
    # Una entrada registrada con su importación (RF-008-07) y una fuente que ya lo estaba, con
    # el mismo contenido y los mismos ajustes, reutilizada (RF-008-54).
    INPUT_REGISTERED = "input_registered"
    INPUT_REUSED = "input_reused"
    # Una entrada sustituida por la que la actualiza (RF-008-11), cambiada con la copia
    # mantenida (RF-008-12), descartada (RF-008-55) y con su nombre o su entrega editados
    # (D-11; ``input_edited`` no está en la lista del plan §5.2.3: deja quién y cuándo).
    INPUT_UPDATED = "input_updated"
    INPUT_KEPT = "input_kept"
    INPUT_DISCARDED = "input_discarded"
    INPUT_EDITED = "input_edited"
    # Una entrada cuya fuente ya no tiene el contenido registrado (o el visto), «cambiada»
    # (RF-008-10), y una cambiada o mantenida cuya fuente vuelve al registrado, otra vez vigente.
    INPUT_CHANGED = "input_changed"
    INPUT_RESTORED = "input_restored"
    # El original de una entrada tabular o documental que pasa del límite y no se guarda
    # (RF-008-53; D-18).
    ORIGINAL_NOT_STORED = "original_not_stored"


@dataclass(frozen=True)
class ProjectEvent:
    """Una fila de ``gb_event``."""

    at: str
    user_host: str
    session_uid: str | None
    kind: str
    entity_kind: str | None
    entity_uid: str | None
    message: str
    data: Any


def _check_no_paths(message: str, data: object) -> None:
    found = find_absolute_paths([message, data])
    if found:
        raise ValueError(
            f"un evento del proyecto no puede llevar rutas absolutas (RF-002-18): {found}"
        )


def record_event(
    conn: sqlite3.Connection,
    kind: EventKind,
    message: str,
    *,
    session: SessionInfo,
    at: str,
    entity_kind: str | None = None,
    entity_uid: str | None = None,
    data: Mapping[str, Any] | None = None,
) -> None:
    """Inserta un evento en ``gb_event`` dentro de la transacción de ``conn`` (una
    conexión de escritura de Geoblender). ``ValueError`` si el mensaje o los datos llevan
    una ruta absoluta."""
    _check_no_paths(message, data)
    payload = None if data is None else json.dumps(dict(data), ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT INTO gb_event (at, user_host, session_uid, kind, entity_kind, entity_uid, "
        "message, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            at,
            session.user_host,
            session.session_uid,
            kind.value,
            entity_kind,
            entity_uid,
            message,
            payload,
        ),
    )


def read_events(conn: sqlite3.Connection, kind: EventKind | None = None) -> list[ProjectEvent]:
    """Los eventos del proyecto en orden (solo los de ``kind``, si se indica)."""
    sql = (
        "SELECT at, user_host, session_uid, kind, entity_kind, entity_uid, message, data "
        "FROM gb_event"
    )
    params: tuple[Any, ...] = ()
    if kind is not None:
        sql += " WHERE kind = ?"
        params = (kind.value,)
    rows = conn.execute(sql + " ORDER BY fid", params).fetchall()
    return [
        ProjectEvent(
            at, user_host, session_uid, event_kind, entity_kind, entity_uid, message,
            None if data is None else json.loads(data),
        )
        for at, user_host, session_uid, event_kind, entity_kind, entity_uid, message, data in rows
    ]


OriginTriple = tuple[int, int, int]


def _origin_triple(value: object) -> OriginTriple:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    ):
        raise ValueError(f"no es un GeoOrigin (x0, y0, z0) en metros enteros: {value!r}")
    return (value[0], value[1], value[2])


def last_origin_move(conn: sqlite3.Connection) -> tuple[OriginTriple, OriginTriple] | None:
    """El último cambio de GeoOrigin registrado (evento ``move_origin`` de
    ``Project.set_window``): (origen anterior, origen nuevo), en metros enteros; ``None``
    si no hay ninguno o sus datos no tienen esa forma (RF-002-27). Lo usa la apertura para
    reconocer una cabecera que se quedó con el origen anterior (RF-002-05)."""
    row = conn.execute(
        "SELECT data FROM gb_event WHERE kind = ? ORDER BY fid DESC LIMIT 1",
        (EventKind.MOVE_ORIGIN.value,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        data = json.loads(row[0])
        return _origin_triple(data["from"]), _origin_triple(data["to"])
    except (ValueError, KeyError, TypeError):
        return None


def log_event(kind: EventKind, message: str, **data: Any) -> None:
    """Deja en el registro técnico de la extensión un evento que no se pudo escribir en
    el proyecto (solo lectura, fallo de escritura, cerrojo perdido)."""
    LOGGER.warning("%s: %s %s", kind.value, message, data or "")
