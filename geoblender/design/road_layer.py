# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de ejes de pistas de una versión para QGIS: su tabla ``des_rax_<vNN>`` (spec 017, T26; HU-017-1 y HU-017-3; RF-017-27, RF-015-27, RF-008-56; plan 017 §5.2.3 «La capa de ejes de pistas»
y §5.1; D-19; decisión T26-a de la sesión principal).

``des.road_layer`` es la operación de la **versión** que pone en ``des_rax_<vNN>`` una fila por cada pista **calculada** (las «sin calcular» no tienen eje): su eje por estaciones como ``LINESTRING`` con **la
rasante en la Z de cada vértice** (coordenadas absolutas en float64, en el CRS del proyecto: ``core.gpkg.wkb`` ya escribe la Z), su código, su nombre, su clase normativa, su longitud, sus cotas de inicio y de fin,
su desnivel, sus pendientes media y máxima, su radio mínimo, las anchuras de su calzada y de su sección, su perfil y su estado (:class:`~.entities.EntityState`: al día, obsoleta, con el «apoyo retirado» o
descartada, que se dibuja atenuada). QGIS 4.2 la abre con el estilo **por clase** de ``core.constraints.styles`` (T26 (b)). Es **una salida, no editable a mano** (D-19, RF-008-56): las pistas cambian desde su
capa de origen o sus parámetros y esta capa se regenera tras cada orden de pistas (:func:`~.entity_store.after_entity_change`) y al terminar «Recalcular lo obsoleto»
(:func:`~.entity_store.layers_sync_steps`); si se edita en QGIS, se bloquea. **Su estado es el del registro**: :func:`road_layer_pending` la marca si dice otra cosa que él (el hallazgo D-1 de la 016, con la
pista: la capa de una versión con **solo una pista** decía «obsoleta» sobre una pista al día tras «Recalcular lo obsoleto» y tras «Cambiar parámetro…»).

Este módulo es **perezoso** (``design.provenance`` declara la operación; ``bl`` importa este módulo al usarla, RNF-001-03) y tiene dos partes, como ``design.entity_layer`` y ``design.entity_store`` juntos:

- **El formato**: :class:`RoadLayerRow`, :func:`create_road_layer_table`, :func:`write_road_layer` y :func:`read_road_layer`. ``write_road_layer`` **reescribe la tabla entera** desde las filas (la operación es
  su única dueña: las filas por código, ``fid`` 1…n, sin dejar el contador del autoincremento), de modo que las mismas filas dan siempre los mismos bytes y el mismo hash de contenido, sea cual sea su orden.
- **El almacén**: :func:`road_sources` lee las pistas de la versión (el registro, el eje de cada una, sus cifras, su perfil y su clase), :func:`road_layer_rows_steps` arma las filas (sin proyecto dentro: recibe lo
  leído), :func:`prepare_road_layer`, :func:`run_road_layer`, :func:`road_layer_steps` y :func:`recompute_road_layer` la preparan, la registran en **una** transacción y la repiten, y
  :func:`road_layer_pending` y :func:`road_layer_sync_steps` la ponen al día si ya no dice lo que el registro.

Python puro (nivel 8).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ..core.constraints import styles
from ..core.datasets import external as dataset_external
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetStatus
from ..core.gpkg.base import ColumnDef, create_feature_table, set_column_titles
from ..core.gpkg.wkb import decode_geometry, encode_geometry
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore
from ..core.project.model import Progress
from ..core.provenance.graph import DATASET
from ..core.provenance.operations import OperationHandle
from ..core.provenance.recompute import RecomputeRequest
from ..core.versions import read as versions_read
from ..core.versions.model import Version, version_locator
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.store import StoreProject
from . import entities, entity_store, pipeline, provenance, road_profiles
from .entities import EntityKind, EntityState
from .entity_layer import LAYER_STATES
from .messages import DesignError
from .params import RoadParam, RoadProfileParam, entity_key, is_code, road_profile_key
from .store import _STORE_PHASE, DesignWriter, OperationStart, Stored, _start, _store_steps, require_version

__all__ = [
    "COLUMN_NAMES",
    "COLUMN_TITLES",
    "FIGURE_COLUMNS",
    "GEOMETRY_TYPE",
    "LAYER_STATES",
    "ROUTE_COLUMNS",
    "ROUTE_COLUMN_NAMES",
    "ROUTE_COLUMN_TITLES",
    "ROUTE_IDENTIFIER",
    "PreparedRoadLayer",
    "RoadHead",
    "RoadLayerRow",
    "RoadSource",
    "RouteLayerRow",
    "create_road_layer_table",
    "create_route_layer_table",
    "layer_differences",
    "prepare_road_layer",
    "read_road_layer",
    "read_route_layer",
    "recompute_road_layer",
    "road_heads",
    "road_layer_pending",
    "road_layer_rows",
    "road_layer_rows_steps",
    "road_layer_steps",
    "road_layer_sync_steps",
    "road_layer_table",
    "road_sources",
    "route_layer_table",
    "run_road_layer",
    "write_road_layer",
    "write_route_layer",
    "written_rows",
]

GEOMETRY_TYPE = "LINESTRING"
IDENTIFIER = "Ejes de pistas"
"""El principio del identificador de la capa en ``gpkg_contents`` (lleva el código de la versión)."""

_TABLE = re.compile(r"[a-z][a-z0-9_]{0,62}")
_VERSION_SUFFIX = re.compile(r"v[0-9]+")
_LAYER_PHASE = "road_layer"

FIGURE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("length_m", "des.road_length_m"), ("z_start_m", "des.road_z_start_m"), ("z_end_m", "des.road_z_end_m"), ("drop_m", "des.road_drop_m"),
    ("gradient_mean_pct", "des.road_gradient_mean_pct"), ("gradient_max_pct", "des.road_gradient_max_pct"), ("radius_min_m", "des.road_radius_min_m"),
    ("width_m", "des.road_width_m"), ("section_m", "des.road_section_m"))
