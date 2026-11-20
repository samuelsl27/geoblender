# SPDX-License-Identifier: GPL-3.0-or-later
"""La malla de la ruta, los 16 rumbos y la red 2D de una pista (spec 017, T06; HU-017-1; RF-017-09, 11 y 06; RNF-017-01 y 06;
plan 017 §5.4 A0 y A1, §5.7 P-6 y P-13, §7.3 y §9; D-8, D-10 y D-23).

Lo que da, todo en el dominio (Python y numpy, sin Blender), con las coordenadas absolutas en float64 (regla 4 de AGENTS.md):

- **La malla** (:func:`route_mesh` → :class:`RouteMesh`; D-10, P-6): un **múltiplo entero del paso del proyecto** (si no lo es,
  ``ValueError``); el **nodo** es un bloque de ``k × k`` celdas y su cota, **la media** de las del bloque. Un nodo con alguna
  celda sin dato (o fuera de la rejilla: los bloques incompletos del sur y del este), o que las máscaras prohíben pisar (alguna
  celda de su bloque está en ``mask``), **no se pisa**. La malla es **derivada y solo para buscar**: ninguna cifra de volumen ni
  de longitud de la pista sale de ella (RF-017-09), las de la pista salen de su eje y de la rejilla del proyecto. Con ``avoid_weight``
  (el peso ≥ 1 de las zonas «preferible no afectar» de RF-017-06) cada nodo lleva el mayor de las celdas de su bloque: un nodo
  «ve» la zona si **alguna** celda de su bloque está en ella (plan §5.8 H-6); la afección que se dice sale de la rejilla.
- **Los 16 rumbos** (:data:`HEADINGS`; D-8 y D-23, RF-017-11): los pasos ``(dx, dy)`` de un nodo a su vecino —``dx`` al este y
  ``dy`` al norte— entre ``{(±1, 0), (0, ±1), (±1, ±1), (±2, ±1), (±1, ±2)}`` (los 8 inmediatos y los 8 «de caballo»),
  **numerados en sentido horario desde el norte** (el 0 es ``(0, 1)``, el 4 ``(1, 0)``, el 8 ``(0, -1)`` y el 12 ``(-1, 0)``). **No se
  ofrece 8**: ninguna función de este módulo admite otro número de rumbos (con 8, en un talud del 38 % no había solución al 10 %: B2).
  En la malla la fila 0 es el norte, así que el paso ``(dx, dy)`` de un nodo ``(i, j)`` va al ``(i − dy, j + dx)``.
- **Los pasos admisibles** (:func:`step_masks`; RF-017-09): un paso de un nodo es admisible si ni él ni su extremo ni, en los pasos
  «de caballo», los dos nodos intermedios que la recta atraviesa están prohibidos o sin dato, y ``|Δcota| ≤ pd·L(h) + 2H``: la
  condición **necesaria** de una ruta con esa altura máxima de desmonte y terraplén (con ``H = 0``, la pista que sigue el terreno).
  Son 16 máscaras de la forma de la malla, construidas por desplazamientos de numpy (13 ms con 175.525 nodos medidos).
- **La red 2D** (:func:`network_steps` → :class:`Network`; A1, P-13, plan §9): un **Dijkstra con ``heapq``**, sobre listas planas y
  la malla con un marco de dos nodos (sin comprobar límites), desde el destino (o desde un conjunto de nodos: el destino por cota,
  T08) y, aparte, desde el origen: el grafo es no dirigido. **Un bucle de Python por nodo extraído**: es la excepción al principio
  9 que pide y aprueba el plan §9 (S-2), con el presupuesto y los pasos como condición; la relajación vectorizada por
  desplazamientos cuesta ×9 a ×14 más y no tiene tope de iteraciones (``docs/trampas.md`` §2: 3,0 y 4,5 s frente a 0,35 s por corrida
  con 175.525 nodos). Va **por pasos** de :data:`STEP_BUDGET_S` (0,05 s) como mucho (``pace_progress``), cediendo cada
  :data:`NODES_PER_UNIT` nodos extraídos: con progreso y cancelación (cerrar el generador no deja nada).
- **El pasillo** (:func:`corridor` → :class:`Corridor`; RF-017-09): si el origen es alcanzable, la **cota inferior** de la
  longitud de la ruta (m) y los nodos cuya longitud mínima desde el origen más la que les queda hasta el destino no pasa de la
  más corta más la **holgura** ``margin_m``. **Holgura, no ancho**: con 60 m son ±214 m a mitad de una ruta de 1,5 km, de 21.978 a
  31.856 nodos y no los 5.640 de una franja de 60 m de ancho (``docs/trampas.md`` §2).

Las cifras del cálculo van en tanto por uno (``pd`` es ``0,10``, no ``10``) y en metros. Los errores del programa son ``ValueError`` o
``TypeError`` (las entradas se comprueban al llamar, no al avanzar); que la malla pedida sea un múltiplo del paso del proyecto, y
la persona que ha escrito otro número, lo rechaza la preparación de la pista (T19) con su capa, su pista y su valor (RF-017-04).

**Perezoso** (RNF-001-03): ni ``design.model`` ni nada del arranque lo importan; lo pide quien traza una pista.
"""

