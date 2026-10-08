# SPDX-License-Identifier: GPL-3.0-or-later
"""Puntos topográficos y líneas de rotura (spec 006; plan 006 §5.1 y §5.3.2; RF-006-12).

Un levantamiento llega como **filas de texto** (CSV, TXT o XYZ disperso, que lee
``interop.csv_tables.read_table`` de la 005 en el trabajo o el operador: ``gis`` no importa
``interop``) o como **capa de un GeoPackage** (``gis.vector.read_layer``). Aquí se convierte
en puntos (:class:`PointSet`) y líneas de rotura (:class:`Breakline`) con las coordenadas
ABSOLUTAS de la fuente en float64, sin alterarlas: cada una es el float64 más próximo a su
texto, o la de la capa bit a bit.

- :func:`points_from_rows`: las columnas de cada papel (:class:`ColumnMapping`: P, X, Y, Z,
  código y línea) y el decimal declarado («.» o «,»). Las filas con línea forman las líneas,
  en el orden del fichero aunque no estén seguidas; las demás son puntos. Se rechaza, con
  su número (la línea del fichero que da ``read_table``) y su motivo, la fila con columnas
  de menos (o de más con algo escrito), con X, Y o Z vacía o que no es un número en el
  decimal declarado (ni miles, ni ``nan``, ni ``inf``), la línea de un solo punto y la línea
  entera si una de sus filas no vale: una línea de rotura sin cota no se acepta.
- :func:`points_from_features` y :func:`breaklines_from_features`: el papel que el usuario
  declara para una capa; una geometría sin Z no se acepta como punto ni como rotura, y una
  de otro tipo se rechaza con su número de entidad.

Duplicados (RF-006-14; plan A7):

- :func:`find_duplicates`: los puntos que coinciden en planta a ≤ ``tol_xy``
  (``gis.points.dup_xy_tol_m``, 1 mm) forman grupos (las componentes de «a ≤ ``tol_xy``»,
  buscadas en cubetas de lado ``tol_xy`` y sus 8 vecinas); un grupo cuyas cotas difieren
  ≤ ``tol_z`` (``gis.points.dup_z_tol_m``, 0,01 m) se funde y se cuenta; si difieren más,
  es un conflicto (:class:`~gis.reports.Conflict`) con los dos identificadores, la posición
  del primero y las dos cotas. El informe (:class:`DuplicateReport`) da el número de
  duplicados para ``TopoReport.duplicates``.
- :func:`resolve_duplicates`: los puntos sin duplicados según la política que elija el
  usuario para los conflictos (:class:`DuplicatePolicy`: media, mínima, máxima, primero o
  cancelar; «preguntar», por defecto, lanza :class:`~gis.reports.ConflictError` con la lista
  para que elija).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import numpy as np

from . import params
from .messages import render
from .reports import Conflict, ConflictError, ConflictKind, Rejection, TopoReport
from .validate import _roots

if TYPE_CHECKING:
    from .vector import FeatureSet

DECIMALS = {".": "punto", ",": "coma"}
"""Decimales que se admiten, con su nombre."""

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)
_SHOWN = 40  # caracteres de un valor que se muestran en un mensaje
_ROLES = ("x", "y", "z", "point_id", "code", "line")
_REQUIRED = ("x", "y", "z")
_POINT_TYPES = ("POINT", "MULTIPOINT")
_LINE_TYPES = ("LINESTRING", "MULTILINESTRING")
DUP_XY_KEY = "gis.points.dup_xy_tol_m"
DUP_Z_KEY = "gis.points.dup_z_tol_m"
_MAX_CELLS = 2**26  # cubetas por eje como mucho: claves enteras exactas (< 2⁵³)
_HALF_NEIGHBOURS = ((0, 0), (0, 1), (1, -1), (1, 0), (1, 1))  # cada pareja de cubetas, una vez


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """La columna (índice desde 0) de cada papel: X, Y y Z obligatorias; P (identificador
    del punto), código y línea, opcionales. Dos papeles nunca comparten columna."""

    x: int
    y: int
    z: int
    point_id: int | None = None
    code: int | None = None
    line: int | None = None

    def __post_init__(self) -> None:
        used: list[int] = []
        for role in _ROLES:
            index = getattr(self, role)
            if index is None and role not in _REQUIRED:
                continue
            if isinstance(index, bool) or not isinstance(index, int):
                raise TypeError(f"la columna de «{role}» es un índice entero: {index!r}")
            if index < 0:
                raise ValueError(f"la columna de «{role}» no puede ser negativa: {index}")
            used.append(index)
        if len(set(used)) != len(used):
            raise ValueError(f"dos papeles en la misma columna: {used}")

    @classmethod
    def by_name(
        cls,
        columns: Sequence[str],
        *,
        x: str,
        y: str,
        z: str,
        point_id: str | None = None,
        code: str | None = None,
        line: str | None = None,
    ) -> ColumnMapping:
        """La correspondencia por el nombre de cada columna en la cabecera ``columns``;
        ``ValueError`` si un nombre no está (el asistente solo ofrece los que están)."""
        names = list(columns)

        def index(name: str) -> int:
            if name not in names:
                raise ValueError(f"la columna «{name}» no está en la cabecera: {names}")
            return names.index(name)

        def optional(name: str | None) -> int | None:
            return None if name is None else index(name)

        return cls(index(x), index(y), index(z), optional(point_id), optional(code),
                   optional(line))

    @property
    def needed(self) -> int:
        """Las columnas que tiene que tener una fila para llegar a todas las usadas."""
        return 1 + max(i for i in (getattr(self, r) for r in _ROLES) if i is not None)


@dataclass(frozen=True, slots=True, eq=False)
class PointSet:
    """Puntos topográficos: ``xyz`` float64 ``(n, 3)`` ABSOLUTOS en el CRS y el datum de
    la fuente; por punto, su identificador (P, o el número de entidad de una capa; ``""``
    si no hay), su código y su fila (o entidad) de origen."""

    xyz: np.ndarray
    point_ids: tuple[str, ...]
    codes: tuple[str, ...]
    source_rows: tuple[int, ...]

    def __post_init__(self) -> None:
        _check_xyz(self.xyz, "PointSet.xyz")
        count = len(self.xyz)
        for name in ("point_ids", "codes", "source_rows"):
            if len(getattr(self, name)) != count:
                raise ValueError(f"PointSet.{name} no tiene {count} elementos")

    def __len__(self) -> int:
        return len(self.xyz)


@dataclass(frozen=True, slots=True, eq=False)
class Breakline:
    """Una línea de rotura: su identificador, sus vértices ``xyz`` float64 ``(k ≥ 2, 3)``
    ABSOLUTOS, dura (arista obligatoria del TIN) o blanda (solo aporta puntos), su código y
    la fila (o entidad) de origen de cada vértice."""

    line_id: str
    xyz: np.ndarray
    hard: bool = True
    code: str = ""
    source_rows: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _check_xyz(self.xyz, "Breakline.xyz")
        if len(self.xyz) < 2:
            raise ValueError(f"la línea «{self.line_id}» necesita al menos dos vértices")
        if self.source_rows and len(self.source_rows) != len(self.xyz):
            raise ValueError(f"Breakline.source_rows no tiene {len(self.xyz)} elementos")


def _check_xyz(xyz: object, what: str) -> None:
    if not isinstance(xyz, np.ndarray) or xyz.dtype != np.float64:
        raise TypeError(f"{what}: las coordenadas absolutas van en un ndarray float64")
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"{what}: forma {xyz.shape}, se espera (n, 3)")


def _number(text: str, decimal: str) -> tuple[float | None, str | None]:
    """El float64 más próximo a ``text`` y ``None``, o ``None`` y el problema
    (``"empty"`` o ``"invalid"``)."""
    value = text.strip()
    if not value:
        return None, "empty"
    if decimal == ",":
        if "." in value:
            return None, "invalid"
        value = value.replace(",", ".")
    if _NUMBER.fullmatch(value) is None:
        return None, "invalid"
    number = float(value)
    if not math.isfinite(number):
        return None, "invalid"
    return number, None


def _short(text: str) -> str:
    value = text.strip()
    return value if len(value) <= _SHOWN else value[: _SHOWN - 1] + "…"


def _field(fields: Sequence[str], index: int | None) -> str:
    """El texto de la columna ``index`` (sin blancos alrededor), o ``""``."""
    if index is None or index >= len(fields):
        return ""
    return fields[index].strip()


def points_from_rows(
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    mapping: ColumnMapping,
    decimal: str,
    *,
    source: str = "",
    row_numbers: Sequence[int] | None = None,
    hard: bool = True,
) -> tuple[PointSet, list[Breakline], TopoReport]:
    """Puntos y líneas de rotura de las filas de una tabla de texto (RF-006-12).

    ``columns``: la cabecera (vacía si no la hay); ``rows``: los textos de cada fila, tal
    como están; ``mapping``: la columna de cada papel; ``decimal``: «.» o «,»; ``source``:
    el nombre del fichero, para los mensajes; ``row_numbers``: el número que ve el usuario
    de cada fila (``Table.lines``; por defecto, 1, 2…); ``hard``: líneas duras o blandas.
    Las filas no se modifican. ``ValueError`` o ``TypeError`` si las opciones no son
    válidas (un error del programa: el asistente solo ofrece las válidas).
    """
    if decimal not in DECIMALS:
        raise ValueError(f"decimal «{decimal}» no admitido: {', '.join(DECIMALS)}")
    if not isinstance(mapping, ColumnMapping):
        raise TypeError("mapping es un ColumnMapping")
    headers = [str(name) for name in columns]
    if headers and mapping.needed > len(headers):
        raise ValueError(f"la correspondencia usa la columna {mapping.needed} y la "
                         f"cabecera tiene {len(headers)}")
    numbers = list(range(1, len(rows) + 1)) if row_numbers is None else list(row_numbers)
    if len(numbers) != len(rows):
        raise ValueError(f"row_numbers tiene {len(numbers)} números para {len(rows)} filas")
    expected = len(headers) if headers else mapping.needed
    axes = (("X", mapping.x), ("Y", mapping.y), ("Z", mapping.z))
    rejected: list[Rejection] = []
    found: list[tuple[int, list[float], str, str]] = []
    lines: dict[str, list[tuple[int, list[float], str]]] = {}
    bad_lines: dict[str, int] = {}

    def reject(row: int, code: str, line_id: str = "", **values: object) -> None:
        rejected.append(Rejection(row, render(code, file=source, row=row, **values), code))
        if line_id:
            bad_lines.setdefault(line_id, row)

    for number, fields in zip(numbers, rows, strict=True):
        line_id = _field(fields, mapping.line)
        count = len(fields)
        extra = count > expected and any(f.strip() for f in fields[expected:])
        if count < expected or (headers and extra):
            reject(number, "gis.row_columns", line_id, value=count, expected=expected)
            continue
        xyz: list[float] = []
        for axis, index in axes:
            value, problem = _number(fields[index], decimal)
            if value is not None:
                xyz.append(value)
                continue
            header = headers[index] if headers else f"columna {index + 1}"
            if problem == "empty" and axis == "Z" and line_id:
                reject(number, "gis.breakline_no_elevation", line_id, line=line_id)
            elif problem == "empty":
                reject(number, "gis.value_empty", line_id, column=axis, header=header)
            else:
                reject(number, "gis.value_not_number", line_id, column=axis, header=header,
                       value=_short(fields[index]))
            break
        else:
            code = _field(fields, mapping.code)
            if line_id:
                lines.setdefault(line_id, []).append((number, xyz, code))
            else:
                found.append((number, xyz, _field(fields, mapping.point_id), code))
    breaklines: list[Breakline] = []
    for line_id, vertices in lines.items():
        bad = bad_lines.get(line_id)
        if bad is not None:
            for number, _xyz, _code in vertices:
                reject(number, "gis.line_rejected", line=line_id, bad_row=bad)
        elif len(vertices) < 2:
            reject(vertices[0][0], "gis.line_single_point", line=line_id)
        else:
            breaklines.append(Breakline(
                line_id=line_id,
                xyz=np.array([v[1] for v in vertices], dtype=np.float64),
                hard=bool(hard),
                code=vertices[0][2],
                source_rows=tuple(v[0] for v in vertices),
            ))
    point_set = PointSet(
        xyz=np.array([p[1] for p in found], dtype=np.float64).reshape(-1, 3),
        point_ids=tuple(p[2] for p in found),
        codes=tuple(p[3] for p in found),
        source_rows=tuple(p[0] for p in found),
    )
    report = TopoReport(
        source=source,
        read=len(rows),
        points=len(point_set),
        lines=len(breaklines),
        rejected=tuple(sorted(rejected, key=lambda r: r.row)),
    )
    return point_set, breaklines, report


def _attribute(features: FeatureSet, name: str | None) -> tuple[Any, ...] | None:
    if name is None:
        return None
    if name not in features.attributes:
        raise ValueError(f"la capa «{features.layer.name}» no tiene el campo «{name}»: "
                         f"{list(features.attributes)}")
    return features.attributes[name]


def _text(values: tuple[Any, ...] | None, index: int, default: str) -> str:
    if values is None:
        return default
    value = values[index]
    return "" if value is None else str(value).strip()


def _role_check(features: FeatureSet, index: int, types: tuple[str, ...], plural: str,
                singular: str) -> Rejection | None:
    """El rechazo de la entidad ``index`` si no es de ``types`` o no tiene Z."""
    geometry = features.geometries[index]
    fid = features.fids[index]
    layer = features.layer.name
    if geometry.geometry_type not in types:
        code = "gis.feature_role_mismatch"
        text = render(code, layer=layer, row=fid, value=geometry.geometry_type, role=plural,
                      expected=" y ".join(types))
        return Rejection(fid, text, code)
    if not geometry.has_z:
        code = "gis.feature_without_z"
        return Rejection(fid, render(code, layer=layer, row=fid, role=singular), code)
    return None


def _report(features: FeatureSet, rejected: list[Rejection], **counts: int) -> TopoReport:
    every = [*features.report.rejected, *rejected]
    return replace(features.report, rejected=tuple(sorted(every, key=lambda r: r.row)),
                   **counts)


def points_from_features(
    features: FeatureSet, *, id_field: str | None = None, code_field: str | None = None
) -> tuple[PointSet, TopoReport]:
    """Los puntos de una capa con el papel «puntos» (RF-006-12): cada Point o cada parte de
    un MultiPoint, con Z; su identificador, el campo ``id_field`` (por defecto, el número
    de entidad) y su código, ``code_field``. Una entidad de otro tipo o sin Z se rechaza
    con su número; el informe conserva los rechazos y avisos de la lectura."""
    ids = _attribute(features, id_field)
    codes = _attribute(features, code_field)
    rejected: list[Rejection] = []
    blocks: list[np.ndarray] = []
    point_ids: list[str] = []
    point_codes: list[str] = []
    rows: list[int] = []
    for index, fid in enumerate(features.fids):
        problem = _role_check(features, index, _POINT_TYPES, "puntos", "punto")
        if problem is not None:
            rejected.append(problem)
            continue
        xyz = features.geometries[index].coords.reshape(-1, 3)
        blocks.append(xyz)
        point_ids += [_text(ids, index, str(fid))] * len(xyz)
        point_codes += [_text(codes, index, "")] * len(xyz)
        rows += [fid] * len(xyz)
    xyz = np.concatenate(blocks) if blocks else np.empty((0, 3), dtype=np.float64)
    point_set = PointSet(xyz, tuple(point_ids), tuple(point_codes), tuple(rows))
    return point_set, _report(features, rejected, points=len(point_set), lines=0)


def breaklines_from_features(
    features: FeatureSet,
    *,
    hard: bool = True,
    id_field: str | None = None,
    code_field: str | None = None,
) -> tuple[list[Breakline], TopoReport]:
    """Las líneas de rotura de una capa con ese papel (RF-006-12): cada LineString o cada
    parte de un MultiLineString (``<id>.1``, ``<id>.2``…), con Z, duras o blandas; su
    identificador, el campo ``id_field`` (por defecto, el número de entidad) y su código,
    ``code_field``. Una entidad de otro tipo, sin Z (una rotura sin cota no se acepta) o
    con una parte de un solo vértice se rechaza con su número."""
    ids = _attribute(features, id_field)
    codes = _attribute(features, code_field)
    rejected: list[Rejection] = []
    breaklines: list[Breakline] = []
    for index, fid in enumerate(features.fids):
        problem = _role_check(features, index, _LINE_TYPES, "líneas de rotura",
                              "línea de rotura")
        if problem is not None:
            rejected.append(problem)
            continue
        geometry = features.geometries[index]
        parts = [geometry.coords] if geometry.geometry_type == "LINESTRING" else list(
            geometry.coords
        )
        if any(len(part) < 2 for part in parts):
            code = "gis.feature_geometry_invalid"
            text = render(code, layer=features.layer.name, file=features.layer.file, row=fid,
                          detail="una línea tiene un solo vértice")
            rejected.append(Rejection(fid, text, code))
            continue
        line_id = _text(ids, index, str(fid))
        code = _text(codes, index, "")
        for number, part in enumerate(parts, start=1):
            breaklines.append(Breakline(
                line_id=line_id if len(parts) == 1 else f"{line_id}.{number}",
                xyz=part,
                hard=bool(hard),
                code=code,
                source_rows=(fid,) * len(part),
            ))
    return breaklines, _report(features, rejected, points=0, lines=len(breaklines))


# Duplicados (RF-006-14; plan A7) ----------------------------------------------------------


class DuplicatePolicy(StrEnum):
    """Cómo resolver los puntos en conflicto: a ≤ ``tol_xy`` en planta con cotas que
    difieren más de ``tol_z`` (RF-006-14). Por defecto, preguntar (D-5)."""

    ASK = "ask"
    """Preguntar: si hay conflictos, :class:`~gis.reports.ConflictError` con la lista."""
    MEAN = "mean"
    """La cota media del grupo, en la posición del primero."""
    MIN = "min"
    """El punto de cota mínima, tal cual."""
    MAX = "max"
    """El punto de cota máxima, tal cual."""
    FIRST = "first"
    """El primero, tal cual."""
    CANCEL = "cancel"
    """Cancelar: si hay conflictos, el TIN no se crea."""


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """Puntos que coinciden en planta: sus posiciones en la entrada, en orden (el primero
    es el que se conserva) y si sus cotas difieren más de ``tol_z`` (``conflict``)."""

    indices: tuple[int, ...]
    conflict: bool

    @property
    def kept(self) -> int:
        """La posición del primero: el que se conserva sin conflicto o con «primero»."""
        return self.indices[0]


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    """Los duplicados de ``count`` puntos con las tolerancias ``tol_xy`` y ``tol_z`` (m):
    los grupos de dos o más, por su primer punto, y los conflictos (los de los grupos con
    ``conflict``)."""

    count: int
    tol_xy: float
    tol_z: float
    groups: tuple[DuplicateGroup, ...] = ()
    conflicts: tuple[Conflict, ...] = ()

    @property
    def merged(self) -> int:
        """Puntos que se funden con el primero de su grupo (cotas dentro de ``tol_z``)."""
        return sum(len(g.indices) - 1 for g in self.groups if not g.conflict)

    @property
    def duplicates(self) -> int:
        """Puntos que coinciden en planta con otro anterior, fundidos o en conflicto: el
        ``TopoReport.duplicates`` de la importación (RF-006-12)."""
        return sum(len(g.indices) - 1 for g in self.groups)


def duplicate_tolerances(tol_xy: float | None = None,
                         tol_z: float | None = None) -> tuple[float, float]:
    """Las tolerancias en planta y en cota (m): las de ``gis/params.py`` si son ``None``;
    si no, comprobadas como esos parámetros (``GisError`` ``gis.param_*`` con la clave
    como campo)."""
    def value(key: str, given: float | None) -> float:
        definition = params.param(key)
        return float(definition.default if given is None else definition.check(given))

    return value(DUP_XY_KEY, tol_xy), value(DUP_Z_KEY, tol_z)


def _expand(start: np.ndarray, stop: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada ``k`` y cada posición de ``start[k]`` a ``stop[k]`` (sin incluir), el
    par (``k``, posición), vectorizado."""
    counts = stop - start
    owner = np.repeat(np.arange(len(start), dtype=np.int64), counts)
    offsets = np.repeat(np.cumsum(counts) - counts - start, counts)
    return owner, np.arange(len(owner), dtype=np.int64) - offsets


