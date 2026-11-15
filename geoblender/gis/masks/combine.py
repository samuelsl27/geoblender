# SPDX-License-Identifier: GPL-3.0-or-later
"""Combinar las restricciones en máscaras (spec 012; RF-012-04, RF-012-11, RF-012-13, RF-012-14,
RF-012-15; plan 012 A2, A3, D-11, D-13, D-14 y D-25).

Dos pasos:

1. :func:`prepare_steps` / :func:`prepare`: comprueba (RF-012-04, D-11) que ninguna restricción
   activa esté incompleta (``core.constraints.checks``) ni tenga una geometría no válida (se
   corta a sí misma, sin área, una línea sin longitud, sin geometría); si alguna lo está,
   :class:`IncompleteConstraints` con la lista de todas. Sin rejilla o sin límite legal activo,
   ``ConstraintError`` con la orden que lo resuelve; sin perímetro, el límite legal hace de
   perímetro, con su aviso (RF-012-15, D-14). Después, la zona de cada restricción activa
   (``gis.masks.zones``) con lo que queda fuera de la rejilla (m², con su aviso) y los límites:
   los límites legales y los perímetros **se unen antes** (``gis.polygons.overlay``) para formar
   el dominio, el corte, el relleno, la franja y la rejilla de clases, y la banda hacia dentro de
   la unión usa el mayor resguardo hacia dentro de los límites legales (del lado seguro). **Con
   varios límites legales** (T44, hallazgo F-1), lo que se da **por límite** es de cada uno: su
   zona son las celdas enteras dentro de **su** polígono y su banda hacia dentro es la banda de la
   unión ∩ sus celdas (:attr:`Limits.legal_bands`), con cada celda de la banda en un solo límite
   (el primero por código) para que ni se cuente dos veces ni se pierda.
2. :func:`combine` (**A3**): con ``P`` el perímetro (celdas enteras dentro), ``Lin`` las enteras
   dentro del límite legal, ``Lb`` su banda hacia dentro y ``U`` intocables y exclusiones:
   dominio ``D = P ∩ Lin − U``; corte ``C = D − Lb − sin corte − solo relleno − solo
   restauración − banda de resguardo``; relleno ``F = D − sin relleno``; franja ``S = P − Lin −
   U − sin relleno`` (RF-012-13: perímetro ∖ límite legal). Las prohibiciones **se suman
   siempre**: ni la prioridad ni un tipo permisivo devuelven nada (RF-012-14, D-13). Las celdas
   de ``P − U`` sin corte, sin relleno y fuera de la franja son **conflictos**, agrupados por
   las restricciones que los causan (en orden de prioridad, la mayor antes; a igual prioridad,
   por código). La **rejilla de clases** lleva los bits de D-25 (:class:`ClassBit`).

Las máscaras son tramos de fila (:class:`~.zones.Runs`). Python puro con numpy (nivel 2).

**Por pasos** (RNF-012-06; spec 012, T35): :func:`check_steps` (un paso por restricción y por
polígono), :func:`prepare_steps` y :func:`combine_steps` (un paso por operación entre máscaras y
por causa de los conflictos) ceden el control entre unidades de pocos milisegundos; :func:`check`,
:func:`prepare` y :func:`combine` son lo mismo de una vez y dan el mismo resultado bit a bit.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntFlag
from types import MappingProxyType
from typing import Any

import numpy as np

from ...core.constraints.checks import Incomplete, incomplete
from ...core.constraints.messages import ConstraintError, render
from ...core.constraints.model import (
    Constraint,
    ConstraintParam,
    ConstraintType,
    GeometryKind,
    is_code,
)
from ...core.constraints.params import param_key
from ...core.params.store import ResolvedParam
from ..grid import Grid
from ..polygons import TOLERANCE_M, drain, overlay, problem_steps
from .zones import (
    ROWS_PER_STEP,
    SEGMENTS_PER_STEP,
    LimitRuns,
    Runs,
    limit_steps,
    near_runs,
    segments_of,
    touched_runs,
    zone_steps,
)

__all__ = [
    "GRID_COMMAND",
    "LEGAL_COMMAND",
    "ClassBit",
    "Conflict",
    "IncompleteConstraints",
    "Limits",
    "Masks",
    "Notice",
    "Outside",
    "Prepared",
    "Runs",
    "Zone",
    "check",
    "check_steps",
    "combine",
    "combine_steps",
    "geometry_sha256",
    "limit_outside",
    "prepare",
    "prepare_steps",
]

LEGAL_COMMAND = "geoblender.core_edit_limits"
"""La orden que declara los límites (sin límite legal, sin perímetro)."""
GRID_COMMAND = "geoblender.gis_resample_to_grid"
"""La orden que crea la rejilla del proyecto."""

_GEOMETRY_PROBLEMS = {
    "self_intersecting": "core.constraint_self_intersecting",
    "no_area": "core.constraint_no_area",
    "hole_outside": "core.constraint_hole_outside",
    "overlap": "core.constraint_parts_overlap",
}


class ClassBit(IntFlag):
    """Los bits de la rejilla de clases (D-25)."""

    CUT_ALLOWED = 1
    FILL_ALLOWED = 2
    FILL_STRIP = 4
    PERIMETER = 8
    LEGAL = 16
    INNER_BAND = 32
    UNTOUCHABLE = 64
    AVOID = 128
    RESTORATION = 256
    ACCESS = 512
    CONFLICT = 1024


# --- Datos -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Notice:
    """Un aviso para la persona: un código de ``core.constraints.messages`` y sus valores (un
    ``ConstraintType`` se ve con su nombre en el idioma)."""

    code: str
    values: tuple[tuple[str, object], ...] = ()

    def value(self, name: str) -> object:
        """El valor ``name`` (``None`` si no lo tiene)."""
        return dict(self.values).get(name)

    def text(self, language: str = "es") -> str:
        """El aviso como lo lee una persona en ``language``."""
        shown = {k: v.label(language) if isinstance(v, ConstraintType) else v
                 for k, v in self.values}
        return render(self.code, language=language, **shown)


@dataclass(frozen=True, slots=True, eq=False)
class Zone:
    """La zona de una restricción activa en la rejilla: su código, nombre, tipo, prioridad y
    geometría; sus celdas (``runs``; de un límite legal, las enteras dentro de **su** polígono; de
    un perímetro de actuación, las enteras dentro de la unión de los perímetros); el resguardo
    hacia fuera con que se calculó, el peso («preferible no afectar») y el área de la zona fuera
    de la rejilla (m²; de un límite, la exacta del polígono)."""

    code: str
    name: str
    ctype: ConstraintType
    kind: GeometryKind
    priority: int
    runs: Runs
    outward_m: float
    weight: float | None
    outside_m2: float


@dataclass(frozen=True, slots=True, eq=False)
class Limits:
    """Los límites en la rejilla: el legal (enteras dentro y su banda hacia dentro, de la unión
    de los límites legales activos: con lo que se forman el dominio y las máscaras), las celdas
    enteras dentro del perímetro (o del límite legal, ``perimeter_from_legal``) y los códigos de
    cada uno. ``legal_bands``: la banda hacia dentro de **cada** límite legal (por código) = la
    de la unión ∩ sus celdas, cada celda de la banda en un solo límite (el primero por código):
    juntas son ``legal.band`` y ninguna celda sale en dos. Con un solo límite, ``legal.band``."""

    legal: LimitRuns
    perimeter: Runs
    legal_codes: tuple[str, ...]
    perimeter_codes: tuple[str, ...]
    perimeter_from_legal: bool
    legal_bands: Mapping[str, Runs]


@dataclass(frozen=True, slots=True)
class Outside:
    """Lo que queda fuera de la rejilla de una restricción: su código, nombre, tipo y área
    (m²)."""

    code: str
    name: str
    ctype: ConstraintType
    area_m2: float


@dataclass(frozen=True, slots=True, eq=False)
class Prepared:
    """Lo que necesita :func:`combine` y el informe de los límites: las zonas por código (en el
    orden de entrada), los límites, los polígonos ABSOLUTOS de los límites legales y del
    perímetro (el legal si no hay), y los avisos."""

    zones: Mapping[str, Zone]
    limits: Limits
    legal: tuple[tuple[np.ndarray, ...], ...]
    perimeter: tuple[tuple[np.ndarray, ...], ...]
    notices: tuple[Notice, ...]

    @property
    def outside(self) -> tuple[Outside, ...]:
        """Las restricciones con parte de su zona fuera de la rejilla."""
        return tuple(Outside(z.code, z.name, z.ctype, z.outside_m2)
                     for z in self.zones.values() if z.outside_m2 > 0.0)


@dataclass(frozen=True, slots=True, eq=False)
class Conflict:
    """Celdas sin movimiento posible (RF-012-14): las restricciones que lo causan (en orden de
    prioridad), sus celdas y su área (m²)."""

    causes: tuple[str, ...]
    runs: Runs
    area_m2: float


@dataclass(frozen=True, slots=True, eq=False)
class Masks:
    """Las máscaras combinadas (RF-012-11, RF-012-13, RF-012-14; tramos de fila) y la rejilla de
    clases (``uint16``, bits de :class:`ClassBit`)."""

    perimeter: Runs
    legal: LimitRuns
    untouchable: Runs
    default_domain: Runs
    cut_allowed: Runs
    fill_allowed: Runs
    fill_strip: Runs
    avoid: Mapping[str, float]
    restoration: Runs
    access: Runs
    conflicts: tuple[Conflict, ...]
    classes: np.ndarray = field(repr=False)

    @property
    def no_movement(self) -> Runs:
        """Todas las celdas en conflicto."""
        return Runs.union_all(c.runs for c in self.conflicts)

    @property
    def no_movement_m2(self) -> float:
        """El área sin movimiento posible (m²)."""
        return math.fsum(c.area_m2 for c in self.conflicts)


class IncompleteConstraints(ConstraintError):
    """Restricciones incompletas o no válidas que impiden combinar (RF-012-04, D-11): el error
    para el usuario, con la lista de todas en ``problems``."""

    def __init__(self, found: Sequence[Incomplete]) -> None:
        self.problems: tuple[Incomplete, ...] = tuple(found)
        super().__init__("core.constraint_incomplete", count=len(self.problems),
                         items=" ".join(p.text("es") for p in self.problems))


# --- Comprobar ---------------------------------------------------------------------------------


def _value(found: object) -> object:
    return found.value if isinstance(found, ResolvedParam) else found


def _active(item: Constraint, resolved: Mapping[str, object]) -> bool:
    return (is_code(item.code)
            and _value(resolved.get(param_key(item.code, ConstraintParam.ACTIVE))) is True)


def geometry_sha256(item: Constraint) -> str:
    """La huella de la geometría de una restricción (su tipo de geometría y sus coordenadas
    float64, parte a parte y anillo a anillo)."""
    digest = hashlib.sha256(item.kind.value.encode("ascii"))
    for part in item.parts:
        digest.update(b"P%d" % len(part))
        for ring in part:
            values = np.ascontiguousarray(ring, dtype="<f8")
            digest.update(b"R%d" % values.shape[0])
            digest.update(values.tobytes())
    return digest.hexdigest()


_PROBLEMS_MEMO: dict[str, tuple[str, ...]] = {}
"""Los problemas de geometría ya calculados, por huella de la geometría (véase
:func:`_geometry_problems_steps`)."""
_PROBLEMS_MEMO_MAX = 8192


def _geometry_problems_steps(item: Constraint) -> Generator[None, None, tuple[str, ...]]:
    """Los códigos de los problemas de la geometría de ``item`` (en su orden y sin repetir). Lo
    caro, la comprobación de polígonos que se cortan a sí mismos, es una función de la geometría
    sola: se recuerda por su huella, para que comprobar al empezar a compilar (``begin_compile``)
    y otra vez en los pasos, o compilar de nuevo, cueste una vez (T35; el resultado es el mismo)."""
    if not item.parts:
        return ("core.constraint_no_geometry",)
    if item.kind is GeometryKind.POLYGON:
        key = geometry_sha256(item)
        known = _PROBLEMS_MEMO.get(key)
        if known is not None:
            return known
        found: list[str] = []
        for problem in (yield from problem_steps(item.parts)):
            code = _GEOMETRY_PROBLEMS[problem.problem]
            if code not in found:
                found.append(code)
        if len(_PROBLEMS_MEMO) >= _PROBLEMS_MEMO_MAX:
            _PROBLEMS_MEMO.clear()
        _PROBLEMS_MEMO[key] = tuple(found)
        return tuple(found)
    if item.kind is GeometryKind.LINE:
        length = math.fsum(float(np.sum(np.hypot(*np.diff(path, axis=0).T)))
                           for part in item.parts for path in part)
        if length <= TOLERANCE_M:
            return ("core.constraint_no_length",)
    return ()


def check_steps(constraints: Iterable[Constraint], resolved: Mapping[str, object]
                ) -> Generator[None, None, tuple[Incomplete, ...]]:
    """:func:`check` por pasos: uno por restricción y por polígono de cada una (RNF-012-06)."""
    constraints = tuple(constraints)
    base = incomplete(constraints, resolved)
    yield
    by_item: dict[int, list[Incomplete]] = {}
    position = {(item.layer, item.fid): index for index, item in enumerate(constraints)}
    for found in base:
        by_item.setdefault(position.get((found.layer, found.fid), 0), []).append(found)
    for index, item in enumerate(constraints):
        if is_code(item.code) and _value(resolved.get(
                param_key(item.code, ConstraintParam.ACTIVE))) is False:
            continue
        for code in (yield from _geometry_problems_steps(item)):
            geometry = by_item.setdefault(index, [])
            # La geometría, antes de los parámetros y después de los datos de la restricción.
            geometry.append(Incomplete(item.code, item.name, item.ctype, code, "geometry",
                                       item.kind.value, item.layer, item.fid, item.kind))
        yield
    ordered: list[Incomplete] = []
    for index in sorted(by_item):
        ordered.extend(sorted(by_item[index], key=_problem_order))
    return tuple(ordered)


def check(constraints: Iterable[Constraint],
          resolved: Mapping[str, object]) -> tuple[Incomplete, ...]:
    """Lo que impide combinar ``constraints`` (RF-012-04): lo incompleto de
    ``core.constraints.checks`` y la geometría no válida de las que no están desactivadas, por
    restricción en su orden."""
    return drain(check_steps(constraints, resolved))


_ORDER = (
    "core.constraint_no_code", "core.constraint_code_invalid", "core.constraint_code_repeated",
    "core.constraint_code_repeated_declared", "core.constraint_no_type", "core.constraint_no_reason", "core.constraint_no_decider",
    "core.constraint_limit_not_polygon", "core.constraint_no_geometry",
    "core.constraint_self_intersecting", "core.constraint_no_area",
    "core.constraint_hole_outside", "core.constraint_parts_overlap", "core.constraint_no_length",
)


def _problem_order(found: Incomplete) -> int:
    return _ORDER.index(found.problem) if found.problem in _ORDER else len(_ORDER)


# --- Preparar ----------------------------------------------------------------------------------


def _number(resolved: Mapping[str, object], item: Constraint, param: ConstraintParam) -> float:
    return float(_value(resolved.get(param_key(item.code, param))))  # type: ignore[arg-type]


def _corner(grid: Grid) -> tuple[float, float]:
    return (grid.west, grid.extent.ymin)


def _outside_cells(item: Constraint, grid: Grid, outward: float, *,
                   rows_per_step: int = ROWS_PER_STEP) -> Generator[None, None, int]:
    """Las celdas de la zona de ``item`` fuera de ``grid``: su zona en una rejilla con las mismas
    líneas que cubre su caja ampliada en el resguardo (y una celda), menos las de la ventana.

    Esa rejilla ampliada tiene el tamaño de la restricción: con celdas de 1 m, la de un recinto de
    50 km son 2,5·10⁹ celdas, y construir su zona (una matriz densa por banda de filas) tardaba
    88 s en pasos de 0,5 s (RNF-012-01 y RNF-012-06; T40, hallazgo F-4). No se construye: se
    recorre por **bandas de ``rows_per_step`` filas**, la zona de cada una **por tramos**
    (``zones.touched_runs`` y ``near_runs``, a coste de las celdas que cruzan las aristas) y se
    cuentan las de fuera de la ventana banda a banda, un paso por banda. Las celdas son, bit a bit,
    las de la zona de ``zone_steps`` en esa rejilla."""
    segments = segments_of(item, grid)
    dx, dy = grid.dx, grid.dy
    c0 = math.floor((float(segments[..., 0].min()) - outward) / dx) - 1
    c1 = math.ceil((float(segments[..., 0].max()) + outward) / dx) + 1
    s0 = math.floor((float(segments[..., 1].min()) - outward) / dy) - 1
    s1 = math.ceil((float(segments[..., 1].max()) + outward) / dy) + 1
    if c0 >= 0 and s0 >= 0 and c1 <= grid.ncols and s1 <= grid.nrows:
        return 0
    # La rejilla ampliada lleva las coordenadas absolutas reales: la tolerancia de la celda (T39)
    # sale de ellas, como en la del proyecto.
    wide = Grid(grid.west + c0 * dx, grid.extent.ymin + s1 * dy, dx, dy, c1 - c0, s1 - s0)
    polygon = getattr(item.kind, "value", item.kind) == GeometryKind.POLYGON.value
    shape = segments_of(item, wide)
    shift = grid.nrows - s1
    rows = np.arange(max(0, shift), min(grid.nrows, grid.nrows - s0), dtype=np.int64)
    window = Runs(rows, np.zeros_like(rows), np.full_like(rows, grid.ncols))
    size = max(int(rows_per_step), 1)
    outside = 0
    for begin in range(0, wide.nrows, size):
        band = slice(begin, begin + size)
        found = [touched_runs(shape, wide, rows=band)] if polygon else []
        if outward > 0.0:
            found.append(near_runs(shape, outward, wide, rows=band))
        zone = Runs.union_all(found)
        if len(zone):
            shifted = Runs(zone.row + shift, zone.col0 + c0, zone.col1 + c0)
            here = window.between_rows(begin + shift, begin + size - 1 + shift)
            outside += shifted.cells - shifted.intersection(here).cells
        yield
    return outside


def limit_outside(item: Constraint, grid: Grid) -> float:
    """El área exacta (m²) del polígono de un límite fuera de ``grid``."""
    box = grid.extent
    window = np.array([[box.xmin, box.ymin], [box.xmax, box.ymin], [box.xmax, box.ymax],
                       [box.xmin, box.ymax], [box.xmin, box.ymin]], dtype=np.float64)
    area = overlay(item.parts, [(window,)], "difference", origin=_corner(grid)).area_m2
    return area if area > 0.0 else 0.0


def _by_priority(codes: Iterable[str], zones: Mapping[str, Zone]) -> tuple[str, ...]:
    return tuple(sorted(codes, key=lambda code: (-zones[code].priority, code)))


def _own_cells_steps(legal: Sequence[Constraint], united: LimitRuns, grid: Grid,
                     corner: tuple[float, float], steps: Mapping[str, int]
                     ) -> Generator[None, None, dict[str, Runs]]:
    """Las celdas enteras dentro de **su** polígono de cada límite legal (por código; T44, F-1).
    Con uno solo son las de la unión, sin recalcular; con varios, las de cada polígono (sus partes
    se unen antes, como la unión de todos) y una celda que los límites reparten (a caballo de la
    frontera común) no está entera dentro de ninguno."""
    if len(legal) == 1:
        return {legal[0].code: united.inside}
    found: dict[str, Runs] = {}
    for item in legal:
        edges = overlay(item.parts, [], "union", origin=corner).edges_local
        yield
        found[item.code] = (yield from limit_steps(edges, grid, None, **steps)).inside
    return found


def _inner_bands_steps(legal: Sequence[Constraint], united: LimitRuns,
                       own: Mapping[str, Runs], grid: Grid, steps: Mapping[str, int]
                       ) -> Generator[None, None, dict[str, Runs]]:
    """La banda hacia dentro de cada límite legal (por código; T44, F-1): la banda de la unión
    (``united.band``, con el mayor resguardo hacia dentro de todos) ∩ las celdas de ese límite,
    **cada celda de la banda en un solo límite**: la que está en dos límites que se solapan va al
    primero por código (el orden alfabético de los códigos, el mismo con cualquier orden de
    entrada). La celda de la banda a caballo de dos límites (entera dentro de la unión, no de
    ninguno) va al primero por código que la toca. Entre todas son ``united.band``: ni se cuenta
    una celda dos veces ni se pierde un corte en ella."""
    order = sorted(item.code for item in legal)
    if len(order) == 1:
        return {order[0]: united.band}
    bands: dict[str, Runs] = {}
    rest = united.band
    for code in order:
        bands[code] = rest.intersection(own[code])
        rest = rest.difference(bands[code])
        yield
    if len(rest):  # a caballo: sin celdas enteras en ningún límite, pero dentro de la unión
        by_code = {item.code: item for item in legal}
        for code in order:
            touched = yield from zone_steps(by_code[code], grid, 0.0, **steps)
            mine = rest.intersection(touched)
            if len(mine):
                bands[code] = bands[code].union(mine)
                rest = rest.difference(mine)
            if not len(rest):
                break
        if len(rest):  # defensa: lo que ninguno toca (por el redondeo) va al primero, no se pierde
            bands[order[0]] = bands[order[0]].union(rest)
    return bands


def prepare_steps(constraints: Iterable[Constraint], resolved: Mapping[str, object],
                  grid: Grid | None, *, segments_per_step: int = SEGMENTS_PER_STEP,
                  rows_per_step: int = ROWS_PER_STEP) -> Generator[None, None, Prepared]:
    """Las zonas y los límites de ``constraints`` en ``grid`` por pasos (RF-012-04, RF-012-11,
    RF-012-15); lo preparado (:class:`Prepared`), en ``StopIteration.value``. ``resolved``: los
    valores de sus parámetros en la versión, por clave (valor o ``ResolvedParam``)."""
    constraints = tuple(constraints)
    if grid is None:
        raise ConstraintError("core.constraint_no_grid", command=GRID_COMMAND)
    found = yield from check_steps(constraints, resolved)
    if found:
        raise IncompleteConstraints(found)
    active = [item for item in constraints if _active(item, resolved)]
    legal = [item for item in active if item.ctype is ConstraintType.LEGAL_LIMIT]
    if not legal:
        raise ConstraintError("core.constraint_no_legal_limit", command=LEGAL_COMMAND)
    perimeter = [item for item in active if item.ctype is ConstraintType.ACTION_PERIMETER]
    steps = {"segments_per_step": segments_per_step, "rows_per_step": rows_per_step}
    corner = _corner(grid)
    notices: list[Notice] = []

    legal_parts = tuple(part for item in legal for part in item.parts)
    inward = max(_number(resolved, item, ConstraintParam.BUFFER_IN) for item in legal)
    edges = overlay(legal_parts, [], "union", origin=corner).edges_local
    yield
    legal_runs = yield from limit_steps(edges, grid, inward, **steps)
    own_cells = yield from _own_cells_steps(legal, legal_runs, grid, corner, steps)
    inner_bands = yield from _inner_bands_steps(legal, legal_runs, own_cells, grid, steps)
    if perimeter:
        perimeter_parts = tuple(part for item in perimeter for part in item.parts)
        edges = overlay(perimeter_parts, [], "union", origin=corner).edges_local
        yield
        perimeter_runs = (yield from limit_steps(edges, grid, None, **steps)).inside
    else:
        perimeter_parts = legal_parts
        perimeter_runs = legal_runs.inside
        names = ", ".join(item.shown_name() for item in legal)
        notices.append(Notice("core.constraint_perimeter_from_legal",
                              (("name", names), ("command", LEGAL_COMMAND))))

    zones: dict[str, Zone] = {}
    for item in active:
        assert item.ctype is not None
        weight = None
        if item.ctype.is_limit:
            runs = perimeter_runs if item.ctype is ConstraintType.ACTION_PERIMETER else (
                own_cells[item.code])
            outward = 0.0
            outside = limit_outside(item, grid)
            yield
        else:
            outward = _number(resolved, item, ConstraintParam.BUFFER_OUT)
            if item.ctype is ConstraintType.AVOID:
                weight = _number(resolved, item, ConstraintParam.WEIGHT)
            runs = yield from zone_steps(item, grid, outward, **steps)
            outside = (yield from _outside_cells(
                item, grid, outward, rows_per_step=rows_per_step)) * grid.cell_area
        zones[item.code] = Zone(item.code, item.shown_name(), item.ctype, item.kind,
                                item.priority, runs, outward, weight, outside)
        if outside > 0.0:
            notices.append(Notice("core.constraint_zone_outside_grid", (
                ("code", item.code), ("name", item.shown_name()), ("ctype", item.ctype),
                ("area", round(outside, 2)))))
    legal_codes = _by_priority((i.code for i in legal), zones)
    limits = Limits(legal_runs, perimeter_runs, legal_codes,
                    _by_priority((i.code for i in perimeter or legal), zones),
                    not perimeter, MappingProxyType({code: inner_bands[code]
                                                     for code in legal_codes}))
    return Prepared(MappingProxyType(zones), limits, legal_parts, perimeter_parts,
                    tuple(notices))


def prepare(constraints: Iterable[Constraint], resolved: Mapping[str, object],
            grid: Grid | None, **steps: int) -> Prepared:
    """:func:`prepare_steps` de una vez."""
    return drain(prepare_steps(constraints, resolved, grid, **steps))


# --- Combinar (A3) -----------------------------------------------------------------------------


def _union(zones: Iterable[Zone], test: Any) -> Runs:
    return Runs.union_all(zone.runs for zone in zones if test(zone.ctype))


def _cells(runs: Runs) -> tuple[np.ndarray, np.ndarray]:
    """Las celdas de ``runs`` (fila, columna), en orden."""
    count = runs.col1 - runs.col0
    owner = np.repeat(np.arange(len(runs)), count)
    offset = np.arange(owner.size) - np.repeat(np.cumsum(count) - count, count)
    return runs.row[owner], runs.col0[owner] + offset


_GROUPS_PER_UNIT = 32
"""Conflictos que arma cada unidad de :func:`_conflicts_steps` (cada uno cuesta unas decenas de
microsegundos)."""


def _conflicts_steps(blocked: Runs, candidates: list[tuple[str, Runs]], grid: Grid,
                     zones: Mapping[str, Zone]) -> Generator[None, None, tuple[Conflict, ...]]:
    """Los conflictos de las celdas ``blocked`` por las causas ``candidates`` (código, celdas),
    una unidad por causa y por grupo de conflictos (T35)."""
    if len(blocked) == 0:
        return ()
    rows, cols = _cells(blocked)
    keys = rows * grid.ncols + cols  # ascendentes: las celdas salen por fila y columna
    # Las celdas con las mismas causas, por refinamiento de grupos: cada causa parte los grupos
    # que toca en lo que está dentro y lo que no. Cuesta lo que suman las intersecciones, no
    # celdas bloqueadas × causas (la matriz celda × causa tardaba 8 s con 500 recintos). Cada
    # intersección es con las filas que toca la causa, no con todas las bloqueadas (mismo resultado).
    label = np.zeros(keys.size, dtype=np.int64)
    causes_of: list[tuple[int, ...]] = [()]
    for index, (_, runs) in enumerate(candidates):
        if len(runs) == 0:
            continue
        near = blocked.between_rows(int(runs.row[0]), int(runs.row[-1]))
        r, c = _cells(runs.intersection(near))
        if r.size == 0:
            continue
        at = np.searchsorted(keys, r * grid.ncols + c)  # lo que cruza está en lo bloqueado
        touched, inverse = np.unique(label[at], return_inverse=True)
        first = len(causes_of)
        causes_of.extend((*causes_of[old], index) for old in touched.tolist())
        label[at] = first + inverse.ravel()
        yield
    order = np.argsort(label, kind="stable")  # dentro de un grupo, sus celdas siguen en orden
    starts = np.flatnonzero(np.diff(label[order], prepend=-1))
    found = []
    for count, (begin, end) in enumerate(zip(starts.tolist(),
                                             [*starts[1:].tolist(), order.size], strict=True)):
        mine = order[begin:end]
        causes = _by_priority((candidates[k][0] for k in causes_of[int(label[mine[0]])]), zones)
        runs = Runs(rows[mine], cols[mine], cols[mine] + 1)
        found.append(Conflict(causes, runs, runs.area(grid)))
        if count % _GROUPS_PER_UNIT == _GROUPS_PER_UNIT - 1:
            yield
    found.sort(key=lambda c: (-c.runs.cells, c.causes))
    return tuple(found)


def _conflicts(blocked: Runs, candidates: list[tuple[str, Runs]], grid: Grid,
               zones: Mapping[str, Zone]) -> tuple[Conflict, ...]:
    return drain(_conflicts_steps(blocked, candidates, grid, zones))


def _paint(classes: np.ndarray, runs: Runs, bit: ClassBit) -> None:
    """Pone ``bit`` en las celdas de ``runs`` de la rejilla de clases."""
    if len(runs):
        np.bitwise_or(classes, np.uint16(int(bit)), out=classes, where=runs.mask(classes.shape))


def combine_steps(zones: Mapping[str, Zone], limits: Limits, grid: Grid
                  ) -> Generator[None, None, Masks]:
    """:func:`combine` por pasos (RNF-012-06; T35): una unidad por operación entre máscaras, por
    causa de los conflictos y por bit de la rejilla de clases."""
    items = [zone for zone in zones.values() if not zone.ctype.is_limit]
    perimeter, legal = limits.perimeter, limits.legal
    untouchable = _union(items, lambda t: t.removes_from_domain)
    yield
    no_cut = _union(items, lambda t: t.forbids_cut and not t.removes_from_domain)
    no_fill = _union(items, lambda t: t.forbids_fill and not t.removes_from_domain)
    yield
    domain = perimeter.intersection(legal.inside).difference(untouchable)
    yield
    cut = domain.difference(legal.band).difference(no_cut)
    yield
    fill = domain.difference(no_fill)
    strip = perimeter.difference(legal.inside).difference(untouchable).difference(no_fill)
    yield
    restoration = _union(items, lambda t: t is ConstraintType.RESTORATION_ONLY)
    access = _union(items, lambda t: t is ConstraintType.REQUIRES_ACCESS)
    avoid_runs = _union(items, lambda t: t is ConstraintType.AVOID)
    avoid = MappingProxyType({z.code: float(z.weight) for z in items  # type: ignore[arg-type]
                              if z.ctype is ConstraintType.AVOID})
    yield

    blocked = (perimeter.difference(untouchable).difference(cut).difference(fill)
               .difference(strip))
    yield
    outside_core = blocked.difference(legal.core)
    candidates = [(code, outside_core) for code in limits.legal_codes]
    candidates += [(z.code, z.runs) for z in items
                   if (z.ctype.forbids_cut or z.ctype.forbids_fill)
                   and not z.ctype.removes_from_domain]
    yield
    conflicts = yield from _conflicts_steps(blocked, candidates, grid, zones)
    conflict_runs = Runs.union_all(c.runs for c in conflicts)
    yield

    classes = np.zeros(grid.shape, dtype=np.uint16)
    yield
    for bit, runs in ((ClassBit.CUT_ALLOWED, cut), (ClassBit.FILL_ALLOWED, fill),
                      (ClassBit.FILL_STRIP, strip), (ClassBit.PERIMETER, perimeter),
                      (ClassBit.LEGAL, legal.inside), (ClassBit.INNER_BAND, legal.band),
                      (ClassBit.UNTOUCHABLE, untouchable), (ClassBit.AVOID, avoid_runs),
                      (ClassBit.RESTORATION, restoration), (ClassBit.ACCESS, access),
                      (ClassBit.CONFLICT, conflict_runs)):
        _paint(classes, runs, bit)
        yield
    return Masks(perimeter, legal, untouchable, domain, cut, fill, strip, avoid, restoration,
                 access, conflicts, classes)


def combine(zones: Mapping[str, Zone], limits: Limits, grid: Grid) -> Masks:
    """**A3** (RF-012-13, RF-012-14; D-13, D-25): las máscaras de ``zones`` y ``limits`` en
    ``grid``."""
    return drain(combine_steps(zones, limits, grid))
