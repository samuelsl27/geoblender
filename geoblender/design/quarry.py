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
- :func:`crown_ring`, :func:`hold_zones` y :func:`crown_seeds` (T07; RF-014-02; A2): la
  **coronación** ``C = dilate_square(R, k) ∧ ¬R ∧ isfinite(z)``, el anillo exterior del recinto de
  ``k`` celdas (el parámetro ``des.quarry.crown_ring_cells``) con dato de terreno; las **zonas a
  sostener** ``H``, la unión de las zonas de las restricciones intocables y sin corte de las
  máscaras (ya con su resguardo, ADR-0028); y las semillas «coronación y zonas a sostener», ``s =
  z`` en ``C ∪ H`` y en ninguna otra celda (un :class:`~.seeds.SeedSet` de la 013).
- :func:`outside_crown` (T07; RF-014-03; A3): las semillas elegidas por el usuario que caen fuera
  de ``C ∪ H``, por grupos 4-conexos (:class:`SeedGroup`: celdas, m² y el centro absoluto de sus
  celdas en float64), para avisar antes de calcular (error 10).

Las demás piezas de la cantera (fondos, techo, corredores, ancla y las dos superficies)
llegan con sus tareas. Python puro con numpy (nivel 8): no importa ``reserves`` ni ``bl``; no
escribe nada.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from ..gis.messages import format_value
from . import provenance
from .grids import _label_units, dilate_square
from .messages import DesignError
from .params import CROWN_RING, check_quarry_param
from .seeds import DomainSet, SeedSet, collect_seeds, domain_of

__all__ = [
    "AREA_PART_LABELS",
    "HOLD_TYPES",
    "AreaOutcome",
    "AreaPart",
    "SeedGroup",
    "area_outcome",
    "area_parts",
    "crown_ring",
    "crown_seeds",
    "excavation_area",
    "hold_zones",
    "outside_crown",
]

AREA_PART_LABELS = MappingProxyType({
    "outside_limit": "perímetro fuera del límite legal",
    "untouchable": "intocables y exclusiones",
    "inner_band": "resguardo hacia dentro del límite",
    "no_cut": "zonas sin corte, solo relleno o solo restauración",
    "no_terrain": "sin dato de terreno",
})
"""Las partes que separan el perímetro de actuación del recinto, en su orden, con su texto."""
HOLD_TYPES = frozenset({"untouchable", "no_cut"})
"""Los tipos de restricción (valores de ``ConstraintType``) cuyas zonas son **a sostener** (A2):
los intocables y las zonas sin corte."""
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


# --- Coronación y zonas a sostener (T07; A2, A3) -----------------------------------------------


@dataclass(frozen=True, slots=True)
class SeedGroup:
    """Un grupo 4-conexo de semillas del usuario fuera de la coronación y de las zonas a sostener
    (A3, RF-014-03): su número ``group`` (desde 1, en el orden de su primera celda recorriendo la
    rejilla fila a fila desde el norte), sus ``cells``, su ``area_m2`` y el centro ``x``, ``y`` (m,
    absolutos en float64): la media de los centros de sus celdas."""

    group: int
    cells: int
    area_m2: float
    x: float
    y: float


def _same_shape(name: str, values: np.ndarray, shape: tuple[int, ...]) -> None:
    if values.shape != shape:
        raise ValueError(f"{name} es de {values.shape} celdas, no de las {shape} de la rejilla")


def crown_ring(area: np.ndarray, start: np.ndarray, ring_cells: int) -> np.ndarray:
    """**A2** (RF-014-02): la coronación del recinto ``area`` (máscara), ``dilate_square(area, k) ∧
    ¬area ∧ isfinite(start)``, como máscara nueva: las celdas fuera del recinto a distancia de
    Chebyshev ≤ ``k`` = ``ring_cells`` de alguna suya (también alrededor de sus agujeros) con dato
    en la superficie de partida ``start``. ``k`` se comprueba como el parámetro
    ``des.quarry.crown_ring_cells`` (``check_quarry_param``: ``DesignError`` fuera de [1; 50],
    ``TypeError`` si no es entero); ``ValueError`` si ``start`` no es de la forma de ``area``."""
    width = int(check_quarry_param(CROWN_RING, ring_cells))
    inside = np.asarray(area, dtype=bool)
    values = np.asarray(start)
    _same_shape("la superficie de partida", values, inside.shape)
    with np.errstate(invalid="ignore"):
        terrain = np.isfinite(values)
    return dilate_square(inside, width) & ~inside & terrain


