# SPDX-License-Identifier: GPL-3.0-or-later
"""Las tablas del proyecto de las restricciones (spec 012; RF-012-01, RF-012-03, RF-012-07,
RF-012-09, RF-012-26, RF-012-27; plan 012 §5.2.1, §5.3.1, D-20, D-21, D-22, D-26 y D-35).

- :data:`TABLES` y :func:`create_tables`: las siete tablas de §5.2.1, creadas con ``execute``
  (una sentencia cada vez: ``executescript`` confirmaría la transacción) dentro de la
  transacción que las escribe por primera vez. Las tres capas de restricciones
  (``core_constraint_polygon``, ``_line`` y ``_point``; D-20, D-21), ``core_intention``
  (``GEOMETRY``) y ``core_sector`` van a ``gpkg_contents`` y ``gpkg_geometry_columns`` (2D, CRS
  del proyecto); las dos de búsquedas, como tablas de atributos. Lo que QGIS no rellena tiene
  valor por defecto o es ``NULL``: una fila así se lee y es «incompleta» (``checks``), nunca un
  error de QGIS. El tipo de las tres capas lleva la lista de valores de los once tipos con su
  español (:data:`CTYPE_ENUM`, D-35) y un ``CHECK`` que rechaza lo demás.
- Filas: :func:`read_constraints` / :func:`write_constraints` (el código, único en las tres
  capas al escribir e inmutable, D-22; al leer, un repetido se lee y lo marca ``checks``),
  :func:`read_intentions` / :func:`write_intentions`, :func:`read_sectors` /
  :func:`write_sectors` (con :func:`sector_sha256`, la huella de su geometría, D-26;
  :func:`replace_sectors` al declararlos de nuevo y :func:`sector_states`, el estado de cada
  uno según sus búsquedas, A12) y
  :func:`append_search`, :func:`read_searches` y :func:`read_hits` (solo se añaden filas).
  La geometría, **absoluta en float64**, con ``core.gpkg.wkb``: vuelve bit a bit.
- :func:`dataset_specs`: los datos del proyecto de las siete tablas (``core``; las tres capas,
  editables a mano en QGIS, RF-008-56; lo demás, no).

Todas reciben la conexión de una transacción de escritura (o una de lectura para leer) y no la
confirman. Python puro (``core``).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

import numpy as np

from ..content.builtin import GPKG_LAYER
from ..datasets import DatasetSpec, Store
from ..gpkg.base import set_column_enum, set_column_titles
from ..gpkg.wkb import decode_geometry, encode_geometry, geometry_wkb
from ..hashing import canonical_json, sha256_bytes
from .messages import ConstraintError
from .model import (
    Constraint,
    ConstraintType,
    GeometryKind,
    Intention,
    SearchHit,
    SearchRecord,
    Sector,
)

__all__ = [
    "CONSTRAINT_LAYERS",
    "CTYPE_ENUM",
    "HIT_TABLE",
    "INTENTION_TABLE",
    "SEARCH_TABLE",
    "SECTOR_TABLE",
    "TABLES",
    "ListedIntention",
    "SectorState",
    "append_search",
    "constraint_names",
    "create_tables",
    "dataset_specs",
    "layer_of",
    "listed_intentions",
    "read_constraints",
    "read_hits",
    "read_intentions",
    "read_searches",
    "read_sectors",
    "replace_sectors",
    "sector_sha256",
    "sector_states",
    "taken_codes",
    "write_constraints",
    "write_intentions",
    "write_sectors",
]

MODULE = "core"
CONSTRAINT_LAYERS: Mapping[GeometryKind, str] = MappingProxyType({
    GeometryKind.POLYGON: "core_constraint_polygon",
    GeometryKind.LINE: "core_constraint_line",
    GeometryKind.POINT: "core_constraint_point",
})
"""La capa de restricciones de cada geometría (D-20), en el orden en que se leen."""
INTENTION_TABLE = "core_intention"
SECTOR_TABLE = "core_sector"
SEARCH_TABLE = "core_untouchable_search"
HIT_TABLE = "core_untouchable_hit"
TABLES: tuple[str, ...] = (*CONSTRAINT_LAYERS.values(), INTENTION_TABLE, SECTOR_TABLE,
                           SEARCH_TABLE, HIT_TABLE)
"""Las siete tablas del proyecto de la 012 (plan §5.2.1), en el orden en que se crean."""
CTYPE_ENUM = "core_constraint_ctype"
"""El nombre de la lista de valores del tipo, la misma en las tres capas (D-35)."""

_MULTI: Mapping[GeometryKind, str] = MappingProxyType({
    GeometryKind.POLYGON: "MULTIPOLYGON",
    GeometryKind.LINE: "MULTILINESTRING",
    GeometryKind.POINT: "MULTIPOINT",
})
_KIND_OF_TYPE: Mapping[str, GeometryKind] = MappingProxyType({
    "POLYGON": GeometryKind.POLYGON, "MULTIPOLYGON": GeometryKind.POLYGON,
    "LINESTRING": GeometryKind.LINE, "MULTILINESTRING": GeometryKind.LINE,
    "POINT": GeometryKind.POINT, "MULTIPOINT": GeometryKind.POINT,
})
_CTYPES = ", ".join(f"'{ctype.value}'" for ctype in ConstraintType)

_CONSTRAINT_COLUMNS = (
    "uid", "code", "name", "ctype", "priority", "reason", "decided_by", "decided_on",
    "decision_uid", "intention_uid", "source_input", "source_fid",
)


def _constraint_ddl(table: str, geometry: str) -> str:
    return f"""CREATE TABLE {table} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  geom {geometry},
  uid TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(16)))),
  code TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  ctype TEXT CHECK (ctype IS NULL OR ctype IN ({_CTYPES})),
  priority INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  decided_by TEXT,
  decided_on DATE,
  decision_uid TEXT,
  intention_uid TEXT,
  source_input TEXT,
  source_fid INTEGER
)"""


_ROLES = ", ".join(f"'{role}'" for role in (
    "protect", "fill", "mine_to_elevation", "keep_as_is", "platform", "slope_to_treat"))

# Cada tabla: su DDL, su tipo de geometría (None: tabla de atributos), su identificador en
# gpkg_contents y su papel como dato.
_SPECS: Mapping[str, tuple[str, str | None, str, str]] = MappingProxyType({
    **{table: (_constraint_ddl(table, _MULTI[kind]), _MULTI[kind], label, "constraints")
       for (kind, table), label in zip(CONSTRAINT_LAYERS.items(), (
           "Restricciones (polígonos)", "Restricciones (líneas)", "Restricciones (puntos)"),
           strict=True)},
    INTENTION_TABLE: (f"""CREATE TABLE {INTENTION_TABLE} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  geom GEOMETRY NOT NULL,
  uid TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ({_ROLES})),
  elevation_m DOUBLE,
  stated_on DATE NOT NULL,
  document_input TEXT NOT NULL,
  decision_uid TEXT,
  source_input TEXT NOT NULL,
  source_fid INTEGER NOT NULL
)""", "GEOMETRY", "Intenciones del cliente", "intentions"),
    SECTOR_TABLE: (f"""CREATE TABLE {SECTOR_TABLE} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  geom MULTIPOLYGON NOT NULL,
  uid TEXT NOT NULL UNIQUE,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  geom_sha256 TEXT NOT NULL
)""", "MULTIPOLYGON", "Sectores de búsqueda de intocables", "sectors"),
    SEARCH_TABLE: (f"""CREATE TABLE {SEARCH_TABLE} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  uid TEXT NOT NULL UNIQUE,
  operation_uid TEXT NOT NULL,
  sector_code TEXT NOT NULL,
  sector_sha256 TEXT NOT NULL,
  distance_m DOUBLE NOT NULL,
  closed_by TEXT NOT NULL,
  closed_at DATETIME NOT NULL
)""", None, "Búsquedas de intocables", "searches"),
    HIT_TABLE: (f"""CREATE TABLE {HIT_TABLE} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  search_uid TEXT NOT NULL,
  layer_dataset TEXT NOT NULL,
  feature_fid INTEGER NOT NULL,
  distance_m DOUBLE NOT NULL,
  attributes TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('converted', 'discarded')),
  reason TEXT NOT NULL,
  constraint_code TEXT
)""", None, "Entidades halladas en las búsquedas de intocables", "search_hits"),
})

CONSTRAINT_TITLES: Mapping[str, str] = MappingProxyType({
    "uid": "Identificador", "code": "Código", "name": "Nombre", "ctype": "Tipo",
    "priority": "Prioridad", "reason": "Motivo", "decided_by": "Decisor",
    "decided_on": "Fecha de la decisión", "decision_uid": "Decisión de la propiedad",
    "intention_uid": "Intención del cliente", "source_input": "Entrada de origen",
    "source_fid": "Entidad de origen",
})
"""Los títulos en español de las columnas de las tres capas, que QGIS muestra como alias."""


def layer_of(kind: GeometryKind | str) -> str:
    """La capa de restricciones de la geometría ``kind``."""
    return CONSTRAINT_LAYERS[GeometryKind(kind)]


# --- Tablas -----------------------------------------------------------------------------------


def _existing(conn: sqlite3.Connection) -> set[str]:
    marks = ", ".join("?" for _ in TABLES)
    return {str(row[0]) for row in conn.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({marks})", TABLES)}


def create_tables(conn: sqlite3.Connection, srs_id: int) -> tuple[str, ...]:
    """Crea en la transacción de ``conn`` las tablas de :data:`TABLES` que falten, con el CRS
    ``srs_id`` (el del proyecto, en ``gpkg_spatial_ref_sys``), y devuelve las creadas, en su
    orden. Las capas de restricciones nuevas reciben los títulos en español y la lista de
    valores del tipo (D-35). ``ValueError`` si ``srs_id`` no está en la base."""
    if isinstance(srs_id, bool) or not isinstance(srs_id, int) or conn.execute(
            "SELECT 1 FROM gpkg_spatial_ref_sys WHERE srs_id = ?", (srs_id,)).fetchone() is None:
        raise ValueError(f"el SRS {srs_id!r} no está en gpkg_spatial_ref_sys: las capas de las "
                         "restricciones usan el CRS del proyecto")
    present = _existing(conn)
    created: list[str] = []
    for table in TABLES:
        if table in present:
            continue
        ddl, geometry, identifier, _role = _SPECS[table]
        conn.execute(ddl)
        if geometry is None:
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description) VALUES (?, 'attributes', ?, '')", (table, identifier))
        else:
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                         (table, identifier, srs_id))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                         "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (table, geometry, srs_id))
        if table in CONSTRAINT_LAYERS.values():
            set_column_titles(conn, table, CONSTRAINT_TITLES)
            set_column_enum(conn, table, "ctype",
                            [(ctype.value, ctype.label("es")) for ctype in ConstraintType],
                            name=CTYPE_ENUM)
        created.append(table)
    return tuple(created)


def dataset_specs(*, crs_epsg: int | None = None) -> tuple[DatasetSpec, ...]:
    """Los datos del proyecto de :data:`TABLES` (plan §5.2.1; RF-008-56): de ``core``, en
    ``project.gpkg``, leídos con ``core.gpkg_layer@1``; las capas, ``vector`` (con
    ``crs_epsg``), y las búsquedas, ``table``. Solo las tres capas de restricciones son
    editables a mano en QGIS."""
    specs = []
    for table in TABLES:
        _ddl, geometry, _identifier, role = _SPECS[table]
        specs.append(DatasetSpec(
            table, MODULE, "table" if geometry is None else "vector", Store.GPKG, table,
            reader=GPKG_LAYER.id, role=role,
            crs_epsg=None if geometry is None else crs_epsg,
            qgis_editable=table in CONSTRAINT_LAYERS.values()))
    return tuple(specs)


# --- Geometría --------------------------------------------------------------------------------


def _plan(array: object) -> np.ndarray:
    """Las coordenadas en planta ``(k, 2)`` (sin Z) de un array leído."""
    values = np.asarray(array, dtype=np.float64)
    return values.reshape(-1, values.shape[-1])[:, :2]


def _read_parts(blob: object) -> tuple[GeometryKind, tuple[tuple[np.ndarray, ...], ...]]:
    """La geometría y las partes absolutas de un blob GeoPackage (también uno simple o con Z
    escrito por otro programa)."""
    geometry = decode_geometry(bytes(blob), external=True)
    name, coords = geometry.geometry_type, geometry.coords
    kind = _KIND_OF_TYPE[name]
    if name == "POLYGON":
        parts = (tuple(_plan(ring) for ring in coords),)
    elif name == "MULTIPOLYGON":
        parts = tuple(tuple(_plan(ring) for ring in polygon) for polygon in coords)
    elif name == "LINESTRING":
        parts = ((_plan(coords),),)
    elif name == "MULTILINESTRING":
        parts = tuple((_plan(line),) for line in coords)
    else:
        parts = tuple((point[None, :],) for point in _plan(coords))
    return kind, parts


def _blob(kind: GeometryKind, parts: Sequence[Sequence[np.ndarray]],
          srs_id: int) -> bytes | None:
    """El blob ``MULTI*`` de unas partes absolutas, o ``None`` sin ninguna."""
    if not parts:
        return None
    if kind is GeometryKind.POLYGON:
        coords: object = [list(part) for part in parts]
    elif kind is GeometryKind.LINE:
        coords = [part[0] for part in parts]
    else:
        coords = np.vstack([np.asarray(part[0], dtype=np.float64) for part in parts])
    return encode_geometry(_MULTI[kind], coords, srs_id, False)


def _date(value: object) -> date | None:
    """Una fecha guardada (``AAAA-MM-DD``, quizá con hora, escrita por QGIS); ``None`` si
    falta o no es una fecha."""
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _text_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


# --- Restricciones ----------------------------------------------------------------------------


def read_constraints(conn: sqlite3.Connection,
                     layers: Mapping[GeometryKind, str] | None = None, *,
                     uid: str | None = None) -> tuple[Constraint, ...]:
    """Las restricciones de las tres capas, por capa (polígonos, líneas, puntos) y fid; ninguna
    si no existen las tablas. Con ``layers`` (geometría → tabla), solo las de esas tablas (una
    copia congelada con otro nombre, al reproducir); su ``layer`` es el de su geometría. Con
    ``uid``, solo la de ese ``uid`` (ninguna, si no está; la barra N de la restricción
    seleccionada, spec 012, T27). Lo que no rellenó QGIS queda vacío: un tipo fuera de la lista
    (no puede estar: ``CHECK``) o ``NULL`` es ``None``; una fecha que no lo es, ``None``."""
    chosen = CONSTRAINT_LAYERS if layers is None else layers
    present = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    found: list[Constraint] = []
    where, args = ("", ()) if uid is None else (" WHERE uid = ?", (str(uid),))
    for kind, table in chosen.items():
        if table not in present:
            continue
        columns = ", ".join(_CONSTRAINT_COLUMNS)
        for row in conn.execute(f'SELECT fid, geom, {columns} FROM "{table}"{where} ORDER BY fid',
                                args):
            fid, blob, uid, code, name, ctype, priority, reason, decided_by, decided_on, \
                decision_uid, intention_uid, source_input, source_fid = row
            parts = () if blob is None else _read_parts(blob)[1]
            found.append(Constraint(
                uid=str(uid), code=str(code or ""), name=str(name or ""),
                ctype=ConstraintType(ctype) if ctype in ConstraintType else None,
                kind=kind, parts=parts, priority=int(priority or 0), reason=reason,
                decided_by=decided_by, decided_on=_date(decided_on),
                decision_uid=decision_uid, intention_uid=intention_uid,
                source_input=source_input,
                source_fid=None if source_fid is None else int(source_fid),
                layer=CONSTRAINT_LAYERS[kind], fid=int(fid)))
    return tuple(found)


def constraint_names(conn: sqlite3.Connection) -> dict[str, tuple[str, ConstraintType | None]]:
    """Código → (nombre, tipo) de las restricciones de las tres capas con código (sin leer su
    geometría: lo que enseña la ventana de una verificación, spec 012, T28). Un nombre vacío
    queda vacío y un tipo que no es uno de los once, ``None``; ninguna si no existen las
    tablas."""
    present = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    found: dict[str, tuple[str, ConstraintType | None]] = {}
    for table in CONSTRAINT_LAYERS.values():
        if table not in present:
            continue
        for code, name, ctype in conn.execute(
                f"SELECT code, name, ctype FROM \"{table}\" WHERE code <> '' ORDER BY fid"):
            found.setdefault(str(code), (str(name or ""),
                                         ConstraintType(ctype) if ctype in ConstraintType
                                         else None))
    return found


def _codes(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Código → los ``uid`` que lo usan en las tres capas (sin los vacíos)."""
    taken: dict[str, set[str]] = {}
    for table in CONSTRAINT_LAYERS.values():
        for uid, code in conn.execute(f"SELECT uid, code FROM {table} WHERE code <> ''"):
            taken.setdefault(str(code), set()).add(str(uid))
    return taken


