# SPDX-License-Identifier: GPL-3.0-or-later
"""El núcleo de la verificación en m³ por recinto (spec 012; RF-012-21, RF-012-22, RF-012-23;
plan 012 §5.3.1, A7–A10, D-6, D-41).

Una superficie final frente a la de partida, celda a celda, en la rejilla de las máscaras:

- :class:`CheckZone` y :func:`check_zones`: los recintos que se verifican, en su orden: «fuera
  del perímetro» (:data:`OUTSIDE_PERIMETER`, las celdas sin el bit del perímetro de la rejilla de
  clases), «fuera del límite legal» (:data:`OUTSIDE_LEGAL`, sin el bit del límite legal: las que
  no están enteras dentro, D-1) y la zona de cada restricción por su código (sus tramos de
  ``gis_mskz_``; ``<código>:inner``, la banda hacia dentro de un límite legal), cada uno con lo
  que cuenta en él (:class:`Counts`, A8): el corte, el relleno, cualquier movimiento, nada (un
  límite por dentro), su afección («preferible no afectar») o nada que comprobar («requiere
  acceso», R-40).
- :class:`Checker`: **A7**, por bandas de filas (las de ``reserves.surfaces.lockstep_bands``):
  ``d = partida − final`` donde las dos tienen dato; corte donde ``d > e`` y relleno donde
  ``−d > e`` (``e``, el espesor mínimo de verificación, D-6), **con todo su espesor** (lo que no
  pasa el umbral no cuenta; lo que pasa, entero); por recinto, el corte y el relleno (m³), el
  área con movimiento (m²) y el área sin dato (m²), con los tramos de fila de cada recinto (sumas
  acumuladas por fila: ningún par celda-recinto). Una celda en dos recintos cuenta en los dos: la
  tabla es por recinto, no una partición.
- **La base de los acopios (A12; RF-012-21, RF-012-22, RF-012-30; DIFF-012 de la 016)**: una
  retirada de acopio baja material por encima de la base del acopio, que no es terreno. Con la
  base (``Checker.add(..., base=)``: su cota en cada celda de las huellas de los acopios
  detectados, NaN fuera) los recintos de :attr:`Counts.CUT_TERRAIN` (sin corte, solo relleno,
  solo restauración, banda de resguardo y banda hacia dentro de un límite legal; se piden con
  ``with_base=True`` en :func:`counts_of` y :func:`check_zones`) cuentan como **corte de
  terreno** solo el de ``R = mín(partida, base)`` frente a la final (``R = partida`` donde no hay
  base), con todo su espesor cuando ``R − final`` pasa del umbral; el resto del corte de
  RF-012-21 es el **corte de acopios** (:attr:`ZoneTotals.stockpile_cut_m3`) y el corte de
  terreno más el de acopios es ese corte (``cut_m3``). El veredicto, los grupos y la rejilla de
  incumplimientos usan el de terreno. Fuera del límite legal, los intocables, las exclusiones,
  fuera del perímetro, el relleno en «sin relleno» y la afección cuentan **todo** el movimiento
  (donde un acopio no se retira: RF-016-11). Sin base, o sin recintos de terreno, el resultado
  es el de siempre, bit a bit (:attr:`Counts.CUT`). :func:`lowest_base` toma la menor de varias
  bases (P-10) y este módulo no importa ``design``: quien lee la base de las detecciones es
  ``reserves.compliance_store``.
- :class:`ZoneIndex` (:func:`zone_index`, :func:`zone_index_steps`): lo que las finales de una
  verificación comparten, hecho una vez (T36): los tramos de todos los recintos ordenados por
  fila, los de cada modo de contar y la unión de las celdas de cada modo como máscara.
- :func:`verdict`: **A9** (CA-2, CA-13; D-6): «no cumple» si lo que cuenta pasa de 0 m³
  (tolerancia 0 con el umbral ``e``: basta una celda), «cumple» si no; «preferible no afectar»,
  sin juicio (su afección en m², m³ y m³ × peso); «requiere acceso», «sin comprobar (R-40)».
- :func:`label_groups`: **A10** (D-41): las celdas que incumplen, agrupadas por contigüidad de
  lado (4-conexión) con tramos de fila, parejas de tramos de filas seguidas que se solapan
  (búsqueda binaria) y etiquetas por saltos de puntero (Shiloach–Vishkin, 1982). Cada grupo
  (:class:`Group`) con su recinto, su área (m²), su volumen (m³), su espesor máximo (m), su centro
  absoluto (media de los centros de sus celdas, de igual área) y su caja, para «Ir a». **A escala
  (T36)** :meth:`Checker.result_steps` no agrupa celdas sino los **tramos** de fila de las que
  incumplen en cada recinto (la intersección de los tramos del recinto con los de las celdas que
  cuentan, de la rejilla de incumplimientos), por pasos cortos; el resultado es el mismo, bit a
  bit (las sumas de enteros son exactas y el volumen es ``math.fsum``, que no depende del orden).
- :func:`check`: una final de una vez (:class:`FinalCheck`, con la rejilla de las celdas que
  incumplen y su ``final − partida``, D-42); la misma superficie como partida y final da ceros y
  el aviso ``res.same_surface``.
- :class:`ComplianceRequest`: lo que pide una verificación (la partida, de 1 a
  :data:`MAX_FINALS` finales, las máscaras de la versión, el espesor mínimo y, opcional, las bases
  de los acopios detectados sobre la partida); la lee la operación ``res.verify_constraints``
  (``reserves.compliance_store``, T17).

Volúmenes y áreas con el área exacta de la celda de la rejilla (``Grid.cell_area``), en float64.
Python puro (nivel 9).
"""

from __future__ import annotations

import math
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

import numpy as np

from ..core.constraints.model import ConstraintType
from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from ..gis.masks.zones import Runs
from .surfaces import BAND_ROWS, SurfaceRef
from .volumes import Notice

__all__ = [
    "INNER_SUFFIX",
    "MAX_FINALS",
    "OUTSIDE_LEGAL",
    "OUTSIDE_PERIMETER",
    "CheckZone",
    "Checker",
    "ComplianceRequest",
    "Counts",
    "FinalCheck",
    "Group",
    "Verdict",
    "ZoneIndex",
    "ZoneTotals",
    "check",
    "check_zones",
    "check_zones_steps",
    "counts_of",
    "label_groups",
    "lowest_base",
    "verdict",
    "zone_index",
    "zone_index_steps",
]