def _close_pairs(xy: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray]:
    """Las parejas (``i`` < ``j``) de ``xy`` (float64 ``(n, 2)``, ABSOLUTAS) a ≤ ``tol`` en
    planta. Cubetas de lado ``tol`` (o mayor, si la extensión pide más de
    :data:`_MAX_CELLS` por eje) ordenadas por clave; cada punto mira su cubeta y la mitad de
    sus 8 vecinas, así que cada pareja de cubetas se mira una vez. La distancia se mide con
    las diferencias de las coordenadas absolutas, exactas entre puntos cercanos."""
    empty = np.empty(0, dtype=np.int64)
    if len(xy) < 2:
        return empty, empty
    local = xy - xy.min(axis=0)
    size = max(tol, float(local.max()) / _MAX_CELLS)
    cells = np.floor(local / size).astype(np.int64)
    stride = int(cells[:, 1].max()) + 2  # cy + 1 y cy − 1 nunca pisan otra columna
    keys = cells[:, 0] * stride + cells[:, 1]
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    firsts, seconds = [], []
    for dx, dy in _HALF_NEIGHBOURS:
        wanted = sorted_keys + (dx * stride + dy)  # ya ordenadas: búsqueda mucho más rápida
        start = np.searchsorted(sorted_keys, wanted, side="left")
        stop = np.searchsorted(sorted_keys, wanted, side="right")
        owner, position = _expand(start, stop)
        if dx == 0 and dy == 0:
            later = position > owner
            owner, position = owner[later], position[later]
        first, second = order[owner], order[position]
        delta = xy[first] - xy[second]
        near = np.hypot(delta[:, 0], delta[:, 1]) <= tol
        firsts.append(first[near])
        seconds.append(second[near])
    first = np.concatenate(firsts)
    second = np.concatenate(seconds)
    return np.minimum(first, second), np.maximum(first, second)


