# SPDX-License-Identifier: GPL-3.0-or-later
"""Validación de una superficie (spec 006, T14; RF-006-23; plan 006 §5.3.2 y §5.4 A17).

:func:`validate_raster` informa de una superficie en rejilla con un
:class:`~.reports.SurfaceReport` (cifras diagnósticas, CALCULADO):

- el área de la rejilla y el área sin dato (m²; el porcentaje es ``nodata_pct``);
- el área de cada **hueco interior** (m²): las componentes 4-conexas del sin dato que no tocan
  el borde de la rejilla (las que lo tocan son el sin dato exterior: el contorno irregular de
  un levantamiento, no un hueco), de mayor a menor y, a igual área, por su primera celda (de
  norte a sur y de oeste a este);
- las **celdas con dato fuera de la ventana de trabajo** (la de la 002): las que tienen alguna
  parte fuera, con una tolerancia de :data:`~.resample.CELL_TOLERANCE` del paso (en una
  rejilla alineada con la ventana, una celda está entera dentro o entera fuera);
- las **cotas fuera del rango plausible** ``gis.validate.z_range_m`` (de −500 a 5.000 m, con
  los extremos dentro): un −9999 o un −32768 que la fuente no declaró como sin dato.

Sin dato es NaN o ±∞ (como en ``volume_between``). Cada área es un número de celdas por el
área exacta de la celda (|dx·dy|, RF-006-02). Las componentes (A17) salen de los tramos de
fila del sin dato y de la unión de los tramos que se solapan entre filas consecutivas, con
una unión–búsqueda vectorizada (enganche al menor índice y salto de punteros): la memoria y
el tiempo van con el número de tramos, no con el de celdas. Se recorre la rejilla por bloques
de filas de como mucho :data:`BLOCK_ITEMS` celdas. La entrada no se modifica.

:func:`validate_tin` informa de un TIN con el mismo :class:`~.reports.SurfaceReport`:

- el **área** que encierra su borde exterior (triángulos y huecos, m²) y, como área sin dato,
  la de sus **huecos interiores**: cada uno, la región sin triángulos que encierra un ciclo
  del borde que se recorre en sentido horario, menos las islas del TIN que tenga dentro
  (área neta, como el hueco de una rejilla); de mayor a menor;
- los **triángulos con algún vértice fuera de la ventana** (``cells_outside_window``) y los
  **vértices con la cota fuera del rango plausible** (``out_of_range``);
- el **% de triángulos planos**, el **lado máximo** en planta y los **degenerados** (área en
  planta < 10⁻⁶ m²), calculados como en ``build_tin``: dan lo mismo, bit a bit.

El borde de un TIN son las aristas de un solo triángulo, orientadas como en él (con el
triángulo a su izquierda); en un vértice donde se tocan dos trozos de borde (dos huecos, o
un hueco y el borde exterior, que se tocan en un punto) cada arista sigue con la primera
saliente en sentido antihorario desde la que llega: así cada región sin triángulos (un
hueco o el exterior) tiene su propio ciclo. Su área con signo (fórmula del área de Gauss)
dice si es un borde exterior (positiva; dos trozos del TIN que se tocan en un vértice son
un solo ciclo, con la suma de sus áreas) o un hueco (negativa); una isla está en el hueco
más pequeño que contiene un punto de uno de sus triángulos (paridad de un rayo hacia +X).

``gis.tin`` se importa dentro de las funciones del TIN: ``gis.points`` (que importa
``gis.tin``) usa la unión–búsqueda de este módulo.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from ..core.georef import Window
from . import params
from .raster import Raster
from .reports import SurfaceReport
from .resample import CELL_TOLERANCE

if TYPE_CHECKING:
    from .tin import Tin

__all__ = [
    "BLOCK_ITEMS",
    "SURFACE_GRID",
    "SURFACE_TIN",
    "Z_RANGE_KEY",
    "validate_raster",
    "validate_tin",
]

Z_RANGE_KEY = "gis.validate.z_range_m"
SURFACE_GRID = "grid"
"""El ``surface_type`` de una rejilla en :class:`~.reports.SurfaceReport`."""
SURFACE_TIN = "tin"
"""El ``surface_type`` de un TIN en :class:`~.reports.SurfaceReport`."""
BLOCK_ITEMS = 1 << 22
"""Celdas por bloque de filas (al menos una fila): acota la memoria de las máscaras."""


def _z_range(z_range: Sequence[float] | None) -> tuple[float, float]:
    """El rango plausible: el del parámetro, o ``z_range`` comprobado como él
    (``gis.param_*``)."""
    if z_range is None:
        low, high = params.default(Z_RANGE_KEY)  # type: ignore[misc]
    else:
        low, high = params.param(Z_RANGE_KEY).check(z_range)  # type: ignore[misc]
    return (float(low), float(high))


def _span(inside: np.ndarray) -> tuple[int, int]:
    """``(primero, fin)`` de las posiciones verdaderas de ``inside``, que son contiguas
    (bordes ordenados frente a un intervalo); ``(0, 0)`` si no hay ninguna."""
    index = np.flatnonzero(inside)
    if index.size == 0:
        return (0, 0)
    return (int(index[0]), int(index[-1]) + 1)


def _window_span(raster: Raster, window: Window) -> tuple[tuple[int, int], tuple[int, int]]:
    """Las filas y las columnas de ``raster`` enteras dentro de ``window`` (con una
    tolerancia de :data:`CELL_TOLERANCE` del paso): ``((fila0, fila1), (col0, col1))``."""
    grid = raster.grid
    x = grid.west + np.arange(grid.ncols + 1, dtype=np.float64) * grid.dx
    y = grid.north - np.arange(grid.nrows + 1, dtype=np.float64) * grid.dy
    tol_x = CELL_TOLERANCE * grid.dx
    tol_y = CELL_TOLERANCE * grid.dy
    columns = (x[:-1] >= window.xmin - tol_x) & (x[1:] <= window.xmax + tol_x)
    rows = (y[:-1] <= window.ymax + tol_y) & (y[1:] >= window.ymin - tol_y)
    return _span(rows), _span(columns)


def _runs(nodata: np.ndarray, first_row: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los tramos de fila de ``nodata`` (un bloque de filas): fila absoluta, columna inicial
    y columna final (excluida), en orden de filas y, en cada fila, de columnas."""
    rows, cols = nodata.shape
    padded = np.zeros((rows, cols + 2), dtype=np.int8)
    padded[:, 1:-1] = nodata
    change = np.diff(padded, axis=1)
    row, start = np.nonzero(change == 1)
    _, stop = np.nonzero(change == -1)
    return (row + first_row).astype(np.int64), start.astype(np.int64), stop.astype(np.int64)


