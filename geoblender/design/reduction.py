# SPDX-License-Identifier: GPL-3.0-or-later
"""Las dos reducciones exactas de semillas de la euclídea exacta (spec 013, T08; RF-013-12; plan 013
A5, D-22, T3; ADR-0014).

La envolvente ascendente es ``T(p) = mín_q [f_q + k·|p − q|]``, con ``f_q`` la cota de la semilla
``q``, ``|p − q|`` la distancia entre centros de celda **en celdas** y ``k = t·h`` lo que sube por
celda de distancia (m). Con una zona maciza de 160.000 semillas la búsqueda exacta cuesta 23-64 s;
estas dos reglas retiran de ella las semillas que no pueden ser la mejor de ninguna celda y **no
cambian ninguna cota**:

- **Dominada** (:func:`dominated_cells`): ``U(q) < f_q − 10⁻⁹``, con ``U ≥ T`` una cota superior
  (el *chamfer* sin escala, que es la longitud de un camino real y nunca queda por debajo de la
  distancia euclídea). Otra semilla da menos que ``f_q`` en la propia celda de ``q`` y, como ``T``
  es ``k``-Lipschitz, ``f_q + k·|p − q|`` supera a ``T(p)`` en toda celda ``p``: ``q`` no es nunca
  la mejor.
- **Redundante** (:func:`redundant_cells`): sus 8 vecinas son semillas con
  ``f_n ≤ f_q + k·g`` (:data:`MIN_GAIN`). Para toda otra celda ``p`` hay una vecina ``n`` que queda
  al menos ``g`` más cerca (``|p − q| − |p − n| ≥ g``), y entonces ``f_n + k·|p − n| ≤ f_q + k·g +
  k·(|p − q| − g) = f_q + k·|p − q|``: su cono no es mayor. Si ``n`` también se retira, se repite
  con ``n`` y la distancia a ``p`` baja al menos ``g`` cada vez, así que acaba en una semilla que
  queda o en la propia ``p`` (de ahí que la cota de una celda retirada sea ``mín(T, f)``). Ni
  ``p`` ni ``q`` son puntos cualesquiera del plano, sino centros de celda: el mínimo de la ganancia
  sobre la retícula entera es **exactamente 1** (los puntos del eje, ``p − q = (d, 0)``), mientras
  que sobre el plano continuo sería 0,4824; el umbral con 1 retira muchas más semillas, como las
  de una ladera, y sigue siendo exacto (``tests/unit/design/test_reduction.py`` lo comprueba por
  fuerza bruta, y que con algo más de 1 ya cambia la cota).

Las reglas se aplican a la vez a todas las semillas, y es exacto: una semilla que es la mejor de
alguna celda nunca es dominada (sería estrictamente peor que otra) y, si es redundante, la cadena de
vecinas llega a otra que también es la mejor, más cerca de la celda. Los bordes de la rejilla no
tienen 8 vecinas: nunca son redundantes.

Las semillas se entregan en la convención **ascendente**: la cota si es semilla y ``+inf`` si no (la
descendente se niega antes). Python puro (nivel 8), con numpy; sin modificar nada de lo que recibe.
"""

from __future__ import annotations

import math
from collections.abc import Generator
from dataclasses import dataclass

import numpy as np

__all__ = [
    "DOMINANCE_TOLERANCE_M",
    "MIN_GAIN",
    "Reduction",
    "dominated_cells",
    "reduce_seeds",
    "reduce_units",
    "redundant_cells",
]

MIN_GAIN = 1.0
"""``g``: lo que, como mínimo, deja más cerca de cualquier otra celda la mejor de las 8 vecinas de
una semilla, en celdas (el mínimo sobre la retícula entera; vale 1 en los puntos del eje)."""
DOMINANCE_TOLERANCE_M = 1e-9
"""Lo que una cota ha de quedar por debajo de la de la semilla para dominarla (m)."""
ROWS_PER_UNIT = 128
"""Las filas de una unidad de trabajo si no se dice otra cosa."""


