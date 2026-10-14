# SPDX-License-Identifier: GPL-3.0-or-later
"""Dónde caen las celdas con dato de un MDT: fuera de la ventana de trabajo o a más de 8 km del
GeoOrigin (spec 006, T51; §8 «MDT que sale de la ventana de trabajo o a más de 8 km del
GeoOrigin»: se importa entero, con aviso, y la rejilla del proyecto solo cubre la ventana;
RF-006-08, RF-006-11, RF-002-26).

- :func:`data_extent`: la extensión (bordes de celda, m) de las celdas con dato de una rejilla,
  sin las filas ni las columnas del borde que no tienen ninguna; ``None`` si no hay ninguna.
- :func:`cells_precision`: el aviso de RF-002-26 (``core.georef.PrecisionReport``: cuántos
  puntos pasan de 8 000 m del GeoOrigin en X o en Y y el error máximo estimado de float32 en la
  escena) de los **centros de las celdas con dato**: el mismo, campo a campo, que
  ``core.georef.precision_report`` sobre esos centros, calculado por filas y por columnas, sin
  construir los 100 M de puntos de un MDT grande (un MDT es una malla regular: un centro pasa
  del límite si su columna pasa en X o su fila pasa en Y). Las distancias, con
  ``core.georef.world_to_local`` (ARQ-14).
- :func:`extent_in`: esa extensión en el CRS del proyecto: la misma si la fuente ya lo está;
  si no, la caja de sus esquinas y de los puntos medios de sus lados transformados con la
  transformación de la importación (``gis.crs.transformation_for``); ``None`` si alguno no sale
  finito (fuera de la rejilla de la transformación).
- :func:`outside_window`: si una extensión sale de la ventana de trabajo por algún lado (más de
  :data:`EDGE_TOLERANCE_M`).

Lo calcula el trabajo de la importación (``gis.jobs``, ``gis_read_raster``), que tiene las
cotas, y lo presenta la orden en su informe; la vista avisa de lo que carga con
``precision_report`` (``bl.scene.views``). Coordenadas ABSOLUTAS en float64. Python puro y
numpy (ADR-0004).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..core.georef import (
    PRECISION_LIMIT_M,
    GeoOrigin,
    PrecisionReport,
    Window,
    precision_report,
    world_to_local,
)
from ..core.georef.transform import float32_error_mm
from .grid import Grid

if TYPE_CHECKING:
    from .ports import Transform

__all__ = [
    "EDGE_TOLERANCE_M",
    "cells_precision",
    "data_extent",
    "extent_in",
    "outside_window",
]

EDGE_TOLERANCE_M = 1e-6
"""Lo que un borde puede pasar del de la ventana sin salir de ella (m): el ruido de la coma
flotante de unas coordenadas que caen justo en el borde."""


def _check_valid(grid: Grid, valid: np.ndarray) -> np.ndarray:
    """La máscara de celdas con dato (``bool`` de la forma de ``grid``); si no lo es,
    ``ValueError`` (error del programa)."""
    mask = np.asarray(valid)
    if mask.dtype != np.bool_ or mask.shape != grid.shape:
        raise ValueError(f"la máscara de celdas con dato es bool {grid.shape}, no "
                         f"{mask.dtype} {mask.shape}")
    return mask


def data_extent(grid: Grid, valid: np.ndarray) -> Window | None:
    """La extensión de las celdas con dato (``valid``, ``bool`` de ``grid.shape``) de
    ``grid``: los bordes de la primera y la última fila y columna con alguna; ``None`` si no
    hay ninguna."""
    mask = _check_valid(grid, valid)
    rows = np.flatnonzero(mask.any(axis=1))
    if not len(rows):
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    return Window(
        grid.west + float(cols[0]) * grid.dx,
        grid.north - float(rows[-1] + 1) * grid.dy,
        grid.west + float(cols[-1] + 1) * grid.dx,
        grid.north - float(rows[0]) * grid.dy,
    )


def _axis_distances(grid: Grid, origin: GeoOrigin) -> tuple[np.ndarray, np.ndarray]:
    """|X| local de cada columna de centros y |Y| local de cada fila, con
    ``world_to_local`` sobre los centros de la primera fila y de la primera columna (los
    mismos números que ``Grid.centers``)."""
    x = grid.west + (np.arange(grid.ncols, dtype=np.float64) + 0.5) * grid.dx
    y = grid.north - (np.arange(grid.nrows, dtype=np.float64) + 0.5) * grid.dy
    first_row = world_to_local(np.column_stack([x, np.full(grid.ncols, y[0])]), origin)
    first_col = world_to_local(np.column_stack([np.full(grid.nrows, x[0]), y]), origin)
    return np.abs(first_row[:, 0]), np.abs(first_col[:, 1])


def cells_precision(grid: Grid, valid: np.ndarray, origin: GeoOrigin, *,
                    limit_m: float = PRECISION_LIMIT_M) -> PrecisionReport:
    """El aviso de RF-002-26 de los centros de las celdas con dato (``valid``) de ``grid``
    respecto a ``origin``: el que da ``core.georef.precision_report`` sobre esos centros
    (``kind`` ``"points"``), sin construirlos todos."""
    mask = _check_valid(grid, valid)
    rows_with_data = mask.any(axis=1)
    if not rows_with_data.any():
        return precision_report(np.empty((0, 2), dtype=np.float64), origin, limit_m)
    cols_with_data = mask.any(axis=0)
    across, along = _axis_distances(grid, origin)
    largest = float(max(across[cols_with_data].max(), along[rows_with_data].max()))
    far_cols = across > limit_m
    far_rows = along > limit_m
    count = int(np.count_nonzero(mask[:, far_cols]))
    if far_rows.any():
        count += int(np.count_nonzero(mask[far_rows][:, ~far_cols]))
    return PrecisionReport("points", limit_m, largest, float32_error_mm(largest),
                           points_outside=count)


def extent_in(extent: Window, transform: Transform | None) -> Window | None:
    """``extent`` en el CRS del proyecto: la misma sin ``transform``; con ella (la de la
    fuente al proyecto), la caja de sus cuatro esquinas y de los puntos medios de sus lados
    transformados (Z = 0); ``None`` si alguno no sale finito."""
    if transform is None:
        return extent
    xs = (extent.xmin, 0.5 * (extent.xmin + extent.xmax), extent.xmax)
    ys = (extent.ymin, 0.5 * (extent.ymin + extent.ymax), extent.ymax)
    points = np.array([(x, y, 0.0) for x in xs for y in ys if (x, y) != (xs[1], ys[1])],
                      dtype=np.float64)
    moved = np.asarray(transform.apply(points), dtype=np.float64)
    if moved.shape != points.shape or not np.isfinite(moved[:, :2]).all():
        return None
    return Window(float(moved[:, 0].min()), float(moved[:, 1].min()),
                  float(moved[:, 0].max()), float(moved[:, 1].max()))


def outside_window(extent: Window, window: Window, *,
                   tolerance_m: float = EDGE_TOLERANCE_M) -> bool:
    """``True`` si ``extent`` sale de ``window`` por algún lado en más de ``tolerance_m``."""
    return (extent.xmin < window.xmin - tolerance_m
            or extent.ymin < window.ymin - tolerance_m
            or extent.xmax > window.xmax + tolerance_m
            or extent.ymax > window.ymax + tolerance_m)
