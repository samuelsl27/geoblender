# SPDX-License-Identifier: GPL-3.0-or-later
"""La topografía en Blender (código ``gis``, spec 006; plan 006 §5.1 y §5.6; ADR-0025 §2).

Hoy (T40) solo da a la 008 los lectores de contenido de ``gis`` (``gis.content``,
RF-006-26, RF-008-09): :func:`register` los registra en ``core.content`` con el lector de
tablas de texto de ``interop`` (``gis`` no puede importarlo, ARQ-07) y :func:`unregister` los
quita, simétricos e idempotentes. Así la lista estática del trabajo ``core_content_hash``
(``workers/core_content_hash.py``) coincide con lo que registra Blender. T26 añade aquí los
trabajos y las definiciones de parámetros; los operadores, T28 y siguientes.
"""

from __future__ import annotations

from collections.abc import Callable

from ...core.content import readers as content_readers
from ...gis import content
from ...interop.csv_tables import read_table

classes: tuple[type, ...] = ()
"""Los operadores de ``gis`` (aún ninguno)."""

_UNDO: list[Callable[[], None]] = []


def register() -> None:
    """Da a los lectores de ``gis`` el lector de tablas de ``interop`` y registra los que aún
    no están; idempotente."""
    if content.table_reader() is None:
        content.use_table_reader(read_table)
        _UNDO.append(_forget_table_reader)
    for reader in content.CONTENT_READERS:
        if reader.id not in content_readers.READERS:
            content_readers.register_reader(reader)
            _UNDO.append(_unregister_reader(reader))


def unregister() -> None:
    """Quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo); idempotente."""
    while _UNDO:
        _UNDO.pop()()


def _unregister_reader(reader: content_readers.ContentReader) -> Callable[[], None]:
    def undo() -> None:
        if content_readers.READERS.get(reader.id) is reader:
            content_readers.unregister_reader(reader.id)

    return undo


def _forget_table_reader() -> None:
    if content.table_reader() is read_table:
        content.use_table_reader(None)
