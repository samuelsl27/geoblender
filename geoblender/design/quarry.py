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
  :func:`floors_above_terrain` (:class:`FloorsAbove`) mide lo que queda por encima del terreno,
  que se admite (allí no hay corte) y se informa.
- :func:`with_floors` y :func:`floor_cut_steps` (T08; RF-014-05; A4): la corta ``máx(ENV↓(s, t),
  ENV↓(F, t))`` (``zdes = máx(BASE0, ZF)`` de la V7) sobre la envolvente de la 013, calculada
  como la envolvente descendente de la unión de las semillas y los fondos (el máximo de los dos
  donde coinciden): la descendente es un máximo sobre las semillas, así que es lo mismo con una
  sola envolvente.

- :func:`corridor_cells` (T09; RF-014-09, RF-014-10; A6): los **corredores** de una capa de
  líneas (eje, ancho y una cota fija o una rasante) convertidos en fondos con **extremos planos**
  (:class:`CorridorMap`, con un :class:`FloorMap`): las celdas a ≤ ancho/2 de un tramo cuya
  proyección no cae fuera del eje, con la cota fija o la de la rasante en la abscisa de esa
  proyección; su longitud medida es la del eje con error ≤ 1 celda (error 20), y
  :func:`corridor_too_long` da el aviso de RF-014-10.

- :func:`conservation_ceiling_steps` (T10; RF-014-07; A5): el **techo de conservación** ``U =
  ENV↑(z en Z, tan(talud de conservación))`` de las zonas a conservar (:class:`ConserveZone`)
  sobre la envolvente ascendente de la 013 (:class:`ConservationCeiling`, con el aviso
  ``des.conserve_nodata`` de las celdas de la zona sin dato de terreno, que no lo siembran), y
  :func:`apply_ceiling`, sus tres reglas: en ``Z``, la superficie es ``z``; fuera, ninguna celda
  con ``z > U`` se excava y la superficie no pasa de ``máx(U, z)`` (no entierra la zona: el error
  37 fue un relleno; spec 0.2). :func:`conserve_moved` (RF-014-08) mide lo que un diseño mueve
  dentro de las zonas, con el espesor mínimo de la 012, por partes con su volumen y su centro
  (:class:`ConserveMoved`, :class:`ConservePart`): más de 0 m³ es un error del diseño.

- :func:`floor_anchor_steps` (T11; RF-014-11; A7): la **rejilla de anclas** «al fondo de cada
  muro» (:class:`FloorAnchors`): en cada celda, la cota del fondo más próximo en planta (distancia
  euclídea exacta entre centros de celda; empate, la más baja), y :func:`anchored_request`, su paso
  al escalonado de la 013 como ancla en rejilla (D-18 de la 013): las bermas de cada muro quedan en
  ``fondo + k·h``.

Las demás piezas de la cantera (las dos superficies) llegan con sus tareas. Python puro
con numpy (nivel 8): no importa ``reserves`` ni ``bl``; no escribe nada.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import format_value
from ..gis.vector import FeatureLayer
from . import provenance
from .envelopes import (
    BLOCK_CELLS,
    BLOCK_GROUP,
    CELLS_PER_UNIT,
    EVALS_PER_UNIT,
    SlopeField,
    _exact_work,
    chamfer_units,
    constant_slope,
    envelope_steps,
)
from .grids import _label_units, _nearest_units, dilate_square
from .messages import DesignError, render
from .model import CorridorFields, DesignRequest, Direction, EnvelopeRequest, LayerField, Metric
from .params import CONSERVE_SLOPE, CROWN_RING, check_quarry_param
from .report import moved_cells
from .seeds import DomainSet, SeedSet, collect_seeds, domain_of, pace_progress
from .zones import _paint, _polygon_spans

