# SPDX-License-Identifier: GPL-3.0-or-later
"""La detección de acopios: el plano de base robusto y su límite de inclinación (spec 016, T06; RF-016-02, RF-016-04,
RF-016-05, RF-016-07; plan 016 A2, §5.2.2, §7.1, §7.3; D-3). Las demás piezas de A3 a A5 (la huella iterativa y el
reparto, los candidatos, las bases y los espesores) las añaden T07 a T09 a este módulo.

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

Ninguna entrada se modifica. Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

import numpy as np

from ..gis.grid import Grid
from .messages import lookup
from .morphology import dilate
from .params import STOCKPILE_RANGES, StockpileParam
from .preview import Notice

__all__ = [
    "BasePlane",
    "PlaneParams",
    "SiteMessage",
    "StockpileRejected",
    "base_plane",
    "cell_slope_deg",
    "crown_of",
    "fit_plane",
]

_NO_CROWN_CELLS = "des.stockpile_no_crown_cells"
_NO_TERRAIN_CROWN = "des.stockpile_no_terrain_crown"
_CROWN_FEW_FLAT = "des.stockpile_crown_few_flat"
_TILT_LIMITED = "des.stockpile_tilt_limited"
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
