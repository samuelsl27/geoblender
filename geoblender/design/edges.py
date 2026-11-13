# SPDX-License-Identifier: GPL-3.0-or-later
"""El borde de un diseño con el terreno no afectado: la transición y el salto creado (spec 014,
T26 y T27; HU-014-5; RF-014-19 a RF-014-21; plan 014 A10, A11, §5.3.1).

- :func:`transition_steps` (A10): la **transición** de una superficie de diseño ``S`` con el
  terreno no afectado del borde de su dominio de trabajo ``D``. Las semillas son la superficie de
  partida ``z`` en el **anillo exterior de una celda** de ``D`` (``dilate_square(D, 1) ∧ ¬D``,
  como la coronación, con dato de terreno); con el ángulo de transición ``θ`` (el parámetro
  ``des.edge.transition_deg``, sin valor por defecto: D-9) y la envolvente de la 013, ``T↓ =
  ENV↓(·, tan θ)`` y ``T↑ = ENV↑(·, tan θ)``; dentro de ``D``, ``S' = mín(máx(S, T↓), T↑)`` (ninguna
  pared más empinada que ``θ`` hacia el terreno no afectado, ni hacia abajo ni hacia arriba);
  fuera, ``S``. El volumen de la transición es ``Σ |S' − S| · área de celda``
  (:class:`Transition`).

  Ninguna pareja del borde (una celda de ``D`` y su vecina fuera, con dato de terreno) queda más
  empinada que ``θ`` siempre que el propio terreno del anillo no lo sea: los pesos de vecino del
  *chamfer* 5×5 son menores que la distancia (ADR-0014) y la euclídea exacta es la distancia.
- :func:`created_steps` (A11): el **salto creado** en el borde de un diseño. Son del borde las
  parejas de celdas vecinas (4 vecinos) con una celda **movida** (en el dominio, con dato en las
  dos superficies y ``|S − z|`` mayor que el espesor mínimo de la 012) y la otra no (con dato en
  las dos); en cada una, ``c = |S_a − S_b| − |z_a − z_b|``: el salto con el diseño menos el que ya
  tenía el terreno, que nunca cuenta (error 48). El informe (:class:`EdgeReport`) da las parejas,
  las que pasan del salto admitido, el máximo con su lugar y los **tramos** (:class:`EdgeStretch`),
  y avisa si queda dentro del salto admitido menos del porcentaje admitido (RF-014-21, D-6).
- :func:`edge_transition_steps` (T28; RF-014-19 a RF-014-21): lo que calcula la operación
  ``des.edge_transition`` («Transiciones con el terreno no afectado») con una superficie de diseño:
  su dominio (:func:`transition_domain`: las celdas que **mueve el diseño** donde las máscaras
  admiten mover el terreno, de modo que su anillo es el terreno no afectado del borde del diseño,
  el mismo borde en que A11 mide el salto creado), la transición en él (A10), el salto creado de la
  superficie nueva (A11), sus tres cifras (:func:`edge_transition_figures`) y el aviso de RF-014-21
  (:func:`edge_notices`), en un :class:`EdgeTransition`.

Python puro con numpy (nivel 8): no importa ``reserves`` ni ``bl``; no escribe nada.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import format_value
from . import pipeline, provenance
from .envelopes import (
    BLOCK_CELLS,
    BLOCK_GROUP,
    CELLS_PER_UNIT,
    EVALS_PER_UNIT,
    SlopeField,
    _exact_work,
    chamfer_units,
    constant_slope,
)
from .grids import Labels, _label_units, dilate_square
from .messages import render
from .model import Direction, Metric
from .params import EDGE_MAX_STEP, EDGE_MIN_SHARE, EDGE_TRANSITION, check_quarry_param
from .preview import Notice
from .report import _thickness, _units
from .seeds import pace_progress

__all__ = [
    "EDGE_PHASE",
    "PAIR_CELLS_PER_UNIT",
    "TRANSITION_NAME",
    "EdgeReport",
    "EdgeStretch",
    "EdgeTransition",
    "Transition",
    "created_steps",
    "edge_notices",
    "edge_transition_figures",
    "edge_transition_steps",
    "transition_domain",
    "transition_steps",
]

TRANSITION_NAME = "transición con el terreno no afectado"
"""El nombre de las envolventes de la transición en los mensajes de la 013 (RF-013-15)."""


@dataclass(frozen=True, slots=True, eq=False)
class Transition:
    """La **transición** del borde (A10, RF-014-19): ``grid``, la superficie ``S'`` (m, float64,
    nueva; ``NaN`` donde ``S`` no tiene dato); el volumen de la transición ``volume_m3`` (``Σ |S' −
    S| · área de celda``, lo que sube más lo que baja), las ``cells`` que cambian, el ángulo de
    transición ``angle_deg`` (°) y ``cell_area_m2``, el área de una celda."""

    grid: np.ndarray
    volume_m3: float
    cells: int
    angle_deg: float
    cell_area_m2: float

    @property
    def area_m2(self) -> float:
        """El área de las celdas que cambian (m²)."""
        return self.cells * self.cell_area_m2


def _same_shape(name: str, values: np.ndarray, shape: tuple[int, ...]) -> None:
    """``ValueError`` (error del programa) si ``values`` no es de la forma de la rejilla."""
    if values.shape != shape:
        raise ValueError(f"{name} {values.shape} no es de la forma de la rejilla {shape}")


def _envelope_work(seed: np.ndarray, geometry: Grid, slope: SlopeField, metric: Metric,
                   way: Direction, name: str) -> Generator[None, None, np.ndarray]:
    """Las unidades de la envolvente de la 013 de ``seed`` en el sentido ``way`` con ``slope`` y
    ``metric`` (la euclídea exacta, con una pendiente constante), con ``name`` en sus mensajes: su
    rejilla, o ``+inf`` (``−inf`` en la descendente) en toda la rejilla sin ninguna semilla."""
    if not np.isfinite(seed).any():
        yield None
        return np.full(seed.shape, np.inf if way is Direction.UP else -np.inf)
    if metric is Metric.EXACT:
        found = yield from _exact_work(seed, geometry, slope, way, name, CELLS_PER_UNIT,
                                       EVALS_PER_UNIT, BLOCK_CELLS, BLOCK_GROUP)
    else:
        found = yield from chamfer_units(seed, geometry, slope, way, name=name)
    return found.grid


def _transition_units(surface: np.ndarray, start: np.ndarray, domain: np.ndarray,
                      geometry: Grid, degrees: float, metric: Metric, name: str
                      ) -> Generator[None, None, Transition]:
    """Las unidades de :func:`transition_steps`: las dos envolventes desde el anillo y la
    superficie nueva con lo que cambia, por bandas de filas."""
    with np.errstate(invalid="ignore"):
        ring = dilate_square(domain, 1) & ~domain & np.isfinite(start)
    seed = np.where(ring, start, np.nan)
    slope = constant_slope(degrees)
    yield None
    lower = yield from _envelope_work(seed, geometry, slope, metric, Direction.DOWN, name)
    upper = yield from _envelope_work(seed, geometry, slope, metric, Direction.UP, name)
    design = surface.copy()
    step = max(1, CELLS_PER_UNIT // max(geometry.ncols, 1))
    sums: list[float] = []
    cells = 0
    for first in range(0, geometry.nrows, step):
        rows = slice(first, first + step)
        before = surface[rows]
        with np.errstate(invalid="ignore"):
            joined = np.minimum(np.maximum(before, lower[rows]), upper[rows])
            moved = np.where(domain[rows] & np.isfinite(before), np.abs(joined - before), 0.0)
        changed = moved > 0.0
        design[rows] = np.where(changed, joined, before)
        sums.append(float(moved.sum()))
        cells += int(np.count_nonzero(changed))
        yield None
    return Transition(design, math.fsum(sums) * geometry.cell_area, cells, degrees,
                      geometry.cell_area)


def transition_steps(surface: np.ndarray, start: np.ndarray, domain: np.ndarray, geometry: Grid,
                     angle_deg: float | None, *, metric: Metric | str = Metric.CHAMFER5,
                     name: str = "", budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A10** (RF-014-19): la transición de la superficie de diseño ``surface`` (``S``, m,
    float64, de la forma de ``geometry``) con el terreno no afectado del borde de su dominio de
    trabajo ``domain`` (``D``, una máscara de ``geometry``, p. ej. ``DomainSet.mask``), sobre la
    superficie de partida ``start`` (``z``, m), con el ángulo de transición ``angle_deg`` (°, el
    parámetro ``des.edge.transition_deg``, sin factor de malla) y la ``metric`` de la 013 (*chamfer*
    5×5 o euclídea exacta), por pasos de ``budget_s`` como mucho: el último ``Progress`` (fase
    ``transition``) lleva la :class:`Transition`.

    Las semillas son ``z`` en el anillo exterior de una celda de ``D`` (Chebyshev) donde tiene
    dato; ``T↓`` y ``T↑``, sus envolventes descendente y ascendente con ``tan θ``; dentro de ``D``
    y donde ``S`` tiene dato, ``S' = mín(máx(S, T↓), T↑)``; en las demás celdas, ``S`` tal cual
    (una celda que ya está entre las dos no cambia ni un bit). Sin anillo con dato no hay
    transición: ``S``, 0 m³.

    Rechazos al llamar: el ángulo, como el parámetro (``check_quarry_param``:
    ``des.quarry_param_missing`` sin valor, D-9; ``des.quarry_param_range`` fuera de (0; 90));
    ``ValueError`` (error del programa) si una rejilla no es de la forma de ``geometry`` o la
    métrica no es de la 013. Al avanzar, los de la envolvente de la 013 (RF-013-15), con ``name``
    («<superficie> (transición con el terreno no afectado)»). Ninguna entrada se modifica y no se
    escribe nada; cerrar el generador a mitad no deja nada."""
    degrees = float(check_quarry_param(EDGE_TRANSITION, angle_deg))
    shape = geometry.shape
    design = np.asarray(surface, dtype=np.float64)
    base = np.asarray(start, dtype=np.float64)
    inside = np.asarray(domain, dtype=bool)
    for label, grid in (("la superficie de diseño", design), ("la superficie de partida", base),
                        ("el dominio de trabajo", inside)):
        _same_shape(label, grid, shape)
    way = Metric(metric)
    label = f"{name} ({TRANSITION_NAME})" if name else TRANSITION_NAME
    work = _transition_units(design, base, inside, geometry, degrees, way, label)
    return pace_progress(work, budget_s, phase="transition",
                         running="Calculando la transición con el terreno no afectado…",
                         finished="Transición con el terreno no afectado calculada")


