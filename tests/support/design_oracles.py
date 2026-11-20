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
- :func:`hand_dilate`, :func:`hand_zones`, :func:`hand_footprint`, :func:`hand_volume` y :func:`hand_share` (spec 016,
  T07; plan 016 A3): la dilatación, las zonas conexas (una búsqueda en anchura), la huella con sus huecos rellenos
  (otra, desde fuera), el volumen y el reparto de las celdas comunes **a mano**: bucles de Python sin numpy ni
  ``design.grids`` ni ``design.morphology``, la distancia entre marcas por fuerza bruta con enteros, para comparar con
  ``design.stockpiles`` (RF-016-02, RF-016-04, RF-016-05, RF-016-06).
- :func:`hand_layers` (spec 016, T09; plan 016 A5): la base, el espesor ``máx(z − base, 0)``, el terreno sin acopios
  ``mín(z, base)``, la superficie y el volumen de las celdas de una huella **a mano**, un bucle de Python por celda
  con ``fsum``, para comparar con las bases y los espesores de ``design.stockpiles`` (RF-016-01, RF-016-09).
- :func:`hand_removal` (spec 016, T17; plan 016 A6): la retirada de un acopio **a mano**: el dominio de la retirada, su
  anillo de semillas, la envolvente descendente (la euclídea por fuerza bruta o el *chamfer* de :func:`dijkstra`), la
  superficie ``mín(z, máx(base, envolvente))`` y las cuatro cifras (retirado, apoyado, transición y no retirado) como
  longitud de la columna ``[z', z]`` a cada lado de la superficie de detección, un bucle de Python por celda con
  ``fsum``, para comparar con ``design.removal`` (RF-016-11, RF-016-13).
- :func:`hand_wall` (spec 016, T19; plan 016 A8): la pared que deja una retirada **a mano**: las parejas de celdas
  vecinas (4 vecinos) con una movida y la otra no, su salto creado ``|S_a − S_b| − |z_a − z_b|``, las que pasan del
  salto admitido y de la inclinación, sus tramos (una búsqueda en anchura sobre las celdas de esas parejas) y, de cada
  uno, la altura (mayor cota menos menor cota de sus parejas), la inclinación de su peor pareja, su mayor salto creado y
  el punto medio de esa pareja, un bucle de Python por pareja sin numpy, para comparar con ``design.removal``
  (RF-016-15).
- :func:`hand_buttress` (spec 016, T26; plan 016 A10): el contrafuerte **a mano**: las semillas (la zona de coronación con la
  superficie por debajo de la cota de coronación), la envolvente descendente (la euclídea por fuerza bruta o el *chamfer* de
  :func:`dijkstra`, con el alcance), el escalonado en relleno de :func:`hand_stairs` (en racionales), su recorte final (la
  envolvente ascendente de :func:`dijkstra` con la cara por el factor de malla y ``mín(recorte, S)``), la composición
  ``máx(partida, recorte)`` donde se admite el relleno y las cifras (volumen, área y altura máxima) como un bucle de Python
  por celda con ``fsum``, para comparar con ``design.buttress`` (RF-016-17).
- :func:`hand_net` (spec 017, T06; plan 017 §5.4 A1): la red 2D de la ruta **a mano**: la malla (la media de cada bloque de celdas con
  ``fsum`` y los nodos prohibidos o sin dato, con bucles de Python por celda), el grafo explícito de pasos admisibles (una lista de
  aristas por nodo, con los límites, los nodos intermedios de los pasos «de caballo» y ``|Δcota| ≤ pd·L + 2H``) y las distancias por
  **Bellman–Ford** (pasadas completas sobre todas las aristas hasta que ninguna mejora), para comparar con ``design.road_net``
  (RF-017-09, RF-017-11). Los rumbos son un parámetro (:data:`HAND_HEADINGS`, la lista de D-8 copiada aquí): con los 8 inmediatos
  muestra lo que no pasa con 8 (B2).
- :func:`hand_route` y :func:`hand_corridor` (spec 017, T09; plan 017 §5.4 A2 y §7.1): la ruta 3D de mínimo coste **por fuerza bruta**: el
  grafo explícito de estados ``(nodo, nivel, rumbo)`` construido entero (cada nivel de llegada de cada paso, sin tablas de saltos ni cota
  admisible), un Dijkstra completo con etiquetas enteras ``(coste en nanómetros, giros)`` y la ruta elegida recorriendo todas las aristas
  (el desempate de D-23), y el pasillo desde la red 2D de :func:`hand_net`, para comparar con ``design.road_route`` (RF-017-10, RF-017-09).

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
    "HAND_HEADINGS",
    "Displacement",
    "HandButtress",
    "HandFootprint",
    "HandLayers",
    "HandPlane",
    "HandRemoval",
    "HandRoute",
    "HandWall",
    "HandWallStretch",
    "brute_force_euclidean",
    "dijkstra",
    "euclidean_displacements",
    "hand_buttress",
    "hand_cell_slope_deg",
    "hand_corridor",
    "hand_crown",
    "hand_dilate",
    "hand_footprint",
    "hand_layers",
    "hand_net",
    "hand_plane",
    "hand_removal",
    "hand_route",
    "hand_share",
    "hand_stairs",
    "hand_volume",
    "hand_wall",
    "hand_zones",
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


# --- La huella de un acopio y el reparto de las celdas comunes, a mano (spec 016, T07; plan 016 A3) ---------------


def hand_dilate(mask: Sequence[Sequence[bool]], cell: float, radius_m: float) -> np.ndarray:
    """Las celdas a no más de ``radius_m`` m de alguna de ``mask`` (centro con centro, con la tolerancia de 10⁻⁹ m del
    disco de A1): la marca ampliada por su margen. Fuerza bruta (cada celda contra cada celda de la máscara)."""
    rows, cols = len(mask), len(mask[0])
    cells = [(r, c) for r in range(rows) for c in range(cols) if mask[r][c]]
    found = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            found[r, c] = any(math.hypot((r - i) * cell, (c - j) * cell) <= radius_m + 1e-9 for i, j in cells)
    return found


def _neighbours(r: int, c: int) -> tuple[tuple[int, int], ...]:
    return ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))