def _links(row: np.ndarray, start: np.ndarray, stop: np.ndarray,
           ncols: int) -> tuple[np.ndarray, np.ndarray]:
    """Los pares (tramo de la fila de arriba, tramo) que se solapan en alguna columna
    (4-conexión). Con la clave fila·(ncols + 1) + columna, los tramos de la fila de arriba
    que solapan [inicio, fin) son un intervalo de índices: los que acaban después del
    inicio y empiezan antes del fin."""
    width = ncols + 1
    above = (row - 1) * width
    first = np.searchsorted(row * width + stop, above + start, side="right")
    last = np.searchsorted(row * width + start, above + stop, side="left")
    links = np.maximum(last - first, 0)
    lower = np.repeat(np.arange(row.size, dtype=np.int64), links)
    offset = np.arange(lower.size, dtype=np.int64) - np.repeat(np.cumsum(links) - links, links)
    return np.repeat(first, links) + offset, lower


def _roots(count: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La raíz de cada uno de los ``count`` nodos con las aristas (``a``, ``b``): el menor
    índice de su componente. Unión–búsqueda vectorizada: cada raíz se engancha a la menor
    raíz vecina y después se saltan punteros hasta que cada nodo apunta a su raíz (siempre
    padre ≤ hijo, así que no hay ciclos)."""
    parent = np.arange(count, dtype=np.int64)
    while a.size:
        root_a = parent[a]
        root_b = parent[b]
        apart = root_a != root_b
        if not apart.any():
            break
        a, b = a[apart], b[apart]
        root_a, root_b = root_a[apart], root_b[apart]
        np.minimum.at(parent, np.maximum(root_a, root_b), np.minimum(root_a, root_b))
        while True:
            grand = parent[parent]
            if np.array_equal(grand, parent):
                break
            parent = grand
    return parent


def _hole_cells(row: np.ndarray, start: np.ndarray, stop: np.ndarray, nrows: int,
                ncols: int) -> np.ndarray:
    """Las celdas de cada hueco interior (componente 4-conexa del sin dato que no toca el
    borde), de mayor a menor y, a igual número, por su primera celda."""
    count = row.size
    if count == 0:
        return np.empty(0, dtype=np.int64)
    upper, lower = _links(row, start, stop, ncols)
    root = _roots(count, upper, lower)
    cells = np.bincount(root, weights=stop - start, minlength=count)  # exacto: < 2⁵³
    border = (row == 0) | (row == nrows - 1) | (start == 0) | (stop == ncols)
    exterior = np.zeros(count, dtype=bool)
    exterior[root[border]] = True
    # La raíz es el primer tramo de la componente (el menor índice): su primera celda.
    holes = np.flatnonzero((root == np.arange(count)) & ~exterior)
    sizes = cells[holes].astype(np.int64)
    return sizes[np.argsort(-sizes, kind="stable")]


def validate_raster(
    raster: Raster,
    *,
    window: Window,
    z_range: Sequence[float] | None = None,
) -> SurfaceReport:
    """Valida la superficie en rejilla ``raster`` frente a la ventana de trabajo ``window``
    (``core.georef.Window``, absoluta) y el rango plausible de cotas (RF-006-23, A17).

    ``z_range`` ``None`` es el de ``gis.validate.z_range_m``; uno explícito se comprueba
    como el parámetro (``gis.param_*``). Devuelve un :class:`~.reports.SurfaceReport` de
    tipo ``grid``: áreas en m², huecos interiores de mayor a menor, celdas con dato fuera de
    la ventana y cotas con dato fuera del rango. Entradas mal formadas: ``TypeError`` (error
    del programa).
    """
    if not isinstance(raster, Raster):
        raise TypeError(f"raster debe ser un Raster, no {type(raster).__name__}")
    if not isinstance(window, Window):
        raise TypeError(f"window debe ser una core.georef.Window, no {type(window).__name__}")
    low, high = _z_range(z_range)
    grid = raster.grid
    (row_first, row_stop), (col_first, col_stop) = _window_span(raster, window)
    block_rows = max(1, BLOCK_ITEMS // grid.ncols)
    valid_cells = outside = out_of_range = 0
    runs: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for first in range(0, grid.nrows, block_rows):
        values = raster.values[first:first + block_rows]
        valid = np.isfinite(values)
        rows = valid.shape[0]
        count = int(np.count_nonzero(valid))
        valid_cells += count
        inside_first = min(max(row_first - first, 0), rows)
        inside_stop = min(max(row_stop - first, 0), rows)
        inside = valid[inside_first:inside_stop, col_first:col_stop]
        outside += count - int(np.count_nonzero(inside))
        with np.errstate(invalid="ignore"):
            out_of_range += int(np.count_nonzero(valid & ((values < low) | (values > high))))
        if count < valid.size:
            runs.append(_runs(~valid, first))
    if runs:
        row, start, stop = (np.concatenate(parts) for parts in zip(*runs, strict=True))
    else:
        row = start = stop = np.empty(0, dtype=np.int64)
    holes = _hole_cells(row, start, stop, grid.nrows, grid.ncols)
    cell_area = grid.cell_area
    cells = grid.nrows * grid.ncols
    return SurfaceReport(
        surface_type=SURFACE_GRID,
        area_m2=cells * cell_area,
        nodata_area_m2=(cells - valid_cells) * cell_area,
        hole_areas_m2=tuple(int(size) * cell_area for size in holes),
        cells_outside_window=outside,
        out_of_range=out_of_range,
        z_range_m=(low, high),
    )


# TIN -------------------------------------------------------------------------------------


def _boundary_edges(faces: np.ndarray,
                    count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Las aristas del borde: las aristas dirigidas de los triángulos (a→b, b→c, c→a) cuya
    inversa no es de ningún triángulo. Origen, destino y triángulo de cada una."""
    tail = faces.astype(np.int64).ravel()
    head = np.roll(faces, -1, axis=1).astype(np.int64).ravel()
    owner = np.repeat(np.arange(len(faces), dtype=np.int64), 3)
    keys = np.sort(tail * count + head)
    twin = head * count + tail
    position = np.minimum(np.searchsorted(keys, twin), keys.size - 1)
    border = keys[position] != twin
    return tail[border], head[border], owner[border]


def _next_edges(xy: np.ndarray, tail: np.ndarray, head: np.ndarray) -> np.ndarray:
    """La arista de borde que sigue a cada una: de las que salen de su destino, la primera
    en sentido antihorario desde la dirección de vuelta a su origen (la de menor ángulo mayor
    que el de esa dirección; si no hay, la de menor ángulo). Así se recorre cada región sin
    triángulos (hueco o exterior) por su lado: en un vértice donde se tocan dos huecos, o un
    hueco y el exterior, cada uno es un ciclo."""
    count = tail.size
    dx = xy[head, 0] - xy[tail, 0]
    dy = xy[head, 1] - xy[tail, 1]
    vertex = np.concatenate([tail, head])
    angle = np.concatenate([np.arctan2(dy, dx), np.arctan2(-dy, -dx)])
    arriving = np.concatenate([np.zeros(count, dtype=np.int8), np.ones(count, dtype=np.int8)])
    # Por vértice y ángulo; a igual ángulo, la salida antes que la vuelta («mayor que»).
    order = np.lexsort((arriving, angle, vertex))
    is_out = order < count
    position = np.arange(order.size)
    beyond = order.size
    next_out = np.minimum.accumulate(np.where(is_out, position, beyond)[::-1])[::-1]
    sorted_vertex = vertex[order]
    group_first = np.searchsorted(sorted_vertex, sorted_vertex, side="left")
    query = np.flatnonzero(~is_out)
    found = next_out[query]
    same = found < beyond
    same[same] = sorted_vertex[found[same]] == sorted_vertex[query[same]]
    found = np.where(same, found, next_out[group_first[query]])
    if (found >= beyond).any() or (sorted_vertex[np.minimum(found, beyond - 1)]
                                   != sorted_vertex[query]).any():
        raise ValueError("el borde del TIN no se puede recorrer: tiene triángulos solapados "
                         "u horarios")
    following = np.empty(count, dtype=np.int64)
    following[order[query] - count] = order[found]
    return following


def _tin_holes(xy: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """El área neta (m²) de cada hueco interior del TIN, de mayor a menor (y, a igual área,
    por el orden de su primera arista): ciclos del borde con área negativa menos las islas
    que tienen directamente dentro (ver el módulo)."""
    tail, head, owner = _boundary_edges(faces, len(xy))
    if not tail.size:
        return np.empty(0)
    # Diferencias exactas: todas las coordenadas del TIN son cercanas entre sí.
    rel = xy - xy.min(axis=0)
    following = _next_edges(rel, tail, head)
    count = tail.size
    root = _roots(count, np.arange(count, dtype=np.int64), following)
    cross = rel[tail, 0] * rel[head, 1] - rel[head, 0] * rel[tail, 1]
    loops = np.flatnonzero(root == np.arange(count))
    area = 0.5 * np.bincount(root, weights=cross, minlength=count)[loops]
    holes = np.flatnonzero(area < 0.0)
    if not holes.size:
        return np.empty(0)
    net = -area[holes]
    islands = np.flatnonzero(area > 0.0)
    if islands.size > 1:
        _subtract_islands(net, rel, faces, tail, head, owner, root, loops, holes,
                          islands, area)
    return net[np.argsort(-net, kind="stable")]


def _subtract_islands(net: np.ndarray, rel: np.ndarray, faces: np.ndarray,
                      tail: np.ndarray, head: np.ndarray, owner: np.ndarray,
                      root: np.ndarray, loops: np.ndarray, holes: np.ndarray,
                      islands: np.ndarray, area: np.ndarray) -> None:
    """Resta a cada hueco el área de los bordes exteriores que tiene directamente dentro: el
    hueco más pequeño que contiene el centroide del triángulo de su primera arista."""
    from .tin import _ray_hits  # aquí: ciclo de importación (ver el módulo)

    probe = rel[faces[owner[loops[islands]]]].mean(axis=1)
    loop_of_edge = np.searchsorted(loops, root)
    hole_of_loop = np.full(loops.size, -1, dtype=np.int64)
    hole_of_loop[holes] = np.arange(holes.size)
    edge_hole = hole_of_loop[loop_of_edge]
    hole_edges = np.flatnonzero(edge_hole >= 0)
    keys = [point * holes.size + edge_hole[hole_edges[side]]
            for point, side in _ray_hits(probe, rel[tail[hole_edges]], rel[head[hole_edges]])]
    if not keys:
        return
    pairs, hits = np.unique(np.concatenate(keys), return_counts=True)
    inside = pairs[hits % 2 == 1]
    island, hole = np.divmod(inside, holes.size)
    order = np.lexsort((-area[holes][hole], island))  # el hueco de menor área primero
    first = np.unique(island[order], return_index=True)[1]
    np.subtract.at(net, hole[order][first], area[islands][island[order][first]])


def validate_tin(
    tin: Tin,
    *,
    window: Window,
    z_range: Sequence[float] | None = None,
) -> SurfaceReport:
    """Valida el TIN ``tin`` frente a la ventana de trabajo ``window`` (``core.georef.Window``,
    absoluta) y el rango plausible de cotas (RF-006-23; ver el módulo). ``z_range`` como en
    :func:`validate_raster`. Devuelve un :class:`~.reports.SurfaceReport` de tipo ``tin``:
    área (la que encierra su borde exterior) y área sin dato (sus huecos interiores) en m²,
    el área neta de cada hueco de mayor a menor, los triángulos con algún vértice fuera de la
    ventana, los vértices con la cota fuera del rango, el % de triángulos planos, el lado
    máximo (m) y los degenerados. Entradas mal formadas: ``TypeError``. El TIN no se
    modifica."""
    from .tin import DEGENERATE_AREA_M2, Tin, _plan_areas, _sides  # ciclo (ver el módulo)

    if not isinstance(tin, Tin):
        raise TypeError(f"tin debe ser un Tin, no {type(tin).__name__}")
    if not isinstance(window, Window):
        raise TypeError(f"window debe ser una core.georef.Window, no {type(window).__name__}")
    low, high = _z_range(z_range)
    xy = tin.vertices[:, :2]
    z = tin.vertices[:, 2]
    faces = tin.faces
    outside_vertex = ((xy[:, 0] < window.xmin) | (xy[:, 0] > window.xmax)
                      | (xy[:, 1] < window.ymin) | (xy[:, 1] > window.ymax))
    areas = _plan_areas(xy, faces)
    holes = _tin_holes(xy, faces)
    nodata = float(holes.sum())
    return SurfaceReport(
        surface_type=SURFACE_TIN,
        area_m2=float(areas.sum()) + nodata,
        nodata_area_m2=nodata,
        hole_areas_m2=tuple(float(value) for value in holes),
        cells_outside_window=int(np.count_nonzero(outside_vertex[faces].any(axis=1))),
        out_of_range=int(np.count_nonzero((z < low) | (z > high))),
        z_range_m=(low, high),
        flat_pct=100.0 * tin.flat_faces / len(faces),
        max_edge_m=float(_sides(xy, faces).max()),
        degenerate=int(np.count_nonzero(areas < DEGENERATE_AREA_M2)),
    )