# --- El salto creado (T27; A11) ------------------------------------------------------------------

PAIR_CELLS_PER_UNIT = 200_000
"""Las celdas de una unidad de trabajo del salto creado (una banda de filas con sus parejas)."""
_PAIRS_PER_UNIT = 1 << 18
"""Las parejas que pasan que se reparten entre sus tramos en cada unidad de trabajo."""


@dataclass(frozen=True, slots=True)
class EdgeStretch:
    """Un **tramo** del borde (A11; RF-014-21): una componente 4-conexa de las celdas de las
    parejas cuyo salto creado pasa del admitido, con su número ``stretch`` (desde 1, en el orden de
    su primera celda recorriendo la rejilla fila a fila desde el norte), sus ``pairs``, su mayor
    salto creado ``maximum_m`` (m) y su centro (``x``, ``y``: la media de los puntos medios de sus
    parejas, en coordenadas absolutas, float64)."""

    stretch: int
    pairs: int
    maximum_m: float
    x: float
    y: float


@dataclass(frozen=True, slots=True, eq=False)
class EdgeReport:
    """El **salto creado** en el borde de un diseño (A11; RF-014-20, RF-014-21): las ``pairs`` del
    borde (4 vecinos: una celda movida y la otra no, con dato en las dos superficies) y las que
    tienen un salto creado mayor que el salto admitido ``threshold_m`` (``over``); el mayor salto
    creado de todas, ``maximum_m`` (m; negativo si el diseño solo reduce los saltos que ya tenía el
    terreno; 0 sin parejas), y su lugar (``x``, ``y``: el punto medio de la pareja, absoluto; a
    igual salto, el primero de norte a sur y de oeste a este; ``None`` sin parejas); los
    ``stretches`` (:class:`EdgeStretch`); el porcentaje admitido ``min_share_pct`` (%, el de las
    parejas que tiene que quedar dentro del salto admitido) y el espesor mínimo con que se
    buscaron las celdas movidas (``min_thickness_m``, m)."""

    pairs: int
    over: int
    maximum_m: float
    x: float | None
    y: float | None
    stretches: tuple[EdgeStretch, ...]
    threshold_m: float
    min_share_pct: float
    min_thickness_m: float

    @property
    def over_pct(self) -> float:
        """El porcentaje de las parejas con un salto creado mayor que el admitido (0 sin
        parejas)."""
        return 100.0 * self.over / self.pairs if self.pairs else 0.0

    @property
    def within_pct(self) -> float:
        """El porcentaje de las parejas dentro del salto admitido (100 sin parejas)."""
        return 100.0 * (self.pairs - self.over) / self.pairs if self.pairs else 100.0

    @property
    def warned(self) -> bool:
        """Si se avisa (RF-014-21, D-6): queda dentro del salto admitido **menos** del porcentaje
        admitido de las parejas (con exactamente ese porcentaje, no)."""
        return (self.pairs - self.over) * 100.0 < self.min_share_pct * self.pairs

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """El aviso en ``language``: ``des.edge_created_step`` (el porcentaje de las parejas que
        pasa, las parejas, el salto y el porcentaje admitidos, el máximo y su lugar al cm y los
        tramos) y una nota ``des.edge_stretch`` por tramo; ``()`` si no se avisa."""
        if not self.warned:
            return ()
        found = [render("des.edge_created_step", language=language,
                        share=round(self.over_pct, 2), pairs=self.pairs,
                        threshold=self.threshold_m, admitted=self.min_share_pct,
                        maximum=round(self.maximum_m, 2), x=_place(self.x), y=_place(self.y),
                        stretches=len(self.stretches))]
        found.extend(render("des.edge_stretch", language=language, stretch=item.stretch,
                            pairs=item.pairs, maximum=round(item.maximum_m, 2),
                            x=_place(item.x), y=_place(item.y)) for item in self.stretches)
        return tuple(found)

    @property
    def notices(self) -> tuple[str, ...]:
        """El aviso en español (:meth:`lines`)."""
        return self.lines("es")


