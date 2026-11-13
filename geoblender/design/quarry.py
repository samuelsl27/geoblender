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

- :func:`floor_map` (T08; RF-014-05, RF-014-06; A4): el **mapa de cotas de fondo** de una capa de
  polígonos con su campo de cota (:class:`FloorMap`: cada celda con el centro dentro de un
  polígono, su cota; ``NaN`` fuera), con sus rechazos: dos polígonos que se solapan, un polígono
  sin cota o con una cota fuera de las del terreno ± 1.000 m (:data:`FLOOR_LEVEL_MARGIN_M`), un
  campo que la capa no tiene o que no es numérico y una capa que no es de polígonos.
  :func:`floors_above_terrain` (:class:`FloorsAbove`) mide lo que queda por encima del terreno
  de los fondos y de los corredores (T42), que se admite (allí no hay corte) y se informa.
- :func:`with_floors` y :func:`floor_cut_steps` (T08; RF-014-05; A4): la corta ``máx(ENV↓(s, t),
  ENV↓(F, t))`` (``zdes = máx(BASE0, ZF)`` de la V7) sobre la envolvente de la 013, calculada
  como la envolvente descendente de la unión de las semillas y los fondos (el máximo de los dos
  donde coinciden): la descendente es un máximo sobre las semillas, así que es lo mismo con una
  sola envolvente.

- :func:`corridor_cells` (T09; RF-014-09, RF-014-10; A6): los **corredores** de una capa de
  líneas (eje, ancho y una cota fija o una rasante) convertidos en fondos con **extremos planos**
  (:class:`CorridorMap`, con un :class:`FloorMap`): las celdas en la banda de un tramo o en la
  unión redonda de un vértice interior sin pasar de un extremo del eje (T41: también con un tramo
  extremo más corto que medio ancho), con la cota fija o la de la rasante en la abscisa de su
  punto más próximo del eje; su longitud medida (la extensión de la huella a lo largo del eje)
  no pasa de la del eje más una celda (error 20), y :func:`corridor_too_long` da el aviso de
  RF-014-10. Con la superficie de partida, la cota de cada corredor pasa por el rango de los
  fondos de RF-014-06 (T42: la fija, o la inicial y la final de su rasante; ``des.floor_level``).

- :func:`conservation_ceiling_steps` (T10; RF-014-07; A5): el **techo de conservación** ``U =
  ENV↑(z en Z, tan(talud de conservación))`` de las zonas a conservar (:class:`ConserveZone`)
  sobre la envolvente ascendente de la 013 (:class:`ConservationCeiling`, con el aviso
  ``des.conserve_nodata`` de las celdas de la zona sin dato de terreno, que no lo siembran), y
  :func:`apply_ceiling`, sus tres reglas: en ``Z``, la superficie es ``z``; fuera, ninguna celda
  con ``z > U`` se excava y la superficie no pasa de ``máx(U, z)`` (no entierra la zona: el error
  37 fue un relleno; spec 0.2). :func:`conserve_moved` (RF-014-08) mide lo que un diseño mueve
  dentro de las zonas, con el espesor mínimo de la 012, por partes con su volumen y su centro
  (:class:`ConserveMoved`, :class:`ConservePart`): más de 0 m³ es un error del diseño, que no se
  crea (``des.conserve_moved``; lo comprueba la cantera, ``store.quarry_compute_steps``, T47).

- :func:`floor_anchor_steps` (T11; RF-014-11; A7): la **rejilla de anclas** «al fondo de cada
  muro» (:class:`FloorAnchors`): en cada celda, la cota del fondo más próximo en planta (distancia
  euclídea exacta entre centros de celda; empate, la más baja), y :func:`anchored_request`, su paso
  al escalonado de la 013 como ancla en rejilla (D-18 de la 013): las bermas de cada muro quedan en
  ``fondo + k·h``.

- :func:`join_floors` (T13; RF-014-06, RF-014-09; A4, A6): los fondos y los corredores en un solo
  :class:`FloorMap` (un corredor es un polígono de fondo), con el rechazo ``des.floor_overlap`` si un
  corredor pisa un fondo.
- :func:`side_steps` (T13; RF-014-01 a RF-014-11; A1 a A7 y A8 por lado): **un lado** de la cantera
  (:class:`SideJob` → :class:`SideOutcome`), el escalonado en corte de la 013
  (``pipeline.envelope_compute_steps`` y ``pipeline.design_compute_steps``) con las semillas
  «coronación y zonas a sostener» (o las de la 013), los fondos y los corredores, el techo de
  conservación y el ancla del lado (la del perfil, una rejilla o «al fondo de cada muro»).
- :func:`quarry_steps` (T16; RF-014-12, RF-014-13, RF-014-14; A8): **las dos superficies** en una
  sola orden (:class:`QuarryJob` → :class:`QuarryOutcome`): los dos lados con :func:`side_steps`,
  primero el que dice el orden del diseño; la regla de orden y ``≤ z`` (:func:`order_surfaces`,
  :class:`OrderedSurfaces`: «final primero» sube la explotación a la final, «explotación primero»
  baja la final a la explotación) y el invariante ``final ≤ explotación ≤ terreno`` a 1 mm
  (:func:`check_order`; si fallara, un error del programa y no se crea nada).
- :func:`classify_steps` (T17; RF-014-15, RF-014-16; A8): **la clasificación** de las dos
  superficies en el dominio de trabajo (:class:`Classification`) con ``Δ = explotación − final``
  y el espesor mínimo ``e`` de la 012: sin diferencia (``Δ ≤ e``), relleno (``Δ > e`` en una zona
  de restauración por relleno, la capa de D-11) o desdoblado (``Δ > e`` fuera de ellas), con sus
  volúmenes (``Σ Δ · área de celda``, la fórmula celda a celda de la cubicación de la 011), la
  excavación de la explotación, sus áreas y las cotas mínima y máxima de cada superficie, en total
  y por sector (:class:`ClassTotals`); :func:`classification_figures`, sus cifras CALCULADO.
  :func:`quarry_steps` la da con las dos superficies.
- :func:`unsplit_zones_steps` (T18; RF-014-17; A9): **el aviso** de que la explotación no llega a
  la final (error 60): el desdoblado de más del umbral sobre terreno sin explotar (la explotación
  a menos de :data:`UNEXPLOITED_M` del terreno) en zonas conexas de más del área mínima
  (:class:`UnsplitZones`, :class:`UnsplitZone`: área, volumen y centro de cada una).
- :func:`to_final_steps` (T18; RF-014-18; A9): **«explotación hasta la final»** en unas celdas
  (:class:`ToFinal`): la explotación baja con bancos de su perfil anclados a sus cotas hasta la
  cota de su ancla inmediatamente por encima de la final, ``T = a + h·⌈(final − a)/h⌉``, sin
  quedar por debajo de la final y con transición al resto a la cara de su perfil
  (``máx(final, mín(explotación, ENV↑(T, tan(cara)·malla)))``), y el volumen que pasa del
  desdoblado a la explotación (:func:`to_final_figures`, ``des.to_final_m3``). :func:`quarry_steps`
  avisa siempre y aplica el modo del diseño (ninguna zona, las avisadas o las de una capa; P-2).

Python puro con numpy (nivel 8): no importa ``reserves`` ni ``bl``; no escribe nada.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.masks.zones import Runs
from ..gis.messages import format_value
from ..gis.vector import FeatureLayer
from . import provenance
from .envelopes import (
    BLOCK_CELLS,
    BLOCK_GROUP,
    CELLS_PER_UNIT,
    EVALS_PER_UNIT,
    TOLERANCE_M,
    SlopeField,
    SlopeRule,
    _exact_work,
    chamfer_units,
    constant_slope,
    envelope_steps,
    sector_slope,
)
from .grids import Labels, _label_units, _nearest_units, dilate_square
from .messages import DesignError, render
from .model import (
    AnchorMode,
    BenchSense,
    CellClass,
    CorridorFields,
    DesignRequest,
    Direction,
    EnvelopeRequest,
    LayerField,
    Metric,
    Order,
    QuarryRequest,
    SeedKind,
    SeedSource,
    SlopeMode,
    Surface,
    ToFinalMode,
)
from .params import (
    CONSERVE_SLOPE,
    CROWN_RING,
    QUARRY_PARAMS,
    UNSPLIT_MIN_AREA,
    UNSPLIT_THRESHOLD,
    check_quarry_param,
)
from .pipeline import (
    DesignJob,
    DesignOutcome,
    EnvelopeJob,
    EnvelopeOutcome,
    bench_profiles,
    design_compute_steps,
    envelope_compute_steps,
    envelope_slope,
    forward,
    imposed_from,
)
from .report import moved_cells
from .seeds import DomainSet, SectorRef, SeedSet, collect_seeds, domain_of, pace_progress
from .zones import _paint, _polygon_spans

__all__ = [
    "ANCHOR_LABEL",
    "AREA_PART_LABELS",
    "CEILING_NAME",
    "CLASS_CELLS_PER_UNIT",
    "CLASS_NAMES",
    "FLOOR_LEVEL_MARGIN_M",
    "HOLD_TYPES",
    "ORDER_NAMES",
    "ORDER_TOLERANCE_M",
    "SIDE_NAMES",
    "TO_FINAL_NAME",
    "UNEXPLOITED_M",
    "AreaOutcome",
    "AreaPart",
    "ClassTotals",
    "Classification",
    "ConservationCeiling",
    "ConserveMoved",
    "ConservePart",
    "ConserveZone",
    "CorridorMap",
    "FloorAnchors",
    "FloorMap",
    "FloorsAbove",
    "OrderedSurfaces",
    "QuarryJob",
    "QuarryOutcome",
    "SeedGroup",
    "SideJob",
    "SideOutcome",
    "ToFinal",
    "UnsplitZone",
    "UnsplitZones",
    "anchored_request",
    "apply_ceiling",
    "area_outcome",
    "area_parts",
    "check_order",
    "classification_figures",
    "classify_steps",
    "conservation_ceiling_steps",
    "conserve_moved",
    "corridor_cells",
    "corridor_too_long",
    "crown_ring",
    "crown_seeds",
    "excavation_area",
    "floor_anchor_steps",
    "floor_cut_steps",
    "floor_map",
    "floors_above_terrain",
    "hold_zones",
    "join_floors",
    "order_surfaces",
    "outside_crown",
    "quarry_steps",
    "side_steps",
    "to_final_figures",
    "to_final_steps",
    "unsplit_zones_steps",
    "with_floors",
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
    ADR-0028), como máscara nueva de la rejilla de las máscaras. Solo lee.

    La unión se hace con los tramos y se pinta una vez (spec 014, T35; RNF-014-02): con las 500
    restricciones de §2.2, una máscara por zona costaba 133 ms en una sola unidad."""
    held = [masks.zone(code) for code, ctype in sorted(masks.ctypes.items())
            if ctype in HOLD_TYPES and code in masks.zones]
    return Runs.union_all(held).mask(masks.grid.shape)


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
    rechazos que :func:`crown_ring`, y ``ValueError`` si ``seeds`` no es de la rejilla. Por
    unidades, :func:`_outside_units`."""
    return _finish(_outside_units(seeds, area, start, masks, ring_cells))


def _outside_units(seeds: SeedSet | np.ndarray, area: np.ndarray, start: np.ndarray,
                   masks: MaskSet, ring_cells: int
                   ) -> Generator[None, None, tuple[SeedGroup, ...]]:
    """Las unidades de :func:`outside_crown` (la coronación y las zonas a sostener; las del
    etiquetado, ``grids._label_units``; los grupos), para avanzarlas por pasos dentro de otro
    cálculo: la parada de «Calcular» de la cantera antes de calcular (T43, RF-014-03). Los rechazos
    salen en la primera."""
    values = np.asarray(seeds.grid if isinstance(seeds, SeedSet) else seeds, dtype=np.float64)
    geometry = masks.grid
    _same_shape("las semillas", values, geometry.shape)
    allowed = crown_ring(area, start, ring_cells) | hold_zones(masks)
    loose = np.isfinite(values) & ~allowed
    if not loose.any():
        return ()
    yield
    labels = yield from _label_units(loose)
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


# --- Fondos (T08; A4) --------------------------------------------------------------------------

FLOOR_LEVEL_MARGIN_M = 1000.0
"""Lo que la cota de un fondo puede quedar por debajo de la mínima del terreno o por encima de su
máxima (m; RF-014-06): fuera, es una cota imposible."""
_NUMERIC_TYPES = frozenset({"DOUBLE", "INTEGER"})
_KINDS_ES = MappingProxyType({"point": "puntos", "line": "líneas", "polygon": "polígonos"})
_NO_VALUE = "—"
_NO_FIELDS = "ninguno"
_GEOMETRY_FIELD = "geometría"


@dataclass(frozen=True, slots=True, eq=False)
class FloorMap:
    """El **mapa de cotas de fondo** (A4, RF-014-05) de la capa ``layer`` y su campo ``field``:
    ``grid`` (m, float64, nueva: la cota del polígono en cada celda con el centro dentro de uno,
    D-16 de la 013; ``NaN`` fuera), ``owner`` (int32: el orden del polígono en la capa, de 1 a n; 0
    fuera) y, por polígono en el orden de la capa, su número (``fids``), su cota (``levels``, m) y
    sus celdas (``cells``); ``cell_area_m2``, el área de una celda de la rejilla."""

    layer: str
    field: str
    grid: np.ndarray
    owner: np.ndarray
    fids: tuple[int, ...]
    levels: tuple[float, ...]
    cells: tuple[int, ...]
    cell_area_m2: float

    @property
    def area_m2(self) -> float:
        """El área de los fondos (m²): sus celdas por el área de celda."""
        return sum(self.cells) * self.cell_area_m2


@dataclass(frozen=True, slots=True)
class FloorsAbove:
    """Lo de los fondos que queda por encima de la superficie de partida (RF-014-05: se admite,
    allí no hay corte, y se informa): sus ``cells`` y su ``area_m2``."""

    cells: int
    area_m2: float

    @property
    def notice(self) -> str | None:
        """El aviso ``des.floor_above_terrain`` en español con el área; ``None`` si no hay nada."""
        if not self.cells:
            return None
        return render("des.floor_above_terrain", area=round(self.area_m2, 2))


def _level_column(layer: FeatureLayer, source: LayerField) -> str:
    """La columna del campo numérico ``source.field`` de la capa (por su nombre en la capa o por
    su columna); ``des.quarry_layer_field`` con los campos numéricos que tiene si no está."""
    numeric = [column for column in layer.columns if column.sql_type in _NUMERIC_TYPES]
    for column in numeric:
        if source.field in (column.field, column.column):
            return column.column
    raise DesignError("des.quarry_layer_field", obj=f"Capa «{source.layer}»", field="campo",
                      value=source.field, layer=source.layer,
                      fields=", ".join(column.field for column in numeric) or _NO_FIELDS)