from __future__ import annotations

import heapq
import math
import numbers
from collections.abc import Generator, Iterator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .seeds import pace_progress

__all__ = [
    "HEADINGS",
    "HEADING_COUNT",
    "NODES_PER_UNIT",
    "STEP_BUDGET_S",
    "STEP_UNITS",
    "Corridor",
    "Network",
    "RouteMesh",
    "corridor",
    "mesh_factor",
    "network_steps",
    "route_mesh",
    "step_masks",
]

HEADINGS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (1, 1), (2, 1), (1, 0), (2, -1), (1, -1), (1, -2),
    (0, -1), (-1, -2), (-1, -1), (-2, -1), (-1, 0), (-2, 1), (-1, 1), (-1, 2))
"""Los 16 rumbos de avance (D-8, D-23, RF-017-11): los pasos ``(dx, dy)`` a un nodo vecino (``dx`` al este y ``dy`` al norte), en
sentido horario desde el norte. Los azimuts (desde el norte, en °) van de 0 a 333,43 y los huecos entre dos contiguos son de 18,43° o
de 26,57° (no son equiespaciados): con ellos la ruta de un plano sin restricciones no pasa de la recta en más de
1/cos(13,28°) − 1 = 2,75 %."""
HEADING_COUNT = len(HEADINGS)
"""16: **el único número de rumbos** (RF-017-11); ninguna función de este módulo tiene un parámetro para otro."""
STEP_UNITS: tuple[float, ...] = tuple(math.hypot(dx, dy) for dx, dy in HEADINGS)
"""La longitud de cada paso en unidades de malla (``√(dx² + dy²)``): 1, √2 o √5; la del paso ``h`` es ``mesh_m · STEP_UNITS[h]``."""
NODES_PER_UNIT = 2_000
"""Los nodos que se extraen de la cola antes de ceder el hilo: el trabajo se parte en unidades de esta cuenta y ``pace_progress`` las
agrupa en pasos de ``STEP_BUDGET_S`` (≈ 2 µs por nodo extraído con sus 16 rumbos: una unidad son unos 4 ms)."""

_PAD = 2
"""El marco de nodos que rodea la malla en la red 2D (el mayor paso es de dos nodos): con él, ningún índice sale de las listas."""
_STEP_TOLERANCE_M = 1e-9
"""El margen (m) con que se compara ``|Δcota|`` con ``pd·L + 2H``: la red 2D es una cota inferior de la ruta 3D, que usa el mismo."""
_CORRIDOR_TOLERANCE = 1e-9
"""La parte (relativa a la ruta más corta) con que se compara ``d_origen + d_destino``: las dos distancias suman en órdenes distintos y
difieren en el último bit; con la holgura 0 el pasillo es la ruta más corta, no un cabo suelto."""
_PHASE = "road_net"
_RUNNING = "Calculando la red 2D de la ruta…"
_FINISHED = "Red 2D de la ruta lista"
_INF = math.inf


# --- Ayudantes -----------------------------------------------------------------------------------------------------------------