def _place(value: float | None) -> float | None:
    """Una coordenada al cm, para un mensaje."""
    return None if value is None else round(value, 2)


def _midpoint(geometry: Grid, key_row: float, key_col: float) -> tuple[float, float]:
    """El punto medio absoluto de una pareja por sus claves de fila y de columna, en medias
    celdas (``2·f + 1`` entre las filas ``f`` y ``f + 1``, ``2·f`` en la fila ``f``; lo mismo en
    columnas), o el centro de varias con la media de sus claves."""
    return (float(geometry.west + (key_col + 1.0) * geometry.dx / 2.0),
            float(geometry.north - (key_row + 1.0) * geometry.dy / 2.0))


@dataclass(slots=True)
class _Found:
    """Lo que se acumula banda a banda: las parejas del borde, el mayor salto creado y su clave, y
    la clave y el salto de las parejas que pasan."""

    pairs: int = 0
    best: float = -math.inf
    best_key: int = -1
    keys: list[np.ndarray] = field(default_factory=list)
    steps: list[np.ndarray] = field(default_factory=list)


def _band_units(design: np.ndarray, start: np.ndarray, domain: np.ndarray, geometry: Grid,
                thickness: float, threshold: float, rows_per_unit: int, marked: np.ndarray,
                found: _Found) -> Generator[None, None, None]:
    """Las parejas del borde por bandas de filas (cada banda con la primera fila de la siguiente,
    para las parejas de norte a sur entre las dos): su salto creado, el mayor y su clave, y las que
    pasan, con sus dos celdas en ``marked``. La clave de una pareja es la de su punto medio,
    ``fila · (2·columnas + 1) + columna`` en medias celdas: ordena de norte a sur y de oeste a
    este."""
    nrows, ncols = geometry.shape
    width = 2 * ncols + 1
    for first in range(0, nrows, rows_per_unit):
        last = min(nrows, first + rows_per_unit)
        stop = min(nrows, last + 1)
        surface = design[first:stop]
        base = start[first:stop]
        with np.errstate(invalid="ignore"):
            valid = np.isfinite(surface) & np.isfinite(base)
            moved = domain[first:stop] & valid & (np.abs(surface - base) > thickness)
        upper, lower = last - first, stop - first - 1
        east = (moved[:upper, :-1] != moved[:upper, 1:]) & valid[:upper, :-1] & valid[:upper, 1:]
        south = (moved[:lower] != moved[1:lower + 1]) & valid[:lower] & valid[1:lower + 1]
        for pairs, (d_row, d_col) in ((east, (0, 1)), (south, (1, 0))):
            rows, cols = np.nonzero(pairs)
            if not rows.size:
                continue
            created = (np.abs(surface[rows, cols] - surface[rows + d_row, cols + d_col])
                       - np.abs(base[rows, cols] - base[rows + d_row, cols + d_col]))
            keys = ((2 * (rows.astype(np.int64) + first) + d_row) * width
                    + 2 * cols.astype(np.int64) + d_col)
            found.pairs += int(rows.size)
            top = float(created.max())
            key = int(keys[created == top].min())
            if top > found.best or (top == found.best and key < found.best_key):
                found.best, found.best_key = top, key
            over = created > threshold
            if over.any():
                marked[rows[over] + first, cols[over]] = True
                marked[rows[over] + first + d_row, cols[over] + d_col] = True
                found.keys.append(keys[over])
                found.steps.append(created[over])
        yield None