def taken_codes(conn: sqlite3.Connection) -> set[str]:
    """Los códigos que ya usan las restricciones de las tres capas (sin los vacíos); ninguno si
    no existen las tablas."""
    present = _existing(conn)
    return {code for table in CONSTRAINT_LAYERS.values() if table in present
            for code in (str(row[0]) for row in conn.execute(
                f"SELECT code FROM {table} WHERE code <> ''"))}


def write_constraints(conn: sqlite3.Connection, rows: Iterable[Constraint], *,
                      srs_id: int) -> tuple[int, ...]:
    """Escribe ``rows`` en su capa (la de su geometría, :func:`layer_of`) y devuelve sus fids:
    una con ``fid`` ≤ 0 se añade; una con ``fid`` > 0 sustituye esa fila (la del mismo
    ``uid``). Su geometría, absoluta en float64, con el CRS ``srs_id``.

    :class:`~.messages.ConstraintError` si un código lo usa ya otra restricción de las tres
    capas (``core.constraint_code_taken``) o si cambia el código que tenía una fila
    (``core.constraint_code_immutable``; D-22); ``ValueError`` si ``layer`` no es la capa de
    su geometría o la fila que sustituye no existe o es de otra restricción."""
    taken = _codes(conn)
    fids: list[int] = []
    for row in rows:
        table = layer_of(row.kind)
        if row.layer != table:
            raise ValueError(f"la restricción «{row.shown_name()}» es {row.kind.value}: su "
                             f"capa es «{table}», no «{row.layer}»")
        if row.code and taken.get(row.code, set()) - {row.uid}:
            raise ConstraintError("core.constraint_code_taken", name=row.shown_name(),
                                  value=row.code)
        values = (row.uid, row.code, row.name, None if row.ctype is None else row.ctype.value,
                  row.priority, row.reason, row.decided_by, _text_date(row.decided_on),
                  row.decision_uid, row.intention_uid, row.source_input, row.source_fid)
        blob = _blob(row.kind, row.parts, srs_id)
        if row.fid > 0:
            stored = conn.execute(f"SELECT uid, code FROM {table} WHERE fid = ?",
                                  (row.fid,)).fetchone()
            if stored is None or stored[0] != row.uid:
                raise ValueError(f"la fila {row.fid} de «{table}» no es la restricción "
                                 f"{row.uid}: no se sustituye")
            if stored[1] and stored[1] != row.code:
                raise ConstraintError("core.constraint_code_immutable", name=row.shown_name(),
                                      old=stored[1], value=row.code)
            assignments = ", ".join(f"{column} = ?" for column in ("geom",
                                                                   *_CONSTRAINT_COLUMNS[1:]))
            conn.execute(f"UPDATE {table} SET {assignments} WHERE fid = ?",
                         (blob, *values[1:], row.fid))
            fid = row.fid
        else:
            marks = ", ".join("?" for _ in range(len(values) + 1))
            cursor = conn.execute(
                f"INSERT INTO {table} (geom, {', '.join(_CONSTRAINT_COLUMNS)}) "
                f"VALUES ({marks})", (blob, *values))
            fid = int(cursor.lastrowid or 0)
        if row.code:
            taken.setdefault(row.code, set()).add(row.uid)
        fids.append(fid)
    return tuple(fids)