@dataclass(frozen=True, slots=True, eq=False)
class Reduction:
    """Las semillas que quedan tras las dos reducciones: sus ``rows`` y ``cols`` (``int64``, por
    filas y luego por columnas) con su cota ``values`` (m, float64), y cuántas se retiraron por
    ``dominated`` y por ``redundant`` (una que cumple las dos cuenta como dominada). Todas las
    semillas son ``seeds`` = ``kept`` + ``dominated`` + ``redundant``: ninguna se pierde sin
    contar."""

    rows: np.ndarray
    cols: np.ndarray
    values: np.ndarray
    dominated: int
    redundant: int

    @property
    def kept(self) -> int:
        """Las semillas que quedan en la búsqueda."""
        return int(self.rows.size)

    @property
    def seeds(self) -> int:
        """Todas las semillas de partida."""
        return self.kept + self.dominated + self.redundant


def _band(start: int, stop: int | None, nrows: int) -> tuple[int, int]:
    """Las filas ``start … stop − 1`` de una rejilla de ``nrows`` (``stop`` ``None``: hasta el
    final); ``ValueError`` si no caben."""
    end = nrows if stop is None else int(stop)
    first = int(start)
    if not 0 <= first <= end <= nrows:
        raise ValueError(f"las filas {first} a {end} no caben en una rejilla de {nrows} filas")
    return first, end


def _floats(grid: object, what: str) -> np.ndarray:
    found = np.asarray(grid, dtype=np.float64)
    if found.ndim != 2:
        raise ValueError(f"{what} es una rejilla de 2 dimensiones, no de {found.ndim}")
    return found


def _rise(rise: float) -> float:
    value = float(rise)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"lo que sube la envolvente por celda debe ser un número finito ≥ 0, "
                         f"no {rise!r}")
    return value


def dominated_cells(values: np.ndarray, bound: np.ndarray,
                    tolerance: float = DOMINANCE_TOLERANCE_M, *, start: int = 0,
                    stop: int | None = None) -> np.ndarray:
    """Las semillas dominadas de las filas ``start … stop − 1`` (toda la rejilla por defecto): las
    celdas con cota finita en ``values`` (la convención ascendente: ``+inf`` sin semilla) cuya cota
    superior ``bound`` (``U ≥ T``, de la misma forma) queda por debajo de la suya en más de
    ``tolerance`` m. Devuelve una máscara nueva de esas filas."""
    seeds = _floats(values, "las semillas")
    limits = _floats(bound, "la cota")
    if seeds.shape != limits.shape:
        raise ValueError(f"la cota {limits.shape} no es de la forma de las semillas {seeds.shape}")
    first, end = _band(start, stop, seeds.shape[0])
    band = seeds[first:end]
    with np.errstate(invalid="ignore"):
        return np.isfinite(band) & (limits[first:end] < band - tolerance)


def redundant_cells(values: np.ndarray, rise: float, *, start: int = 0,
                    stop: int | None = None) -> np.ndarray:
    """Las semillas redundantes de las filas ``start … stop − 1`` (toda la rejilla por defecto): las
    celdas de dentro de la rejilla cuyas 8 vecinas son semillas con cota ``≤ f + rise·g``
    (:data:`MIN_GAIN`), con ``rise = t·h`` lo que sube la envolvente por celda (m). ``values`` es la
    convención ascendente: la cota donde hay semilla y ``+inf`` donde no (nunca NaN ni ``−inf``: una
    vecina sin semilla es ``+inf`` y lo impide). Las filas y las columnas de la orilla de la
    rejilla no lo son nunca. Devuelve una máscara nueva de esas filas."""
    seeds = _floats(values, "las semillas")
    step = _rise(rise)
    nrows, ncols = seeds.shape
    first, end = _band(start, stop, nrows)
    found = np.zeros((end - first, ncols), dtype=bool)
    top, bottom = max(first, 1), min(end, nrows - 1)  # filas de dentro de la rejilla
    if top >= bottom or ncols < 3:
        return found
    peak = np.maximum(seeds[top - 1:bottom - 1, :-2], seeds[top - 1:bottom - 1, 1:-1])
    np.maximum(peak, seeds[top - 1:bottom - 1, 2:], out=peak)
    np.maximum(peak, seeds[top:bottom, :-2], out=peak)
    np.maximum(peak, seeds[top:bottom, 2:], out=peak)
    np.maximum(peak, seeds[top + 1:bottom + 1, :-2], out=peak)
    np.maximum(peak, seeds[top + 1:bottom + 1, 1:-1], out=peak)
    np.maximum(peak, seeds[top + 1:bottom + 1, 2:], out=peak)
    centre = seeds[top:bottom, 1:-1]
    with np.errstate(invalid="ignore"):
        found[top - first:bottom - first, 1:-1] = np.isfinite(centre) & (
            peak <= centre + step * MIN_GAIN)
    return found


