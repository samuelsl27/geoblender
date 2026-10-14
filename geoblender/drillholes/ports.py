# SPDX-License-Identifier: GPL-3.0-or-later
"""Puertos de ``drillholes`` (spec 005; plan 005 §5.1 y §5.3.2; ADR-0004).

Las interfaces que ``drillholes`` define y que implementan otros: el dominio no sabe de dónde
salen las cotas del terreno (principios 3 y 4).

- :class:`SurfaceSampler`: la cota de una superficie (el MDT del proyecto) en puntos sueltos,
  para la diferencia con la cota de las bocas (RF-005-18, DH-W05). La implementa
  ``drillholes.surface.raster_sampler`` con la bilineal de ``gis.raster.sample`` sobre una
  rejilla de la 006 (D-19: solo rejillas, no TIN); un ``ports.py`` solo importa ``core``
  (ARQ-10), así que esa implementación no está aquí.

Coordenadas **absolutas** (CRS del proyecto, m, float64).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from numpy import ndarray

from ..core.georef import CrsRef, VerticalRef

__all__ = ["SurfaceSampler"]


@runtime_checkable
class SurfaceSampler(Protocol):
    """La cota de una superficie en puntos sueltos (RF-005-18).

    - ``crs`` y ``vertical``: el CRS horizontal de las coordenadas y la referencia vertical de
      las cotas de la superficie. La validación exige los de los sondeos (los del proyecto) y
      rechaza otros: nunca se suponen (principio 6).
    - ``sample(xy_abs)``: las cotas (m, float64, forma ``(n,)``) en los ``n`` puntos de
      ``xy_abs`` (X e Y **absolutas**, float64, forma ``(n, 2)``); NaN en un punto fuera de
      la superficie o sin dato. No modifica ``xy_abs``.
    """

    @property
    def crs(self) -> CrsRef: ...

    @property
    def vertical(self) -> VerticalRef: ...

    def sample(self, xy_abs: ndarray) -> ndarray: ...