def hand_zones(mask: Sequence[Sequence[bool]]) -> list[tuple[tuple[int, int], ...]]:
    """Las zonas 4-conexas de ``mask`` (cada una, sus celdas ``(fila, columna)`` en orden de lectura) en el orden de su
    primera celda recorriendo la rejilla fila a fila. Una búsqueda en anchura: ni ``design.grids`` ni numpy."""
    rows, cols = len(mask), len(mask[0])
    seen = [[False] * cols for _ in range(rows)]
    zones: list[tuple[tuple[int, int], ...]] = []
    for r in range(rows):
        for c in range(cols):
            if not mask[r][c] or seen[r][c]:
                continue
            seen[r][c] = True
            queue, found = [(r, c)], []
            while queue:
                i, j = queue.pop()
                found.append((i, j))
                for a, b in _neighbours(i, j):
                    if 0 <= a < rows and 0 <= b < cols and mask[a][b] and not seen[a][b]:
                        seen[a][b] = True
                        queue.append((a, b))
            zones.append(tuple(sorted(found)))
    return zones


@dataclass(frozen=True, slots=True, eq=False)
class HandFootprint:
    """La huella de :func:`hand_footprint`: ``mask`` (la zona elegida con sus huecos rellenos), ``zones`` (las zonas
    conexas que tocan la marca y no se quedaron dentro de la huella: la elegida y las demás), ``other`` (las celdas de
    la mayor de las demás que quedan fuera de la huella, o ``None``) y ``first_edge`` (la primera celda en orden de
    lectura que llega al borde de la marca ampliada, o ``None``)."""

    mask: np.ndarray
    zones: int
    other: tuple[tuple[int, int], ...] | None
    first_edge: tuple[int, int] | None


def hand_footprint(z: Sequence[Sequence[float]], base: Sequence[Sequence[float]], mark: Sequence[Sequence[bool]],
                   enlarged: Sequence[Sequence[bool]], threshold: float) -> HandFootprint | None:
    """La huella de A3 a mano (RF-016-02, RF-016-04, RF-016-05): de las celdas de ``enlarged`` con ``z − base >
    threshold``, la zona conexa mayor (la primera si empatan) que toca ``mark``, con los huecos interiores rellenos
    (las celdas que no son de la zona y no se alcanzan desde fuera de la rejilla sin pasar por ella). ``None`` si
    ninguna zona toca la marca. Una celda sin dato (NaN) no está por encima de nada."""
    rows, cols = len(z), len(z[0])
    above = [[bool(enlarged[r][c]) and z[r][c] - base[r][c] > threshold for c in range(cols)] for r in range(rows)]
    touching = [zone for zone in hand_zones(above) if any(mark[r][c] for r, c in zone)]
    if not touching:
        return None
    chosen = max(touching, key=len)  # ante un empate, la primera
    inside = set(chosen)
    outside = {(-1, -1)}
    queue = [(-1, -1)]
    while queue:
        i, j = queue.pop()
        for a, b in _neighbours(i, j):
            if -1 <= a <= rows and -1 <= b <= cols and (a, b) not in outside and (a, b) not in inside:
                outside.add((a, b))
                queue.append((a, b))
    found = np.array([[(r, c) not in outside for c in range(cols)] for r in range(rows)])
    rest = [tuple(cell for cell in zone if not found[cell]) for zone in touching if zone is not chosen]
    rest = [cells for cells in rest if cells]
    region = [[bool(enlarged[r][c]) or bool(found[r, c]) for c in range(cols)] for r in range(rows)]

    def outer(i: int, j: int) -> bool:
        return not (0 <= i < rows and 0 <= j < cols and region[i][j])

    edge = next(((r, c) for r in range(rows) for c in range(cols)
                 if found[r, c] and any(outer(a, b) for a, b in _neighbours(r, c))), None)
    return HandFootprint(found, 1 + len(rest), max(rest, key=len) if rest else None, edge)


def hand_volume(z: Sequence[Sequence[float]], base: Sequence[Sequence[float]], mask: Sequence[Sequence[bool]],
                cell_area: float, threshold: float) -> float:
    """El volumen de A3 a mano (RF-016-02): ``fsum`` de ``(z − base)·área de celda`` en las celdas de ``mask`` donde
    ``z − base > threshold``, con un bucle de Python."""
    rows, cols = len(z), len(z[0])
    return math.fsum((z[r][c] - base[r][c]) * cell_area for r in range(rows) for c in range(cols)
                     if mask[r][c] and z[r][c] - base[r][c] > threshold)