def reduce_units(values: np.ndarray, bound: np.ndarray, rise: float, *,
                 rows_per_unit: int = ROWS_PER_UNIT,
                 tolerance: float = DOMINANCE_TOLERANCE_M) -> Generator[None, None, Reduction]:
    """Las dos reducciones sobre toda la rejilla, en unidades de ``rows_per_unit`` filas (una por
    ``yield``): devuelve la :class:`Reduction`. ``values`` son las semillas (cota o ``+inf``),
    ``bound`` una cota superior de la envolvente en cada celda (``U ≥ T``; cuanto más ceñida,
    más dominadas) y ``rise`` lo que sube la envolvente por celda de distancia (``t·h``, m).
    ``ValueError`` si las formas no casan, ``rise`` no es un número finito ≥ 0, hay NaN o ``−inf``
    en las semillas o ``rows_per_unit`` es menor que 1. No modifica nada."""
    seeds = _floats(values, "las semillas")
    limits = _floats(bound, "la cota")
    if seeds.shape != limits.shape:
        raise ValueError(f"la cota {limits.shape} no es de la forma de las semillas {seeds.shape}")
    step = _rise(rise)
    if int(rows_per_unit) < 1:
        raise ValueError(f"las filas por unidad deben ser al menos 1, no {rows_per_unit!r}")
    rows_by_unit = int(rows_per_unit)
    kept_rows: list[np.ndarray] = []
    kept_cols: list[np.ndarray] = []
    kept_values: list[np.ndarray] = []
    dominated = redundant = 0
    for first in range(0, seeds.shape[0], rows_by_unit):
        end = min(first + rows_by_unit, seeds.shape[0])
        band = seeds[first:end]
        is_seed = np.isfinite(band)
        if not (is_seed | np.isposinf(band)).all():
            raise ValueError("las semillas son finitas o +inf: NaN y −inf no son una cota")
        beaten = dominated_cells(seeds, limits, tolerance, start=first, stop=end)
        spare = redundant_cells(seeds, step, start=first, stop=end) & ~beaten
        dominated += int(beaten.sum())
        redundant += int(spare.sum())
        rows, cols = np.nonzero(is_seed & ~beaten & ~spare)
        kept_rows.append(rows + first)
        kept_cols.append(cols)
        kept_values.append(band[rows, cols])
        yield None
    return Reduction(np.concatenate(kept_rows).astype(np.int64),
                     np.concatenate(kept_cols).astype(np.int64),
                     np.concatenate(kept_values).astype(np.float64), dominated, redundant)


def reduce_seeds(values: np.ndarray, bound: np.ndarray, rise: float, *,
                 rows_per_unit: int = ROWS_PER_UNIT,
                 tolerance: float = DOMINANCE_TOLERANCE_M) -> Reduction:
    """:func:`reduce_units` hasta el final, de una vez."""
    steps = reduce_units(values, bound, rise, rows_per_unit=rows_per_unit, tolerance=tolerance)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]
