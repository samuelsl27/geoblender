# SPDX-License-Identifier: GPL-3.0-or-later
"""Las capas de cortas de una versión para QGIS: ``des_pit_<vNN>`` (las polilíneas de diseño) y ``des_sky_<vNN>`` (la línea de cielo) (spec 018, T27; HU-018-4; RF-018-33, RF-015-27, RF-008-56; plan 018
§5.1, §5.2.3 y §5.3.2; D-19; el patrón de ``design.road_layer``).

``des.pit_layer`` es la operación de la **versión** que pone en ``des_pit_<vNN>`` una fila por **polilínea** de cada corta **calculada** —``LINESTRING`` con la cota en la Z de cada vértice (coordenadas
absolutas en float64, en el CRS del proyecto: ``core.gpkg.wkb`` ya escribe la Z), con el código y el nombre de su corta, su estado (:class:`~.entities.EntityState`: al día, obsoleta, con el «apoyo retirado» o
descartada, que se dibuja atenuada), su banco, su **tipo** (``foot``, ``crest`` o ``ramp``: el eje de cada rampa va como una línea más), su zona, su sector, su parte, su orden, su rampa, si es una línea fijada,
su cota y su longitud— y en ``des_sky_<vNN>`` una fila por línea de la **línea de cielo**. QGIS 4.2 las abre con el estilo **por tipo** de ``core.constraints.styles``. Son **salidas, no editables a mano**
(D-19, RF-008-56) y **no reproducibles** (como ``des_rax_`` y ``des_enl_``): las cortas cambian desde su capa de origen o sus parámetros y estas capas se regeneran tras cada orden de cortas
(:func:`~.entity_store.after_entity_change`) y al terminar «Recalcular lo obsoleto» (:func:`~.entity_store.layers_sync_steps`); si se editan en QGIS, se bloquean. **Su estado es el del registro**:
:func:`pit_layer_pending` las marca si dicen otra cosa que él.

Este módulo es **perezoso** (``design.provenance`` declara la operación; ``bl`` y ``design.store`` lo importan al usarla, RNF-001-03). Python puro (nivel 8).
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ..core.datasets import external as dataset_external
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetStatus
from ..core.gpkg.base import ColumnDef, create_feature_table, set_column_titles
from ..core.gpkg.wkb import encode_geometry
from ..core.project.model import Progress
from ..core.provenance.operations import OperationHandle
from ..core.provenance.recompute import RecomputeRequest
from ..core.versions import read as versions_read
from ..core.versions.model import Version, version_locator
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.store import StoreProject
from . import entities, entity_store, pipeline, pit_lines, provenance
from .entities import EntityKind, EntityState
from .entity_layer import LAYER_STATES
from .messages import DesignError
from .store import _STORE_PHASE, DesignWriter, OperationStart, Stored, _start, _store_steps, require_version

__all__ = [
    "KINDS",
    "PIT_COLUMN_NAMES",
    "PIT_COLUMN_TITLES",
    "SKY_COLUMN_NAMES",
    "SKY_COLUMN_TITLES",
    "PitHead",
    "PitLayerRow",
    "PitSource",
    "PreparedPitLayer",
    "SkyLayerRow",
    "create_pit_layer_table",
    "create_sky_layer_table",
    "layer_differences",
    "marked_pits",
    "pit_heads",
    "pit_layer_pending",
    "pit_layer_rows_steps",
    "pit_layer_steps",
    "pit_layer_sync_steps",
    "pit_layer_table",
    "pit_sources",
    "prepare_pit_layer",
    "read_pit_layer",
    "read_sky_layer",
    "recompute_pit_layer",
    "run_pit_layer",
    "sky_layer_table",
    "write_pit_layer",
    "write_sky_layer",
    "written_rows",
]

GEOMETRY_TYPE = "LINESTRING"
PIT_IDENTIFIER = "Polilíneas de cortas"
SKY_IDENTIFIER = "Línea de cielo de cortas"
"""El principio del identificador de cada capa en ``gpkg_contents`` (lleva el código de la versión)."""
KINDS: tuple[str, ...] = ("foot", "crest", "ramp")
"""Los tipos de polilínea de la capa (``kind``): el pie y la cresta de cada banco (``des_pbl_``) y el eje de cada rampa (``des_prl_``). La berma no es una línea: es la banda entre el pie de un banco y la cresta
del de abajo."""

_TABLE = re.compile(r"[a-z][a-z0-9_]{0,62}")
_VERSION_SUFFIX = re.compile(r"v[0-9]+")
_LAYER_PHASE = "pit_layer"

PIT_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("code", "TEXT", True), ColumnDef("name", "TEXT", True), ColumnDef("state", "TEXT", True), ColumnDef("bench", "INTEGER", True), ColumnDef("kind", "TEXT", True),
    ColumnDef("zone", "TEXT", True, "''"), ColumnDef("sector", "TEXT", True, "''"), ColumnDef("part", "INTEGER", True), ColumnDef("ordinal", "INTEGER", True),
    ColumnDef("ramp", "TEXT", True, "''"), ColumnDef("fixed", "INTEGER", True), ColumnDef("z_m", "DOUBLE", False), ColumnDef("length_m", "DOUBLE", True))
PIT_COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in PIT_COLUMNS)
"""Las columnas de ``des_pit_<vNN>`` además de ``fid`` y ``geom``, en su orden (RF-018-33: tipo, banco, cota, zona, sector y longitud, con la corta y su estado)."""
PIT_COLUMN_TITLES: Mapping[str, str] = MappingProxyType({
    "code": "Código", "name": "Nombre", "state": "Estado", "bench": "Banco", "kind": "Tipo", "zone": "Zona", "sector": "Sector", "part": "Parte", "ordinal": "Orden", "ramp": "Rampa",
    "fixed": "Línea fijada", "z_m": "Cota (m)", "length_m": "Longitud (m)"})
SKY_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("code", "TEXT", True), ColumnDef("name", "TEXT", True), ColumnDef("state", "TEXT", True), ColumnDef("part", "INTEGER", True), ColumnDef("length_m", "DOUBLE", True))
SKY_COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in SKY_COLUMNS)
"""Las columnas de ``des_sky_<vNN>`` además de ``fid`` y ``geom``."""
SKY_COLUMN_TITLES: Mapping[str, str] = MappingProxyType({"code": "Código", "name": "Nombre", "state": "Estado", "part": "Parte", "length_m": "Longitud (m)"})
if set(PIT_COLUMN_TITLES) != set(PIT_COLUMN_NAMES) or set(SKY_COLUMN_TITLES) != set(SKY_COLUMN_NAMES):  # pragma: no cover - un error del programa
    raise RuntimeError("cada columna de las capas de cortas lleva su título")


def pit_layer_table(version_code: str) -> str:
    """La tabla de las polilíneas de las cortas de la versión ``version_code`` («V01»): ``des_pit_v01`` (``core.versions.model.version_locator``). ``ValueError`` con un código que no es el de una versión."""
    return version_locator(provenance.dataset_name(provenance.PIT_LAYER_TABLE), version_code)


def sky_layer_table(version_code: str) -> str:
    """La tabla de la línea de cielo de las cortas de la versión ``version_code``: ``des_sky_v01``."""
    return version_locator(provenance.dataset_name(provenance.PIT_SKY_LAYER_TABLE), version_code)


def _text(value: object, what: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    found = value.strip()
    if not found and not empty:
        raise ValueError(f"{what} es un texto con algo escrito")
    return found


def _real(value: object, what: str, *, none: bool = False) -> float | None:
    if value is None and none:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | np.floating):
        raise TypeError(f"{what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} es un número finito, no {value!r}")
    return number


def _whole(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise TypeError(f"{what} es un entero, no {value!r}")
    return int(value)


def _points(points: object, what: str) -> np.ndarray:
    try:
        array = np.array(points, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{what} son vértices con (x, y, z) numéricas") from error
    if array.ndim != 2 or array.shape[1] != 3 or array.shape[0] < 2:
        raise ValueError(f"{what} son al menos dos vértices (x, y, z), con la cota en la Z")
    if not np.isfinite(array).all():
        raise ValueError(f"{what} tienen sus coordenadas finitas")
    array.flags.writeable = False
    return array


def _state(value: object) -> EntityState:
    state = EntityState(value)
    if state not in LAYER_STATES:
        raise ValueError(f"una corta {state.value} no tiene líneas: no sale en las capas (salen {', '.join(sorted(item.value for item in LAYER_STATES))})")
    return state


def _pit_code(value: object) -> str:
    code = _text(value, "el código de una corta")
    if entities.kind_of_code(code) is not EntityKind.PIT:
        raise ValueError(f"el código {code!r} no es el de una corta (PIT-001): las capas de cortas solo tienen cortas")
    return code


@dataclass(frozen=True, slots=True, eq=False)
class PitLayerRow:
    """Una polilínea de una corta calculada en la capa (una fila de ``des_pit_<vNN>``): el ``code``, el ``name`` y el ``state`` de su corta, su ``bench``, su ``kind`` (uno de :data:`KINDS`), su ``zone``,
    su ``sector``, su ``part``, su ``ordinal`` (el orden de la polilínea en la corta, desde 1), la ``ramp`` (el código de la definición, solo en las de tipo ``ramp``), si es una línea ``fixed`` (1 o 0), su cota
    (``z_m``: la de su primer vértice; ``None`` en una rampa, que sube) y su longitud en planta; ``points`` ``(n, 3)`` absolutas (``closed``: un anillo **sin** repetir el primer vértice, que se cierra al
    escribirlo). ``layer`` y ``fid``: la tabla y la fila, de una leída. Los errores son del programa (``TypeError`` o ``ValueError``)."""

    code: str
    name: str
    state: EntityState | str
    bench: int
    kind: str
    points: object
    zone: str = ""
    sector: str = ""
    part: int = 0
    ordinal: int = 0
    ramp: str = ""
    fixed: int = 0
    z_m: float | None = None
    length_m: float = 0.0
    closed: bool = False
    layer: str = ""
    fid: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _pit_code(self.code))
        object.__setattr__(self, "name", _text(self.name, "el nombre de una corta"))
        object.__setattr__(self, "state", _state(self.state))
        object.__setattr__(self, "bench", _whole(self.bench, "el banco"))
        if self.kind not in KINDS:
            raise ValueError(f"el tipo de una polilínea es uno de {KINDS}, no {self.kind!r}")
        for field in ("zone", "sector", "ramp"):
            object.__setattr__(self, field, _text(getattr(self, field), f"«{field}»", empty=True))
        object.__setattr__(self, "part", _whole(self.part, "la parte"))
        object.__setattr__(self, "ordinal", _whole(self.ordinal, "el orden"))
        object.__setattr__(self, "fixed", 1 if _whole(self.fixed, "«fixed»") else 0)
        object.__setattr__(self, "z_m", _real(self.z_m, "la cota", none=True))
        object.__setattr__(self, "length_m", _real(self.length_m, "la longitud"))
        object.__setattr__(self, "points", _points(self.points, "una polilínea de la corta"))
        object.__setattr__(self, "closed", bool(self.closed))
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "fid", int(self.fid))


@dataclass(frozen=True, slots=True, eq=False)
class SkyLayerRow:
    """Una línea de la línea de cielo de una corta (una fila de ``des_sky_<vNN>``): el ``code``, el ``name`` y el ``state`` de su corta, su ``part`` (desde 1), su ``length_m`` en planta y sus ``points``
    ``(n, 3)`` con la cota del terreno en la Z. ``layer`` y ``fid``: de una leída."""

    code: str
    name: str
    state: EntityState | str
    part: int
    length_m: float
    points: object
    layer: str = ""
    fid: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _pit_code(self.code))
        object.__setattr__(self, "name", _text(self.name, "el nombre de una corta"))
        object.__setattr__(self, "state", _state(self.state))
        object.__setattr__(self, "part", _whole(self.part, "la parte"))
        object.__setattr__(self, "length_m", _real(self.length_m, "la longitud"))
        object.__setattr__(self, "points", _points(self.points, "una línea de cielo"))
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "fid", int(self.fid))


# --- Las tablas ------------------------------------------------------------------------------------


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _check_table(table: object) -> str:
    if not isinstance(table, str) or _TABLE.fullmatch(table) is None:
        raise ValueError(f"{table!r} no es el nombre de una tabla del GeoPackage (un identificador en minúsculas: letras, cifras y «_», empezando por una letra)")
    return table


def _create(conn: sqlite3.Connection, table: str, srs_id: int, columns: tuple[ColumnDef, ...], titles: Mapping[str, str], identifier: str) -> bool:
    _check_table(table)
    if _exists(conn, table):
        return False
    suffix = table.rpartition("_")[2]
    label = f"{identifier} {suffix.upper()}" if _VERSION_SUFFIX.fullmatch(suffix) else f"{identifier} ({table})"
    create_feature_table(conn, table, GEOMETRY_TYPE, srs_id, True, columns, label, f"{identifier}, de Geoblender: una por versión, no editable a mano")
    set_column_titles(conn, table, titles)
    return True


def create_pit_layer_table(conn: sqlite3.Connection, table: str, srs_id: int) -> bool:
    """Crea en la transacción de ``conn`` la capa de líneas ``table`` de las polilíneas de las cortas (:data:`PIT_COLUMNS`, ``LINESTRING`` **con Z** y el CRS ``srs_id``) con los títulos en español, y la
    registra en ``gpkg_contents`` y ``gpkg_geometry_columns``; ``True`` si la creó y ``False`` si ya estaba. ``ValueError`` si ``table`` no es un nombre de tabla."""
    return _create(conn, table, srs_id, PIT_COLUMNS, PIT_COLUMN_TITLES, PIT_IDENTIFIER)


def create_sky_layer_table(conn: sqlite3.Connection, table: str, srs_id: int) -> bool:
    """Como :func:`create_pit_layer_table` para la línea de cielo (:data:`SKY_COLUMNS`)."""
    return _create(conn, table, srs_id, SKY_COLUMNS, SKY_COLUMN_TITLES, SKY_IDENTIFIER)


def _srs_for_write(conn: sqlite3.Connection, table: str, srs_id: int | None) -> int:
    if _exists(conn, table):
        found = conn.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?", (table,)).fetchone()
        if found is None:
            raise ValueError(f"«{table}» no es una capa registrada en gpkg_geometry_columns")
        if srs_id is not None and srs_id != int(found[0]):
            raise ValueError(f"«{table}» está en el SRS {int(found[0])}, no en el {srs_id}")
        return int(found[0])
    if srs_id is None:
        raise ValueError(f"«{table}» no existe: crearla pide el SRS del proyecto")
    return srs_id


def _closed(points: np.ndarray, closed: bool) -> np.ndarray:
    return np.vstack([points, points[:1]]) if closed else points


def write_pit_layer(conn: sqlite3.Connection, table: str, rows: Iterable[PitLayerRow], *, srs_id: int | None = None) -> tuple[int, ...]:
    """Reescribe la tabla ``table`` de las polilíneas de las cortas con ``rows`` y devuelve sus ``fid`` (RF-018-33): la operación es la única dueña de la tabla, así que se **sustituye entera**, **por código de
    corta y orden** y con los ``fid`` desde 1 (también el contador del autoincremento): las mismas filas dan siempre los mismos bytes y el mismo hash. Con ``rows`` vacío, la tabla queda vacía. Si la tabla no
    existe, la crea con el CRS ``srs_id``. La geometría **absoluta en float64** y la cota en la Z. ``ValueError`` (errores del programa) si dos filas repiten el código y el orden o ``table`` no es una capa
    registrada; ``TypeError`` si una fila no es una :class:`PitLayerRow`. No confirma la transacción."""
    found = tuple(rows)
    _check_table(table)
    for item in found:
        if not isinstance(item, PitLayerRow):
            raise TypeError(f"una fila de la capa de polilíneas de cortas es una PitLayerRow, no {item!r}")
    keys = [(item.code, item.ordinal) for item in found]
    if len(set(keys)) != len(keys):
        raise ValueError("dos polilíneas de la capa repiten la corta y el orden")
    srs = _srs_for_write(conn, table, srs_id)
    create_pit_layer_table(conn, table, srs)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    names = ", ".join(("geom", *PIT_COLUMN_NAMES))
    marks = ", ".join("?" for _ in range(len(PIT_COLUMN_NAMES) + 1))
    fids: list[int] = []
    for item in sorted(found, key=lambda row: (entities.code_order(row.code), row.ordinal)):
        blob = encode_geometry(GEOMETRY_TYPE, _closed(np.asarray(item.points), item.closed), srs, True)
        cursor = conn.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', (
            blob, item.code, item.name, str(item.state), item.bench, item.kind, item.zone, item.sector, item.part, item.ordinal, item.ramp, item.fixed, item.z_m, item.length_m))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def write_sky_layer(conn: sqlite3.Connection, table: str, rows: Iterable[SkyLayerRow], *, srs_id: int | None = None) -> tuple[int, ...]:
    """Como :func:`write_pit_layer` para la línea de cielo (``des_sky_<vNN>``), por corta y parte."""
    found = tuple(rows)
    _check_table(table)
    for item in found:
        if not isinstance(item, SkyLayerRow):
            raise TypeError(f"una fila de la capa de la línea de cielo es una SkyLayerRow, no {item!r}")
    keys = [(item.code, item.part) for item in found]
    if len(set(keys)) != len(keys):
        raise ValueError("dos líneas de cielo de la capa repiten la corta y la parte")
    srs = _srs_for_write(conn, table, srs_id)
    create_sky_layer_table(conn, table, srs)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    names = ", ".join(("geom", *SKY_COLUMN_NAMES))
    marks = ", ".join("?" for _ in range(len(SKY_COLUMN_NAMES) + 1))
    fids: list[int] = []
    for item in sorted(found, key=lambda row: (entities.code_order(row.code), row.part)):
        blob = encode_geometry(GEOMETRY_TYPE, np.asarray(item.points), srs, True)
        cursor = conn.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', (blob, item.code, item.name, str(item.state), item.part, item.length_m))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def _line(blob: object) -> np.ndarray:
    from ..core.gpkg.wkb import decode_geometry

    geometry = decode_geometry(bytes(blob), external=True)  # type: ignore[arg-type]
    if geometry.geometry_type != GEOMETRY_TYPE:
        raise ValueError(f"la geometría de una polilínea de corta es una línea, no {geometry.geometry_type}")
    return np.asarray(geometry.coords, dtype=np.float64).reshape(-1, 3)


def read_pit_layer(conn: sqlite3.Connection, table: str) -> tuple[PitLayerRow, ...]:
    """Las polilíneas de la tabla ``table``, por ``fid``, con su capa y su ``fid``; ninguna si la tabla no existe. Un anillo se devuelve **cerrado** (con el primer vértice repetido, como está en la
    tabla). ``ValueError`` si una fila no es de una polilínea de la capa."""
    _check_table(table)
    if not _exists(conn, table):
        return ()
    found = []
    for row in conn.execute(f'SELECT fid, geom, {", ".join(PIT_COLUMN_NAMES)} FROM "{table}" ORDER BY fid'):
        fid, blob, code, name, state, bench, kind, zone, sector, part, ordinal, ramp, fixed, z_m, length_m = row
        if blob is None:
            raise ValueError(f"la fila {fid} de «{table}» no tiene geometría")
        found.append(PitLayerRow(code, name, state, bench, kind, _line(blob), zone, sector, part, ordinal, ramp, fixed, z_m, length_m, False, table, int(fid)))
    return tuple(found)


def read_sky_layer(conn: sqlite3.Connection, table: str) -> tuple[SkyLayerRow, ...]:
    """Las líneas de cielo de la tabla ``table``, por ``fid``; ninguna si la tabla no existe."""
    _check_table(table)
    if not _exists(conn, table):
        return ()
    found = []
    for row in conn.execute(f'SELECT fid, geom, {", ".join(SKY_COLUMN_NAMES)} FROM "{table}" ORDER BY fid'):
        fid, blob, code, name, state, part, length_m = row
        if blob is None:
            raise ValueError(f"la fila {fid} de «{table}» no tiene geometría")
        found.append(SkyLayerRow(code, name, state, part, length_m, _line(blob), table, int(fid)))
    return tuple(found)


# --- Lo que lee el almacén -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PitHead:
    """Lo que las capas saben de una corta **calculada** sin leer sus líneas (:func:`pit_heads`): su ``code`` y su ``name`` de ahora, su ``state`` (el que deduce el grafo) y el uid de su operación vigente."""

    code: str
    name: str
    state: EntityState
    operation_uid: str

    @property
    def live(self) -> bool:
        """Si sus datos están vivos: una corta **descartada** sale en las capas (es un registro, atenuada) pero sus datos ya no son entrada de ninguna operación."""
        return self.state is not EntityState.DISCARDED


@dataclass(frozen=True, slots=True)
class PitSource:
    """Lo que las capas saben de una corta **calculada** de la versión (:func:`pit_sources`): su ``code`` y su ``name`` de ahora (``calc_name`` es con el que se calculó: el de sus datos ``des_pbl_``), su
    ``state``, sus polilíneas (``polylines``: ``des_pbl_`` tal cual, :class:`~.pit_lines.LineRow`), su línea de cielo (``skyline``: ``des_psk_``) y los ejes de sus rampas (``ramps``: ``(rampa, banco,
    vértices (n, 3))``)."""

    code: str
    name: str
    calc_name: str
    state: EntityState
    polylines: tuple[pit_lines.LineRow, ...]
    skyline: tuple[pit_lines.LineRow, ...]
    ramps: tuple[tuple[str, int, np.ndarray], ...]

    @property
    def live(self) -> bool:
        """Si sus datos están vivos (la descartada sale en las capas pero no es entrada)."""
        return self.state is not EntityState.DISCARDED


def _layer_entries(listed: entities.EntityRegistry) -> list[entities.EntityEntry]:
    """Las cortas **calculadas** del registro que salen en las capas (:data:`~.entity_layer.LAYER_STATES`: al día, obsoletas, con el apoyo retirado y descartadas)."""
    return [entry for entry in listed if entry.record.kind == EntityKind.PIT and entry.operation_uid is not None and EntityState(entry.record.state) in LAYER_STATES]


def pit_heads(project: StoreProject, conn: sqlite3.Connection, version: Version, *, listed: entities.EntityRegistry | None = None) -> tuple[PitHead, ...]:
    """Las cortas **calculadas** de la versión ``version`` como las ven las capas, sin leer sus líneas (RF-018-33; solo lee con la instantánea de ``conn``): del registro de las entidades su código, su nombre,
    su estado y su operación vigente. Por orden de código. Es lo barato que compara :func:`pit_layer_pending` con la tabla."""
    shown = _layer_entries(entities.registry(project, version.uid, conn=conn) if listed is None else listed)
    return tuple(PitHead(entry.record.code, entry.record.name, EntityState(entry.record.state), str(entry.operation_uid)) for entry in shown)


_RAMPS = 'SELECT ramp, bench, x, y, level_m FROM "{table}" ORDER BY fid'


def _data(conn: sqlite3.Connection, head: PitHead, version: Version, role: str, what: str) -> tuple[str, str]:
    """La tabla y el nombre del dato de la corta ``head`` con el papel ``role``, **si se puede usar**: lo editado fuera de Geoblender sin ser editable a mano se rechaza con ``des.pitlayer_blocked`` y lo que
    falta o lo dañado, con ``des.pitlayer_unusable``. ``ValueError`` si la operación no escribió uno solo."""
    rows = conn.execute(entity_store._ENTITY_DATA, (head.operation_uid, "dataset", role)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"la operación {head.operation_uid} de la corta {head.code} escribió {len(rows)} datos «{what}», no uno")
    ((table, dataset, status),) = rows
    where = {"obj": f"Corta «{head.name}»", "field": what, "value": str(table), "entity": head.name, "table": str(table), "version": version.code}
    if str(status) == DatasetStatus.BLOCKED.value:
        raise DesignError("des.pitlayer_blocked", **where)
    if str(status) in entity_store._UNUSABLE_STATUSES:
        raise DesignError("des.pitlayer_unusable", **where)
    return str(table), str(dataset)


def _source(conn: sqlite3.Connection, head: PitHead, version: Version) -> PitSource:
    poly_table, poly_name = _data(conn, head, version, provenance.PIT_POLYLINES_ROLE, "polilíneas")
    sky_table, _sky_name = _data(conn, head, version, provenance.PIT_SKYLINE_ROLE, "línea de cielo")
    ramp_table, _ramp_name = _data(conn, head, version, provenance.PIT_RAMPS_ROLE, "rampas")
    where = {"obj": f"Corta «{head.name}»", "field": "polilíneas", "value": poly_table, "entity": head.name, "table": poly_table, "version": version.code}
    try:
        polylines = pit_lines.read_pit_lines(conn, poly_table, pit_lines.POLYLINES, closed_column="closed")
        skyline = pit_lines.read_pit_lines(conn, sky_table, pit_lines.SKYLINE)
        ramps: dict[tuple[str, int], list[tuple[float, float, float]]] = {}
        for ramp, bench, x, y, level in conn.execute(_RAMPS.format(table=ramp_table)):
            ramps.setdefault((str(ramp), int(bench)), []).append((float(x), float(y), float(level)))
        axes = tuple((ramp, bench, _points(stations, "el eje de una rampa")) for (ramp, bench), stations in ramps.items())
    except (ValueError, TypeError, sqlite3.Error) as error:
        raise DesignError("des.pitlayer_unusable", **where) from error
    prefix = provenance.dataset_name(provenance.PIT_POLYLINES_TABLE, "x")[:-1]
    return PitSource(head.code, head.name, poly_name.removeprefix(prefix), head.state, polylines, skyline, axes)


def pit_sources(project: StoreProject, version: Version, *, conn: sqlite3.Connection | None = None) -> tuple[PitSource, ...]:
    """Las cortas **calculadas** de la versión ``version`` como las ven las capas (RF-018-33; solo lee): las del registro con operación vigente (:data:`~.entity_layer.LAYER_STATES`: al día, obsoletas, con el
    apoyo retirado y **descartadas**, que siguen en el proyecto; no las «sin calcular»), cada una con su estado y sus polilíneas, su línea de cielo y las estaciones de sus rampas, de sus datos **vigentes**.
    Por orden de código. ``conn`` es una conexión de lectura de quien llama (una instantánea); sin ella, una propia."""
    if conn is None:
        with entity_store._consistent(project) as reading:
            return pit_sources(project, version, conn=reading)
    return tuple(_source(conn, head, version) for head in pit_heads(project, conn, version))


# --- Las filas -------------------------------------------------------------------------------------


def _length(points: np.ndarray) -> float:
    return float(np.hypot(*np.diff(points[:, :2], axis=0).T).sum())


def pit_layer_rows_steps(sources: Sequence[PitSource]) -> Generator[Progress, None, tuple[tuple[PitLayerRow, ...], tuple[SkyLayerRow, ...]]]:
    """**El cálculo de las capas de cortas**, compartido por la orden, el recálculo y lo que sigue a cada orden de cortas (sin proyecto dentro: recibe lo leído): de cada corta de ``sources`` las filas de sus
    polilíneas (con el eje de cada rampa a continuación) y de su línea de cielo, **por código** y una corta por paso. Lo mismo da las mismas tablas (el mismo hash)."""
    ordered = sorted(sources, key=lambda item: entities.code_order(item.code))
    lines: list[PitLayerRow] = []
    sky: list[SkyLayerRow] = []
    for index, source in enumerate(ordered):
        yield Progress(_LAYER_PHASE, index, len(ordered), f"Capas de cortas: «{source.name}»…")
        for line in source.polylines:
            bench, kind, zone, sector, part, ordinal, closed, fixed, z_m, length_m = line.values
            lines.append(PitLayerRow(source.code, source.name, source.state, bench, kind, line.points, zone, sector, part, ordinal, "", fixed, z_m, length_m, bool(line.closed)))
        ordinal = len(source.polylines)
        for ramp, bench, points in source.ramps:
            ordinal += 1
            lines.append(PitLayerRow(source.code, source.name, source.state, bench, "ramp", points, ordinal=ordinal, ramp=ramp, length_m=_length(points)))
        for part, line in enumerate(source.skyline, start=1):
            sky.append(SkyLayerRow(source.code, source.name, source.state, part, _length(np.asarray(line.points)), line.points))
    return tuple(lines), tuple(sky)


def pit_layer_rows(sources: Sequence[PitSource]) -> tuple[tuple[PitLayerRow, ...], tuple[SkyLayerRow, ...]]:
    """Las filas de :func:`pit_layer_rows_steps` de una vez (para quien no necesita los pasos)."""
    work = pit_layer_rows_steps(sources)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def layer_differences(shown: Mapping[str, tuple[str, str]], wanted: Mapping[str, tuple[str, str]]) -> tuple[str, ...]:
    """Los códigos de las cortas en que las capas (``shown``: código → nombre y estado, como los dice la tabla) **no dicen lo que el registro** (``wanted``: lo mismo, de hoy): la que tiene otro nombre u otro
    estado, la que falta y la que sobra; por código. Ninguno si dicen lo mismo. Es lo que mira :func:`pit_layer_pending`."""
    return tuple(sorted((code for code in {*shown, *wanted} if shown.get(code) != wanted.get(code)), key=entities.code_order))


# --- La operación ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreparedPitLayer:
    """Lo que se lee antes de poner al día las capas de cortas (:func:`prepare_pit_layer`): la ``version``, las cortas calculadas (``sources``) y lo que anotará la operación (``start``)."""

    version: Version
    sources: tuple[PitSource, ...]
    start: OperationStart


def _live_layer(conn: sqlite3.Connection, version: Version) -> str | None:
    """El uid de la operación que escribió la capa vigente de la versión (``des_pit``), la que sustituye la nueva; ``None`` si todavía no se escribió. Si se editó fuera de Geoblender, la última
    operación de Geoblender que la escribió."""
    record = dataset_registry.get(conn, provenance.dataset_name(provenance.PIT_LAYER_TABLE), version_uid=version.uid)
    if record is None or not record.live:
        return None
    return dataset_external.last_writer(conn, record.uid)


def prepare_pit_layer(project: StoreProject, version: Version | str | None, *, supersedes: str | None = None) -> PreparedPitLayer:
    """Prepara ``des.pit_layer`` en la versión editable ``version`` (spec 018, T27; RF-018-33): lee las cortas calculadas (:func:`pit_sources`) y arma lo que anotará la operación: sus ajustes (las cortas que
    enseña) y, como entradas, de las **vivas**, sus polilíneas, su línea de cielo y sus rampas (la descartada sale en las capas pero no es entrada). ``supersedes``: la capa que sustituye (por defecto, la
    vigente de la versión, si la hay). Rechazos, sin escribir nada: los de :func:`~.store.require_version` (RF-009-21) y los de :func:`pit_sources`."""
    wanted = version.uid if isinstance(version, Version) else version
    found = require_version(project, wanted, provenance.PIT_LAYER)
    with entity_store._consistent(project) as conn:
        sources = pit_sources(project, found, conn=conn)
        before = _live_layer(conn, found) if supersedes is None else supersedes
    live = [source for source in sources if source.live]
    settings = provenance.pit_layer_settings([(source.code, source.name) for source in sources])
    inputs = provenance.pit_layer_inputs(dict.fromkeys(source.calc_name for source in live))
    return PreparedPitLayer(found, sources, _start(project, provenance.PIT_LAYER, "", found, None, settings, inputs, (), before))


def _layer_message(count: int, version_code: str) -> str:
    if count == 0:
        return f"Las capas de cortas de {version_code} no tienen ninguna corta calculada"
    if count == 1:
        return f"Las capas de cortas de {version_code} enseñan 1 corta"
    return f"Las capas de cortas de {version_code} enseñan {count} cortas"


def _layer_run(project: StoreProject, handle: OperationHandle, prepared: PreparedPitLayer, budget_s: float) -> Generator[Progress, None, None]:
    with DesignWriter(project, provenance.PIT_LAYER, "", version=handle.version_uid, handle=handle) as writer:
        lines, sky = yield from pit_layer_rows_steps(prepared.sources)
        yield from pipeline.forward(_store_steps(writer.pit_layer_steps(lines), budget_s, "la capa de polilíneas de cortas"))
        yield from pipeline.forward(_store_steps(writer.sky_layer_steps(sky), budget_s, "la capa de la línea de cielo"))
        message = _layer_message(len(prepared.sources), prepared.version.code)
        stored = writer.commit(message=message)
        yield Progress(_STORE_PHASE, 1, 1, message, result=stored)


def run_pit_layer(project: StoreProject, *, version: Version | str | None, supersedes: str | None = None, budget_s: float = STEP_BUDGET_S
                  ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Pone al día las capas de cortas de la versión ``version`` **de una vez**, sin pedir confirmación (spec 018, T27; RF-018-33: una operación aparte que cada orden de cortas hace en su propia
    transacción): empieza la operación ``des.pit_layer`` —si ``supersedes`` es la de una capa anterior (por defecto, la vigente de la versión), la sustituye— con lo que lee hoy y devuelve su
    ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan las filas (:func:`pit_layer_rows_steps`), reescriben las dos tablas enteras (``des_pit_<vNN>`` y ``des_sky_<vNN>``) con su
    fila de estilo y completan la operación en **una** transacción; el último lleva el :class:`~.store.Stored`. Cerrarlos antes, o un fallo, no dejan nada. Al llamar, sin empezar nada: los rechazos de
    :func:`prepare_pit_layer`."""
    prepared = prepare_pit_layer(project, version, supersedes=supersedes)
    handle = prepared.start.begin(project)
    return handle, _layer_run(project, handle, prepared, budget_s)