def hand_share(footprints: Sequence[Sequence[Sequence[bool]]], marks: Sequence[Sequence[Sequence[bool]]]
               ) -> list[np.ndarray]:
    """El reparto de las celdas comunes de A3 a mano (RF-016-06): cada celda en las huellas de varias marcas va a la
    marca que la contiene si es una sola y, si la contienen varias o ninguna, a la **más próxima** de entre las que
    la contienen (o, si ninguna, de entre las que tienen la celda en su huella), por la distancia exacta al conjunto
    de celdas de la marca (el cuadrado de la distancia entre centros, en celdas², con enteros); a igual distancia,
    la primera. Devuelve las huellas nuevas, en el orden dado. Fuerza bruta."""
    rows, cols = len(footprints[0]), len(footprints[0][0])
    mark_cells = [[(r, c) for r in range(rows) for c in range(cols) if mark[r][c]] for mark in marks]

    def distance2(k: int, r: int, c: int) -> int | float:
        return min(((r - i) ** 2 + (c - j) ** 2 for i, j in mark_cells[k]), default=math.inf)

    found = [np.array(footprint, dtype=bool) for footprint in footprints]
    for r in range(rows):
        for c in range(cols):
            claimants = [k for k in range(len(footprints)) if footprints[k][r][c]]
            if len(claimants) < 2:
                continue
            containing = [k for k in claimants if marks[k][r][c]]
            pool = containing if containing else claimants
            owner = min(pool, key=lambda k: (distance2(k, r, c), k)) if len(pool) > 1 else pool[0]
            for k in claimants:
                found[k][r, c] = k == owner
    return found


@dataclass(frozen=True, slots=True)
class HandLayers:
    """Lo que da :func:`hand_layers`, por celda ``(fila, columna)`` de la huella: ``base``, ``thickness`` (``máx(z −
    base, 0)``), ``ground`` (``mín(z, base)``) y ``surface`` (``z``); ``volume`` (m³), el volumen de la huella (las
    celdas que pasan del umbral) y ``thickness_max`` (m)."""

    base: dict[tuple[int, int], float]
    thickness: dict[tuple[int, int], float]
    ground: dict[tuple[int, int], float]
    surface: dict[tuple[int, int], float]
    volume: float
    thickness_max: float


def hand_layers(z: Sequence[Sequence[float]], base: Sequence[Sequence[float]], mask: Sequence[Sequence[bool]],
                cell_area: float, threshold: float) -> HandLayers:
    """A5 a mano (RF-016-01, RF-016-09): en cada celda de ``mask`` (la huella), la base, el espesor ``máx(z − base, 0)``
    (nunca negativo: donde el terreno queda bajo la base, 0), el terreno sin acopios ``mín(z, base)`` y la superficie
    ``z``, y el volumen de la huella (``fsum`` de ``(z − base)·área de celda`` donde ``z − base > threshold``, como la
    011). Un bucle de Python por celda."""
    layers: tuple[dict[tuple[int, int], float], ...] = ({}, {}, {}, {})
    for r, row in enumerate(z):
        for c, level in enumerate(row):
            if not mask[r][c]:
                continue
            floor = base[r][c]
            layers[0][r, c] = floor
            layers[1][r, c] = level - floor if level - floor > 0.0 else 0.0
            layers[2][r, c] = level if level < floor else floor
            layers[3][r, c] = level
    volume = math.fsum((z[r][c] - base[r][c]) * cell_area for r, c in layers[1] if z[r][c] - base[r][c] > threshold)
    return HandLayers(*layers, volume, max(layers[1].values(), default=0.0))


@dataclass(frozen=True, slots=True)
class HandRemoval:
    """Lo que da :func:`hand_removal`: la superficie ``surface`` (``(filas, columnas)``, m), las cifras (m³) ``removed``
    (la columna retirada por debajo de la superficie de detección), ``resting`` (la de por encima), ``transition`` (lo
    que queda sobre la base en el dominio), ``kept`` (lo que queda en la huella donde el dominio no admite la retirada)
    y ``above`` (todo lo que la huella tiene sobre la base), las ``transition_cells`` y las celdas de la huella que se
    retiran (``admitted``), las que no (``held``) y las semillas (``ring``), por ``(fila, columna)``."""

    surface: np.ndarray
    removed: float
    resting: float
    transition: float
    kept: float
    above: float
    transition_cells: int
    admitted: frozenset[tuple[int, int]]
    held: frozenset[tuple[int, int]]
    ring: frozenset[tuple[int, int]]


def _overlap(low: float, high: float, floor: float, ceiling: float) -> float:
    """La longitud de ``[low, high]`` que cae en ``[floor, ceiling]`` (0 si no se tocan)."""
    return max(min(high, ceiling) - max(low, floor), 0.0)


