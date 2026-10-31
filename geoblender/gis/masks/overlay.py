# SPDX-License-Identifier: GPL-3.0-or-later
"""El informe de los límites (spec 012; RF-012-05, RF-012-15; plan 012 A4, D-12 y D-14).

:func:`limits_report`: el área (m² y ha, D-12) del límite legal ``L``, del perímetro de
actuación ``P`` (sin perímetro, el límite legal, D-14), de ``L ∩ P`` y de la franja ``P ∖ L``
con cada una de sus partes (área y centro absoluto) como aviso, con la superposición exacta de
``gis.polygons.overlay`` (error relativo ≤ 10⁻⁹ frente al área exacta; errores 27 y 45 del
proyecto de referencia). Los límites de cada clase se unen antes (dos concesiones contiguas dan
lo mismo que una). :func:`report_of` lo da desde lo preparado para combinar
(``gis.masks.combine.Prepared``), con lo que queda fuera de la rejilla (RF-012-15).

Python puro con numpy (nivel 2).
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass

import numpy as np

from ..grid import Grid
from ..polygons import Part, drain, overlay
from .combine import Notice, Outside, Prepared

__all__ = ["M2_PER_HA", "LimitsReport", "limits_report", "limits_report_steps", "report_of",
           "report_steps"]

M2_PER_HA = 10_000.0
"""Metros cuadrados de una hectárea."""

type Rings = Sequence[np.ndarray]


@dataclass(frozen=True, slots=True)
class LimitsReport:
    """El informe de los límites (RF-012-05): áreas en m² (y en ha, sus propiedades ``*_ha``),
    las partes de la franja (de mayor a menor área; centro ABSOLUTO), si el perímetro es el
    límite legal y lo que queda fuera de la rejilla."""

    legal_m2: float
    perimeter_m2: float
    intersection_m2: float
    strip_m2: float
    strip_parts: tuple[Part, ...]
    perimeter_from_legal: bool
    outside: tuple[Outside, ...] = ()

    @property
    def legal_ha(self) -> float:
        return self.legal_m2 / M2_PER_HA

    @property
    def perimeter_ha(self) -> float:
        return self.perimeter_m2 / M2_PER_HA

    @property
    def intersection_ha(self) -> float:
        return self.intersection_m2 / M2_PER_HA

    @property
    def strip_ha(self) -> float:
        return self.strip_m2 / M2_PER_HA

    def notices(self) -> tuple[Notice, ...]:
        """Los avisos: lo que queda fuera de la rejilla y cada parte de la franja."""
        found = [Notice("core.constraint_zone_outside_grid", (
            ("code", item.code), ("name", item.name), ("ctype", item.ctype),
            ("area", round(item.area_m2, 2)))) for item in self.outside]
        found += [Notice("core.constraint_strip_part", (
            ("area", round(part.area_m2, 2)), ("hectares", round(part.area_m2 / M2_PER_HA, 4)),
            ("x", round(part.centroid[0], 2)), ("y", round(part.centroid[1], 2))))
            for part in self.strip_parts]
        return tuple(found)


def _positive(area: float) -> float:
    return area if area > 0.0 else 0.0


def limits_report_steps(legal: Sequence[Rings], perimeter: Sequence[Rings] | None, *,
                        origin: Sequence[float], outside: Sequence[Outside] = ()
                        ) -> Generator[None, None, LimitsReport]:
    """:func:`limits_report` por pasos: uno por superposición (RNF-012-06; T35)."""
    from_legal = not perimeter
    used = legal if from_legal else perimeter
    legal_m2 = _positive(overlay(legal, [], "union", origin=origin).area_m2)
    yield
    if from_legal:
        return LimitsReport(legal_m2, legal_m2, legal_m2, 0.0, (), True, tuple(outside))
    perimeter_m2 = _positive(overlay(used, [], "union", origin=origin).area_m2)
    yield
    both = _positive(overlay(used, legal, "intersection", origin=origin).area_m2)
    yield
    strip = overlay(used, legal, "difference", origin=origin)
    return LimitsReport(legal_m2, perimeter_m2, both, _positive(strip.area_m2), strip.parts,
                        False, tuple(outside))


def limits_report(legal: Sequence[Rings], perimeter: Sequence[Rings] | None, *,
                  origin: Sequence[float], outside: Sequence[Outside] = ()) -> LimitsReport:
    """El informe de los límites legales ``legal`` y del perímetro ``perimeter`` (cada uno, sus
    polígonos con sus anillos ABSOLUTOS; ``None`` o vacío: sin perímetro, el límite legal) con
    las superposiciones relativas a ``origin`` (``(x, y)`` absolutos cercanos, p. ej. la esquina
    suroeste de la rejilla)."""
    return drain(limits_report_steps(legal, perimeter, origin=origin, outside=outside))


def report_steps(prepared: Prepared, grid: Grid) -> Generator[None, None, LimitsReport]:
    """:func:`report_of` por pasos."""
    perimeter = None if prepared.limits.perimeter_from_legal else prepared.perimeter
    return limits_report_steps(prepared.legal, perimeter, origin=(grid.west, grid.extent.ymin),
                               outside=prepared.outside)


def report_of(prepared: Prepared, grid: Grid) -> LimitsReport:
    """:func:`limits_report` de lo preparado para combinar, en ``grid``."""
    return drain(report_steps(prepared, grid))
