# SPDX-License-Identifier: GPL-3.0-or-later
"""Fracción exacta del área de cada celda dentro de un polígono (spec 011; RF-011-01,
RF-011-07; plan 011 A5, D-5 y D-21).

El cálculo está en ``gis.coverage`` desde la spec 012 (plan 012 §5.6, D-18 y T2: lo usan también
las máscaras de las restricciones y el diseño, que no pueden importar ``reserves``); aquí se
reexporta con los mismos objetos, para que la cubicación y sus pruebas no cambien.
"""

from __future__ import annotations

from ..gis.coverage import (
    FRACTION_EPSILON,
    CoverageBand,
    band_coverage,
    polygon_edges,
    signed_area,
)

__all__ = [
    "FRACTION_EPSILON",
    "CoverageBand",
    "band_coverage",
    "polygon_edges",
    "signed_area",
]
