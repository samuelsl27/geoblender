# SPDX-License-Identifier: GPL-3.0-or-later
"""Superficies en rejilla (spec 006; plan 006 §5.3.2; ADR-0005, ADR-0014).

- :class:`Raster`: una superficie en una :class:`~.grid.Grid` del proyecto o importada: sus
  cotas en float64 (m; NaN = sin dato), una por celda, con las filas de norte a sur, y el
  CRS horizontal y la referencia vertical a los que se refieren (``core.georef``, spec
  002), que nunca se suponen (constitución, principio 6).

Las coordenadas de la rejilla son **absolutas** (CRS del proyecto, m, float64).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from .grid import Grid

__all__ = ["Raster"]


@dataclass(frozen=True, slots=True, eq=False)
class Raster:
    """Superficie en rejilla: ``grid`` (absoluta), ``values`` (cotas en m, float64, de forma
    ``grid.shape``, fila 0 al norte; NaN = sin dato), ``crs`` y ``vertical``.

    ``values`` no se copia: quien crea el ráster no debe modificarlo después. Uno mal formado
    (otro tipo de datos, otra forma, una rejilla, un CRS o una referencia vertical que no lo
    son) es un error del programa (``TypeError`` o ``ValueError``): los lectores validan antes
    la fuente, con un error para el usuario. La igualdad es la identidad (``eq=False``): dos
    rásteres se comparan por su rejilla y sus valores, explícitamente.
    """

    grid: Grid
    values: np.ndarray
    crs: CrsRef
    vertical: VerticalRef

    def __post_init__(self) -> None:
        if not isinstance(self.grid, Grid):
            raise TypeError(f"Raster.grid debe ser una Grid, no {type(self.grid).__name__}")
        if not isinstance(self.values, np.ndarray) or self.values.dtype != np.float64:
            found = getattr(self.values, "dtype", type(self.values).__name__)
            raise TypeError(f"Raster.values debe ser un array float64, no {found}")
        if self.values.shape != self.grid.shape:
            raise ValueError(
                f"Raster.values tiene la forma {self.values.shape} y su rejilla, "
                f"{self.grid.shape}"
            )
        if not isinstance(self.crs, CrsRef):
            raise TypeError(f"Raster.crs debe ser un CrsRef, no {type(self.crs).__name__}")
        if not isinstance(self.vertical, VerticalRef):
            raise TypeError(
                f"Raster.vertical debe ser un VerticalRef, no {type(self.vertical).__name__}"
            )
