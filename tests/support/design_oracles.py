# SPDX-License-Identifier: GPL-3.0-or-later
"""Los oráculos de las envolventes (spec 013, T01; plan 013 §7.1, A3, A4, A5; ADR-0014).

Dos implementaciones lentas y obvias, independientes del núcleo de ``design`` (que se escribe
después), para rejillas pequeñas (≤ 90 × 90 celdas):

- :func:`brute_force_euclidean`: la euclídea exacta por fuerza bruta,
  ``E_up(p) = mín_q [f_q + t·h·|p − q|]`` con la distancia entre centros de celda, para una
  pendiente constante (la euclídea exacta no admite pendiente por sectores: RF-013-16).
- :func:`dijkstra`: el camino más corto sobre unos desplazamientos con peso, que con
  :data:`CHAMFER5` es el *chamfer* 5×5 (16 desplazamientos de pesos 1, √2 y √5, por la
  :data:`CHAMFER_SCALE` del ADR-0014) y con :func:`euclidean_displacements` es la euclídea: el
  camino más corto con todos los desplazamientos pesados con su longitud real es el segmento
  recto, así que coincide con la fuerza bruta (la prueba de los oráculos entre sí). El coste de
  **entrar** en una celda usa la pendiente ``t`` de la celda de llegada (A2).
- :func:`relaxation_violation` y :func:`seed_violation`: las comprobaciones del punto fijo de A4
  (RF-013-15), la mayor violación de las relajaciones ``E(p) ≤ E(q) + coste(q → p)`` y de las
  semillas (``E_up ≤ f`` o ``E_down ≥ f``), que valen 0 para una envolvente correcta.
- :func:`hand_stairs` (T09, A8): el escalonado en corte o en relleno celda a celda, con el piso
  ``n`` y la fracción ``f`` en **aritmética racional exacta** (``fractions``) y la fórmula del RF
  escrita tal cual, para comparar con ``design.benching`` (RF-013-22, RF-013-23).

Convenciones: ``seed`` es la rejilla de semillas (fila 0 al norte): una celda es semilla si su cota
es finita; ``+inf``, ``−inf`` y NaN no lo son. ``direction="up"`` es ``E_up = mín_q [s + t·d]`` y
``"down"`` es ``E_down = −E_up(−s) = máx_q [s − t·d]``. Una celda inalcanzable sale ``+inf``
(``−inf`` en la descendente). Ninguna entrada se modifica y cada llamada da un array nuevo.

Solo fuera de Blender; solo ``numpy`` y la biblioteca estándar.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from fractions import Fraction

import numpy as np

__all__ = [
    "CHAMFER5",
    "CHAMFER_SCALE",
    "Displacement",
    "brute_force_euclidean",
    "dijkstra",
    "euclidean_displacements",
    "hand_stairs",
    "relaxation_violation",
    "seed_violation",
]

Displacement = tuple[int, int, float]
"""Un desplazamiento ``(filas, columnas, peso)``: el peso es el coste, en celdas, de moverse."""

CHAMFER_SCALE = 0.98644
"""La escala del *chamfer* 5×5 (ADR-0014): el error de distancia queda en ±1,36 %."""


def _chamfer5() -> tuple[Displacement, ...]:
    found: list[Displacement] = []
    for sign_row in (1, -1):
        for sign_col in (1, -1):
            found.append((sign_row, sign_col, math.sqrt(2.0)))
            found.append((2 * sign_row, sign_col, math.sqrt(5.0)))
            found.append((sign_row, 2 * sign_col, math.sqrt(5.0)))
    for sign in (1, -1):
        found.append((sign, 0, 1.0))
        found.append((0, sign, 1.0))
    return tuple(found)


CHAMFER5: tuple[Displacement, ...] = _chamfer5()
"""Los 16 desplazamientos de la máscara 5×5 del *chamfer* con su peso: 4 de eje (1), 4 diagonales
(√2) y 8 de caballo (√5)."""


def euclidean_displacements(radius: int) -> tuple[Displacement, ...]:
    """Todos los desplazamientos no nulos con ``|filas|, |columnas| ≤ radius``, pesados con su
    longitud real (``math.hypot``): con ellos, Dijkstra es la euclídea exacta."""
    if int(radius) != radius or radius < 1:
        raise ValueError(f"el radio debe ser un entero ≥ 1, no {radius!r}")
    return tuple((row, col, math.hypot(row, col))
                 for row in range(-radius, radius + 1) for col in range(-radius, radius + 1)
                 if (row, col) != (0, 0))


def _sign(direction: str) -> float:
    if direction == "up":
        return 1.0
    if direction == "down":
        return -1.0
    raise ValueError(f"la dirección es «up» o «down», no {direction!r}")


def _step(step: float) -> float:
    value = float(step)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"el paso de la rejilla debe ser un número finito > 0, no {step!r}")
    return value


def _tangents(tan: object, shape: tuple[int, ...]) -> np.ndarray:
    found = np.broadcast_to(np.asarray(tan, dtype=np.float64), shape)
    if not np.isfinite(found).all() or (found < 0.0).any():
        raise ValueError("la pendiente (tan) debe ser finita y ≥ 0 en todas las celdas")
    return found


def _seeds(seed: object) -> np.ndarray:
    found = np.asarray(seed, dtype=np.float64)
    if found.ndim != 2:
        raise ValueError(f"la rejilla de semillas es de 2 dimensiones, no {found.ndim}")
    return found


def brute_force_euclidean(seed: object, tan: object, step: float, *,
                          direction: str = "up") -> np.ndarray:
    """La euclídea exacta por fuerza bruta: ``mín_q [f_q + t·h·|p − q|]`` (``máx_q [f_q − …]`` en la
    descendente), con ``|p − q|`` la distancia entre centros de celda en celdas y ``h`` el paso.
    ``tan`` debe ser constante (escalar o un mapa de un solo valor)."""
    sign = _sign(direction)
    unit = _step(step)
    values = sign * _seeds(seed)
    shape = values.shape
    tangents = _tangents(tan, shape)
    if tangents.size and float(tangents.min()) != float(tangents.max()):
        raise ValueError("la euclídea exacta solo admite una pendiente constante (RF-013-16)")
    tangent = float(tangents.flat[0]) if tangents.size else 0.0
    rows, cols = np.indices(shape)
    found = np.full(shape, np.inf)
    for row, col in zip(*np.nonzero(np.isfinite(values)), strict=True):
        candidate = values[row, col] + tangent * unit * np.hypot(rows - row, cols - col)
        np.minimum(found, candidate, out=found)
    return sign * found


def dijkstra(seed: object, tan: object, step: float, *,
             displacements: Sequence[Displacement] = CHAMFER5, scale: float = CHAMFER_SCALE,
             direction: str = "up") -> np.ndarray:
    """El camino más corto desde las semillas sobre ``displacements``: moverse de ``q`` a ``p``
    cuesta ``peso · h · escala · t(p)`` (la pendiente de la celda de llegada, A2) y ``E(p)`` es el
    mínimo de ``f_q`` más lo que cuesta el camino. Con :data:`CHAMFER5` y la escala por defecto es
    el *chamfer* 5×5 del plan (A3); con ``scale=1`` y todos los desplazamientos
    (:func:`euclidean_displacements`), la euclídea."""
    sign = _sign(direction)
    unit = _step(step) * float(scale)
    values = sign * _seeds(seed)
    nrows, ncols = values.shape
    cost = (unit * _tangents(tan, values.shape)).ravel().tolist()
    best = np.full(values.size, np.inf).tolist()
    heap: list[tuple[float, int]] = []
    for index in np.flatnonzero(np.isfinite(values.ravel())).tolist():
        best[index] = float(values.flat[index])
        heap.append((best[index], index))
    heapq.heapify(heap)
    while heap:
        reached, index = heapq.heappop(heap)
        if reached > best[index]:
            continue
        row, col = divmod(index, ncols)
        for d_row, d_col, weight in displacements:
            target_row, target_col = row + d_row, col + d_col
            if 0 <= target_row < nrows and 0 <= target_col < ncols:
                target = target_row * ncols + target_col
                candidate = reached + weight * cost[target]
                if candidate < best[target]:
                    best[target] = candidate
                    heapq.heappush(heap, (candidate, target))
    return sign * np.asarray(best, dtype=np.float64).reshape(values.shape)


def _shifted(grid: np.ndarray, d_row: int, d_col: int) -> tuple[tuple[slice, slice],
                                                                 tuple[slice, slice]] | None:
    """Los trozos de ``grid`` (llegada) y de su vecina desplazada ``(d_row, d_col)`` (salida) que
    caen dentro, o ``None`` si el desplazamiento se sale de la rejilla."""
    nrows, ncols = grid.shape
    if abs(d_row) >= nrows or abs(d_col) >= ncols:
        return None
    arrival = (slice(max(d_row, 0), nrows + min(d_row, 0)),
               slice(max(d_col, 0), ncols + min(d_col, 0)))
    origin = (slice(max(-d_row, 0), nrows + min(-d_row, 0)),
              slice(max(-d_col, 0), ncols + min(-d_col, 0)))
    return arrival, origin


def relaxation_violation(envelope: object, tan: object, step: float, *,
                         displacements: Sequence[Displacement] = CHAMFER5,
                         scale: float = CHAMFER_SCALE, direction: str = "up") -> float:
    """La mayor violación (m) de las relajaciones ``E(p) ≤ E(q) + coste(q → p)`` sobre toda la
    rejilla y todos los desplazamientos (A4; ``E(p) ≥ E(q) − coste`` en la descendente): 0 si la
    envolvente es un punto fijo. ``+inf`` si una celda sin envolvente tiene una vecina con ella."""
    sign = _sign(direction)
    unit = _step(step) * float(scale)
    values = sign * np.asarray(envelope, dtype=np.float64)
    cost = unit * _tangents(tan, values.shape)
    worst = 0.0
    for d_row, d_col, weight in displacements:
        pieces = _shifted(values, d_row, d_col)
        if pieces is None:
            continue
        arrival, origin = pieces
        with np.errstate(invalid="ignore"):
            excess = values[arrival] - (values[origin] + weight * cost[arrival])
        excess = excess[np.isfinite(values[origin]) | np.isposinf(values[arrival])]
        excess = excess[~np.isnan(excess)]
        if excess.size:
            worst = max(worst, float(excess.max()))
    return worst


def seed_violation(envelope: object, seed: object, *, direction: str = "up") -> float:
    """La mayor violación (m) de las semillas: cuánto pasa ``E_up`` de la cota de una semilla (o
    cuánto queda ``E_down`` por debajo de ella); 0 si en cada semilla ``E_up ≤ f``
    (``E_down ≥ f``)."""
    sign = _sign(direction)
    values = sign * np.asarray(envelope, dtype=np.float64)
    seeds = sign * _seeds(seed)
    is_seed = np.isfinite(seeds)
    if not is_seed.any():
        return 0.0
    with np.errstate(invalid="ignore"):
        excess = values[is_seed] - seeds[is_seed]
    excess = np.where(np.isnan(excess), np.inf, excess)
    return max(0.0, float(excess.max()))


def _stair(surface: float, height: float, tan_face: float, berm: float, anchor: float,
           fill: bool) -> float:
    """El escalonado de una celda con ``n = ⌊(S − z₀)/h⌋`` y ``f = u − n`` exactos (racionales)."""
    if not all(math.isfinite(value) for value in (surface, height, tan_face, berm, anchor)):
        return math.nan
    level = (Fraction(surface) - Fraction(anchor)) / Fraction(height)
    number = math.floor(level)
    fraction = float(level - number)
    advance = height / tan_face + berm
    if fill:
        rise = max((fraction * advance - berm) * tan_face, 0.0)
    else:
        rise = min(fraction * advance * tan_face, height)
    return anchor + number * height + rise


def hand_stairs(surface: object, height: object, tan_face: object, berm: object, anchor: object,
                *, fill: bool = False) -> np.ndarray:
    """El escalonado por celda del RF-013-22 (``fill=False``: cara primero,
    ``z₀ + n·h + mín(f·a·tan α, h)``) o del RF-013-23 (``fill=True``: berma primero,
    ``z₀ + n·h + máx((f·a − B)·tan α, 0)``), con ``a = h/tan α + B``, ``u = (S − z₀)/h``,
    ``n = ⌊u⌋`` y ``f = u − n``. Los cinco argumentos se difunden entre sí (escalares o arrays); una
    celda con algún dato no finito sale NaN. Lento (un bucle de Python con racionales): para pocas
    celdas. Ninguna entrada se modifica."""
    arrays = np.broadcast_arrays(*(np.asarray(value, dtype=np.float64)
                                   for value in (surface, height, tan_face, berm, anchor)))
    found = np.empty(arrays[0].shape)
    for index in np.ndindex(found.shape):
        s, h, t, b, z = (float(array[index]) for array in arrays)
        found[index] = _stair(s, h, t, b, z, fill)
    return found
