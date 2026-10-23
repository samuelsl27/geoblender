# SPDX-License-Identifier: GPL-3.0-or-later
"""Migración del esquema 2 al 3: versiones y revisiones (spec 009; RF-009-02, RF-009-04,
RF-009-12, RF-009-23; RF-002-20, RF-002-22; plan 009 §5.2.3 y D-24; ADR-0006 §7; ADR-0013).

:func:`apply` aplica ``core.versions.schema.apply_schema_3``, lo mismo que hace crear un
proyecto tras el esquema 2: crea con ``IF NOT EXISTS`` las tablas de las versiones, las
revisiones, lo congelado y las decisiones de la propiedad, con sus índices y sus disparadores,
y las declara en ``gpkg_extensions``; añade a ``gb_dataset`` y ``gb_operation`` sus columnas
nuevas si faltan (``ALTER TABLE … ADD COLUMN``: no copia ni mueve filas); y rehace el índice de
nombres vivos y los disparadores que las nombran si no lo están. Así crear de cero y migrar dan
el mismo ``sqlite_master`` y las mismas filas de ``gpkg_extensions``, y aplicarla otra vez no
cambia nada (idempotente, spec 002, I-2).

**No hay datos que migrar**: un proyecto del esquema 2 no tiene versiones, y todo lo que tiene
es del proyecto (``version_uid = ''``, ``revision_uid = ''``); ninguna fila ni ningún fichero
fuera de la base y la cabecera cambia, y ningún hash de contenido tampoco. ``min_reader_schema``
sigue en 1 (:data:`MIGRATION` no lo cambia, D-24): un Geoblender del esquema 2 abre el proyecto
migrado entero en solo lectura con el aviso de «versión más moderna» (RF-002-22); lo sube a 3
crear la primera versión. La copia previa completa
(``<Nombre>.gbproj.respaldo-esquema-2``), la transacción, el contador de cambios de SQLite, la
cabecera regenerada y el solo lectura de quien no acepta migrar son de ``migrate_steps`` (spec
002), sin cambios.
"""

from __future__ import annotations

import sqlite3

from ...versions.schema import apply_schema_3
from .base import Migration


def apply(conn: sqlite3.Connection) -> None:
    """Lleva la base del esquema 2 al 3 en la transacción de ``conn`` (de ``migrate_steps``,
    sin confirmar ni deshacer). Se puede aplicar más de una vez."""
    apply_schema_3(conn)


MIGRATION = Migration(2, 3, "versiones y revisiones (spec 009)", apply, min_reader_schema=None)
"""La migración 2 → 3, en ``core.project.migrations.REGISTRY``."""