def _floor_level(value: object, fid: int, source: LayerField, low: float, high: float) -> float:
    """La cota ``value`` del polígono ``fid`` como float; ``des.floor_level`` si falta, no es un
    número finito o queda fuera de ``[low, high]`` (RF-014-06: no se elige ninguna por él)."""
    number: float | None = None
    if value is not None and not isinstance(value, bool):
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            number = None
    if number is not None and math.isfinite(number) and low <= number <= high:
        return number
    if value is None:
        shown: object = _NO_VALUE
    elif number is not None and not math.isfinite(number):
        shown = str(number)
    else:
        shown = value
    raise DesignError("des.floor_level", obj=f"Polígono {fid} de la capa «{source.layer}»",
                      field=source.field, value=shown, layer=source.layer, polygon=fid, low=low,
                      high=high)


def _level_range(values: np.ndarray) -> tuple[float, float]:
    """Las cotas que admite un fondo o un corredor (RF-014-06): ``[mín(z) −
    FLOOR_LEVEL_MARGIN_M, máx(z) + FLOOR_LEVEL_MARGIN_M]`` m con las celdas con dato de la
    superficie de partida ``values``; ``ValueError`` (error del programa) si no tiene ninguna."""
    with np.errstate(invalid="ignore"):
        finite = np.isfinite(values)
    if not finite.any():
        raise ValueError("la superficie de partida no tiene ninguna celda con dato")
    return (float(values[finite].min()) - FLOOR_LEVEL_MARGIN_M,
            float(values[finite].max()) + FLOOR_LEVEL_MARGIN_M)


def floor_map(layer: FeatureLayer, source: LayerField, start: np.ndarray,
              geometry: Grid) -> FloorMap:
    """**A4** (RF-014-05, RF-014-06): el mapa de cotas de fondo de la capa de polígonos ``layer``
    (sus entidades; ``source`` da su nombre en el proyecto y el campo de la cota, m) en la rejilla
    ``geometry``: cada celda con el centro dentro de un polígono (D-16 de la 013; las partes de una
    entidad se unen) lleva su cota (:class:`FloorMap`). ``start`` es la superficie de partida
    (float64, de la forma de la rejilla): da el rango de las cotas admitidas. Solo lee.

    Rechazos (``DesignError``, sin elegir ninguna cota por la persona), en el orden de la capa y,
    en cada polígono, primero su cota: una capa que no es de polígonos
    (``des.layer_not_polygons``); un campo que la capa no tiene o que no es numérico
    (``des.quarry_layer_field``); una cota que falta, no es finita o queda fuera de ``[mín(z) −
    1.000, máx(z) + 1.000]`` m (``des.floor_level``, con la capa, el polígono, el campo, el valor y
    el rango); un polígono que pisa celdas de otro anterior (``des.floor_overlap``, con los dos y
    las celdas comunes). Un fondo por encima del terreno se admite (:func:`floors_above_terrain`).
    ``ValueError`` (error del programa) si ``start`` no es de la forma de la rejilla o no tiene
    ninguna celda con dato. Cada polígono cuesta su caja, no la rejilla entera."""
    values = np.asarray(start, dtype=np.float64)
    _same_shape("la superficie de partida", values, geometry.shape)
    if layer.kind != "polygon":
        raise DesignError("des.layer_not_polygons", obj=f"Capa de polígonos «{source.layer}»",
                          field=_GEOMETRY_FIELD, value=_KINDS_ES.get(layer.kind, layer.kind),
                          layer=source.layer)
    column = _level_column(layer, source)
    low, high = _level_range(values)
    grid = np.full(geometry.shape, np.nan)
    owner = np.zeros(geometry.shape, dtype=np.int32)
    levels: list[float] = []
    cells: list[int] = []
    for index, (fid, parts) in enumerate(zip(layer.fids, layer.parts, strict=True), start=1):
        level = _floor_level(layer.values[column][index - 1], fid, source, low, high)
        top, left, block = _paint(_polygon_spans(parts, geometry), geometry.nrows,
                                  geometry.ncols)
        window = (slice(top, top + block.shape[0]), slice(left, left + block.shape[1]))
        taken = owner[window][block]
        taken = taken[taken > 0]
        if taken.size:
            first = int(taken.min())
            raise DesignError("des.floor_overlap", obj=f"Capa «{source.layer}»",
                              field=_GEOMETRY_FIELD, value=layer.fids[first - 1],
                              layer=source.layer, other=fid,
                              cells=int(np.count_nonzero(taken == first)))
        owner[window][block] = index
        grid[window][block] = level
        levels.append(level)
        cells.append(int(np.count_nonzero(block)))
    return FloorMap(source.layer, source.field, grid, owner, tuple(layer.fids), tuple(levels),
                    tuple(cells), geometry.cell_area)


def floors_above_terrain(floors: FloorMap, start: np.ndarray, *others: FloorMap) -> FloorsAbove:
    """Lo de los fondos ``floors`` —y de los mapas ``others``, como el de los corredores, que son
    fondos (RF-014-09; T42)— por encima de la superficie de partida ``start`` (las celdas con cota
    de fondo mayor que la del terreno, cada una una vez aunque esté en dos mapas; RF-014-05): se
    admite —allí no hay corte, la superficie nunca supera el terreno— y se informa con su área
    (:attr:`FloorsAbove.notice`). ``ValueError`` si ``start`` u otro mapa no es de la forma de
    ``floors``. Solo lee."""
    values = np.asarray(start, dtype=np.float64)
    _same_shape("la superficie de partida", values, floors.grid.shape)
    above = np.zeros(floors.grid.shape, dtype=bool)
    for found in (floors, *others):
        _same_shape("el mapa de fondos", found.grid, floors.grid.shape)
        with np.errstate(invalid="ignore"):
            above |= found.grid > values
    cells = int(np.count_nonzero(above))
    return FloorsAbove(cells, cells * floors.cell_area_m2)


def with_floors(seeds: SeedSet, floors: FloorMap) -> SeedSet:
    """Las semillas de la corta con fondos (A4): las de ``seeds`` y las celdas de ``floors`` con su
    cota; donde coinciden, la más alta de las dos (``máx(ENV↓(s), ENV↓(F))`` es la envolvente
    descendente de esta unión). Un :class:`~.seeds.SeedSet` nuevo con su misma geometría, su
    dominio y sus celdas sin cota, contado de nuevo; las entradas no se modifican. ``ValueError``
    si el mapa no es de la rejilla de las semillas."""
    _same_shape("el mapa de fondos", floors.grid, np.shape(seeds.grid))
    return _with_cells(seeds, floors.grid)