# --- Intenciones ------------------------------------------------------------------------------


def read_intentions(conn: sqlite3.Connection) -> tuple[Intention, ...]:
    """Las intenciones del cliente, por fid (ninguna sin la tabla); su geometría dice si son
    puntos, líneas o polígonos."""
    if INTENTION_TABLE not in _existing(conn):
        return ()
    found = []
    for row in conn.execute(
            f"SELECT fid, geom, uid, name, role, elevation_m, stated_on, document_input, "
            f"decision_uid, source_input, source_fid FROM {INTENTION_TABLE} ORDER BY fid"):
        fid, blob, uid, name, role, elevation, stated_on, document, decision, source, \
            source_fid = row
        kind, parts = _read_parts(blob)
        found.append(Intention(
            uid=str(uid), name=str(name), role=role, kind=kind, parts=parts,
            elevation_m=None if elevation is None else float(elevation),
            stated_on=date.fromisoformat(str(stated_on)[:10]), document_input=str(document),
            decision_uid=decision, source_input=str(source), source_fid=int(source_fid),
            fid=int(fid)))
    return tuple(found)


def write_intentions(conn: sqlite3.Connection, rows: Iterable[Intention], *,
                     srs_id: int) -> tuple[int, ...]:
    """Añade las intenciones ``rows`` (su ``fid`` no cuenta) y devuelve sus fids; una
    intención no se cambia ni se borra (RF-012-27)."""
    fids = []
    for row in rows:
        cursor = conn.execute(
            f"INSERT INTO {INTENTION_TABLE} (geom, uid, name, role, elevation_m, stated_on, "
            "document_input, decision_uid, source_input, source_fid) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_blob(row.kind, row.parts, srs_id), row.uid, row.name, row.role.value,
             row.elevation_m, row.stated_on.isoformat(), row.document_input, row.decision_uid,
             row.source_input, row.source_fid))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