"""Las cifras de la pista que salen en la capa: la columna de ``des_rax_<vNN>`` y la cifra de la operación de la pista de la que sale (``des.road_*``, RF-017-23). Todas pueden faltar: sin curvas no hay
radio mínimo."""

COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("code", "TEXT", True), ColumnDef("name", "TEXT", True), ColumnDef("class_name", "TEXT", True, "''"), ColumnDef("state", "TEXT", True),
    ColumnDef("profile", "TEXT", True, "''"), *(ColumnDef(column, "DOUBLE", False) for column, _key in FIGURE_COLUMNS))
COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in COLUMNS)
"""Las columnas de la tabla además de ``fid`` y ``geom``, en su orden. Incluyen las del contrato del estilo (``core.constraints.styles.ROAD_FIELDS``)."""
if not set(styles.ROAD_FIELDS) <= set(COLUMN_NAMES):  # pragma: no cover - un error del programa
    raise RuntimeError("la tabla de la capa de ejes de pistas no tiene los campos que el estilo espera")
COLUMN_TITLES: Mapping[str, str] = MappingProxyType({
    "code": "Código", "name": "Nombre", "class_name": "Clase normativa", "state": "Estado", "profile": "Perfil", "length_m": "Longitud (m)",
    "z_start_m": "Cota de inicio (m)", "z_end_m": "Cota de fin (m)", "drop_m": "Desnivel (m)", "gradient_mean_pct": "Pendiente media (%)",
    "gradient_max_pct": "Pendiente máxima (%)", "radius_min_m": "Radio mínimo (m)", "width_m": "Anchura de la calzada (m)", "section_m": "Anchura de la sección (m)"})
"""Los títulos en español de las columnas, que QGIS muestra como alias."""
if set(COLUMN_TITLES) != set(COLUMN_NAMES):  # pragma: no cover - un error del programa
    raise RuntimeError("cada columna de la capa de ejes de pistas lleva su título")


def road_layer_table(version_code: str) -> str:
    """La tabla de la capa de ejes de pistas de la versión ``version_code`` («V01»): ``des_rax_v01`` (``core.versions.model.version_locator``; el nombre de su dato es :func:`~.provenance.dataset_name` de
    ``rax``). ``ValueError`` con un código que no es el de una versión."""
    return version_locator(provenance.dataset_name(provenance.ROAD_LAYER_TABLE), version_code)


def _text(value: object, what: str, *, empty: bool = False) -> str:
    """``value`` sin los espacios de los extremos; ``TypeError`` si no es un texto y ``ValueError`` si queda vacío (salvo con ``empty``)."""
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    found = value.strip()
    if not found and not empty:
        raise ValueError(f"{what} es un texto con algo escrito")
    return found


