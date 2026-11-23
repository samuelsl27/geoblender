# SPDX-License-Identifier: GPL-3.0-or-later
"""Las dos capas de líneas con Z que deja «Crear» una corta: las polilíneas de diseño ``des_pbl_<n>`` y la línea de cielo ``des_psk_<n>`` (spec 018, T23; HU-018-1 y HU-018-4; RF-018-01,
RF-018-25, RF-018-29, RF-015-01; plan 018 §5.2.3).

Son **salidas de la operación ``des.pit``** (``DatasetFamily`` de tipo ``vector``, una por corta y versión), no las capas de QGIS por versión (``des_pit_<vNN>`` y ``des_sky_<vNN>``, T27): tablas de líneas
``LINESTRING`` **con Z** del GeoPackage del proyecto con la geometría **absoluta en float64** (``core.gpkg.wkb``) y los atributos de cada línea en las columnas de :data:`POLYLINE_COLUMNS` y
:data:`SKYLINE_COLUMNS`. La operación es su única dueña: :func:`write_pit_lines` las **escribe enteras**, en el orden en que llegan las filas y con los ``fid`` desde 1, de modo que las mismas filas dan siempre
los mismos bytes y el mismo hash de contenido (RF-018-25). Un anillo (``closed``) se guarda con su primer vértice repetido al final, como una línea cerrada, y al leerlo se quita.

Este módulo es **perezoso** (``design.provenance`` declara las familias; ``design.store`` lo importa al usarlo) y no depende del almacén: solo del formato. Python puro (nivel 8).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.gpkg.base import ColumnDef, create_feature_table, set_column_titles
from ..core.gpkg.wkb import decode_geometry, encode_geometry

__all__ = [
    "GEOMETRY_TYPE",
    "POLYLINE_COLUMNS",
    "SKYLINE_COLUMNS",
    "LineRow",
    "columns_of",
    "create_pit_lines_table",
    "read_pit_lines",
    "write_pit_lines",
]

GEOMETRY_TYPE = "LINESTRING"
POLYLINES = "pbl"
SKYLINE = "psk"
_TABLE = re.compile(r"[a-z][a-z0-9_]{0,62}")

POLYLINE_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("bench", "INTEGER", True), ColumnDef("kind", "TEXT", True), ColumnDef("zone", "TEXT", True, "''"), ColumnDef("sector", "TEXT", True, "''"),
    ColumnDef("part", "INTEGER", True), ColumnDef("ordinal", "INTEGER", True), ColumnDef("closed", "INTEGER", True), ColumnDef("fixed", "INTEGER", True),
    ColumnDef("z_m", "DOUBLE", True), ColumnDef("length_m", "DOUBLE", True))
"""Las columnas de ``des_pbl_`` además de ``fid`` y ``geom`` (plan 018 §5.2.3: «banco, tipo, zona, sector, orden, vértices con Z»): el ``bench``, el ``kind`` (``foot`` o ``crest``), la ``zone`` (vacía si no es de
una zona de rampa), el ``sector`` (vacío: el perímetro), la ``part`` del banco en que se divide el interior, el ``ordinal`` de la polilínea en el orden registrado (RF-018-25: desde 1), si es un anillo
(``closed``) o una línea del usuario tal cual (``fixed``: 1 o 0), su cota (``z_m``, la de su primer vértice) y su longitud en planta (``length_m``, con el cierre)."""
SKYLINE_COLUMNS: tuple[ColumnDef, ...] = (ColumnDef("part", "INTEGER", True), ColumnDef("length_m", "DOUBLE", True))
"""Las columnas de ``des_psk_`` además de ``fid`` y ``geom``: el número de la ``part`` de la línea de cielo (desde 1) y su longitud en planta (``length_m``)."""

_COLUMNS: Mapping[str, tuple[ColumnDef, ...]] = MappingProxyType({POLYLINES: POLYLINE_COLUMNS, SKYLINE: SKYLINE_COLUMNS})
_IDENTIFIERS = MappingProxyType({POLYLINES: "Polilíneas de la corta", SKYLINE: "Línea de cielo de la corta"})
_TITLES: Mapping[str, Mapping[str, str]] = MappingProxyType({
    POLYLINES: MappingProxyType({"bench": "Banco", "kind": "Tipo", "zone": "Zona", "sector": "Sector", "part": "Parte", "ordinal": "Orden", "closed": "Anillo", "fixed": "Línea fijada",
                                 "z_m": "Cota (m)", "length_m": "Longitud (m)"}),
    SKYLINE: MappingProxyType({"part": "Parte", "length_m": "Longitud (m)"})})


def columns_of(family: str) -> tuple[ColumnDef, ...]:
    """Las columnas de la familia de líneas ``family`` (``pbl`` o ``psk``); ``KeyError`` si no es una."""
    return _COLUMNS[family]


@dataclass(frozen=True, slots=True, eq=False)
class LineRow:
    """Una línea de ``des_pbl_`` o de ``des_psk_``: sus ``points`` ``(n, 3)`` (x, y absolutas y la cota en la Z, float64; un anillo **sin repetir** el primer vértice si ``closed``) y los ``values`` de sus
    columnas (las de :data:`POLYLINE_COLUMNS` o :data:`SKYLINE_COLUMNS`, en su orden). Los errores son del programa (``ValueError``)."""

    points: np.ndarray
    values: tuple[Any, ...]
    closed: bool = False

    def __post_init__(self) -> None:
        try:
            array = np.array(self.points, dtype=np.float64, copy=True)
        except (TypeError, ValueError) as error:
            raise ValueError("una línea de la corta son vértices con (x, y, z) numéricas") from error
        if array.ndim != 2 or array.shape[1] != 3 or array.shape[0] < 2:
            raise ValueError("una línea de la corta son al menos dos vértices (x, y, z)")
        if not np.isfinite(array).all():
            raise ValueError("una línea de la corta tiene sus coordenadas finitas")
        array.flags.writeable = False
        object.__setattr__(self, "points", array)
        object.__setattr__(self, "values", tuple(self.values))
        object.__setattr__(self, "closed", bool(self.closed))


def _check_table(table: object) -> str:
    if not isinstance(table, str) or _TABLE.fullmatch(table) is None:
        raise ValueError(f"{table!r} no es el nombre de una tabla del GeoPackage (un identificador en minúsculas: letras, cifras y «_», empezando por una letra)")
    return table


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def create_pit_lines_table(conn: sqlite3.Connection, table: str, family: str, srs_id: int, label: str = "") -> bool:
    """Crea en la transacción de ``conn`` la capa de líneas ``table`` de la familia ``family`` (``pbl`` o ``psk``; ``LINESTRING`` **con Z** y el CRS ``srs_id``, el del proyecto) con los títulos en español de sus
    columnas, y la registra en ``gpkg_contents`` y ``gpkg_geometry_columns``; ``True`` si la creó y ``False`` si ya estaba. ``label``: el nombre de la corta, para el identificador."""
    _check_table(table)
    if _exists(conn, table):
        return False
    identifier = f"{_IDENTIFIERS[family]} {label}".strip()
    create_feature_table(conn, table, GEOMETRY_TYPE, srs_id, True, _COLUMNS[family], identifier, f"{_IDENTIFIERS[family]}, de Geoblender: una salida de la operación de la corta, no editable a mano")
    set_column_titles(conn, table, _TITLES[family])
    return True


def _srs_of(conn: sqlite3.Connection, table: str) -> int:
    found = conn.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?", (table,)).fetchone()
    if found is None:
        raise ValueError(f"«{table}» no es una capa registrada en gpkg_geometry_columns")
    return int(found[0])


def write_pit_lines(conn: sqlite3.Connection, table: str, family: str, rows: Iterable[LineRow], *, srs_id: int | None = None, label: str = "") -> tuple[int, ...]:
    """Reescribe la tabla ``table`` de la familia ``family`` con ``rows`` y devuelve sus ``fid`` (desde 1, en el orden de ``rows``; el contador del autoincremento también): la operación de la corta es su
    única dueña, así que se **sustituye entera**. Con ``rows`` vacío, la tabla queda vacía. Si no existe, la crea con el CRS ``srs_id`` (:func:`create_pit_lines_table`); si existe, ``srs_id`` (si se da) es el
    suyo. ``ValueError`` (errores del programa) si ``table`` no es una capa registrada, falta el SRS de una tabla que no existe o una fila no lleva las columnas de la familia; ``TypeError`` si una fila no es
    una :class:`LineRow`. No confirma la transacción."""
    found = tuple(rows)
    _check_table(table)
    columns = _COLUMNS[family]
    for item in found:
        if not isinstance(item, LineRow):
            raise TypeError(f"una fila de las líneas de la corta es una LineRow, no {item!r}")
        if len(item.values) != len(columns):
            raise ValueError(f"una fila de «{family}» lleva {len(columns)} columnas, no {len(item.values)}")
    if _exists(conn, table):
        srs = _srs_of(conn, table)
        if srs_id is not None and srs_id != srs:
            raise ValueError(f"«{table}» está en el SRS {srs}, no en el {srs_id}")
    elif srs_id is None:
        raise ValueError(f"«{table}» no existe: crearla pide el SRS del proyecto")
    else:
        srs = srs_id
    create_pit_lines_table(conn, table, family, srs, label)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    names = ", ".join(("geom", *(column.name for column in columns)))
    marks = ", ".join("?" for _ in range(len(columns) + 1))
    fids: list[int] = []
    for item in found:
        points = np.asarray(item.points)
        if item.closed:
            points = np.vstack([points, points[:1]])
        blob = encode_geometry(GEOMETRY_TYPE, points, srs, True)
        cursor = conn.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', (blob, *item.values))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def read_pit_lines(conn: sqlite3.Connection, table: str, family: str, *, closed_column: str | None = None) -> tuple[LineRow, ...]:
    """Las líneas de la tabla ``table`` de la familia ``family``, por ``fid``; ninguna si la tabla no existe. Si la familia tiene la columna ``closed_column`` (``closed`` en las polilíneas) y vale 1, el
    primer vértice repetido al final se quita."""
    _check_table(table)
    if not _exists(conn, table):
        return ()
    columns = _COLUMNS[family]
    names = [column.name for column in columns]
    found = []
    for row in conn.execute(f'SELECT geom, {", ".join(names)} FROM "{table}" ORDER BY fid'):
        blob, *values = row
        if blob is None:
            raise ValueError(f"una fila de «{table}» no tiene geometría")
        geometry = decode_geometry(bytes(blob), external=True)
        points = np.asarray(geometry.coords, dtype=np.float64).reshape(-1, 3)
        closed = closed_column is not None and bool(values[names.index(closed_column)])
        found.append(LineRow(points[:-1] if closed else points, tuple(values), closed))
    return tuple(found)

