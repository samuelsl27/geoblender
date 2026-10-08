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

La validación de un TIN (``validate_tin``: triángulos planos, lado máximo y degenerados) es de
la T19.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ..core.georef import Window
from . import params
from .raster import Raster
from .reports import SurfaceReport
from .resample import CELL_TOLERANCE

__all__ = ["BLOCK_ITEMS", "SURFACE_GRID", "Z_RANGE_KEY", "validate_raster"]

Z_RANGE_KEY = "gis.validate.z_range_m"
SURFACE_GRID = "grid"
"""El ``surface_type`` de una rejilla en :class:`~.reports.SurfaceReport`."""
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
