# SPDX-License-Identifier: GPL-3.0-or-later
"""Esquema del GeoPackage del proyecto: tablas internas y sus disparadores (spec 002;
RF-002-05, RF-002-14, RF-002-15, RF-002-20, RF-002-22; ADR-0006; formato-proyecto §3.2 y
§3.10; plan 002 §5.2; spec 008, plan §5.2).

- **Esquema 1** (spec 002): ``gb_project``, ``gb_event`` y ``gb_schema_migration``.
- **Esquema 2** (spec 008): el 1 sin cambios más las tablas de la procedencia
  (``core.provenance.schema``: parámetros, entradas, datos, operaciones, cifras, la caché de
  obsolescencia y lo ignorado). ``min_reader_schema`` sigue en 1: como las tablas del 1 no
  cambian, un Geoblender de la 002 abre un proyecto del 2 en solo lectura con el aviso de
  «versión más moderna» (RF-002-22).
- **Esquema 3** (spec 009): el 2 más las versiones, sus revisiones, lo congelado y las
  decisiones de la propiedad (``core.versions.schema``), con la versión de cada dato, su título
  y la revisión de cada operación en las tablas de la 008. ``min_reader_schema`` sigue en 1 al
  migrar: un proyecto sin versiones no tiene nada que un Geoblender del 2 lea mal; lo sube a 3
  crear la primera versión (plan 009, D-24). Un proyecto nuevo se crea directamente en el 3 (el
  2 y después ``apply_schema_3``, lo mismo que hace migrar); uno anterior se migra
  (``core.project.migrations``).

:func:`missing_objects` echa en falta lo de un esquema concreto: al abrir, lo del 1 para leer
``gb_project`` y después lo del esquema del proyecto (de uno posterior, lo que conoce esta
versión).

Tablas internas, declaradas en ``gpkg_extensions`` (``imga_geoblender``, ``write-only``) y
fuera de ``gpkg_contents``: QGIS 4.2 las lista igualmente (spec 002, D-5), así que las
protegen disparadores (los de las tablas del 1, aquí; los de la procedencia, en
``core.provenance.schema``):

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

La fila única de ``gb_project`` se escribe y se lee como ``core.project.model.
ProjectRecord`` (:func:`insert_project`, :func:`read_project`), y las migraciones
registradas, con :func:`read_migrations`.

``gb_writer()`` no es seguridad: evita que otro programa altere por error lo que solo
gestiona Geoblender. Las capas de dominio siguen admitiendo ``ALTER TABLE`` desde
cualquier programa. Un esquema publicado no cambia nunca: cualquier cambio sube
``SCHEMA_VERSION`` con su migración (spec 002 §6, I-3).
"""

from __future__ import annotations

import functools
import sqlite3

from ..gpkg.base import create_structure, register_internal_table
from ..provenance import schema as provenance_schema
from ..versions import schema as versions_schema
from .model import ProjectRecord

SCHEMA_VERSION = 3
MIN_READER_SCHEMA = 1
SCHEMA_1_TABLES: tuple[str, ...] = ("gb_project", "gb_event", "gb_schema_migration")
INTERNAL_TABLES: tuple[str, ...] = (
    SCHEMA_1_TABLES + provenance_schema.INTERNAL_TABLES + versions_schema.INTERNAL_TABLES
)
"""Las tablas internas del esquema de esta versión: las del 1, las de la procedencia (2) y las
de las versiones (3)."""

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
    """Crea el esquema de esta versión (:data:`SCHEMA_VERSION`, el 3): las tablas internas
    del 1, sus disparadores y su declaración en ``gpkg_extensions``, las de la procedencia
    (``core.provenance.schema.create_tables``: el esquema 2) y después lo del 3
    (``core.versions.schema.apply_schema_3``, lo mismo que hace la migración 2 → 3), en la
    transacción de ``conn`` (tras ``core.gpkg.base.create_base``).

    Las tablas y las columnas del 3 se crean antes que los índices y los disparadores: cada
    ``ALTER TABLE … ADD COLUMN`` vuelve a leer el esquema entero, y con los disparadores ya
    creados crear un proyecto costaría 2 ms más (las pruebas crean cientos). El resultado es
    el mismo ``sqlite_master`` que migrar (lo comprueba ``test_migration_0003``)."""
    for table, ddl in _TABLES.items():
        conn.execute(ddl)
        register_internal_table(conn, table)
    provenance_schema.create_tables(conn, tables_only=True)
    versions_schema.add_columns(conn)
    for ddl in TRIGGERS.values():
        conn.execute(ddl)
    provenance_schema.create_tables(conn)
    versions_schema.apply_schema_3(conn)


