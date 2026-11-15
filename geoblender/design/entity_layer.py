# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de entidades de una versión para QGIS: su tabla ``des_enl_<vNN>`` (spec 015, T30; HU-015-1;
RF-015-27, RF-008-56; plan 015 §5.2.3, §5.3.2 y P-7; ADR-0030 §5; D-13).

``des.entity_layer`` es la operación de la **versión** que pone en ``des_enl_<vNN>`` una fila por cada entidad
**calculada** (las «sin calcular» no tienen huella y no salen), con el contorno de su huella (``des_epr_``),
su código, su nombre, su tipo, su estado (:class:`~.entities.EntityState`: al día, obsoleta, descartada o con
el «apoyo retirado»), de qué superficie parte, en qué se apoya, su cadena y sus cifras principales (el área de
la huella, el corte y el relleno de la huella y del borde). QGIS 4.2 la abre con el estilo por tipo de entidad y
por estado de ``core.constraints.styles`` (T22). Es **una salida, no editable a mano** (D-13, RF-008-56): las
entidades cambian desde su capa de origen o sus parámetros, y esta capa se regenera tras cada orden de
entidades; si se edita en QGIS, se bloquea.

Este módulo es el formato de la tabla, como ``core.constraints.declared`` lo es de las declaradas; el
contenido de cada fila (el estado, las dependencias, la cadena) lo arma ``design.entity_store``, que es quien
conoce el registro de las entidades.

- :class:`EntityLayerRow`: una fila. ``parts`` es el contorno de las celdas de la huella (``design.entities.
  declared_zone_of_runs`` con resguardo 0): por cada polígono, sus anillos cerrados (exterior y huecos) en
  coordenadas **absolutas** float64 ``(k, 2)``.
- :func:`create_entity_layer_table`, :func:`write_entity_layer` y :func:`read_entity_layer`: la capa
  ``MULTIPOLYGON`` (2D, CRS del proyecto) con los títulos en español de :data:`COLUMN_TITLES`.
  ``write_entity_layer`` **reescribe la tabla entera** desde las filas (la operación es su única dueña: las
  filas por código, ``fid`` 1…n, sin dejar el contador del autoincremento), de modo que las mismas filas dan
  siempre los mismos bytes y el mismo hash de contenido, sea cual sea su orden.

Las funciones reciben la conexión de una transacción de escritura (o una de lectura para leer) y no la
confirman. Python puro (nivel 8).
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ..core.constraints import styles
from ..core.gpkg.base import ColumnDef, create_feature_table, set_column_titles
from ..core.gpkg.wkb import decode_geometry, encode_geometry
from ..core.versions.model import version_locator
from .entities import EntityKind, EntityState
from .params import entity_segment
from .provenance import ENTITY_MAP_TABLE, dataset_name

__all__ = [
    "COLUMN_NAMES",
    "COLUMN_TITLES",
    "FIGURE_COLUMNS",
    "GEOMETRY_TYPE",
    "LAYER_STATES",
    "EntityLayerRow",
    "create_entity_layer_table",
    "entity_layer_table",
    "read_entity_layer",
    "write_entity_layer",
]

GEOMETRY_TYPE = "MULTIPOLYGON"
IDENTIFIER = "Entidades de diseño"
"""El principio del identificador de la capa en ``gpkg_contents`` (lleva el código de la versión)."""
LAYER_STATES: frozenset[EntityState] = frozenset({
    EntityState.CURRENT, EntityState.STALE, EntityState.SUPPORT_REMOVED, EntityState.DISCARDED})
"""Los estados de una entidad que sale en la capa: las que tienen huella (una **calculada**: al día, obsoleta, con
el apoyo retirado, o **descartada**, que sigue en el proyecto como registro y se dibuja atenuada). Una «sin
calcular» no tiene geometría."""

_TABLE = re.compile(r"[a-z][a-z0-9_]{0,62}")
_VERSION_SUFFIX = re.compile(r"v[0-9]+")

COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("code", "TEXT", True), ColumnDef("name", "TEXT", True), ColumnDef("kind", "TEXT", True),
    ColumnDef("state", "TEXT", True), ColumnDef("start", "TEXT", False),
    ColumnDef("supports", "TEXT", True, "''"), ColumnDef("chain", "TEXT", True, "''"),
    ColumnDef("area_m2", "DOUBLE", False), ColumnDef("cut_m3", "DOUBLE", False),
    ColumnDef("fill_m3", "DOUBLE", False), ColumnDef("edge_cut_m3", "DOUBLE", False),
    ColumnDef("edge_fill_m3", "DOUBLE", False),
)
COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in COLUMNS)
"""Las columnas de la tabla además de ``fid`` y ``geom``, en su orden. Incluyen las del contrato del estilo
(``core.constraints.styles.ENTITY_FIELDS``: ``kind``, ``name``, ``state``, ``supports`` y ``chain``)."""
if not set(styles.ENTITY_FIELDS) <= set(COLUMN_NAMES):  # pragma: no cover - un error del programa
    raise RuntimeError("la tabla de la capa de entidades no tiene los campos que el estilo espera")
FIGURE_COLUMNS: tuple[str, ...] = ("area_m2", "cut_m3", "fill_m3", "edge_cut_m3", "edge_fill_m3")
"""Las columnas de las cifras principales de la entidad (todas pueden faltar: una entidad sin ellas las deja
sin valor)."""
COLUMN_TITLES: Mapping[str, str] = MappingProxyType({
    "code": "Código", "name": "Nombre", "kind": "Tipo", "state": "Estado", "start": "Parte de",
    "supports": "Se apoya en", "chain": "Cadena", "area_m2": "Área de la huella (m²)",
    "cut_m3": "Corte de la huella (m³)", "fill_m3": "Relleno de la huella (m³)",
    "edge_cut_m3": "Corte del borde (m³)", "edge_fill_m3": "Relleno del borde (m³)",
})
"""Los títulos en español de las columnas, que QGIS muestra como alias."""


def entity_layer_table(version_code: str) -> str:
    """La tabla de la capa de entidades de la versión ``version_code`` («V01»): ``des_enl_v01``
    (``core.versions.model.version_locator``; el nombre de su dato es :func:`~.provenance.dataset_name` de
    ``enl``). ``ValueError`` con un código que no es el de una versión."""
    return version_locator(dataset_name(ENTITY_MAP_TABLE), version_code)


def _text(value: object, what: str, *, empty: bool = False) -> str:
    """``value`` sin los espacios de los extremos; ``TypeError`` si no es un texto y ``ValueError`` si queda
    vacío (salvo con ``empty``)."""
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    found = value.strip()
    if not found and not empty:
        raise ValueError(f"{what} es un texto con algo escrito")
    return found