def _figure(value: object, what: str) -> float | None:
    """La cifra ``value`` como real finito (``None``: sin valor); ``TypeError`` si no es un número y ``ValueError`` si no es finito."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | np.floating):
        raise TypeError(f"{what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} es un número finito, no {value!r}")
    return number


def _points(points: object) -> np.ndarray:
    """La línea ``points`` como un ``(n, 3)`` float64 de solo lectura (x, y absolutas y la Z de la rasante); ``ValueError`` si no son al menos dos estaciones con tres coordenadas finitas."""
    try:
        array = np.array(points, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as error:
        raise ValueError("el eje de una pista son estaciones con (x, y, z) numéricas") from error
    if array.ndim != 2 or array.shape[1] != 3 or array.shape[0] < 2:
        raise ValueError("el eje de una pista de la capa son al menos dos estaciones (x, y, z), con la rasante en la Z")
    if not np.isfinite(array).all():
        raise ValueError("el eje de una pista de la capa tiene sus coordenadas finitas")
    array.flags.writeable = False
    return array


@dataclass(frozen=True, slots=True, eq=False)
class RoadLayerRow:
    """Una pista calculada en la capa (una fila de ``des_rax_<vNN>``): su ``code`` (``RDW-001``), su ``name``, su clase normativa (``class_name``) y su ``profile`` (el nombre del perfil), su ``state`` (uno
    de :data:`LAYER_STATES`: el que deduce el grafo de la 008) y las cifras de :data:`FIGURE_COLUMNS` (``None`` si faltan); ``points``, su eje por estaciones ``(n, 3)`` con la **rasante en la Z** (coordenadas
    absolutas, float64). ``layer`` y ``fid``: la tabla y la fila, de una leída. Los errores son del programa (``TypeError`` o ``ValueError``)."""

    code: str
    name: str
    class_name: str
    state: EntityState | str
    profile: str
    points: object
    length_m: float | None = None
    z_start_m: float | None = None
    z_end_m: float | None = None
    drop_m: float | None = None
    gradient_mean_pct: float | None = None
    gradient_max_pct: float | None = None
    radius_min_m: float | None = None
    width_m: float | None = None
    section_m: float | None = None
    layer: str = ""
    fid: int = 0

    def __post_init__(self) -> None:
        if entities.kind_of_code(self.code) is not EntityKind.ROAD:
            raise ValueError(f"el código {self.code!r} no es el de una pista (RDW-001): la capa de ejes solo tiene pistas")
        object.__setattr__(self, "name", _text(self.name, "el nombre de una pista"))
        object.__setattr__(self, "class_name", _text(self.class_name, "la clase normativa de una pista", empty=True))
        object.__setattr__(self, "profile", _text(self.profile, "el perfil de una pista", empty=True))
        state = EntityState(self.state)
        if state not in LAYER_STATES:
            raise ValueError(f"una pista {state.value} no tiene eje: no sale en la capa (salen {', '.join(sorted(item.value for item in LAYER_STATES))})")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "points", _points(self.points))
        for column, _key in FIGURE_COLUMNS:
            object.__setattr__(self, column, _figure(getattr(self, column), f"la cifra «{column}»"))
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "fid", int(self.fid))


# --- La tabla --------------------------------------------------------------------------------------


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _check_table(table: object) -> str:
    if not isinstance(table, str) or _TABLE.fullmatch(table) is None:
        raise ValueError(f"{table!r} no es el nombre de una tabla del GeoPackage (un identificador en minúsculas: letras, cifras y «_», empezando por una letra)")
    return table


def create_road_layer_table(conn: sqlite3.Connection, table: str, srs_id: int) -> bool:
    """Crea en la transacción de ``conn`` la capa de líneas ``table`` de los ejes de pistas (:data:`COLUMNS`, ``LINESTRING`` **con Z** y el CRS ``srs_id``, el del proyecto) con los títulos en español de
    :data:`COLUMN_TITLES`, y la registra en ``gpkg_contents`` y ``gpkg_geometry_columns``; ``True`` si la creó y ``False`` si ya estaba (no hace nada). ``ValueError`` si ``table`` no es un nombre de
    tabla; ``ValidationError`` de ``core.gpkg`` si ``srs_id`` no está en ``gpkg_spatial_ref_sys``."""
    _check_table(table)
    if _exists(conn, table):
        return False
    suffix = table.rpartition("_")[2]
    label = f"{IDENTIFIER} {suffix.upper()}" if _VERSION_SUFFIX.fullmatch(suffix) else f"{IDENTIFIER} ({table})"
    create_feature_table(conn, table, GEOMETRY_TYPE, srs_id, True, COLUMNS, label, f"{IDENTIFIER}, de Geoblender: una por versión, no editable a mano")
    set_column_titles(conn, table, COLUMN_TITLES)
    return True


def _srs_of(conn: sqlite3.Connection, table: str) -> int:
    found = conn.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?", (table,)).fetchone()
    if found is None:
        raise ValueError(f"«{table}» no es una capa registrada en gpkg_geometry_columns")
    return int(found[0])


def _insert(table: str) -> str:
    columns = ", ".join(("geom", *COLUMN_NAMES))
    marks = ", ".join("?" for _ in range(len(COLUMN_NAMES) + 1))
    return f'INSERT INTO "{table}" ({columns}) VALUES ({marks})'


def write_road_layer(conn: sqlite3.Connection, table: str, rows: Iterable[RoadLayerRow], *, srs_id: int | None = None) -> tuple[int, ...]:
    """Reescribe la tabla ``table`` de la capa de ejes de pistas con ``rows`` y devuelve sus ``fid`` (RF-017-27): la operación es la única dueña de la tabla, así que se **sustituye entera** —lo que ya no
    está, desaparece—, por código y con los ``fid`` desde 1 (también el contador del autoincremento), de modo que las mismas filas dan siempre los mismos bytes y el mismo hash de contenido. Con ``rows``
    vacío, la tabla queda vacía. Si la tabla no existe, la crea con el CRS ``srs_id`` (:func:`create_road_layer_table`); si existe, ``srs_id`` (si se da) es el suyo. Con la geometría **absoluta en
    float64** y la rasante en la Z (``core.gpkg.wkb``).

    ``ValueError`` (errores del programa) si dos filas repiten el código, ``table`` no es una capa registrada, o falta el SRS de una tabla que no existe o no es el de la que existe; ``TypeError`` si una
    fila no es una :class:`RoadLayerRow`. No escribe nada si rechaza alguna; no confirma la transacción."""
    found = tuple(rows)
    _check_table(table)
    for item in found:
        if not isinstance(item, RoadLayerRow):
            raise TypeError(f"una fila de la capa de ejes de pistas es una RoadLayerRow, no {item!r}")
    codes = [item.code for item in found]
    if len(set(codes)) != len(codes):
        raise ValueError(f"dos pistas de la capa repiten el código: {sorted(code for code in set(codes) if codes.count(code) > 1)}")
    if _exists(conn, table):
        srs = _srs_of(conn, table)
        if srs_id is not None and srs_id != srs:
            raise ValueError(f"«{table}» está en el SRS {srs}, no en el {srs_id}")
    elif srs_id is None:
        raise ValueError(f"«{table}» no existe: crearla pide el SRS del proyecto")
    else:
        srs = srs_id
    create_road_layer_table(conn, table, srs)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    fids: list[int] = []
    for item in sorted(found, key=lambda row: row.code):
        blob = encode_geometry(GEOMETRY_TYPE, np.asarray(item.points), srs, True)
        cursor = conn.execute(_insert(table), (blob, item.code, item.name, item.class_name, str(item.state), item.profile, *(getattr(item, column) for column, _key in FIGURE_COLUMNS)))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def _line(blob: object) -> np.ndarray:
    """Las estaciones absolutas ``(n, 3)`` de un blob ``LINESTRING`` con Z."""
    geometry = decode_geometry(bytes(blob), external=True)  # type: ignore[arg-type]
    if geometry.geometry_type != GEOMETRY_TYPE:
        raise ValueError(f"la geometría de una pista es una línea, no {geometry.geometry_type}")
    return np.asarray(geometry.coords, dtype=np.float64).reshape(-1, 3)


def read_road_layer(conn: sqlite3.Connection, table: str) -> tuple[RoadLayerRow, ...]:
    """Las pistas de la tabla ``table``, por ``fid``; ninguna si la tabla no existe. Con su capa (``table``) y su ``fid``. ``ValueError`` si una fila no es de una pista de la capa (una editada fuera: la
    tabla no es editable a mano, RF-008-56)."""
    _check_table(table)
    if not _exists(conn, table):
        return ()
    columns = ", ".join(COLUMN_NAMES)
    found = []
    for row in conn.execute(f'SELECT fid, geom, {columns} FROM "{table}" ORDER BY fid'):
        fid, blob, code, name, class_name, state, profile, *figures = row
        if blob is None:
            raise ValueError(f"la fila {fid} de «{table}» no tiene geometría")
        found.append(RoadLayerRow(code=code, name=name, class_name=class_name, state=state, profile=profile, points=_line(blob), layer=table, fid=int(fid),
                                  **dict(zip((column for column, _key in FIGURE_COLUMNS), figures, strict=True))))
    return tuple(found)


# --- La capa propuesta del trazado (spec 017, T27; RF-017-28, P-8, D-19) --------------------------------------
# ``des_rpl_<nombre>_<vNN>``: lo que deja ``des.road_propose`` («Proponer el trazado…»). **No es una salida bloqueada** como ``des_rax_``: es una tabla de proyecto normal, **editable en QGIS**
# (``DatasetFamily.qgis_editable``), que no es una entidad ni lleva estilo propio de Geoblender, y que una pista «eje 3D» lee con su Z (T23-a) como entrada con su hash.

ROUTE_IDENTIFIER = "Trazado propuesto"
"""El principio del identificador de la capa propuesta en ``gpkg_contents`` (lleva el nombre de la propuesta)."""
ROUTE_COLUMNS: tuple[ColumnDef, ...] = (ColumnDef("name", "TEXT", True),)
ROUTE_COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in ROUTE_COLUMNS)
"""Las columnas de la capa propuesta además de ``fid`` y ``geom``: **solo el nombre** de la línea (por el que una pista «eje 3D» la elige). Las cifras de la propuesta (longitud, pendiente máxima) son de
la operación: una cifra en la tabla quedaría mal en cuanto se edite la línea en QGIS, y todas las columnas cuentan en el hash que deja obsoleta a una pista que la usa."""
ROUTE_COLUMN_TITLES: Mapping[str, str] = MappingProxyType({"name": "Nombre"})
"""Los títulos en español de las columnas, que QGIS muestra como alias."""


def route_layer_table(version_code: str, name: str) -> str:
    """La tabla de la capa propuesta del trazado ``name`` en la versión ``version_code`` («V01»): ``des_rpl_<nombre>_<vNN>`` (:func:`~.provenance.dataset_locator` de ``rpl``: el nombre en ASCII y
    en minúsculas, ``gis.provenance.dataset_slug``). ``ValueError`` con un código que no es el de una versión; ``GisError`` si el nombre no tiene ninguna letra ni cifra."""
    return provenance.dataset_locator(provenance.ROUTE_LAYER_TABLE, name, version_code)


@dataclass(frozen=True, slots=True, eq=False)
class RouteLayerRow:
    """Una línea de la capa propuesta (una fila de ``des_rpl_<nombre>_<vNN>``): su ``name`` y su eje por estaciones ``points`` ``(n, 3)`` con **la rasante en la Z** (coordenadas absolutas, float64, de
    solo lectura). ``layer`` y ``fid``: la tabla y la fila, de una leída. Los errores son del programa (``TypeError`` o ``ValueError``)."""

    name: str
    points: object
    layer: str = ""
    fid: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "el nombre de una línea propuesta"))
        object.__setattr__(self, "points", _points(self.points))
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "fid", int(self.fid))


def create_route_layer_table(conn: sqlite3.Connection, table: str, srs_id: int, name: str = "") -> bool:
    """Crea en la transacción de ``conn`` la capa de líneas ``table`` de un trazado propuesto (:data:`ROUTE_COLUMNS`, ``LINESTRING`` **con Z** y el CRS ``srs_id``, el del proyecto) con los títulos en
    español de :data:`ROUTE_COLUMN_TITLES`, y la registra en ``gpkg_contents`` y ``gpkg_geometry_columns``; ``True`` si la creó y ``False`` si ya estaba (no hace nada). ``name`` es el de la propuesta
    (para el título que ve QGIS). ``ValueError`` si ``table`` no es un nombre de tabla; ``ValidationError`` de ``core.gpkg`` si ``srs_id`` no está en ``gpkg_spatial_ref_sys``."""
    _check_table(table)
    if _exists(conn, table):
        return False
    label = f"{ROUTE_IDENTIFIER} {name}".strip() if name else f"{ROUTE_IDENTIFIER} ({table})"
    create_feature_table(conn, table, GEOMETRY_TYPE, srs_id, True, ROUTE_COLUMNS, label,
                         f"{ROUTE_IDENTIFIER}, de Geoblender: eje con su rasante en la Z, editable a mano en QGIS (es del usuario desde que se crea)")
    set_column_titles(conn, table, ROUTE_COLUMN_TITLES)
    return True


def write_route_layer(conn: sqlite3.Connection, table: str, rows: Iterable[RouteLayerRow], *, srs_id: int | None = None, name: str = "") -> tuple[int, ...]:
    """Reescribe la tabla ``table`` de la capa propuesta con ``rows`` y devuelve sus ``fid`` (RF-017-28): al crear la propuesta o repetirla es **la operación quien la escribe** —entera, por nombre y con
    los ``fid`` desde 1—, de modo que las mismas filas dan siempre los mismos bytes y el mismo hash de contenido; después es **de la persona** (se edita en QGIS) y Geoblender no la vuelve a escribir
    sin que la operación se repita. Si la tabla no existe, la crea con el CRS ``srs_id``; si existe, ``srs_id`` (si se da) es el suyo. Con la geometría **absoluta en float64** y la rasante en la Z
    (``core.gpkg.wkb``).

    ``ValueError`` (errores del programa) si dos filas repiten el nombre, ``table`` no es una capa registrada, o falta el SRS de una tabla que no existe o no es el de la que existe; ``TypeError`` si una
    fila no es una :class:`RouteLayerRow`. No escribe nada si rechaza alguna; no confirma la transacción."""
    found = tuple(rows)
    _check_table(table)
    for item in found:
        if not isinstance(item, RouteLayerRow):
            raise TypeError(f"una fila de la capa propuesta es una RouteLayerRow, no {item!r}")
    names = [item.name for item in found]
    if len(set(names)) != len(names):
        raise ValueError(f"dos líneas de la capa propuesta repiten el nombre: {sorted(each for each in set(names) if names.count(each) > 1)}")
    if _exists(conn, table):
        srs = _srs_of(conn, table)
        if srs_id is not None and srs_id != srs:
            raise ValueError(f"«{table}» está en el SRS {srs}, no en el {srs_id}")
    elif srs_id is None:
        raise ValueError(f"«{table}» no existe: crearla pide el SRS del proyecto")
    else:
        srs = srs_id
    create_route_layer_table(conn, table, srs, name)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    fids: list[int] = []
    for item in sorted(found, key=lambda row: row.name):
        blob = encode_geometry(GEOMETRY_TYPE, np.asarray(item.points), srs, True)
        cursor = conn.execute(f'INSERT INTO "{table}" (geom, name) VALUES (?, ?)', (blob, item.name))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def read_route_layer(conn: sqlite3.Connection, table: str) -> tuple[RouteLayerRow, ...]:
    """Las líneas de la tabla ``table`` de la capa propuesta, por ``fid``; ninguna si la tabla no existe. Con su capa (``table``) y su ``fid``. **Solo lee**: la tabla es de la persona (se edita en
    QGIS) y se lee tal como esté. ``ValueError`` si una fila no tiene geometría, no es una línea o no tiene su Z."""
    _check_table(table)
    if not _exists(conn, table):
        return ()
    found = []
    for fid, blob, name in conn.execute(f'SELECT fid, geom, name FROM "{table}" ORDER BY fid'):
        if blob is None:
            raise ValueError(f"la fila {fid} de «{table}» no tiene geometría")
        found.append(RouteLayerRow(str(name), _line(blob), table, int(fid)))
    return tuple(found)


# --- Lo que lee el almacén -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoadHead:
    """Lo que la capa sabe de una pista **calculada** sin leer su eje (:func:`road_heads`): su ``code`` y su ``name`` de ahora, su ``state`` (el que deduce el grafo), el uid de su operación vigente, el
    código del perfil que usa (``profile_code``: ``des.road.{e}.profile``), el nombre de ese perfil (``profile``) y su clase normativa (``class_name``: ``des.roadprofile.{p}.class``). Vacíos
    ``profile`` y ``class_name`` si la pista no tiene perfil o el perfil no tiene clase."""

    code: str
    name: str
    state: EntityState
    operation_uid: str
    profile_code: str = ""
    profile: str = ""
    class_name: str = ""

    @property
    def live(self) -> bool:
        """Si sus datos están vivos: una pista **descartada** sale en la capa (es un registro, atenuada) pero sus datos ya no son entrada de ninguna operación."""
        return self.state is not EntityState.DISCARDED


@dataclass(frozen=True, slots=True)
class RoadSource:
    """Lo que la capa de ejes sabe de una pista **calculada** de la versión (:func:`road_sources`): su ``code`` y su ``name`` de ahora (``calc_name`` es el con que se calculó: el de su dato ``des_rdx_``), su
    ``state``, el nombre de su perfil (``profile``) y su clase (``class_name``), su eje por estaciones ``(n, 3)`` con la rasante en la Z (``points``) y las cifras de su operación (``figures``: la clave
    ``des.road_*`` → su valor). ``profile_code`` es el código del perfil, que lee la operación de la capa."""

    code: str
    name: str
    calc_name: str
    state: EntityState
    profile: str
    class_name: str
    points: np.ndarray
    figures: Mapping[str, float]
    profile_code: str = ""

    @property
    def live(self) -> bool:
        """Si sus datos están vivos (la descartada sale en la capa pero no es entrada)."""
        return self.state is not EntityState.DISCARDED


def _value(resolved: Mapping[str, object], key: str) -> str:
    """El texto del parámetro ``key`` ya resuelto (``""`` si ningún ámbito lo tiene o no tiene valor)."""
    found = resolved.get(key)
    raw = getattr(found, "value_json", None)
    if raw is None:
        return ""
    value = json.loads(raw)
    return value.strip() if isinstance(value, str) else ""


def _layer_entries(listed: entities.EntityRegistry) -> list[entities.EntityEntry]:
    """Las pistas **calculadas** del registro que salen en la capa (:data:`LAYER_STATES`: al día, obsoletas, con el apoyo retirado y descartadas)."""
    return [entry for entry in listed if entry.record.kind == EntityKind.ROAD and entry.operation_uid is not None and EntityState(entry.record.state) in LAYER_STATES]


def road_heads(project: StoreProject, conn: sqlite3.Connection, version: Version, *, listed: entities.EntityRegistry | None = None) -> tuple[RoadHead, ...]:
    """Las pistas **calculadas** de la versión ``version`` como las ve la capa, sin leer su eje (RF-017-27; solo lee con la instantánea de ``conn``): del registro de las entidades su código, su nombre, su
    estado y su operación vigente y, de los parámetros resueltos versión → proyecto, el perfil que usa y la clase normativa de ese perfil, que la pista **no lee** pero la capa dice. Por orden de código.
    Es lo barato que compara :func:`road_layer_pending` con la tabla."""
    shown = _layer_entries(entities.registry(project, version.uid, conn=conn) if listed is None else listed)
    if not shown:
        return ()
    store = ParameterStore(project)
    scopes = (VERSION_SCOPE, PROJECT_SCOPE)
    keys = [entity_key(entry.record.code, RoadParam.PROFILE) for entry in shown]
    resolved = store.resolve_many(conn, keys, scopes, version=version.uid)
    codes = [_value(resolved, key) for key in keys]
    classes = store.resolve_many(conn, [road_profile_key(code, RoadProfileParam.CLASS) for code in dict.fromkeys(codes) if code and is_code(code)], scopes, version=version.uid)
    names = {item.code: item.name for item in road_profiles.read_profiles(conn)}
    return tuple(RoadHead(entry.record.code, entry.record.name, EntityState(entry.record.state), str(entry.operation_uid), code, names.get(code, ""),
                          _value(classes, road_profile_key(code, RoadProfileParam.CLASS)) if code and is_code(code) else "")
                 for entry, code in zip(shown, codes, strict=True))


_AXIS = 'SELECT x, y, level_m FROM "{table}" ORDER BY fid'
_FIGURES_OF = "SELECT operation_uid, key, value FROM gb_figure WHERE key IN ({keys}) AND operation_uid IN ({marks})"
_CHUNK = 400


def _figures(conn: sqlite3.Connection, operations: Iterable[str]) -> dict[str, dict[str, float]]:
    """Las cifras de la capa (:data:`FIGURE_COLUMNS`) de cada operación de ``operations``, por su uid; las que no tiene, no salen."""
    keys = [key for _column, key in FIGURE_COLUMNS]
    found: dict[str, dict[str, float]] = {}
    uids = sorted(set(operations))
    for first in range(0, len(uids), _CHUNK):
        part = uids[first:first + _CHUNK]
        sql = _FIGURES_OF.format(keys=", ".join("?" for _ in keys), marks=", ".join("?" for _ in part))
        for uid, key, value in conn.execute(sql, (*keys, *part)):
            if value is not None:
                found.setdefault(str(uid), {})[str(key)] = float(value)
    return found


def _axis(conn: sqlite3.Connection, head: RoadHead, version: Version) -> tuple[str, np.ndarray]:
    """El nombre con que se calculó (el de su ``des_rdx_``, sin el prefijo) y el eje por estaciones ``(n, 3)`` de la pista ``head``, de su ``des_rdx_`` **vigente**, **si se puede usar** (como la huella de
    una entidad para la capa de entidades): lo editado fuera de Geoblender sin ser editable a mano se rechaza con ``des.axes_layer_blocked``, y lo que falta, lo dañado o lo que ya no es el eje de una pista,
    con ``des.axes_layer_unusable``. Solo lee."""
    rows = conn.execute(entity_store._ENTITY_DATA, (head.operation_uid, DATASET, provenance.ROAD_AXIS_ROLE)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"la operación {head.operation_uid} de la pista {head.code} escribió {len(rows)} ejes por estaciones, no uno")
    ((table, dataset, status),) = rows
    where = {"obj": f"Pista «{head.name}»", "field": "eje", "value": str(table), "entity": head.name, "table": str(table), "version": version.code}
    if str(status) == DatasetStatus.BLOCKED.value:
        raise DesignError("des.axes_layer_blocked", **where)
    if str(status) in entity_store._UNUSABLE_STATUSES:
        raise DesignError("des.axes_layer_unusable", **where)
    try:
        points = _points(conn.execute(_AXIS.format(table=table)).fetchall())
    except (ValueError, TypeError, sqlite3.Error) as error:
        raise DesignError("des.axes_layer_unusable", **where) from error
    prefix = provenance.dataset_name(provenance.ROAD_AXIS_TABLE, "x")[:-1]
    return str(dataset).removeprefix(prefix), points


def road_sources(project: StoreProject, version: Version, *, conn: sqlite3.Connection | None = None) -> tuple[RoadSource, ...]:
    """Las pistas **calculadas** de la versión ``version`` como las ve la capa de ejes (RF-017-27; solo lee): las del registro con operación vigente (:data:`LAYER_STATES`: al día, obsoletas, con el apoyo
    retirado y **descartadas**, que siguen en el proyecto; no las «sin calcular», que no tienen eje), cada una con su estado, su perfil y su clase (:func:`road_heads`), el eje de su ``des_rdx_`` vigente (la
    de una descartada, de su dato descartado) y las cifras de su operación. Por orden de código. ``conn`` es una conexión de lectura de quien llama (una instantánea); sin ella, una propia."""
    if conn is None:
        with entity_store._consistent(project) as reading:
            return road_sources(project, version, conn=reading)
    heads = road_heads(project, conn, version)
    figures = _figures(conn, (head.operation_uid for head in heads))
    found = []
    for head in heads:
        calc_name, points = _axis(conn, head, version)
        found.append(RoadSource(head.code, head.name, calc_name, head.state, head.profile, head.class_name, points, figures.get(head.operation_uid, {}), head.profile_code))
    return tuple(found)


# --- Las filas -----------------------------------------------------------------------------------------


def road_layer_rows_steps(sources: Sequence[RoadSource]) -> Generator[Progress, None, tuple[RoadLayerRow, ...]]:
    """**El cálculo de la capa de ejes de pistas**, compartido por la orden, el recálculo y lo que sigue a cada orden de pistas (sin proyecto dentro: recibe lo leído): de cada pista de ``sources`` una
    :class:`RoadLayerRow` con su eje y las cifras de su operación, **por código** y una por paso. Lo mismo da la misma tabla (el mismo hash)."""
    ordered = sorted(sources, key=lambda item: entities.code_order(item.code))
    rows: list[RoadLayerRow] = []
    for index, source in enumerate(ordered):
        yield Progress(_LAYER_PHASE, index, len(ordered), f"Capa de ejes de pistas: «{source.name}»…")
        rows.append(RoadLayerRow(code=source.code, name=source.name, class_name=source.class_name, state=source.state, profile=source.profile, points=source.points,
                                 **{column: source.figures.get(key) for column, key in FIGURE_COLUMNS}))
    return tuple(rows)


def road_layer_rows(sources: Sequence[RoadSource]) -> tuple[RoadLayerRow, ...]:
    """Las filas de :func:`road_layer_rows_steps` de una vez (para quien no necesita los pasos)."""
    work = road_layer_rows_steps(sources)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def layer_differences(shown: Mapping[str, tuple[str, str, str, str]], wanted: Mapping[str, tuple[str, str, str, str]]) -> tuple[str, ...]:
    """Los códigos de las pistas en que la capa (``shown``: código → nombre, estado, clase y perfil, como los dice la tabla) **no dice lo que el registro** (``wanted``: lo mismo, de hoy): la que tiene otro
    nombre, otro estado, otra clase u otro perfil, la que falta y la que sobra; por código. Ninguno si dicen lo mismo. Es lo que mira :func:`road_layer_pending`."""
    return tuple(sorted(code for code in {*shown, *wanted} if shown.get(code) != wanted.get(code)))


# --- La operación ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreparedRoadLayer:
    """Lo que se lee antes de poner al día la capa de ejes (:func:`prepare_road_layer`): la ``version``, las pistas calculadas (``sources``) y lo que anotará la operación (``start``)."""

    version: Version
    sources: tuple[RoadSource, ...]
    start: OperationStart


def _live_layer(conn: sqlite3.Connection, version: Version) -> str | None:
    """El uid de la operación que escribió la capa vigente de la versión (``des_rax``), la que sustituye la nueva; ``None`` si todavía no se escribió. Si la capa se editó fuera de Geoblender, la última
    operación de Geoblender que la escribió (``core.datasets.external.last_writer``)."""
    record = dataset_registry.get(conn, provenance.dataset_name(provenance.ROAD_LAYER_TABLE), version_uid=version.uid)
    if record is None or not record.live:
        return None
    return dataset_external.last_writer(conn, record.uid)


def prepare_road_layer(project: StoreProject, version: Version | str | None, *, supersedes: str | None = None) -> PreparedRoadLayer:
    """Prepara ``des.road_layer`` en la versión editable ``version`` (spec 017, T26; RF-017-27): lee las pistas calculadas (:func:`road_sources`) y arma lo que anotará la operación: sus ajustes (las pistas que
    enseña), como entradas, de las **vivas**, su huella ``des_epr_``, su eje ``des_rdx_`` y su informe ``des_prp_`` (la descartada sale en la capa pero no es entrada: sus datos están descartados) y, como
    parámetros, el perfil de cada pista y su clase (la pista no la lee: la lee la capa). ``supersedes``: la capa que sustituye (por defecto, la vigente de la versión, si la hay).

    Rechazos, sin escribir nada: los de :func:`~.store.require_version` (RF-009-21: sin versión activa, desconocida o no editable) y los de :func:`road_sources` (un eje que no se puede usar)."""
    wanted = version.uid if isinstance(version, Version) else version
    found = require_version(project, wanted, provenance.ROAD_LAYER)
    with entity_store._consistent(project) as conn:
        sources = road_sources(project, found, conn=conn)
        before = _live_layer(conn, found) if supersedes is None else supersedes
    live = [source for source in sources if source.live]
    settings = provenance.road_layer_settings([(source.code, source.name) for source in sources])
    inputs = provenance.road_layer_inputs(dict.fromkeys(source.calc_name for source in live))
    params = provenance.road_layer_params([(source.code, source.profile_code) for source in live if source.profile_code])
    return PreparedRoadLayer(found, sources, _start(project, provenance.ROAD_LAYER, "", found, None, settings, inputs, params, before))


def _layer_message(count: int, version_code: str) -> str:
    """El mensaje de la operación: cuántas pistas enseña la capa de ejes de la versión."""
    if count == 0:
        return f"La capa de ejes de pistas de {version_code} no tiene ninguna pista calculada"
    if count == 1:
        return f"La capa de ejes de pistas de {version_code} enseña 1 pista"
    return f"La capa de ejes de pistas de {version_code} enseña {count} pistas"


def _layer_run(project: StoreProject, handle: OperationHandle, prepared: PreparedRoadLayer, budget_s: float) -> Generator[Progress, None, None]:
    with DesignWriter(project, provenance.ROAD_LAYER, "", version=handle.version_uid, handle=handle) as writer:
        rows = yield from road_layer_rows_steps(prepared.sources)
        yield from pipeline.forward(_store_steps(writer.road_layer_steps(rows), budget_s, "la capa de ejes de pistas"))
        message = _layer_message(len(rows), prepared.version.code)
        stored = writer.commit(message=message)
        yield Progress(_STORE_PHASE, 1, 1, message, result=stored)


def run_road_layer(project: StoreProject, *, version: Version | str | None, supersedes: str | None = None, budget_s: float = STEP_BUDGET_S
                   ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Pone al día la capa de ejes de pistas de la versión ``version`` **de una vez**, sin pedir confirmación (spec 017, T26; RF-017-27; plan 015 §5.3.2: una operación aparte que cada orden de pistas hace en
    su propia transacción): empieza la operación ``des.road_layer`` —si ``supersedes`` es la de una capa anterior (por defecto, la vigente de la versión), la sustituye— con lo que lee hoy y devuelve su
    ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan las filas (:func:`road_layer_rows_steps`), reescriben la tabla entera ``des_rax_<vNN>`` con su fila de estilo y completan la
    operación en **una** transacción; el último lleva el :class:`~.store.Stored`. Cerrarlos antes, o un fallo, no dejan nada y la operación queda cancelada o fallida. Al llamar, sin empezar nada: los
    rechazos de :func:`prepare_road_layer`."""
    prepared = prepare_road_layer(project, version, supersedes=supersedes)
    handle = prepared.start.begin(project)
    return handle, _layer_run(project, handle, prepared, budget_s)