def pit_layer_steps(project: StoreProject, version: Version | str | None, *, supersedes: str | None = None, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, None]:
    """Los pasos de **poner al día las capas de cortas** de la versión ``version`` (es lo que las órdenes de cortas encadenan tras su commit, :func:`~.entity_store.after_entity_change`): lo de
    :func:`run_pit_layer` empezando al avanzar, sin devolver el ``OperationHandle``; el último paso lleva el :class:`~.store.Stored`. Repetirla con las mismas cortas da las mismas tablas y el mismo hash."""
    _handle, work = run_pit_layer(project, version=version, supersedes=supersedes, budget_s=budget_s)
    yield from work


def recompute_pit_layer(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.pit_layer`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; RF-018-33): las capas son de la **versión**, no de una corta, así que se
    rehacen enteras con las cortas calculadas de la versión y sus estados de hoy, sustituyendo a las que se repiten (lo descartado sale de sus entradas: ``OperationDef.drops_discarded``). Devuelve lo de
    :func:`run_pit_layer`. ``VersionError`` si la petición no es de una versión editable."""
    project: StoreProject = request.project  # type: ignore[assignment]
    return run_pit_layer(project, version=request.version, supersedes=request.operation_uid, budget_s=budget_s)


def _wanted(heads: Iterable[PitHead]) -> dict[str, tuple[str, str]]:
    return {head.code: (head.name, str(head.state)) for head in heads}


def _shown(conn: sqlite3.Connection, table: str) -> dict[str, tuple[str, str]]:
    return {str(code): (str(name), str(state)) for code, name, state in conn.execute(f'SELECT DISTINCT code, name, state FROM "{table}"')}


def _differences(project: StoreProject, conn: sqlite3.Connection, version_uid: str) -> tuple[str, ...] | None:
    """Los códigos en que la capa de polilíneas no dice lo del registro; ``None`` si la capa no se puede usar (editada fuera de Geoblender y bloqueada, o dañada). ``ValueError`` si no se puede saber."""
    version = versions_read.version(conn, version_uid)
    if version is None:
        raise ValueError(f"la versión {version_uid} no existe")
    wanted = _wanted(pit_heads(project, conn, version))
    record = dataset_registry.get(conn, provenance.dataset_name(provenance.PIT_LAYER_TABLE), version_uid=version_uid)
    if record is None or not record.live:
        return tuple(sorted(wanted, key=entities.code_order))
    if str(record.status) in entity_store._UNUSABLE_STATUSES:
        return None
    return layer_differences(_shown(conn, record.locator), wanted)


def pit_layer_pending(project: StoreProject, conn: sqlite3.Connection, version_uid: str) -> bool:
    """Si las capas de cortas de la versión ``version_uid`` (su uid) **no dicen lo que dice el registro** de sus cortas (spec 018, T27; RF-018-33): alguna corta calculada no tiene sus filas (la tabla ni existe,
    si es la primera de la versión), o las de alguna tienen otro nombre u otro **estado** (al día, obsoleta, con el apoyo retirado o descartada), o queda una fila de lo que ya no sale. Es **la marca** de una
    capa atrasada: la capa escribe el estado que deduce el grafo en el momento de escribirla, y el grafo cambia después por vías que no la regeneran (cambiar un parámetro, recalcular una corta con la misma
    salida, dar por bueno un apoyo, o cerrar con Esc o un fallo lo que sigue a crear una corta). Quien la pone al día es :func:`pit_layer_sync_steps`. Barata y de solo lectura (con la instantánea de
    ``conn``): sin ninguna operación ``des.pit`` vigente en la versión, una consulta; con ellas, el registro de las entidades y las columnas de código, nombre y estado de la tabla, **sin leer su
    geometría**. Una capa que no se puede usar (editada fuera de Geoblender y bloqueada, o dañada) no se marca: no es de la capa decidirlo, y la 008 ofrece resolverla. Si no se puede saber, **está marcada**."""
    if not provenance.has_pit_operation(conn, version_uid):
        return False
    try:
        found = _differences(project, conn, version_uid)
    except (DesignError, ValueError, sqlite3.Error):
        return True
    return bool(found)


def marked_pits(project: StoreProject, conn: sqlite3.Connection, version_uid: str) -> tuple[str, ...]:
    """Los códigos de las cortas de la versión ``version_uid`` **para las que las capas están marcadas** (spec 018, T27; RF-018-33, RF-015-25): las que tienen otro nombre u otro **estado** en las filas de la
    capa que en el registro de hoy, y las que faltan o sobran en ella (:func:`layer_differences`). Barata y de solo lectura, sin leer ninguna geometría. **Sin capa, o con una que no se puede usar**, y si no se
    puede saber, **ninguna** (:func:`pit_layer_pending` es la que no la da por buena: aquí no se afirma lo que no se sabe)."""
    if not provenance.has_pit_operation(conn, version_uid):
        return ()
    try:
        record = dataset_registry.get(conn, provenance.dataset_name(provenance.PIT_LAYER_TABLE), version_uid=version_uid)
        if record is None or not record.live:
            return ()
        return _differences(project, conn, version_uid) or ()
    except (DesignError, ValueError, sqlite3.Error):
        return ()


def pit_layer_sync_steps(project: StoreProject, version: Version | str | None, *, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, bool]:
    """Los pasos de **poner al día las capas de cortas de la versión** ``version`` **si están marcadas** (:func:`pit_layer_pending`; spec 018, T27; RF-018-33): lo de :func:`pit_layer_steps` solo si la capa no
    dice lo que el registro y, si no, **nada** (ni un paso: no se escribe ninguna operación). Devuelve si la regeneró. Lo hacen, tras lo suyo, :func:`~.entity_store.layers_sync_steps` (por ``bl``, al
    terminar «Recalcular lo obsoleto») y dar por bueno un apoyo. Rechazos, sin escribir nada: los de :func:`~.store.require_version` (RF-009-21)."""
    wanted = None if version is None else (version.uid if isinstance(version, Version) else version)
    found = require_version(project, wanted, provenance.PIT_LAYER)
    with entity_store._consistent(project) as conn:
        if not pit_layer_pending(project, conn, found.uid):
            return False
    yield from pit_layer_steps(project, found, budget_s=budget_s)
    return True


def written_rows(stored: Stored, conn: sqlite3.Connection) -> int:
    """Cuántas cortas enseñan las capas que acaba de escribir ``stored`` (para lo que cuenta lo que sigue a una orden de cortas): las distintas de la capa de polilíneas."""
    count = 0
    for record in stored.records:
        if record.locator.startswith(provenance.dataset_name(provenance.PIT_LAYER_TABLE) + "_"):
            (count,) = conn.execute(f'SELECT COUNT(DISTINCT code) FROM "{record.locator}"').fetchone()
    return int(count)