OUTSIDE_PERIMETER = "outside_perimeter"
"""El código del recinto «fuera del perímetro» (cualquier movimiento incumple)."""
OUTSIDE_LEGAL = "outside_legal"
"""El código del recinto «fuera del límite legal» (el corte incumple; el relleno, no)."""
INNER_SUFFIX = ":inner"
"""El sufijo de la banda hacia dentro de un límite legal (``<código>:inner``, de ``gis_mskz_``)."""
MAX_FINALS = 10
"""Finales de una verificación, como mucho (D-40)."""
_MAX_THICKNESS_M = 10.0
_INDEX_ROWS = 256
"""Las filas de una unidad al calcular lo que comparten las finales."""
_CHUNK_ROWS = 64
"""Las filas de una unidad al buscar los tramos de las celdas que incumplen."""
_RUNS_PER_UNIT = 1 << 15
"""Los tramos de recinto de una unidad al cruzarlos con los de las celdas que incumplen."""
_CELLS_PER_UNIT = 1 << 17
"""Las celdas de una unidad al sacar las filas, las columnas y los espesores de los grupos."""
_GROUP_RUNS_PER_UNIT = 1024
"""Los tramos de grupo, como mucho, de una de esas unidades (los grupos pequeños cuestan más
por grupo que por celda)."""


class Counts(StrEnum):
    """Lo que cuenta en un recinto (A8; RF-012-22)."""

    CUT = "cut"  # el corte: fuera del límite legal, banda hacia dentro, sin corte, solo relleno…
    CUT_TERRAIN = "cut_terrain"  # el corte de terreno (A12): como CUT, menos lo de los acopios
    FILL = "fill"  # el relleno: sin relleno
    ANY = "any"  # cualquier movimiento: fuera del perímetro, intocable, exclusión
    NOTHING = "nothing"  # nada: un límite por dentro
    AVOID = "avoid"  # su afección, sin juicio: preferible no afectar
    ACCESS = "access"  # sin comprobar (R-40): requiere acceso


class Verdict(StrEnum):
    """El veredicto de un recinto (A9)."""

    COMPLIES = "complies"  # cumple
    FAILS = "fails"  # no cumple
    NOT_JUDGED = "not_judged"  # preferible no afectar: su afección, sin juicio
    UNCHECKED = "unchecked"  # requiere acceso: sin comprobar (R-40)


_CUT_TYPES = (ConstraintType.NO_CUT, ConstraintType.FILL_ONLY, ConstraintType.RESTORATION_ONLY,
              ConstraintType.SETBACK)
_ANY_TYPES = (ConstraintType.UNTOUCHABLE, ConstraintType.EXCLUSION)
_COUNTED = (Counts.CUT, Counts.CUT_TERRAIN, Counts.FILL, Counts.ANY)
"""Los modos de contar que dan grupos que incumplen."""


def counts_of(code: str, ctype: ConstraintType | None, *, with_base: bool = False) -> Counts:
    """Lo que cuenta en el recinto ``code`` de tipo ``ctype`` (A8; ``None`` en los dos recintos
    de los límites, :data:`OUTSIDE_PERIMETER` y :data:`OUTSIDE_LEGAL`). Con ``with_base`` (hay
    base de acopios, A12), en las cinco zonas del dominio por defecto (sin corte, solo relleno,
    solo restauración, banda de resguardo y banda hacia dentro de un límite legal) cuenta el corte
    de terreno (:attr:`Counts.CUT_TERRAIN`); «fuera del límite legal» sigue en
    :attr:`Counts.CUT`."""
    if code == OUTSIDE_PERIMETER:
        return Counts.ANY
    if code == OUTSIDE_LEGAL:
        return Counts.CUT
    if ctype is None:
        raise ValueError(f"el recinto «{code}» no tiene tipo de restricción")
    ctype = ConstraintType(ctype)
    cut = Counts.CUT_TERRAIN if with_base else Counts.CUT
    if code.endswith(INNER_SUFFIX):
        if ctype is not ConstraintType.LEGAL_LIMIT:
            raise ValueError(f"«{code}»: solo un límite legal tiene banda hacia dentro")
        return cut
    if ctype in _ANY_TYPES:
        return Counts.ANY
    if ctype in _CUT_TYPES:
        return cut
    if ctype is ConstraintType.NO_FILL:
        return Counts.FILL
    if ctype is ConstraintType.AVOID:
        return Counts.AVOID
    if ctype is ConstraintType.REQUIRES_ACCESS:
        return Counts.ACCESS
    return Counts.NOTHING  # un límite (legal o perímetro): prohíbe fuera, no dentro


@dataclass(frozen=True, slots=True, eq=False)
class CheckZone:
    """Un recinto que se verifica: su código, su tipo (``None`` en los dos de los límites), lo
    que cuenta en él, sus celdas (tramos de fila) y su peso («preferible no afectar»)."""

    code: str
    ctype: ConstraintType | None
    counts: Counts
    runs: Runs = field(repr=False)
    weight: float | None = None