@dataclass(frozen=True, slots=True)
class ListedIntention:
    """Una intención para enseñarla en una lista (T25; RF-012-26, RF-012-27): la intención,
    el nombre de la entrada de su documento (``document``) y de la de su capa de origen
    (``source``; vacíos si la entrada ya no está), su decisión enlazada como se lee
    («15/09/2025 · quién: qué»; vacía si no la tiene) y los códigos de las restricciones que
    salieron de ella (``converted``, por su capa y su fid)."""

    intention: Intention
    document: str
    source: str
    decision: str
    converted: tuple[str, ...]


def _input_names(conn: sqlite3.Connection, tables: set[str]) -> dict[str, str]:
    if "gb_input" not in tables:
        return {}
    return {str(uid): str(name) for uid, name in conn.execute("SELECT uid, name FROM gb_input")}


def _decision_texts(conn: sqlite3.Connection, tables: set[str]) -> dict[str, str]:
    if "gb_decision" not in tables:
        return {}
    found: dict[str, str] = {}
    for uid, who, day, what in conn.execute(
            "SELECT uid, decided_by, decided_at, what FROM gb_decision"):
        year, month, number = str(day)[:10].split("-")
        found[str(uid)] = f"{number}/{month}/{year} · {who}: {' '.join(str(what).split())}"
    return found


