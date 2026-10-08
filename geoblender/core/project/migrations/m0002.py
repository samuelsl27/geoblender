# SPDX-License-Identifier: GPL-3.0-or-later
"""Migración del esquema 1 al 2: la procedencia (spec 008 §8, último caso, y §11;
RF-002-20, RF-002-22; plan 008 §5.2.4 y §5.4.12; ADR-0006 §7; ADR-0025).

El esquema 2 es el 1 sin cambios más las tablas internas de la procedencia
(``core.provenance.schema``: parámetros, entradas, datos, operaciones, cifras, la caché de la
obsolescencia y lo ignorado, con sus índices y disparadores). :func:`apply`:

- crea lo que falte con ``CREATE … IF NOT EXISTS`` y declara en ``gpkg_extensions`` las
  tablas nuevas (``imga_geoblender``, ``write-only``), con
  ``core.provenance.schema.create_tables``, lo mismo que hace crear un proyecto;
- devuelve a las declaraciones que escribió la 002 (las tres tablas del 1) la definición de la
  extensión sin número de esquema (``core.gpkg.base.EXTENSION_DEFINITION``). Solo cambia las
  de Geoblender que tienen el texto antiguo (:data:`SCHEMA_1_DEFINITION`): las de otras
  extensiones y cualquier tabla del usuario quedan como estaban.

Así crear de cero y migrar dan el mismo ``sqlite_master`` y las mismas filas de
``gpkg_extensions``, y aplicarla otra vez no cambia nada (idempotente, spec 002, I-2).

No hay datos que migrar: un proyecto de la 002 no tiene parámetros, entradas ni operaciones.
``min_reader_schema`` sigue en 1 (:data:`MIGRATION` no lo cambia): las tablas del 1 no
cambian, así que un Geoblender de la 002 abre un proyecto migrado en solo lectura con su aviso
de «versión más moderna» (RF-002-22). La copia previa completa
(``<Nombre>.gbproj.respaldo-esquema-1``), la transacción, el contador de cambios de SQLite,
la cabecera regenerada y el solo lectura de quien no acepta migrar son de
``migrate_steps`` (spec 002), sin cambios.
"""

from __future__ import annotations

import sqlite3

from ...gpkg.base import EXTENSION_DEFINITION, EXTENSION_NAME
from ...provenance import schema as provenance_schema
from .base import Migration

SCHEMA_1_DEFINITION = "Geoblender — docs/arquitectura/datos/formato-proyecto.md (esquema 1)"
"""La definición de la extensión que escribía la spec 002 (con el número de esquema)."""


def apply(conn: sqlite3.Connection) -> None:
    """Lleva la base del esquema 1 al 2 en la transacción de ``conn`` (de
    ``migrate_steps``, sin confirmar ni deshacer). Se puede aplicar más de una vez."""
    provenance_schema.create_tables(conn)
    conn.execute(
        "UPDATE gpkg_extensions SET definition = ? WHERE extension_name = ? AND definition = ?",
        (EXTENSION_DEFINITION, EXTENSION_NAME, SCHEMA_1_DEFINITION),
    )


MIGRATION = Migration(1, 2, "procedencia (spec 008)", apply, min_reader_schema=None)
"""La migración 1 → 2, en ``core.project.migrations.REGISTRY``."""