def hold_zones(masks: MaskSet) -> np.ndarray:
    """**A2** (RF-014-02): las zonas a sostener ``H`` de ``masks``, la unión de las zonas de las
    restricciones de :data:`HOLD_TYPES` (intocables y sin corte; su zona ya lleva el resguardo,
    ADR-0028), como máscara nueva de la rejilla de las máscaras. Solo lee."""
    found = np.zeros(masks.grid.shape, dtype=bool)
    for code, ctype in sorted(masks.ctypes.items()):
        if ctype in HOLD_TYPES and code in masks.zones:
            found |= masks.zone(code).mask(masks.grid.shape)
    return found


def crown_seeds(area: np.ndarray, start: np.ndarray, masks: MaskSet, ring_cells: int, *,
                domain: DomainSet | None = None) -> SeedSet:
    """**A2** (RF-014-02): las semillas «coronación y zonas a sostener»: la superficie de partida
    ``start`` (m, float64) en ``C ∪ H`` (:func:`crown_ring` y :func:`hold_zones`) y en ninguna otra
    celda (``+inf``: la envolvente de la 013 no toma por semilla ninguna celda no finita, suba o
    baje). Las celdas de ``C ∪ H`` sin dato no son semilla y se cuentan (``nodata_cells``). Las
    semillas fuera del dominio de trabajo ``domain`` (por defecto, el recinto ``area`` sin sectores)
    se cuentan y se conservan, como en la 013. Ninguna entrada se modifica; los rechazos, los de
    :func:`crown_ring`."""
    inside = np.asarray(area, dtype=bool)
    _same_shape("el recinto", inside, masks.grid.shape)
    chosen = crown_ring(inside, start, ring_cells) | hold_zones(masks)
    if domain is None:
        domain = domain_of(inside, np.zeros(inside.shape, dtype=np.int16), (),
                           masks.grid.cell_area)
    return collect_seeds(np.asarray(start, dtype=np.float64), chosen, domain, masks.grid)


def _finish[T](work: Generator[None, None, T]) -> T:
    """Avanza unas unidades hasta el final y devuelve su resultado."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


def outside_crown(seeds: SeedSet | np.ndarray, area: np.ndarray, start: np.ndarray,
                  masks: MaskSet, ring_cells: int) -> tuple[SeedGroup, ...]:
    """**A3** (RF-014-03, error 10): las semillas ``seeds`` elegidas por el usuario (un
    :class:`~.seeds.SeedSet` de la 013 o una rejilla de cotas: son semilla las celdas con cota
    finita) que caen fuera de la coronación y de las zonas a sostener del recinto ``area`` (``C ∪
    H``, como en :func:`crown_seeds`), por grupos 4-conexos (:class:`SeedGroup`), en el orden de su
    primera celda fila a fila; ``()`` si no hay ninguna. El centro de cada grupo es la media exacta
    de los índices de sus celdas llevada a coordenadas absolutas (float64). Solo lee; los mismos
    rechazos que :func:`crown_ring`, y ``ValueError`` si ``seeds`` no es de la rejilla."""
    values = np.asarray(seeds.grid if isinstance(seeds, SeedSet) else seeds, dtype=np.float64)
    geometry = masks.grid
    _same_shape("las semillas", values, geometry.shape)
    allowed = crown_ring(area, start, ring_cells) | hold_zones(masks)
    loose = np.isfinite(values) & ~allowed
    if not loose.any():
        return ()
    labels = _finish(_label_units(loose))
    flat = labels.grid.ravel()
    picked = np.flatnonzero(flat)
    rows, cols = np.divmod(picked, geometry.ncols)
    count = labels.count + 1
    row_sum = np.bincount(flat[picked], weights=rows, minlength=count)
    col_sum = np.bincount(flat[picked], weights=cols, minlength=count)
    found = []
    for index in range(1, count):
        cells = int(labels.sizes[index - 1])
        x = geometry.west + (col_sum[index] / cells + 0.5) * geometry.dx
        y = geometry.north - (row_sum[index] / cells + 0.5) * geometry.dy
        found.append(SeedGroup(index, cells, cells * geometry.cell_area, float(x), float(y)))
    return tuple(found)
