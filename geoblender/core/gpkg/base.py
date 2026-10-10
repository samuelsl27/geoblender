# SPDX-License-Identifier: GPL-3.0-or-later
"""Estructura GeoPackage 1.4 del proyecto (spec 002; RF-002-14; ADR-0006;
formato-proyecto §3.1; plan 002 §5.2 y §6).

- :func:`create_base`: ``application_id`` (``GPKG``) y ``user_version`` (10400), las
  tablas obligatorias del estándar (``gpkg_spatial_ref_sys``, ``gpkg_contents``,
  ``gpkg_geometry_columns``) y ``gpkg_extensions``, con las filas −1, 0 y 4326 del
  estándar y la del CRS horizontal del proyecto con su WKT1 del catálogo. El CRS vertical
  es un dato del proyecto (``gb_project``): las capas usan el EPSG horizontal, lo más
  compatible con QGIS, DXF y otros (plan 002 §6).
- :func:`register_internal_table`: una tabla interna ``gb_*`` se declara en
  ``gpkg_extensions`` con la extensión ``imga_geoblender`` en alcance ``write-only`` (con
  ``read-write`` GDAL avisa al leer) y no se registra en ``gpkg_contents``: QGIS 4.2 la
  lista igualmente y la protegen los disparadores (spec 002, D-5).
- :func:`create_feature_table` y :func:`create_attribute_table`: capas y tablas de
  atributos registradas, con ``fid INTEGER PRIMARY KEY AUTOINCREMENT``.

Todas reciben la conexión de una transacción de escritura
(``GpkgConnection.transaction()``) y no la confirman.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
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


def create_base(conn: sqlite3.Connection, crs: CrsRef) -> None:
    """Crea la estructura GeoPackage 1.4 con el CRS horizontal del proyecto."""
    conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version = {USER_VERSION}")
    for statement in _DDL:
        conn.execute(statement)
    conn.executemany(
        "INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
        "organization_coordsys_id, definition, description) VALUES (?, ?, ?, ?, ?, ?)",
        [*_STANDARD_SRS, (crs.name, crs.epsg, "EPSG", crs.epsg, crs.wkt1, crs.area or None)],
    )


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
