# SPDX-License-Identifier: GPL-3.0-or-later
"""Fracción exacta del área de cada celda dentro de un polígono (spec 011; RF-011-01,
RF-011-07; plan 011 A5, D-5 y D-21; bajada de ``reserves.coverage`` a ``gis`` sin cambiar el
cálculo en la spec 012, plan 012 §5.6, D-18 y T2, para las máscaras de las restricciones,
RF-012-12, y el diseño; ``reserves.coverage`` la reexporta).

Una cubicación se reparte entre polígonos (los dominios, recortados por el ámbito) por la
**fracción exacta del área de cada celda** que queda dentro de cada uno (D-5), no por su centro:
así el área de cada dominio es la de su polígono, los de una partición suman 1 en cada celda y uno
menor que una celda recibe lo suyo.

El cálculo es el del rasterizador de área con signo (FreeType; *font-rs*, R. Levien, 2016), sobre
las **aristas orientadas** del polígono (exterior antihorario, huecos horarios): cada arista se
parte en las líneas de la rejilla; cada trozo, dentro de la celda de columna ``i`` de su fila,
aporta su *cubierta* ``Δy`` y su *área* ``Δy·((i + 1) − x̄)`` (lo que queda a su derecha dentro
de la celda), en unidades de celda; la fracción de la celda es ``−(área(i) + Σ_{i' < i}
cubierta(i'))``, una suma acumulada por filas. Es exacta salvo el redondeo de float64.

- :func:`polygon_edges`: los anillos ABSOLUTOS de un polígono (el primero, el exterior) como
  aristas orientadas, en metros **relativos a la esquina suroeste** de la rejilla, con los
  sentidos normalizados (vengan como vengan, y cerrados o no).
- :func:`band_coverage`: las celdas tocadas de una **banda de filas** (la fila 0 es la del
  norte), con su fracción; por bandas sale bit a bit lo mismo que de una vez.
- :func:`signed_area`: el área con signo de un anillo (positiva si es antihorario).
- ``band_spans`` (spec 012, T40): las celdas de una banda con una fracción mayor que un umbral
  como **tramos de fila**, sin la matriz de la banda: las mismas celdas que :func:`band_coverage`
  (bit a bit) para un polígono mucho mayor que la rejilla, a coste de las celdas que cruzan sus
  aristas. No cambia el cálculo de arriba: es otra forma de sumar lo mismo.

Precisión: restar la esquina suroeste a unas coordenadas de la rejilla es exacto en float64 (lema
de Sterbenz), y en unidades de celda los números son pequeños. Cada corte de una arista con una
línea de la rejilla se calcula desde sus extremos **en un orden fijo** (de menor a mayor), así que
una arista común a dos polígonos, recorrida en sentidos opuestos, da en los dos los mismos trozos
con el signo cambiado: se cancelan bit a bit. Solo se cortan las líneas de la rejilla dentro de las
columnas y de las filas de la banda: lo que queda al oeste de la rejilla solo aporta su cubierta;
lo del este, nada.

Una celda que el polígono no toca puede quedar con un residuo del redondeo (≈ 10⁻¹⁶) en lugar
de 0: las fracciones de valor absoluto ≤ :data:`FRACTION_EPSILON` no se dan (es un área de
10⁻¹² de la celda). Python puro con numpy (nivel 2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .grid import Grid

__all__ = [
    "FRACTION_EPSILON",
    "CoverageBand",
    "band_coverage",
    "polygon_edges",
    "signed_area",
]

FRACTION_EPSILON = 1e-12
"""Por debajo de este valor absoluto, una fracción es un residuo del redondeo y no se da."""


@dataclass(frozen=True, slots=True)
class CoverageBand:
    """Las celdas tocadas de una banda de filas: ``rows`` y ``cols`` (int64; la fila 0 es la del
    norte) y ``fraction`` (float64, la fracción de su área dentro del polígono, en [0, 1] salvo
    el redondeo), en orden de filas y, dentro de cada una, de columnas; cada celda, una vez."""

    rows: np.ndarray
    cols: np.ndarray
    fraction: np.ndarray

    def __len__(self) -> int:
        return int(self.fraction.size)


def _empty() -> CoverageBand:
    return CoverageBand(np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64),
                        np.zeros(0, dtype=np.float64))


def _open_ring(ring: object) -> np.ndarray:
    """El anillo como array ``(k, 2)`` float64, sin repetir al final el primer vértice."""
    points = np.asarray(ring, dtype=np.float64)
    if points.ndim != 2 or points.shape[0] == 0 or points.shape[1] < 2:
        raise ValueError(f"Un anillo es un array (k, 2) de vértices, no de forma {points.shape}")
    points = points[:, :2]
    if not np.all(np.isfinite(points)):
        raise ValueError("Un anillo tiene vértices no finitos")
    if points.shape[0] > 1 and np.array_equal(points[0], points[-1]):
        points = points[:-1]
    return points


def signed_area(ring: np.ndarray) -> float:
    """El área con signo (en las unidades de las coordenadas al cuadrado) del anillo ``(k, 2)``,
    cerrado o no: positiva si es antihorario y negativa si es horario. Se calcula respecto a su
    primer vértice, para no perder precisión con coordenadas grandes."""
    points = _open_ring(ring)
    relative = points - points[0]
    x, y = relative[:, 0], relative[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def polygon_edges(rings: Sequence[np.ndarray], grid: Grid) -> np.ndarray:
    """Las aristas orientadas ``(n, 2, 2)`` (``[arista, extremo, (x, y)]``) del polígono de los
    anillos ABSOLUTOS ``rings`` (el primero, el exterior; los demás, sus huecos), en metros
    relativos a la esquina suroeste de ``grid``: el exterior en sentido antihorario y los
    huecos en horario, vengan como vengan. Cada anillo es una cadena cerrada de aristas.

    Un polígono sin anillos o un anillo de menos de tres vértices es un error del programa
    (:class:`ValueError`): los polígonos del usuario los valida antes ``gis.polygons``."""
    if len(rings) == 0:
        raise ValueError("Un polígono tiene al menos un anillo (el exterior)")
    corner = np.array([grid.west, grid.extent.ymin], dtype=np.float64)
    parts = []
    for number, ring in enumerate(rings):
        points = _open_ring(ring)
        if points.shape[0] < 3:
            raise ValueError(f"Un anillo tiene al menos tres vértices, no {points.shape[0]}")
        points = points - corner
        area = signed_area(points)
        if (area < 0.0) if number == 0 else (area > 0.0):
            points = points[::-1]
        parts.append(np.stack([points, np.roll(points, -1, axis=0)], axis=1))
    return np.ascontiguousarray(np.concatenate(parts))


def _ranges(first: np.ndarray, last: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada ``e``, los enteros de ``first[e]`` a ``last[e]`` (floats enteros): ``(dueño,
    valor)``, en orden de dueño y de valor."""
    count = np.maximum(last - first + 1.0, 0.0).astype(np.int64)
    owner = np.repeat(np.arange(first.size), count)
    offset = np.arange(owner.size, dtype=np.float64) - np.repeat(
        (np.cumsum(count) - count).astype(np.float64), count)
    return owner, first[owner] + offset