def _mask_runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los tramos de fila (fila, primera columna, siguiente a la última) de las celdas
    verdaderas de la máscara 2D ``mask``, de norte a sur y de oeste a este."""
    height, width = mask.shape
    padded = np.zeros((height, width + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    flat = padded.reshape(-1)
    # Cada fila empieza y acaba en 0: los cambios alternan «sube» (empieza un tramo) y «baja»
    # (acaba), y entre el final de una fila y el principio de la siguiente no hay ninguno.
    edges = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    first, after = edges[0::2], edges[1::2]
    stride = width + 2
    row = first // stride
    base = row * stride + 1
    return row, first - base, after - base


def check_zones_steps(classes: np.ndarray, zones: Mapping[str, Runs],
                      ctypes: Mapping[str, ConstraintType],
                      weights: Mapping[str, float] | None = None, *, with_base: bool = False
                      ) -> Generator[None, None, tuple[CheckZone, ...]]:
    """:func:`check_zones` por pasos (T36): una unidad por cada :data:`_INDEX_ROWS` filas de las
    celdas de los dos recintos de fuera. Devuelve los recintos."""
    classes = np.asarray(classes)
    if classes.ndim != 2:
        raise ValueError(f"la rejilla de clases es 2D, no de forma {classes.shape}")
    weights = weights or {}
    bits = classes.astype(np.uint16, copy=False)
    empty = np.zeros(0, np.int64)
    outside = []
    for bit in (ClassBit.PERIMETER, ClassBit.LEGAL):
        pieces = []
        for top in range(0, bits.shape[0], _INDEX_ROWS):
            local, begin, end = _mask_runs((bits[top:top + _INDEX_ROWS] & np.uint16(bit)) == 0)
            pieces.append((local + top, begin, end))
            yield None
        outside.append(Runs(*(np.concatenate([piece[k] for piece in pieces] or [empty])
                              for k in range(3))))
    found = [
        CheckZone(OUTSIDE_PERIMETER, None, Counts.ANY, outside[0]),
        CheckZone(OUTSIDE_LEGAL, None, Counts.CUT, outside[1]),
    ]
    for code, runs in zones.items():
        base = code.removesuffix(INNER_SUFFIX)
        if base not in ctypes:
            raise ValueError(f"la zona «{code}» no tiene tipo de restricción")
        ctype = ConstraintType(ctypes[base])
        counts = counts_of(code, ctype, with_base=with_base)
        weight = None
        if counts is Counts.AVOID:
            if code not in weights:
                raise ValueError(f"la zona «{code}» (preferible no afectar) no tiene peso")
            weight = float(weights[code])
        found.append(CheckZone(code, ctype, counts, runs, weight))
    return tuple(found)


def _drain[T](steps: Generator[None, None, T]) -> T:
    """Recorre unos pasos hasta el final y devuelve lo que devuelven."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def check_zones(classes: np.ndarray, zones: Mapping[str, Runs],
                ctypes: Mapping[str, ConstraintType],
                weights: Mapping[str, float] | None = None, *, with_base: bool = False
                ) -> tuple[CheckZone, ...]:
    """Los recintos de una verificación (A7, A8): «fuera del perímetro» y «fuera del límite
    legal» por los bits de la rejilla de clases ``classes`` (D-25) y cada zona de ``zones``
    (código → tramos, en su orden; ``<código>:inner`` con el tipo de su límite legal), con su
    tipo de ``ctypes`` y, la «preferible no afectar», su peso de ``weights``. Con ``with_base``
    (la verificación tiene base de acopios, A12), las cinco zonas del dominio por defecto cuentan
    el corte de terreno (:attr:`Counts.CUT_TERRAIN`); sin ella, el corte (:attr:`Counts.CUT`),
    como siempre."""
    return _drain(check_zones_steps(classes, zones, ctypes, weights, with_base=with_base))


def verdict(zone: CheckZone, counted_cells: int) -> Verdict:
    """**A9** (CA-2, CA-13; D-6): el veredicto de ``zone`` con ``counted_cells`` celdas cuyo
    movimiento cuenta en ella (las que pasan el espesor mínimo; cada una, > 0 m³)."""
    if zone.counts is Counts.AVOID:
        return Verdict.NOT_JUDGED
    if zone.counts is Counts.ACCESS:
        return Verdict.UNCHECKED
    if zone.counts is Counts.NOTHING:
        return Verdict.COMPLIES
    return Verdict.FAILS if counted_cells > 0 else Verdict.COMPLIES


@dataclass(frozen=True, slots=True)
class ZoneTotals:
    """Lo verificado en un recinto (RF-012-21, RF-012-22): su código y su tipo, lo que cuenta,
    el corte y el relleno (m³) y el área con movimiento (m²) de las celdas que pasan el espesor
    mínimo, el área sin dato (m²), lo que cuenta (m³; el corte, el relleno o los dos), su peso y
    el volumen por el peso («preferible no afectar»; si no, ``None``), y el veredicto.

    En un recinto de :attr:`Counts.CUT_TERRAIN` (A12; RF-012-30), ``cut_m3`` sigue siendo el corte
    de RF-012-21 (el de toda la partida), ``counted_m3`` es el **corte de terreno** (el que
    juzga el veredicto) y ``stockpile_cut_m3``, el **corte de acopios** (el resto): terreno +
    acopios = ``cut_m3``. En los demás recintos, ``stockpile_cut_m3`` es 0."""

    code: str
    ctype: ConstraintType | None
    counts: Counts
    cut_m3: float
    fill_m3: float
    moved_m2: float
    nodata_m2: float
    counted_m3: float
    weight: float | None
    weighted_m3: float | None
    verdict: Verdict
    stockpile_cut_m3: float = 0.0


@dataclass(frozen=True, slots=True, eq=False)
class Group:
    """Un grupo de celdas contiguas (4-conexión) que incumple en un recinto (RF-012-23): el
    recinto, sus celdas (número, y sus filas y columnas en la rejilla), su área (m²), su volumen
    (m³), su espesor máximo (m), su centro ABSOLUTO (x, y) y su caja ABSOLUTA (oeste, sur, este,
    norte)."""

    zone: str
    cells: int
    area_m2: float
    volume_m3: float
    max_m: float
    center: tuple[float, float]
    box: tuple[float, float, float, float]
    rows: np.ndarray = field(repr=False)
    cols: np.ndarray = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class FinalCheck:
    """La verificación de una final: lo de cada recinto en su orden, los grupos que incumplen
    (por recinto y, en cada uno, por su primera celda de norte a sur y de oeste a este), si la
    final es la misma superficie que la partida, los avisos y la rejilla de las celdas que
    incumplen con su espesor con signo (:attr:`violations`)."""

    totals: tuple[ZoneTotals, ...]
    groups: tuple[Group, ...]
    same_surface: bool
    notices: tuple[Notice, ...]
    violations: np.ndarray | None = field(default=None, repr=False)
    """La rejilla de incumplimientos (D-42), de la forma de la rejilla de las máscaras: ``final −
    partida`` (m) en las celdas que incumplen en algún recinto (una celda en dos recintos, una
    vez) y NaN en las demás. ``None`` si ninguna incumple. De solo lectura. En una celda que solo
    incumple en un recinto de terreno (:attr:`Counts.CUT_TERRAIN`, A12), el valor es ``final −
    R``, con ``R = mín(partida, base)``: el espesor del corte de terreno."""

    @property
    def fails(self) -> bool:
        """Si algún recinto no cumple."""
        return any(item.verdict is Verdict.FAILS for item in self.totals)

    def zone(self, code: str) -> ZoneTotals:
        """Lo del recinto ``code`` (``KeyError`` si no lo hay)."""
        for item in self.totals:
            if item.code == code:
                return item
        raise KeyError(code)

    def groups_of(self, code: str) -> tuple[Group, ...]:
        """Los grupos que incumplen en el recinto ``code``."""
        return tuple(group for group in self.groups if group.zone == code)