def hand_removal(z: Sequence[Sequence[float]], base: Sequence[Sequence[float]],
                 detected: Sequence[Sequence[float]], footprint: Sequence[Sequence[bool]],
                 domain: Sequence[Sequence[bool]], *, step: float, tan: float, metric: str = "exact"
                 ) -> HandRemoval:
    """A6 a mano (RF-016-11, RF-016-13): la retirada de un acopio de ``footprint`` (con su ``base`` y la superficie con que
    se detectó, ``detected``, que solo se leen en la huella) de la superficie ``z`` (NaN, sin dato), con celdas de
    ``step`` m de lado, en el ``domain`` que admite la retirada y con la tangente efectiva ``tan`` (``tan θ`` por el
    factor de malla). Se retira lo que está en la huella, en el dominio y con dato; sus semillas son las celdas con dato que no se retiran y tocan (8
    vecinas) una que sí; la envolvente descendente de las semillas es ``máx_s [z_s − tan·paso·d]`` con la distancia
    euclídea entre centros (``metric="exact"``) o el *chamfer* 5×5 de :func:`dijkstra` (``"chamfer5"``), y la superficie
    nueva ``mín(z, máx(base, envolvente))`` en lo que se retira; lo demás, ``z``. Las cifras son la longitud de la
    columna que se quita ``[z', z]`` a cada lado de ``detected`` (retirado y apoyado), lo que queda sobre la base en lo
    que se retira (transición) y la columna sobre la base de la huella que el dominio no deja retirar (no retirado)."""
    nrows, ncols = len(z), len(z[0])
    cells = [(r, c) for r in range(nrows) for c in range(ncols)]
    has_data = {(r, c): math.isfinite(z[r][c]) for r, c in cells}
    admitted = {(r, c) for r, c in cells if footprint[r][c] and domain[r][c] and has_data[r, c]}
    held = {(r, c) for r, c in cells if footprint[r][c] and not (domain[r][c] and has_data[r, c]) and has_data[r, c]}
    ring = {(r, c) for r, c in cells if (r, c) not in admitted and has_data[r, c]
            and any((r + dr, c + dc) in admitted for dr in (-1, 0, 1) for dc in (-1, 0, 1))}
    if metric == "exact":
        def envelope(r: int, c: int) -> float:
            return max((z[rs][cs] - tan * step * math.hypot(r - rs, c - cs) for rs, cs in ring), default=-math.inf)
    elif metric == "chamfer5":
        seeds = np.full((nrows, ncols), np.nan)
        for r, c in ring:
            seeds[r, c] = z[r][c]
        found = dijkstra(seeds, tan, step, direction="down")

        def envelope(r: int, c: int) -> float:
            return float(found[r, c])
    else:
        raise ValueError(f"la métrica es «exact» o «chamfer5», no {metric!r}")
    surface = np.array([[z[r][c] for c in range(ncols)] for r in range(nrows)], dtype=np.float64)
    removed: list[float] = []
    resting: list[float] = []
    transition: list[float] = []
    for r, c in sorted(admitted):
        level, floor = z[r][c], base[r][c]
        new = min(level, max(floor, envelope(r, c)))
        surface[r, c] = new
        removed.append(_overlap(new, level, -math.inf, detected[r][c]))
        resting.append(_overlap(new, level, detected[r][c], math.inf))
        transition.append(max(new - floor, 0.0))
    area = step * step
    above = [max(z[r][c] - base[r][c], 0.0) for r, c in cells if footprint[r][c] and has_data[r, c]]
    kept = [max(z[r][c] - base[r][c], 0.0) for r, c in sorted(held)]
    return HandRemoval(surface, math.fsum(removed) * area, math.fsum(resting) * area, math.fsum(transition) * area,
                       math.fsum(kept) * area, math.fsum(above) * area,
                       sum(1 for value in transition if value > 0.0), frozenset(admitted), frozenset(held),
                       frozenset(ring))


@dataclass(frozen=True, slots=True)
class HandWallStretch:
    """Un tramo de la pared de :func:`hand_wall`: sus ``pairs``, su ``height`` (m: la mayor cota de sus parejas menos la
    menor), el ángulo de su peor pareja (``angle``, °), su mayor salto creado (``step``, m) y el punto medio de esa pareja
    (``x``, ``y``: absolutos). El primer tramo es el de la primera celda de norte a sur y de oeste a este."""

    pairs: int
    height: float
    angle: float
    step: float
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class HandWall:
    """Lo que da :func:`hand_wall`: las parejas del borde (``pairs``), las que pasan del salto admitido (``over``) y los
    ``stretches`` (los tramos de las que además pasan de la inclinación)."""

    pairs: int
    over: int
    stretches: tuple[HandWallStretch, ...]


def hand_wall(z: Sequence[Sequence[float]], surface: Sequence[Sequence[float]], admitted: Sequence[Sequence[bool]], *,
              dx: float, dy: float, west: float, north: float, thickness: float, threshold: float,
              limit_deg: float) -> HandWall:
    """A8 a mano (RF-016-15): la pared que deja la ``surface`` nueva frente a la de partida ``z`` (NaN, sin dato; celdas
    de ``dx`` × ``dy`` m con la esquina noroeste en ``west``, ``north``). Una celda está **movida** si está en
    ``admitted``, tiene dato en las dos y ``|surface − z|`` pasa de ``thickness``; una **pareja** es de dos celdas
    vecinas (4 vecinos) con dato en las dos, una movida y la otra no; su **salto creado** es ``|S_a − S_b| − |z_a −
    z_b|`` y su **inclinación**, ``atan(|S_a − S_b| / distancia)`` en grados. Cuentan las parejas con un salto creado
    **mayor** que ``threshold`` y una inclinación **mayor** que ``limit_deg``; sus celdas forman los **tramos** (4
    vecinos entre celdas) y de cada uno se da la altura (mayor cota de las dos celdas de sus parejas menos la menor), la
    inclinación de su peor pareja (a igual inclinación, la primera de norte a sur y de oeste a este), su mayor salto
    creado y el punto medio de esa pareja."""
    nrows, ncols = len(z), len(z[0])

    def valid(r: int, c: int) -> bool:
        return math.isfinite(z[r][c]) and math.isfinite(surface[r][c])

    def moved(r: int, c: int) -> bool:
        return bool(admitted[r][c]) and valid(r, c) and abs(surface[r][c] - z[r][c]) > thickness

    edge = over = 0
    found: list[tuple[int, int, tuple[int, int], tuple[int, int], float, float]] = []
    for r in range(nrows):
        for c in range(ncols):
            for d_row, d_col, distance in ((0, 1, dx), (1, 0, dy)):
                r2, c2 = r + d_row, c + d_col
                if r2 >= nrows or c2 >= ncols or not (valid(r, c) and valid(r2, c2)) or moved(r, c) == moved(r2, c2):
                    continue
                edge += 1
                drop = abs(surface[r][c] - surface[r2][c2])
                created = drop - abs(z[r][c] - z[r2][c2])
                if created <= threshold:
                    continue
                over += 1
                angle = math.degrees(math.atan(drop / distance))
                if angle > limit_deg:
                    found.append((2 * r + d_row, 2 * c + d_col, (r, c), (r2, c2), angle, created))
    cells = {cell for item in found for cell in item[2:4]}
    stretches: list[HandWallStretch] = []
    seen: set[tuple[int, int]] = set()
    for first in sorted(cells):
        if first in seen:
            continue
        members = {first}
        queue = [first]
        while queue:
            r, c = queue.pop()
            for near in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if near in cells and near not in members:
                    members.add(near)
                    queue.append(near)
        seen |= members
        mine = sorted((item for item in found if item[2] in members), key=lambda item: (item[0], item[1]))
        worst = max(mine, key=lambda item: (item[4], -item[0], -item[1]))
        levels = [surface[r][c] for item in mine for r, c in item[2:4]]
        stretches.append(HandWallStretch(
            len(mine), max(levels) - min(levels), worst[4], max(item[5] for item in mine),
            west + (worst[1] + 1) * dx / 2.0, north - (worst[0] + 1) * dy / 2.0))
    return HandWall(edge, over, tuple(stretches))