def _finite(value: object, what: str, *, minimum: float = 0.0, strict: bool = False) -> float:
    """``value`` como ``float`` finito y ``≥ minimum`` (o ``>`` con ``strict``); ``TypeError`` si no es un número real."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < minimum or (strict and number == minimum):
        raise ValueError(f"{what} es un número finito {'mayor que' if strict else 'no menor que'} {minimum:g}, no {value!r}")
    return number


def _shifted(values: np.ndarray, d_row: int, d_col: int, fill: object) -> np.ndarray:
    """``out[i, j] = values[i + d_row, j + d_col]`` y ``fill`` donde esa posición sale de la malla (un array nuevo)."""
    out = np.full(values.shape, fill, dtype=values.dtype)
    rows, cols = values.shape
    i0, i1 = max(0, -d_row), min(rows, rows - d_row)
    j0, j1 = max(0, -d_col), min(cols, cols - d_col)
    if i0 < i1 and j0 < j1:
        out[i0:i1, j0:j1] = values[i0 + d_row:i1 + d_row, j0 + d_col:j1 + d_col]
    return out


def _readonly(values: np.ndarray) -> np.ndarray:
    """Una vista de solo lectura de ``values`` (no cambia las banderas del array de quien lo da)."""
    view = values.view()
    view.flags.writeable = False
    return view


def _intermediates(dx: int, dy: int) -> tuple[tuple[int, int], ...]:
    """Los dos nodos que atraviesa la recta de un paso «de caballo» ``(dx, dy)`` (los 8 inmediatos no atraviesan ninguno)."""
    if abs(dx) == 2:
        return ((dx // 2, 0), (dx // 2, dy))
    if abs(dy) == 2:
        return ((0, dy // 2), (dx, dy // 2))
    return ()


_INTERMEDIATES = tuple(_intermediates(dx, dy) for dx, dy in HEADINGS)


# --- La malla ------------------------------------------------------------------------------------------------------------------


def mesh_factor(grid: Grid, mesh_m: float) -> int:
    """El factor entero ``k`` de la malla de la ruta de ``mesh_m`` m sobre ``grid`` (D-10): ``mesh_m = k · paso``. La rejilla ha de
    ser de celdas cuadradas (ADR-0014). ``ValueError`` si no lo es o si ``mesh_m`` no es un múltiplo entero del paso del proyecto
    (con un margen de 10⁻⁹ relativo): la ruta se busca en bloques enteros de celdas."""
    if not isinstance(grid, Grid):
        raise TypeError(f"la rejilla es Grid, no {grid!r}")
    if grid.dx != grid.dy:
        raise ValueError(f"la malla de la ruta se mide sobre celdas cuadradas (ADR-0014), no de {grid.dx} × {grid.dy} m")
    mesh = _finite(mesh_m, "la malla de la ruta", strict=True)
    factor = round(mesh / grid.dx)
    if factor < 1 or abs(mesh - factor * grid.dx) > 1e-9 * max(mesh, grid.dx):
        raise ValueError(f"la malla de la ruta ({mesh:g} m) no es un múltiplo entero del paso del proyecto ({grid.dx:g} m): "
                         "la ruta se busca en bloques enteros de celdas (D-10)")
    return int(factor)


@dataclass(frozen=True, slots=True, eq=False)
class RouteMesh:
    """La malla de la ruta (A0, A1; D-10, P-6): ``grid`` (la del proyecto), el factor ``k`` (cada nodo es un bloque de ``k × k``
    celdas), ``mesh_m`` (``k`` veces el paso: el lado de un nodo, m), la cota de cada nodo (``z``: la media de las celdas de su bloque,
    m, float64; ``NaN`` si alguna celda no tiene dato o el bloque se sale de la rejilla), ``forbidden`` (alguna celda del bloque está en
    la máscara que prohíbe pisar), ``walkable`` (``z`` finita y no ``forbidden``) y, si se dio, ``weight`` (el mayor peso ≥ 1 de las celdas
    de su bloque; ``None`` si no hay ninguna zona «preferible no afectar»: todo pesa 1). Todos son de la forma de la malla ``(ni, nj)``
    (la fila 0, al norte; ``ni = ⌈filas / k⌉``) y de solo lectura. Solo la crea :func:`route_mesh`.

    **Es solo para buscar**: ninguna cifra de volumen ni de longitud de la pista sale de ella (RF-017-09)."""

    grid: Grid
    k: int
    mesh_m: float
    z: np.ndarray
    forbidden: np.ndarray
    walkable: np.ndarray
    weight: np.ndarray | None = None

    @property
    def shape(self) -> tuple[int, int]:
        """``(ni, nj)``: los nodos por fila y por columna."""
        return (int(self.z.shape[0]), int(self.z.shape[1]))

    @property
    def size(self) -> int:
        """Los nodos de la malla."""
        return int(self.z.size)

    def node_of(self, x: float, y: float) -> tuple[int, int]:
        """El nodo ``(i, j)`` que contiene el punto absoluto ``(x, y)`` (el de su celda: un punto en el borde de dos celdas va a la del
        este y a la del sur). ``ValueError`` si cae fuera de la rejilla del proyecto."""
        grid = self.grid
        column = math.floor((float(x) - grid.west) / grid.dx)
        row = math.floor((grid.north - float(y)) / grid.dy)
        if not (0 <= row < grid.nrows and 0 <= column < grid.ncols):
            raise ValueError(f"el punto ({x}, {y}) cae fuera de la rejilla del proyecto: no es de ningún nodo")
        return (row // self.k, column // self.k)

    def center_of(self, i: int, j: int) -> tuple[float, float]:
        """El centro (absoluto, float64) del bloque del nodo ``(i, j)`` (el nominal, de ``k × k`` celdas, también en los bloques
        incompletos del borde). ``ValueError`` si el nodo no es de la malla."""
        rows, cols = self.shape
        if not (0 <= i < rows and 0 <= j < cols):
            raise ValueError(f"el nodo ({i}, {j}) no es de la malla de {rows} × {cols} nodos")
        side = self.mesh_m
        return (self.grid.west + (j + 0.5) * side, self.grid.north - (i + 0.5) * side)


def route_mesh(grid: Grid, surface: np.ndarray, mesh_m: float, mask: np.ndarray | None = None, *,
               avoid_weight: np.ndarray | None = None) -> RouteMesh:
    """La malla de la ruta sobre ``grid`` (A1; D-10, P-6): bloques de ``k × k`` celdas, con ``k`` el factor entero de ``mesh_m``
    (:func:`mesh_factor`), y como cota de cada nodo **la media** de las de su bloque de la superficie de partida ``surface`` (m, de la
    forma de la rejilla; ``NaN``, sin dato). Un nodo con alguna celda sin dato, **o que ``mask`` prohíbe pisar** (``True`` en alguna
    celda de su bloque: los intocables y las exclusiones de RF-017-06; ``None``: ninguna), no se pisa (``walkable`` falso). Con
    ``avoid_weight`` (≥ 1, de la forma de la rejilla) cada nodo lleva el mayor peso de las celdas de su bloque. Las entradas no se
    modifican. ``ValueError`` si ``mesh_m`` no es un múltiplo entero del paso del proyecto, la rejilla no es de celdas cuadradas o un
    array no es de la forma de la rejilla (o un peso baja de 1)."""
    k = mesh_factor(grid, mesh_m)
    shape = grid.shape
    heights = np.asarray(surface, dtype=np.float64)
    if heights.shape != shape:
        raise ValueError(f"la superficie {heights.shape} no es de la forma de la rejilla {shape}")
    prohibited = None
    if mask is not None:
        prohibited = np.asarray(mask, dtype=np.bool_)
        if prohibited.shape != shape:
            raise ValueError(f"la máscara {prohibited.shape} no es de la forma de la rejilla {shape}")
    weights = None
    if avoid_weight is not None:
        weights = np.asarray(avoid_weight, dtype=np.float64)
        if weights.shape != shape:
            raise ValueError(f"el peso de «preferible no afectar» {weights.shape} no es de la forma de la rejilla {shape}")
        if not bool((weights >= 1.0).all()):
            raise ValueError("el peso de una celda «preferible no afectar» es un número finito de 1 o más (RF-017-06)")
    rows, cols = shape
    ni, nj = -(-rows // k), -(-cols // k)
    pad = ((0, ni * k - rows), (0, nj * k - cols))
    partial = pad != ((0, 0), (0, 0))

    def blocks(values: np.ndarray, fill: object) -> np.ndarray:
        return (np.pad(values, pad, constant_values=fill) if partial else values).reshape(ni, k, nj, k)

    z = blocks(heights, np.nan).mean(axis=(1, 3))
    z[~np.isfinite(z)] = np.nan
    forbidden = (blocks(prohibited, False).any(axis=(1, 3)) if prohibited is not None
                 else np.zeros((ni, nj), dtype=np.bool_))
    walkable = np.isfinite(z) & ~forbidden
    weight = None if weights is None else _readonly(blocks(weights, 1.0).max(axis=(1, 3)))
    return RouteMesh(grid, k, k * grid.dx, _readonly(z), _readonly(forbidden), _readonly(walkable), weight)


# --- Los pasos admisibles --------------------------------------------------------------------------------------------------------


def step_masks(mesh: RouteMesh, pd: float, hmax: float) -> tuple[np.ndarray, ...]:
    """Las 16 máscaras de paso admisible de ``mesh`` (RF-017-09, RF-017-11): ``masks[h][i, j]`` es verdadero si el paso del rumbo
    ``h`` (:data:`HEADINGS`) desde el nodo ``(i, j)`` es admisible, esto es, si ni el nodo ni su extremo ni, en los pasos «de caballo», los
    dos nodos que la recta atraviesa están prohibidos o sin dato (``walkable``), y ``|Δcota| ≤ pd·L(h) + 2·hmax`` con ``L(h)`` la longitud
    del paso (más ``10⁻⁹`` m de margen): la condición necesaria de una ruta con esa altura máxima de desmonte y terraplén ``hmax`` (m), con
    ``pd`` la pendiente de diseño **en tanto por uno**. Son simétricas (si el paso de ``a`` a ``b`` es admisible, el de ``b`` a ``a``, en el
    rumbo opuesto, también). Un array por rumbo, de solo lectura, de la forma de la malla; no hay forma de pedir otro número de rumbos."""
    if not isinstance(mesh, RouteMesh):
        raise TypeError(f"la malla es RouteMesh, no {mesh!r}")
    slope = _finite(pd, "la pendiente de diseño (en tanto por uno)")
    height = _finite(hmax, "la altura máxima de desmonte y terraplén (m)")
    z, walkable = mesh.z, mesh.walkable
    found: list[np.ndarray] = []
    with np.errstate(invalid="ignore"):
        for (dx, dy), unit, between in zip(HEADINGS, STEP_UNITS, _INTERMEDIATES, strict=True):
            limit = slope * (mesh.mesh_m * unit) + 2.0 * height + _STEP_TOLERANCE_M
            step = walkable & _shifted(walkable, -dy, dx, False)
            step &= np.abs(_shifted(z, -dy, dx, np.nan) - z) <= limit
            for mid_x, mid_y in between:
                step &= _shifted(walkable, -mid_y, mid_x, False)
            found.append(_readonly(step))
    return tuple(found)


# --- La red 2D -------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Network:
    """La red 2D desde unos nodos (A1): ``dist`` es la longitud mínima (m, float64, de la forma de la malla y de solo lectura) desde
    ``sources`` (los índices planos ``i · nj + j`` de los nodos de partida que se pisan, ordenados) a cada nodo por pasos de los 16 rumbos
    admisibles, y ``inf`` donde no llega; ``pd`` y ``hmax`` son con los que se calculó. La longitud es de la **malla**: una cota inferior
    de la de la pista, no una cifra de ella (RF-017-09)."""

    mesh: RouteMesh
    sources: np.ndarray
    dist: np.ndarray
    pd: float
    hmax: float

    @property
    def reached(self) -> int:
        """Los nodos a los que llega (los de partida también)."""
        return int(np.isfinite(self.dist).sum())

    def distance_to(self, i: int, j: int) -> float:
        """La longitud mínima (m) al nodo ``(i, j)``; ``inf`` si no llega."""
        return float(self.dist[i, j])

    def reaches(self, i: int, j: int) -> bool:
        """Si la red llega al nodo ``(i, j)``."""
        return bool(math.isfinite(self.dist[i, j]))


def _target_nodes(mesh: RouteMesh, target: object) -> np.ndarray:
    """Los índices planos de los nodos de partida de ``target`` (un nodo ``(i, j)`` o una máscara booleana de la malla) que se pisan,
    ordenados; los demás se descartan (una partida que no se pisa no llega a ningún sitio: no es un error de las entradas)."""
    rows, cols = mesh.shape
    if isinstance(target, np.ndarray):
        if target.dtype != np.bool_ or target.shape != (rows, cols):
            raise ValueError(f"un conjunto de nodos es una máscara booleana de la forma de la malla {(rows, cols)}, no {target.dtype} "
                             f"{target.shape}")
        found = np.flatnonzero(target)
    else:
        try:
            i, j = target  # type: ignore[misc]
        except (TypeError, ValueError):
            raise TypeError(f"el destino es un nodo (i, j) o una máscara booleana de la malla, no {target!r}") from None
        for item in (i, j):
            if isinstance(item, bool) or not isinstance(item, numbers.Integral):
                raise TypeError(f"los índices de un nodo son enteros, no {target!r}")
        if not (0 <= i < rows and 0 <= j < cols):
            raise ValueError(f"el nodo {target!r} no es de la malla de {rows} × {cols} nodos")
        found = np.array([int(i) * cols + int(j)], dtype=np.int64)
    found = found[mesh.walkable.ravel()[found]]
    return np.sort(found).astype(np.int64, copy=False)


def _dijkstra_units(mesh: RouteMesh, masks: tuple[np.ndarray, ...], sources: np.ndarray, pd: float, hmax: float
                    ) -> Generator[None, None, Network]:
    """Las unidades de :func:`network_steps`: el Dijkstra, que cede el hilo cada :data:`NODES_PER_UNIT` nodos extraídos. Lo único que
    guarda son sus listas locales: cerrarlo no deja nada."""
    rows, cols = mesh.shape
    width = cols + 2 * _PAD
    padded = (rows + 2 * _PAD) * width
    allow: list[bytes] = []
    for mask in masks:
        framed = np.zeros((rows + 2 * _PAD, width), dtype=np.uint8)
        framed[_PAD:-_PAD, _PAD:-_PAD] = mask
        allow.append(framed.tobytes())
    yield
    table = tuple((allow[h], -dy * width + dx, mesh.mesh_m * STEP_UNITS[h]) for h, (dx, dy) in enumerate(HEADINGS))
    dist = [_INF] * padded
    heap: list[tuple[float, int]] = []
    for flat in sources.tolist():
        index = (flat // cols + _PAD) * width + flat % cols + _PAD
        dist[index] = 0.0
        heap.append((0.0, index))
    heapq.heapify(heap)
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        count = 0
        while heap and count < NODES_PER_UNIT:
            reached, node = pop(heap)
            if reached > dist[node]:
                continue
            count += 1
            for permitted, offset, length in table:
                if permitted[node]:
                    other = node + offset
                    cost = reached + length
                    if cost < dist[other]:
                        dist[other] = cost
                        push(heap, (cost, other))
        yield
    found = np.array(dist, dtype=np.float64).reshape(rows + 2 * _PAD, width)[_PAD:-_PAD, _PAD:-_PAD].copy()
    return Network(mesh, _readonly(sources), _readonly(found), pd, hmax)


def network_steps(mesh: RouteMesh, target: tuple[int, int] | np.ndarray, pd: float, hmax: float, *,
                  budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Los pasos de la red 2D de ``mesh`` desde ``target`` (A1; RF-017-09, RF-017-11, RNF-017-01 y 06): la longitud mínima desde un nodo
    ``(i, j)`` o desde **un conjunto de nodos** (una máscara booleana de la forma de la malla: el destino por cota, T08) a cada nodo, por
    pasos de los 16 rumbos admisibles (:func:`step_masks`) con ``pd`` la pendiente de diseño **en tanto por uno** y ``hmax`` la altura
    máxima de desmonte y terraplén (m). Un Dijkstra con ``heapq`` (plan §9: un bucle de Python por nodo extraído), por pasos de
    ``budget_s`` como mucho (``STEP_BUDGET_S``, 0,05 s: RNF-017-06) con su progreso; el último ``Progress`` lleva la :class:`Network`
    (``pipeline.forward`` la extrae). Una partida que no se pisa (prohibida o sin dato) no llega a ningún sitio: la red sale vacía, no es
    un error. Las entradas se comprueban **al llamar** (``ValueError`` o ``TypeError``). Cerrar el generador a mitad no deja nada: no
    escribe en la malla ni en ningún sitio."""
    if not isinstance(mesh, RouteMesh):
        raise TypeError(f"la malla es RouteMesh, no {mesh!r}")
    budget = _finite(budget_s, "el presupuesto de un paso (s)", strict=True)
    slope = _finite(pd, "la pendiente de diseño (en tanto por uno)")
    height = _finite(hmax, "la altura máxima de desmonte y terraplén (m)")
    sources = _target_nodes(mesh, target)
    masks = step_masks(mesh, slope, height)
    work = _dijkstra_units(mesh, masks, sources, slope, height)
    return pace_progress(work, budget, phase=_PHASE, running=_RUNNING, finished=_FINISHED,
                         total=max(2, mesh.size // 10_000 + 2))


# --- El pasillo ------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Corridor:
    """El pasillo de la ruta 3D (RF-017-09): ``net_origin`` y ``net_dest`` (las dos redes 2D de las que sale), la holgura ``margin_m``
    (m), ``reachable`` (si el origen es alcanzable), la **cota inferior** de la longitud de la ruta (``lower_bound_m``, m: la longitud
    mínima de la red 2D del origen al destino; ``None`` si no es alcanzable) y ``mask`` (los nodos cuya longitud mínima desde el origen
    más la que les queda hasta el destino no pasa de la más corta más la holgura; vacía si no es alcanzable; de solo lectura). La
    holgura **no es el ancho**. Ninguna cifra de volumen ni de longitud de la pista sale de aquí: es solo el espacio donde se busca."""

    net_origin: Network
    net_dest: Network
    margin_m: float
    reachable: bool
    lower_bound_m: float | None
    mask: np.ndarray

    @property
    def mesh(self) -> RouteMesh:
        """La malla de las dos redes."""
        return self.net_origin.mesh

    @property
    def nodes(self) -> int:
        """Los nodos del pasillo."""
        return int(self.mask.sum())


def corridor(net_origin: Network, net_dest: Network, margin_m: float) -> Corridor:
    """El pasillo de la ruta (RF-017-09): si el origen es alcanzable (``net_dest.dist`` es finita en él), la cota inferior de la longitud
    de la ruta (``net_dest.dist`` en el origen, m) y los nodos con ``d_origen + d_destino ≤ la más corta + margin_m`` (la holgura, m; con 0,
    la ruta más corta; con un margen de 10⁻⁹ relativo para el último bit de las sumas). ``net_origin`` es la red desde el origen y
    ``net_dest``, desde el destino (un nodo o un conjunto): las dos de la misma malla (``ValueError`` si no)."""
    if not isinstance(net_origin, Network) or not isinstance(net_dest, Network):
        raise TypeError("el pasillo se arma con dos redes 2D (Network): la del origen y la del destino")
    if net_origin.mesh is not net_dest.mesh:
        raise ValueError("las redes 2D del origen y del destino son de la misma malla")
    margin = _finite(margin_m, "la holgura del pasillo (m)")
    shape = net_origin.mesh.shape
    shortest = _INF
    if net_origin.sources.size:
        shortest = float(net_dest.dist.ravel()[net_origin.sources].min())
    if not math.isfinite(shortest):
        empty = np.zeros(shape, dtype=np.bool_)
        return Corridor(net_origin, net_dest, margin, False, None, _readonly(empty))
    reach = net_origin.dist + net_dest.dist
    found = reach <= shortest + margin + _CORRIDOR_TOLERANCE * shortest
    return Corridor(net_origin, net_dest, margin, True, shortest, _readonly(found))