# --- Lo que comparten las finales ----------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class _TypedRuns:
    """Los tramos de los recintos de un modo de contar, en el orden (recinto, fila, columna)."""

    position: np.ndarray
    row: np.ndarray
    col0: np.ndarray
    col1: np.ndarray


@dataclass(frozen=True, slots=True, eq=False)
class ZoneIndex:
    """Los recintos de una verificación listos para sus finales (T36), hechos una vez:

    - ``position``, ``row``, ``col0`` y ``col1``: los tramos de todos los recintos recortados a
      la rejilla y ordenados por fila (estable), para las sumas por banda;
    - ``typed``: los tramos de los recintos de cada modo de contar de :data:`_COUNTED`, en el
      orden (recinto, fila, columna), para los grupos;
    - ``masks``: la unión de las celdas de los recintos de cada modo como máscara de la rejilla,
      para marcar la rejilla de incumplimientos."""

    grid: Grid
    zones: tuple[CheckZone, ...]
    position: np.ndarray
    row: np.ndarray
    col0: np.ndarray
    col1: np.ndarray
    typed: Mapping[Counts, _TypedRuns]
    masks: Mapping[Counts, np.ndarray]


def zone_index_steps(grid: Grid, zones: Sequence[CheckZone]
                     ) -> Generator[None, None, ZoneIndex]:
    """El :class:`ZoneIndex` de ``zones`` en ``grid``, por pasos: una unidad por cada
    :data:`_INDEX_ROWS` filas de las máscaras y por cada ordenación."""
    if not isinstance(grid, Grid):
        raise TypeError(f"se esperaba una Grid, no {type(grid).__name__}")
    zones = tuple(zones)
    codes = [zone.code for zone in zones]
    if len(set(codes)) != len(codes):
        raise ValueError(f"códigos de recinto repetidos: {codes}")
    empty = np.zeros(0, np.int64)
    position = np.concatenate([np.full(len(z.runs), i, np.int64) for i, z in enumerate(zones)]
                              or [empty])
    row = np.concatenate([z.runs.row for z in zones] or [empty])
    col0 = np.concatenate([z.runs.col0 for z in zones] or [empty])
    col1 = np.concatenate([z.runs.col1 for z in zones] or [empty])
    yield None
    keep = (row >= 0) & (row < grid.nrows)
    col0, col1 = np.clip(col0, 0, grid.ncols), np.clip(col1, 0, grid.ncols)
    keep &= col1 > col0
    position, row, col0, col1 = position[keep], row[keep], col0[keep], col1[keep]
    order = np.argsort(row, kind="stable")
    yield None
    typed: dict[Counts, _TypedRuns] = {}
    masks: dict[Counts, np.ndarray] = {}
    for counts in _COUNTED:
        chosen = np.array([zone.counts is counts for zone in zones], dtype=bool)
        take = chosen[position]
        if not take.any():
            continue
        mine = _TypedRuns(position[take], row[take], col0[take], col1[take])
        typed[counts] = mine
        union = Runs(mine.row, mine.col0, mine.col1)
        yield None
        mask = np.zeros(grid.shape, dtype=bool)
        for top in range(0, grid.nrows, _INDEX_ROWS):
            stop = min(top + _INDEX_ROWS, grid.nrows)
            mask[top:stop] = union.between_rows(top, stop - 1).mask(
                (stop - top, grid.ncols), (top, 0))
            yield None
        masks[counts] = mask
    return ZoneIndex(grid, zones, position[order], row[order], col0[order], col1[order],
                     MappingProxyType(typed), MappingProxyType(masks))


def zone_index(grid: Grid, zones: Sequence[CheckZone]) -> ZoneIndex:
    """:func:`zone_index_steps` de una vez."""
    return _drain(zone_index_steps(grid, zones))


# --- A7: por bandas ----------------------------------------------------------------------------


