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

Los duplicados (``TopoReport.duplicates``) los cuenta ``find_duplicates`` (T16) sobre lo que
se devuelve aquí.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np

from .messages import render
from .reports import Rejection, TopoReport

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
