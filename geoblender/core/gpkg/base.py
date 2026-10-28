# SPDX-License-Identifier: GPL-3.0-or-later
"""Estructura GeoPackage 1.4 del proyecto (spec 002; RF-002-14; ADR-0006;
formato-proyecto §3.1; plan 002 §5.2 y §6).

- :func:`create_base`: ``application_id`` (``GPKG``) y ``user_version`` (10400), las
  tablas obligatorias del estándar (``gpkg_spatial_ref_sys``, ``gpkg_contents``,
  ``gpkg_geometry_columns``) y ``gpkg_extensions``, con las filas −1, 0 y 4326 del
  estándar (:func:`create_structure`) y la del CRS horizontal del proyecto con su WKT1 del
  catálogo (:func:`insert_srs`). El CRS vertical
  es un dato del proyecto (``gb_project``): las capas usan el EPSG horizontal, lo más
  compatible con QGIS, DXF y otros (plan 002 §6).
- :func:`register_internal_table`: una tabla interna ``gb_*`` se declara en
  ``gpkg_extensions`` con la extensión ``imga_geoblender`` en alcance ``write-only`` (con
  ``read-write`` GDAL avisa al leer) y no se registra en ``gpkg_contents``: QGIS 4.2 la
  lista igualmente y la protegen los disparadores (spec 002, D-5).
- :func:`create_feature_table` y :func:`create_attribute_table`: capas y tablas de
  atributos registradas, con ``fid INTEGER PRIMARY KEY AUTOINCREMENT``.
- :func:`set_column_titles`: los títulos (alias) de las columnas de una capa o tabla
  registrada, que QGIS muestra en lugar del nombre (spec 005, T36; RF-005-01). Van en
  ``gpkg_data_columns`` (extensión ``gpkg_schema``), en ``name`` y en ``title``: el GDAL de
  QGIS 4.2 (3.13.1) toma el alias de ``name`` y no lee ``title``. Las dos tablas de la
  extensión y sus filas en ``gpkg_extensions`` se crean la primera vez que un módulo pone
  títulos: un proyecto nuevo o migrado no las tiene.
- :func:`create_index`: un índice de una capa o tabla, único o no, con columnas que se
  comparan sin distinguir mayúsculas (``COLLATE NOCASE``), con el nombre de
  :func:`index_name` (spec 005, T36).

Todas reciben la conexión de una transacción de escritura
(``GpkgConnection.transaction()``) y no la confirman.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..errors import ValidationError
from ..georef.crs import CrsRef
from .wkb import WKB_TYPES

APPLICATION_ID = 1196444487  # 0x47504B47, «GPKG»
USER_VERSION = 10400  # GeoPackage 1.4.0
GPKG_VERSION = "1.4.0"
EXTENSION_NAME = "imga_geoblender"
# Sin número de esquema (spec 008, plan §5.1): el esquema lo dice gb_project, y la
# declaración de una tabla no cambia al migrar.
EXTENSION_DEFINITION = "Geoblender — docs/arquitectura/datos/formato-proyecto.md"
EXTENSION_SCOPE = "write-only"
GEOMETRY_COLUMN = "geom"
COLUMN_TYPES: frozenset[str] = frozenset(
    {"INTEGER", "DOUBLE", "TEXT", "BOOLEAN", "BLOB", "DATE", "DATETIME"}
)
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_RESERVED_COLUMNS = frozenset({"fid", GEOMETRY_COLUMN})
_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
# Extensión «schema» de GeoPackage 1.4 (anexo F.9): los títulos de las columnas. La
# definición y el alcance, los que escribe el GDAL de QGIS 4.2 (3.13.1) al poner un alias y
# los que exige su validate_gpkg.py (read-write, sin columna, una fila por tabla).
DATA_COLUMNS_TABLE = "gpkg_data_columns"
DATA_COLUMN_CONSTRAINTS_TABLE = "gpkg_data_column_constraints"
SCHEMA_EXTENSION = "gpkg_schema"
SCHEMA_EXTENSION_DEFINITION = "http://www.geopackage.org/spec121/#extension_schema"
SCHEMA_EXTENSION_SCOPE = "read-write"
INDEX_PREFIX = "idx_"
"""El prefijo del nombre de un índice de :func:`create_index` (:func:`index_name`)."""

# GeoPackage 1.4, tabla 21 (WKT de EPSG:4326 que exige el estándar).
WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,'
    'AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG",'
    '"9122"]],AUTHORITY["EPSG","4326"]]'
)
_STANDARD_SRS: tuple[tuple[str, int, str, int, str, str], ...] = (
    (
        "Undefined cartesian SRS",
        -1,
        "NONE",
        -1,
        "undefined",
        "undefined cartesian coordinate reference system",
    ),
    (
        "Undefined geographic SRS",
        0,
        "NONE",
        0,
        "undefined",
        "undefined geographic coordinate reference system",
    ),
    (
        "WGS 84 geodetic",
        4326,
        "EPSG",
        4326,
        WGS84_WKT,
        "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid",
    ),
)

_DDL: tuple[str, ...] = (
    """CREATE TABLE gpkg_spatial_ref_sys (
  srs_name TEXT NOT NULL,
  srs_id INTEGER PRIMARY KEY,
  organization TEXT NOT NULL,
  organization_coordsys_id INTEGER NOT NULL,
  definition TEXT NOT NULL,
  description TEXT
)""",
    f"""CREATE TABLE gpkg_contents (
  table_name TEXT NOT NULL PRIMARY KEY,
  data_type TEXT NOT NULL,
  identifier TEXT UNIQUE,
  description TEXT DEFAULT '',
  last_change DATETIME NOT NULL DEFAULT ({_NOW}),
  min_x DOUBLE,
  min_y DOUBLE,
  max_x DOUBLE,
  max_y DOUBLE,
  srs_id INTEGER,
  CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
)""",
    """CREATE TABLE gpkg_geometry_columns (
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  geometry_type_name TEXT NOT NULL,
  srs_id INTEGER NOT NULL,
  z TINYINT NOT NULL,
  m TINYINT NOT NULL,
  CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
  CONSTRAINT uk_gc_table_name UNIQUE (table_name),
  CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
  CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id)
)""",
    """CREATE TABLE gpkg_extensions (
  table_name TEXT,
  column_name TEXT,
  extension_name TEXT NOT NULL,
  definition TEXT NOT NULL,
  scope TEXT NOT NULL,
  CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
)""",
)

# Las tablas de la extensión «schema» con la estructura de GeoPackage 1.4, como las crea el
# GDAL de QGIS 4.2 (``min_is_inclusive`` y ``max_is_inclusive``, no los nombres de la 1.0).
_SCHEMA_DDL: dict[str, str] = {
    DATA_COLUMNS_TABLE: f"""CREATE TABLE {DATA_COLUMNS_TABLE} (
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  name TEXT,
  title TEXT,
  description TEXT,
  mime_type TEXT,
  constraint_name TEXT,
  CONSTRAINT pk_gdc PRIMARY KEY (table_name, column_name),
  CONSTRAINT gdc_tn UNIQUE (table_name, name)
)""",
    DATA_COLUMN_CONSTRAINTS_TABLE: f"""CREATE TABLE {DATA_COLUMN_CONSTRAINTS_TABLE} (
  constraint_name TEXT NOT NULL,
  constraint_type TEXT NOT NULL,
  value TEXT,
  min NUMERIC,
  min_is_inclusive BOOLEAN,
  max NUMERIC,
  max_is_inclusive BOOLEAN,
  description TEXT,
  CONSTRAINT gdcc_ntv UNIQUE (constraint_name, constraint_type, value)
)""",
}


@dataclass(frozen=True)
class ColumnDef:
    """Una columna de una capa o tabla: nombre (identificador en minúsculas), tipo del
    estándar (``COLUMN_TYPES``), ``NOT NULL`` y valor por defecto en SQL (``"''"``,
    ``"0"``…), o ``None``."""

    name: str
    sql_type: str
    not_null: bool = False
    default: str | None = None

    def sql(self) -> str:
        """La definición de la columna para ``CREATE TABLE``."""
        parts = [f'"{self.name}"', self.sql_type]
        if self.not_null:
            parts.append("NOT NULL")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        return " ".join(parts)


def _invalid(code: str, reason: str, field: str, value: object) -> ValidationError:
    return ValidationError(
        f"core.gpkg_{code}", reason, obj="GeoPackage del proyecto", field=field, value=value
    )


def _check_name(name: str, field: str) -> str:
    if not isinstance(name, str) or not _IDENTIFIER.match(name):
        raise _invalid(
            "name_invalid",
            "debe ser un identificador en minúsculas (letras, cifras y «_», empezando por "
            "una letra, hasta 63 caracteres)",
            field,
            name,
        )
    return name


def _check_columns(columns: Sequence[ColumnDef]) -> list[str]:
    seen: set[str] = set()
    for column in columns:
        _check_name(column.name, "columna")
        if column.name in _RESERVED_COLUMNS or column.name in seen:
            reason = "está reservada (fid, geom) o repetida"
            raise _invalid("column_reserved", reason, "columna", column.name)
        if column.sql_type not in COLUMN_TYPES:
            reason = f"tipo no admitido; los admitidos son {', '.join(sorted(COLUMN_TYPES))}"
            raise _invalid("column_type", reason, "tipo de columna", column.sql_type)
        seen.add(column.name)
    return [column.sql() for column in columns]


_INSERT_SRS = (
    "INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
    "organization_coordsys_id, definition, description) VALUES (?, ?, ?, ?, ?, ?)"
)


def create_base(conn: sqlite3.Connection, crs: CrsRef) -> None:
    """Crea la estructura GeoPackage 1.4 con el CRS horizontal del proyecto
    (:func:`create_structure` e :func:`insert_srs`)."""
    create_structure(conn)
    insert_srs(conn, crs)


def create_structure(conn: sqlite3.Connection) -> None:
    """La estructura GeoPackage 1.4 sin el CRS del proyecto: ``application_id``,
    ``user_version``, las tablas del estándar y sus filas −1, 0 y 4326 (la base de un
    proyecto nuevo la hace una vez por proceso: ``core.project.schema.base_image``; tarea
    009/T34)."""
    conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version = {USER_VERSION}")
    for statement in _DDL:
        conn.execute(statement)
    conn.executemany(_INSERT_SRS, _STANDARD_SRS)


def insert_srs(conn: sqlite3.Connection, crs: CrsRef) -> None:
    """La fila del CRS horizontal ``crs`` en ``gpkg_spatial_ref_sys``, con su WKT1 del
    catálogo (tras :func:`create_structure`)."""
    conn.execute(_INSERT_SRS, (crs.name, crs.epsg, "EPSG", crs.epsg, crs.wkt1, crs.area or None))


def register_internal_table(conn: sqlite3.Connection, table_name: str) -> None:
    """Declara una tabla interna de Geoblender en ``gpkg_extensions`` (``write-only``);
    no la registra en ``gpkg_contents``."""
    _check_name(table_name, "tabla")
    conn.execute(
        "INSERT INTO gpkg_extensions (table_name, column_name, extension_name, "
        "definition, scope) VALUES (?, NULL, ?, ?, ?)",
        (table_name, EXTENSION_NAME, EXTENSION_DEFINITION, EXTENSION_SCOPE),
    )


def _srs_exists(conn: sqlite3.Connection, srs_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM gpkg_spatial_ref_sys WHERE srs_id = ?", (srs_id,)
    ).fetchone()
    return row is not None


def create_feature_table(
    conn: sqlite3.Connection,
    name: str,
    geometry_type: str,
    srs_id: int,
    has_z: bool,
    columns: Sequence[ColumnDef],
    identifier: str,
    description: str = "",
) -> None:
    """Crea una capa con geometría ``geom`` y la registra en ``gpkg_contents`` y
    ``gpkg_geometry_columns`` (``z`` = 1 con Z, 0 sin ella; sin M)."""
    _check_name(name, "tabla")
    definitions = _check_columns(columns)
    kind = str(geometry_type).upper()
    if kind not in WKB_TYPES:
        reason = f"tipo de geometría no admitido; los admitidos son {', '.join(WKB_TYPES)}"
        raise _invalid("geometry_type", reason, "tipo de geometría", geometry_type)
    if isinstance(srs_id, bool) or not isinstance(srs_id, int) or not _srs_exists(
        conn, srs_id
    ):
        reason = "no está en gpkg_spatial_ref_sys (las capas usan el CRS del proyecto)"
        raise _invalid("srs_unknown", reason, "SRS", srs_id)
    body = ", ".join(
        ["fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL", f"{GEOMETRY_COLUMN} {kind}"]
        + definitions
    )
    conn.execute(f'CREATE TABLE "{name}" ({body})')
    conn.execute(
        "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
        "srs_id) VALUES (?, 'features', ?, ?, ?)",
        (name, identifier, description, srs_id),
    )
    conn.execute(
        "INSERT INTO gpkg_geometry_columns (table_name, column_name, "
        "geometry_type_name, srs_id, z, m) VALUES (?, ?, ?, ?, ?, 0)",
        (name, GEOMETRY_COLUMN, kind, srs_id, 1 if has_z else 0),
    )


def create_attribute_table(
    conn: sqlite3.Connection,
    name: str,
    columns: Sequence[ColumnDef],
    identifier: str,
    description: str = "",
) -> None:
    """Crea una tabla sin geometría y la registra en ``gpkg_contents`` como
    ``attributes`` (sin SRS)."""
    _check_name(name, "tabla")
    definitions = _check_columns(columns)
    body = ", ".join(["fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL", *definitions])
    conn.execute(f'CREATE TABLE "{name}" ({body})')
    conn.execute(
        "INSERT INTO gpkg_contents (table_name, data_type, identifier, description) "
        "VALUES (?, 'attributes', ?, ?)",
        (name, identifier, description),
    )


# --- Títulos e índices (spec 005, T36) ----------------------------------------------------------


def _quote(identifier: str) -> str:
    """Un identificador de SQLite entre comillas dobles (las de dentro, dobladas)."""
    return '"' + identifier.replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return row is not None


def _existing_table(conn: sqlite3.Connection, table: str) -> list[str]:
    """Las columnas de ``table`` (un identificador del proyecto que existe), en su orden;
    ``ValidationError`` si el nombre no es válido o la tabla no existe."""
    _check_name(table, "tabla")
    if not _table_exists(conn, table):
        raise _invalid("table_unknown", "no existe en la base de datos", "tabla", table)
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote(table)})")]


def _known_column(columns: Sequence[str], table: str, column: object) -> str:
    if not isinstance(column, str) or column not in columns:
        reason = f"la tabla «{table}» no tiene esa columna"
        raise _invalid("column_unknown", reason, "columna", column)
    return column


def _create_schema_tables(conn: sqlite3.Connection) -> None:
    """Las dos tablas de la extensión «schema» y sus filas en ``gpkg_extensions``, las que
    falten (también si otro programa creó una tabla sin declararla)."""
    for table, ddl in _SCHEMA_DDL.items():
        if not _table_exists(conn, table):
            conn.execute(ddl)
        declared = conn.execute(
            "SELECT 1 FROM gpkg_extensions WHERE table_name = ? AND extension_name = ?",
            (table, SCHEMA_EXTENSION),
        ).fetchone()
        if declared is None:
            conn.execute(
                "INSERT INTO gpkg_extensions (table_name, column_name, extension_name, "
                "definition, scope) VALUES (?, NULL, ?, ?, ?)",
                (table, SCHEMA_EXTENSION, SCHEMA_EXTENSION_DEFINITION, SCHEMA_EXTENSION_SCOPE),
            )


def set_column_titles(
    conn: sqlite3.Connection, table: str, titles: Mapping[str, str]
) -> None:
    """Pone a las columnas de la capa o tabla ``table`` (registrada en ``gpkg_contents``) los
    títulos de ``titles`` (columna → título), que QGIS muestra como alias de cada campo
    (RF-005-01; plan 005 §5.2.1).

    Cada título va a ``gpkg_data_columns`` en ``name`` y en ``title``: el estándar llama
    ``title`` al título, pero el GDAL de QGIS 4.2 (3.13.1) toma el alias de ``name`` y no lee
    ``title``. La primera vez crea ``gpkg_data_columns`` y ``gpkg_data_column_constraints`` y
    las declara en ``gpkg_extensions`` (``gpkg_schema``, ``read-write``); sin títulos no crea
    nada. Volver a llamarla cambia los títulos de esas columnas y deja los de las demás y lo
    que otro programa escribió en sus filas (``description``…).

    Rechaza sin escribir nada, con ``ValidationError``: una tabla que no existe
    (``core.gpkg_table_unknown``) o que no está en ``gpkg_contents``
    (``core.gpkg_table_unregistered``), un nombre que no es un identificador, una columna
    que no tiene (``core.gpkg_column_unknown``), un título que no es un texto con algo
    escrito (``core.gpkg_title_invalid``) y dos columnas de la tabla con el mismo título sin
    distinguir mayúsculas (``core.gpkg_title_repeated``); ``TypeError`` si ``titles`` no es
    un diccionario."""
    if not isinstance(titles, Mapping):
        raise TypeError(f"los títulos son un diccionario columna → título, no {titles!r}")
    columns = _existing_table(conn, table)
    registered = conn.execute(
        "SELECT 1 FROM gpkg_contents WHERE table_name = ?", (table,)
    ).fetchone()
    if registered is None:
        reason = "no es una capa ni una tabla registrada en gpkg_contents"
        raise _invalid("table_unregistered", reason, "tabla", table)
    wanted: dict[str, str] = {}
    for column, title in titles.items():
        _known_column(columns, table, column)
        if not isinstance(title, str) or not title.strip():
            reason = "un título es un texto con algo escrito"
            raise _invalid("title_invalid", reason, f"título de «{column}»", title)
        wanted[column] = title
    if not wanted:
        return
    existing: dict[str, str] = {}
    if _table_exists(conn, DATA_COLUMNS_TABLE):
        existing = {
            str(column): str(name)
            for column, name in conn.execute(
                f"SELECT column_name, name FROM {DATA_COLUMNS_TABLE} "
                "WHERE table_name = ? AND name IS NOT NULL",
                (table,),
            )
        }
    seen: dict[str, str] = {}
    for column, title in {**existing, **wanted}.items():
        other = seen.setdefault(title.casefold(), column)
        if other != column:
            reason = f"es ya el título de la columna «{other}» de «{table}»"
            raise _invalid("title_repeated", reason, f"título de «{column}»", title)
    _create_schema_tables(conn)
    marks = ", ".join("?" for _ in wanted)
    # Sin el título de antes primero: intercambiar dos títulos chocaría con UNIQUE (tabla, name).
    conn.execute(
        f"UPDATE {DATA_COLUMNS_TABLE} SET name = NULL "
        f"WHERE table_name = ? AND column_name IN ({marks})",
        (table, *wanted),
    )
    conn.executemany(
        f"INSERT INTO {DATA_COLUMNS_TABLE} (table_name, column_name, name, title) "
        "VALUES (?, ?, ?, ?) ON CONFLICT (table_name, column_name) "
        "DO UPDATE SET name = excluded.name, title = excluded.title",
        [(table, column, title, title) for column, title in wanted.items()],
    )


def _registered_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Las columnas de ``table``, que existe y está en ``gpkg_contents``."""
    columns = _existing_table(conn, table)
    registered = conn.execute(
        "SELECT 1 FROM gpkg_contents WHERE table_name = ?", (table,)
    ).fetchone()
    if registered is None:
        reason = "no es una capa ni una tabla registrada en gpkg_contents"
        raise _invalid("table_unregistered", reason, "tabla", table)
    return columns


