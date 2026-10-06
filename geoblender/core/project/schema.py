# SPDX-License-Identifier: GPL-3.0-or-later
"""Esquema 1 del GeoPackage del proyecto: tablas internas y sus disparadores (spec 002;
RF-002-05, RF-002-14, RF-002-15; ADR-0006; formato-proyecto §3.2 y §3.10; plan 002 §5.2).

Tablas internas, declaradas en ``gpkg_extensions`` (``imga_geoblender``, ``write-only``) y
fuera de ``gpkg_contents``: QGIS 4.2 las lista igualmente (spec 002, D-5), así que las
protegen disparadores:

- escritura solo desde una conexión de Geoblender: ``WHEN gb_writer() IS NOT 1``; en una
  conexión ajena (QGIS, GDAL) la función no existe y la sentencia ni se prepara;
- ``gb_project``: una sola fila, y la identidad y el CRS (``uid``, ``created_with``,
  ``crs_epsg``, ``crs_wkt``, ``vcrs_epsg``, ``vcrs_wkt``) no cambian nunca (cambiar el CRS
  de un proyecto con datos es R-79); un ``UPDATE`` que los escribe con el mismo valor sí
  pasa;
- ``gb_event`` y ``gb_schema_migration``: de solo inserción, también para Geoblender.

El ``CHECK`` del CRS vertical exige ``vcrs_note IS NOT NULL`` además de
``length(vcrs_note) > 0`` (la DDL del plan 002 §5.2 solo tiene lo segundo): con una nota
nula ``length`` da NULL, y SQLite solo rechaza un ``CHECK`` falso, no uno nulo; sin ello
pasaría un vertical local sin descripción (spec 002, T08).

``gb_writer()`` no es seguridad: evita que otro programa altere por error lo que solo
gestiona Geoblender. Las capas de dominio siguen admitiendo ``ALTER TABLE`` desde
cualquier programa. Un esquema publicado no cambia nunca: cualquier cambio sube
``SCHEMA_VERSION`` con su migración (spec 002 §6, I-3).
"""

from __future__ import annotations

import sqlite3

from ..gpkg.base import register_internal_table

SCHEMA_VERSION = 1
MIN_READER_SCHEMA = 1
INTERNAL_TABLES: tuple[str, ...] = ("gb_project", "gb_event", "gb_schema_migration")

_TABLES: dict[str, str] = {
    "gb_project": """CREATE TABLE gb_project (
  fid                INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid                TEXT     NOT NULL UNIQUE,
  name               TEXT     NOT NULL,
  code               TEXT,
  client             TEXT,
  description        TEXT,
  schema_version     INTEGER  NOT NULL CHECK (schema_version >= 1),
  min_reader_schema  INTEGER  NOT NULL CHECK (min_reader_schema BETWEEN 1 AND schema_version),
  created_with       TEXT     NOT NULL,
  last_written_with  TEXT     NOT NULL,
  crs_epsg           INTEGER  NOT NULL,
  crs_name           TEXT     NOT NULL,
  crs_wkt            TEXT     NOT NULL,
  vcrs_epsg          INTEGER,
  vcrs_name          TEXT     NOT NULL,
  vcrs_wkt           TEXT,
  vcrs_note          TEXT,
  origin_x           INTEGER  NOT NULL CHECK (origin_x % 100 = 0),
  origin_y           INTEGER  NOT NULL CHECK (origin_y % 100 = 0),
  origin_z           INTEGER  NOT NULL DEFAULT 0 CHECK (origin_z BETWEEN -10000 AND 10000),
  grid_step_m        DOUBLE   NOT NULL DEFAULT 1.0
                     CHECK (grid_step_m BETWEEN 0.5 AND 5.0
                            AND grid_step_m * 2 = CAST(grid_step_m * 2 AS INTEGER)),
  window_xmin        DOUBLE   NOT NULL,
  window_ymin        DOUBLE   NOT NULL,
  window_xmax        DOUBLE   NOT NULL,
  window_ymax        DOUBLE   NOT NULL,
  active_version_uid TEXT,
  created_at         DATETIME NOT NULL,
  modified_at        DATETIME NOT NULL,
  CHECK (window_xmin < window_xmax AND window_ymin < window_ymax),
  CHECK ((vcrs_epsg IS NULL AND vcrs_wkt IS NULL
          AND vcrs_note IS NOT NULL AND length(vcrs_note) > 0)
      OR (vcrs_epsg IS NOT NULL AND vcrs_wkt IS NOT NULL AND vcrs_note IS NULL))
)""",
    "gb_event": """CREATE TABLE gb_event (
  fid         INTEGER  PRIMARY KEY AUTOINCREMENT,
  at          DATETIME NOT NULL,
  user_host   TEXT     NOT NULL,
  session_uid TEXT,
  kind        TEXT     NOT NULL,
  entity_kind TEXT,
  entity_uid  TEXT,
  message     TEXT     NOT NULL,
  data        TEXT
)""",
    "gb_schema_migration": """CREATE TABLE gb_schema_migration (
  fid          INTEGER  PRIMARY KEY AUTOINCREMENT,
  from_version INTEGER  NOT NULL,
  to_version   INTEGER  NOT NULL,
  applied_at   DATETIME NOT NULL,
  applied_with TEXT     NOT NULL,
  backup_dir   TEXT     NOT NULL,
  user_host    TEXT     NOT NULL
)""",
}