# --- El contrafuerte, a mano (spec 016, T26; plan 016 A10) ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HandButtress:
    """Lo que da :func:`hand_buttress`, todo ``(filas, columnas)``: las ``seeds`` (booleana), la ``envelope`` descendente (m;
    NaN más allá del alcance), el escalonado en relleno ``stairs``, su recorte ``stepped``, la ``surface`` de diseño y las
    cifras: el ``volume_m3`` (lo que la superficie sube sobre la de partida), el ``area_m2`` (las celdas que suben), las
    ``cells`` que suben y la ``height_max_m`` (lo más que sube una celda; 0 si ninguna)."""

    seeds: np.ndarray
    envelope: np.ndarray
    stairs: np.ndarray
    stepped: np.ndarray
    surface: np.ndarray
    volume_m3: float
    area_m2: float
    cells: int
    height_max_m: float


def hand_buttress(start: object, zone: object, allowed: object, *, crown: float, height: float, tan_face: float,
                  berm: float, anchor: float, mesh: float = 1.0, step: float, metric: str = "exact",
                  reach: float | None = None) -> HandButtress:
    """A10 a mano (RF-016-17): el contrafuerte de la zona de coronación ``zone`` (booleana) sobre la superficie ``start`` (NaN,
    sin dato) en el relleno admitido ``allowed`` (booleana), con celdas de ``step`` m de lado, la cota de coronación ``crown``
    y el perfil ``height``, ``tan_face``, ``berm`` y ``anchor`` con su factor de malla ``mesh``. Las semillas son las celdas
    de la zona con dato y ``start < crown``, a la cota ``crown``; la envolvente descendente de las semillas tiene la
    tangente del talud general por el factor de malla, ``mesh · h / (h/tan α + B)``, con la distancia euclídea entre centros
    (``metric="exact"``: :func:`brute_force_euclidean`) o el *chamfer* 5×5 (``"chamfer5"``: :func:`dijkstra`), y NaN más
    allá de ``reach`` (m) si se da; el escalonado es el de :func:`hand_stairs` en relleno (racionales); su recorte, la
    envolvente ascendente de :func:`dijkstra` con ``tan α · mesh`` (siempre el *chamfer*, como el recorte de la 013)
    acotada por la envolvente; y la superficie, ``máx(start, recorte)`` en las celdas admitidas con dato en las dos y
    ``start`` en las demás. Las cifras: un bucle de Python por celda, la suma con ``fsum``."""
    level = np.asarray(start, dtype=np.float64)
    inside = np.asarray(zone, dtype=bool)
    admitted = np.asarray(allowed, dtype=bool)
    nrows, ncols = level.shape
    tangent = mesh * height / (height / tan_face + berm)
    seeds = np.zeros(level.shape, dtype=bool)
    seed_levels = np.full(level.shape, np.nan)
    for r in range(nrows):
        for c in range(ncols):
            if inside[r, c] and math.isfinite(level[r, c]) and level[r, c] < crown:
                seeds[r, c] = True
                seed_levels[r, c] = crown
    if metric == "exact":
        envelope = brute_force_euclidean(seed_levels, tangent, step, direction="down")
    elif metric == "chamfer5":
        envelope = dijkstra(seed_levels, tangent, step, direction="down")
    else:
        raise ValueError(f"la métrica es «exact» o «chamfer5», no {metric!r}")
    if reach is not None:
        origin = np.where(seeds, 0.0, np.nan)
        far = (brute_force_euclidean(origin, 1.0, step, direction="up") if metric == "exact"
               else dijkstra(origin, 1.0, step, direction="up"))
        envelope = np.where(far > reach, np.nan, envelope)
    stairs = hand_stairs(envelope, height, tan_face, berm, anchor, fill=True)
    finite = np.isfinite(stairs)
    trimmed = dijkstra(np.where(finite, stairs, np.nan), tan_face * mesh, step, direction="up")
    stepped = np.where(finite, np.minimum(trimmed, envelope), np.nan)
    surface = level.copy()
    rise: list[float] = []
    for r in range(nrows):
        for c in range(ncols):
            if admitted[r, c] and math.isfinite(level[r, c]) and math.isfinite(stepped[r, c]):
                surface[r, c] = max(level[r, c], stepped[r, c])
            if surface[r, c] > level[r, c]:
                rise.append(float(surface[r, c] - level[r, c]))
    area = step * step
    return HandButtress(seeds, envelope, stairs, stepped, surface, math.fsum(rise) * area, len(rise) * area, len(rise),
                        max(rise, default=0.0))