def _stretch_units(found: _Found, labels: Labels, geometry: Grid
                   ) -> Generator[None, None, tuple[EdgeStretch, ...]]:
    """Los tramos por trozos de parejas: cada pareja que pasa, en el tramo de su celda del norte o
    del oeste (las dos celdas de una pareja son vecinas), con sus parejas, su máximo y la suma de
    las claves de sus puntos medios."""
    count = labels.count
    if not count:
        return ()
    width = 2 * geometry.ncols + 1
    keys = np.concatenate(found.keys)
    steps = np.concatenate(found.steps)
    pairs = np.zeros(count + 1, dtype=np.int64)
    rows_sum = np.zeros(count + 1)
    cols_sum = np.zeros(count + 1)
    top = np.full(count + 1, -math.inf)
    for first in range(0, keys.size, _PAIRS_PER_UNIT):
        key_rows, key_cols = np.divmod(keys[first:first + _PAIRS_PER_UNIT], width)
        tags = labels.grid[key_rows // 2, key_cols // 2]
        pairs += np.bincount(tags, minlength=count + 1)
        rows_sum += np.bincount(tags, weights=key_rows, minlength=count + 1)
        cols_sum += np.bincount(tags, weights=key_cols, minlength=count + 1)
        np.maximum.at(top, tags, steps[first:first + _PAIRS_PER_UNIT])
        yield None
    stretches = []
    for index in range(1, count + 1):
        total = int(pairs[index])
        x, y = _midpoint(geometry, rows_sum[index] / total, cols_sum[index] / total)
        stretches.append(EdgeStretch(index, total, float(top[index]), x, y))
    return tuple(stretches)


def _created_units(design: np.ndarray, start: np.ndarray, domain: np.ndarray, geometry: Grid,
                   thickness: float, threshold: float, share: float, cells_per_unit: int
                   ) -> Generator[None, None, EdgeReport]:
    """Las unidades de :func:`created_steps`: las parejas por bandas, las componentes de las
    celdas de las que pasan y sus tramos."""
    marked = np.zeros(geometry.shape, dtype=bool)
    found = _Found()
    rows_per_unit = max(1, cells_per_unit // max(geometry.ncols, 1))
    yield from _band_units(design, start, domain, geometry, thickness, threshold, rows_per_unit,
                           marked, found)
    labels: Labels = yield from _label_units(marked)
    stretches = yield from _stretch_units(found, labels, geometry)
    over = sum(int(item.size) for item in found.keys)
    if not found.pairs:
        return EdgeReport(0, 0, 0.0, None, None, (), threshold, share, thickness)
    x, y = _midpoint(geometry, *divmod(found.best_key, 2 * geometry.ncols + 1))
    return EdgeReport(found.pairs, over, found.best, x, y, stretches, threshold, share,
                      thickness)


def created_steps(design: np.ndarray, start: np.ndarray, domain: np.ndarray, geometry: Grid,
                  min_thickness_m: float, threshold_m: float | None, share_pct: float | None, *,
                  budget_s: float = STEP_BUDGET_S, cells_per_unit: int = PAIR_CELLS_PER_UNIT
                  ) -> Iterator[Progress]:
    """**A11** (RF-014-20, RF-014-21; error 48): el salto creado en el borde de la superficie de
    diseño ``design`` (``S``, m, float64, de la forma de ``geometry``) sobre la superficie de
    partida ``start`` (``z``, m), con el dominio de trabajo ``domain`` (una máscara de
    ``geometry``), el espesor mínimo de la 012 ``min_thickness_m`` (m), el salto admitido
    ``threshold_m`` (m, el parámetro ``des.edge.max_created_step_m``) y el porcentaje admitido
    ``share_pct`` (%, ``des.edge.min_share``: el de las parejas que tiene que quedar dentro del
    salto admitido; D-6), por pasos de ``budget_s`` como mucho (bandas de ``cells_per_unit``
    celdas): el último ``Progress`` (fase ``created_step``) lleva el :class:`EdgeReport`.

    Una celda está **movida** si está en ``domain``, tiene dato en las dos superficies y ``|S −
    z|`` es mayor que el espesor mínimo (la máscara del informe de la 013). Son del **borde** las
    parejas de celdas vecinas (4 vecinos) con una movida y la otra no, con dato en las dos
    superficies; su **salto creado** es ``c = |S_a − S_b| − |z_a − z_b|``: el salto con el diseño
    menos el del terreno, así que el que el terreno ya tenía nunca cuenta. Pasan las de ``c``
    mayor que el salto admitido; sus celdas (las dos de cada pareja) forman los **tramos**
    (componentes 4-conexas). Se avisa si queda dentro del salto admitido menos del porcentaje
    admitido de las parejas (:attr:`EdgeReport.warned`).

    Rechazos al llamar: el salto y el porcentaje admitidos, como sus parámetros
    (``check_quarry_param``: ``des.quarry_param_missing`` o ``des.quarry_param_range``);
    ``ValueError`` (error del programa) si una rejilla no es de la forma de ``geometry``, el
    espesor no es finito y ≥ 0 o ``cells_per_unit`` < 1. Ninguna entrada se modifica y no se
    escribe nada; cerrar el generador a mitad no deja nada."""
    threshold = float(check_quarry_param(EDGE_MAX_STEP, threshold_m))
    share = float(check_quarry_param(EDGE_MIN_SHARE, share_pct))
    thickness = _thickness(min_thickness_m)
    units = _units(cells_per_unit)
    surface = np.asarray(design, dtype=np.float64)
    base = np.asarray(start, dtype=np.float64)
    inside = np.asarray(domain, dtype=bool)
    for label, grid in (("la superficie de diseño", surface), ("la superficie de partida", base),
                        ("el dominio de trabajo", inside)):
        _same_shape(label, grid, geometry.shape)
    work = _created_units(surface, base, inside, geometry, thickness, threshold, share, units)
    return pace_progress(work, budget_s, phase="created_step",
                         running="Midiendo el salto creado en el borde…",
                         finished="Salto creado en el borde, medido")


# --- La operación «Transiciones con el terreno no afectado» (T28; RF-014-19 a RF-014-21) ---------

EDGE_PHASE = "edge"
"""La fase de los pasos de :func:`edge_transition_steps` que no son de la transición ni del salto
creado (el dominio y el resultado)."""
_TRANSITION_FIGURE = "des.transition_m3"
_STEP_FIGURE = "des.created_step_max_m"
_SHARE_FIGURE = "des.created_step_share_pct"


@dataclass(frozen=True, slots=True, eq=False)
class EdgeTransition:
    """Lo que calcula ``des.edge_transition`` (RF-014-19 a RF-014-21): el ``domain`` de la
    transición (:func:`transition_domain`), la ``transition`` (A10, :class:`Transition`: la
    superficie nueva y su volumen), el ``report`` del salto creado de la superficie nueva (A11,
    :class:`EdgeReport`), sus cifras CALCULADO (``figures``, :func:`edge_transition_figures`) y el
    ``message`` de la operación."""

    domain: np.ndarray
    transition: Transition
    report: EdgeReport
    figures: tuple[FigureSpec, ...]
    message: str

    @property
    def grid(self) -> np.ndarray:
        """La superficie con la transición (m, float64; la de ``transition``)."""
        return self.transition.grid

    @property
    def notices(self) -> tuple[Notice, ...]:
        """El aviso de RF-014-21 y sus tramos (:func:`edge_notices`); ninguno si no se avisa."""
        return edge_notices(self.report)


def transition_domain(surface: np.ndarray, start: np.ndarray, min_thickness_m: float,
                      allowed: np.ndarray | None = None) -> np.ndarray:
    """El dominio de la transición de la superficie de diseño ``surface`` (``S``, m) sobre la de
    partida ``start`` (``z``, m) (T28; RF-014-19): las celdas que **mueve el diseño** —con dato en
    las dos superficies y ``|S − z|`` mayor que el espesor mínimo de la 012 ``min_thickness_m`` (m),
    la máscara de las celdas movidas del informe de la 013 y de A11— y, si se da, dentro de
    ``allowed`` (las celdas en que las máscaras admiten mover el terreno: el corte o el relleno
    admitidos). Su anillo exterior es así el **terreno no afectado** del borde del diseño: las
    celdas que el diseño no mueve, que es donde A11 mide el salto creado. Una máscara nueva;
    ``ValueError`` (error del programa) si las rejillas no son de la misma forma o el espesor no
    es finito y ≥ 0."""
    thickness = _thickness(min_thickness_m)
    design = np.asarray(surface, dtype=np.float64)
    base = np.asarray(start, dtype=np.float64)
    _same_shape("la superficie de partida", base, design.shape)
    with np.errstate(invalid="ignore"):
        moved = np.isfinite(design) & np.isfinite(base) & (np.abs(design - base) > thickness)
    if allowed is not None:
        inside = np.asarray(allowed, dtype=bool)
        _same_shape("lo que admiten las máscaras", inside, design.shape)
        moved &= inside
    return moved


def edge_notices(report: EdgeReport) -> tuple[Notice, ...]:
    """El aviso de RF-014-21 del salto creado ``report`` (``des.edge_created_step``, con el
    porcentaje de las parejas que pasa, las parejas, el salto y el porcentaje admitidos, el máximo
    y su lugar al cm y los tramos) y una nota ``des.edge_stretch`` por tramo, con sus valores como
    números (``preview.Notice``); ninguno si no se avisa (:attr:`EdgeReport.warned`)."""
    if not report.warned:
        return ()
    found = [Notice("des.edge_created_step", {
        "share": round(report.over_pct, 2), "pairs": report.pairs,
        "threshold": report.threshold_m, "admitted": report.min_share_pct,
        "maximum": round(report.maximum_m, 2), "x": _place(report.x), "y": _place(report.y),
        "stretches": len(report.stretches)})]
    found.extend(Notice("des.edge_stretch", {
        "stretch": item.stretch, "pairs": item.pairs, "maximum": round(item.maximum_m, 2),
        "x": _place(item.x), "y": _place(item.y)}) for item in report.stretches)
    return tuple(found)


def edge_transition_figures(name: str, transition: Transition, report: EdgeReport
                            ) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO de la transición ``name`` (plan 014 §5.2.3; RF-014-19 a RF-014-21), con
    el ámbito de ``provenance.quarry_figure_scope``: el volumen de la transición (m³), el mayor
    salto creado del borde de la superficie nueva (m: si es negativo —el diseño solo reduce los
    saltos que ya tenía el terreno— o no hay parejas, 0 m, porque la cifra no admite negativos; el
    informe ``des_erp_`` lleva el valor con su signo) y el porcentaje de las parejas del borde
    dentro del salto admitido (%, el 100 % sin parejas)."""
    scope = provenance.quarry_figure_scope(name)
    return (FigureSpec(_TRANSITION_FIGURE, float(transition.volume_m3), "m3", scope=scope),
            FigureSpec(_STEP_FIGURE, max(0.0, float(report.maximum_m)), "m", scope=scope),
            FigureSpec(_SHARE_FIGURE, float(report.within_pct), "%", scope=scope))


def _edge_message(name: str, transition: Transition, report: EdgeReport) -> str:
    """El mensaje de la operación: lo que hace la transición y lo que queda en el borde."""
    return (f"Transición «{name}» calculada: {format_value(round(transition.volume_m3, 2))} m³ en "
            f"{transition.cells} celdas a {format_value(transition.angle_deg)}°; salto creado "
            f"máximo {format_value(round(max(0.0, report.maximum_m), 2))} m, "
            f"{format_value(round(report.within_pct, 2))} % de las {report.pairs} parejas del "
            f"borde dentro de {format_value(report.threshold_m)} m")


def _edge_steps(surface: np.ndarray, start: np.ndarray, geometry: Grid,
                allowed: np.ndarray | None, degrees: float, thickness: float, threshold: float,
                share: float, metric: Metric, name: str, budget_s: float
                ) -> Generator[Progress, None, None]:
    yield Progress(EDGE_PHASE, 0, 1, "Buscando las celdas que mueve el diseño…")
    domain = transition_domain(surface, start, thickness, allowed)
    transition: Transition = yield from pipeline.forward(transition_steps(
        surface, start, domain, geometry, degrees, metric=metric, name=name, budget_s=budget_s))
    report: EdgeReport = yield from pipeline.forward(created_steps(
        transition.grid, start, domain, geometry, thickness, threshold, share,
        budget_s=budget_s))
    outcome = EdgeTransition(domain, transition, report,
                             edge_transition_figures(name, transition, report),
                             _edge_message(name, transition, report))
    yield Progress(EDGE_PHASE, 1, 1, outcome.message, result=outcome)


def edge_transition_steps(surface: np.ndarray, start: np.ndarray, geometry: Grid, *,
                          angle_deg: float | None, min_thickness_m: float,
                          threshold_m: float | None, share_pct: float | None, name: str,
                          allowed: np.ndarray | None = None,
                          metric: Metric | str = Metric.CHAMFER5,
                          budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Lo que calcula ``des.edge_transition`` (T28; RF-014-19 a RF-014-21; A10, A11) con la
    superficie de diseño ``surface`` (``S``, m, float64, de la forma de ``geometry``) sobre la de
    partida ``start`` (``z``, m), por pasos de ``budget_s`` como mucho: el dominio
    (:func:`transition_domain`, con el espesor mínimo ``min_thickness_m`` y lo que admiten las
    máscaras, ``allowed``), la transición en él con el ángulo de transición ``angle_deg`` (°) y la
    ``metric`` de la 013 (:func:`transition_steps`) y el salto creado de la superficie nueva en ese
    mismo dominio con el salto admitido ``threshold_m`` (m) y el porcentaje admitido
    ``share_pct`` (%) (:func:`created_steps`). El último ``Progress`` (fase :data:`EDGE_PHASE`)
    lleva el :class:`EdgeTransition` de la operación ``name`` (el ámbito de sus cifras).

    Rechazos al llamar: el ángulo, el salto y el porcentaje, como sus parámetros
    (``check_quarry_param``: ``des.quarry_param_missing`` —el ángulo no tiene valor por defecto,
    D-9— o ``des.quarry_param_range``); ``GisError`` ``gis.dataset_name_invalid`` si el nombre no
    tiene ninguna letra ni cifra; ``ValueError`` (error del programa) si una rejilla no es de la
    forma de ``geometry``, el espesor no es finito y ≥ 0 o la métrica no es de la 013. Ninguna
    entrada se modifica y no se escribe nada; cerrar el generador a mitad no deja nada."""
    provenance.quarry_figure_scope(name)  # el nombre, al llamar: lo necesitan las cifras
    degrees = float(check_quarry_param(EDGE_TRANSITION, angle_deg))
    threshold = float(check_quarry_param(EDGE_MAX_STEP, threshold_m))
    share = float(check_quarry_param(EDGE_MIN_SHARE, share_pct))
    thickness = _thickness(min_thickness_m)
    design = np.asarray(surface, dtype=np.float64)
    base = np.asarray(start, dtype=np.float64)
    for label, grid in (("la superficie de diseño", design), ("la superficie de partida", base)):
        _same_shape(label, grid, geometry.shape)
    inside = None if allowed is None else np.asarray(allowed, dtype=bool)
    if inside is not None:
        _same_shape("lo que admiten las máscaras", inside, geometry.shape)
    return _edge_steps(design, base, geometry, inside, degrees, thickness, threshold, share,
                       Metric(metric), name, budget_s)
