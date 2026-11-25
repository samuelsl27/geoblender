# SPDX-License-Identifier: GPL-3.0-or-later
"""Migración del esquema 3 al 4: el aspecto de los elementos (spec 019; RF-019-07 a 09; ADR-0033).

:func:`apply` aplica ``core.project.schema.apply_schema_4``, lo mismo que hace crear un proyecto
tras el esquema 3: crea con ``IF NOT EXISTS`` la tabla ``gb_appearance`` y sus disparadores (solo
escribe Geoblender) y la declara en ``gpkg_extensions``. Así crear de cero y migrar dan el mismo
``sqlite_master`` y las mismas filas de ``gpkg_extensions``, y aplicarla otra vez no cambia nada
(idempotente, spec 002, I-2).

**No hay datos que migrar**: la tabla nace vacía (una fila existe solo si alguien cambió un
aspecto; el predefinido sale del catálogo) y no se toca ninguna otra tabla, ni ninguna huella ni
estado de seguimiento. ``min_reader_schema`` sigue en el que tenga el proyecto (:data:`MIGRATION`
no lo cambia, como la m0003): un Geoblender del esquema 3 abre el proyecto migrado entero en solo
lectura con el aviso de «versión más moderna» (RF-002-22) y ``checkout`` le dice «es de un
esquema posterior». La copia previa completa (``<Nombre>.gbproj.respaldo-esquema-3``), la
transacción, el contador de cambios de SQLite, la cabecera regenerada y el solo lectura de quien
no acepta migrar son de ``migrate_steps`` (spec 002), sin cambios.
"""

from __future__ import annotations

import sqlite3

from ..schema import apply_schema_4
from .base import Migration


def apply(conn: sqlite3.Connection) -> None:
    """Lleva la base del esquema 3 al 4 en la transacción de ``conn`` (de ``migrate_steps``,
    sin confirmar ni deshacer). Se puede aplicar más de una vez."""
    apply_schema_4(conn)


MIGRATION = Migration(3, 4, "aspecto de los elementos (spec 019)", apply, min_reader_schema=None)
"""La migración 3 → 4, en ``core.project.migrations.REGISTRY``."""