def _thickness(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise ValueError(f"el espesor mínimo de verificación es un número, no {value!r}")
    value = float(value)
    if not (math.isfinite(value) and 0.0 <= value <= _MAX_THICKNESS_M):
        raise ValueError("el espesor mínimo de verificación está entre 0 y "
                         f"{_MAX_THICKNESS_M:g} m, no {value!r}")
    return value


def _band(value: np.ndarray | float, rows: int, ncols: int) -> np.ndarray:
    if isinstance(value, int | float | np.integer | np.floating):
        return np.full((rows, ncols), float(value), dtype=np.float64)
    band = np.asarray(value, dtype=np.float64)
    if band.shape != (rows, ncols):
        raise ValueError(f"una banda de {rows} × {ncols} celdas, no de forma {band.shape}")
    return band


class Checker:
    """**A7**: una final frente a la partida, por bandas de filas (:meth:`add`, de norte a sur o
    en cualquier orden, cada fila una vez) y el resultado (:meth:`result`, o :meth:`result_steps`
    por pasos). Con ``index`` (:func:`zone_index`), el de las demás finales de la misma
    verificación: se hace una vez."""

    def __init__(self, grid: Grid, zones: Sequence[CheckZone], min_thickness_m: float, *,
                 index: ZoneIndex | None = None) -> None:
        if not isinstance(grid, Grid):
            raise TypeError(f"se esperaba una Grid, no {type(grid).__name__}")
        zones = tuple(zones)
        if index is None:
            index = zone_index(grid, zones)
        elif index.zones != zones or not index.grid.same_geometry(grid):
            raise ValueError("el índice de recintos no es el de esta rejilla y estos recintos")
        self.grid = grid
        self.zones = zones
        self.index = index
        self.threshold = _thickness(min_thickness_m)
        count = len(zones)
        self._cut = np.zeros(count, np.float64)
        self._fill = np.zeros(count, np.float64)
        self._cut_cells = np.zeros(count, np.int64)
        self._fill_cells = np.zeros(count, np.int64)
        self._moved = np.zeros(count, np.int64)
        self._nodata = np.zeros(count, np.int64)
        # A12: el corte de terreno y el de acopios de los recintos de ``Counts.CUT_TERRAIN``.
        self._terrain = np.zeros(count, np.float64)
        self._terrain_cells = np.zeros(count, np.int64)
        self._stock = np.zeros(count, np.float64)
        self._has_terrain = any(zone.counts is Counts.CUT_TERRAIN for zone in zones)
        self._violations: np.ndarray | None = None
        self._terrain_field: np.ndarray | None = None
        self._same = True

    def add(self, top: int, start: np.ndarray | float, final: np.ndarray | float,
            base: np.ndarray | None = None) -> None:
        """Acumula la banda de filas desde ``top`` de la partida y de la final (float64, NaN sin
        dato; o una cota constante) y, si se da, la de la base de los acopios (A12: su cota en las
        celdas de sus huellas, NaN sin dato; de la forma de las otras). Sin base, o sin recintos
        de :attr:`Counts.CUT_TERRAIN`, es lo de siempre."""
        grid = self.grid
        shapes = [np.shape(v) for v in (start, final) if np.ndim(v) == 2]
        if not shapes:
            raise ValueError("al menos una de las dos superficies es una rejilla")
        rows = int(shapes[0][0])
        if not (0 <= top and top + rows <= grid.nrows):
            raise ValueError(f"la banda de las filas {top}–{top + rows} no está en la rejilla")
        start_band = _band(start, rows, grid.ncols)
        final_band = _band(final, rows, grid.ncols)
        base_band = None if base is None else _band(base, rows, grid.ncols)
        if self._same and not np.array_equal(start_band, final_band, equal_nan=True):
            self._same = False
        valid = np.isfinite(start_band) & np.isfinite(final_band)
        with np.errstate(invalid="ignore"):
            difference = np.where(valid, start_band - final_band, 0.0)
        cut = valid & (difference > self.threshold)
        fill = valid & (-difference > self.threshold)
        shared = self.index
        first = int(np.searchsorted(shared.row, top, side="left"))
        last = int(np.searchsorted(shared.row, top + rows, side="left"))
        if first == last:
            return
        index = shared.position[first:last]
        local = shared.row[first:last] - top
        col0, col1 = shared.col0[first:last], shared.col1[first:last]
        count = len(self.zones)

        def run_sums(values: np.ndarray) -> np.ndarray:
            sums = np.zeros((rows, grid.ncols + 1), dtype=values.dtype)
            np.cumsum(values, axis=1, out=sums[:, 1:])
            return sums[local, col1] - sums[local, col0]

        def add_to(target: np.ndarray, values: np.ndarray) -> None:
            target += np.bincount(index, weights=values, minlength=count).astype(target.dtype)

        cut_values = np.where(cut, difference, 0.0)
        cut_sums = run_sums(cut_values)
        add_to(self._cut, cut_sums)
        add_to(self._fill, run_sums(np.where(fill, -difference, 0.0)))
        cut_cells = run_sums(cut.astype(np.int64))
        fill_cells = run_sums(fill.astype(np.int64))
        add_to(self._cut_cells, cut_cells)
        add_to(self._fill_cells, fill_cells)
        add_to(self._moved, cut_cells + fill_cells)  # el corte y el relleno no comparten celda
        add_to(self._nodata, run_sums((~valid).astype(np.int64)))
        # A12: R = mín(partida, base) donde hay base y R = partida donde no. Sin base en la banda
        # (o sin recintos de terreno), el corte de terreno es el corte: las mismas sumas.
        terrain_difference, terrain_cut = difference, cut
        if self._has_terrain:
            present = None if base_band is None else np.isfinite(base_band)
            if present is not None and present.any():
                with np.errstate(invalid="ignore"):
                    reference = np.fmin(start_band, np.where(present, base_band, np.nan))
                    terrain_difference = np.where(valid, reference - final_band, 0.0)
                terrain_cut = valid & (terrain_difference > self.threshold)
                terrain_values = np.where(terrain_cut, terrain_difference, 0.0)
                add_to(self._terrain, run_sums(terrain_values))
                add_to(self._terrain_cells, run_sums(terrain_cut.astype(np.int64)))
                add_to(self._stock, run_sums(cut_values - terrain_values))
            else:
                add_to(self._terrain, cut_sums)
                add_to(self._terrain_cells, cut_cells)
        self._mark(top, rows, cut, fill, difference, terrain_cut, terrain_difference)

    def _mark(self, top: int, rows: int, cut: np.ndarray, fill: np.ndarray,
              difference: np.ndarray, terrain_cut: np.ndarray,
              terrain_difference: np.ndarray) -> None:
        """Marca en la rejilla de incumplimientos las celdas de la banda que incumplen en algún
        recinto: ``final − partida`` (``−d``) donde incumple un recinto que cuenta todo el
        movimiento (el corte, el relleno o cualquiera) y ``final − R`` donde solo incumple uno de
        terreno (A12); las demás, NaN. Los recintos de terreno, además, llevan su propia rejilla
        (``final − R``) para sus grupos, que no se mezcla con la de contar todo."""
        full: np.ndarray | None = None
        terrain: np.ndarray | None = None
        for counts, mask in self.index.masks.items():
            if counts is Counts.CUT_TERRAIN:
                terrain = mask[top:top + rows] & terrain_cut
                continue
            if counts is Counts.CUT:
                wanted = cut
            elif counts is Counts.FILL:
                wanted = fill
            else:
                wanted = cut | fill
            part = mask[top:top + rows] & wanted
            full = part if full is None else full | part
        has_full = full is not None and bool(full.any())
        has_terrain = terrain is not None and bool(terrain.any())
        if not (has_full or has_terrain):
            return
        if self._violations is None:
            self._violations = np.full(self.grid.shape, np.nan, dtype=np.float64)
        if not has_terrain:
            self._violations[top:top + rows] = np.where(full, -difference, np.nan)
            return
        if self._terrain_field is None:
            self._terrain_field = np.full(self.grid.shape, np.nan, dtype=np.float64)
        only = np.where(terrain, -terrain_difference, np.nan)
        self._terrain_field[top:top + rows] = only
        self._violations[top:top + rows] = (
            np.where(full, -difference, only) if has_full else only)

    def result(self, *, start_name: str = "") -> FinalCheck:
        """Lo de cada recinto y los grupos que incumplen (:class:`FinalCheck`)."""
        return _drain(self.result_steps(start_name=start_name))

    def result_steps(self, *, start_name: str = ""
                     ) -> Generator[None, None, FinalCheck]:
        """:meth:`result` por pasos: cada unidad es una porción corta del trabajo (unas
        :data:`_CHUNK_ROWS` filas, :data:`_RUNS_PER_UNIT` tramos o :data:`_CELLS_PER_UNIT`
        celdas). Cerrarlo a mitad no deja nada."""
        area = self.grid.cell_area
        totals = []
        for position, zone in enumerate(self.zones):
            cut = float(self._cut[position]) * area
            fill = float(self._fill[position]) * area
            counted_cells = {Counts.CUT: int(self._cut_cells[position]),
                             Counts.CUT_TERRAIN: int(self._terrain_cells[position]),
                             Counts.FILL: int(self._fill_cells[position]),
                             Counts.ANY: int(self._moved[position])}.get(zone.counts, 0)
            counted = {Counts.CUT: cut, Counts.CUT_TERRAIN: float(self._terrain[position]) * area,
                       Counts.FILL: fill, Counts.ANY: cut + fill}.get(zone.counts, 0.0)
            weighted = None
            if zone.counts is Counts.AVOID:
                counted = cut + fill
                weighted = counted * float(zone.weight if zone.weight is not None else 0.0)
            stockpile = (float(self._stock[position]) * area
                         if zone.counts is Counts.CUT_TERRAIN else 0.0)
            totals.append(ZoneTotals(
                zone.code, zone.ctype, zone.counts, cut, fill,
                int(self._moved[position]) * area, int(self._nodata[position]) * area,
                counted, zone.weight, weighted, verdict(zone, counted_cells), stockpile))
        yield None
        groups = yield from self._group_steps()
        notices = (Notice("res.same_surface", {"surface": start_name}),) if self._same else ()
        violations = self._violations
        if violations is not None:
            violations.flags.writeable = False
        return FinalCheck(tuple(totals), tuple(groups), self._same, notices, violations)

    def _group_steps(self) -> Generator[None, None, list[Group]]:
        field_ = self._violations
        if field_ is None:
            return []
        positions: list[np.ndarray] = []
        groups: list[Group] = []
        for counts in _COUNTED:
            # Los de terreno se agrupan por su rejilla (``final − R``), no por la de contar todo.
            source = self._terrain_field if counts is Counts.CUT_TERRAIN else field_
            if source is None:
                continue
            mine, found = yield from _type_groups(self.index, source, counts, self.threshold)
            positions.append(mine)
            groups += found
        if not groups:
            return []
        order = np.argsort(np.concatenate(positions), kind="stable")  # recinto, y su orden
        yield None
        return [groups[i] for i in order.tolist()]


# --- A10: grupos -------------------------------------------------------------------------------


def _touching(key_row: np.ndarray, col0: np.ndarray, col1: np.ndarray, width: int
              ) -> tuple[np.ndarray, np.ndarray]:
    """Las parejas (izquierda, derecha) de tramos de filas seguidas que se solapan, por búsqueda
    binaria. ``key_row`` es la «fila» de cada tramo (los de otro recinto, otra fila) y los tramos
    vienen ordenados por ``(key_row, col0)``; ``width`` es mayor que cualquier columna."""
    key_end = key_row * width + col1
    key_start = key_row * width + col0
    low = np.searchsorted(key_end, (key_row + 1) * width + col0, side="right")
    high = np.searchsorted(key_start, (key_row + 1) * width + col1, side="left")
    many = np.maximum(high - low, 0)
    left = np.repeat(np.arange(col0.size), many)
    offsets = np.arange(int(many.sum())) - np.repeat(np.cumsum(many) - many, many)
    right = np.repeat(low, many) + offsets
    return left, right


def _components_steps(count: int, left: np.ndarray, right: np.ndarray
                      ) -> Generator[None, None, np.ndarray]:
    """La etiqueta de cada uno de ``count`` nodos unidos por las parejas ``(left, right)``: el
    menor índice de su componente. Saltos de puntero (Shiloach–Vishkin, 1982): cada pareja une
    las raíces de sus extremos en la menor y se comprime el árbol, hasta que ninguna pareja une
    dos raíces distintas; las parejas que ya están unidas dejan de mirarse. Una unidad por
    vuelta y por salto."""
    label = np.arange(count)
    while left.size:
        a, b = label[left], label[right]
        live = a != b
        if not live.any():
            break
        if not live.all():
            left, right, a, b = left[live], right[live], a[live], b[live]
        least = np.minimum(a, b)
        np.minimum.at(label, a, least)
        np.minimum.at(label, b, least)
        yield None
        while True:
            jumped = label[label]
            if np.array_equal(jumped, label):
                break
            label = jumped
            yield None
    return label


def label_groups(rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, int]:
    """**A10** (D-41): las celdas ``(rows[i], cols[i])`` (distintas, índices ≥ 0) agrupadas por
    contigüidad de lado (4-conexión). Devuelve la etiqueta de cada celda (0…n−1, numeradas por
    su primera celda de norte a sur y de oeste a este) y el número de grupos ``n``."""
    rows = np.asarray(rows, dtype=np.int64).ravel()
    cols = np.asarray(cols, dtype=np.int64).ravel()
    if rows.shape != cols.shape:
        raise ValueError("tantas filas como columnas")
    if rows.size == 0:
        return np.zeros(0, np.int64), 0
    if rows.min() < 0 or cols.min() < 0:
        raise ValueError("los índices de celda no son negativos")
    order = np.lexsort((cols, rows))
    r, c = rows[order], cols[order]
    if np.any((r[1:] == r[:-1]) & (c[1:] == c[:-1])):
        raise ValueError("celdas repetidas")
    # Tramos de fila: una celda empieza tramo si cambia la fila o salta la columna.
    starts = np.r_[True, (r[1:] != r[:-1]) | (c[1:] != c[:-1] + 1)]
    run_of_cell = np.cumsum(starts) - 1
    first = np.flatnonzero(starts)
    run_row = r[first]
    run_col0 = c[first]
    run_col1 = np.r_[c[np.flatnonzero(starts)[1:] - 1], c[-1]] + 1
    # Parejas de tramos de filas seguidas que se solapan y sus componentes (saltos de puntero).
    width = int(max(int(run_col1.max()), 1)) + 1
    left, right = _touching(run_row, run_col0, run_col1, width)
    label = _drain(_components_steps(first.size, left, right))
    roots, run_label = np.unique(label, return_inverse=True)
    result = np.empty(rows.size, np.int64)
    result[order] = run_label[run_of_cell]
    return result, int(roots.size)


def _type_groups(shared: ZoneIndex, field_: np.ndarray, counts: Counts, threshold: float
                 ) -> Generator[None, None, tuple[np.ndarray, list[Group]]]:
    """Los grupos que incumplen en los recintos del modo de contar ``counts`` (T36), en el orden
    (recinto, primera celda), y el recinto de cada uno.

    De ``field_`` (la rejilla de incumplimientos: ``final − partida`` donde algún recinto
    incumple, NaN en las demás) salen los tramos de las celdas que cuentan en este modo (el corte,
    ``field < −e``; el relleno, ``field > e``; cualquier movimiento, las que no son NaN: una
    celda de la rejilla en un recinto del modo cuenta si y solo si incumple en él; el corte de
    terreno, como el corte pero de su propia rejilla, ``final − R``, A12). Cada tramo
    de un recinto se cruza con ellos (búsqueda binaria) y da los tramos de las celdas que
    incumplen; los de filas seguidas que se solapan, en el mismo recinto, son del mismo grupo
    (:func:`_components_steps`). Un grupo son sus tramos; sus celdas, sus filas y sus columnas, se
    sacan por trozos de unas :data:`_CELLS_PER_UNIT` celdas. Las sumas de enteros (celdas,
    centro) son exactas y el volumen es ``math.fsum`` de sus espesores, como cuando se agrupaban
    las celdas una a una: el resultado es el mismo bit a bit."""
    grid = shared.grid
    typed = shared.typed.get(counts)
    nothing: tuple[np.ndarray, list[Group]] = (np.zeros(0, np.int64), [])
    if typed is None:
        return nothing
    width = grid.ncols + 1
    # 1. Los tramos de las celdas que cuentan en este modo.
    pieces = []
    for top in range(0, grid.nrows, _CHUNK_ROWS):
        part = field_[top:top + _CHUNK_ROWS]
        if counts is Counts.CUT or counts is Counts.CUT_TERRAIN:
            wanted = part < -threshold
        elif counts is Counts.FILL:
            wanted = part > threshold
        else:
            wanted = ~np.isnan(part)
        local, begin, end = _mask_runs(wanted)
        if local.size:
            pieces.append((local + top, begin, end))
        yield None
    if not pieces:
        return nothing
    wanted_row, wanted_begin, wanted_end = (np.concatenate([piece[k] for piece in pieces])
                                            for k in range(3))
    wanted_end_key = wanted_row * width + wanted_end
    wanted_begin_key = wanted_row * width + wanted_begin
    # 2. Los tramos de cada recinto cruzados con ellos: los tramos de las celdas que incumplen.
    found = []
    for first in range(0, typed.row.size, _RUNS_PER_UNIT):
        part_slice = slice(first, first + _RUNS_PER_UNIT)
        z_row, z_begin = typed.row[part_slice], typed.col0[part_slice]
        z_end, z_position = typed.col1[part_slice], typed.position[part_slice]
        low = np.searchsorted(wanted_end_key, z_row * width + z_begin, side="right")
        high = np.searchsorted(wanted_begin_key, z_row * width + z_end, side="left")
        many = np.maximum(high - low, 0)
        total = int(many.sum())
        if total:
            left = np.repeat(np.arange(z_row.size), many)
            right = np.repeat(low, many) + (np.arange(total)
                                            - np.repeat(np.cumsum(many) - many, many))
            found.append((z_position[left], z_row[left],
                          np.maximum(z_begin[left], wanted_begin[right]),
                          np.minimum(z_end[left], wanted_end[right])))
        yield None
    if not found:
        return nothing
    v_position, v_row, v_begin, v_end = (np.concatenate([item[k] for item in found])
                                         for k in range(4))
    del found, pieces, wanted_row, wanted_begin, wanted_end, wanted_end_key, wanted_begin_key
    # 3. Los grupos: parejas de tramos de filas seguidas del mismo recinto que se solapan.
    count = v_row.size
    left, right = _touching(v_position * (grid.nrows + 1) + v_row, v_begin, v_end, width)
    yield None
    label = yield from _components_steps(count, left, right)
    del left, right
    is_root = label == np.arange(count)
    group_of_root = np.cumsum(is_root) - 1
    group = group_of_root[label]  # el número de grupo de cada tramo (por su primer tramo)
    groups_n = int(group_of_root[-1]) + 1
    order = np.argsort(group, kind="stable")  # los tramos de cada grupo, juntos y en su orden
    yield None
    s_row, s_begin, s_end = v_row[order], v_begin[order], v_end[order]
    s_position = v_position[order]
    lens = s_end - s_begin
    runs_in = np.bincount(group, minlength=groups_n)
    first_run = np.cumsum(runs_in) - runs_in
    end_cells = np.cumsum(lens)
    run_start = end_cells - lens
    cells_n = np.add.reduceat(lens, first_run).tolist()
    sum_cols = np.add.reduceat((s_begin + s_end - 1) * lens // 2, first_run).tolist()
    sum_rows = np.add.reduceat(s_row * lens, first_run).tolist()
    min_col = np.minimum.reduceat(s_begin, first_run).tolist()
    max_col = (np.maximum.reduceat(s_end, first_run) - 1).tolist()
    min_row = s_row[first_run].tolist()
    max_row = s_row[first_run + runs_in - 1].tolist()
    group_position = s_position[first_run]
    group_end = first_run + runs_in
    codes = [zone.code for zone in shared.zones]
    group_code = [codes[position] for position in group_position.tolist()]
    yield None
    # 4. Las celdas de cada grupo (filas, columnas y espesores) por trozos de tramos; un grupo
    # que cruza dos trozos acumula sus partes (a lo sumo hay uno abierto).
    area = grid.cell_area
    flat = field_.reshape(-1)
    built: list[Group] = []
    carry_rows: list[np.ndarray] = []
    carry_cols: list[np.ndarray] = []
    carry_values: list[float] = []
    carry_max = 0.0
    begin_run = 0
    while begin_run < count:
        base = int(run_start[begin_run])
        end_run = max(min(int(np.searchsorted(end_cells, base + _CELLS_PER_UNIT, side="right")),
                          begin_run + _GROUP_RUNS_PER_UNIT), begin_run + 1)
        lens_c = lens[begin_run:end_run]
        total_c = int(lens_c.sum())
        rows_c = np.repeat(s_row[begin_run:end_run], lens_c)
        cols_c = (np.arange(total_c) - np.repeat(run_start[begin_run:end_run] - base, lens_c)
                  + np.repeat(s_begin[begin_run:end_run], lens_c))
        values_c = np.abs(flat[rows_c * grid.ncols + cols_c])
        # Las partes de grupo de este trozo: desde el primer grupo con tramos a partir de
        # begin_run hasta el último que empieza antes de end_run.
        first_in = int(np.searchsorted(group_end, begin_run, side="right"))
        last_in = int(np.searchsorted(first_run, end_run, side="left"))
        part_from = np.maximum(first_run[first_in:last_in], begin_run)
        part_to = np.minimum(group_end[first_in:last_in], end_run)
        part_a = run_start[part_from] - base
        part_b = end_cells[part_to - 1] - base
        part_max = np.maximum.reduceat(values_c, part_a).tolist()
        starts_here = (first_run[first_in:last_in] >= begin_run).tolist()
        ends_here = (group_end[first_in:last_in] <= end_run).tolist()
        for k, (a, b) in enumerate(zip(part_a.tolist(), part_b.tolist(), strict=True)):
            g = first_in + k
            if starts_here[k]:
                carry_rows, carry_cols = [rows_c[a:b]], [cols_c[a:b]]
                carry_values, carry_max = values_c[a:b].tolist(), part_max[k]
            else:
                carry_rows.append(rows_c[a:b])
                carry_cols.append(cols_c[a:b])
                carry_values += values_c[a:b].tolist()
                carry_max = max(carry_max, part_max[k])
            if not ends_here[k]:
                continue
            rows_g = carry_rows[0] if len(carry_rows) == 1 else np.concatenate(carry_rows)
            cols_g = carry_cols[0] if len(carry_cols) == 1 else np.concatenate(carry_cols)
            cells = cells_n[g]
            mean_col = float(sum_cols[g]) / cells
            mean_row = float(sum_rows[g]) / cells
            built.append(Group(
                group_code[g], cells, cells * area, math.fsum(carry_values) * area,
                float(carry_max),
                (grid.west + (mean_col + 0.5) * grid.dx, grid.north - (mean_row + 0.5) * grid.dy),
                (grid.west + min_col[g] * grid.dx, grid.north - (max_row[g] + 1) * grid.dy,
                 grid.west + (max_col[g] + 1) * grid.dx, grid.north - min_row[g] * grid.dy),
                _readonly(rows_g), _readonly(cols_g)))
            carry_rows, carry_cols, carry_values = [], [], []
        begin_run = end_run
        yield None
    return group_position, built


def _readonly(values: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(values, dtype=np.int64)
    values.flags.writeable = False
    return values


def check(grid: Grid, zones: Sequence[CheckZone], start: np.ndarray | float,
          final: np.ndarray | float, min_thickness_m: float, *, band_rows: int = BAND_ROWS,
          start_name: str = "", base: np.ndarray | None = None) -> FinalCheck:
    """Una final frente a la partida de una vez (:class:`Checker` por bandas de ``band_rows``
    filas); ``start`` y ``final``, rejillas de forma ``grid.shape`` o cotas constantes; ``base``,
    la rejilla de la base de los acopios (A12), opcional."""
    if band_rows < 1:
        raise ValueError(f"una banda tiene al menos una fila, no {band_rows}")
    checker = Checker(grid, zones, min_thickness_m)
    for top in range(0, grid.nrows, band_rows):
        stop = min(top + band_rows, grid.nrows)
        checker.add(top, _rows_of(start, top, stop), _rows_of(final, top, stop),
                    None if base is None else np.asarray(base, dtype=np.float64)[top:stop])
    return checker.result(start_name=start_name)


def _rows_of(value: np.ndarray | float, top: int, stop: int) -> np.ndarray | float:
    if np.ndim(value) == 0:
        return float(value)  # type: ignore[arg-type]
    return np.asarray(value, dtype=np.float64)[top:stop]


def lowest_base(bands: Sequence[np.ndarray]) -> np.ndarray | None:
    """La base de varias detecciones sobre la misma partida (P-10): en cada celda, la **menor** de
    las que tienen dato (el lado seguro: cuenta más corte de terreno) y NaN donde ninguna lo tiene.
    ``None`` sin ninguna; con una sola, esa misma banda; las bandas de la misma forma, o
    :class:`ValueError`. No modifica ninguna."""
    found: np.ndarray | None = None
    for band in bands:
        band = np.asarray(band, dtype=np.float64)
        if found is None:
            found = band
        elif band.shape != found.shape:
            raise ValueError(f"las bases de los acopios son de la misma forma, no {found.shape} "
                             f"y {band.shape}")
        else:
            found = np.fmin(found, band)
    return found


# --- La petición -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComplianceRequest:
    """Lo que pide una verificación (RF-012-21; D-28, D-40): su nombre, la superficie de
    partida, las finales (de 1 a :data:`MAX_FINALS`, distintas), las máscaras de la versión (al
    día, ``gis.masks.access``) y el espesor mínimo de verificación (m, D-6) y, opcional, las
    bases de los acopios detectados al día sobre la partida (``bases``, A12: una rejilla por
    detección, que se combinan con :func:`lowest_base`; vacío, sin base: la verificación de
    siempre). Una petición incoherente es un error del programa (:class:`ValueError`)."""

    name: str
    start: SurfaceRef
    finals: tuple[SurfaceRef, ...]
    masks: MaskSet
    min_thickness_m: float
    bases: tuple[SurfaceRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"una verificación tiene nombre, no {self.name!r}")
        finals = tuple(self.finals)
        if not 1 <= len(finals) <= MAX_FINALS:
            raise ValueError(f"de 1 a {MAX_FINALS} superficies finales, no {len(finals)}")
        if len(set(finals)) != len(finals):
            raise ValueError("una superficie final repetida")
        if not all(isinstance(item, SurfaceRef) for item in (self.start, *finals)):
            raise ValueError("las superficies son SurfaceRef")
        if not isinstance(self.masks, MaskSet):
            raise ValueError(f"las máscaras son un MaskSet, no {type(self.masks).__name__}")
        bases = tuple(self.bases)
        if not all(isinstance(item, SurfaceRef) for item in bases):
            raise ValueError("las bases de los acopios son SurfaceRef")
        if any(item.elevation is not None for item in bases):
            raise ValueError("la base de unos acopios es una rejilla, no una cota constante")
        if len(set(bases)) != len(bases):
            raise ValueError("una base de acopios repetida")
        object.__setattr__(self, "bases", bases)
        object.__setattr__(self, "finals", finals)
        object.__setattr__(self, "min_thickness_m", _thickness(self.min_thickness_m))

    def same_as_start(self, position: int) -> bool:
        """Si la final ``position`` es la misma superficie que la partida."""
        return self.finals[position] == self.start
