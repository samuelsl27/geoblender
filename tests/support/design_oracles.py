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
- :func:`hand_plane`, :func:`hand_cell_slope_deg` y :func:`hand_crown` (spec 016, T06; plan 016 A2): el plano de
  base robusto, la pendiente de cada celda y la corona **a mano**: bucles de Python sin numpy, el ajuste por las
  ecuaciones normales en **aritmética racional exacta** (``fractions``: sin redondeos ni ``lstsq``), la mediana y
  el cuantil ordenando, para comparar con ``design.stockpiles`` (RF-016-02, RF-016-07).

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
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

__all__ = [
    "CHAMFER5",
    "CHAMFER_SCALE",
    "Displacement",
    "HandPlane",
    "brute_force_euclidean",
    "dijkstra",
    "euclidean_displacements",
    "hand_cell_slope_deg",
    "hand_crown",
    "hand_plane",
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


# --- El plano de base de un acopio, a mano (spec 016, T06; plan 016 A2) --------------------------------


@dataclass(frozen=True, slots=True)
class HandPlane:
    """El plano ``z = pivot_z + b·(x − pivot_x) + c·(y − pivot_y)`` de :func:`hand_plane`: su pivote
    ``(pivot_x, pivot_y)`` (la media de las celdas dadas), ``pivot_z`` y las pendientes al este (``east_slope``, ``b``)
    y al norte (``north_slope``, ``c``), la inclinación del ajuste (``fitted_tilt_deg``), si se limitó (``limited``)
    y, por cada celda dada en su orden, si entró en el último ajuste (``kept``)."""

    pivot_x: float
    pivot_y: float
    pivot_z: float
    east_slope: float
    north_slope: float
    fitted_tilt_deg: float
    limited: bool
    kept: tuple[bool, ...]

    def at(self, x: float, y: float) -> float:
        """La cota del plano en ``(x, y)``."""
        return self.pivot_z + self.east_slope * (x - self.pivot_x) + self.north_slope * (y - self.pivot_y)


def _determinant(m: Sequence[Sequence[Fraction]]) -> Fraction:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _exact_fit(cells: Sequence[tuple[Fraction, Fraction, Fraction]]) -> tuple[Fraction, Fraction, Fraction]:
    """``(a, b, c)`` de ``z = a + b·x + c·y`` por mínimos cuadrados, de las ecuaciones normales resueltas con la regla
    de Cramer en racionales (``ValueError`` si no determinan un plano: menos de tres celdas o alineadas)."""
    zero = Fraction(0)
    n = Fraction(len(cells))
    sx = sum((x for x, _, _ in cells), zero)
    sy = sum((y for _, y, _ in cells), zero)
    sxx = sum((x * x for x, _, _ in cells), zero)
    sxy = sum((x * y for x, y, _ in cells), zero)
    syy = sum((y * y for _, y, _ in cells), zero)
    sz = sum((z for _, _, z in cells), zero)
    sxz = sum((x * z for x, _, z in cells), zero)
    syz = sum((y * z for _, y, z in cells), zero)
    matrix = ((n, sx, sy), (sx, sxx, sxy), (sy, sxy, syy))
    rhs = (sz, sxz, syz)
    det = _determinant(matrix)
    if det == 0:
        raise ValueError("las celdas no determinan un plano")
    found = []
    for column in range(3):
        swapped = [list(row) for row in matrix]
        for row in range(3):
            swapped[row][column] = rhs[row]
        found.append(_determinant(swapped) / det)
    return found[0], found[1], found[2]


def _median(values: Sequence[Fraction]) -> Fraction:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _linear_quantile(values: Sequence[Fraction], q: Fraction) -> Fraction:
    """El cuantil ``q`` de ``values`` por interpolación lineal entre los dos valores ordenados que rodean al índice
    ``q·(n − 1)`` (el método por defecto de ``numpy.quantile``)."""
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def hand_plane(cells: Sequence[tuple[float, float, float]], *, rounds: int, max_residual_m: float,
               tilt_max_deg: float, quantile: float) -> HandPlane:
    """El plano de base de A2 a mano (RF-016-02, RF-016-07): ``cells`` son ``(x, y, z)`` de las celdas de la corona
    que cuentan (las llanas o toda la corona), en el orden de lectura.

    Ajuste por mínimos cuadrados exactos (racionales; coordenadas desde la media de las celdas) y, ``rounds`` veces,
    se descartan las celdas cuyo residuo se aparta de la **mediana** de los residuos de las que quedan más que
    ``max_residual_m`` (``>``; un descarte que dejaría menos de tres celdas o alineadas no se hace, y si no se
    descarta nada se acaba). Si la inclinación del ajuste, ``atan(√(b² + c²))``, pasa de ``tilt_max_deg``, las
    pendientes se escalan hasta ella sin cambiar su dirección y ``pivot_z`` es el cuantil ``quantile`` (interpolación
    lineal) de ``z − b'·(x − pivot_x) − c'·(y − pivot_y)`` en las celdas que quedaron. Solo bucles y racionales:
    ``ValueError`` si las celdas no determinan un plano."""
    if len(cells) < 3:
        raise ValueError("un plano necesita al menos tres celdas")
    pivot_x = math.fsum(x for x, _, _ in cells) / len(cells)
    pivot_y = math.fsum(y for _, y, _ in cells) / len(cells)
    relative = [(Fraction(x) - Fraction(pivot_x), Fraction(y) - Fraction(pivot_y), Fraction(z)) for x, y, z in cells]
    kept = list(range(len(cells)))
    a, b, c = _exact_fit([relative[i] for i in kept])
    limit = Fraction(max_residual_m)
    for _ in range(rounds):
        residuals = [relative[i][2] - (a + b * relative[i][0] + c * relative[i][1]) for i in kept]
        median = _median(residuals)
        staying = [i for i, r in zip(kept, residuals, strict=True) if abs(r - median) <= limit]
        if len(staying) == len(kept) or len(staying) < 3:
            break
        try:
            refit = _exact_fit([relative[i] for i in staying])
        except ValueError:
            break
        kept, (a, b, c) = staying, refit
    east, north = float(b), float(c)
    gradient = math.hypot(east, north)
    fitted = math.degrees(math.atan(gradient))
    limited = fitted > tilt_max_deg
    pivot_z = float(a)
    if limited:
        scale = math.tan(math.radians(tilt_max_deg)) / gradient
        east, north = east * scale, north * scale
        levels = [relative[i][2] - (Fraction(east) * relative[i][0] + Fraction(north) * relative[i][1])
                  for i in kept]
        pivot_z = float(_linear_quantile(levels, Fraction(quantile)))
    staying_set = set(kept)
    flags = tuple(i in staying_set for i in range(len(cells)))
    return HandPlane(pivot_x, pivot_y, pivot_z, east, north, fitted, limited, flags)


def hand_cell_slope_deg(z: Sequence[Sequence[float]], dx: float, dy: float) -> np.ndarray:
    """La pendiente de cada celda (°): ``atan(√(∂z/∂x² + ∂z/∂y²))`` con la diferencia centrada entre las dos celdas
    vecinas (``(z₊ − z₋)/(2·paso)``) y, en el borde de la rejilla, la de un lado (``(z₁ − z₀)/paso``); una celda sin
    dato (NaN), o con alguna de las que usa sin dato, sale NaN. Bucles de Python (RF-016-02)."""
    rows, cols = len(z), len(z[0])
    found = np.empty((rows, cols))
    for r in range(rows):
        for c in range(cols):
            if math.isnan(z[r][c]):
                found[r, c] = math.nan
                continue
            if c == 0:
                east = (z[r][1] - z[r][0]) / dx
            elif c == cols - 1:
                east = (z[r][c] - z[r][c - 1]) / dx
            else:
                east = (z[r][c + 1] - z[r][c - 1]) / (2.0 * dx)
            if r == 0:
                south = (z[1][c] - z[0][c]) / dy
            elif r == rows - 1:
                south = (z[r][c] - z[r - 1][c]) / dy
            else:
                south = (z[r + 1][c] - z[r - 1][c]) / (2.0 * dy)
            found[r, c] = math.degrees(math.atan(math.hypot(east, south)))
    return found


def hand_crown(footprint: Sequence[Sequence[bool]], cell: float, inner_m: float, outer_m: float) -> np.ndarray:
    """La corona de A2 (RF-016-02): las celdas a no más de ``outer_m`` m de alguna celda de la huella y a más de
    ``inner_m`` m de todas (centro con centro, en metros, con la tolerancia de 10⁻⁹ m del disco de A1). Fuerza
    bruta: cada celda contra cada celda de la huella; para rejillas pequeñas."""
    rows, cols = len(footprint), len(footprint[0])
    cells = [(r, c) for r in range(rows) for c in range(cols) if footprint[r][c]]
    found = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            nearest = min((math.hypot((r - i) * cell, (c - j) * cell) for i, j in cells), default=math.inf)
            found[r, c] = nearest <= outer_m + 1e-9 and not nearest <= inner_m + 1e-9
    return found
