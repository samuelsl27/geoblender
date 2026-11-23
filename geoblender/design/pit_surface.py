# SPDX-License-Identifier: GPL-3.0-or-later
"""La superficie de la corta en la rejilla (spec 018, T18; HU-018-4; RF-018-28 y 31; CE-018-03 y 11; plan 018 §5.4 A10, §5.7 P-6, P-7 y P-10).

Desde las polilíneas con su Z (pies y crestas de los bancos) y los bordes de las rampas, la **superficie oficial** de la corta es la de la
rejilla del proyecto (ADR-0014, D-10):

1. **Aristas obligatorias.** Cada polilínea cerrada (y el borde izquierdo, el eje y el borde derecho de cada rampa, abiertos) se **densifica**
   a lados de a lo sumo el doble del paso de la rejilla (el riesgo de ``plan.md`` §8: una arista larga con ángulo agudo daría triángulos que
   cruzan una cara en vez de seguirla) y sus vértices, sin repetir, con su Z, son los puntos de la triangulación; los lados, sus aristas
   obligatorias. Todo se triangula **en unidades de celda** (columna ``(X − oeste)/dx``, fila hacia el norte ``(Y − norte)/dy``), con la esquina
   de la rejilla restada antes de dividir (regla 4 de ``AGENTS.md``, ADR-0005).
2. **La triangulación.** El :class:`~geoblender.gis.cdt.PureTriangulator` por pasos (P-6: 17 µs por punto, cancelable, sin la llamada
   nativa). Los triángulos pasan a la rejilla con :func:`~geoblender.gis.tin.tin_to_raster` **por bandas de filas** (las de
   :mod:`design.thickness`, de coste acotado: RNF-018-06), con el mismo resultado bit a bit que de una pieza.
3. **El recinto** (P-7). La CDT de contornos anidados rellena toda la envolvente convexa; la superficie solo vale **dentro de la polilínea
   más externa**: la unión de las celdas cuyo centro cae dentro de alguna polilínea cerrada (:func:`design.zones._spans`; la regla par-impar
   de cada anillo por separado, así que un anillo dentro de otro no es un hueco).
4. **La composición** (RF-013-29). :func:`design.compose.compose` con el sentido de corte: ``mín(corta, partida)`` en las celdas donde el
   corte se admite (``cut_allowed`` y no ``untouchable``) y la de partida **exacta, bit a bit**, en todas las demás (fuera del recinto,
   en lo prohibido y donde alguna no tiene dato). Las celdas donde la corta baja y las máscaras no dejan (``blocked``) se dan aparte: son un
   hallazgo de A12.
5. **Las cifras.** El volumen de corte es ``Σ (partida − corta) · área de celda`` y el **volumen por banco**, el reparto de la 011 sobre las
   cotas ancladas ``z₀ + k·h`` (RF-018-31): cada celda aporta a cada rodaja ``[z_k, z_k+1)`` lo que su intervalo ``[corta, partida]`` solapa
   con ella (``z_k = ancla + k·altura``, la única expresión de las cotas; el extremo superior justo en una cota va a la rodaja de abajo; los
   trozos de en medio, por diferencias acumuladas: coste proporcional a las celdas, no a las rodajas). ``design`` no importa ``reserves``
   (P-10): es la **misma fórmula**, y la prueba de referencia la compara con el núcleo de la 011 a ≤ 10⁻⁹ relativo.

Las polilíneas y las rampas llegan **absolutas** (float64); la rejilla, la partida y las máscaras son las del trabajo. Ninguna entrada se
modifica y lo que sale es de solo lectura. **Los pasos** (:func:`rasterize_steps`) ceden el hilo cada ≈ 0,05 s (``pace_progress``;
RNF-018-06): la triangulación cada ``STEP_POINTS`` puntos y la rejilla por bandas de filas; cerrar el generador a mitad no deja nada.
Los errores de los datos de la triangulación (dos aristas que se cruzan, una que pasa por un vértice) salen como los de ``gis``
(``gis.triangulation_input``), sin relajar nada. Perezoso (RNF-001-03): nada del arranque lo importa. Python puro con numpy.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from ..core.project.model import Progress
from ..gis.cdt import PureTriangulator
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.tin import Tin, tin_to_raster
from .compose import compose
from .model import BenchSense
from .pit_model import PitJob, Polyline
from .seeds import pace_progress
from .thickness import _raster_bands, _row_costs
from .zones import _full, _spans, to_cell_units

__all__ = ["MAX_SIDE_CELLS", "PitSurface", "bench_volumes", "rasterize", "rasterize_steps"]

MAX_SIDE_CELLS: float = 2.0
"""El lado mayor de las aristas que se triangulan, en celdas (RF-018-28, plan §8): el doble del paso de la rejilla."""
_PHASE = "pit_surface"
_SPILL = 1e-9
"""Lo que un extremo puede apartarse de una cota de rodaja para contar en ella (m): el redondeo de la resta."""


@dataclass(frozen=True, slots=True, eq=False)
class PitSurface:
    """La superficie de una corta en la rejilla del proyecto (A10), todo de solo lectura y de la forma de la rejilla:

    - ``surface``: la superficie de diseño compuesta con la de partida (m; ``NaN``: sin dato en la de partida);
    - ``stepped``: la de las polilíneas sola, **dentro del recinto** (``NaN`` fuera de él);
    - ``enclosure``: las celdas dentro de la polilínea más externa;
    - ``blocked``: las celdas del recinto donde la corta baja de la partida y las máscaras no admiten el corte (se quedan como la partida);
    - ``cut_cells``: las celdas donde la superficie queda por debajo de la partida (el movimiento);
    - ``cut_m3``: el volumen de corte, ``Σ (partida − corta) · área de celda``;
    - ``bench_levels`` y ``bench_m3``: las cotas ``z_0 < … < z_n`` de las rodajas (``ancla + k·altura``; vacías si nada se mueve) y el
      volumen de cada una, que suman ``cut_m3``;
    - ``triangles`` y ``points``: los de la triangulación (0 y 0 si no hizo falta)."""

    surface: np.ndarray
    stepped: np.ndarray
    enclosure: np.ndarray
    blocked: np.ndarray
    cut_cells: np.ndarray
    cut_m3: float
    bench_levels: np.ndarray
    bench_m3: np.ndarray
    triangles: int
    points: int

    def __post_init__(self) -> None:
        for name in ("surface", "stepped", "enclosure", "blocked", "cut_cells", "bench_levels", "bench_m3"):
            array = getattr(self, name)
            array.flags.writeable = False


# --- Las aristas obligatorias ------------------------------------------------------------------------------------------------


def _densify(cells: np.ndarray, z: np.ndarray, closed: bool, step: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Los vértices ``cells`` ``(k, 2)`` (unidades de celda) con su ``z`` de una línea con sus lados partidos en trozos iguales de a lo sumo
    :data:`MAX_SIDE_CELLS` celdas (``step`` = lo que mide una celda en cada eje, para el largo): ``(k', 2)`` y ``(k',)``, la Z lineal en cada
    lado. Una línea cerrada no repite el primer vértice; los puntos añadidos van entre los suyos, en el orden de la línea."""
    nxt = np.roll(np.arange(len(cells)), -1) if closed else np.arange(1, len(cells))
    first = np.arange(len(cells)) if closed else np.arange(len(cells) - 1)
    delta = cells[nxt] - cells[first]
    length = np.hypot(delta[:, 0] * step[0], delta[:, 1] * step[1]) / (MAX_SIDE_CELLS * min(step))
    parts = np.maximum(np.ceil(length), 1.0).astype(np.int64)
    if int(parts.max()) == 1:
        return cells, z
    owner = np.repeat(np.arange(len(first)), parts)
    along = np.arange(int(parts.sum())) - (np.cumsum(parts) - parts)[owner]
    fraction = (along / parts[owner])[:, None]
    points = cells[first][owner] + delta[owner] * fraction
    heights = z[first][owner] + (z[nxt] - z[first])[owner] * fraction[:, 0]
    if not closed:  # el último vértice cierra el último lado: se añade al final
        points = np.vstack([points, cells[-1:]])
        heights = np.append(heights, z[-1])
    return points, heights