__all__ = [
    "ANCHOR_LABEL",
    "AREA_PART_LABELS",
    "CEILING_NAME",
    "FLOOR_LEVEL_MARGIN_M",
    "HOLD_TYPES",
    "AreaOutcome",
    "AreaPart",
    "ConservationCeiling",
    "ConserveMoved",
    "ConservePart",
    "ConserveZone",
    "CorridorMap",
    "FloorAnchors",
    "FloorMap",
    "FloorsAbove",
    "SeedGroup",
    "anchored_request",
    "apply_ceiling",
    "area_outcome",
    "area_parts",
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
    "outside_crown",
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
    with np.errstate(invalid="ignore"):
        finite = np.isfinite(values)
    if not finite.any():
        raise ValueError("la superficie de partida no tiene ninguna celda con dato")
    low = float(values[finite].min()) - FLOOR_LEVEL_MARGIN_M
    high = float(values[finite].max()) + FLOOR_LEVEL_MARGIN_M
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


def floors_above_terrain(floors: FloorMap, start: np.ndarray) -> FloorsAbove:
    """Lo de los fondos ``floors`` por encima de la superficie de partida ``start`` (las celdas
    con cota de fondo mayor que la del terreno; RF-014-05): se admite —allí no hay corte, la
    superficie nunca supera el terreno— y se informa con su área (:attr:`FloorsAbove.notice`).
    ``ValueError`` si ``start`` no es de la forma del mapa. Solo lee."""
    values = np.asarray(start, dtype=np.float64)
    _same_shape("la superficie de partida", values, floors.grid.shape)
    with np.errstate(invalid="ignore"):
        above = int(np.count_nonzero(floors.grid > values))
    return FloorsAbove(above, above * floors.cell_area_m2)


def with_floors(seeds: SeedSet, floors: FloorMap) -> SeedSet:
    """Las semillas de la corta con fondos (A4): las de ``seeds`` y las celdas de ``floors`` con su
    cota; donde coinciden, la más alta de las dos (``máx(ENV↓(s), ENV↓(F))`` es la envolvente
    descendente de esta unión). Un :class:`~.seeds.SeedSet` nuevo con su misma geometría, su
    dominio y sus celdas sin cota, contado de nuevo; las entradas no se modifican. ``ValueError``
    si el mapa no es de la rejilla de las semillas."""
    values = np.asarray(seeds.grid, dtype=np.float64)
    _same_shape("el mapa de fondos", floors.grid, values.shape)
    inside = np.isfinite(floors.grid)
    joined = np.where(np.isfinite(values), values, -np.inf)
    joined = np.where(inside, np.fmax(joined, floors.grid), joined)
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
    la abscisa de sus celdas; 0 si no tiene ninguna), todas en m."""

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


def _corridor_sigma(paths: list[np.ndarray], half: float, geometry: Grid,
                    window: tuple[slice, slice]) -> np.ndarray:
    """La abscisa ``σ`` (m, a lo largo del eje desde su principio; las partes, seguidas) de cada
    celda de ``window`` dentro del corredor, ``NaN`` fuera (A6). Por tramo: la distancia del
    centro al tramo y la proyección ``t`` sobre su recta; dentro si la distancia es ≤ ``half`` y
    ni ``t < 0`` en el primer tramo de un camino ni ``t`` pasa del último (extremos planos,
    perpendiculares al eje; en un vértice interior, la unión redonda de la distancia al tramo).
    Cada celda toma la abscisa del tramo más próximo (a igual distancia, el anterior)."""
    rows = np.arange(window[0].start, window[0].stop, dtype=np.float64)
    cols = np.arange(window[1].start, window[1].stop, dtype=np.float64)
    shape = (rows.size, cols.size)
    best = np.full(shape, np.inf)
    sigma = np.full(shape, np.nan)
    limit = half * half
    walked = 0.0
    for path in paths:
        lengths = np.hypot(*np.diff(path, axis=0).T)
        segments = [i for i in range(lengths.size) if lengths[i] > 0.0]
        for i in segments:
            a, b, length = path[i], path[i + 1], float(lengths[i])
            ux, uy = (b - a) / length
            px = ((geometry.west - a[0]) + (cols + 0.5) * geometry.dx)[None, :]
            py = ((geometry.north - a[1]) - (rows + 0.5) * geometry.dy)[:, None]
            along = px * ux + py * uy
            across = py * ux - px * uy
            clamped = np.clip(along, 0.0, length)
            d2 = across * across + (along - clamped) ** 2
            inside = d2 <= limit
            if i == segments[0]:
                inside &= along >= 0.0
            if i == segments[-1]:
                inside &= along <= length
            better = inside & (d2 < best)
            best[better] = d2[better]
            sigma[better] = (walked + clamped)[better]
            walked += length
    return sigma


def corridor_cells(layer: FeatureLayer, fields: CorridorFields, geometry: Grid) -> CorridorMap:
    """**A6** (RF-014-09, RF-014-10): los corredores de la capa de líneas ``layer`` (sus
    entidades; ``fields`` da su nombre en el proyecto, el campo del ancho, m, y el de la cota fija
    o los de la rasante: cota inicial, m, y pendiente, %, positiva cuando sube en el sentido del
    eje) convertidos en fondos con **extremos planos** en la rejilla ``geometry``
    (:class:`CorridorMap`): dentro, cada celda con el centro a ≤ ancho/2 de un tramo del eje y
    cuya proyección no cae antes de su principio ni después de su final; su cota, la fija o
    ``cota inicial + σ · pendiente / 100`` con ``σ`` la abscisa de su proyección. Su longitud
    medida (máximo menos mínimo de ``σ``) es la del eje con error ≤ 1 celda (error 20), y
    :attr:`CorridorMap.notices` avisa si pasara de la del eje más el ancho. Solo lee; cada
    corredor cuesta su caja, no la rejilla entera.

    Rechazos (``DesignError``, sin suponer nada), en el orden de la capa y, en cada corredor,
    primero su ancho, después su cota y después su eje: una capa que no es de líneas
    (``des.corridor_not_lines``); un campo que la capa no tiene o que no es numérico
    (``des.quarry_layer_field``); un ancho que falta, no es finito o es ≤ 0
    (``des.corridor_width``); una cota, cota inicial o pendiente que falta o no es finita
    (``des.corridor_level_missing``); un eje de longitud cero (``des.corridor_length_zero``); y,
    como dos fondos (RF-014-06), un corredor que pisa celdas de otro anterior
    (``des.floor_overlap``, con los dos y las celdas comunes)."""
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
        if not axis > 0.0:
            raise DesignError("des.corridor_length_zero",
                              obj=f"Corredor {fid} de la capa «{fields.layer}»",
                              field=_GEOMETRY_FIELD, value=round(axis, 2), layer=fields.layer,
                              corridor=fid)
        window = _corridor_window(paths, width / 2.0, geometry)
        sigma = _corridor_sigma(paths, width / 2.0, geometry, window)
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
        found = sigma[inside]
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


def _ceiling_work(seed: np.ndarray, geometry: Grid, slope: SlopeField, metric: Metric,
                  zone: np.ndarray, names: tuple[str, ...], nodata: tuple[int, ...],
                  slope_deg: float) -> Generator[None, None, ConservationCeiling]:
    """Las unidades del techo: la envolvente ascendente de la 013 de ``seed`` con ``slope`` y
    ``metric``; sin ninguna semilla, ``+inf`` en toda la rejilla (no hay techo)."""
    if not np.isfinite(seed).any():
        yield None
        grid = np.full(seed.shape, np.inf)
    elif metric is Metric.EXACT:
        found = yield from _exact_work(seed, geometry, slope, Direction.UP, CEILING_NAME,
                                       CELLS_PER_UNIT, EVALS_PER_UNIT, BLOCK_CELLS, BLOCK_GROUP)
        grid = found.grid
    else:
        found = yield from chamfer_units(seed, geometry, slope, Direction.UP, name=CEILING_NAME)
        grid = found.grid
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
    with np.errstate(invalid="ignore"):
        keep = ~ceiling.zone & np.isfinite(values) & (values > ceiling.grid)
        np.minimum(design, np.fmax(ceiling.grid, values), out=design)
    design[keep] = values[keep]
    design[ceiling.zone] = values[ceiling.zone]
    return design


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
    no se crea sin confirmación expresa con motivo (lo pide quien crea). Solo lee; ``ValueError``
    si las rejillas no son de la forma de ``geometry``."""
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
