# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera con dos superficies: el recinto excavable (spec 014, T06; HU-014-1; RF-014-01; plan
014 A1, §5.3.1).

- :func:`excavation_area`: el **recinto excavable** de una versión, ``R = masks.cut_allowed() ∧
  isfinite(z)`` (A1): el corte admitido de sus máscaras de la 012 —el dominio por defecto, perímetro
  de actuación ∩ límite legal − intocables y exclusiones, menos el resguardo hacia dentro del límite
  y las zonas sin corte, solo relleno o solo restauración (RF-012-13)— donde la superficie de partida
  ``z`` tiene dato. Vacío, :class:`~.messages.DesignError` ``des.quarry_area_empty`` con el área de
  cada parte que lo vacía (:func:`area_parts`).
- :func:`area_parts`: lo que separa el perímetro de actuación del recinto, por partes disjuntas
  (:class:`AreaPart`) en este orden: el perímetro fuera del límite legal, los intocables y las
  exclusiones, el resguardo hacia dentro del límite, las zonas que no admiten corte y las celdas sin
  dato de terreno. Con el recinto, suman el perímetro.
- :func:`area_outcome`: el recinto medido (:class:`AreaOutcome`): su rejilla para el GeoTIFF
  ``des_rcn_`` (1 dentro, sin dato fuera), sus celdas, su área en m² (las celdas por el área de
  celda) y la cifra CALCULADO ``des.rcn_area_m2``.

Las demás piezas de la cantera (semillas, fondos, techo, corredores, ancla y las dos superficies)
llegan con sus tareas. Python puro con numpy (nivel 8): no importa ``reserves`` ni ``bl``; no
escribe nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from ..gis.messages import format_value
from . import provenance
from .messages import DesignError

__all__ = [
    "AREA_PART_LABELS",
    "AreaOutcome",
    "AreaPart",
    "area_outcome",
    "area_parts",
    "excavation_area",
]

AREA_PART_LABELS = MappingProxyType({
    "outside_limit": "perímetro fuera del límite legal",
    "untouchable": "intocables y exclusiones",
    "inner_band": "resguardo hacia dentro del límite",
    "no_cut": "zonas sin corte, solo relleno o solo restauración",
    "no_terrain": "sin dato de terreno",
})
"""Las partes que separan el perímetro de actuación del recinto, en su orden, con su texto."""
_NO_PERIMETER = "el perímetro de actuación no tiene ninguna celda en la rejilla"
_AREA_FIGURE = "des.rcn_area_m2"


@dataclass(frozen=True, slots=True)
class AreaPart:
    """Una parte de lo que vacía el recinto (:func:`area_parts`): su clave de
    :data:`AREA_PART_LABELS`, sus celdas y su área en m²."""

    key: str
    cells: int
    area_m2: float

    @property
    def label(self) -> str:
        """Su texto en español."""
        return AREA_PART_LABELS[self.key]


@dataclass(frozen=True, slots=True, eq=False)
class AreaOutcome:
    """El recinto medido: su ``grid`` (float64, nueva: 1 dentro y ``NaN`` fuera), sus ``cells``,
    su ``area_m2``, las cifras CALCULADO (``figures``: ``des.rcn_area_m2`` con el ámbito del nombre)
    y el ``message`` de la operación."""

    grid: np.ndarray
    cells: int
    area_m2: float
    figures: tuple[FigureSpec, ...]
    message: str


def _bit(masks: MaskSet, bit: ClassBit) -> np.ndarray:
    return (masks.classes & np.uint16(int(bit))) != 0


def _terrain(masks: MaskSet, start: np.ndarray) -> np.ndarray:
    """Las celdas con dato de la superficie de partida ``start``; ``ValueError`` si no es una
    rejilla de la forma de la de las máscaras."""
    values = np.asarray(start)
    if values.shape != masks.grid.shape:
        raise ValueError(f"la superficie de partida es de {values.shape} celdas, no de las "
                         f"{masks.grid.shape} de la rejilla de las máscaras")
    with np.errstate(invalid="ignore"):
        return np.isfinite(values)