def _cluster(
    xy: np.ndarray, z: np.ndarray, tol_xy: float, tol_z: float,
    priority: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Grupos de puntos a ≤ ``tol_xy`` en planta (componentes conexas, plan A7).

    Devuelve ``kept``: para cada punto, el que se conserva de su grupo (él mismo si está
    solo), el de menor ``priority`` (una permutación de las posiciones; por defecto, la
    posición); ``conflict``: si las cotas de su grupo difieren más de ``tol_z``; y
    ``pairs`` ``(m, 2)``: las parejas (``i`` < ``j``) que se listan como conflictos, en
    orden: las vecinas (a ≤ ``tol_xy``) con Δz > ``tol_z`` y, en un grupo en conflicto sin
    ninguna (una cadena), la de su cota mínima y su cota máxima.
    """
    count = len(xy)
    rank = np.arange(count, dtype=np.int64) if priority is None else priority
    by_rank = np.empty(count, dtype=np.int64)
    by_rank[rank] = np.arange(count, dtype=np.int64)
    first, second = _close_pairs(xy, tol_xy)
    roots = _roots(count, rank[first], rank[second])
    kept = by_rank[roots[rank]]
    low = z.copy()
    high = z.copy()
    np.minimum.at(low, kept, z)
    np.maximum.at(high, kept, z)
    in_conflict = (high - low > tol_z)[kept]
    steep = np.abs(z[first] - z[second]) > tol_z
    pairs = [np.column_stack([first[steep], second[steep]])]
    covered = np.zeros(count, dtype=bool)
    covered[kept[first[steep]]] = True
    for group in np.flatnonzero(in_conflict & (kept == np.arange(count)) & ~covered):
        members = np.flatnonzero(kept == group)
        lowest = int(members[np.argmin(z[members])])
        highest = int(members[np.argmax(z[members])])
        pairs.append(np.array([[min(lowest, highest), max(lowest, highest)]]))
    listed = np.concatenate(pairs).reshape(-1, 2).astype(np.int64)
    listed = listed[np.lexsort((listed[:, 1], listed[:, 0]))]
    return kept, in_conflict, listed


def _check_points(xyz: object, what: str) -> None:
    _check_xyz(xyz, what)
    if not np.isfinite(xyz).all():  # type: ignore[call-overload]
        raise ValueError(f"{what}: hay coordenadas que no son finitas")


def find_duplicates(
    xyz: np.ndarray,
    *,
    tol_xy: float | None = None,
    tol_z: float | None = None,
    ids: Sequence[str] | None = None,
) -> DuplicateReport:
    """Los puntos de ``xyz`` (float64 ``(n, 3)``, ABSOLUTOS) que coinciden en planta a
    ≤ ``tol_xy`` (RF-006-14; plan A7): grupos por su primer punto y conflictos (cotas que
    difieren más de ``tol_z``) con los identificadores ``ids`` (por defecto, «#1», «#2»…
    por su posición), la posición X, Y del primero de la pareja y sus dos cotas. Las
    tolerancias, las de :func:`duplicate_tolerances`. No modifica ``xyz``."""
    _check_points(xyz, "xyz")
    tol_xy, tol_z = duplicate_tolerances(tol_xy, tol_z)
    count = len(xyz)
    labels = tuple(f"#{i + 1}" for i in range(count)) if ids is None else tuple(ids)
    if len(labels) != count:
        raise ValueError(f"ids tiene {len(labels)} identificadores para {count} puntos")
    kept, in_conflict, pairs = _cluster(xyz[:, :2], xyz[:, 2], tol_xy, tol_z)
    grouped = np.flatnonzero(np.bincount(kept, minlength=count)[kept] > 1)
    groups: list[DuplicateGroup] = []
    if grouped.size:
        order = grouped[np.lexsort((grouped, kept[grouped]))]
        cuts = np.flatnonzero(np.diff(kept[order])) + 1
        for members in np.split(order, cuts):
            groups.append(DuplicateGroup(tuple(int(i) for i in members),
                                         bool(in_conflict[members[0]])))
    groups.sort(key=lambda group: group.indices[0])
    conflicts = tuple(
        Conflict(ConflictKind.DUPLICATE_POINTS, (labels[i], labels[j]), float(xyz[i, 0]),
                 float(xyz[i, 1]), (float(xyz[i, 2]), float(xyz[j, 2])))
        for i, j in pairs.tolist()
    )
    return DuplicateReport(count, tol_xy, tol_z, tuple(groups), conflicts)


def resolve_duplicates(
    points: PointSet,
    report: DuplicateReport,
    policy: DuplicatePolicy | str,
    *,
    name: str = "",
) -> PointSet:
    """Los puntos de ``points`` sin duplicados (RF-006-14), con el informe de
    :func:`find_duplicates` sobre ellos. Cada grupo sin conflicto se queda en su primer
    punto; uno en conflicto, según ``policy``: la media (posición del primero con la cota
    media), la mínima o la máxima (ese punto tal cual) o el primero. Con conflictos,
    «preguntar» y «cancelar» lanzan :class:`~gis.reports.ConflictError` (TIN ``name``) con
    la lista. El orden es el de entrada; ``points`` no se modifica. ``ValueError`` si la
    política no existe o el informe es de otros puntos (errores del programa)."""
    policy = DuplicatePolicy(policy)
    if not isinstance(points, PointSet):
        raise TypeError("points es un PointSet")
    if report.count != len(points):
        raise ValueError(f"el informe es de {report.count} puntos y hay {len(points)}")
    if report.conflicts and policy in (DuplicatePolicy.ASK, DuplicatePolicy.CANCEL):
        code = ("gis.duplicate_conflicts" if policy is DuplicatePolicy.ASK
                else "gis.duplicates_cancelled")
        raise ConflictError(code, report.conflicts, tin=name, tol_xy=report.tol_xy,
                            tol_z=report.tol_z)
    xyz = points.xyz.copy()
    point_ids = list(points.point_ids)
    codes = list(points.codes)
    rows = list(points.source_rows)
    keep = np.ones(len(points), dtype=bool)
    for group in report.groups:
        first, *others = group.indices
        keep[others] = False
        if not group.conflict or policy is DuplicatePolicy.FIRST:
            continue
        members = list(group.indices)
        heights = points.xyz[members, 2]
        if policy is DuplicatePolicy.MEAN:
            xyz[first, 2] = float(np.mean(heights))
            continue
        pick = np.argmin(heights) if policy is DuplicatePolicy.MIN else np.argmax(heights)
        chosen = members[int(pick)]
        xyz[first] = points.xyz[chosen]
        point_ids[first] = points.point_ids[chosen]
        codes[first] = points.codes[chosen]
        rows[first] = points.source_rows[chosen]
    kept = np.flatnonzero(keep).tolist()
    return PointSet(
        xyz=np.ascontiguousarray(xyz[keep]),
        point_ids=tuple(point_ids[i] for i in kept),
        codes=tuple(codes[i] for i in kept),
        source_rows=tuple(rows[i] for i in kept),
    )
