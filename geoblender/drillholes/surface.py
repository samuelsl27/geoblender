# SPDX-License-Identifier: GPL-3.0-or-later
"""La cota del MDT en las bocas, con una rejilla de la 006 (spec 005, T10; RF-005-18; plan 005
§5.6.6 y §5.6.12; D-19).

:func:`raster_sampler` da el :class:`~.ports.SurfaceSampler` de un ``gis.raster.Raster`` (el
``gis_dtm_*`` que se elige en «Validar»): su cota en cada punto es la **bilineal** de
``gis.raster.sample`` (la misma función que remuestrea la rejilla del proyecto, RF-006-11):
entre los cuatro centros vecinos; en un centro, su cota bit a bit; NaN si falta un vecino de
peso no nulo (fuera de los centros de la rejilla o sin dato). Solo rejillas, no TIN (D-19).

Está aquí y no en ``ports.py`` porque un ``ports.py`` solo importa ``core`` (ARQ-10);
``drillholes`` (nivel 3) sí puede importar ``gis`` (nivel 2, ARQ-07). ``validate`` no importa
este módulo: recibe el puerto.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from ..gis.raster import Raster, sample

__all__ = ["METHOD", "RasterSampler", "raster_sampler"]

METHOD = "bilinear"
"""El método de muestreo del MDT (RF-005-18: interpolación bilineal)."""


@dataclass(frozen=True, slots=True, eq=False)
class RasterSampler:
    """El :class:`~.ports.SurfaceSampler` de ``raster`` (véase el módulo): su CRS y su
    referencia vertical, y su cota bilineal en puntos absolutos."""

    raster: Raster

    def __post_init__(self) -> None:
        if not isinstance(self.raster, Raster):
            raise TypeError(f"el MDT es un gis.raster.Raster, no {type(self.raster).__name__}")

    @property
    def crs(self) -> CrsRef:
        return self.raster.crs

    @property
    def vertical(self) -> VerticalRef:
        return self.raster.vertical

    def sample(self, xy_abs: np.ndarray) -> np.ndarray:
        """Las cotas (float64, forma ``(n,)``; NaN fuera del MDT o sin dato) en los puntos
        ``xy_abs`` (``(n, 2)``, absolutos)."""
        return sample(self.raster, xy_abs, method=METHOD)


def raster_sampler(raster: Raster) -> RasterSampler:
    """El :class:`~.ports.SurfaceSampler` del MDT ``raster`` para la validación (DH-W05),
    con la bilineal de ``gis.raster.sample``. ``raster`` no se copia ni se modifica."""
    return RasterSampler(raster)