def _enum_values(values: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Los pares (código, texto) de una lista de valores, comprobados."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, str) or not isinstance(item, Sequence) or len(item) != 2:
            reason = "cada valor es un par (código, texto)"
            raise _invalid("enum_invalid", reason, "valor de la lista", item)
        code, text = item
        if not isinstance(code, str) or not code.strip():
            reason = "un código es un texto con algo escrito"
            raise _invalid("enum_invalid", reason, "código de la lista", code)
        if not isinstance(text, str) or not text.strip():
            reason = "el texto de un código es un texto con algo escrito"
            raise _invalid("enum_invalid", reason, f"texto de «{code}»", text)
        if code in seen:
            raise _invalid("enum_invalid", "está repetido en la lista", "código de la lista",
                           code)
        seen.add(code)
        pairs.append((code, text))
    if not pairs:
        raise _invalid("enum_invalid", "una lista de valores tiene al menos uno",
                       "lista de valores", "vacía")
    return pairs


def set_column_enum(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    values: Sequence[tuple[str, str]],
    *,
    name: str | None = None,
) -> str:
    """Pone a la columna ``column`` de la capa o tabla ``table`` (registrada en
    ``gpkg_contents``) la lista de valores ``values`` (pares código → texto para las personas)
    y devuelve el nombre de la lista (spec 012, D-35; RF-012-03).

    La lista va a ``gpkg_data_column_constraints`` (extensión «schema» de GeoPackage 1.4) como
    filas ``enum``: el código en ``value`` y su texto en ``description``, en su orden; la
    columna la nombra en ``gpkg_data_columns.constraint_name`` sin tocar su título. El GDAL la
    lee como dominio de campo y QGIS la ofrece como lista. ``name`` (un identificador; por
    defecto ``<tabla>_<columna>``) permite que varias columnas compartan una lista; volver a
    llamarla con el mismo nombre la sustituye entera.

    Rechaza sin escribir nada, con ``ValidationError``: una tabla que no existe o no está
    registrada, una columna que no tiene, un nombre que no es un identificador
    (``core.gpkg_name_invalid``) y una lista vacía, con un par mal formado, un código o un
    texto vacíos o un código repetido (``core.gpkg_enum_invalid``); ``TypeError`` si
    ``values`` es un texto o un diccionario y no una lista de pares."""
    if isinstance(values, str | Mapping) or not isinstance(values, Sequence):
        raise TypeError(f"la lista de valores es una secuencia de pares (código, texto), no "
                        f"{values!r}")
    columns = _registered_columns(conn, table)
    _known_column(columns, table, column)
    list_name = _check_name(f"{table}_{column}" if name is None else name, "lista de valores")
    pairs = _enum_values(values)
    _create_schema_tables(conn)
    conn.execute(
        f"DELETE FROM {DATA_COLUMN_CONSTRAINTS_TABLE} "
        "WHERE constraint_name = ? AND constraint_type = 'enum'",
        (list_name,),
    )
    conn.executemany(
        f"INSERT INTO {DATA_COLUMN_CONSTRAINTS_TABLE} (constraint_name, constraint_type, "
        "value, description) VALUES (?, 'enum', ?, ?)",
        [(list_name, code, text) for code, text in pairs],
    )
    conn.execute(
        f"INSERT INTO {DATA_COLUMNS_TABLE} (table_name, column_name, constraint_name) "
        "VALUES (?, ?, ?) ON CONFLICT (table_name, column_name) "
        "DO UPDATE SET constraint_name = excluded.constraint_name",
        (table, column, list_name),
    )
    return list_name


def index_name(table: str, columns: Sequence[str]) -> str:
    """El nombre del índice de las columnas ``columns`` de ``table`` que crea
    :func:`create_index`: ``idx_<tabla>_<columna>[_<columna>…]``."""
    return f"{INDEX_PREFIX}{table}_{'_'.join(columns)}"


def create_index(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    *,
    unique: bool = False,
    nocase: Sequence[str] = (),
) -> str:
    """Crea el índice de las columnas ``columns`` (en su orden) de la capa o tabla ``table``,
    único si ``unique``, y devuelve su nombre (:func:`index_name`). Las columnas de ``nocase``
    se comparan sin distinguir mayúsculas (``COLLATE NOCASE``): un índice único así rechaza
    «s-12» junto a «S-12». ``NOCASE`` de SQLite solo iguala las letras sin tilde (A–Z);
    una consulta lo usa con ``= ? COLLATE NOCASE``.

    Rechaza sin crear nada, con ``ValidationError``: una tabla que no existe
    (``core.gpkg_table_unknown``) o un nombre que no es un identificador, ninguna columna,
    una repetida o una de ``nocase`` que no está en el índice (``core.gpkg_index_columns``),
    una columna que la tabla no tiene (``core.gpkg_column_unknown``) y un índice que ya
    existe (``core.gpkg_index_exists``); ``TypeError`` si ``columns`` o ``nocase`` son un
    texto y no una lista."""
    if isinstance(columns, str) or isinstance(nocase, str):
        raise TypeError("las columnas del índice son una lista de nombres, no un texto")
    if not isinstance(unique, bool):
        raise TypeError(f"«unique» es sí o no, no {unique!r}")
    known = _existing_table(conn, table)
    names = list(columns)
    folded = set(nocase)
    shown = ", ".join(str(name) for name in names)
    if not names or len(set(names)) != len(names):
        reason = "un índice lleva al menos una columna, ninguna repetida"
        raise _invalid("index_columns", reason, "columnas del índice", shown)
    for column in names:
        _known_column(known, table, column)
    outside = sorted(str(column) for column in folded if column not in names)
    if outside:
        reason = f"tienen que ser columnas del índice ({shown})"
        raise _invalid("index_columns", reason, "columnas sin mayúsculas", ", ".join(outside))
    name = index_name(table, names)
    taken = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if taken is not None:
        raise _invalid("index_exists", "ya existe en la base de datos", "índice", name)
    keys = ", ".join(
        f"{_quote(column)} COLLATE NOCASE" if column in folded else _quote(column)
        for column in names
    )
    kind = "UNIQUE INDEX" if unique else "INDEX"
    conn.execute(f"CREATE {kind} {_quote(name)} ON {_quote(table)} ({keys})")
    return name