# --- La red 2D de la ruta (spec 017, T06; plan 017 §5.4 A1) ------------------------------------------------------------------------

HAND_HEADINGS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (1, 1), (2, 1), (1, 0), (2, -1), (1, -1), (1, -2),
    (0, -1), (-1, -2), (-1, -1), (-2, -1), (-1, 0), (-2, 1), (-1, 1), (-1, 2))
"""Los 16 pasos ``(dx, dy)`` a un nodo vecino (``dx`` al este y ``dy`` al norte), en sentido horario desde el norte (D-8): una copia
**independiente** de la de ``design.road_net``; los 8 inmediatos (``|dx|, |dy| ≤ 1``) son los de índice par, ``HAND_HEADINGS[::2]``."""
HAND_STEP_TOLERANCE_M = 1e-9
"""El margen (m) de ``|Δcota| ≤ pd·L + 2H``: el de A2 (``10⁻⁹``), que la red 2D comparte para ser una cota inferior de la ruta 3D."""


def _hand_blocks(surface: Sequence[Sequence[float]], forbidden: Sequence[Sequence[bool]] | None, factor: int
                 ) -> tuple[dict[tuple[int, int], float], int, int]:
    """La malla de A1 **a mano**: la cota de cada nodo que se pisa (la media, con ``fsum``, de las celdas de su bloque de ``factor ×
    factor``; no se pisa uno con alguna celda sin dato, fuera de la rejilla —los bloques incompletos— o en ``forbidden``) y el número de filas
    y de columnas de nodos."""
    rows = len(surface)
    cols = len(surface[0])
    ni, nj = -(-rows // factor), -(-cols // factor)
    height: dict[tuple[int, int], float] = {}
    for i in range(ni):
        for j in range(nj):
            cells = [(r, c) for r in range(i * factor, (i + 1) * factor) for c in range(j * factor, (j + 1) * factor)]
            if any(r >= rows or c >= cols for r, c in cells):
                continue
            values = [float(surface[r][c]) for r, c in cells]
            if not all(math.isfinite(v) for v in values):
                continue
            if forbidden is not None and any(bool(forbidden[r][c]) for r, c in cells):
                continue
            height[(i, j)] = math.fsum(values) / (factor * factor)
    return height, ni, nj


def _hand_between(dx: int, dy: int) -> list[tuple[int, int]]:
    """Los dos nodos que atraviesa la recta de un paso «de caballo» ``(dx, dy)`` como desplazamientos ``(mx, my)``; ninguno en los demás."""
    if abs(dx) == 2:
        return [(dx // 2, 0), (dx // 2, dy)]
    if abs(dy) == 2:
        return [(0, dy // 2), (dx, dy // 2)]
    return []


def hand_net(surface: Sequence[Sequence[float]], forbidden: Sequence[Sequence[bool]] | None, factor: int, cell_m: float, pd: float,
             hmax: float, targets: Sequence[tuple[int, int]], *,
             headings: Sequence[tuple[int, int]] = HAND_HEADINGS) -> np.ndarray:
    """La red 2D de A1 **a mano** (RF-017-09, RF-017-11): la longitud mínima (m) desde los nodos ``targets`` ``(i, j)`` a cada nodo de la
    malla de bloques de ``factor × factor`` celdas de ``cell_m`` m sobre ``surface`` (fila 0 al norte; ``NaN``, sin dato) como un
    array ``(ni, nj)`` con ``inf`` donde no llega. La cota de un nodo es la media de las celdas de su bloque (``fsum``); no se pisa
    un nodo con alguna celda sin dato, fuera de la rejilla (los bloques incompletos) o en ``forbidden``. Una arista del grafo explícito
    va del nodo ``(i, j)`` al ``(i − dy, j + dx)`` para cada rumbo ``(dx, dy)`` de ``headings`` si los dos se pisan, ni los dos nodos
    que la recta atraviesa en un paso «de caballo» están prohibidos y ``|Δcota| ≤ pd·L + 2·hmax`` (``L = factor·cell_m·√(dx² + dy²)``,
    con ``pd`` en tanto por uno); las distancias, por Bellman–Ford: pasadas completas sobre todas las aristas hasta que ninguna mejore.
    Un destino que no se pisa no cuenta. Bucles de Python, sin ``design.road_net`` ni numpy en el cálculo."""
    height, ni, nj = _hand_blocks(surface, forbidden, factor)
    edges: dict[tuple[int, int], list[tuple[tuple[int, int], float]]] = {node: [] for node in height}
    for (i, j), z0 in height.items():
        for dx, dy in headings:
            other = (i - dy, j + dx)
            if other not in height:
                continue
            if any((i - my, j + mx) not in height for mx, my in _hand_between(dx, dy)):
                continue
            length = factor * cell_m * math.hypot(dx, dy)
            if abs(height[other] - z0) <= pd * length + 2.0 * hmax + HAND_STEP_TOLERANCE_M:
                edges[(i, j)].append((other, length))
    best = {node: math.inf for node in height}
    for node in targets:
        if node in best:
            best[node] = 0.0
    for _ in range(len(height)):
        changed = False
        for node, found in edges.items():
            reached = best[node]
            if reached == math.inf:
                continue
            for other, length in found:
                if reached + length < best[other]:
                    best[other] = reached + length
                    changed = True
        if not changed:
            break
    out = np.full((ni, nj), math.inf)
    for (i, j), value in best.items():
        out[i, j] = value
    return out


# --- La ruta 3D de la pista (spec 017, T09; plan 017 §5.4 A2 y §7.1) ---------------------------------------------------------------

HAND_COST_SCALE = 1_000_000_000
"""Las unidades de coste por metro: el coste del paso es un entero en nanómetros, redondeado una vez por paso (D-23: empates exactos)."""
HAND_LEVEL_MARGIN_M = 1e-9
"""El margen (m) de la pendiente de un paso, ``|Δcota| ≤ pd·L + 10⁻⁹``: el de A2."""


@dataclass(frozen=True, slots=True)
class HandRoute:
    """La ruta de :func:`hand_route`: ``found``; con ruta, su ``cost_units`` (entero, en :data:`HAND_COST_SCALE` unidades por metro), los
    ``turns``, los ``nodes`` ``(i, j)`` del origen al destino, el índice de rumbo con que se llega a cada uno (``headings``; el primero es
    el de partida, libre) y el ``levels`` (múltiplos del paso de cota sobre el terreno del nodo) de cada nodo. Siempre, los ``states`` y las
    ``edges`` del grafo explícito, y ``tied``: **cuántas veces el desempate decidió** (en la ruta, los estados cuyo origen se eligió entre
    dos o más con la misma etiqueta, y el estado de llegada si dos rumbos la compartían)."""

    found: bool
    cost_units: int | None
    turns: int | None
    nodes: tuple[tuple[int, int], ...]
    headings: tuple[int, ...]
    levels: tuple[int, ...]
    states: int
    edges: int
    tied: int


def _hand_weights(weight: Sequence[Sequence[float]] | None, factor: int, ni: int, nj: int) -> dict[tuple[int, int], float]:
    """El peso de cada nodo: el mayor de las celdas de su bloque (1 sin ``weight``)."""
    if weight is None:
        return {(i, j): 1.0 for i in range(ni) for j in range(nj)}
    rows, cols = len(weight), len(weight[0])
    found: dict[tuple[int, int], float] = {}
    for i in range(ni):
        for j in range(nj):
            found[(i, j)] = max(float(weight[r][c]) for r in range(i * factor, min((i + 1) * factor, rows))
                                for c in range(j * factor, min((j + 1) * factor, cols)))
    return found


def _hand_top(hmax: float, level_step_m: float) -> int:
    """El número de niveles a cada lado, ``M = ⌊H/Δz⌋``, en aritmética racional sobre los decimales dados (``14/0,28`` es 50, no 49,99…)."""
    return math.floor(Fraction(repr(float(hmax))) / Fraction(repr(float(level_step_m))))


def hand_route(surface: Sequence[Sequence[float]], forbidden: Sequence[Sequence[bool]] | None, factor: int, cell_m: float, pd: float,
               hmax: float, level_step_m: float, lambda_per_m: float, turn_m: float, origin: tuple[int, int],
               destination: tuple[int, int], *, start_level_m: float | None = None, end_level_m: float | None = None,
               weight: Sequence[Sequence[float]] | None = None, domain: Sequence[Sequence[bool]] | None = None,
               headings: Sequence[tuple[int, int]] = HAND_HEADINGS) -> HandRoute:
    """La ruta 3D de mínimo coste de A2 **por fuerza bruta** (RF-017-10, RF-017-11, D-23): un Dijkstra **completo** (sin parar en el destino) sobre
    el grafo explícito de estados ``(i, j, m, h)`` —nodo de la malla de bloques de ``factor × factor`` celdas de ``cell_m`` m sobre
    ``surface``, nivel ``m ∈ [−M, M]`` con ``M = ⌊hmax/level_step_m⌋`` (la cota es la del terreno del nodo más ``m·level_step_m``) y rumbo
    ``h``—, que se **construye entero** (cada estado, cada rumbo ``h' ∈ {h − 1, h, h + 1}`` módulo el número de rumbos y **cada** nivel de
    llegada, comprobando la pendiente ``|Δcota| ≤ pd·L + 10⁻⁹`` con las cotas: sin tablas de saltos) y se recorre con una cola.

    - **El coste del paso**: ``int(10⁹ · L · (1 + λ·Δz·(|m| + |m'|)/2) · w + ½)`` (``w``, la media de los pesos de los dos nodos, el mayor de
      las celdas de su bloque) más, si cambia el rumbo, ``int(10⁹ · giro + ½)``; la etiqueta de un estado es ``(coste, giros)``, comparada
      por orden lexicográfico (el menor número de giros a igual coste). Los costes son **enteros**: los empates son exactos.
    - **Desde** el nodo ``origin`` con el nivel más próximo a ``start_level_m`` (``None``: el del terreno) y los 16 rumbos a coste 0 (el rumbo
      de partida es libre); **hasta** ``destination`` con el nivel más próximo a ``end_level_m``. Los nodos que se pisan son los de
      :func:`hand_net` (la media de su bloque; ni una celda sin dato o prohibida) y, si hay ``domain`` (el pasillo, :func:`hand_corridor`),
      solo los de él (los nodos intermedios de un paso «de caballo» solo han de pisarse).
    - **La ruta** es la del estado de llegada de menor ``(coste, giros, rumbo)`` y, hacia atrás, de cada estado su origen de **menor
      ``(rumbo anterior, salto de nivel)``** entre los que dan su misma etiqueta (D-23: gana el menor número de giros y, a igual número, el
      primer rumbo en sentido horario desde el norte). Se elige recorriendo **todas** las aristas del grafo, no mientras se relajan.

    Un nivel de partida o de llegada fuera de ``±M`` no deja estado: sin ruta."""
    height, ni, nj = _hand_blocks(surface, forbidden, factor)
    usable = {node for node in height if domain is None or bool(domain[node[0]][node[1]])}
    weights = _hand_weights(weight, factor, ni, nj)
    count = len(headings)
    top = _hand_top(hmax, level_step_m)
    turn_units = int(turn_m * HAND_COST_SCALE + 0.5)
    length_of = [factor * cell_m * math.hypot(dx, dy) for dx, dy in headings]
    nothing = HandRoute(False, None, None, (), (), (), 0, 0, 0)

    def level_near(wanted: float | None, node: tuple[int, int]) -> int | None:
        found = 0 if wanted is None else math.floor((wanted - height[node]) / level_step_m + 0.5)
        return found if -top <= found <= top else None

    if origin not in usable or destination not in usable:
        return nothing
    start_level, end_level = level_near(start_level_m, origin), level_near(end_level_m, destination)
    if start_level is None or end_level is None:
        return nothing
    State = tuple[int, int, int, int]  # (i, j, m, h)
    edges: list[tuple[State, State, int, int]] = []
    out: dict[State, list[tuple[State, int, int]]] = {}
    states = 0
    for node in sorted(usable):
        i, j = node
        for m in range(-top, top + 1):
            for h in range(count):
                states += 1
                source: State = (i, j, m, h)
                for other in ((h - 1) % count, h, (h + 1) % count):
                    dx, dy = headings[other]
                    target = (i - dy, j + dx)
                    if target not in usable or any((i - my, j + mx) not in height for mx, my in _hand_between(dx, dy)):
                        continue
                    for m2 in range(-top, top + 1):
                        rise = (height[target] + m2 * level_step_m) - (height[node] + m * level_step_m)
                        if abs(rise) > pd * length_of[other] + HAND_LEVEL_MARGIN_M:
                            continue
                        both = abs(m) + abs(m2)
                        units = int(HAND_COST_SCALE * length_of[other] * (1.0 + lambda_per_m * level_step_m * both * 0.5)
                                    * ((weights[node] + weights[target]) * 0.5) + 0.5)
                        turned = other != h
                        step: tuple[State, State, int, int] = (source, (target[0], target[1], m2, other),
                                                              units + (turn_units if turned else 0), int(turned))
                        edges.append(step)
                        out.setdefault(source, []).append((step[1], step[2], step[3]))
    starts = [(origin[0], origin[1], start_level, h) for h in range(count)]
    label: dict[State, tuple[int, int]] = {state: (0, 0) for state in starts}
    queue = [(0, 0, state) for state in starts]
    heapq.heapify(queue)
    while queue:
        cost, turns, state = heapq.heappop(queue)
        if label[state] != (cost, turns):
            continue
        for other_state, units, turned in out.get(state, ()):
            candidate = (cost + units, turns + turned)
            if other_state not in label or candidate < label[other_state]:
                label[other_state] = candidate
                heapq.heappush(queue, (candidate[0], candidate[1], other_state))
    arrivals = sorted((label[(destination[0], destination[1], end_level, h)], h) for h in range(count)
                      if (destination[0], destination[1], end_level, h) in label)
    if not arrivals:
        return HandRoute(False, None, None, (), (), (), states, len(edges), 0)
    best_parent: dict[State, tuple[int, int, State]] = {}
    candidates: dict[State, int] = {}
    for source, target_state, units, turned in edges:
        if source not in label or target_state not in label:
            continue
        if (label[source][0] + units, label[source][1] + turned) != label[target_state]:
            continue
        candidates[target_state] = candidates.get(target_state, 0) + 1
        key = (source[3], target_state[2] - source[2], source)
        if target_state not in best_parent or key < best_parent[target_state]:
            best_parent[target_state] = key
    (cost, turns), arrival_heading = arrivals[0]
    tied = 1 if len(arrivals) > 1 and arrivals[1][0] == arrivals[0][0] else 0
    state = (destination[0], destination[1], end_level, arrival_heading)
    chain = [state]
    while state not in starts:
        tied += candidates[state] > 1
        state = best_parent[state][2]
        chain.append(state)
    chain.reverse()
    return HandRoute(True, cost, turns, tuple((s[0], s[1]) for s in chain), tuple(s[3] for s in chain), tuple(s[2] for s in chain),
                     states, len(edges), tied)


def hand_corridor(surface: Sequence[Sequence[float]], forbidden: Sequence[Sequence[bool]] | None, factor: int, cell_m: float, pd: float,
                  hmax: float, origin: tuple[int, int], destination: tuple[int, int], margin_m: float) -> np.ndarray:
    """El pasillo de la ruta **a mano** (RF-017-09): los nodos con ``d_origen + d_destino ≤ la más corta + margin_m`` (con 10⁻⁹ relativo para el
    último bit de las sumas), con las dos distancias de :func:`hand_net` (Bellman–Ford); vacío si el origen no alcanza el destino. Un array
    ``(ni, nj)`` booleano."""
    from_origin = hand_net(surface, forbidden, factor, cell_m, pd, hmax, [origin])
    from_destination = hand_net(surface, forbidden, factor, cell_m, pd, hmax, [destination])
    shortest = float(from_destination[origin])
    if not math.isfinite(shortest):
        return np.zeros(from_origin.shape, dtype=bool)
    return (from_origin + from_destination) <= shortest + margin_m + 1e-9 * shortest