_WRITER_ONLY = "solo Geoblender escribe en esta tabla interna (gb_writer)"
_APPEND_ONLY = "registro de solo inserción: no se modifica ni se borra"
_IDENTITY_COLUMNS = ("uid", "created_with", "crs_epsg", "crs_wkt", "vcrs_epsg", "vcrs_wkt")


def _trigger(name: str, timing: str, table: str, when: str | None, message: str) -> str:
    condition = f"\nWHEN {when}" if when else ""
    text = f"{table}: {message}".replace("'", "''")
    return (
        f"CREATE TRIGGER {name} {timing} ON {table}{condition}\n"
        f"BEGIN SELECT RAISE(ABORT, '{text}'); END"
    )


def _triggers() -> dict[str, str]:
    writer = "gb_writer() IS NOT 1"
    changed = " OR ".join(f"NEW.{column} IS NOT OLD.{column}" for column in _IDENTITY_COLUMNS)
    triggers = {
        "gb_project_single": _trigger(
            "gb_project_single",
            "BEFORE INSERT",
            "gb_project",
            "(SELECT count(*) FROM gb_project) > 0",
            "solo puede haber una fila, la identidad del proyecto",
        ),
        "gb_project_identity": _trigger(
            "gb_project_identity",
            f"BEFORE UPDATE OF {', '.join(_IDENTITY_COLUMNS)}",
            "gb_project",
            changed,
            "la identidad y el CRS del proyecto no cambian nunca",
        ),
    }
    for kind in ("INSERT", "UPDATE", "DELETE"):
        name = f"gb_project_w_{kind.lower()[:3]}"
        triggers[name] = _trigger(name, f"BEFORE {kind}", "gb_project", writer, _WRITER_ONLY)
    for table in ("gb_event", "gb_schema_migration"):
        triggers[f"{table}_w_ins"] = _trigger(
            f"{table}_w_ins", "BEFORE INSERT", table, writer, _WRITER_ONLY
        )
        triggers[f"{table}_no_upd"] = _trigger(
            f"{table}_no_upd", "BEFORE UPDATE", table, None, _APPEND_ONLY
        )
        triggers[f"{table}_no_del"] = _trigger(
            f"{table}_no_del", "BEFORE DELETE", table, None, _APPEND_ONLY
        )
    return triggers


TRIGGERS: dict[str, str] = _triggers()


def create_schema(conn: sqlite3.Connection) -> None:
    """Crea las tablas internas del esquema 1, sus disparadores y su declaración en
    ``gpkg_extensions``, en la transacción de ``conn`` (tras ``core.gpkg.base.
    create_base``)."""
    for table, ddl in _TABLES.items():
        conn.execute(ddl)
        register_internal_table(conn, table)
    for ddl in TRIGGERS.values():
        conn.execute(ddl)


def missing_objects(conn: sqlite3.Connection) -> list[str]:
    """Lo que le falta a la base para tener el esquema 1 (``"table gb_event"``,
    ``"trigger gb_event_no_upd"``…), en orden; lista vacía si está completo."""
    present = set(
        conn.execute(
            "SELECT type || ' ' || name FROM sqlite_master WHERE type IN ('table', 'trigger')"
        ).fetchall()
    )
    expected = [f"table {table}" for table in _TABLES] + [f"trigger {name}" for name in TRIGGERS]
    return [item for item in expected if (item,) not in present]
