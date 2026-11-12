# SPDX-License-Identifier: GPL-3.0-or-later
"""El borde de un diseño con el terreno no afectado: la transición (spec 014, T26; HU-014-5;
RF-014-19; plan 014 A10, §5.3.1).

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

Python puro con numpy (nivel 8): no importa ``reserves`` ni ``bl``; no escribe nada.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
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
from .grids import dilate_square
from .model import Direction, Metric
from .params import EDGE_TRANSITION, check_quarry_param
from .seeds import pace_progress

__all__ = [
    "TRANSITION_NAME",
    "Transition",
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