def road_layer_steps(project: StoreProject, version: Version | str | None, *, supersedes: str | None = None, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, None]:
    """Los pasos de **poner al día la capa de ejes de pistas** de la versión ``version`` (spec 017, T26; RF-017-27: es lo que las órdenes de pistas encadenan tras su commit,
    :func:`~.entity_store.after_entity_change`): lo de :func:`run_road_layer` empezando al avanzar, sin devolver el ``OperationHandle``; el último paso lleva el :class:`~.store.Stored`. Repetirla con las
    mismas pistas da la misma tabla y el mismo hash y sustituye a la vigente."""
    _handle, work = run_road_layer(project, version=version, supersedes=supersedes, budget_s=budget_s)
    yield from work


def recompute_road_layer(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.road_layer`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; spec 017, T26; RF-017-27): la capa es de la **versión**, no de una pista, así
    que se rehace entera con las pistas calculadas de la versión y sus estados de hoy, sustituyendo a la que se repite (lo descartado sale de sus entradas: ``OperationDef.drops_discarded``). Devuelve lo
    de :func:`run_road_layer`. ``VersionError`` si la petición no es de una versión editable."""
    project: StoreProject = request.project  # type: ignore[assignment]
    return run_road_layer(project, version=request.version, supersedes=request.operation_uid, budget_s=budget_s)


def _wanted(heads: Iterable[RoadHead]) -> dict[str, tuple[str, str, str, str]]:
    return {head.code: (head.name, str(head.state), head.class_name, head.profile) for head in heads}


def road_layer_pending(project: StoreProject, conn: sqlite3.Connection, version_uid: str) -> bool:
    """Si la capa de ejes de pistas de la versión ``version_uid`` (su uid) **no dice lo que dice el registro** de sus pistas (spec 017, T26; RF-017-27; hallazgo D-1 de la 016 con la pista): alguna pista
    calculada no tiene su fila (la tabla ni existe, si es la primera de la versión), o la fila de alguna tiene otro nombre, otro **estado** (al día, obsoleta, con el apoyo retirado o descartada), otra clase
    normativa u otro perfil, o queda una fila de lo que ya no sale. Es **la marca** de una capa atrasada: la capa escribe el estado que deduce el grafo en el momento de escribirla, y el grafo cambia después
    por vías que no la regeneran (cambiar un parámetro, recalcular una pista con la misma salida —la 008 no toca lo que depende de lo que no cambió—, dar por bueno un apoyo, cambiar la clase de un
    perfil, o cerrar con Esc o un fallo lo que sigue a crear una pista antes de la capa). Quien la pone al día es :func:`road_layer_sync_steps`. Barata y de solo lectura (con la instantánea de ``conn``): sin
    ninguna operación ``des.road`` vigente en la versión, una consulta; con ellas, el registro de las entidades, los parámetros del perfil y la columna de código, nombre, estado, clase y perfil de la
    tabla, **sin leer su geometría**. Una capa que no se puede usar (editada fuera de Geoblender y bloqueada, o dañada) no se marca: no es de la capa decidirlo, y la 008 ofrece resolverla. Si no se puede
    saber, **está marcada**: lo seguro es no darla por buena, y quien intente ponerla al día dirá el motivo."""
    if not provenance.has_road_operation(conn, version_uid):
        return False
    try:
        version = versions_read.version(conn, version_uid)
        if version is None:
            return True
        wanted = _wanted(road_heads(project, conn, version))
        record = dataset_registry.get(conn, provenance.dataset_name(provenance.ROAD_LAYER_TABLE), version_uid=version_uid)
        if record is None or not record.live:
            return bool(wanted)
        if str(record.status) in entity_store._UNUSABLE_STATUSES:
            return False
        shown = {str(code): (str(name), str(state), str(class_name), str(profile)) for code, name, state, class_name, profile in conn.execute(
            f'SELECT code, name, state, class_name, profile FROM "{record.locator}"')}
        return bool(layer_differences(shown, wanted))
    except (DesignError, ValueError, sqlite3.Error):
        return True


def road_layer_sync_steps(project: StoreProject, version: Version | str | None, *, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, bool]:
    """Los pasos de **poner al día la capa de ejes de pistas de la versión** ``version`` **si está marcada** (:func:`road_layer_pending`; spec 017, T26; RF-017-27): lo de :func:`road_layer_steps` solo si la
    capa no dice lo que el registro y, si no, **nada** (ni un paso: no se escribe ninguna operación). Devuelve si la regeneró. Lo hacen, tras lo suyo, :func:`~.entity_store.layers_sync_steps` (por ``bl``,
    al terminar «Recalcular lo obsoleto») y dar por bueno un apoyo. Cada paso es de ``budget_s`` como mucho y cerrarlos (Esc) no deja nada a medias (una operación y una transacción). Rechazos, sin escribir
    nada: los de :func:`~.store.require_version` (RF-009-21)."""
    wanted = None if version is None else (version.uid if isinstance(version, Version) else version)
    found = require_version(project, wanted, provenance.ROAD_LAYER)
    with entity_store._consistent(project) as conn:
        if not road_layer_pending(project, conn, found.uid):
            return False
    yield from road_layer_steps(project, found, budget_s=budget_s)
    return True


def written_rows(stored: Stored, conn: sqlite3.Connection) -> int:
    """Cuántas pistas enseña la capa que acaba de escribir ``stored`` (para lo que cuenta lo que sigue a una orden de pistas)."""
    (record,) = stored.records
    (count,) = conn.execute(f'SELECT COUNT(*) FROM "{record.locator}"').fetchone()
    return int(count)