def _figure(value: object, what: str) -> float | None:
    """La cifra ``value`` como real finito (``None``: sin valor); ``TypeError`` si no es un número y
    ``ValueError`` si no es finito."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | np.floating):
        raise TypeError(f"{what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} es un número finito, no {value!r}")
    return number


def _parts(parts: object) -> tuple[tuple[np.ndarray, ...], ...]:
    """El contorno ``parts`` como tuplas de anillos ``(k, 2)`` float64 de solo lectura; ``ValueError`` si no
    hay ninguna parte o un anillo no es un contorno cerrado de al menos tres vértices distintos."""
    if not isinstance(parts, tuple | list) or not parts:
        raise ValueError("una entidad de la capa tiene geometría: al menos una parte con su anillo exterior")
    found: list[tuple[np.ndarray, ...]] = []
    for part in parts:
        rings = []
        for ring in part:
            array = np.array(ring, dtype=np.float64, copy=True)
            if array.ndim != 2 or array.shape[1] != 2 or array.shape[0] < 4:
                raise ValueError("un anillo del contorno de una entidad son al menos cuatro vértices (x, y)")
            if not np.array_equal(array[0], array[-1]) or not np.isfinite(array).all():
                raise ValueError("un anillo del contorno de una entidad es finito y está cerrado")
            array.flags.writeable = False
            rings.append(array)
        if not rings:
            raise ValueError("una parte del contorno de una entidad tiene su anillo exterior")
        found.append(tuple(rings))
    return tuple(found)


@dataclass(frozen=True, slots=True, eq=False)
class EntityLayerRow:
    """Una entidad calculada en la capa (una fila de ``des_enl_<vNN>``): su ``code`` (``PLT-001``), su
    ``name``, su ``kind`` (``EntityKind``), su ``state`` (uno de :data:`LAYER_STATES`: el que deduce el grafo
    de la 008), de qué superficie parte (``start``, tal cual la guarda la entidad; ``None`` si no tiene), en qué
    se apoya (``supports``, un texto; vacío si en nada), su cadena (``chain``: «partida → … → última») y sus
    cifras principales (:data:`FIGURE_COLUMNS`, ``None`` si faltan); ``parts``, el contorno de su huella (véase
    el módulo). ``layer`` y ``fid``: la tabla y la fila, de una leída. Los errores son del programa
    (``TypeError`` o ``ValueError``)."""

    code: str
    name: str
    kind: EntityKind | str
    state: EntityState | str
    start: str | None
    supports: str
    chain: str
    parts: tuple[tuple[np.ndarray, ...], ...]
    area_m2: float | None = None
    cut_m3: float | None = None
    fill_m3: float | None = None
    edge_cut_m3: float | None = None
    edge_fill_m3: float | None = None
    layer: str = ""
    fid: int = 0

    def __post_init__(self) -> None:
        entity_segment(self.code)  # ValueError si no es el código de una entidad
        object.__setattr__(self, "name", _text(self.name, "el nombre de una entidad"))
        object.__setattr__(self, "kind", EntityKind(self.kind))
        state = EntityState(self.state)
        if state not in LAYER_STATES:
            raise ValueError(f"una entidad {state.value} no tiene huella: no sale en la capa (salen "
                             f"{', '.join(sorted(item.value for item in LAYER_STATES))})")
        object.__setattr__(self, "state", state)
        if self.start is not None:
            object.__setattr__(self, "start", _text(self.start, "la superficie de partida"))
        object.__setattr__(self, "supports", _text(self.supports, "lo que apoya la entidad", empty=True))
        object.__setattr__(self, "chain", _text(self.chain, "la cadena de la entidad", empty=True))
        object.__setattr__(self, "parts", _parts(self.parts))
        for column in FIGURE_COLUMNS:
            object.__setattr__(self, column, _figure(getattr(self, column), f"la cifra «{column}»"))
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "fid", int(self.fid))


# --- La tabla --------------------------------------------------------------------------------------


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (table,)).fetchone() is not None


def _check_table(table: object) -> str:
    if not isinstance(table, str) or _TABLE.fullmatch(table) is None:
        raise ValueError(f"{table!r} no es el nombre de una tabla del GeoPackage (un identificador en "
                         "minúsculas: letras, cifras y «_», empezando por una letra)")
    return table


def create_entity_layer_table(conn: sqlite3.Connection, table: str, srs_id: int) -> bool:
    """Crea en la transacción de ``conn`` la capa de polígonos ``table`` de las entidades (:data:`COLUMNS`,
    ``MULTIPOLYGON`` 2D con el CRS ``srs_id``, el del proyecto) con los títulos en español de
    :data:`COLUMN_TITLES`, y la registra en ``gpkg_contents`` y ``gpkg_geometry_columns``; ``True`` si la creó
    y ``False`` si ya estaba (no hace nada). ``ValueError`` si ``table`` no es un nombre de tabla;
    ``ValidationError`` de ``core.gpkg`` si ``srs_id`` no está en ``gpkg_spatial_ref_sys``."""
    _check_table(table)
    if _exists(conn, table):
        return False
    suffix = table.rpartition("_")[2]
    label = (f"{IDENTIFIER} {suffix.upper()}" if _VERSION_SUFFIX.fullmatch(suffix)
             else f"{IDENTIFIER} ({table})")
    create_feature_table(conn, table, GEOMETRY_TYPE, srs_id, False, COLUMNS, label,
                         f"{IDENTIFIER}, de Geoblender: una por versión, no editable a mano")
    set_column_titles(conn, table, COLUMN_TITLES)
    return True


def _srs_of(conn: sqlite3.Connection, table: str) -> int:
    found = conn.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
                         (table,)).fetchone()
    if found is None:
        raise ValueError(f"«{table}» no es una capa registrada en gpkg_geometry_columns")
    return int(found[0])


def _insert(table: str) -> str:
    columns = ", ".join(("geom", *COLUMN_NAMES))
    marks = ", ".join("?" for _ in range(len(COLUMN_NAMES) + 1))
    return f'INSERT INTO "{table}" ({columns}) VALUES ({marks})'


def write_entity_layer(conn: sqlite3.Connection, table: str, rows: Iterable[EntityLayerRow], *,
                       srs_id: int | None = None) -> tuple[int, ...]:
    """Reescribe la tabla ``table`` de la capa de entidades con ``rows`` y devuelve sus ``fid`` (RF-015-27): la
    operación es la única dueña de la tabla, así que se **sustituye entera** —lo que ya no está, desaparece—, por
    código y con los ``fid`` desde 1 (también el contador del autoincremento), de modo que las mismas filas dan
    siempre los mismos bytes y el mismo hash de contenido. Con ``rows`` vacío, la tabla queda vacía. Si la tabla
    no existe, la crea con el CRS ``srs_id`` (:func:`create_entity_layer_table`); si existe, ``srs_id`` (si se
    da) es el suyo. Con la geometría **absoluta en float64** (``core.gpkg.wkb``).

    ``ValueError`` (errores del programa) si dos filas repiten el código, ``table`` no es una capa registrada, o
    falta el SRS de una tabla que no existe o no es el de la que existe; ``TypeError`` si una fila no es una
    :class:`EntityLayerRow`. No escribe nada si rechaza alguna; no confirma la transacción."""
    found = tuple(rows)
    _check_table(table)
    for item in found:
        if not isinstance(item, EntityLayerRow):
            raise TypeError(f"una fila de la capa de entidades es una EntityLayerRow, no {item!r}")
    codes = [item.code for item in found]
    if len(set(codes)) != len(codes):
        raise ValueError(f"dos entidades de la capa repiten el código: "
                         f"{sorted(code for code in set(codes) if codes.count(code) > 1)}")
    if _exists(conn, table):
        srs = _srs_of(conn, table)
        if srs_id is not None and srs_id != srs:
            raise ValueError(f"«{table}» está en el SRS {srs}, no en el {srs_id}")
    elif srs_id is None:
        raise ValueError(f"«{table}» no existe: crearla pide el SRS del proyecto")
    else:
        srs = srs_id
    create_entity_layer_table(conn, table, srs)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    fids: list[int] = []
    for item in sorted(found, key=lambda row: row.code):
        blob = encode_geometry(GEOMETRY_TYPE, [list(part) for part in item.parts], srs, False)
        cursor = conn.execute(_insert(table), (
            blob, item.code, item.name, str(item.kind), str(item.state), item.start, item.supports,
            item.chain, item.area_m2, item.cut_m3, item.fill_m3, item.edge_cut_m3, item.edge_fill_m3))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def _polygons(blob: object) -> tuple[tuple[np.ndarray, ...], ...]:
    """Las partes absolutas (anillos ``(k, 2)``) de un blob ``MULTIPOLYGON`` o ``POLYGON``."""
    geometry = decode_geometry(bytes(blob), external=True)  # type: ignore[arg-type]
    name, coords = geometry.geometry_type, geometry.coords
    if name == "POLYGON":
        coords = [coords]
    elif name != "MULTIPOLYGON":
        raise ValueError(f"la geometría de una entidad es un polígono, no {name}")
    return tuple(tuple(np.asarray(ring, dtype=np.float64).reshape(-1, np.shape(ring)[-1])[:, :2]
                       for ring in polygon) for polygon in coords)


def read_entity_layer(conn: sqlite3.Connection, table: str) -> tuple[EntityLayerRow, ...]:
    """Las entidades de la tabla ``table``, por ``fid``; ninguna si la tabla no existe. Con su capa
    (``table``) y su ``fid``. ``ValueError`` si una fila no es de una entidad de la capa (una editada fuera: la
    tabla no es editable a mano, RF-008-56)."""
    _check_table(table)
    if not _exists(conn, table):
        return ()
    columns = ", ".join(COLUMN_NAMES)
    found = []
    for row in conn.execute(f'SELECT fid, geom, {columns} FROM "{table}" ORDER BY fid'):
        fid, blob, code, name, kind, state, start, supports, chain, *figures = row
        if blob is None:
            raise ValueError(f"la fila {fid} de «{table}» no tiene geometría")
        found.append(EntityLayerRow(
            code=code, name=name, kind=kind, state=state, start=start, supports=supports, chain=chain,
            parts=_polygons(blob), layer=table, fid=int(fid),
            **dict(zip(FIGURE_COLUMNS, figures, strict=True))))
    return tuple(found)