@functools.cache
def base_image() -> bytes:
    """La base de un proyecto nuevo sin sus filas propias, como imagen de un fichero SQLite
    (tarea 009/T34; RNF-001-01): la estructura GeoPackage con las filas del estándar
    (``core.gpkg.base.create_structure``) y el esquema de esta versión (:func:`create_schema`),
    hechos una vez por proceso en una base en memoria (``sqlite3.Connection.serialize``).

    Crear un proyecto escribe la imagen y añade, en una transacción, el CRS del proyecto, su
    fila de ``gb_project`` y su evento (``core.project.create``): el mismo ``sqlite_master``
    (tipo, nombre, tabla y SQL, en su orden) y las mismas filas que hacerlo todo en la base,
    en ≈ 3 ms en vez de ≈ 9 ms (sus ≈ 140 objetos, con los 106 disparadores, cuestan a SQLite
    ≈ 5,5 ms; las pruebas crean miles de proyectos). Solo cambian las páginas en que SQLite
    guarda cada tabla. La imagen es inmutable (``bytes``) y no está en WAL (formato 1)."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        conn.execute("BEGIN")
        create_structure(conn)
        create_schema(conn)
        conn.execute("COMMIT")
        return conn.serialize()
    finally:
        conn.close()


def missing_objects(conn: sqlite3.Connection, version: int) -> list[str]:
    """Lo que le falta a la base para tener el esquema ``version`` (``"table gb_event"``,
    ``"trigger gb_event_no_upd"``, ``"index gb_figure_key"``…), en orden: lo del 1;
    desde el 2, lo de la procedencia, y desde el 3, lo de las versiones
    (``core.versions.schema.missing_objects``); lista vacía si está completo. De un esquema
    posterior al de esta versión se echa en falta lo que esta conoce (:data:`SCHEMA_VERSION`):
    uno posterior que se pueda leer (``min_reader_schema``) lo conserva.

    ``TypeError`` si ``version`` no es un entero y ``ValueError`` si es menor que 1."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError(f"el esquema es un entero, no {version!r}")
    if version < 1:
        raise ValueError(f"no hay esquema {version}: el primero es el 1")
    present = set(
        conn.execute(
            "SELECT type || ' ' || name FROM sqlite_master WHERE type IN ('table', 'trigger')"
        ).fetchall()
    )
    expected = [f"table {table}" for table in _TABLES] + [f"trigger {name}" for name in TRIGGERS]
    missing = [item for item in expected if (item,) not in present]
    if min(version, SCHEMA_VERSION) >= 2:
        missing += provenance_schema.missing_objects(conn)
    if min(version, SCHEMA_VERSION) >= 3:
        missing += versions_schema.missing_objects(conn)
    return missing


def insert_project(conn: sqlite3.Connection, record: ProjectRecord) -> None:
    """Escribe la fila única de ``gb_project`` (en una transacción de una conexión de
    escritura de Geoblender, que tiene ``gb_writer()``)."""
    row = record.as_row()
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO gb_project ({names}) VALUES ({marks})", tuple(row.values()))


def read_project(conn: sqlite3.Connection) -> ProjectRecord | None:
    """La fila de ``gb_project`` como :class:`ProjectRecord`, o ``None`` si no la hay."""
    columns = ProjectRecord.columns()
    row = conn.execute(f"SELECT {', '.join(columns)} FROM gb_project").fetchone()
    return None if row is None else ProjectRecord.from_row(dict(zip(columns, row, strict=True)))


def read_migrations(conn: sqlite3.Connection) -> tuple[tuple[int, int], ...]:
    """Las migraciones registradas en ``gb_schema_migration``, (de, a), en orden."""
    rows = conn.execute(
        "SELECT from_version, to_version FROM gb_schema_migration ORDER BY fid"
    ).fetchall()
    return tuple((int(low), int(high)) for low, high in rows)