def _to_cells(vertices: np.ndarray, grid: Grid) -> np.ndarray:
    """Los vértices ``(k, 2)`` o ``(k, 3)`` absolutos en unidades de celda con la fila hacia el norte (``y = −fila``, como ``tin_to_raster``)."""
    columns, rows = to_cell_units([vertices], grid)[0].T
    return np.column_stack([columns, -rows])


@dataclass(slots=True, eq=False)
class _Lines:
    """Los puntos y las aristas obligatorias que se van sumando."""

    points: list[np.ndarray]
    heights: list[np.ndarray]
    edges: list[np.ndarray]
    total: int = 0

    def add(self, cells: np.ndarray, z: np.ndarray, closed: bool) -> None:
        count = len(cells)
        index = np.arange(self.total, self.total + count)
        pairs = np.column_stack([index, np.roll(index, -1)]) if closed else np.column_stack([index[:-1], index[1:]])
        self.points.append(cells)
        self.heights.append(z)
        self.edges.append(pairs)
        self.total += count


def _unique_points(lines: _Lines) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los puntos sin repetir (la Z del primero de cada grupo), las aristas con los índices nuevos y sin las degeneradas ni las repetidas.
    Dos líneas que comparten un vértice (los bancos que se tocan, el borde de una rampa sobre un pie) son una sola referencia."""
    xy = np.vstack(lines.points)
    z = np.concatenate(lines.heights)
    edges = np.vstack(lines.edges)
    _, first, inverse = np.unique(xy, axis=0, return_index=True, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)
    order = np.sort(first)  # los puntos en el orden en que llegaron
    rank = np.empty(len(first), dtype=np.int64)
    rank[np.argsort(first, kind="stable")] = np.arange(len(first))
    remap = rank[inverse]
    edges = remap[edges]
    edges = edges[edges[:, 0] != edges[:, 1]]
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    return xy[order], z[order], edges.astype(np.int32)


# --- La superficie -----------------------------------------------------------------------------------------------------------


def _enclosure(polylines: Sequence[Polyline], grid: Grid) -> np.ndarray:
    """El recinto de la polilínea más externa: la unión de las celdas con el centro dentro de alguna polilínea cerrada (cada anillo, por su
    cuenta: un anillo dentro de otro no es un hueco)."""
    rings = [item.vertices for item in polylines if item.closed]
    spans = [_spans(to_cell_units([ring], grid), grid.nrows, grid.ncols) for ring in rings]
    rows = np.concatenate([part[0] for part in spans])
    begin = np.concatenate([part[1] for part in spans])
    end = np.concatenate([part[2] for part in spans])
    return _full((rows, begin, end), grid.nrows, grid.ncols)


def _rasterize_units(tin: Tin, grid: Grid, crs: CrsRef, vertical: VerticalRef) -> Generator[None, None, np.ndarray]:
    """El TIN (en unidades de celda) en la rejilla de ``grid`` por bandas de filas (las de :func:`design.thickness._raster_bands`): cada una
    rasteriza solo los triángulos de su caja, en el orden del TIN, y una unidad es una banda. El resultado es el de una pieza bit a bit (los
    centros de celda son enteros y medios exactos con cualquier esquina de banda)."""
    nrows, ncols = grid.shape
    out = np.full((nrows, ncols), np.nan)
    cost, first, last = _row_costs(tin, (nrows, ncols))
    yield
    for top, bottom in _raster_bands(cost):
        chosen = np.flatnonzero((first < bottom) & (last >= top))
        if chosen.size:
            part = Tin(tin.vertices, tin.faces[chosen], tin.constraint_edges, tin.vertex_source, triangulator=tin.triangulator)
            band = Grid(0.0, -float(top), 1.0, 1.0, ncols, bottom - top)
            out[top:bottom] = tin_to_raster(part, band, crs=crs, vertical=vertical).values
        yield
    return out


def _level(anchor_m: float, height_m: float, number: np.ndarray | float) -> Any:
    """La cota ``ancla + k·altura`` de la rodaja ``k``: la única expresión de las cotas (la de la 011)."""
    return anchor_m + number * height_m


def _slice_index(z: np.ndarray, anchor_m: float, height_m: float) -> np.ndarray:
    """La rodaja ``[z_k, z_k+1)`` de cada cota de ``z`` (una cota justo en un límite va a la de arriba), como en la 011."""
    number = np.floor((z - anchor_m) / height_m)
    number -= z < _level(anchor_m, height_m, number)
    number += z >= _level(anchor_m, height_m, number + 1.0)
    return number.astype(np.int64)


def bench_volumes(start: np.ndarray, surface: np.ndarray, cell_area_m2: float, anchor_m: float, height_m: float
                  ) -> tuple[np.ndarray, np.ndarray]:
    """**El volumen por banco** (RF-018-31, P-10): ``(cotas, volúmenes)`` del corte entre ``start`` y ``surface`` (rejillas de la misma forma;
    ``NaN`` sin dato) repartido en las rodajas ``[z_k, z_k+1)`` con ``z_k = anclaje + k·altura``: cada celda donde ``start > surface`` aporta a
    cada rodaja lo que su intervalo ``[surface, start]`` solapa con ella, por su área de celda (m³). Las cotas van de la rodaja de la menor
    cota de corte a la de la mayor (la mayor justo en una cota cierra la última); ``volúmenes`` tiene una menos. Sin corte, dos arrays vacíos
    (``cotas`` con una sola cota no hay). Es la fórmula del núcleo de la 011 (``reserves.kernel``): el extremo superior justo en una cota va a
    la rodaja de abajo y los trozos enteros de en medio se suman por diferencias acumuladas, así que el coste es el de las celdas."""
    if height_m <= 0.0 or not math.isfinite(height_m) or not math.isfinite(anchor_m):
        raise ValueError(f"la altura y el anclaje de las rodajas son finitos y la altura positiva, no {height_m!r} y {anchor_m!r}")
    lower = np.asarray(surface, dtype=np.float64)
    upper = np.asarray(start, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        moving = np.isfinite(lower) & np.isfinite(upper) & (upper > lower)
    if not moving.any():
        return np.empty(0), np.empty(0)
    a, b = lower[moving], upper[moving]
    first = int(_slice_index(np.array([a.min()]), anchor_m, height_m)[0])
    top = int(_slice_index(np.array([b.max()]), anchor_m, height_m)[0])
    if not (top > first and _level(anchor_m, height_m, float(top)) == float(b.max())):
        top += 1
    count = top - first
    levels = np.asarray(_level(anchor_m, height_m, np.arange(first, top + 1, dtype=np.float64)))
    k_a = _slice_index(a, anchor_m, height_m) - first
    k_b = _slice_index(b, anchor_m, height_m) - first
    on_level = b == _level(anchor_m, height_m, (k_b + first).astype(np.float64))
    k_b = np.where(on_level & (k_b > k_a), k_b - 1, k_b)  # el extremo superior justo en una cota va a la rodaja de abajo
    same = k_a == k_b
    volume = np.zeros(count)
    volume += np.bincount(k_a[same], weights=(b - a)[same], minlength=count)
    split = ~same
    volume += np.bincount(k_a[split], weights=levels[k_a[split] + 1] - a[split], minlength=count)
    volume += np.bincount(k_b[split], weights=b[split] - levels[k_b[split]], minlength=count)
    cover = np.zeros(count + 1)
    cover += np.bincount(k_a[split] + 1, minlength=count + 1)
    cover -= np.bincount(k_b[split], minlength=count + 1)
    whole = np.cumsum(cover)[:count] * np.diff(levels)  # las rodajas enteras de en medio
    return levels, (volume + whole) * cell_area_m2


def _surface_units(job: PitJob, polylines: Sequence[Polyline], ramps: Sequence[Any], crs: CrsRef, vertical: VerticalRef
                   ) -> Generator[None, None, PitSurface]:
    grid = job.grid
    step = (grid.dx, grid.dy)
    lines = _Lines([], [], [])
    for item in polylines:
        cells, z = _densify(_to_cells(item.vertices, grid), np.asarray(item.vertices[:, 2], dtype=np.float64), item.closed, step)
        lines.add(cells, z, item.closed)
    for ramp in ramps:
        for line in ramp.band.breaklines:
            cells, z = _densify(_to_cells(line, grid), np.asarray(line[:, 2], dtype=np.float64), False, step)
            lines.add(cells, z, False)
    yield
    xy, height, edges = _unique_points(lines)
    faces = yield from PureTriangulator().triangulate_steps(xy, edges)
    tin = Tin(np.column_stack([xy, height]), faces, edges, np.full(len(xy), 3, dtype=np.uint8), triangulator=PureTriangulator.name)
    raster = yield from _rasterize_units(tin, grid, crs, vertical)
    enclosure = _enclosure(polylines, grid)
    yield
    stepped = np.where(enclosure, raster, np.nan)
    allowed = job.cut_allowed & ~job.untouchable
    surface = compose(job.start, stepped, allowed, BenchSense.CUT)
    with np.errstate(invalid="ignore"):
        lowered = np.isfinite(stepped) & np.isfinite(job.start) & (stepped < job.start)
        cut_cells = surface < job.start
    blocked = lowered & ~allowed
    yield
    rows = np.where(cut_cells, job.start - surface, 0.0)
    cut_m3 = math.fsum(rows.sum(axis=1).tolist()) * grid.cell_area
    levels, by_bench = bench_volumes(job.start, surface, grid.cell_area, job.anchor_m, job.height_m)
    yield
    return PitSurface(surface, stepped, enclosure, blocked, cut_cells, cut_m3, levels, by_bench, len(faces), len(xy))


def _polylines_of(benches: Any) -> tuple[Polyline, ...]:
    found = tuple(getattr(benches, "polylines", benches))
    if not found or not all(isinstance(item, Polyline) for item in found):
        raise ValueError("la superficie de una corta sale de sus polilíneas (al menos una): «Benches» o una lista de Polyline")
    if not any(item.closed for item in found):
        raise ValueError("la superficie de una corta necesita al menos una polilínea cerrada para su recinto")
    return found


def rasterize_steps(job: PitJob, benches: Any, ramps: Sequence[Any] = (), *, crs: CrsRef, vertical: VerticalRef,
                    budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A10** (RF-018-28 y 31): la superficie de la corta de ``job`` (:class:`PitSurface`) desde sus polilíneas (``benches``: los
    :class:`~design.pit_bench.Benches` o una lista de :class:`~design.pit_model.Polyline`) y los bordes de sus rampas (``ramps``: cada una con
    su ``band``, :class:`~design.pit_ramp.Band`, cuyas ``breaklines`` son aristas obligatorias), por pasos de ``budget_s`` como mucho (la
    triangulación y la rejilla ceden el hilo; cerrar el generador a mitad no deja nada y no modifica nada). El último ``Progress`` (fase
    ``pit_surface``) lleva la :class:`PitSurface`. ``crs`` y ``vertical`` son los del proyecto: solo marcan el ráster intermedio del TIN
    (como en ``design.thickness``). Un error de la triangulación (aristas que se cruzan, una que pasa por un vértice) sale al avanzar,
    como el de ``gis``; no se escribe nada."""
    work = _surface_units(job, _polylines_of(benches), tuple(ramps), crs, vertical)
    return pace_progress(work, budget_s, phase=_PHASE, running="Calculando la superficie de la corta…", finished="Superficie calculada")


def rasterize(job: PitJob, benches: Any, ramps: Sequence[Any] = (), *, crs: CrsRef, vertical: VerticalRef) -> PitSurface:
    """:func:`rasterize_steps` hasta el final, sin pasos: la :class:`PitSurface` de ``job``. Los mismos errores."""
    work = _surface_units(job, _polylines_of(benches), tuple(ramps), crs, vertical)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: PitSurface = done.value
            return result