def area_parts(masks: MaskSet, start: np.ndarray) -> tuple[AreaPart, ...]:
    """Lo que separa el perímetro de actuación de ``masks`` del recinto (A1, RF-014-01), por
    partes disjuntas en el orden de :data:`AREA_PART_LABELS` (todas, también las vacías): las
    celdas del perímetro fuera del límite legal; dentro, las de los intocables y las exclusiones;
    del resto, las del resguardo hacia dentro del límite; del resto del dominio por defecto, las que
    no admiten corte; y las que lo admiten sin dato en ``start``. Solo lee."""
    terrain = _terrain(masks, start)
    perimeter = _bit(masks, ClassBit.PERIMETER)
    legal = _bit(masks, ClassBit.LEGAL)
    untouchable = _bit(masks, ClassBit.UNTOUCHABLE)
    band = _bit(masks, ClassBit.INNER_BAND)
    cut = masks.cut_allowed()
    inside = perimeter & legal
    domain = inside & ~untouchable
    found = {
        "outside_limit": perimeter & ~legal,
        "untouchable": inside & untouchable,
        "inner_band": domain & band,
        "no_cut": domain & ~band & ~cut,
        "no_terrain": cut & ~terrain,
    }
    area = masks.grid.cell_area
    return tuple(AreaPart(key, int(np.count_nonzero(cells)), int(np.count_nonzero(cells)) * area)
                 for key, cells in found.items())


def _parts_text(parts: tuple[AreaPart, ...]) -> str:
    shown = [f"{part.label}: {format_value(round(part.area_m2, 2))} m²" for part in parts
             if part.cells]
    return "; ".join(shown) if shown else _NO_PERIMETER


def excavation_area(masks: MaskSet, start: np.ndarray, *, version: str | None = None
                    ) -> np.ndarray:
    """**A1** (RF-014-01): el recinto excavable, ``masks.cut_allowed() ∧ isfinite(start)``, como
    máscara nueva de la rejilla de ``masks`` (``start``, la superficie de partida en float64, de su
    forma). Ninguna entrada se modifica.

    Rechazos: ``DesignError`` ``des.quarry_area_empty`` si no tiene ninguna celda, con la versión
    ``version`` (su código; sin él, el uid de las máscaras) y el área de cada parte que lo vacía
    (:func:`area_parts`); ``ValueError`` (error del programa) si ``start`` no es de la forma de la
    rejilla."""
    terrain = _terrain(masks, start)
    area = masks.cut_allowed() & terrain
    if not area.any():
        shown = version or masks.version_uid
        raise DesignError("des.quarry_area_empty", obj=f"Recinto de la versión {shown}",
                          field="recinto", value=0, version=shown,
                          parts=_parts_text(area_parts(masks, start)))
    return area


def area_outcome(name: str, area: np.ndarray, geometry: Grid) -> AreaOutcome:
    """El recinto ``area`` (máscara de ``geometry``) de la operación ``name`` medido
    (:class:`AreaOutcome`): la rejilla del GeoTIFF, sus celdas, su área (celdas · área de celda,
    m²) y la cifra ``des.rcn_area_m2`` con el ámbito de ``provenance.figure_scope``.
    ``ValueError`` si ``area`` no es de la forma de ``geometry``."""
    mask = np.asarray(area, dtype=bool)
    if mask.shape != geometry.shape:
        raise ValueError(f"el recinto es de {mask.shape} celdas, no de las {geometry.shape} de "
                         "la rejilla")
    cells = int(np.count_nonzero(mask))
    area_m2 = cells * geometry.cell_area
    grid = np.where(mask, 1.0, np.nan)
    figures = (FigureSpec(_AREA_FIGURE, float(area_m2), "m2",
                          scope=provenance.figure_scope(name)),)
    text = (f"Recinto «{name}» calculado: {cells} celdas "
            f"({format_value(round(area_m2, 2))} m²)")
    return AreaOutcome(grid, cells, float(area_m2), figures, text)
