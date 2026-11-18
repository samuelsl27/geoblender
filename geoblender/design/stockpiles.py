# SPDX-License-Identifier: GPL-3.0-or-later
"""La detección de acopios: el plano de base robusto y su límite de inclinación (A2, spec 016, T06; RF-016-02,
RF-016-04, RF-016-05, RF-016-07), la huella iterativa, sus avisos y el reparto de las celdas comunes (A3, T07;
RF-016-02, RF-016-04, RF-016-05, RF-016-06) y los candidatos sin marca con la regla de identidad al repetir (A4, T08;
RF-016-08, RF-016-10); plan 016 A2, A3, A4, §5.2.2, §7.1, §7.3; D-3, D-10, D-16, D-17, D-18, D-23. Las demás piezas (las
bases, los espesores y el terreno sin acopios) las añade T09 a este módulo.

**A2.** Sobre la ventana de una marca (una rejilla pequeña del proyecto, en coordenadas absolutas float64), con ``H`` la
huella (al principio, las celdas de la marca):

- :func:`crown_of` — la **corona**: ``H`` dilatado ``crown_outer`` menos ``H`` dilatado ``crown_inner``, con el disco
  exacto de :mod:`design.morphology` (A1).
- :func:`cell_slope_deg` — la **pendiente de la celda** de la corona: ``atan(√(∂z/∂x² + ∂z/∂y²))`` con diferencias
  centradas (de un lado en el borde de la ventana: ``numpy.gradient``). El plan no dice cómo se calcula y no hay otra
  función de pendiente de superficie en ``design``, ``gis`` ni ``reserves``: es esta. Una celda sin dato, o que usa
  una sin dato, sale ``NaN`` y no cuenta como llana.
- :func:`fit_plane` — el plano ``z = z₀ + b·(x − x₀) + c·(y − y₀)`` de las celdas dadas por mínimos cuadrados
  (``numpy.linalg.lstsq``) y, ``rounds`` veces, se descartan las celdas cuyo residuo se aparta de la **mediana** de los
  residuos de las que quedan más que ``max_residual_m`` (``>``) y se vuelve a ajustar (un descarte que dejaría menos de
  tres celdas, o que no determina un plano, no se hace; y sin descarte se acaba antes). Si la inclinación del ajuste
  pasa de ``tilt_max_deg`` (``>``), se deja en ella conservando el **azimut** y el nivel ``pivot_z`` se apoya en el
  **cuantil** ``quantile`` (interpolación lineal, el ``numpy.quantile`` por defecto) de
  ``z − b'·(x − pivot_x) − c'·(y − pivot_y)`` en las celdas del último ajuste (las que quedaron tras descartar las
  atípicas), con la nota de RF-016-07.
- :func:`base_plane` — todo A2 sobre una ventana: la corona, su rechazo (RF-016-04), las celdas llanas (pendiente menor
  que ``crown_slope_deg`` si suman ``crown_flat_min_m2`` m² y, si no, toda la corona, con la nota de RF-016-05) y el
  ajuste.

**El plano.** Se guarda con un pivote ``(x₀, y₀)`` (la media de las celdas de la corona) y no como ``a + b·x + c·y``,
y el ajuste se hace en coordenadas desde el pivote (:attr:`BasePlane.intercept` da la ``a`` absoluta): con nortes de
4,4 Mm la forma absoluta resta números de 10⁵ para dar una cota de 10² (medido con 400 celdas de 1 m: 3·10⁻¹¹ m de
error en las celdas con coordenadas absolutas y 10⁻¹³ m con el pivote; nada a 10⁻⁶ m, pero sí a la tolerancia de las
cuentas a mano). El **azimut** es el de la **máxima pendiente hacia donde sube el plano**, desde el norte de
cuadrícula en sentido horario (``atan2(b, c)``, en [0°, 360°); el ``atan2(c, b)`` del plan es el mismo rumbo medido
desde el este en sentido antihorario), y es 0° si el plano es horizontal (no hay máxima pendiente).

**Avisos y rechazos.** A2 no conoce el nombre de la marca ni el lugar: da su ``code`` de ``design.messages`` y sus
valores en un :class:`SiteMessage` que se completa con :meth:`SiteMessage.notice` (la marca y el lugar). Una **nota**
va en :attr:`BasePlane.notes` (el acopio la lleva); un **rechazo** (RF-016-04: una corona sin celdas o sin terreno,
que no ajusta un plano) es la excepción :class:`StockpileRejected`, con su mensaje: el acopio no se registra y se
informa en el resumen (``Notice.severity`` no admite un error), sin parar a las otras marcas.

**A3.** Sobre la misma ventana, con la **marca** ``M`` (una máscara de la rejilla) y su **ampliada** ``M⁺`` (la marca
dilatada ``margin_m`` con el disco de A1), y ``u`` el umbral de la huella de la 011 (``res.anthropic_presence_m``, que
la detección lee por su clave y se pasa en ``FootprintParams.threshold_m``: la huella de un acopio y la unidad antrópica
de la 011 tienen las mismas celdas solo si leen el mismo):

- :func:`footprint_above` — **una vuelta de A3 sobre un plano ya dado** (o sobre una superficie de base propia,
  RF-016-03): de las celdas de ``M⁺`` con ``z − base > u`` (estrictamente: un valor justo en el umbral no cuenta; una
  celda sin dato no está por encima de nada), la **zona conexa mayor que toca la marca** (4-conexión,
  :func:`design.grids.label_components`; a igual tamaño, la que tiene la primera celda en el orden de lectura) con los
  **huecos interiores rellenos** (D-18: :func:`design.morphology.fill_holes`; un hueco cuenta en el área de la huella,
  y en el volumen solo donde pasa del umbral). Rechaza el acopio (:class:`StockpileRejected`, RF-016-04) si ninguna zona
  toca la marca (``des.stockpile_no_cells``: la marca no da ninguna celda sobre el umbral) o si en la huella falta
  terreno (``des.stockpile_no_terrain``: una celda de un hueco rellenado sin dato, en la superficie o en la base;
  con cuántas son y el lugar de la primera en el orden de lectura). Da las **notas** de RF-016-05: ``des.stockpile_
  footprint_at_edge`` si una celda de la huella tiene un vecino 4 que no es de la marca ampliada ni de la huella (el
  borde de la ventana cuenta como fuera), con el lugar de la primera en el orden de lectura, y
  ``des.stockpile_several_zones`` si otras zonas que tocan la marca quedan fuera de la huella (una isla dentro de un
  hueco rellenado no cuenta), con cuántas zonas hay y en torno al centro de la mayor de las demás.
- :func:`grow_footprint` — **A2 y A3 en vueltas**: ``turns`` veces, el plano de A2 sobre la huella de la vuelta
  anterior (la **marca** en la primera: «al principio, las celdas de la marca») y la huella de ese plano
  (:func:`footprint_above`), hasta que la huella no cambie (**convergida**: el plano es el de la huella final). Si se
  acaban las vueltas con la huella aún cambiando, se queda con el último plano y la última huella y lo anota
  (``des.stockpile_not_converged``, en torno al centro de las celdas que cambiaron en la última vuelta). Mide el
  **volumen** (:func:`footprint_volume`): ``math.fsum((z − plano)·área de celda)`` en las celdas de la huella con
  ``z − plano > u``, como la 011. Las notas, en este orden: llega al borde, más de una zona, corona con pocas celdas
  llanas (A2), plano limitado (A2) y no se estabiliza; las del plano y de la huella son las de la **última** vuelta.
- :func:`share_cells` — el **reparto** de las celdas comunes de las huellas de varias marcas (RF-016-06, D-16): cada
  celda en más de una huella va a la marca que la contiene si la contiene una sola de las que la reclaman y, si la
  contienen varias o ninguna, a la **más próxima** de entre las que la reclaman: por la distancia exacta al conjunto de
  celdas de la marca (:func:`design.grids.nearest_value_steps`, enteros, sobre la ventana de las marcas que se tocan),
  que para la marca que contiene la celda es 0 (así que una sola regla da las dos); a igual distancia, la primera de la
  lista. Da las huellas nuevas (con su volumen y su área recalculados sobre lo que les queda y su propio plano) y, por
  cada pareja de marcas con celdas comunes, un :class:`SharedCells` con las dos marcas, el área repartida y el lugar (el
  centro de las celdas comunes): el aviso de RF-016-06 (``des.stockpile_shared_cells``). Las máscaras de todas las marcas
  son de **la misma ventana** (quien tiene una ventana por marca calcula las que se tocan en una ventana común).

**A4.** Los candidatos **sin marca** (RF-016-08, D-10), sobre la superficie ``z`` de la rejilla entera:

- :func:`candidates_steps` (y :func:`find_candidates`, de una vez) — en el **perímetro de actuación**, las celdas con
  ``z − apertura(z, ⌀ = open_diameter_m) > min_height_m`` (estrictamente: :func:`design.morphology.opening_steps` con
  el disco exacto de A1; una celda sin dato no cuenta), sus componentes 4-conexas (:func:`design.grids.label_components`)
  y el **filtro** de cada zona: no es candidata si **contiene o se solapa con** alguna celda de ``marked`` (las celdas
  de las marcas: quien llama da la unión de sus huellas, y de las propias marcas si alguna se rechazó, para que no
  vuelva como candidata: decisión de la sesión principal sobre «sin marca», 18/11/2026), si su área (celdas por el área de
  celda, m²) queda fuera de ``[min_area_m2, max_area_m2]`` (**ambos incluidos**). A las que pasan, A2 y A3 **como si la
  zona fuera una marca** (:func:`grow_footprint`, con el margen de ``footprint``) en **su ventana de trabajo** (A0:
  :func:`mark_window`, la caja de la zona ampliada por el margen más la corona y dos celdas, recortada a la rejilla: lo
  mismo que sobre la rejilla entera, sin pagarla por candidato). **No sale ningún candidato sin filtrar:** lo que el
  filtro descarta **solo se cuenta** (``on_marks``, ``too_small``, ``too_large``; nunca una lista), y una zona que pasa
  los filtros pero cuyo plano o huella no se pueden formar (:class:`StockpileRejected`: A2 y A3 rechazan una marca así)
  se cuenta en ``rejected`` y no sale. Los contadores no se solapan: ``zones`` = candidatos + ``on_marks`` +
  ``too_small`` + ``too_large`` + ``rejected`` (una zona con marca no es «pequeña» aunque lo sea). Salen en el orden de
  la primera celda de su zona recorriendo la rejilla fila a fila. Los candidatos entre sí y con las marcas **no se
  reparten** celdas (la spec no lo pide): un candidato cuya huella llegue a la de una marca la solapa. **Los bordes de
  la rejilla:** lo de fuera no cuenta en la apertura (T05, decisión 4: el disco se recorta), así que un montón que
  **toca** el borde de la rejilla puede quedar entero bajo el disco recortado y no dar zona (o solo trozos), y cerca del
  borde la apertura se aparta del plano hasta unos decímetros; quien lo quiera de otro modo rellena ``z`` antes de llamar.
- :func:`carry_decisions` — la **regla de identidad al repetir** (RF-016-10, D-23): un candidato nuevo conserva la
  decisión (convertido o descartado, con su motivo) de uno anterior si sus huellas comparten **más de la mitad del área
  de cada una** (estrictamente: justo la mitad no basta; con las celdas de una misma rejilla, las celdas valen
  áreas iguales y se cuentan con enteros). Una decisión se conserva **una sola vez**: ante varias parejas gana la que
  más celdas comparte (a igualdad, el candidato nuevo y después el anterior de índice menor). Función pura sobre las
  celdas de cada huella en la rejilla entera (:attr:`Candidate.cells`).

Ninguna entrada se modifica. Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .grids import label_components, label_components_steps, nearest_value_steps
from .messages import lookup
from .morphology import dilate, fill_holes, opening_steps
from .params import STOCKPILE_RANGES, StockpileParam
from .pipeline import forward
from .platform import work_window
from .preview import Notice
from .seeds import pace_progress

__all__ = [
    "BasePlane",
    "Candidate",
    "CandidateParams",
    "Candidates",
    "Claim",
    "Footprint",
    "FootprintCut",
    "FootprintParams",
    "PlaneParams",
    "Shared",
    "SharedCells",
    "SiteMessage",
    "StockpileRejected",
    "base_plane",
    "candidates_steps",
    "carry_decisions",
    "cell_slope_deg",
    "crown_of",
    "find_candidates",
    "fit_plane",
    "footprint_above",
    "footprint_volume",
    "grow_footprint",
    "mark_window",
    "share_cells",
    "share_cells_steps",
    "window_grid",
]

_NO_CROWN_CELLS = "des.stockpile_no_crown_cells"
_NO_TERRAIN_CROWN = "des.stockpile_no_terrain_crown"
_CROWN_FEW_FLAT = "des.stockpile_crown_few_flat"
_TILT_LIMITED = "des.stockpile_tilt_limited"
_NO_CELLS = "des.stockpile_no_cells"
_NO_TERRAIN = "des.stockpile_no_terrain"
_AT_EDGE = "des.stockpile_footprint_at_edge"
_SEVERAL_ZONES = "des.stockpile_several_zones"
_NOT_CONVERGED = "des.stockpile_not_converged"
_SHARED_CELLS = "des.stockpile_shared_cells"
_MIN_CELLS = 3
"""Las celdas que hacen falta para determinar un plano."""


@dataclass(frozen=True, slots=True)
class SiteMessage:
    """Un aviso o una nota de un acopio que aún no sabe su marca ni su lugar: el ``code`` de ``design.messages`` y sus
    ``values`` (sin escribir, ni ``mark``, ``x`` e ``y`` salvo que el mensaje se sitúe a sí mismo: el primer lugar sin
    dato de ``des.stockpile_no_terrain_crown``). :meth:`notice` lo completa."""

    code: str
    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        lookup(self.code)  # un código que no está en el catálogo es un error del programa
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def notice(self, mark: str, x: float, y: float) -> Notice:
        """El aviso para la marca ``mark``, en torno al lugar ``(x, y)`` (m, absolutas): los valores del propio mensaje
        mandan sobre ``mark``, ``x`` e ``y``."""
        return Notice(self.code, {"mark": mark, "x": x, "y": y, **self.values})


class StockpileRejected(Exception):
    """El acopio se rechaza y no se registra (RF-016-04): ``message`` es el :class:`SiteMessage` con su caso. No es un
    error del usuario que pare la operación: quien recorre las marcas lo recoge, lo añade al resumen y sigue."""

    def __init__(self, code: str, **values: object) -> None:
        self.message = SiteMessage(code, values)
        super().__init__(f"{code}: {dict(self.message.values)}")

    def with_values(self, **more: object) -> StockpileRejected:
        """El mismo rechazo con más valores (los de quien sabe lo que la función de abajo no sabe)."""
        return StockpileRejected(self.message.code, **{**self.message.values, **more})


def _check_value(name: str, value: object, *, integer: bool = False) -> float | int:
    """``value`` si está en el rango de ``name`` en ``design.params.STOCKPILE_RANGES`` (la única fuente de los límites
    de los umbrales de la detección) y, si ``integer``, es un entero; ``ValueError`` que nombra el parámetro si no."""
    allowed = STOCKPILE_RANGES[name]
    if integer and (isinstance(value, bool) or not isinstance(value, numbers.Integral)):
        raise ValueError(f"«{name}» es un número entero, no {value!r}")
    if not allowed.contains(value):
        raise ValueError(f"«{name}» no admite {value!r}: va de {allowed.text()}")
    return int(value) if integer else float(value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PlaneParams:
    """Los umbrales de A2 (plan 016 §5.2.2: la familia ``stockpile``), con los nombres de sus parámetros: la separación
    interior y exterior de la corona (m), la pendiente de corona (°), el área llana mínima (m²), el residuo máximo (m),
    las vueltas del ajuste, la inclinación máxima (°) y el cuantil de apoyo (—; los dos últimos, HIPÓTESIS). **Sin valor
    por defecto**: los pone quien resuelve los parámetros de la detección, con su tipo y procedencia. Un valor fuera de
    su rango (``STOCKPILE_RANGES``) es un ``ValueError`` que lo nombra."""

    crown_inner_m: float
    crown_outer_m: float
    crown_slope_deg: float
    crown_flat_min_m2: float
    max_residual_m: float
    fit_rounds: int
    tilt_max_deg: float
    support_quantile: float

    def __post_init__(self) -> None:
        for param in (StockpileParam.CROWN_INNER, StockpileParam.CROWN_OUTER, StockpileParam.CROWN_SLOPE,
                      StockpileParam.CROWN_FLAT_MIN, StockpileParam.MAX_RESIDUAL, StockpileParam.TILT_MAX,
                      StockpileParam.SUPPORT_QUANTILE):
            object.__setattr__(self, param.value, _check_value(param.value, getattr(self, param.value)))
        object.__setattr__(self, StockpileParam.FIT_ROUNDS.value,
                           _check_value(StockpileParam.FIT_ROUNDS.value, self.fit_rounds, integer=True))


@dataclass(frozen=True, slots=True, eq=False)
class BasePlane:
    """El plano de base de un acopio (A2): ``z = pivot_z + b·(x − pivot_x) + c·(y − pivot_y)`` con el pivote
    ``(pivot_x, pivot_y)`` (la media de las celdas de la corona; coordenadas absolutas, m), la cota ``pivot_z`` en él,
    la pendiente al este (``east_slope``, ``b``, m/m) y al norte (``north_slope``, ``c``). Los nombres ``x0``, ``y0`` y
    ``z0`` son los del GeoOrigin para la regla ARQ-14 (``tools/gbtools/rules/georef.py``): por eso no se usan.

    ``fitted_tilt_deg`` es la inclinación del ajuste, antes de limitarla; ``azimuth_deg``, el azimut de su máxima
    pendiente (hacia donde sube, desde el norte, en sentido horario; 0° si es horizontal), que la limitación conserva;
    ``limited``, si pasó de la inclinación máxima y se dejó en ella. ``crown`` son las celdas que se dieron al ajuste
    (las llanas de la corona o toda ella), ``kept`` las del último (sin las atípicas descartadas; ambas, máscaras de la
    forma de la ventana) y ``notes`` las notas del acopio, en el orden de A2 (la corona, después la inclinación)."""

    pivot_x: float
    pivot_y: float
    pivot_z: float
    east_slope: float
    north_slope: float
    fitted_tilt_deg: float
    azimuth_deg: float
    limited: bool
    crown: np.ndarray
    kept: np.ndarray
    notes: tuple[SiteMessage, ...] = ()

    @property
    def tilt_deg(self) -> float:
        """La inclinación del plano (°), ``atan(√(b² + c²))``: la limitada, si ``limited``."""
        return math.degrees(math.atan(math.hypot(self.east_slope, self.north_slope)))

    @property
    def slope_percent(self) -> float:
        """La pendiente del plano (%), ``100·√(b² + c²)``."""
        return 100.0 * math.hypot(self.east_slope, self.north_slope)

    @property
    def intercept(self) -> float:
        """El ``a`` de ``z = a + b·x + c·y`` en coordenadas absolutas (m): ``pivot_z − b·pivot_x − c·pivot_y``."""
        return self.pivot_z - self.east_slope * self.pivot_x - self.north_slope * self.pivot_y

    def at(self, x: object, y: object) -> np.ndarray:
        """La cota del plano en ``(x, y)`` (m, absolutas; escalares o arrays), ``pivot_z + b·(x − pivot_x) +
        c·(y − pivot_y)``."""
        return (self.pivot_z + self.east_slope * (np.asarray(x, dtype=np.float64) - self.pivot_x)
                + self.north_slope * (np.asarray(y, dtype=np.float64) - self.pivot_y))

    def values(self, grid: Grid) -> np.ndarray:
        """La cota del plano en los centros de ``grid`` (m, float64, nueva)."""
        return self.at(*grid.centers())


def _mask(found: object, shape: tuple[int, ...] | None, what: str) -> np.ndarray:
    """``found`` como máscara booleana de 2 dimensiones (de la forma ``shape``, si se da); ``ValueError`` si no."""
    array = np.asarray(found)
    if array.ndim != 2 or array.dtype != np.bool_:
        raise ValueError(f"{what} es una máscara booleana de 2 dimensiones, no un array {array.dtype} de "
                         f"{array.ndim}")
    if shape is not None and array.shape != shape:
        raise ValueError(f"{what} tiene {array.shape} celdas y se esperaban {shape}")
    return array


def _step(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)) \
            or not math.isfinite(float(value)) or value <= 0:
        raise ValueError(f"{what} es un número finito mayor que 0, no {value!r}")
    return float(value)


def crown_of(footprint: np.ndarray, cell: float, *, inner_m: float, outer_m: float) -> np.ndarray:
    """La corona de ``footprint`` (A2, RF-016-02): las celdas de la huella dilatada ``outer_m`` m menos las de la
    dilatada ``inner_m`` m (el disco exacto de :func:`design.morphology.dilate` sobre celdas de ``cell`` m), una máscara
    nueva sin la huella. Sin huella, o con ``inner_m ≥ outer_m``, no tiene celdas (A2 rechaza el acopio)."""
    mask = _mask(footprint, None, "la huella")
    return dilate(mask, outer_m, cell) & ~dilate(mask, inner_m, cell)


def cell_slope_deg(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """La pendiente de cada celda de ``z`` (°, float64, nueva): ``atan(√(∂z/∂x² + ∂z/∂y²))`` con la diferencia centrada
    entre las dos celdas vecinas y, en el borde, la de un lado (``numpy.gradient``), con los pasos ``dx`` y ``dy`` (m).
    Una celda sin dato (``NaN``), o vecina de una sin dato, sale ``NaN``. ``ValueError`` si ``z`` no es de 2 dimensiones
    con al menos 2 filas y 2 columnas o un paso no es un número finito mayor que 0."""
    found = np.asarray(z, dtype=np.float64)
    if found.ndim != 2 or min(found.shape) < 2:
        raise ValueError(f"la pendiente pide una rejilla de al menos 2 × 2 celdas, no {found.shape}")
    step_x, step_y = _step(dx, "el paso en X"), _step(dy, "el paso en Y")
    with np.errstate(invalid="ignore"):
        d_row, d_col = np.gradient(found, step_y, step_x)
        slope = np.degrees(np.arctan(np.hypot(d_col, d_row)))
    slope[~np.isfinite(found)] = np.nan
    return slope


def fit_plane(z: np.ndarray, crown: np.ndarray, x: np.ndarray, y: np.ndarray, *, rounds: int, max_residual_m: float,
              tilt_max_deg: float, quantile: float) -> BasePlane:
    """El plano de base robusto de las celdas de ``crown`` (A2, RF-016-02, RF-016-07), de ``z`` (la superficie, m) en
    las coordenadas absolutas ``x`` e ``y`` (m, float64) de sus celdas, todo de la misma forma: ``rounds`` vueltas de
    descarte por el residuo (``max_residual_m``) y, si pasa de ``tilt_max_deg``, la inclinación limitada con el nivel
    en el cuantil ``quantile`` (ver el módulo). Los límites son los de ``STOCKPILE_RANGES``.

    ``ValueError`` si un valor está fuera de rango, las formas no cuadran, ``crown`` no es una máscara o una de sus
    celdas no tiene dato (eso lo rechaza antes :func:`base_plane`, que sabe la marca). :class:`StockpileRejected`
    (``des.stockpile_no_crown_cells``, sin los valores del anillo) si las celdas no determinan un plano: menos de tres
    o alineadas."""
    rounds = int(_check_value(StockpileParam.FIT_ROUNDS.value, rounds, integer=True))
    max_residual_m = float(_check_value(StockpileParam.MAX_RESIDUAL.value, max_residual_m))
    tilt_max_deg = float(_check_value(StockpileParam.TILT_MAX.value, tilt_max_deg))
    quantile = float(_check_value(StockpileParam.SUPPORT_QUANTILE.value, quantile))
    heights, easting, northing = (np.asarray(array, dtype=np.float64) for array in (z, x, y))
    if heights.ndim != 2 or easting.shape != heights.shape or northing.shape != heights.shape:
        raise ValueError("la superficie y las coordenadas son rejillas de 2 dimensiones de la misma forma")
    selected = _mask(crown, heights.shape, "la corona")
    index = np.flatnonzero(selected.ravel())
    level, east, north = (array.ravel()[index] for array in (heights, easting, northing))
    if not (np.isfinite(level).all() and np.isfinite(east).all() and np.isfinite(north).all()):
        raise ValueError("las celdas de la corona tienen que tener dato y coordenadas finitas")
    if index.size < _MIN_CELLS:
        raise StockpileRejected(_NO_CROWN_CELLS)
    pivot_x, pivot_y = float(east.mean()), float(north.mean())
    design = np.column_stack((np.ones(index.size), east - pivot_x, north - pivot_y))

    def solve(keep: np.ndarray) -> np.ndarray | None:
        coefficients, _, rank, _ = np.linalg.lstsq(design[keep], level[keep], rcond=None)
        return coefficients if rank == _MIN_CELLS else None

    kept = np.ones(index.size, dtype=bool)
    found = solve(kept)
    if found is None:
        raise StockpileRejected(_NO_CROWN_CELLS)
    coefficients = found
    for _ in range(rounds):
        residual = level[kept] - design[kept] @ coefficients
        stays = np.abs(residual - np.median(residual)) <= max_residual_m
        if stays.all():
            break
        trial = kept.copy()
        trial[np.flatnonzero(kept)[~stays]] = False
        if trial.sum() < _MIN_CELLS:
            break
        refit = solve(trial)
        if refit is None:
            break
        kept, coefficients = trial, refit
    pivot_z, b, c = (float(value) for value in coefficients)
    gradient = math.hypot(b, c)
    fitted = math.degrees(math.atan(gradient))
    azimuth = math.degrees(math.atan2(b, c)) % 360.0 if gradient > 0.0 else 0.0
    azimuth = 0.0 if azimuth >= 360.0 else azimuth
    limited = fitted > tilt_max_deg
    notes: tuple[SiteMessage, ...] = ()
    if limited:
        scale = math.tan(math.radians(tilt_max_deg)) / gradient
        b, c = b * scale, c * scale
        pivot_z = float(np.quantile(level[kept] - b * (east[kept] - pivot_x) - c * (north[kept] - pivot_y), quantile))
        notes = (SiteMessage(_TILT_LIMITED, {"fitted": fitted, "limit": tilt_max_deg, "quantile": quantile}),)
    used = np.zeros(selected.size, dtype=bool)
    used[index[kept]] = True
    return BasePlane(pivot_x, pivot_y, pivot_z, b, c, fitted, azimuth, limited, selected.copy(),
                     used.reshape(selected.shape), notes)


def base_plane(z: np.ndarray, footprint: np.ndarray, grid: Grid, params: PlaneParams) -> BasePlane:
    """El plano de base de la huella ``footprint`` de la ventana ``grid`` sobre la superficie ``z`` (A2 entero,
    RF-016-02, RF-016-04, RF-016-05, RF-016-07): la corona de ``footprint`` (:func:`crown_of`), las celdas llanas
    (pendiente menor que ``crown_slope_deg`` si suman ``crown_flat_min_m2`` m²; si no, toda la corona y la nota
    ``des.stockpile_crown_few_flat`` con el área llana, la pendiente y el área mínima) y el ajuste (:func:`fit_plane`;
    con la nota de la inclinación, si la limita), en coordenadas absolutas float64 desde ``grid.west`` y
    ``grid.north``. La huella solo da la corona: A2 no lee ``z`` en ella (lo hace A3).

    :class:`StockpileRejected` si la corona no tiene celdas con las que ajustar un plano
    (``des.stockpile_no_crown_cells``, con ``inner`` y ``outer``) o alguna no tiene terreno
    (``des.stockpile_no_terrain_crown``, con ``cells`` y el ``x`` y el ``y`` de la primera en el orden de lectura).
    ``ValueError`` si la rejilla no tiene celdas cuadradas o ``z`` y ``footprint`` no son de su forma."""
    if not isinstance(params, PlaneParams):
        raise TypeError(f"los parámetros de A2 son PlaneParams, no {params!r}")
    if grid.dx != grid.dy:
        raise ValueError(f"la rejilla de los acopios es la del proyecto, de celdas cuadradas, no {grid.dx} × {grid.dy}")
    heights = np.asarray(z, dtype=np.float64)
    if heights.shape != grid.shape:
        raise ValueError(f"la superficie tiene {heights.shape} celdas y la ventana {grid.shape}")
    mask = _mask(footprint, grid.shape, "la huella")
    ring = {"inner": params.crown_inner_m, "outer": params.crown_outer_m}
    crown = crown_of(mask, grid.dx, inner_m=params.crown_inner_m, outer_m=params.crown_outer_m)
    if not crown.any():
        raise StockpileRejected(_NO_CROWN_CELLS, **ring)
    x, y = grid.centers()
    missing = crown & ~np.isfinite(heights)
    if missing.any():
        row, col = np.argwhere(missing)[0]
        raise StockpileRejected(_NO_TERRAIN_CROWN, cells=int(missing.sum()), x=float(x[row, col]),
                                y=float(y[row, col]))
    flat = crown & (cell_slope_deg(heights, grid.dx, grid.dy) < params.crown_slope_deg)
    flat_area = float(flat.sum()) * grid.cell_area
    notes: tuple[SiteMessage, ...] = ()
    chosen = flat
    if flat_area < params.crown_flat_min_m2:
        chosen = crown
        notes = (SiteMessage(_CROWN_FEW_FLAT, {"area": flat_area, "slope": params.crown_slope_deg,
                                               "minimum": params.crown_flat_min_m2}),)
    try:
        plane = fit_plane(heights, chosen, x, y, rounds=params.fit_rounds, max_residual_m=params.max_residual_m,
                          tilt_max_deg=params.tilt_max_deg, quantile=params.support_quantile)
    except StockpileRejected as error:
        if error.message.code == _NO_CROWN_CELLS:
            raise error.with_values(**ring) from None
        raise
    return replace(plane, notes=notes + plane.notes)


# --- A3: la huella ---------------------------------------------------------------------------------------------------


def _threshold(value: object) -> float:
    """El umbral de la huella (m): un número real finito no negativo; ``ValueError`` que lo nombra si no. Lo lee la
    detección de ``res.anthropic_presence_m`` (la 011, [0; 10] m): su rango lo comprueba ``core.params``."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(float(value)) \
            or value < 0:  # type: ignore[operator]
        raise ValueError(f"«threshold_m» es un número finito no negativo, no {value!r}")
    return float(value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class FootprintParams:
    """Los umbrales de A3 (plan 016 §5.2.2, ``stockpile``): los de A2 (``plane``), el margen de la marca ampliada
    (``margin_m``, m), las vueltas (``turns``) y el umbral de la huella (``threshold_m``, m: el
    ``res.anthropic_presence_m`` de la 011, que la detección lee por su clave). **Sin valor por defecto**: los pone
    quien resuelve los parámetros. Un valor fuera de su rango (``STOCKPILE_RANGES``; el umbral, finito y no negativo) es
    un ``ValueError`` que lo nombra. El margen de cada marca (el campo ``margen`` de la capa) se cambia con
    ``dataclasses.replace``."""

    plane: PlaneParams
    margin_m: float
    turns: int
    threshold_m: float

    def __post_init__(self) -> None:
        if not isinstance(self.plane, PlaneParams):
            raise TypeError(f"los umbrales de A2 son PlaneParams, no {self.plane!r}")
        object.__setattr__(self, StockpileParam.MARGIN.value, _check_value(StockpileParam.MARGIN.value,
                                                                           self.margin_m))
        object.__setattr__(self, StockpileParam.TURNS.value,
                           _check_value(StockpileParam.TURNS.value, self.turns, integer=True))
        object.__setattr__(self, "threshold_m", _threshold(self.threshold_m))


@dataclass(frozen=True, slots=True, eq=False)
class FootprintCut:
    """La huella que corta una superficie de base de la superficie (:func:`footprint_above`): ``mask`` (las celdas de
    la zona elegida con sus huecos rellenos), ``zones`` (las zonas conexas que tocan la marca y no quedaron dentro de la
    huella: la elegida y las demás) y las ``notes`` de RF-016-05 (llega al borde, más de una zona), en ese orden."""

    mask: np.ndarray
    zones: int
    notes: tuple[SiteMessage, ...]


@dataclass(frozen=True, slots=True, eq=False)
class Footprint:
    """La huella de un acopio con su volumen (A3): ``mask`` (las celdas de la huella, con sus huecos), ``base`` (la
    superficie de base en toda la ventana, m: el plano evaluado en los centros de celda o la superficie de base propia),
    ``plane`` (el :class:`BasePlane` con que se formó, o ``None`` si la base es propia, RF-016-03), ``volume_m3`` (``fsum``
    de ``(z − base)·área de celda`` donde ``z − base`` pasa del umbral), ``area_m2`` (el área de todas las celdas de la
    huella, huecos incluidos), ``turns`` (las vueltas que se hicieron), ``converged`` (si la huella dejó de cambiar) y
    las ``notes`` del acopio, en el orden documentado en el módulo."""

    mask: np.ndarray
    base: np.ndarray
    plane: BasePlane | None
    volume_m3: float
    area_m2: float
    turns: int
    converged: bool
    notes: tuple[SiteMessage, ...] = ()


def _centre(mask: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """El centro (la media de los centros de celda, m absolutos) de las celdas de ``mask``."""
    return float(x[mask].mean()), float(y[mask].mean())


def footprint_above(z: np.ndarray, base: np.ndarray, mark: np.ndarray, enlarged: np.ndarray, grid: Grid,
                    threshold_m: float) -> FootprintCut:
    """La huella de ``mark`` sobre la superficie de base ``base`` (A3, RF-016-02, RF-016-04, RF-016-05; con una base
    propia, RF-016-03): la zona conexa mayor que toca la marca de las celdas de ``enlarged`` (la marca ampliada por su
    margen) con ``z − base > threshold_m``, con sus huecos interiores rellenos, y sus notas (ver el módulo). Todo, de la
    forma de ``grid`` (``mark`` y ``enlarged``, máscaras booleanas).

    :class:`StockpileRejected` si ninguna zona toca la marca (``des.stockpile_no_cells``, con el umbral) o si en la huella
    falta terreno (``des.stockpile_no_terrain``, con cuántas celdas y el lugar absoluto de la primera). ``ValueError`` si
    las formas no cuadran, una máscara no es booleana o el umbral no es válido. Ninguna entrada se modifica."""
    heights, ground = (np.asarray(array, dtype=np.float64) for array in (z, base))
    if heights.shape != grid.shape or ground.shape != grid.shape:
        raise ValueError(f"la superficie ({heights.shape}), la base ({ground.shape}) y la ventana ({grid.shape}) "
                         "tienen que ser de la misma forma")
    marked = _mask(mark, grid.shape, "la marca")
    region = _mask(enlarged, grid.shape, "la marca ampliada")
    limit = _threshold(threshold_m)
    with np.errstate(invalid="ignore"):
        above = region & ((heights - ground) > limit)
    labels = label_components(above)
    touched = np.unique(labels.grid[marked])
    touched = touched[touched > 0]
    if touched.size == 0:
        raise StockpileRejected(_NO_CELLS, threshold=limit)
    chosen = int(touched[int(np.argmax(labels.sizes[touched - 1]))])  # a igual tamaño, la primera en leerse
    footprint = fill_holes(labels.grid == chosen)
    x, y = grid.centers()
    missing = footprint & ~(np.isfinite(heights) & np.isfinite(ground))
    if missing.any():
        row, col = np.argwhere(missing)[0]
        raise StockpileRejected(_NO_TERRAIN, cells=int(missing.sum()), x=float(x[row, col]), y=float(y[row, col]))
    notes: list[SiteMessage] = []
    reach = np.pad(region | footprint, 1)
    inside = (reach[1:-1, 1:-1] & reach[:-2, 1:-1] & reach[2:, 1:-1] & reach[1:-1, :-2] & reach[1:-1, 2:])
    edge = footprint & ~inside
    if edge.any():
        row, col = np.argwhere(edge)[0]
        notes.append(SiteMessage(_AT_EDGE, {"x": float(x[row, col]), "y": float(y[row, col])}))
    outside = labels.grid[(labels.grid > 0) & ~footprint]
    left = np.bincount(outside, minlength=labels.count + 1)
    others = [int(label) for label in touched if label != chosen and left[label] > 0]
    if others:
        biggest = others[int(np.argmax([left[label] for label in others]))]
        place = _centre((labels.grid == biggest) & ~footprint, x, y)
        notes.append(SiteMessage(_SEVERAL_ZONES, {"zones": 1 + len(others), "x": place[0], "y": place[1]}))
    return FootprintCut(footprint, 1 + len(others), tuple(notes))


def footprint_volume(z: np.ndarray, base: np.ndarray, mask: np.ndarray, cell_area: float,
                     threshold_m: float) -> float:
    """El volumen de una huella (m³, A3, RF-016-02): ``math.fsum((z − base)·cell_area)`` en las celdas de ``mask`` con
    ``z − base > threshold_m``, como la 011 (los huecos de la huella cuentan en su área, no en el volumen).
    ``ValueError`` si las formas no cuadran, ``mask`` no es booleana o el área o el umbral no son válidos."""
    heights, ground = (np.asarray(array, dtype=np.float64) for array in (z, base))
    if heights.shape != ground.shape:
        raise ValueError(f"la superficie ({heights.shape}) y la base ({ground.shape}) son de la misma forma")
    counted = _mask(mask, heights.shape, "la huella")
    area = _step(cell_area, "el área de la celda")
    limit = _threshold(threshold_m)
    with np.errstate(invalid="ignore"):
        excess = heights - ground
        counted = counted & (excess > limit)
    return math.fsum((excess[counted] * area).tolist())


def grow_footprint(z: np.ndarray, mark: np.ndarray, grid: Grid, params: FootprintParams) -> Footprint:
    """El acopio de la marca ``mark`` en la ventana ``grid`` sobre la superficie ``z`` (A2 y A3 enteros, RF-016-02,
    RF-016-04, RF-016-05, RF-016-07): hasta ``params.turns`` vueltas del plano de A2 sobre la huella de la vuelta anterior
    (la marca, en la primera) y de la huella de ese plano (:func:`footprint_above`), hasta que la huella no cambie; el
    volumen sobre el plano (:func:`footprint_volume`) y las notas (ver el módulo).

    :class:`StockpileRejected` con el caso de A2 (la corona sin celdas o sin terreno) o de A3 (la marca sin ninguna
    celda sobre el umbral o sin terreno en la huella): la marca no da acopio. ``ValueError`` si la rejilla no tiene celdas
    cuadradas o ``z`` y ``mark`` no son de su forma; ``TypeError`` si ``params`` no son :class:`FootprintParams`.
    Ninguna entrada se modifica."""
    if not isinstance(params, FootprintParams):
        raise TypeError(f"los parámetros de A3 son FootprintParams, no {params!r}")
    if grid.dx != grid.dy:
        raise ValueError(f"la rejilla de los acopios es la del proyecto, de celdas cuadradas, no {grid.dx} × {grid.dy}")
    heights = np.asarray(z, dtype=np.float64)
    if heights.shape != grid.shape:
        raise ValueError(f"la superficie tiene {heights.shape} celdas y la ventana {grid.shape}")
    marked = _mask(mark, grid.shape, "la marca")
    enlarged = dilate(marked, params.margin_m, grid.dx)
    current = previous = marked
    converged = False
    plane: BasePlane | None = None
    ground: np.ndarray | None = None
    cut: FootprintCut | None = None
    turns = 0
    for turns in range(1, params.turns + 1):
        plane = base_plane(heights, current, grid, params.plane)
        ground = plane.values(grid)
        cut = footprint_above(heights, ground, marked, enlarged, grid, params.threshold_m)
        if np.array_equal(cut.mask, current):
            converged = True
            break
        previous, current = current, cut.mask
    assert plane is not None and ground is not None and cut is not None  # params.turns ≥ 1
    notes = cut.notes + plane.notes
    if not converged:
        x, y = grid.centers()
        place = _centre(cut.mask ^ previous, x, y)
        notes += (SiteMessage(_NOT_CONVERGED, {"turns": params.turns, "x": place[0], "y": place[1]}),)
    return Footprint(cut.mask, ground, plane, footprint_volume(heights, ground, cut.mask, grid.cell_area,
                                                              params.threshold_m),
                     float(cut.mask.sum()) * grid.cell_area, turns, converged, notes)


# --- A3: el reparto de las celdas comunes ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Claim:
    """Lo que una marca reclama: su ``name`` (única entre las reclamaciones), su ``mark`` (máscara de la ventana común)
    y su :class:`Footprint` (de la misma ventana, ya formado con :func:`grow_footprint`)."""

    name: str
    mark: np.ndarray
    footprint: Footprint


@dataclass(frozen=True, slots=True)
class SharedCells:
    """Dos marcas cuyas huellas comparten celdas (RF-016-06): sus nombres (``mark``, ``other``, en el orden de las
    reclamaciones), cuántas celdas comparten antes de repartirlas (``cells``), su área (``area_m2``) y el centro de esas
    celdas (``x``, ``y``, m absolutos). :attr:`message` es el aviso, con las dos marcas, el área repartida y el lugar."""

    mark: str
    other: str
    cells: int
    area_m2: float
    x: float
    y: float

    @property
    def message(self) -> SiteMessage:
        """El aviso ``des.stockpile_shared_cells`` de la pareja, completo (sus valores mandan sobre los de
        :meth:`SiteMessage.notice`)."""
        return SiteMessage(_SHARED_CELLS, {"mark": self.mark, "other": self.other, "area": self.area_m2,
                                           "x": self.x, "y": self.y})


@dataclass(frozen=True, slots=True, eq=False)
class Shared:
    """Lo que da el reparto: las huellas (``footprints``, en el orden de las reclamaciones; el **mismo objeto** si no
    tuvo celdas comunes, y si no, otro con su máscara, su volumen y su área sobre lo que le queda) y un
    :class:`SharedCells` por cada pareja con celdas comunes (``shared``, por parejas en el orden de las reclamaciones)."""

    footprints: tuple[Footprint, ...]
    shared: tuple[SharedCells, ...]


def _share_inputs(claims: Sequence[Claim], z: np.ndarray, grid: Grid, threshold_m: float
                  ) -> tuple[tuple[Claim, ...], np.ndarray, Grid, float]:
    found = tuple(claims)
    if not found:
        raise ValueError("el reparto necesita al menos una reclamación")
    if grid.dx != grid.dy:
        raise ValueError(f"la rejilla de los acopios es la del proyecto, de celdas cuadradas, no {grid.dx} × {grid.dy}")
    heights = np.asarray(z, dtype=np.float64)
    if heights.shape != grid.shape:
        raise ValueError(f"la superficie tiene {heights.shape} celdas y la ventana {grid.shape}")
    names = [claim.name for claim in found]
    if len(set(names)) != len(names):
        raise ValueError(f"los nombres de las marcas se repiten: {names}")
    for claim in found:
        _mask(claim.mark, grid.shape, f"la marca «{claim.name}»")
        _mask(claim.footprint.mask, grid.shape, f"la huella de «{claim.name}»")
    return found, heights, grid, _threshold(threshold_m)


def share_cells_steps(claims: Sequence[Claim], z: np.ndarray, grid: Grid, threshold_m: float, *,
                      budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """:func:`share_cells` por pasos de ``budget_s`` como mucho (la distancia exacta a cada marca, de
    :func:`design.grids.nearest_value_steps`): el último ``Progress`` (fase ``share``) lleva el :class:`Shared`. Los
    rechazos (``ValueError``: sin reclamaciones, nombres repetidos, máscaras que no son de la ventana) salen **en la
    llamada**. Cerrar el generador a mitad no deja nada."""
    return _share_run(_share_inputs(claims, z, grid, threshold_m), budget_s)


def share_cells(claims: Sequence[Claim], z: np.ndarray, grid: Grid, threshold_m: float) -> Shared:
    """El reparto de las celdas comunes de las huellas de ``claims`` (RF-016-06, D-16; ver el módulo), sobre la
    superficie ``z`` de la ventana ``grid`` y con el umbral ``threshold_m`` (m) del volumen que se recalcula:
    :func:`share_cells_steps` de una vez."""
    last: Progress | None = None
    for last in share_cells_steps(claims, z, grid, threshold_m):
        pass
    if last is None or not isinstance(last.result, Shared):  # inalcanzable: el último paso lo lleva
        raise RuntimeError("el reparto no dio resultado")
    return last.result


def _share_run(prepared: tuple[tuple[Claim, ...], np.ndarray, Grid, float], budget_s: float
               ) -> Generator[Progress, None, None]:
    """Los pasos de :func:`share_cells_steps`."""
    claims, heights, grid, limit = prepared
    footprints = [claim.footprint.mask for claim in claims]
    marks = [claim.mark for claim in claims]
    count = np.sum(np.stack(footprints), axis=0)
    if not (count >= 2).any():
        yield Progress("share", 1, 1, "Sin celdas comunes que repartir",
                       result=Shared(tuple(claim.footprint for claim in claims), ()))
        return
    involved = [k for k, footprint in enumerate(footprints) if (footprint & (count >= 2)).any()]
    reach = np.logical_or.reduce([footprints[k] | marks[k] for k in involved])
    rows, cols = np.flatnonzero(reach.any(axis=1)), np.flatnonzero(reach.any(axis=0))
    box = (slice(int(rows[0]), int(rows[-1]) + 1), slice(int(cols[0]), int(cols[-1]) + 1))
    zeros = np.zeros(reach[box].shape)
    unreachable = np.iinfo(np.int64).max
    distances = []
    for k in involved:
        nearest = yield from forward(nearest_value_steps(marks[k][box], zeros, grid.dx, budget_s=budget_s))
        distances.append(np.where(nearest.cells2 >= 0, nearest.cells2, unreachable - 1))
    claimed = np.stack([footprints[k][box] for k in involved])
    # La marca que contiene la celda está a distancia 0, así que es la más próxima de las que la reclaman (y si la
    # contienen varias, o ninguna, es la más próxima): una sola regla; a igual distancia, la primera de la lista.
    owner = np.where(claimed, np.stack(distances), unreachable).argmin(axis=0)
    shared_here = claimed.sum(axis=0) >= 2
    kept = claimed & (~shared_here[None] | (np.arange(len(involved))[:, None, None] == owner[None]))
    results = [claim.footprint for claim in claims]
    for index, k in enumerate(involved):
        if np.array_equal(kept[index], claimed[index]):
            continue
        mask = footprints[k].copy()
        mask[box] = kept[index]
        results[k] = replace(claims[k].footprint, mask=mask, area_m2=float(mask.sum()) * grid.cell_area,
                             volume_m3=footprint_volume(heights, claims[k].footprint.base, mask, grid.cell_area,
                                                        limit))
    x, y = grid.centers()
    pairs = []
    for first, k in enumerate(involved):
        for later in involved[first + 1:]:
            common = footprints[k] & footprints[later]
            if common.any():
                place = _centre(common, x, y)
                pairs.append(SharedCells(claims[k].name, claims[later].name, int(common.sum()),
                                         float(common.sum()) * grid.cell_area, place[0], place[1]))
    yield Progress("share", 1, 1, "Celdas comunes repartidas", result=Shared(tuple(results), tuple(pairs)))


# --- A4: los candidatos sin marca -------------------------------------------------------------------------------------


def window_grid(grid: Grid, window: tuple[slice, slice]) -> Grid:
    """La rejilla de la ventana ``window`` (filas y columnas de ``grid``) de ``grid``: la esquina noroeste de su primera
    celda, los mismos pasos. ``ValueError`` si la ventana está vacía o sale de la rejilla."""
    rows, cols = window
    if not (0 <= rows.start < rows.stop <= grid.nrows and 0 <= cols.start < cols.stop <= grid.ncols):
        raise ValueError(f"la ventana ({rows}, {cols}) no cabe en una rejilla de {grid.shape} celdas")
    return Grid(grid.west + cols.start * grid.dx, grid.north - rows.start * grid.dy, grid.dx, grid.dy,
                cols.stop - cols.start, rows.stop - rows.start)


def _box_window(rows: slice, cols: slice, grid: Grid, params: FootprintParams) -> tuple[slice, slice]:
    """La ventana de trabajo de la caja ``rows`` × ``cols`` (A0): el alcance de A2 y A3 es el margen más la corona
    exterior (la huella no sale de la marca ampliada y la corona, de la huella dilatada), y ``work_window`` añade las
    dos celdas de la pendiente."""
    return work_window(rows, cols, params.margin_m + params.plane.crown_outer_m, grid)


def mark_window(mark: np.ndarray, grid: Grid, params: FootprintParams) -> tuple[slice, slice]:
    """**A0** de un acopio (plan 016 §5.4): la ventana de la rejilla ``grid`` en la que calcular A2 y A3 de la marca
    ``mark`` (máscara de ``grid``) sin cambiar un bit del resultado frente a la rejilla entera: la caja de la marca
    ampliada por el margen y la corona exterior de ``params`` y por dos celdas (la pendiente de la corona lee a sus
    vecinas), recortada a la rejilla (:func:`design.platform.work_window`). ``ValueError`` si la marca no tiene celdas o
    no es de la forma de ``grid``."""
    marked = _mask(mark, grid.shape, "la marca")
    rows, cols = np.flatnonzero(marked.any(axis=1)), np.flatnonzero(marked.any(axis=0))
    if rows.size == 0:
        raise ValueError("la marca no tiene ninguna celda")
    return _box_window(slice(int(rows[0]), int(rows[-1]) + 1), slice(int(cols[0]), int(cols[-1]) + 1), grid, params)


@dataclass(frozen=True, slots=True)
class CandidateParams:
    """Los umbrales de A4 (plan 016 §5.2.2, ``stockpile``): el diámetro del disco de la apertura (``open_diameter_m``,
    m), la altura mínima que sobresale (``min_height_m``, m), el área mínima y máxima de una zona (``min_area_m2`` y
    ``max_area_m2``, m²; ambas incluidas) y los de A2 y A3 con que se forma el acopio de cada zona (``footprint``).
    **Sin valor por defecto**: los pone quien resuelve los parámetros. Un valor fuera de su rango
    (``STOCKPILE_RANGES``) es un ``ValueError`` que lo nombra, y también un área mínima mayor que la máxima."""

    open_diameter_m: float
    min_height_m: float
    min_area_m2: float
    max_area_m2: float
    footprint: FootprintParams

    def __post_init__(self) -> None:
        if not isinstance(self.footprint, FootprintParams):
            raise TypeError(f"los umbrales de la huella de un candidato son FootprintParams, no {self.footprint!r}")
        for param in (StockpileParam.OPEN_DIAMETER, StockpileParam.MIN_HEIGHT, StockpileParam.MIN_AREA,
                      StockpileParam.MAX_AREA):
            object.__setattr__(self, param.value, _check_value(param.value, getattr(self, param.value)))
        if self.min_area_m2 > self.max_area_m2:
            raise ValueError(f"«{StockpileParam.MIN_AREA.value}» ({self.min_area_m2}) no puede pasar de "
                             f"«{StockpileParam.MAX_AREA.value}» ({self.max_area_m2})")


@dataclass(frozen=True, slots=True, eq=False)
class Candidate:
    """Un candidato sin marca (A4): su ``zone`` (la componente que lo da, máscara de su ventana), su ``footprint`` (A2 y
    A3 sobre la zona como si fuera una marca: huella, plano de base, volumen y notas, de la **ventana**), su
    ``window`` (filas y columnas de la rejilla entera, de la ventana de trabajo), la rejilla de esa ventana
    (``grid``) y las celdas de su huella en la rejilla entera (``cells``: ``fila · columnas + columna``, ``int64``,
    ordenadas y sin repetir), que usa :func:`carry_decisions`."""

    zone: np.ndarray
    footprint: Footprint
    window: tuple[slice, slice]
    grid: Grid
    cells: np.ndarray

    @property
    def centre(self) -> tuple[float, float]:
        """El centro de su huella (la media de los centros de celda, m absolutos): el lugar al que «ir»."""
        x, y = self.grid.centers()
        return _centre(self.footprint.mask, x, y)


@dataclass(frozen=True, slots=True, eq=False)
class Candidates:
    """Los candidatos sin marca de una superficie (A4): la ``grid`` entera, los ``items`` que pasan los filtros y se
    pudieron formar, en el orden de lectura de su zona, y los **contadores** de lo demás, que nunca se lista: las
    ``zones`` que salieron de la apertura antes de filtrar, las que tienen marca (``on_marks``), las que no llegan al
    área mínima (``too_small``) o pasan de la máxima (``too_large``) y las que pasan los filtros pero A2 o A3 rechazan
    (``rejected``). No se solapan: ``zones`` es la suma de los candidatos y de los cuatro contadores."""

    grid: Grid
    items: tuple[Candidate, ...]
    zones: int
    on_marks: int
    too_small: int
    too_large: int
    rejected: int

    @property
    def filtered(self) -> int:
        """Las zonas que descartó el filtro del área (el informe las cuenta, sin listarlas)."""
        return self.too_small + self.too_large


_CandidateInputs = tuple[np.ndarray, Grid, np.ndarray, np.ndarray, CandidateParams]


def _candidate_inputs(z: object, grid: Grid, perimeter: object, marked: object | None,
                      params: object) -> _CandidateInputs:
    """Las entradas de A4 comprobadas (``ValueError`` o ``TypeError`` que nombra la que falla): la superficie, la
    rejilla de celdas cuadradas, el perímetro y las celdas con marca (ninguna si ``marked`` es ``None``)."""
    if not isinstance(params, CandidateParams):
        raise TypeError(f"los parámetros de A4 son CandidateParams, no {params!r}")
    if grid.dx != grid.dy:
        raise ValueError(f"la rejilla de los acopios es la del proyecto, de celdas cuadradas, no {grid.dx} × {grid.dy}")
    heights = np.asarray(z, dtype=np.float64)
    if heights.shape != grid.shape:
        raise ValueError(f"la superficie tiene {heights.shape} celdas y la rejilla {grid.shape}")
    region = _mask(perimeter, grid.shape, "el perímetro")
    taken = np.zeros(grid.shape, dtype=bool) if marked is None else _mask(marked, grid.shape, "las celdas con marca")
    return heights, grid, region, taken, params


def candidates_steps(z: np.ndarray, grid: Grid, perimeter: np.ndarray, marked: np.ndarray | None,
                     params: CandidateParams, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """A4 por pasos de ``budget_s`` como mucho (la apertura por bandas, las zonas y un candidato por unidad): el último
    ``Progress`` (fase ``candidates``) lleva los :class:`Candidates` de la superficie ``z`` de la rejilla ``grid`` (el
    ``surface`` del plan 016 §5.3.1, con la rejilla que el plan da por supuesta), dentro de ``perimeter`` y sin las
    zonas que contienen o se solapan con las celdas de ``marked`` (ver el módulo; ``None``: ninguna marca). Todo lo que
    se rechaza de la entrada (formas, máscaras que no son booleanas, celdas no cuadradas, infinitos, parámetros) sale
    **en la llamada**. Ninguna entrada se modifica; cerrar el generador a mitad no deja nada."""
    prepared = _candidate_inputs(z, grid, perimeter, marked, params)
    opening = opening_steps(prepared[0], params.open_diameter_m / 2.0, grid.dx, budget_s=budget_s)
    return _candidates_run(prepared, opening, budget_s)


def find_candidates(z: np.ndarray, grid: Grid, perimeter: np.ndarray, marked: np.ndarray | None,
                    params: CandidateParams) -> Candidates:
    """:func:`candidates_steps` de una vez (ver el módulo)."""
    last: Progress | None = None
    for last in candidates_steps(z, grid, perimeter, marked, params):
        pass
    if last is None or not isinstance(last.result, Candidates):  # inalcanzable: el último paso lo lleva
        raise RuntimeError("la búsqueda de candidatos no dio resultado")
    return last.result


def _candidates_run(prepared: _CandidateInputs, opening: Iterator[Progress], budget_s: float
                    ) -> Generator[Progress, None, None]:
    """Los pasos de :func:`candidates_steps`: la apertura, las zonas y un candidato por unidad."""
    heights, grid, region, taken, params = prepared
    opened = yield from forward(opening)
    with np.errstate(invalid="ignore"):
        above = region & ((heights - opened) > params.min_height_m)
    del opened
    yield Progress("candidates", 0, 1, "Buscando las zonas que sobresalen…")
    labels = yield from forward(label_components_steps(above, budget_s=budget_s))
    found = yield from forward(pace_progress(
        _candidate_units(heights, grid, taken, labels, params), budget_s, phase="candidates",
        running="Formando los candidatos…", finished="Candidatos formados"))
    yield Progress("candidates", 1, 1, "Candidatos encontrados", result=found)


def _candidate_units(heights: np.ndarray, grid: Grid, taken: np.ndarray, labels: object, params: CandidateParams
                     ) -> Generator[None, None, Candidates]:
    """Las unidades de A4 tras etiquetar las zonas: el filtro y, por unidad, A2 y A3 de cada zona que pasa."""
    count = labels.count  # type: ignore[attr-defined]
    cell_ids = labels.grid  # type: ignore[attr-defined]
    area = labels.sizes * grid.cell_area  # type: ignore[attr-defined]
    on_marks = np.bincount(cell_ids[taken], minlength=count + 1)[1:] > 0
    free = ~on_marks
    too_small = free & (area < params.min_area_m2)
    too_large = free & (area > params.max_area_m2)
    wanted = np.flatnonzero(free & ~too_small & ~too_large) + 1  # las etiquetas de los candidatos
    yield
    # Las celdas de cada etiqueta que pasa, agrupadas por etiqueta (orden estable: el de lectura dentro de cada una).
    flat = cell_ids.ravel()
    selected = np.zeros(count + 1, dtype=bool)
    selected[wanted] = True
    cells = np.flatnonzero(selected[flat])
    tags = flat[cells]
    order = np.argsort(tags, kind="stable")
    cells, tags = cells[order], tags[order]
    first = np.searchsorted(tags, wanted, side="left")
    last = np.searchsorted(tags, wanted, side="right")
    yield
    items: list[Candidate] = []
    rejected = 0
    for label, begin, end in zip(wanted.tolist(), first.tolist(), last.tolist(), strict=True):
        rows, cols = np.divmod(cells[begin:end], grid.ncols)
        window = _box_window(slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1),
                             grid, params.footprint)
        zone = cell_ids[window] == label
        place = window_grid(grid, window)
        try:
            footprint = grow_footprint(heights[window], zone, place, params.footprint)
        except StockpileRejected:
            rejected += 1
        else:
            inside_rows, inside_cols = np.nonzero(footprint.mask)
            keys = (inside_rows.astype(np.int64) + window[0].start) * grid.ncols + (inside_cols + window[1].start)
            items.append(Candidate(zone, footprint, window, place, keys))
        yield
    return Candidates(grid, tuple(items), count, int(on_marks.sum()), int(too_small.sum()), int(too_large.sum()),
                      rejected)


# --- A4: la regla de identidad al repetir (D-23) ---------------------------------------------------------------------


def _footprint_cells(value: object, what: str) -> np.ndarray:
    """Las celdas de una huella como ``int64`` ordenadas y sin repetir; ``ValueError`` si no son un array de 1
    dimensión de enteros."""
    found = np.asarray(value)
    if found.ndim != 1 or found.dtype.kind not in "iu":
        raise ValueError(f"{what}: las celdas de una huella son un array de 1 dimensión de enteros, no un array "
                         f"{found.dtype} de {found.ndim}")
    return np.unique(found.astype(np.int64, copy=False))


def carry_decisions(new: Sequence[np.ndarray], previous: Sequence[np.ndarray]) -> tuple[int | None, ...]:
    """La regla de identidad al repetir una detección (RF-016-10, D-23; ver el módulo): para cada huella de ``new`` (las
    celdas de un candidato nuevo en la rejilla entera, como :attr:`Candidate.cells`), el índice en ``previous`` del
    candidato anterior cuya **decisión conserva**, o ``None`` si hay que volver a preguntar. Conserva la de aquel con el
    que comparte **más de la mitad del área de cada uno** (más celdas comunes que la mitad de las de cada huella:
    enteros, sin redondeos); si varios cumplen, gana la pareja con más celdas comunes (a igualdad, el candidato nuevo
    y después el anterior de índice menor) y cada decisión anterior se conserva **una sola vez**. Función pura: no
    lee más que las celdas. ``ValueError`` si una huella no es un array de 1 dimensión de enteros."""
    fresh = [_footprint_cells(cells, f"la huella nueva {k}") for k, cells in enumerate(new)]
    old = [_footprint_cells(cells, f"la huella anterior {k}") for k, cells in enumerate(previous)]
    kept: list[int | None] = [None] * len(fresh)
    if not fresh or not old:
        return tuple(kept)
    where = np.concatenate(old)
    owners = np.concatenate([np.full(cells.size, k, dtype=np.int64) for k, cells in enumerate(old)])
    order = np.argsort(where, kind="stable")
    where, owners = where[order], owners[order]
    old_sizes = np.array([cells.size for cells in old], dtype=np.int64)
    pairs: list[tuple[int, int, int]] = []
    for i, cells in enumerate(fresh):
        if cells.size == 0 or where.size == 0:
            continue
        low = np.searchsorted(where, cells, side="left")
        counts = np.searchsorted(where, cells, side="right") - low
        total = int(counts.sum())
        if total == 0:
            continue
        starts = np.repeat(low, counts) + np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
        shared = np.bincount(owners[starts], minlength=len(old))
        for j in np.flatnonzero((2 * shared > cells.size) & (2 * shared > old_sizes)).tolist():
            pairs.append((-int(shared[j]), i, j))
    used: set[int] = set()
    for _negative, i, j in sorted(pairs):
        if kept[i] is None and j not in used:
            kept[i] = j
            used.add(j)
    return tuple(kept)
