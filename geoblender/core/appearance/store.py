# SPDX-License-Identifier: GPL-3.0-or-later
"""Almacén del aspecto de los elementos en el proyecto (spec 019, T03; RF-019-07 a 09; ADR-0033).

La tabla ``gb_appearance`` (esquema 4) guarda solo lo que una persona cambió: una fila por
``(item_name, prop)`` con el valor canónico (:func:`core.appearance.model.validate`). El
predefinido no se guarda (sale de ``core.appearance.catalog``) y «restablecer» borra la fila.

**No es una operación ni una cifra**: este módulo no toca ``gb_dataset``, ``gb_operation``,
huellas, estados de seguimiento ni obsoletos. Solo lo escribe el hilo principal de Blender con
una conexión de Geoblender (``gb_writer()``), nunca un worker (principio 7); no usa WAL.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping

from .model import validate

__all__ = ["read", "reset", "write"]

_CHUNK = 500


def read(conn: sqlite3.Connection, names: Iterable[str]) -> dict[str, dict[str, str]]:
    """Los valores guardados de cada nombre de ``names`` que tenga alguno: ``{nombre: {prop:
    valor}}``. Un nombre sin filas no aparece (su aspecto es el predefinido)."""
    wanted = list(dict.fromkeys(names))
    found: dict[str, dict[str, str]] = {}
    for start in range(0, len(wanted), _CHUNK):
        chunk = wanted[start : start + _CHUNK]
        marks = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT item_name, prop, value FROM gb_appearance "
            f"WHERE item_name IN ({marks}) ORDER BY item_name, prop",
            chunk,
        )
        for item, prop, value in rows:
            found.setdefault(str(item), {})[str(prop)] = str(value)
    return found


def write(
    conn: sqlite3.Connection,
    name: str,
    kind: str,
    values: Mapping[str, object],
    who: str,
    now: str,
) -> dict[str, str]:
    """Guarda (inserta o sustituye) los valores de ``name``, de tipo ``kind``, validados y
    canónicos, en la transacción de ``conn``; devuelve lo escrito. Todo o nada: si un valor no
    es válido para el tipo, :class:`~geoblender.core.errors.GeoblenderError` y no se escribe
    nada. ``who`` es ``usuario@equipo`` y ``now`` la hora UTC ya formateada (sin reloj aquí)."""
    canonical = {prop: validate(kind, prop, raw, name=name) for prop, raw in values.items()}
    conn.executemany(
        "INSERT INTO gb_appearance (item_name, item_kind, prop, value, modified_at, modified_by) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (item_name, prop) DO UPDATE SET "
        "item_kind = excluded.item_kind, value = excluded.value, "
        "modified_at = excluded.modified_at, modified_by = excluded.modified_by",
        [(name, kind, prop, value, now, who) for prop, value in canonical.items()],
    )
    return canonical


def reset(conn: sqlite3.Connection, name: str, props: Iterable[str] | None = None) -> int:
    """Restablece el aspecto de ``name`` borrando sus filas (las de ``props``, o todas si es
    ``None``); devuelve cuántas borró."""
    if props is None:
        return conn.execute("DELETE FROM gb_appearance WHERE item_name = ?", (name,)).rowcount
    chosen = list(dict.fromkeys(props))
    if not chosen:
        return 0
    marks = ", ".join("?" for _ in chosen)
    return conn.execute(
        f"DELETE FROM gb_appearance WHERE item_name = ? AND prop IN ({marks})", (name, *chosen)
    ).rowcount