def _with_cells(seeds: SeedSet, levels: np.ndarray) -> SeedSet:
    """Las semillas ``seeds`` y las celdas de ``levels`` con cota finita; donde coinciden, la más
    alta. Un :class:`~.seeds.SeedSet` nuevo con la geometría, el dominio y las celdas sin cota de
    ``seeds``."""
    values = np.asarray(seeds.grid, dtype=np.float64)
    extra = np.asarray(levels, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        inside = np.isfinite(extra)
    joined = np.where(np.isfinite(values), values, -np.inf)
    joined = np.where(inside, np.fmax(joined, extra), joined)
    joined[np.isneginf(joined)] = np.inf
    found = collect_seeds(joined, None, seeds.domain, seeds.geometry)
    return replace(found, nodata_cells=seeds.nodata_cells)


def floor_cut_steps(request: EnvelopeRequest, seeds: SeedSet, floors: FloorMap,
                    slope: SlopeField, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A4** (RF-014-05): la corta ``máx(ENV↓(s, t), ENV↓(F, t))`` de las semillas ``seeds`` y los
    fondos ``floors`` con la pendiente ``slope``, sobre la envolvente de la 013
    (``envelope_steps`` de :func:`with_floors`, con la métrica, el nombre y el alcance de
    ``request``; con alcance, también los fondos son semilla), por pasos: el último ``Progress``
    lleva la ``Envelope``. El escalonado sigue sobre ella; la composición con el terreno (la
    superficie nunca lo supera) es posterior. Los rechazos, los de ``envelope_steps``;
    ``ValueError`` al llamar si ``request`` no es descendente o el mapa no es de la rejilla."""
    if Direction(request.direction) is not Direction.DOWN:
        raise ValueError("la corta con fondos es una envolvente descendente, no "
                         f"{Direction(request.direction).value!r}")
    return envelope_steps(request, with_floors(seeds, floors), slope, budget_s=budget_s)


# --- Corredores (T09; A6) ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class CorridorMap:
    """Los corredores de una capa de líneas (A6, RF-014-09) convertidos en fondos: ``floors``, un
    :class:`FloorMap` (la cota de cada celda del corredor —la fija o la de su rasante—, ``NaN``
    fuera; ``levels``, la cota fija o la inicial de cada uno; ``field``, el campo de esa cota) y,
    por corredor en el orden de la capa, su ancho (``widths_m``), la longitud de su eje
    (``axes_m``) y la longitud medida en la rejilla (``lengths_m``: el máximo menos el mínimo de
    la abscisa sin recortar de sus celdas, la extensión de su huella a lo largo del eje; 0 si no
    tiene ninguna), todas en m."""

    floors: FloorMap
    widths_m: tuple[float, ...]
    axes_m: tuple[float, ...]
    lengths_m: tuple[float, ...]

    @property
    def notices(self) -> tuple[str, ...]:
        """Los avisos ``des.corridor_too_long`` (RF-014-10) de sus corredores, en su orden."""
        found = (corridor_too_long(fid, axis, length, width) for fid, axis, length, width
                 in zip(self.floors.fids, self.axes_m, self.lengths_m, self.widths_m,
                        strict=True))
        return tuple(text for text in found if text is not None)


def corridor_too_long(corridor: int, axis_m: float, length_m: float,
                      width_m: float) -> str | None:
    """**RF-014-10**: el aviso ``des.corridor_too_long`` en español, con las dos longitudes en m,
    si el corredor ``corridor`` mide (``length_m``) más que su eje (``axis_m``) más su ancho
    (``width_m``); ``None`` si no pasa de ahí."""
    if not length_m > axis_m + width_m:
        return None
    return render("des.corridor_too_long", corridor=corridor, length=round(length_m, 2),
                  axis=round(axis_m, 2), width=round(width_m, 2))


def _number(value: object) -> float | None:
    """``value`` como float finito; ``None`` si falta, no es un número o no es finito."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _shown(value: object) -> object:
    """``value`` como se nombra en un rechazo: «—» si falta y el texto de un float no finito."""
    if value is None:
        return _NO_VALUE
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _corridor_value(layer: FeatureLayer, column: str, index: int, fid: int, layer_name: str,
                    field: str, code: str, *, positive: bool = False) -> float:
    """El valor del corredor ``fid`` (entidad ``index``) en la columna ``column`` como float
    finito (y mayor que 0 con ``positive``); si no, ``DesignError`` ``code`` con la capa, el
    corredor, el campo y el valor (no se supone ninguno)."""
    value = layer.values[column][index]
    number = _number(value)
    if number is not None and (not positive or number > 0.0):
        return number
    raise DesignError(code, obj=f"Corredor {fid} de la capa «{layer_name}»", field=field,
                      value=_shown(value), layer=layer_name, corridor=fid)


def _corridor_level(fid: int, fields: CorridorFields, start_level: float, grade_pct: float,
                    axis_m: float, low: float, high: float) -> None:
    """**RF-014-06** para un corredor, que es un polígono de fondo (RF-014-09; T42, hallazgo F-3
    de la T38): su cota —la fija, o la inicial y la final de su rasante, la del final del eje de
    ``axis_m`` m— dentro de ``[low, high]`` (las del terreno ± :data:`FLOOR_LEVEL_MARGIN_M`). Si
    no, ``des.floor_level`` como un polígono de fondo, con la capa, el corredor (su número), el
    campo —el de la cota fija o el de la inicial; para la final, «<cota inicial> + <pendiente>»—
    y el valor (la cota, en m); no se elige ninguna por él."""
    field = fields.start_level_field if fields.graded else fields.level_field
    checks = [(str(field), start_level)]
    if fields.graded:
        checks.append((f"{fields.start_level_field} + {fields.grade_field}",
                       start_level + axis_m * grade_pct / 100.0))
    for name, level in checks:
        if not low <= level <= high:
            raise DesignError("des.floor_level", obj=f"Corredor {fid} de la capa «{fields.layer}»",
                              field=name, value=level, layer=fields.layer, polygon=fid, low=low,
                              high=high)


def _axis_paths(parts: tuple[tuple[np.ndarray, ...], ...]) -> list[np.ndarray]:
    """Los caminos del eje de una entidad (cada parte, en su orden), float64 ``(k, 2)``."""
    return [np.asarray(path, dtype=np.float64).reshape(-1, 2) for part in parts for path in part]


def _corridor_window(paths: list[np.ndarray], half: float,
                     geometry: Grid) -> tuple[slice, slice]:
    """Las filas y columnas de la rejilla que pueden tener el centro a ≤ ``half`` de los
    caminos: su caja ampliada en ``half``, recortada a la rejilla."""
    points = np.concatenate(paths)
    west, south = points.min(axis=0) - half
    east, north = points.max(axis=0) + half
    col0 = min(max(math.floor((west - geometry.west) / geometry.dx), 0), geometry.ncols)
    col1 = min(max(math.ceil((east - geometry.west) / geometry.dx), col0), geometry.ncols)
    row0 = min(max(math.floor((geometry.north - north) / geometry.dy), 0), geometry.nrows)
    row1 = min(max(math.ceil((geometry.north - south) / geometry.dy), row0), geometry.nrows)
    return slice(row0, row1), slice(col0, col1)


def _segment_frame(a: np.ndarray, b: np.ndarray, length: float, geometry: Grid,
                   rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """La proyección (``along``, m desde ``a`` en el sentido de ``b``) y la distancia con signo a
    la recta (``across``, m) de los centros de las filas ``rows`` y columnas ``cols`` de
    ``geometry`` respecto del tramo ``a → b`` de longitud ``length`` (> 0)."""
    ux, uy = (b - a) / length
    px = ((geometry.west - a[0]) + (cols + 0.5) * geometry.dx)[None, :]
    py = ((geometry.north - a[1]) - (rows + 0.5) * geometry.dy)[:, None]
    return px * ux + py * uy, py * ux - px * uy


def _corridor_sigma(paths: list[np.ndarray], half: float, geometry: Grid,
                    window: tuple[slice, slice]) -> tuple[np.ndarray, np.ndarray]:
    """La abscisa ``σ`` (m, a lo largo del eje desde su principio; las partes, seguidas) de cada
    celda de ``window`` dentro del corredor y su abscisa **sin recortar**, ``NaN`` fuera (A6).

    Cada celda toma el tramo más próximo de **todo** el eje (a igual distancia, el anterior):
    ``σ`` es la abscisa de su punto más próximo; la sin recortar, la de su proyección sobre la
    recta de ese tramo (pasa del vértice en la unión redonda de fuera). Dentro: el centro en la
    banda de un tramo (a ≤ ``half`` de su recta y con la proyección sobre el tramo: su rectángulo
    de extremos planos) o, si no, a ≤ ``half`` del eje (la unión redonda de un vértice interior)
    sin pasar de un extremo del camino de su tramo más próximo (antes del plano perpendicular del
    principio de su primer tramo o después del del final del último). Así los extremos son planos
    también con un tramo extremo más corto que medio ancho (T41, F-2: la unión redonda del
    vértice vecino no deja pasar del extremo) y un gancho corto al final no abre un hueco en la
    banda del tramo anterior."""
    rows = np.arange(window[0].start, window[0].stop, dtype=np.float64)
    cols = np.arange(window[1].start, window[1].stop, dtype=np.float64)
    shape = (rows.size, cols.size)
    best = np.full(shape, np.inf)
    sigma = np.full(shape, np.nan)
    reach = np.full(shape, np.nan)
    band = np.zeros(shape, dtype=bool)
    passes = np.zeros(shape, dtype=bool)
    limit = half * half
    walked = 0.0
    for path in paths:
        lengths = np.hypot(*np.diff(path, axis=0).T)
        segments = [i for i in range(lengths.size) if lengths[i] > 0.0]
        if not segments:
            continue
        first, last = segments[0], segments[-1]
        before, _ = _segment_frame(path[first], path[first + 1], float(lengths[first]),
                                   geometry, rows, cols)
        after, _ = _segment_frame(path[last], path[last + 1], float(lengths[last]), geometry,
                                  rows, cols)
        out = (before < 0.0) | (after > float(lengths[last]))
        for i in segments:
            length = float(lengths[i])
            along, across = _segment_frame(path[i], path[i + 1], length, geometry, rows, cols)
            clamped = np.clip(along, 0.0, length)
            d2 = across * across + (along - clamped) ** 2
            band |= (along >= 0.0) & (along <= length) & (across * across <= limit)
            better = d2 < best
            best[better] = d2[better]
            sigma[better] = (walked + clamped)[better]
            reach[better] = (walked + along)[better]
            passes[better] = out[better]
            walked += length
    inside = band | ((best <= limit) & ~passes)
    sigma[~inside] = np.nan
    reach[~inside] = np.nan
    return sigma, reach


def corridor_cells(layer: FeatureLayer, fields: CorridorFields, geometry: Grid, *,
                   start: np.ndarray | None = None) -> CorridorMap:
    """**A6** (RF-014-09, RF-014-10): los corredores de la capa de líneas ``layer`` (sus
    entidades; ``fields`` da su nombre en el proyecto, el campo del ancho, m, y el de la cota fija
    o los de la rasante: cota inicial, m, y pendiente, %, positiva cuando sube en el sentido del
    eje) convertidos en fondos con **extremos planos** en la rejilla ``geometry``
    (:class:`CorridorMap`): dentro, cada celda con el centro en la banda de un tramo (a ≤
    ancho/2 de su recta y con la proyección sobre el tramo) o, en la unión redonda de un vértice
    interior, a ≤ ancho/2 del eje sin pasar de un extremo (ni antes del plano perpendicular de
    su principio ni después del de su final, aunque el tramo extremo mida menos que medio ancho:
    T41); su cota, la fija o ``cota inicial + σ · pendiente / 100`` con ``σ`` la abscisa de su
    punto más próximo del eje. Su longitud medida (máximo menos mínimo de la abscisa sin
    recortar de sus celdas: la extensión de la huella a lo largo del eje) no pasa de la del eje
    más una celda si sus tramos extremos miden al menos medio ancho, ni baja de ella en dos
    celdas o más (es la de los centros; error 20: no los 220 m de un *buffer* de 200 m de eje y
    20 m de ancho), y :attr:`CorridorMap.notices` avisa si pasara de la del eje más el ancho.
    Solo lee; cada corredor cuesta su caja, no la rejilla entera.

    Con ``start``, la superficie de partida (float64, de la forma de la rejilla; la pasan la
    cantera y su vista previa), la cota de cada corredor se comprueba como la de un polígono de
    fondo (RF-014-06; T42): la fija, o la inicial y la final de su rasante (la del final del eje),
    dentro de ``[mín(z) − 1.000, máx(z) + 1.000]`` m. Un corredor por encima del terreno se admite
    (:func:`floors_above_terrain` con su mapa).

    Rechazos (``DesignError``, sin suponer nada), en el orden de la capa y, en cada corredor,
    primero su ancho, después su cota y después su eje: una capa que no es de líneas
    (``des.corridor_not_lines``); un campo que la capa no tiene o que no es numérico
    (``des.quarry_layer_field``); un ancho que falta, no es finito o es ≤ 0
    (``des.corridor_width``); una cota, cota inicial o pendiente que falta o no es finita
    (``des.corridor_level_missing``); con ``start``, una cota fuera del rango
    (``des.floor_level``, como un polígono de fondo: la capa, el corredor, el campo —para la final
    de la rasante, «<cota inicial> + <pendiente>»—, el valor y el rango); un eje de longitud cero
    (``des.corridor_length_zero``); y, como dos fondos (RF-014-06), un corredor que pisa celdas de
    otro anterior (``des.floor_overlap``, con los dos y las celdas comunes). ``ValueError`` (error
    del programa) si ``start`` no es de la forma de la rejilla o no tiene ninguna celda con
    dato."""
    if layer.kind != "line":
        raise DesignError("des.corridor_not_lines", obj=f"Capa de líneas «{fields.layer}»",
                          field=_GEOMETRY_FIELD, value=_KINDS_ES.get(layer.kind, layer.kind),
                          layer=fields.layer)
    level_fields = tuple(name for name in ((fields.start_level_field, fields.grade_field)
                                           if fields.graded else (fields.level_field,))
                         if name is not None)
    width_column = _level_column(layer, LayerField(fields.layer, fields.width_field))
    level_columns = tuple(_level_column(layer, LayerField(fields.layer, name))
                          for name in level_fields)
    bounds = None
    if start is not None:
        values = np.asarray(start, dtype=np.float64)
        _same_shape("la superficie de partida", values, geometry.shape)
        bounds = _level_range(values)
    grid = np.full(geometry.shape, np.nan)
    owner = np.zeros(geometry.shape, dtype=np.int32)
    levels: list[float] = []
    cells: list[int] = []
    widths: list[float] = []
    axes: list[float] = []
    measured: list[float] = []
    for index, (fid, parts) in enumerate(zip(layer.fids, layer.parts, strict=True), start=1):
        width = _corridor_value(layer, width_column, index - 1, fid, fields.layer,
                                fields.width_field, "des.corridor_width", positive=True)
        values = [_corridor_value(layer, column, index - 1, fid, fields.layer, name,
                                  "des.corridor_level_missing")
                  for column, name in zip(level_columns, level_fields, strict=True)]
        start_level, grade_pct = (values[0], values[1]) if fields.graded else (values[0], 0.0)
        paths = _axis_paths(parts)
        axis = float(sum(np.hypot(*np.diff(path, axis=0).T).sum() for path in paths))
        if bounds is not None:
            _corridor_level(fid, fields, start_level, grade_pct, axis, *bounds)
        if not axis > 0.0:
            raise DesignError("des.corridor_length_zero",
                              obj=f"Corredor {fid} de la capa «{fields.layer}»",
                              field=_GEOMETRY_FIELD, value=round(axis, 2), layer=fields.layer,
                              corridor=fid)
        window = _corridor_window(paths, width / 2.0, geometry)
        sigma, reach = _corridor_sigma(paths, width / 2.0, geometry, window)
        inside = np.isfinite(sigma)
        taken = owner[window][inside]
        taken = taken[taken > 0]
        if taken.size:
            first = int(taken.min())
            raise DesignError("des.floor_overlap", obj=f"Capa «{fields.layer}»",
                              field=_GEOMETRY_FIELD, value=layer.fids[first - 1],
                              layer=fields.layer, other=fid,
                              cells=int(np.count_nonzero(taken == first)))
        owner[window][inside] = index
        grid[window][inside] = start_level + sigma[inside] * grade_pct / 100.0
        levels.append(start_level)
        cells.append(int(np.count_nonzero(inside)))
        widths.append(width)
        axes.append(axis)
        found = reach[inside]
        measured.append(float(found.max() - found.min()) if found.size else 0.0)
    floors = FloorMap(fields.layer, level_fields[0], grid, owner, tuple(layer.fids),
                      tuple(levels), tuple(cells), geometry.cell_area)
    return CorridorMap(floors, tuple(widths), tuple(axes), tuple(measured))


# --- Techo de conservación (T10; A5) -----------------------------------------------------------

CEILING_NAME = "Techo de conservación"
"""El nombre del techo en los mensajes de la envolvente de la 013 (RF-013-15)."""


@dataclass(frozen=True, slots=True, eq=False)
class ConserveZone:
    """Una zona **a conservar** (RF-014-07): su ``name`` (el de la restricción de la 012 o el del
    polígono de la capa, como lo ve la persona) y su ``mask`` (booleana, de la rejilla)."""

    name: str
    mask: np.ndarray


@dataclass(frozen=True, slots=True, eq=False)
class ConservationCeiling:
    """El **techo de conservación** (A5, RF-014-07): ``grid``, ``U`` (m, float64, nueva; ``+inf``
    donde no hay techo porque ninguna celda lo siembra), ``zone`` (la unión de las zonas, booleana y
    nueva) y, por zona en su orden, su nombre (``names``) y sus celdas sin dato de terreno
    (``nodata_cells``: no siembran); el talud de conservación ``slope_deg`` (°) y
    ``cell_area_m2``, el área de una celda."""

    grid: np.ndarray
    zone: np.ndarray
    names: tuple[str, ...]
    nodata_cells: tuple[int, ...]
    slope_deg: float
    cell_area_m2: float

    @property
    def notices(self) -> tuple[str, ...]:
        """Los avisos ``des.conserve_nodata`` en español (zona y área en m²) de las zonas con
        celdas sin dato de terreno, en su orden."""
        return tuple(render("des.conserve_nodata", zone=name,
                            area=round(cells * self.cell_area_m2, 2))
                     for name, cells in zip(self.names, self.nodata_cells, strict=True) if cells)


def _zone_masks(zones: Sequence[ConserveZone], shape: tuple[int, ...]) -> list[np.ndarray]:
    """Las máscaras de ``zones`` (booleanas); ``ValueError`` si una no es de la forma ``shape``."""
    found = []
    for zone in zones:
        mask = np.asarray(zone.mask, dtype=bool)
        _same_shape(f"la zona a conservar «{zone.name}»", mask, shape)
        found.append(mask)
    return found


def _rising_work(seed: np.ndarray, geometry: Grid, slope: SlopeField, metric: Metric,
                 name: str) -> Generator[None, None, np.ndarray]:
    """Las unidades de la envolvente **ascendente** de la 013 de ``seed`` con ``slope`` y
    ``metric`` (la euclídea exacta, con una pendiente constante), con ``name`` en sus mensajes:
    su rejilla, o ``+inf`` en toda la rejilla sin ninguna semilla."""
    if not np.isfinite(seed).any():
        yield None
        return np.full(seed.shape, np.inf)
    if metric is Metric.EXACT:
        found = yield from _exact_work(seed, geometry, slope, Direction.UP, name,
                                       CELLS_PER_UNIT, EVALS_PER_UNIT, BLOCK_CELLS, BLOCK_GROUP)
    else:
        found = yield from chamfer_units(seed, geometry, slope, Direction.UP, name=name)
    return found.grid


def _ceiling_work(seed: np.ndarray, geometry: Grid, slope: SlopeField, metric: Metric,
                  zone: np.ndarray, names: tuple[str, ...], nodata: tuple[int, ...],
                  slope_deg: float) -> Generator[None, None, ConservationCeiling]:
    """Las unidades del techo: la envolvente ascendente de la 013 de ``seed`` con ``slope`` y
    ``metric``; sin ninguna semilla, ``+inf`` en toda la rejilla (no hay techo)."""
    grid = yield from _rising_work(seed, geometry, slope, metric, CEILING_NAME)
    return ConservationCeiling(grid, zone, names, nodata, slope_deg, geometry.cell_area)


def conservation_ceiling_steps(zones: Sequence[ConserveZone], start: np.ndarray, geometry: Grid,
                               slope_deg: float | None, *, metric: Metric | str = Metric.CHAMFER5,
                               budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A5** (RF-014-07): el techo de conservación ``U = ENV↑(z en Z, tan(talud))`` de las zonas
    a conservar ``zones`` (``Z``, su unión: la ascendente es un mínimo sobre las semillas, así que
    es el menor de los techos de cada zona) sobre la superficie de partida ``start`` (m, float64,
    de la forma de ``geometry``), con el talud de conservación ``slope_deg`` (°, el parámetro
    ``des.conserve.slope_deg``, sin factor de malla) y la ``metric`` de la 013 (*chamfer* 5×5 o
    euclídea exacta), por pasos: el último ``Progress`` (fase ``ceiling``) lleva el
    :class:`ConservationCeiling`. Las celdas de una zona sin dato de terreno no lo siembran y se
    cuentan para su aviso (``des.conserve_nodata``); sin ninguna semilla no hay techo (``+inf``).
    Las reglas que impone son las de :func:`apply_ceiling`. Ninguna entrada se modifica.

    Rechazos al llamar: el talud, como el parámetro (``check_quarry_param``:
    ``des.quarry_param_missing`` sin valor, D-9; ``des.quarry_param_range`` fuera de (0; 90));
    ``ValueError`` (error del programa) si una zona o ``start`` no son de la forma de la rejilla.
    Al avanzar, los de la envolvente de la 013 (RF-013-15)."""
    degrees = float(check_quarry_param(CONSERVE_SLOPE, slope_deg))
    values = np.asarray(start, dtype=np.float64)
    _same_shape("la superficie de partida", values, geometry.shape)
    way = Metric(metric)
    masks = _zone_masks(zones, geometry.shape)
    with np.errstate(invalid="ignore"):
        terrain = np.isfinite(values)
    union = np.zeros(geometry.shape, dtype=bool)
    for mask in masks:
        union |= mask
    nodata = tuple(int(np.count_nonzero(mask & ~terrain)) for mask in masks)
    seed = np.where(union & terrain, values, np.inf)
    work = _ceiling_work(seed, geometry, constant_slope(degrees), way, union,
                         tuple(zone.name for zone in zones), nodata, degrees)
    return pace_progress(work, budget_s, phase="ceiling",
                         running="Calculando el techo de conservación…",
                         finished="Techo de conservación calculado")


def apply_ceiling(surface: np.ndarray, start: np.ndarray,
                  ceiling: ConservationCeiling) -> np.ndarray:
    """**A5** (RF-014-07, spec 0.2): las tres reglas del techo ``ceiling`` sobre la superficie de
    diseño ``surface`` (m, float64) frente a la de partida ``start``, como rejilla nueva: en la zona
    a conservar, la superficie es ``z`` (0 m³); fuera, ninguna celda con ``z > U`` se excava (queda
    ``z``, ``KEEP`` como la V9) y la superficie no pasa de ``máx(U, z)`` (no entierra la zona: el
    error 37 fue un relleno). Una celda sin dato en ``surface`` sigue sin dato. ``ValueError`` si
    las rejillas no son de la misma forma. Ninguna entrada se modifica."""
    design = np.array(surface, dtype=np.float64)
    values = np.asarray(start, dtype=np.float64)
    _same_shape("la superficie de diseño", design, ceiling.grid.shape)
    _same_shape("la superficie de partida", values, ceiling.grid.shape)
    held = _held(values, ceiling)
    with np.errstate(invalid="ignore"):
        np.minimum(design, np.fmax(ceiling.grid, values), out=design)
    design[held] = values[held]
    return design


def _held(start: np.ndarray, ceiling: ConservationCeiling) -> np.ndarray:
    """Las celdas que el techo deja como el terreno ``start``: la zona a conservar y, fuera, las
    que tienen ``z > U`` (``KEEP``). Una máscara nueva."""
    with np.errstate(invalid="ignore"):
        keep = ~ceiling.zone & np.isfinite(start) & (start > ceiling.grid)
    return keep | ceiling.zone


@dataclass(frozen=True, slots=True)
class ConservePart:
    """Una parte de lo que el diseño mueve dentro de una zona a conservar (RF-014-08): la zona
    (``zone``, su nombre), su número ``part`` (desde 1 en la zona, 4-conexa, en el orden de su
    primera celda fila a fila desde el norte), sus ``cells``, su ``volume_m3`` (desmonte más
    terraplén, con todo su espesor) y el centro ``x``, ``y`` (m, absolutos en float64): la media
    de los centros de sus celdas."""

    zone: str
    part: int
    cells: int
    volume_m3: float
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class ConserveMoved:
    """Lo que el diseño mueve dentro de las zonas a conservar (RF-014-08), por partes
    (:class:`ConservePart`, por zona en su orden)."""

    parts: tuple[ConservePart, ...]

    @property
    def volume_m3(self) -> float:
        """El volumen movido en todas las zonas (m³)."""
        return math.fsum(part.volume_m3 for part in self.parts)

    @property
    def moved(self) -> bool:
        """Si el diseño mueve más de 0 m³ en alguna zona: un error del diseño."""
        return bool(self.parts)

    @property
    def notices(self) -> tuple[str, ...]:
        """El error del diseño en español: ``des.conserve_moved`` (volumen y partes) y una
        ``des.conserve_part`` por parte (zona, volumen y centro, redondeados al cm); ``()`` si no
        mueve nada."""
        if not self.parts:
            return ()
        lines = [render("des.conserve_moved", volume=round(self.volume_m3, 2),
                        parts=len(self.parts))]
        lines.extend(render("des.conserve_part", zone=part.zone,
                            volume=round(part.volume_m3, 2), x=round(part.x, 2),
                            y=round(part.y, 2)) for part in self.parts)
        return tuple(lines)


def conserve_moved(design: np.ndarray, start: np.ndarray, zones: Sequence[ConserveZone],
                   geometry: Grid, min_thickness_m: float) -> ConserveMoved:
    """**RF-014-08**: lo que la superficie ``design`` mueve frente a ``start`` dentro de cada zona
    a conservar de ``zones``: las celdas con dato en las dos y una diferencia mayor que el espesor
    mínimo de la 012 ``min_thickness_m`` (m; ``design.report.moved_cells``, la máscara del
    informe), por partes 4-conexas de cada zona, con su volumen (todo su espesor por el área de
    celda) y su centro absoluto (:class:`ConserveMoved`). Más de 0 m³ es un error del diseño que
    no se crea (la cantera lo lanza con sus partes, ``store.quarry_compute_steps``, T47). Solo
    lee; ``ValueError`` si las rejillas no son de la forma de ``geometry``."""
    base = np.asarray(start, dtype=np.float64)
    other = np.asarray(design, dtype=np.float64)
    _same_shape("la superficie de partida", base, geometry.shape)
    _same_shape("la superficie de diseño", other, geometry.shape)
    moved = moved_cells(base, other, min_thickness_m)
    found: list[ConservePart] = []
    for zone, mask in zip(zones, _zone_masks(zones, geometry.shape), strict=True):
        inside = moved & mask
        if not inside.any():
            continue
        labels = _finish(_label_units(inside))
        flat = labels.grid.ravel()
        picked = np.flatnonzero(flat)
        tags = flat[picked]
        rows, cols = np.divmod(picked, geometry.ncols)
        count = labels.count + 1
        row_sum = np.bincount(tags, weights=rows, minlength=count)
        col_sum = np.bincount(tags, weights=cols, minlength=count)
        depth = np.abs(base.ravel()[picked] - other.ravel()[picked])
        for index in range(1, count):
            cells = int(labels.sizes[index - 1])
            volume = math.fsum(depth[tags == index]) * geometry.cell_area
            x = geometry.west + (col_sum[index] / cells + 0.5) * geometry.dx
            y = geometry.north - (row_sum[index] / cells + 0.5) * geometry.dy
            found.append(ConservePart(zone.name, index, cells, float(volume), float(x),
                                      float(y)))
    return ConserveMoved(tuple(found))


# --- El ancla al fondo de cada muro (T11; A7) -----------------------------------------------------

ANCHOR_LABEL = "al fondo de cada muro, capa {layer}"
"""El nombre de la rejilla de anclas «al fondo de cada muro» en los mensajes del escalonado de la
013 (``des.anchor_nodata``), con la capa de los fondos."""


@dataclass(frozen=True, slots=True, eq=False)
class FloorAnchors:
    """La **rejilla de anclas** «al fondo de cada muro» (A7, RF-014-11) de la capa de fondos
    ``layer``: ``grid`` (m, float64, nueva), la cota del fondo más próximo a cada celda en planta
    (a igual distancia, la más baja; ``NaN`` en toda la rejilla si no hay ninguna celda de fondo), y
    ``d2_m2`` (float64), el cuadrado de esa distancia entre centros de celda en m² (``+inf`` sin
    fondos)."""

    layer: str
    grid: np.ndarray
    d2_m2: np.ndarray

    @property
    def label(self) -> str:
        """El nombre de la rejilla en los mensajes (:data:`ANCHOR_LABEL`)."""
        return ANCHOR_LABEL.format(layer=self.layer)


def _anchor_work(floors: FloorMap, cell: float) -> Generator[None, None, FloorAnchors]:
    """Las unidades del ancla: el más próximo de la 014 (``grids._nearest_units``) sobre las celdas
    de fondo con su cota."""
    found = np.isfinite(floors.grid)
    nearest = yield from _nearest_units(found, floors.grid, cell)
    return FloorAnchors(floors.layer, nearest.value, nearest.d2)


def floor_anchor_steps(floors: FloorMap, geometry: Grid, *,
                       budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A7** (RF-014-11): la rejilla de anclas «al fondo de cada muro» del mapa de fondos
    ``floors`` (:func:`floor_map`, o el de unos corredores) en la rejilla ``geometry``: cada celda
    lleva la cota del fondo más próximo en planta —distancia euclídea exacta entre centros de celda
    (``design.grids.nearest_value_steps``); a igual distancia, la cota más baja—, por pasos: el
    último ``Progress`` (fase ``anchors``) lleva las :class:`FloorAnchors`. Con ellas como ancla en
    rejilla del escalonado de la 013 (D-18 de la 013; :func:`anchored_request` y ``DesignJob.anchors
    = grid``), las bermas de cada muro quedan en ``fondo + k·h``. Sin ninguna celda de fondo, la
    rejilla no tiene cota y el escalonado la rechaza (``des.anchor_nodata``).

    ``ValueError`` (error del programa) al llamar si el mapa no es de la forma de ``geometry`` o la
    rejilla no tiene celdas cuadradas (ADR-0014). Ninguna entrada se modifica; cerrar el generador a
    mitad no deja nada."""
    _same_shape("el mapa de fondos", floors.grid, geometry.shape)
    if geometry.dx != geometry.dy:
        raise ValueError("el ancla al fondo de cada muro se calcula en una rejilla de celdas "
                         f"cuadradas (ADR-0014), no de {geometry.dx} × {geometry.dy} m")
    return pace_progress(_anchor_work(floors, float(geometry.dx)), budget_s, phase="anchors",
                         running="Buscando el fondo de cada muro…",
                         finished="Rejilla de anclas al fondo de cada muro calculada")


def anchored_request(request: DesignRequest, anchors: FloorAnchors) -> DesignRequest:
    """El paso de :class:`FloorAnchors` al escalonado de la 013 como ancla en rejilla (D-18 de la
    013): la petición ``request`` con la rejilla de anclas nombrada por :attr:`FloorAnchors.label`
    (la que citan sus mensajes); el ``DesignJob`` lleva ``anchors = anchors.grid``. Una petición
    nueva; ``request`` no cambia."""
    return replace(request, anchor_grid=anchors.label)


# --- Un lado de la cantera (T13; A1 a A7, A8 por lado) ---------------------------------------------

SIDE_NAMES = MappingProxyType({Surface.FINAL: "superficie final",
                               Surface.EXPLOITATION: "superficie de explotación"})
"""El nombre de cada superficie en los mensajes: la envolvente y el escalonado de un lado se
llaman «<cantera> (<superficie>)»."""


def join_floors(floors: FloorMap | None, corridors: CorridorMap | None) -> FloorMap | None:
    """Los fondos ``floors`` (:func:`floor_map`) y los corredores ``corridors``
    (:func:`corridor_cells`) en un solo :class:`FloorMap` (A4, A6: un corredor es un polígono de
    fondo, RF-014-09): la cota de cada celda de los dos, los polígonos de los fondos y después los
    corredores (su ``owner``, desplazado por el número de fondos), la capa «<fondos> y
    <corredores>» y el campo de los fondos. Sin corredores, ``floors`` tal cual; sin fondos, el
    mapa de los corredores; sin ninguno, ``None``. Si un corredor pisa un fondo es
    ``des.floor_overlap`` (RF-014-06: no se elige cota), con el fondo, el corredor y sus celdas
    comunes del primer par en el orden de las capas. ``ValueError`` si los mapas no son de la misma
    rejilla. Ninguna entrada se modifica."""
    if corridors is None:
        return floors
    lane = corridors.floors
    if floors is None:
        return lane
    _same_shape("el mapa de los corredores", lane.grid, floors.grid.shape)
    common = (floors.owner > 0) & (lane.owner > 0)
    if common.any():
        first = int(floors.owner[common].min())
        pair = common & (floors.owner == first)
        other = int(lane.owner[pair].min())
        raise DesignError("des.floor_overlap",
                          obj=f"Capas «{floors.layer}» y «{lane.layer}»",
                          field=_GEOMETRY_FIELD, value=floors.fids[first - 1], layer=floors.layer,
                          other=f"{lane.fids[other - 1]} (corredor de la capa «{lane.layer}»)",
                          cells=int(np.count_nonzero(pair & (lane.owner == other))))
    on_lane = lane.owner > 0
    owner = np.where(on_lane, lane.owner + len(floors.fids), floors.owner).astype(np.int32)
    grid = np.where(on_lane, lane.grid, floors.grid)
    return FloorMap(f"{floors.layer} y {lane.layer}", floors.field, grid, owner,
                    floors.fids + lane.fids, floors.levels + lane.levels,
                    floors.cells + lane.cells, floors.cell_area_m2)


@dataclass(frozen=True, slots=True, eq=False)
class _HeldMasks:
    """Las máscaras de la 012 sin corte admitido en las celdas que retiene el techo (A5): así la
    composición de la 013 las deja como el terreno y su informe y sus bermas son los de la
    superficie con el techo."""

    masks: object
    held: np.ndarray

    def cut_allowed(self) -> np.ndarray:
        return self.masks.cut_allowed() & ~self.held  # type: ignore[attr-defined]

    def fill_allowed(self) -> np.ndarray:
        return self.masks.fill_allowed()  # type: ignore[attr-defined]

    def fill_strip(self) -> np.ndarray:
        return self.masks.fill_strip()  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True, eq=False)
class SideJob:
    """Lo que necesita calcular un lado de la cantera, ya leído (como ``DesignJob`` de la 013): la
    petición (``request``) y la superficie (``surface``: su :class:`~.model.QuarrySide`), la de
    partida ``start`` (m, float64), las ``masks`` de la versión (un ``MaskSet``), el ``domain`` de
    trabajo (el recinto de :func:`excavation_area` con las etiquetas de sector, ``domain_of``), los
    parámetros (``values``: clave → valor, los perfiles y los taludes impuestos), el anillo de
    coronación (``ring_cells``, el valor de ``des.quarry.crown_ring_cells``), el espesor mínimo, la
    tolerancia de cara y el umbral de aviso de la 013; las semillas de la 013 (``seeds``) si el lado
    no siembra la coronación, y solo entonces; los fondos y corredores (``floors``,
    :func:`join_floors`), el techo (``ceiling``, :func:`conservation_ceiling_steps`), la rejilla de
    anclas leída (``anchors``) con el ancla en rejilla, y solo con ella, y los sectores con la
    búsqueda pendiente (``pending``)."""

    request: QuarryRequest
    surface: Surface | str
    start: np.ndarray
    masks: MaskSet
    domain: DomainSet
    values: Mapping[str, object]
    ring_cells: int
    min_thickness_m: float
    face_tolerance_deg: float
    warning_ratio: float
    seeds: SeedSet | None = None
    floors: FloorMap | None = None
    ceiling: ConservationCeiling | None = None
    anchors: np.ndarray | None = None
    pending: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "surface", Surface(self.surface))


@dataclass(frozen=True, slots=True, eq=False)
class SideOutcome:
    """Un lado de la cantera calculado: su ``surface``; las semillas base (``seeds``: las de la
    coronación y las zonas a sostener, o las de la 013) y las de su envolvente (``envelope_seeds``:
    con los fondos, los corredores y lo que retiene el techo); lo que retiene el techo (``held``: la
    zona a conservar y las celdas con ``z > U``; ``None`` sin techo); la rejilla de anclas «al fondo
    de cada muro» (``anchors``; ``None`` con otra ancla); la envolvente (``envelope``) y el
    escalonado (``design``) de la 013."""

    surface: Surface
    seeds: SeedSet
    envelope_seeds: SeedSet
    held: np.ndarray | None
    anchors: FloorAnchors | None
    envelope: EnvelopeOutcome
    design: DesignOutcome

    @property
    def grid(self) -> np.ndarray:
        """La superficie del lado (m, float64): la de diseño del escalonado."""
        return self.design.design


def side_steps(job: SideJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**Un lado** de la cantera (A8 por lado, con A1 a A7): el escalonado en corte de la 013 de la
    superficie ``job.surface`` por pasos de ``budget_s`` como mucho (los de
    ``envelope_compute_steps`` y ``design_compute_steps``, §5.3.2); el último ``Progress`` (fase
    ``side``) lleva el :class:`SideOutcome`. En orden:

    1. las semillas: «coronación y zonas a sostener» del recinto (:func:`crown_seeds`, RF-014-02) o
       las de la 013 que se dan;
    2. con ellas, los fondos y corredores (:func:`with_floors`: ``máx(ENV↓(s), ENV↓(F))``,
       RF-014-05, RF-014-09) y, con techo, el terreno en las celdas que retiene (la zona a conservar
       y ``z > U``): de ellas bajan las paredes como de las zonas a sostener;
    3. la envolvente descendente de la 013 con el talud general del perfil del lado por sectores
       (``envelope_slope``) y su métrica, recortada al recinto (RF-014-01);
    4. el ancla: la del perfil, la rejilla leída o «al fondo de cada muro» (:func:`floor_anchor_steps`
       de ``floors``, RF-014-11; sin fondos, sin cota: ``des.anchor_nodata``);
    5. el escalonado en corte de la 013 con los perfiles del lado, compuesto con las máscaras sin
       corte en las celdas que retiene el techo: la superficie cumple las tres reglas de
       :func:`apply_ceiling` (RF-014-07; en corte, nunca pasa de ``z``).

    ``ValueError`` (error del programa) al llamar si las semillas no casan con el lado (dadas con
    «coronación» o sin ellas con las de la 013), si hay rejilla de anclas sin el ancla en rejilla o
    al revés, o si la partida o el dominio no son de la rejilla de las máscaras. Al avanzar, los
    rechazos de la 013 (perfiles, sectores, anclas). Ninguna entrada se modifica y no se escribe
    nada; cerrar el generador a mitad no deja nada."""
    side = job.request.side(job.surface)
    if side.crown_seeds != (job.seeds is None):
        raise ValueError("las semillas de la 013 se dan con un lado que no siembra la coronación, "
                         "y solo entonces (RF-014-02)")
    if (AnchorMode(side.anchor) is AnchorMode.GRID) != (job.anchors is not None):
        raise ValueError("la rejilla de anclas leída va con el ancla en rejilla y solo con ella "
                         "(D-18 de la 013)")
    shape = job.masks.grid.shape
    _same_shape("la superficie de partida", np.asarray(job.start), shape)
    _same_shape("el dominio de trabajo", job.domain.mask, shape)
    return _side_work(job, budget_s)


def _side_work(job: SideJob, budget_s: float) -> Generator[Progress, None, None]:
    side = job.request.side(job.surface)
    surface = Surface(job.surface)
    geometry = job.masks.grid
    start = np.asarray(job.start, dtype=np.float64)
    label = f"{job.request.name} ({SIDE_NAMES[surface]})"
    # Un paso por pieza de la preparación (spec 014, T35; RNF-014-02): juntas, con las 500
    # restricciones de §2.2, pasaban de 0,2 s en una sola llamada del hilo de Blender.
    preparing = Progress("side", 0, 1, f"Preparando la {SIDE_NAMES[surface]}…")
    yield preparing
    base = job.seeds
    if base is None:
        base = crown_seeds(job.domain.mask, start, job.masks, job.ring_cells, domain=job.domain)
        yield preparing
    seeds = base
    if job.floors is not None:
        seeds = with_floors(base, job.floors)
        yield preparing
    held = None
    if job.ceiling is not None:
        held = _held(start, job.ceiling)
        seeds = _with_cells(seeds, np.where(held, start, np.nan))
        yield preparing
    source = side.seeds or SeedSource(SeedKind.SURFACE, surface=job.request.start)
    envelope_request = EnvelopeRequest(label, Direction.DOWN, source,
                                       slope_mode=SlopeMode.SECTORS, metric=side.metric,
                                       base_profile=side.base_profile,
                                       sector_profiles=side.sector_profiles)
    sectors, labels = job.domain.sectors, job.domain.labels
    slope = envelope_slope(envelope_request, sectors, labels, job.values)
    envelope: EnvelopeOutcome = yield from forward(envelope_compute_steps(
        EnvelopeJob(envelope_request, seeds, slope, start, job.min_thickness_m),
        budget_s=budget_s))
    anchors: FloorAnchors | None = None
    anchor_grid, anchor_name = job.anchors, side.anchor_grid
    if AnchorMode(side.anchor) is AnchorMode.NEAREST_FLOOR:
        if job.floors is None:
            anchors = FloorAnchors(_NO_VALUE, np.full(geometry.shape, np.nan),
                                   np.full(geometry.shape, np.inf))
        else:
            anchors = yield from forward(floor_anchor_steps(job.floors, geometry,
                                                            budget_s=budget_s))
        anchor_grid, anchor_name = anchors.grid, anchors.label
    design_request = DesignRequest(label, label, BenchSense.CUT, side.base_profile,
                                   side.sector_profiles, anchor_grid=anchor_name)
    profiles = bench_profiles(job.values, [side.base_profile, *(
        profile for _sector, profile in design_request.sector_profiles)])
    masks: object = job.masks if held is None else _HeldMasks(job.masks, held)
    design: DesignOutcome = yield from forward(design_compute_steps(DesignJob(
        design_request, geometry, start, envelope.grid, masks, sectors, labels,
        imposed_from(job.values, sectors), profiles, anchor_grid, job.min_thickness_m,
        job.face_tolerance_deg, job.warning_ratio, pending=job.pending), budget_s=budget_s))
    outcome = SideOutcome(surface, base, seeds, held, anchors, envelope, design)
    yield Progress("side", 1, 1, f"{SIDE_NAMES[surface].capitalize()} de «{job.request.name}» "
                   "calculada", result=outcome)


# --- Las dos superficies y el orden (T16; A8) -----------------------------------------------------

ORDER_TOLERANCE_M = 0.001
"""La tolerancia del invariante ``final ≤ explotación ≤ terreno`` (m; RF-014-14: 1 mm)."""
ORDER_NAMES = MappingProxyType({Order.FINAL_FIRST: "final primero",
                                Order.EXPLOITATION_FIRST: "explotación primero"})
"""El nombre de cada orden del diseño en los mensajes (RF-014-13)."""
_ORDER_FIELD = "final ≤ explotación ≤ terreno"


@dataclass(frozen=True, slots=True, eq=False)
class OrderedSurfaces:
    """Las dos superficies atadas por la regla de orden (A8; RF-014-13): la ``final`` y la de
    ``exploitation`` (m, float64, rejillas nuevas), el ``order`` con que se ataron y las celdas en
    que la regla cambió la segunda (``adjusted``: las que tenían la final por encima de la
    explotación; «final primero» subió allí la explotación y «explotación primero» bajó la
    final)."""

    final: np.ndarray
    exploitation: np.ndarray
    order: Order
    adjusted: int


def _at_most(grid: np.ndarray, start: np.ndarray) -> np.ndarray:
    """``grid`` sin pasar de ``start`` donde ``start`` tiene dato (``≤ z``); donde no, ``grid``
    tal cual. Una rejilla nueva."""
    return np.where(np.isfinite(start), np.minimum(grid, start), grid)


def order_surfaces(order: Order | str, final: np.ndarray, exploitation: np.ndarray,
                   start: np.ndarray) -> OrderedSurfaces:
    """**La regla de orden** (A8; RF-014-13) de las dos superficies de un diseño, ``final`` y
    ``exploitation`` (m, de la misma rejilla que la de partida ``start``): con «final primero», la
    final se queda y la explotación sube donde queda por debajo de ella (``explotación =
    máx(explotación, final)``); con «explotación primero», la explotación se queda y la final baja
    donde queda por encima (``final = mín(final, explotación)``); después, las dos ``≤ z`` donde
    el terreno tiene dato. Así ``final ≤ explotación ≤ terreno`` (RF-014-14, que comprueba
    :func:`check_order`). Rejillas nuevas (:class:`OrderedSurfaces`); ninguna entrada se
    modifica. ``ValueError`` (error del programa) si las rejillas no tienen la misma forma."""
    order = Order(order)
    base = np.asarray(start, dtype=np.float64)
    upper = np.asarray(final, dtype=np.float64)
    lower = np.asarray(exploitation, dtype=np.float64)
    _same_shape("la superficie final", upper, base.shape)
    _same_shape("la superficie de explotación", lower, base.shape)
    with np.errstate(invalid="ignore"):
        adjusted = int(np.count_nonzero(upper > lower))
    if order is Order.FINAL_FIRST:
        lower = np.maximum(lower, upper)
    else:
        upper = np.minimum(upper, lower)
    return OrderedSurfaces(_at_most(upper, base), _at_most(lower, base), order, adjusted)


def _level(value: float) -> object:
    """Una cota en un mensaje: redondeada al mm, o «—» si no tiene dato."""
    return round(value, 3) if math.isfinite(value) else _NO_VALUE


def check_order(name: str, final: np.ndarray, exploitation: np.ndarray, start: np.ndarray,
                geometry: Grid) -> None:
    """**El invariante** de las dos superficies (A8; RF-014-14): ``final ≤ explotación ≤
    terreno`` en cada celda con :data:`ORDER_TOLERANCE_M` (1 mm), comprobado antes de ofrecer
    «Crear». Una celda sin dato en las tres cumple; una superficie sin dato donde el terreno lo
    tiene (o al revés) no. Si alguna celda no cumple es un **error del programa**
    (:class:`~.messages.DesignError` ``des.quarry_order_broken``: no se crea nada) con la primera
    fila a fila desde el norte, sus coordenadas absolutas (m, centro de la celda) y las tres cotas,
    y el número de celdas que fallan como valor. Solo lee; ``ValueError`` si las rejillas no son
    de la forma de ``geometry``."""
    base = np.asarray(start, dtype=np.float64)
    upper = np.asarray(final, dtype=np.float64)
    lower = np.asarray(exploitation, dtype=np.float64)
    for label, grid in (("la superficie de partida", base), ("la superficie final", upper),
                        ("la superficie de explotación", lower)):
        _same_shape(label, grid, geometry.shape)
    with np.errstate(invalid="ignore"):
        holds = ((upper <= lower + ORDER_TOLERANCE_M) & (lower <= base + ORDER_TOLERANCE_M))
    empty = np.isnan(upper) & np.isnan(lower) & np.isnan(base)
    broken = ~(holds | empty)
    if not broken.any():
        return
    first = int(np.flatnonzero(broken)[0])
    row, col = divmod(first, geometry.ncols)
    x = geometry.west + (col + 0.5) * geometry.dx
    y = geometry.north - (row + 0.5) * geometry.dy
    raise DesignError("des.quarry_order_broken", obj=f"Cantera «{name}»", field=_ORDER_FIELD,
                      value=int(np.count_nonzero(broken)), x=round(x, 2), y=round(y, 2),
                      final=_level(float(upper[row, col])),
                      exploitation=_level(float(lower[row, col])),
                      terrain=_level(float(base[row, col])))


# --- La clasificación y las cifras (T17; A8) ------------------------------------------------------

CLASS_NAMES = MappingProxyType({CellClass.NONE: "sin diferencia",
                                CellClass.UNSPLIT: "desdoblado",
                                CellClass.FILL: "relleno"})
"""El nombre de cada clase de la clasificación en los mensajes y en la leyenda (RF-014-15)."""
CLASS_CELLS_PER_UNIT = 200_000
"""Las celdas de una unidad de trabajo de la clasificación (una banda de filas)."""
_HECTARE_M2 = 10_000.0


@dataclass(frozen=True, slots=True)
class ClassTotals:
    """Las cifras de las dos superficies en un reparto (RF-014-15, RF-014-16): el total
    (``sector`` ``None``) o un sector (:class:`~.seeds.SectorRef`). ``cells``, las celdas del
    dominio de trabajo del reparto, y ``nodata_cells``, las de ellas sin dato en alguna de las dos
    superficies (sin clase); la **excavación de la explotación** (``exp_cut_m3``, m³, y
    ``exp_cut_cells``: las celdas con ``terreno − explotación > e``, con todo su espesor); el
    **desdoblado** y el **relleno** (``unsplit_m3`` y ``fill_m3``: ``Σ Δ · área de celda`` de sus
    celdas, y sus celdas); las celdas **sin diferencia** (``none_cells``); las cotas mínima y máxima
    de cada superficie en las celdas del reparto con dato (m; ``None`` sin ninguna) y el área de
    una celda (m²)."""

    sector: SectorRef | None
    cells: int
    nodata_cells: int
    exp_cut_m3: float
    exp_cut_cells: int
    unsplit_m3: float
    unsplit_cells: int
    fill_m3: float
    fill_cells: int
    none_cells: int
    final_min_m: float | None
    final_max_m: float | None
    exploitation_min_m: float | None
    exploitation_max_m: float | None
    cell_area_m2: float

    def cells_of(self, kind: CellClass | str) -> int:
        """Las celdas de la clase ``kind``."""
        kind = CellClass(kind)
        if kind is CellClass.UNSPLIT:
            return self.unsplit_cells
        if kind is CellClass.FILL:
            return self.fill_cells
        return self.none_cells

    def volume_m3(self, kind: CellClass | str) -> float:
        """El volumen de la clase ``kind`` (m³); sin diferencia no tiene (lo que no pasa del
        espesor mínimo no cuenta, como en la cubicación de la 011)."""
        kind = CellClass(kind)
        if kind is CellClass.UNSPLIT:
            return self.unsplit_m3
        if kind is CellClass.FILL:
            return self.fill_m3
        return 0.0

    def area_m2(self, kind: CellClass | str) -> float:
        """El área de la clase ``kind`` (m²): sus celdas por el área de celda."""
        return self.cells_of(kind) * self.cell_area_m2

    def area_ha(self, kind: CellClass | str) -> float:
        """El área de la clase ``kind`` (ha)."""
        return self.area_m2(kind) / _HECTARE_M2

    @property
    def exp_cut_area_m2(self) -> float:
        """El área de la excavación de la explotación (m²)."""
        return self.exp_cut_cells * self.cell_area_m2

    @property
    def exp_cut_area_ha(self) -> float:
        """El área de la excavación de la explotación (ha)."""
        return self.exp_cut_area_m2 / _HECTARE_M2

    def levels(self, surface: Surface | str) -> tuple[float, float] | None:
        """Las cotas mínima y máxima de la superficie ``surface`` (m), o ``None`` sin dato."""
        if Surface(surface) is Surface.FINAL:
            low, high = self.final_min_m, self.final_max_m
        else:
            low, high = self.exploitation_min_m, self.exploitation_max_m
        return None if low is None or high is None else (low, high)


@dataclass(frozen=True, slots=True, eq=False)
class Classification:
    """La clasificación de las dos superficies (A8; RF-014-15): ``grid`` (float64, de la forma de
    la rejilla), el código de la clase de cada celda del dominio de trabajo con dato en las dos
    (``CellClass.code``: 0 sin diferencia, 1 desdoblado, 2 relleno; P-1) y sin dato (``NaN``) en
    las demás; el espesor mínimo con que se hizo (m), el área de una celda (m²), el ``total`` y un
    reparto por cada sector que toca el dominio (``sectors``, en el orden de los sectores; la
    celdas del dominio de ningún sector cuentan solo en el total)."""

    grid: np.ndarray
    min_thickness_m: float
    cell_area_m2: float
    total: ClassTotals
    sectors: tuple[ClassTotals, ...]

    def sector(self, code: str) -> ClassTotals:
        """El reparto del sector de código ``code``; ``KeyError`` si el dominio no lo toca."""
        for item in self.sectors:
            if item.sector is not None and item.sector.code == code:
                return item
        raise KeyError(code)


def _min_thickness(value: object) -> float:
    """El espesor mínimo (m): un número finito ≥ 0 (``ValueError`` si no)."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"el espesor mínimo es un número finito ≥ 0, no {value!r}")
    return number


def classify_steps(final: np.ndarray, exploitation: np.ndarray, start: np.ndarray,
                   domain: DomainSet, geometry: Grid, min_thickness_m: float, *,
                   fill_zones: np.ndarray | None = None, budget_s: float = STEP_BUDGET_S,
                   cells_per_unit: int = CLASS_CELLS_PER_UNIT) -> Iterator[Progress]:
    """**La clasificación** de las dos superficies ya ordenadas (A8; RF-014-15, RF-014-16) en
    las celdas del dominio de trabajo ``domain`` (con sus etiquetas de sector), por pasos de
    ``budget_s`` como mucho (una unidad por banda de ``cells_per_unit`` celdas); el último
    ``Progress`` (fase ``classes``) lleva la :class:`Classification`. Con ``Δ = explotación −
    final`` y ``e`` = ``min_thickness_m`` (el espesor mínimo de la 012, D-12):

    - ``Δ ≤ e``, **sin diferencia** (también la final hasta 1 mm por encima, RF-014-14);
    - ``Δ > e`` dentro de ``fill_zones`` (las zonas de restauración por relleno, la capa de D-11,
      como máscara de la rejilla; ``None``, ninguna), **relleno**: la diferencia la cubre un
      relleno;
    - ``Δ > e`` fuera de ellas, **desdoblado**: se excava al cerrar.

    Los volúmenes, ``Σ Δ · área de celda`` de las celdas de cada clase, y la excavación de la
    explotación, ``Σ (terreno − explotación) · área de celda`` donde pasa de ``e``: la fórmula
    celda a celda de la cubicación de la 011 (desmonte con todo su espesor donde pasa del umbral),
    en total y por sector; y las cotas mínima y máxima de cada superficie en el dominio. Una celda
    con un valor no finito en una de las dos superficies no tiene clase (``nodata_cells``).

    ``ValueError`` (error del programa) al llamar si las rejillas, el dominio o las zonas no son de
    la forma de ``geometry`` o el espesor no es un número finito ≥ 0; al avanzar, si la final pasa
    de la explotación en más de :data:`ORDER_TOLERANCE_M` (las superficies no vienen de la regla
    de orden). Ninguna entrada se modifica y no se escribe nada; cerrar el generador a mitad no
    deja nada. No importa ``reserves``: la prueba compara con su cubicación."""
    shape = geometry.shape
    upper = np.asarray(final, dtype=np.float64)
    lower = np.asarray(exploitation, dtype=np.float64)
    base = np.asarray(start, dtype=np.float64)
    for label, grid in (("la superficie final", upper), ("la superficie de explotación", lower),
                        ("la superficie de partida", base),
                        ("el dominio de trabajo", domain.mask),
                        ("las etiquetas de sector", domain.labels)):
        _same_shape(label, grid, shape)
    zone = None
    if fill_zones is not None:
        zone = np.asarray(fill_zones, dtype=bool)
        _same_shape("las zonas de restauración por relleno", zone, shape)
    threshold = _min_thickness(min_thickness_m)
    if isinstance(cells_per_unit, bool) or int(cells_per_unit) < 1:
        raise ValueError(f"una unidad tiene al menos una celda, no {cells_per_unit!r}")
    rows = max(1, int(cells_per_unit) // max(geometry.ncols, 1))
    work = _class_units(upper, lower, base, domain, zone, threshold, geometry.cell_area, rows)
    return pace_progress(work, budget_s, phase="classes",
                         running="Clasificando las dos superficies…",
                         finished="Las dos superficies, clasificadas",
                         total=max(2, -(-geometry.nrows // rows) + 1))


@dataclass(slots=True)
class _ClassSums:
    """Lo que se lleva sumado de la clasificación, por etiqueta de sector (la 0, ninguno)."""

    size: int
    exp_cut: list[np.ndarray]
    unsplit: list[np.ndarray]
    fill: list[np.ndarray]
    counts: dict[str, np.ndarray]
    lows: dict[Surface, np.ndarray]
    highs: dict[Surface, np.ndarray]

    @classmethod
    def empty(cls, size: int) -> _ClassSums:
        return cls(size, [], [], [], {key: np.zeros(size, np.int64) for key in
                                      ("cells", "nodata", "exp_cut", "unsplit", "fill", "none")},
                   {surface: np.full(size, np.inf) for surface in Surface},
                   {surface: np.full(size, -np.inf) for surface in Surface})

    def count(self, key: str, label: np.ndarray, mask: np.ndarray) -> None:
        self.counts[key] += np.bincount(label[mask], minlength=self.size)

    def add(self, target: list[np.ndarray], label: np.ndarray, mask: np.ndarray,
            values: np.ndarray) -> None:
        target.append(np.bincount(label[mask], weights=values[mask], minlength=self.size))

    def levels(self, surface: Surface, label: np.ndarray, values: np.ndarray) -> None:
        known = np.isfinite(values)
        np.minimum.at(self.lows[surface], label[known], values[known])
        np.maximum.at(self.highs[surface], label[known], values[known])

    def totals(self, sector: SectorRef | None, labels: Sequence[int], cell_area: float
               ) -> ClassTotals:
        """El reparto de las etiquetas ``labels`` (todas, el total; una, un sector)."""
        chosen = list(labels)

        def volume(parts: list[np.ndarray]) -> float:
            return math.fsum(float(value) for part in parts for value in part[chosen]) * cell_area

        def count(key: str) -> int:
            return int(self.counts[key][chosen].sum())

        def level(values: np.ndarray, pick: str) -> float | None:
            found = values[chosen]
            found = found[np.isfinite(found)]
            if not found.size:
                return None
            return float(found.min() if pick == "min" else found.max())

        return ClassTotals(
            sector, count("cells"), count("nodata"), volume(self.exp_cut), count("exp_cut"),
            volume(self.unsplit), count("unsplit"), volume(self.fill), count("fill"),
            count("none"), level(self.lows[Surface.FINAL], "min"),
            level(self.highs[Surface.FINAL], "max"),
            level(self.lows[Surface.EXPLOITATION], "min"),
            level(self.highs[Surface.EXPLOITATION], "max"), cell_area)


def _class_units(final: np.ndarray, exploitation: np.ndarray, start: np.ndarray,
                 domain: DomainSet, zone: np.ndarray | None, threshold: float, cell_area: float,
                 rows_per_unit: int) -> Generator[None, None, Classification]:
    """Las unidades de :func:`classify_steps`: una por banda de ``rows_per_unit`` filas."""
    nrows = start.shape[0]
    sums = _ClassSums.empty(len(domain.sectors) + 1)
    grid = np.full(start.shape, np.nan)
    for first in range(0, nrows, rows_per_unit):
        rows = slice(first, min(nrows, first + rows_per_unit))
        inside = domain.mask[rows]
        label = domain.labels[rows][inside].astype(np.intp)
        upper, lower, base = final[rows][inside], exploitation[rows][inside], start[rows][inside]
        valid = np.isfinite(upper) & np.isfinite(lower)
        with np.errstate(invalid="ignore"):
            delta = lower - upper
            dug = base - lower
        if bool(np.any(valid & (delta < -ORDER_TOLERANCE_M))):
            raise ValueError("la superficie final queda más de 1 mm por encima de la de "
                             "explotación: las superficies no vienen de la regla de orden "
                             "(RF-014-14)")
        moved = valid & (delta > threshold)
        in_zone = np.zeros(moved.shape, bool) if zone is None else zone[rows][inside]
        filled, unsplit = moved & in_zone, moved & ~in_zone
        codes = np.where(filled, float(CellClass.FILL.code),
                         np.where(unsplit, float(CellClass.UNSPLIT.code),
                                  float(CellClass.NONE.code)))
        codes[~valid] = np.nan
        grid[rows][inside] = codes
        cut = np.isfinite(base) & np.isfinite(lower) & (dug > threshold)
        everything = np.ones(label.shape, bool)
        sums.count("cells", label, everything)
        sums.count("nodata", label, ~valid)
        sums.count("exp_cut", label, cut)
        sums.count("unsplit", label, unsplit)
        sums.count("fill", label, filled)
        sums.count("none", label, valid & ~moved)
        sums.add(sums.exp_cut, label, cut, dug)
        sums.add(sums.unsplit, label, unsplit, delta)
        sums.add(sums.fill, label, filled, delta)
        sums.levels(Surface.FINAL, label, upper)
        sums.levels(Surface.EXPLOITATION, label, lower)
        yield
    sectors = tuple(sums.totals(sector, (index,), cell_area)
                    for index, sector in enumerate(domain.sectors, start=1)
                    if sums.counts["cells"][index] > 0)
    total = sums.totals(None, range(sums.size), cell_area)
    return Classification(grid, threshold, cell_area, total, sectors)


def classification_figures(name: str, classes: Classification) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO de la clasificación ``classes`` de la cantera ``name`` (RF-014-16;
    plan 014 §5.2.3), en el orden de ``provenance.TWO_SURFACES_FIGURES``, en total y por cada
    sector con código (el perímetro como sector único es el total y no se repite): la excavación
    de la explotación, el desdoblado y el relleno de restauración (m³), sus áreas (ha) y las cotas
    mínima y máxima de cada superficie (m; con la superficie en su ámbito, y solo si tiene dato),
    con el ámbito de ``provenance.quarry_figure_scope``. Lo que pasa a la explotación con
    «explotación hasta la final» (``des.to_final_m3``) lo da :func:`to_final_figures`. Un valor no
    finito es un error del programa (``ValueError``)."""
    found: list[FigureSpec] = []
    for item in (classes.total, *classes.sectors):
        if item.sector is not None and not item.sector.code:
            continue
        sector = None if item.sector is None else item.sector.code
        scope = provenance.quarry_figure_scope(name, sector=sector)
        for key, value, unit in (
                ("des.exp_cut_m3", item.exp_cut_m3, "m3"),
                ("des.unsplit_m3", item.unsplit_m3, "m3"),
                ("des.restoration_fill_m3", item.fill_m3, "m3"),
                ("des.exp_cut_area_ha", item.exp_cut_area_ha, "ha"),
                ("des.unsplit_area_ha", item.area_ha(CellClass.UNSPLIT), "ha"),
                ("des.restoration_fill_area_ha", item.area_ha(CellClass.FILL), "ha")):
            found.append(FigureSpec(key, _figure_value(key, value), unit, scope=scope))
        for surface in Surface:
            levels = item.levels(surface)
            if levels is None:
                continue
            surface_scope = provenance.quarry_figure_scope(name, surface=surface, sector=sector)
            for key, value in zip(("des.quarry_min_m", "des.quarry_max_m"), levels, strict=True):
                found.append(FigureSpec(key, _figure_value(key, value), "m",
                                        scope=surface_scope))
    return tuple(found)


def _figure_value(key: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"la cifra «{key}» no es un número finito: {value!r} (no se registra "
                         "una cifra NaN ni infinita)")
    return number


# --- Explotación hasta la final (T18; A9) ---------------------------------------------------------

UNEXPLOITED_M = 0.3
"""El terreno sigue **sin explotar** donde la explotación queda a menos de esto de él (m;
RF-014-17). Es la definición de la spec, no un parámetro (plan 014 §5.2.2)."""
TO_FINAL_NAME = "explotación hasta la final"
"""El nombre de la envolvente de «explotación hasta la final» en los mensajes de la 013
(RF-013-15): «<cantera> (explotación hasta la final)»."""
_TO_FINAL_FIGURE = "des.to_final_m3"
_AREA_RTOL = 1e-12
"""La tolerancia relativa con que una zona pasa del área mínima del aviso (RF-014-17, «de más
del área mínima»): ``área > mín_ha · 10⁴ · (1 + 10⁻¹²)``. El área mínima se da en ha y
``mín_ha · 10⁴`` no siempre es el entero de m² que se tecleó (0,07 ha da 700,0000000000001 m² y
0,0029 ha, 28,999999999999996 m²): sin ella, una zona de justo el área mínima se avisaría con
unos valores y no con otros. Una celda más pasa siempre de ella."""


@dataclass(frozen=True, slots=True)
class UnsplitZone:
    """Una zona conexa (4 vecinos) de desdoblado (A9; RF-014-17, RF-014-18): su número ``zone``
    (desde 1, en el orden de su primera celda recorriendo la rejilla fila a fila desde el norte),
    sus ``cells``, su ``area_m2``, su ``volume_m3`` (el desdoblado de sus celdas, ``Σ
    (explotación − final) · área de celda``) y el centro ``x``, ``y`` (m, absolutos en float64: la
    media de los centros de sus celdas)."""

    zone: int
    cells: int
    area_m2: float
    volume_m3: float
    x: float
    y: float

    @property
    def area_ha(self) -> float:
        """Su área (ha)."""
        return self.area_m2 / _HECTARE_M2


def _band_rows(geometry: Grid) -> int:
    """Las filas de una unidad de trabajo por bandas (:data:`CLASS_CELLS_PER_UNIT` celdas)."""
    return max(1, CLASS_CELLS_PER_UNIT // max(geometry.ncols, 1))


def _zone_units(labels: Labels, delta: np.ndarray, geometry: Grid,
                chosen: Sequence[int] | None = None
                ) -> Generator[None, None, tuple[UnsplitZone, ...]]:
    """Las unidades (una por banda de filas) de las zonas de las componentes ``labels`` (todas, o
    las etiquetas ``chosen`` en su orden), numeradas desde 1, con el volumen de ``delta`` (m) en
    sus celdas y su centro absoluto."""
    count = labels.count + 1
    row_sum = np.zeros(count)
    col_sum = np.zeros(count)
    depth = np.zeros(count)
    step = _band_rows(geometry)
    for first in range(0, geometry.nrows, step):
        band = labels.grid[first:first + step].ravel()
        picked = np.flatnonzero(band)
        tags = band[picked]
        rows, cols = np.divmod(picked, geometry.ncols)
        row_sum += np.bincount(tags, weights=rows + first, minlength=count)
        col_sum += np.bincount(tags, weights=cols, minlength=count)
        depth += np.bincount(tags, weights=delta[first:first + step].ravel()[picked],
                             minlength=count)
        yield None
    found = []
    for number, index in enumerate(range(1, count) if chosen is None else chosen, start=1):
        cells = int(labels.sizes[index - 1])
        x = geometry.west + (col_sum[index] / cells + 0.5) * geometry.dx
        y = geometry.north - (row_sum[index] / cells + 0.5) * geometry.dy
        found.append(UnsplitZone(number, cells, cells * geometry.cell_area,
                                 float(depth[index]) * geometry.cell_area, float(x), float(y)))
    return tuple(found)


@dataclass(frozen=True, slots=True, eq=False)
class UnsplitZones:
    """**El aviso** de que la explotación no llega a la final (A9; RF-014-17, error 60):
    ``candidates``, las celdas de desdoblado con más del umbral de diferencia sobre terreno sin
    explotar (máscara nueva); las ``zones`` avisadas (:class:`UnsplitZone`: las componentes
    4-conexas de ``candidates`` de más del área mínima, numeradas desde 1) y sus celdas
    (``warned``); y el umbral (``threshold_m``, m) y el área mínima (``min_area_ha``, ha) con que
    se buscaron."""

    zones: tuple[UnsplitZone, ...]
    candidates: np.ndarray
    warned: np.ndarray
    threshold_m: float
    min_area_ha: float

    @property
    def area_ha(self) -> float:
        """El área de las zonas avisadas (ha)."""
        return math.fsum(zone.area_m2 for zone in self.zones) / _HECTARE_M2

    @property
    def volume_m3(self) -> float:
        """El desdoblado de las zonas avisadas (m³)."""
        return math.fsum(zone.volume_m3 for zone in self.zones)

    @property
    def notices(self) -> tuple[str, ...]:
        """El aviso en español: ``des.quarry_unsplit_zones`` (las zonas, su área y su volumen, el
        umbral y el área mínima, y el modo que lo resuelve) y una ``des.quarry_unsplit_zone`` por
        zona (área, volumen y centro al cm); ``()`` sin zonas avisadas."""
        if not self.zones:
            return ()
        lines = [render("des.quarry_unsplit_zones", zones=len(self.zones),
                        area=round(self.area_ha, 2), volume=round(self.volume_m3, 1),
                        threshold=self.threshold_m, min_area=self.min_area_ha)]
        lines.extend(render("des.quarry_unsplit_zone", zone=zone.zone,
                            area=round(zone.area_ha, 2), volume=round(zone.volume_m3, 1),
                            x=round(zone.x, 2), y=round(zone.y, 2)) for zone in self.zones)
        return tuple(lines)


def unsplit_zones_steps(final: np.ndarray, exploitation: np.ndarray, start: np.ndarray,
                        classes: Classification, geometry: Grid, threshold_m: float | None,
                        min_area_ha: float | None, *, budget_s: float = STEP_BUDGET_S
                        ) -> Iterator[Progress]:
    """**El aviso de A9** (RF-014-17, error 60; D-5) sobre las dos superficies ya ordenadas
    ``final`` y ``exploitation`` (m, de la forma de ``geometry``) y su clasificación ``classes``
    (:func:`classify_steps`), por pasos de ``budget_s`` como mucho; el último ``Progress`` (fase
    ``unsplit``) lleva las :class:`UnsplitZones`. Son del aviso las celdas **desdobladas** de la
    clasificación con ``Δ = explotación − final`` **mayor** que el umbral ``threshold_m`` (m, el
    parámetro ``des.quarry.unsplit_threshold_m``) sobre **terreno sin explotar**: ``|explotación −
    z| <`` :data:`UNEXPLOITED_M` con la de partida ``start``. Se avisan sus zonas 4-conexas de
    **más** de ``min_area_ha`` (ha, ``des.quarry.unsplit_min_area_ha``; la igualdad no avisa,
    también en coma flotante: ``área > min_area_ha · 10⁴ · (1 + 10⁻¹²)``), con su área, su volumen
    y su centro. El desdoblado bajo el umbral o justo en él, sobre terreno ya excavado o en zonas
    de esa área o más pequeñas no se avisa: cuenta en la clasificación.

    Rechazos al llamar: el umbral y el área mínima, como sus parámetros (``check_quarry_param``:
    ``des.quarry_param_missing`` o ``des.quarry_param_range``); ``ValueError`` (error del programa)
    si las rejillas no son de la forma de ``geometry``. Ninguna entrada se modifica y no se
    escribe nada; cerrar el generador a mitad no deja nada."""
    threshold = float(check_quarry_param(UNSPLIT_THRESHOLD, threshold_m))
    min_area = float(check_quarry_param(UNSPLIT_MIN_AREA, min_area_ha))
    upper = np.asarray(final, dtype=np.float64)
    lower = np.asarray(exploitation, dtype=np.float64)
    base = np.asarray(start, dtype=np.float64)
    for label, grid in (("la superficie final", upper), ("la superficie de explotación", lower),
                        ("la superficie de partida", base), ("la clasificación", classes.grid)):
        _same_shape(label, grid, geometry.shape)
    work = _unsplit_units(upper, lower, base, classes.grid, geometry, threshold, min_area)
    return pace_progress(work, budget_s, phase="unsplit",
                         running="Buscando el desdoblado sobre terreno sin explotar…",
                         finished="Desdoblado sobre terreno sin explotar, medido")


def _unsplit_units(final: np.ndarray, exploitation: np.ndarray, start: np.ndarray,
                   codes: np.ndarray, geometry: Grid, threshold: float, min_area: float
                   ) -> Generator[None, None, UnsplitZones]:
    """Las unidades de :func:`unsplit_zones_steps`: las celdas del aviso y su ``Δ``, por bandas
    de filas; sus componentes; y las zonas avisadas."""
    candidates = np.zeros(final.shape, dtype=bool)
    delta = np.zeros(final.shape)
    step = _band_rows(geometry)
    for first in range(0, geometry.nrows, step):
        rows = slice(first, first + step)
        with np.errstate(invalid="ignore"):
            band = exploitation[rows] - final[rows]
            found = ((codes[rows] == float(CellClass.UNSPLIT.code)) & (band > threshold)
                     & (np.abs(exploitation[rows] - start[rows]) < UNEXPLOITED_M))
        candidates[rows] = found
        delta[rows] = np.where(found, band, 0.0)
        yield None
    labels: Labels = yield from _label_units(candidates)
    areas = labels.sizes * geometry.cell_area
    limit = min_area * _HECTARE_M2 * (1.0 + _AREA_RTOL)
    chosen = [index for index in range(1, labels.count + 1) if areas[index - 1] > limit]
    keep = np.zeros(labels.count + 1, dtype=bool)
    keep[chosen] = True
    zones = yield from _zone_units(labels, delta, geometry, chosen)
    return UnsplitZones(zones, candidates, keep[labels.grid], threshold, min_area)


@dataclass(frozen=True, slots=True, eq=False)
class ToFinal:
    """«Explotación hasta la final» aplicada (A9; RF-014-18): ``exploitation``, la superficie de
    explotación bajada (m, float64, nueva); las celdas en que se aplicó (``target``, una máscara
    nueva) y sus zonas 4-conexas (``zones``, :class:`UnsplitZone`, con el desdoblado que tenían);
    el volumen que pasa del desdoblado a la explotación (``volume_m3``: ``Σ (antes − después) ·
    área de celda``, también el de la transición) y el de cada sector que toca el dominio
    (``sectors``: pares sector y m³, en su orden); y las celdas bajadas (``lowered_cells``)."""

    exploitation: np.ndarray
    target: np.ndarray
    zones: tuple[UnsplitZone, ...]
    volume_m3: float
    sectors: tuple[tuple[SectorRef, float], ...]
    lowered_cells: int

    @property
    def area_ha(self) -> float:
        """El área de las zonas en que se aplicó (ha)."""
        return math.fsum(zone.area_m2 for zone in self.zones) / _HECTARE_M2

    @property
    def notice(self) -> str:
        """La nota en español ``des.quarry_to_final``: las zonas, su área y el volumen que pasa a
        la explotación."""
        return render("des.quarry_to_final", zones=len(self.zones), area=round(self.area_ha, 2),
                      volume=round(self.volume_m3, 1))


def _cell_values(name: str, value: float | np.ndarray, shape: tuple[int, ...]
                 ) -> float | np.ndarray:
    """Un valor por celda (un número o una rejilla de ``shape``), como float64."""
    found = np.asarray(value, dtype=np.float64)
    if found.ndim == 0:
        return float(found)
    _same_shape(name, found, shape)
    return found


def to_final_steps(final: np.ndarray, exploitation: np.ndarray, start: np.ndarray,
                   domain: DomainSet, geometry: Grid, target: np.ndarray, *,
                   anchor: float | np.ndarray, height_m: float | np.ndarray, slope: SlopeField,
                   metric: Metric | str = Metric.CHAMFER5, name: str = "",
                   budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Explotación hasta la final»** (A9; RF-014-18) en las celdas ``target`` (máscara de
    ``geometry``) de las dos superficies ya ordenadas ``final`` y ``exploitation`` (m), por pasos
    de ``budget_s`` como mucho; el último ``Progress`` (fase ``to_final``) lleva el
    :class:`ToFinal`:

    1. en cada celda de ``target``, la cota de ancla de la explotación inmediatamente por encima
       de la final, ``T = a + h·⌈(final − a)/h⌉`` con su ancla ``a`` (``anchor``: la del perfil,
       una rejilla de anclas o la «al fondo de cada muro») y su altura de banco ``h``
       (``height_m``), un número o una rejilla por celda (una final a ≤ 10⁻⁹ m por encima de una
       cota de ancla queda en ella);
    2. la envolvente ascendente de la 013 de ``T`` con la pendiente ``slope`` (``tan(cara) ·
       malla`` del perfil de explotación de cada celda) y la ``metric`` del lado: la transición
       con el resto de la explotación a la cara de su perfil, como la V10;
    3. en el dominio de trabajo ``domain``, ``máx(final, mín(explotación, ENV↑))``: nunca por
       debajo de la final ni por encima de la explotación; fuera, la explotación; y ``≤ z``.

    El volumen que pasa del desdoblado a la explotación es ``Σ (explotación − nueva) · área de
    celda``, en total y por sector; el de cada zona de ``target``, su desdoblado de antes.

    ``ValueError`` (error del programa) al llamar si una rejilla no es de la forma de
    ``geometry``, la altura no es finita y mayor que 0 en ``target``, o la métrica es la euclídea
    exacta con una pendiente que no es constante. Al avanzar, los rechazos de la envolvente de la
    013 (RF-013-15), con ``name`` («<cantera> (explotación hasta la final)»). Ninguna entrada se
    modifica y no se escribe nada; cerrar el generador a mitad no deja nada."""
    shape = geometry.shape
    upper = np.asarray(final, dtype=np.float64)
    lower = np.asarray(exploitation, dtype=np.float64)
    base = np.asarray(start, dtype=np.float64)
    chosen = np.asarray(target, dtype=bool)
    for label, grid in (("la superficie final", upper), ("la superficie de explotación", lower),
                        ("la superficie de partida", base), ("las celdas donde se aplica", chosen),
                        ("el dominio de trabajo", domain.mask),
                        ("las etiquetas de sector", domain.labels)):
        _same_shape(label, grid, shape)
    level_anchor = _cell_values("el ancla", anchor, shape)
    height = _cell_values("la altura de banco", height_m, shape)
    with np.errstate(invalid="ignore"):
        bad = ~(np.isfinite(height) & (np.asarray(height) > 0.0))
    if bool(np.any(np.broadcast_to(bad, shape) & chosen)):
        raise ValueError("la altura de banco es finita y mayor que 0 donde se aplica")
    if not slope.uniform:
        _same_shape("la pendiente", np.asarray(slope.tan), shape)
    way = Metric(metric)
    if way is Metric.EXACT and not slope.uniform and np.ptp(np.asarray(slope.tan)) != 0.0:
        raise ValueError("la euclídea exacta solo admite una pendiente constante (RF-013-16)")
    label = f"{name} ({TO_FINAL_NAME})" if name else TO_FINAL_NAME
    work = _to_final_units(upper, lower, base, domain, geometry, chosen, level_anchor, height,
                           slope, way, label)
    return pace_progress(work, budget_s, phase="to_final",
                         running="Bajando la explotación hasta la final…",
                         finished="Explotación hasta la final calculada")


def _to_final_units(final: np.ndarray, exploitation: np.ndarray, start: np.ndarray,
                    domain: DomainSet, geometry: Grid, target: np.ndarray,
                    anchor: float | np.ndarray, height: float | np.ndarray, slope: SlopeField,
                    metric: Metric, name: str) -> Generator[None, None, ToFinal]:
    """Las unidades de :func:`to_final_steps`: las cotas ``T`` y ``Δ`` donde se aplica, por
    bandas de filas; la envolvente ascendente; la explotación nueva y lo que pasa a ella, por
    bandas; y las zonas."""
    step = _band_rows(geometry)
    bands = [slice(first, first + step) for first in range(0, geometry.nrows, step)]
    seed = np.full(final.shape, np.inf)
    delta = np.zeros(final.shape)
    for rows in bands:
        a = anchor if isinstance(anchor, float) else anchor[rows]
        h = height if isinstance(height, float) else height[rows]
        here = target[rows]
        with np.errstate(invalid="ignore"):
            level = a + h * np.ceil((final[rows] - a - TOLERANCE_M) / h)
            seed[rows] = np.where(here & np.isfinite(level), level, np.inf)
            delta[rows] = np.where(here, exploitation[rows] - final[rows], 0.0)
        yield None
    rising = yield from _rising_work(seed, geometry, slope, metric, name)
    lowered = exploitation.copy()
    size = len(domain.sectors) + 1
    per_label = np.zeros(size)
    in_domain = np.zeros(size, dtype=np.int64)
    changed_cells = 0
    for rows in bands:
        upper, lower = final[rows], exploitation[rows]
        inside = domain.mask[rows] & np.isfinite(upper) & np.isfinite(lower)
        band = np.where(inside, np.fmax(upper, np.fmin(lower, rising[rows])), lower)
        band = _at_most(band, start[rows])
        lowered[rows] = band
        with np.errstate(invalid="ignore"):
            moved = np.where(inside, lower - band, 0.0)
        changed = inside & (moved > 0.0)
        labels_here = domain.labels[rows]
        per_label += np.bincount(labels_here[changed].astype(np.intp), weights=moved[changed],
                                 minlength=size)
        in_domain += np.bincount(labels_here[domain.mask[rows]].astype(np.intp), minlength=size)
        changed_cells += int(np.count_nonzero(changed))
        yield None
    area = geometry.cell_area
    sectors = tuple((sector, float(per_label[index]) * area)
                    for index, sector in enumerate(domain.sectors, start=1)
                    if in_domain[index] > 0)
    labels: Labels = yield from _label_units(target)
    zones = yield from _zone_units(labels, delta, geometry)
    return ToFinal(lowered, target.copy(), zones, math.fsum(per_label.tolist()) * area, sectors,
                   changed_cells)


def to_final_figures(name: str, to_final: ToFinal) -> tuple[FigureSpec, ...]:
    """La cifra CALCULADO ``des.to_final_m3`` (m³; RF-014-18; plan 014 §5.2.3) de la cantera
    ``name``: el volumen que pasa del desdoblado a la explotación con «explotación hasta la
    final», en total y por cada sector con código (el perímetro como sector único es el total y no
    se repite), con el ámbito de ``provenance.quarry_figure_scope``."""
    found = [FigureSpec(_TO_FINAL_FIGURE, _figure_value(_TO_FINAL_FIGURE, to_final.volume_m3),
                        "m3", scope=provenance.quarry_figure_scope(name))]
    found.extend(FigureSpec(_TO_FINAL_FIGURE, _figure_value(_TO_FINAL_FIGURE, volume), "m3",
                            scope=provenance.quarry_figure_scope(name, sector=sector.code))
                 for sector, volume in to_final.sectors if sector.code)
    return tuple(found)


def _parameter_default(key: str) -> float:
    """El valor por defecto declarado del parámetro de la 014 ``key`` (``design.params``)."""
    value = QUARRY_PARAMS[key].default
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"el parámetro «{key}» no tiene un valor por defecto numérico")
    return float(value)


def _by_surface[T](items: Mapping[Surface | str, T]) -> Mapping[Surface, T]:
    """``items`` con sus claves como :class:`~.model.Surface` (``ValueError`` si una no es una de
    las dos), en un mapa que no se puede cambiar."""
    return MappingProxyType({Surface(key): value for key, value in items.items()})


@dataclass(frozen=True, slots=True, eq=False)
class QuarryJob:
    """Lo que necesita calcular la cantera con dos superficies, ya leído y sin proyecto (plan 014
    §5.3.1; lo que ``DesignJob`` a la 013): lo común a los dos lados, como en :class:`SideJob` (la
    petición, la de partida, las máscaras, el dominio de trabajo con sus sectores, los parámetros,
    el anillo de coronación, el espesor mínimo, la tolerancia de cara, el umbral de aviso, los
    fondos y corredores ya juntos, el techo ya calculado y los sectores con la búsqueda
    pendiente: los fondos y el techo se calculan una vez para los dos), y lo de cada lado por su
    :class:`~.model.Surface`: las semillas de la 013 (``seeds``) del lado que no siembra la
    coronación y la rejilla de anclas leída (``anchors``) del lado con el ancla en rejilla; las
    zonas de restauración por relleno de la clasificación (``fill_zones``: la capa de D-11 como
    máscara de la rejilla; ``None``, ninguna); el umbral de desdoblado y el área mínima del aviso
    de «explotación hasta la final» (``unsplit_threshold_m``, m, y ``unsplit_min_area_ha``, ha:
    los valores de ``des.quarry.unsplit_threshold_m`` y ``des.quarry.unsplit_min_area_ha``; por
    defecto, los declarados en ``design.params``, D-5) y, con el modo «las de una capa», sus
    polígonos como máscara de la rejilla (``to_final_zones``; P-2). ``ValueError`` si una clave no
    es una de las dos superficies."""

    request: QuarryRequest
    start: np.ndarray
    masks: MaskSet
    domain: DomainSet
    values: Mapping[str, object]
    ring_cells: int
    min_thickness_m: float
    face_tolerance_deg: float
    warning_ratio: float
    seeds: Mapping[Surface | str, SeedSet] = MappingProxyType({})
    floors: FloorMap | None = None
    ceiling: ConservationCeiling | None = None
    anchors: Mapping[Surface | str, np.ndarray] = MappingProxyType({})
    pending: tuple[str, ...] = ()
    fill_zones: np.ndarray | None = None
    unsplit_threshold_m: float = _parameter_default(UNSPLIT_THRESHOLD)
    unsplit_min_area_ha: float = _parameter_default(UNSPLIT_MIN_AREA)
    to_final_zones: np.ndarray | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "seeds", _by_surface(self.seeds))
        object.__setattr__(self, "anchors", _by_surface(self.anchors))

    def side_job(self, surface: Surface | str) -> SideJob:
        """El :class:`SideJob` del lado ``surface``: lo común y sus semillas y su rejilla de
        anclas, si las tiene."""
        surface = Surface(surface)
        return SideJob(self.request, surface, self.start, self.masks, self.domain, self.values,
                       self.ring_cells, self.min_thickness_m, self.face_tolerance_deg,
                       self.warning_ratio, seeds=self.seeds.get(surface), floors=self.floors,
                       ceiling=self.ceiling, anchors=self.anchors.get(surface),
                       pending=self.pending)


@dataclass(frozen=True, slots=True, eq=False)
class QuarryOutcome:
    """La cantera con dos superficies calculada (A8; RF-014-12 a RF-014-14): el ``order`` del
    diseño, cada lado tal como se calculó, antes de la regla de orden (``final`` y
    ``exploitation``, :class:`SideOutcome`: su envolvente, su escalonado, su informe y sus bermas
    de la 013), las dos superficies atadas por el orden y comprobadas (``ordered``,
    :class:`OrderedSurfaces`), su clasificación (``classes``, :class:`Classification`;
    RF-014-15) y sus cifras CALCULADO (``figures``, :func:`classification_figures` y, con
    «explotación hasta la final», :func:`to_final_figures`; RF-014-16, RF-014-18), el aviso de
    desdoblado sobre terreno sin explotar que queda (``unsplit``, :class:`UnsplitZones`;
    RF-014-17), «explotación hasta la final» aplicada (``to_final``, :class:`ToFinal`; ``None``
    sin el modo) y el ``message`` de la operación. Con el modo, la clasificación, las cifras y el
    aviso son los de la explotación bajada."""

    order: Order
    final: SideOutcome
    exploitation: SideOutcome
    ordered: OrderedSurfaces
    classes: Classification
    figures: tuple[FigureSpec, ...]
    unsplit: UnsplitZones
    to_final: ToFinal | None
    message: str

    def side(self, surface: Surface | str) -> SideOutcome:
        """El lado de la superficie ``surface``, antes de la regla de orden."""
        if Surface(surface) is Surface.FINAL:
            return self.final
        return self.exploitation

    @property
    def final_grid(self) -> np.ndarray:
        """La superficie final (m, float64): la del lado final con la regla de orden y ``≤ z``."""
        return self.ordered.final

    @property
    def exploitation_grid(self) -> np.ndarray:
        """La superficie de explotación (m, float64): la de su lado con la regla de orden y
        ``≤ z`` y, con «explotación hasta la final», bajada (:attr:`ToFinal.exploitation`)."""
        if self.to_final is not None:
            return self.to_final.exploitation
        return self.ordered.exploitation

    @property
    def adjusted(self) -> int:
        """Las celdas en que la regla de orden cambió la segunda superficie."""
        return self.ordered.adjusted

    @property
    def notices(self) -> tuple[str, ...]:
        """Los avisos y las notas en español: el de desdoblado sobre terreno sin explotar con sus
        zonas (RF-014-17) y, con «explotación hasta la final», lo que pasó a la explotación."""
        found = self.unsplit.notices
        if self.to_final is not None:
            found = (*found, self.to_final.notice)
        return found


_EXACT_CODES = MappingProxyType({Surface.FINAL: "des.quarry_final_exact",
                                 Surface.EXPLOITATION: "des.quarry_exploitation_exact"})
"""El rechazo de la euclídea exacta en cada superficie (T45): uno por lado, para nombrarlo en los
dos idiomas."""


def _check_metric(request: QuarryRequest) -> None:
    """RF-014-12 (T45, hallazgo F-6): la métrica de cada lado de la cantera ``request`` es el
    *chamfer* 5×5 (ADR-0014). Cada lado va con la pendiente de sus sectores (:func:`side_steps`)
    y la euclídea exacta solo admite una pendiente constante, así que un lado con ella se rechaza
    **al pedirlo**, antes de leer ni calcular nada: ``DesignError`` ``des.quarry_final_exact`` o
    ``des.quarry_exploitation_exact`` (con los dos, el de la final) con la cantera, el campo
    (``final.metric`` o ``exploitation.metric``, su ajuste) y el valor, que dice que se use el
    *chamfer* 5×5 (y no ``des.exact_needs_constant_slope``, que manda a la orden de la 013). Lo
    llaman :func:`quarry_steps` y ``design.steps.quarry_run``."""
    for surface in Surface:
        metric = Metric(request.side(surface).metric)
        if metric is Metric.EXACT:
            raise DesignError(_EXACT_CODES[surface],
                              obj=f"Cantera «{request.name}» ({SIDE_NAMES[surface]})",
                              field=f"{surface.value}.metric", value=metric.value,
                              quarry=request.name)


def quarry_steps(job: QuarryJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**Las dos superficies** de la cantera en una sola orden (A8; RF-014-12 a RF-014-14), por
    pasos de ``budget_s`` como mucho (los de :func:`side_steps` de cada lado y los del orden,
    §5.3.2); el último ``Progress`` (fase ``quarry``) lleva el :class:`QuarryOutcome`. En orden:

    1. los dos lados con :func:`side_steps` (:meth:`QuarryJob.side_job`), primero el que dice el
       orden del diseño: con «final primero», la final; con «explotación primero», la explotación;
    2. la regla de orden y ``≤ z`` (:func:`order_surfaces`, RF-014-13);
    3. el invariante ``final ≤ explotación ≤ terreno`` a 1 mm (:func:`check_order`, RF-014-14): si
       fallara, ``des.quarry_order_broken`` y ningún paso lleva un resultado que crear;
    4. la clasificación de las dos superficies en el dominio de trabajo con las zonas de
       restauración por relleno del trabajo (:func:`classify_steps`, RF-014-15) y sus cifras
       (:func:`classification_figures`, RF-014-16);
    5. el aviso de desdoblado sobre terreno sin explotar (:func:`unsplit_zones_steps`,
       RF-014-17) y, con «explotación hasta la final» (``request.to_final``, P-2) en las zonas
       avisadas o en las celdas del aviso dentro de los polígonos de ``job.to_final_zones``, la
       explotación bajada con el perfil, el ancla y la métrica del lado de explotación
       (:func:`to_final_steps`, RF-014-18), el invariante otra vez, la clasificación, el aviso de
       lo que queda y la cifra ``des.to_final_m3`` (:func:`to_final_figures`).

    ``ValueError`` (error del programa) al llamar con los de :func:`side_steps` de cada lado, si
    las zonas de relleno no son de la rejilla o si los polígonos de «explotación hasta la final»
    faltan con el modo «capa», se dan con otro modo o no son de la rejilla; ``DesignError`` al
    llamar, antes que nada, si un lado pide la euclídea exacta (:func:`_check_metric`, T45), y si
    el umbral o el área mínima del aviso están fuera de su rango (``check_quarry_param``). Al
    avanzar, los rechazos de la 013 de cada lado. Ninguna entrada se modifica y no se escribe
    nada; cerrar el generador a mitad no deja nada."""
    _check_metric(job.request)
    shape = job.masks.grid.shape
    if job.fill_zones is not None:
        _same_shape("las zonas de restauración por relleno", np.asarray(job.fill_zones), shape)
    mode = ToFinalMode(job.request.to_final)
    if (mode is ToFinalMode.LAYER) != (job.to_final_zones is not None):
        raise ValueError("los polígonos de «explotación hasta la final» van con el modo «capa» "
                         "y solo con él (P-2)")
    if job.to_final_zones is not None:
        _same_shape("los polígonos de «explotación hasta la final»",
                    np.asarray(job.to_final_zones), shape)
    check_quarry_param(UNSPLIT_THRESHOLD, job.unsplit_threshold_m)
    check_quarry_param(UNSPLIT_MIN_AREA, job.unsplit_min_area_ha)
    first = (Surface.FINAL if Order(job.request.order) is Order.FINAL_FIRST
             else Surface.EXPLOITATION)
    second = Surface.EXPLOITATION if first is Surface.FINAL else Surface.FINAL
    sides = {surface: side_steps(job.side_job(surface), budget_s=budget_s)
             for surface in (first, second)}
    return _quarry_work(job, sides[first], sides[second], budget_s)


def _quarry_work(job: QuarryJob, first: Iterator[Progress], second: Iterator[Progress],
                 budget_s: float) -> Generator[Progress, None, None]:
    order, name = Order(job.request.order), job.request.name
    done: list[SideOutcome] = []
    for steps in (first, second):
        outcome: SideOutcome = yield from forward(steps)
        done.append(outcome)
    by_surface = {outcome.surface: outcome for outcome in done}
    final, exploitation = by_surface[Surface.FINAL], by_surface[Surface.EXPLOITATION]
    start = np.asarray(job.start, dtype=np.float64)
    yield Progress("order", 0, 2, f"Ordenando las dos superficies ({ORDER_NAMES[order]})…")
    ordered = order_surfaces(order, final.grid, exploitation.grid, start)
    yield Progress("order", 1, 2, "Comprobando final ≤ explotación ≤ terreno…")
    check_order(name, ordered.final, ordered.exploitation, start, job.masks.grid)
    geometry = job.masks.grid
    yield Progress("classes", 0, 1, "Clasificando las dos superficies…")
    classes: Classification = yield from forward(classify_steps(
        ordered.final, ordered.exploitation, start, job.domain, geometry,
        job.min_thickness_m, fill_zones=job.fill_zones, budget_s=budget_s))
    yield Progress("unsplit", 0, 1, "Buscando el desdoblado sobre terreno sin explotar…")
    unsplit: UnsplitZones = yield from forward(unsplit_zones_steps(
        ordered.final, ordered.exploitation, start, classes, geometry, job.unsplit_threshold_m,
        job.unsplit_min_area_ha, budget_s=budget_s))
    to_final: ToFinal | None = None
    mode = ToFinalMode(job.request.to_final)
    if mode is not ToFinalMode.NONE:
        target = (unsplit.warned if mode is ToFinalMode.WARNED
                  else unsplit.candidates & np.asarray(job.to_final_zones, dtype=bool))
        anchor, height, slope, metric = _exploitation_benches(job, exploitation)
        yield Progress("to_final", 0, 1, "Bajando la explotación hasta la final…")
        to_final = yield from forward(to_final_steps(
            ordered.final, ordered.exploitation, start, job.domain, geometry, target,
            anchor=anchor, height_m=height, slope=slope, metric=metric, name=name,
            budget_s=budget_s))
        check_order(name, ordered.final, to_final.exploitation, start, geometry)
        classes = yield from forward(classify_steps(
            ordered.final, to_final.exploitation, start, job.domain, geometry,
            job.min_thickness_m, fill_zones=job.fill_zones, budget_s=budget_s))
        unsplit = yield from forward(unsplit_zones_steps(
            ordered.final, to_final.exploitation, start, classes, geometry,
            job.unsplit_threshold_m, job.unsplit_min_area_ha, budget_s=budget_s))
    figures = classification_figures(name, classes)
    if to_final is not None:
        figures = (*figures, *to_final_figures(name, to_final))
    text = (f"Cantera «{name}» calculada ({ORDER_NAMES[order]}): superficie final y de "
            f"explotación; la regla de orden cambió {ordered.adjusted} celdas; desdoblado "
            f"{format_value(round(classes.total.unsplit_m3, 1))} m³ y relleno de restauración "
            f"{format_value(round(classes.total.fill_m3, 1))} m³")
    if to_final is not None:
        text += (f"; explotación hasta la final {format_value(round(to_final.volume_m3, 1))} m³ "
                 "del desdoblado a la explotación")
    yield Progress("quarry", 1, 1, text,
                   result=QuarryOutcome(order, final, exploitation, ordered, classes, figures,
                                        unsplit, to_final, text))


def _exploitation_benches(job: QuarryJob, outcome: SideOutcome
                          ) -> tuple[np.ndarray, np.ndarray, SlopeField, Metric]:
    """Lo que A9 lee del lado de explotación (RF-014-18), por celda con las etiquetas de sector
    del dominio (el perfil de cada sector o el base): la cota de ancla (la del perfil, la rejilla
    leída o la «al fondo de cada muro» del lado), la altura de banco, la pendiente de su cara
    ``tan(cara) · malla`` y la métrica del lado."""
    side = job.request.exploitation
    assigned = dict(side.sector_profiles)
    profiles = bench_profiles(job.values, [side.base_profile, *assigned.values()])
    by_label = [profiles[side.base_profile],
                *(profiles[assigned.get(sector.code, side.base_profile)]
                  for sector in job.domain.sectors)]
    labels = job.domain.labels.astype(np.intp)
    heights = np.array([profile.height_m for profile in by_label])[labels]
    rules = [SlopeRule(math.tan(math.radians(profile.face_deg)), profile.mesh_factor)
             for profile in by_label]
    slope = sector_slope(job.domain.labels, rules[1:], rules[0])
    mode = AnchorMode(side.anchor)
    if mode is AnchorMode.GRID:
        anchor = np.asarray(job.anchors[Surface.EXPLOITATION], dtype=np.float64)
    elif mode is AnchorMode.NEAREST_FLOOR:
        if outcome.anchors is None:
            raise ValueError("el lado de explotación con el ancla «al fondo de cada muro» no "
                             "trae su rejilla de anclas")
        anchor = outcome.anchors.grid
    else:
        anchor = np.array([profile.anchor_m for profile in by_label])[labels]
    return anchor, heights, slope, Metric(side.metric)