def _pieces(u: np.ndarray, v: np.ndarray, ncols: int, low: int, high: int
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Los trozos de las aristas ``(u, v)`` (``(m, 2)``, unidades de celda desde la esquina
    suroeste) entre sus cortes con las líneas ``x = 0…ncols`` e ``y = low…high``: su columna, su
    fila (desde el sur), su cubierta y su área, en orden de arista y de recorrido."""
    swap = (u[:, 1] < u[:, 0]) | ((u[:, 1] == u[:, 0]) & (v[:, 1] < v[:, 0]))
    au = np.where(swap, u[:, 1], u[:, 0])
    bu = np.where(swap, u[:, 0], u[:, 1])
    av = np.where(swap, v[:, 1], v[:, 0])
    bv = np.where(swap, v[:, 0], v[:, 1])
    sign = np.where(swap, -1.0, 1.0)
    du, dv = bu - au, bv - av
    # Cortes con x = k (au < k < bu) y con y = k (entre av y bv), solo dentro de la banda.
    xo, xk = _ranges(np.maximum(np.floor(au) + 1.0, 0.0), np.minimum(np.ceil(bu) - 1.0, ncols))
    xt = (xk - au[xo]) / du[xo]
    xv = av[xo] + xt * dv[xo]
    lo, hi = np.minimum(av, bv), np.maximum(av, bv)
    yo, yk = _ranges(np.maximum(np.floor(lo) + 1.0, low), np.minimum(np.ceil(hi) - 1.0, high))
    yt = (yk - av[yo]) / dv[yo]
    yu = au[yo] + yt * du[yo]
    edges = np.arange(au.size)
    owner = np.concatenate([edges, xo, yo, edges])
    t = np.concatenate([np.zeros(au.size), xt, yt, np.ones(au.size)])
    pu = np.concatenate([au, xk, yu, bu])
    pv = np.concatenate([av, xv, yk, bv])
    order = np.lexsort((t, owner))
    owner, pu, pv = owner[order], pu[order], pv[order]
    same = np.flatnonzero(owner[1:] == owner[:-1])
    ua, ub, va, vb = pu[same], pu[same + 1], pv[same], pv[same + 1]
    cover = sign[owner[same]] * (vb - va)
    keep = cover != 0.0
    ua, ub, va, vb, cover = ua[keep], ub[keep], va[keep], vb[keep], cover[keep]
    middle = 0.5 * (ua + ub)
    col = np.floor(middle)
    row = np.floor(0.5 * (va + vb))
    area = cover * ((col + 1.0) - middle)
    return col.astype(np.int64), row.astype(np.int64), cover, area


def band_coverage(edges: np.ndarray, grid: Grid, rows: slice) -> CoverageBand:
    """La fracción exacta del área de cada celda de la banda de filas ``rows`` de ``grid`` (la
    fila 0 es la del norte; sin paso) dentro del polígono de las aristas orientadas ``edges``
    (``(n, 2, 2)``, en metros relativos a la esquina suroeste: exterior antihorario y huecos
    horarios, como las da :func:`polygon_edges`). Da las celdas tocadas (fracción distinta de 0
    salvo :data:`FRACTION_EPSILON`), en orden de filas y columnas; por bandas sale bit a bit lo
    mismo que de una vez.

    Unas aristas que no son ``(n, 2, 2)`` o no finitas, o una banda con paso, son un error del
    programa (:class:`ValueError`)."""
    edges = np.asarray(edges, dtype=np.float64)
    if edges.ndim != 3 or edges.shape[1:] != (2, 2):
        raise ValueError(f"Las aristas son un array (n, 2, 2), no de forma {edges.shape}")
    if not np.all(np.isfinite(edges)):
        raise ValueError("Las aristas tienen coordenadas no finitas")
    start, stop, step = rows.indices(grid.nrows)
    if step != 1:
        raise ValueError(f"Una banda son filas seguidas, no con paso {step}")
    if stop <= start or edges.shape[0] == 0:
        return _empty()
    ncols = grid.ncols
    low, high = grid.nrows - stop, grid.nrows - start   # la banda, en filas desde el sur
    u = edges[:, :, 0] / grid.dx
    v = edges[:, :, 1] / grid.dy
    near = np.flatnonzero((v.max(axis=1) >= low) & (v.min(axis=1) <= high))
    if near.size == 0:
        return _empty()
    col, row, cover, area = _pieces(u[near], v[near], ncols, low, high)
    band = (row >= low) & (row < high)
    left = band & (col < 0)
    right = band & (col >= ncols)
    body = band & (col >= 0) & (col < ncols)
    if not body.any() and not (left.any() and right.any()):
        return _empty()
    first_col = 0 if left.any() else int(col[body].min())
    end_col = ncols if right.any() else int(col[body].max()) + 1
    touched = row[left | right | body]
    first_row, end_row = int(touched.min()), int(touched.max()) + 1
    height, width = end_row - first_row, end_col - first_col
    index = (row[body] - first_row) * width + (col[body] - first_col)
    cell_area = np.bincount(index, weights=area[body], minlength=height * width)
    cell_cover = np.bincount(index, weights=cover[body], minlength=height * width)
    run = np.empty((height, width), dtype=np.float64)
    run[:, 0] = np.bincount(row[left] - first_row, weights=cover[left], minlength=height)
    run[:, 1:] = cell_cover.reshape(height, width)[:, :-1]
    fraction = -(cell_area.reshape(height, width) + np.cumsum(run, axis=1))
    fraction = fraction[::-1]   # de norte a sur, como las filas de la rejilla
    found = np.abs(fraction) > FRACTION_EPSILON
    found_rows, found_cols = np.nonzero(found)
    return CoverageBand(
        (found_rows + (grid.nrows - end_row)).astype(np.int64),
        (found_cols + first_col).astype(np.int64),
        np.ascontiguousarray(fraction[found]),
    )


def _no_spans() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64),
            np.zeros(0, dtype=np.int64))


def band_spans(edges: np.ndarray, grid: Grid, rows: slice, threshold: float
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Las celdas de la banda de filas ``rows`` de ``grid`` con una fracción de su área dentro del
    polígono de las aristas orientadas ``edges`` **mayor que** ``threshold`` (un número ≥
    :data:`FRACTION_EPSILON`), como tramos de fila ``(row, col0, col1)`` (int64: la fila 0 es la del
    norte y ``col1`` es la columna siguiente a la última del tramo; sin ordenar ni unir): las
    mismas celdas que :func:`band_coverage` con ``fraction > threshold``, **sin la matriz de la
    banda**.

    :func:`band_coverage` construye la matriz de todas las columnas entre la primera y la última
    celda que cruzan las aristas, de modo que una banda de un polígono de 50 km con celdas de 1 m
    pesa 12,8 millones de celdas aunque solo cruzan sus aristas unas pocas. Aquí las columnas
    son las que cruzan las aristas de la banda y, tras cada una, **una sola** para el hueco hasta
    la siguiente cruzada: ahí la fracción es la misma en todas (la suma acumulada de lo cubierto
    desde el oeste, porque ninguna arista la cambia) y el hueco entero entra o no. Se suma lo
    mismo en el mismo orden (sumar ceros no cambia un ``float64``), así que cada fracción es, bit
    a bit, la de la matriz; el coste es el de las celdas cruzadas y no el ancho del polígono
    (RNF-012-06).

    Unas aristas que no son ``(n, 2, 2)`` o no finitas, o una banda con paso, son un error del
    programa (:class:`ValueError`)."""
    edges = np.asarray(edges, dtype=np.float64)
    if edges.ndim != 3 or edges.shape[1:] != (2, 2):
        raise ValueError(f"Las aristas son un array (n, 2, 2), no de forma {edges.shape}")
    if not np.all(np.isfinite(edges)):
        raise ValueError("Las aristas tienen coordenadas no finitas")
    start, stop, step = rows.indices(grid.nrows)
    if step != 1:
        raise ValueError(f"Una banda son filas seguidas, no con paso {step}")
    if stop <= start or edges.shape[0] == 0:
        return _no_spans()
    ncols = grid.ncols
    low, high = grid.nrows - stop, grid.nrows - start   # la banda, en filas desde el sur
    u = edges[:, :, 0] / grid.dx
    v = edges[:, :, 1] / grid.dy
    near = np.flatnonzero((v.max(axis=1) >= low) & (v.min(axis=1) <= high))
    if near.size == 0:
        return _no_spans()
    col, row, cover, area = _pieces(u[near], v[near], ncols, low, high)
    band = (row >= low) & (row < high)
    left = band & (col < 0)
    right = band & (col >= ncols)
    body = band & (col >= 0) & (col < ncols)
    if not body.any() and not (left.any() and right.any()):
        return _no_spans()
    first_col = 0 if left.any() else int(col[body].min())
    end_col = ncols if right.any() else int(col[body].max()) + 1
    touched = row[left | right | body]
    first_row, end_row = int(touched.min()), int(touched.max()) + 1
    height = end_row - first_row
    # Las columnas de la matriz comprimida: el hueco de antes de la primera cruzada (0), cada
    # cruzada (1, 3, 5…) y el hueco de después de cada una (2, 4, 6…).
    crossed = np.unique(col[body])
    width = 2 * crossed.size + 1
    index = (row[body] - first_row) * width + 2 * np.searchsorted(crossed, col[body]) + 1
    cell_area = np.bincount(index, weights=area[body], minlength=height * width)
    cell_cover = np.bincount(index, weights=cover[body], minlength=height * width)
    run = np.empty((height, width), dtype=np.float64)
    run[:, 0] = np.bincount(row[left] - first_row, weights=cover[left], minlength=height)
    run[:, 1:] = cell_cover.reshape(height, width)[:, :-1]
    fraction = -(cell_area.reshape(height, width) + np.cumsum(run, axis=1))
    found_row, found_slot = np.nonzero(fraction > threshold)
    north = grid.nrows - 1 - (first_row + found_row)   # de norte a sur, como la rejilla
    single = (found_slot & 1) == 1
    # El hueco ``j`` va de la columna siguiente a la cruzada ``j − 1`` a la cruzada ``j``.
    bounds = np.concatenate(([first_col - 1], crossed, [end_col])).astype(np.int64)
    gap = found_slot[~single] // 2
    gap_first, gap_end = bounds[gap] + 1, bounds[gap + 1]
    long = gap_end > gap_first
    cells = crossed[found_slot[single] // 2]
    return (np.concatenate([north[single], north[~single][long]]),
            np.concatenate([cells, gap_first[long]]),
            np.concatenate([cells + 1, gap_end[long]]))