def listed_intentions(conn: sqlite3.Connection) -> tuple[ListedIntention, ...]:
    """Las intenciones del cliente (:func:`read_intentions`) con el nombre de su documento y de
    su capa, su decisión y las restricciones que salieron de ellas (:class:`ListedIntention`);
    ninguna sin la tabla. Solo lee."""
    intentions = read_intentions(conn)
    if not intentions:
        return ()
    tables = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    names = _input_names(conn, tables)
    decisions = _decision_texts(conn, tables)
    made: dict[str, list[str]] = {}
    for row in read_constraints(conn):
        if row.intention_uid:
            made.setdefault(row.intention_uid, []).append(row.code)
    return tuple(ListedIntention(
        item, names.get(item.document_input, ""), names.get(item.source_input, ""),
        "" if item.decision_uid is None else decisions.get(item.decision_uid, ""),
        tuple(made.get(item.uid, ()))) for item in intentions)


# --- Sectores ---------------------------------------------------------------------------------


def _inside(point: np.ndarray, ring: np.ndarray) -> bool:
    """Si ``point`` está dentro del anillo cerrado ``ring`` (par-impar, en coordenadas
    relativas al punto)."""
    local = ring - point
    a, b = local[:-1], local[1:]
    crosses = (a[:, 1] > 0.0) != (b[:, 1] > 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        x = a[:, 0] + (0.0 - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
    return bool(np.count_nonzero(crosses & (x > 0.0)) % 2)


def _area(ring: np.ndarray) -> float:
    local = ring - ring[0]
    return abs(float(np.sum(local[:-1, 0] * local[1:, 1] - local[1:, 0] * local[:-1, 1])) / 2.0)


def _polygons(rings: Sequence[np.ndarray]) -> list[list[np.ndarray]]:
    """Los anillos de un sector agrupados en polígonos para un ``MULTIPOLYGON``: un anillo
    dentro de un número par de los demás es un exterior; uno dentro de un número impar, un
    hueco del exterior más pequeño que lo contiene. Los exteriores, en su orden; los huecos,
    tras el suyo."""
    rings = [np.asarray(ring, dtype=np.float64) for ring in rings]
    within = [[j for j, other in enumerate(rings) if j != i and _inside(ring[0], other)]
              for i, ring in enumerate(rings)]
    depth = [len(found) for found in within]
    polygons: dict[int, list[np.ndarray]] = {}
    for i, ring in enumerate(rings):
        if depth[i] % 2 == 0:
            polygons[i] = [ring]
    for i, ring in enumerate(rings):
        if depth[i] % 2 == 1:
            owners = [j for j in within[i] if depth[j] == depth[i] - 1] or within[i]
            owner = min(owners, key=lambda j: _area(rings[j]))
            polygons.setdefault(owner, [rings[owner]]).append(ring)
    return [polygons[i] for i in sorted(polygons)]


def sector_sha256(sector: Sector) -> str:
    """La huella de la geometría de un sector (D-26): el sha256 de su WKB ``MULTIPOLYGON``
    tal como se guarda (sin la cabecera GeoPackage, que lleva el SRS)."""
    blob = encode_geometry("MULTIPOLYGON", _polygons(sector.rings), 0, False)
    return sha256_bytes(geometry_wkb(blob))


def read_sectors(conn: sqlite3.Connection) -> tuple[Sector, ...]:
    """Los sectores de búsqueda, por fid (ninguno sin la tabla); sus anillos, polígono a
    polígono (el exterior y sus huecos)."""
    if SECTOR_TABLE not in _existing(conn):
        return ()
    found = []
    for uid, code, name, blob in conn.execute(
            f"SELECT uid, code, name, geom FROM {SECTOR_TABLE} ORDER BY fid"):
        _kind, parts = _read_parts(blob)
        found.append(Sector(str(uid), str(code), str(name),
                            tuple(ring for part in parts for ring in part)))
    return tuple(found)


def write_sectors(conn: sqlite3.Connection, sectors: Iterable[Sector], *,
                  srs_id: int) -> tuple[int, ...]:
    """Añade los sectores ``sectors`` con su huella (:func:`sector_sha256`) y devuelve sus
    fids. Un código repetido lo rechaza la tabla (``sqlite3.IntegrityError``)."""
    fids = []
    for sector in sectors:
        blob = encode_geometry("MULTIPOLYGON", _polygons(sector.rings), srs_id, False)
        cursor = conn.execute(
            f"INSERT INTO {SECTOR_TABLE} (geom, uid, code, name, geom_sha256) "
            "VALUES (?, ?, ?, ?, ?)",
            (blob, sector.uid, sector.code, sector.name, sha256_bytes(geometry_wkb(blob))))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def replace_sectors(conn: sqlite3.Connection, sectors: Iterable[Sector], *,
                    srs_id: int) -> tuple[int, ...]:
    """Sustituye los sectores guardados por ``sectors`` (declararlos de nuevo, RF-012-07): borra
    los anteriores y añade estos con :func:`write_sectors`; sin ninguno, el perímetro de
    actuación queda como único sector (D-26). Las búsquedas cerradas se quedan: la de un
    sector con el mismo código y la misma huella sigue vigente (A12)."""
    conn.execute(f"DELETE FROM {SECTOR_TABLE}")
    return write_sectors(conn, sectors, srs_id=srs_id)


@dataclass(frozen=True, slots=True)
class SectorState:
    """El estado de un sector de búsqueda (RF-012-09, RF-012-10; A12): su código (``""``: el
    perímetro como único sector), su nombre, la huella de su geometría y su búsqueda vigente
    (la última cerrada con esa huella), o ``None`` si está **pendiente**."""

    code: str
    name: str
    sha256: str
    search: SearchRecord | None

    @property
    def current(self) -> bool:
        """Si tiene una búsqueda vigente."""
        return self.search is not None


def sector_states(sectors: Sequence[Sector], searches: Sequence[SearchRecord]
                  ) -> tuple[SectorState, ...]:
    """El estado de cada sector de ``sectors``, en su orden, con las búsquedas ``searches`` que
    no están obsoletas (las de una operación obsoleta las quita antes quien llama: A12): la
    vigente es la última de su código con la huella actual del sector (:func:`sector_sha256`)."""
    last: dict[tuple[str, str], SearchRecord] = {}
    for record in searches:
        last[(record.sector_code, record.sector_sha256)] = record
    states = []
    for sector in sectors:
        sha = sector_sha256(sector)
        states.append(SectorState(sector.code, sector.name, sha, last.get((sector.code, sha))))
    return tuple(states)


# --- Búsquedas --------------------------------------------------------------------------------


def append_search(conn: sqlite3.Connection, record: SearchRecord,
                  hits: Iterable[SearchHit]) -> None:
    """Añade una búsqueda cerrada y sus entidades halladas (RF-012-09), con los atributos de
    cada una en JSON canónico; solo se añaden filas."""
    conn.execute(
        f"INSERT INTO {SEARCH_TABLE} (uid, operation_uid, sector_code, sector_sha256, "
        "distance_m, closed_by, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (record.uid, record.operation_uid, record.sector_code, record.sector_sha256,
         float(record.distance_m), record.closed_by, record.closed_at))
    conn.executemany(
        f"INSERT INTO {HIT_TABLE} (search_uid, layer_dataset, feature_fid, distance_m, "
        "attributes, decision, reason, constraint_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(record.uid if hit.search_uid is None else hit.search_uid, hit.layer_dataset,
          int(hit.feature_fid), float(hit.distance_m),
          canonical_json(dict(hit.attributes)).decode("utf-8"), hit.decision.value,
          hit.reason, hit.constraint_code) for hit in hits])


