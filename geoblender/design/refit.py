# SPDX-License-Identifier: GPL-3.0-or-later
"""El diseño frente a un límite nuevo (spec 014; HU-014-7; RF-014-26; plan 014 A13, §5.3.1; el
error 46 del análisis).

**La comprobación** (T31; RF-014-26): cuando se recompilan las máscaras de una versión, cada
superficie de esta spec que tiene (las dos de una cantera, una transición, un diseño «solo
relleno», un ajuste) se compara con el límite vigente: :func:`outside_volume` da el volumen y el
área de lo que mueve fuera de él (:class:`RefitCheck`) y su aviso ``des.refit_outside``, que lleva a
«Ajustar el diseño a un límite nuevo…». Quien lee las superficies del proyecto es
``design.store.limit_checks``.

- **Lo que mueve** una superficie ``S`` frente a su partida ``z``: las celdas con dato en las dos y
  ``|S − z|`` mayor que el espesor mínimo de la 012 (``design.report.moved_cells``, la máscara del
  informe de la 013).
- **Fuera del límite** (:func:`limit_cells`): un corte (``S < z``) fuera del perímetro de actuación
  ∩ el límite legal sin su resguardo hacia dentro, o un relleno (``S > z``) fuera del perímetro de
  actuación (la franja de solo relleno, perímetro ∖ límite legal, es del límite). Las zonas de las
  demás restricciones (intocables, sin corte…) no son del límite: las verifica la 012 por recinto.
- **Volumen** ``Σ |S − z| · área de celda`` de esas celdas (el desmonte y el terraplén con todo su
  espesor, como ``design.report``) y **área**, sus celdas por el área de celda.

Python puro con numpy; no lee el proyecto ni modifica ninguna entrada.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from .preview import Notice
from .report import moved_cells

__all__ = [
    "OUTSIDE_CODE",
    "RefitCheck",
    "limit_cells",
    "outside_volume",
]

OUTSIDE_CODE = "des.refit_outside"
"""El aviso de una superficie que queda fuera del límite vigente (RF-014-26)."""


@dataclass(frozen=True, slots=True)
class RefitCheck:
    """Una superficie de diseño frente al límite vigente de su versión (RF-014-26): el nombre de su
    dato (``surface``), el código de la versión (``version``), las celdas que mueve fuera del límite
    (``cells``), su área (``area_m2``, m²), su volumen (``volume_m3``, m³) y el espesor mínimo con
    que se midió lo que mueve (``min_thickness_m``, m)."""

    surface: str
    version: str
    cells: int
    area_m2: float
    volume_m3: float
    min_thickness_m: float

    @property
    def outside(self) -> bool:
        """Si mueve alguna celda fuera del límite."""
        return self.cells > 0

    @property
    def notice(self) -> Notice | None:
        """El aviso ``des.refit_outside`` con la superficie, el volumen, el área y la versión;
        ``None`` si no deja nada fuera."""
        if not self.outside:
            return None
        return Notice(OUTSIDE_CODE, {"surface": self.surface, "volume": self.volume_m3,
                                     "area": self.area_m2, "version": self.version})


def _bit(masks: MaskSet, bit: ClassBit) -> np.ndarray:
    return (masks.classes & np.uint16(int(bit))) != 0


def limit_cells(masks: MaskSet) -> tuple[np.ndarray, np.ndarray]:
    """Las celdas de la rejilla de ``masks`` **dentro del límite** (máscaras nuevas): para cortar,
    el perímetro de actuación ∩ el límite legal sin su resguardo hacia dentro; para rellenar, el
    perímetro de actuación (con la franja de solo relleno y el resguardo). Las demás restricciones
    no cuentan (véase el módulo)."""
    perimeter = _bit(masks, ClassBit.PERIMETER)
    cut = perimeter & _bit(masks, ClassBit.LEGAL) & ~_bit(masks, ClassBit.INNER_BAND)
    return cut, perimeter


def _grid(values: np.ndarray, name: str, masks: MaskSet) -> np.ndarray:
    found = np.asarray(values, dtype=np.float64)
    if found.shape != masks.grid.shape:
        raise ValueError(f"{name} es una rejilla de la forma {masks.grid.shape} (la de las "
                         f"máscaras), no de forma {found.shape}")
    return found


def outside_volume(surface: np.ndarray, start: np.ndarray, masks: MaskSet,
                   min_thickness_m: float, *, name: str, version: str = "") -> RefitCheck:
    """**A13**, la comprobación (RF-014-26): lo que la superficie ``surface`` (float64, de la forma
    de la rejilla de ``masks``) mueve frente a su partida ``start`` —más que ``min_thickness_m`` (m),
    con dato en las dos— **fuera del límite** de ``masks`` (:func:`limit_cells`: un corte fuera del
    límite para cortar o un relleno fuera del perímetro), con su volumen y su área. ``name`` es el
    nombre del dato de la superficie y ``version`` el código de su versión (sin él, la de
    ``masks``). Ninguna entrada se modifica.

    ``ValueError`` (error del programa) si una rejilla no es de la forma de la de ``masks`` o el
    espesor no es un número finito ≥ 0."""
    design = _grid(surface, "la superficie", masks)
    terrain = _grid(start, "la superficie de partida", masks)
    moved = moved_cells(terrain, design, min_thickness_m)
    cut_inside, fill_inside = limit_cells(masks)
    with np.errstate(invalid="ignore"):
        outside = moved & (((design < terrain) & ~cut_inside) | ((design > terrain) & ~fill_inside))
    cells = int(np.count_nonzero(outside))
    cell_area = masks.grid.cell_area
    volume = float(np.abs(design[outside] - terrain[outside]).sum()) * cell_area
    return RefitCheck(name, version or masks.version_uid, cells, cells * cell_area, volume,
                      float(min_thickness_m))
