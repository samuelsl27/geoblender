# SPDX-License-Identifier: GPL-3.0-or-later
"""El factor combinado de una cubicación y su efecto (spec 011, D-4; RF-011-01, RF-011-23,
RF-011-24; plan 011 A14 y D-34).

Los volúmenes y las áreas de una cubicación son **de cuadrícula**: los de la proyección del
proyecto, como los del proyecto de referencia, RecMin y QGIS (D-4 de la spec). Lo que separa una
medida de cuadrícula de una sobre el terreno se **informa, no se aplica**:

- el factor de escala de la proyección ``k`` en un punto (:func:`center`: el centro del ámbito o,
  sin él, el de la rejilla), que da ``gis.ports.CrsService.scale_factor`` (el adaptador de
  pyproj de la 006; lo llama ``bl`` y lo pasa a la cubicación: este módulo no sabe de pyproj);
- el factor de elevación ``R/(R + h)``, con ``R`` = :data:`EARTH_RADIUS_M` y ``h`` la cota media
  de lo cubicado;
- el combinado ``F = k·R/(R + h)`` y su efecto en áreas y volúmenes, ``1/F² − 1`` (en %): una
  distancia de cuadrícula es la del terreno por ``F``, así que un área del terreno es la de
  cuadrícula entre ``F²`` (las alturas no cambian).

A 1 000 m de altitud la elevación sola da ≈ 0,03 %; con ``k = 0,9996`` (el meridiano central de
una UTM), ≈ 0,11 % (inv. 08 §3.3). Python puro (nivel 9).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..gis.grid import Grid
    from .polygons import Polygon

__all__ = [
    "EARTH_RADIUS_M",
    "CombinedFactor",
    "center",
    "combined_factor",
    "elevation_factor",
]

EARTH_RADIUS_M = 6_371_000.0
"""El radio medio de la Tierra (m) del factor de elevación (D-34: el radio de Gauss en la
latitud cambiaría el efecto en menos de 10⁻⁵)."""


def _finite(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise ValueError(f"{what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} es un número finito, no {value!r}")
    return number


def elevation_factor(elevation_m: float) -> float:
    """El factor de elevación ``R/(R + h)`` a la cota ``elevation_m`` (m); :class:`ValueError`
    si no es un número finito por encima de ``−R``."""
    h = _finite(elevation_m, "la cota media")
    if not h > -EARTH_RADIUS_M:
        raise ValueError(f"la cota media ({h!r} m) no puede estar a más de un radio de la Tierra "
                         "por debajo del elipsoide")
    return EARTH_RADIUS_M / (EARTH_RADIUS_M + h)


@dataclass(frozen=True, slots=True)
class CombinedFactor:
    """El factor combinado de una cubicación: ``point_scale`` (``k``, el de la proyección en su
    punto) y ``elevation_m`` (``h``, la cota media de lo cubicado, m)."""

    point_scale: float
    elevation_m: float

    @property
    def elevation_factor(self) -> float:
        """``R/(R + h)``."""
        return elevation_factor(self.elevation_m)

    @property
    def combined(self) -> float:
        """``F = k·R/(R + h)``: distancia de cuadrícula / distancia del terreno."""
        return self.point_scale * self.elevation_factor

    @property
    def effect_pct(self) -> float:
        """El efecto en áreas y volúmenes (%): ``(1/F² − 1)·100``; positivo si el terreno mide
        más que la cuadrícula."""
        combined = self.combined
        return (1.0 / (combined * combined) - 1.0) * 100.0


def combined_factor(point_scale: float, elevation_m: float) -> CombinedFactor:
    """El factor combinado con ``k = point_scale`` (positivo y finito) y la cota media
    ``elevation_m`` (m); :class:`ValueError` si alguno no vale."""
    k = _finite(point_scale, "el factor de escala de la proyección")
    if not k > 0.0:
        raise ValueError(f"el factor de escala de la proyección es positivo, no {point_scale!r}")
    h = _finite(elevation_m, "la cota media")
    elevation_factor(h)
    return CombinedFactor(k, h)


def center(grid: Grid, scope: Sequence[Polygon] | None = None) -> tuple[float, float]:
    """El punto (x, y absolutos, float64) donde se toma el factor de escala de la proyección:
    el centro de la caja de los contornos exteriores del ámbito ``scope`` o, sin él, el de la
    rejilla ``grid``."""
    if scope:
        points = np.concatenate([np.asarray(part.rings[0], dtype=np.float64).reshape(-1, 2)
                                 for part in scope])
        low, high = points.min(axis=0), points.max(axis=0)
        return float((low[0] + high[0]) / 2.0), float((low[1] + high[1]) / 2.0)
    extent = grid.extent
    return float((extent.xmin + extent.xmax) / 2.0), float((extent.ymin + extent.ymax) / 2.0)