def read_searches(conn: sqlite3.Connection) -> tuple[SearchRecord, ...]:
    """Las búsquedas cerradas, en el orden en que se cerraron (ninguna sin la tabla)."""
    if SEARCH_TABLE not in _existing(conn):
        return ()
    return tuple(
        SearchRecord(str(uid), str(operation), str(code), str(sha), float(distance),
                     str(closed_by), str(closed_at))
        for uid, operation, code, sha, distance, closed_by, closed_at in conn.execute(
            f"SELECT uid, operation_uid, sector_code, sector_sha256, distance_m, closed_by, "
            f"closed_at FROM {SEARCH_TABLE} ORDER BY fid"))


def read_hits(conn: sqlite3.Connection, search_uid: str | None = None
              ) -> tuple[SearchHit, ...]:
    """Las entidades halladas (las de la búsqueda ``search_uid``, o todas), en su orden."""
    if HIT_TABLE not in _existing(conn):
        return ()
    where, params = ("", ()) if search_uid is None else (" WHERE search_uid = ?", (search_uid,))
    rows: list[Any] = conn.execute(
        f"SELECT search_uid, layer_dataset, feature_fid, distance_m, attributes, decision, "
        f"reason, constraint_code FROM {HIT_TABLE}{where} ORDER BY fid", params).fetchall()
    return tuple(
        SearchHit(str(search), str(layer), int(fid), float(distance), json.loads(attributes),
                  decision, str(reason), code)
        for search, layer, fid, distance, attributes, decision, reason, code in rows)
