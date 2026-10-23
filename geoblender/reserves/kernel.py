# SPDX-License-Identifier: GPL-3.0-or-later
"""El núcleo de la cubicación: totales, umbral, dominios, rodajas y unidades en una sola pasada
por bandas de filas (spec 011; RF-011-01, RF-011-04, RF-011-07, RF-011-09, RF-011-10, RF-011-12,
RF-011-13, RF-011-14; plan 011 A2, A3, A7 y D-20).

Una cubicación es **un solo cálculo** celda a celda (RF-011-10): las dos superficies se leen por
bandas de filas y cada banda se suma, de una vez, a todos los repartos, con las mismas
superficies, el mismo ámbito y el mismo espesor mínimo.

- :class:`Accumulators`: lo que se lleva sumado (float64), con la rejilla, las rodajas, el
  número de dominios, el espesor mínimo, el número de unidades de la columna de materiales y el
  umbral de presencia de lo antrópico de la cubicación, fijados al crearlo.
- :class:`BandValues`: las cotas de una banda de filas de la superficie de partida y de la final
  (una cota constante, como un número) y, con unidades, sus bases y sus espesores.
- :func:`band_step`: suma una banda (A2, A3, A7), con los pesos de ``reserves.polygons.weights``
  si hay ámbito o dominios; de una vez o por trozos de unidades.
- :meth:`Accumulators.result` → :class:`KernelResult`: m³ y m², una vez pasadas todas las filas.

**Una banda (A2).** ``d = partida − final`` en las celdas con dato en las dos (las demás, al área
sin dato; nunca se rellenan); **desmonte** donde ``d > e`` y **terraplén** donde ``−d > e``, con
**todo** su espesor (``e``, el espesor mínimo, es un umbral: D-6, RF-011-04); el resto con dato,
**sin movimiento**. Volúmenes ``Σ w·|d|·A`` y áreas ``Σ w·A`` con ``A`` el área real de celda
(``Grid.cell_area``, RF-006-02) y ``w`` el peso de la celda: 1 sin ámbito, su fracción dentro del
ámbito con él y, en cada dominio, la de las entradas celda-dominio-peso de la banda (A5;
RF-011-07). Sin ámbito, el total no pasa por los pesos: con ``e = 0`` y de una vez es **bit a
bit** el de ``gis.grid.volume_between`` de la 006 (D-20: las mismas restas, el mismo array y la
misma suma por pares de numpy); por bandas, el mismo salvo el redondeo de sumar las bandas.

**Filas.** La fila :data:`ALL` (0) es el total de la cubicación; con dominios, la ``1 + i`` es el
dominio ``i`` de los pesos y la última (:attr:`KernelResult.outside`), «Fuera de los dominios»:
las filas de los dominios suman el total por construcción (A5).

**Rodajas (A3, D-22).** Rodajas semiabiertas ``[z_k, z_k+1)`` de ``reserves.slices``. El
intervalo de cada celda (desmonte ``[final, partida]``, terraplén ``[partida, final]``) va de
``k_a = index(a)`` a ``k_b = index(b)``, con el extremo superior justo en una cota en la rodaja
de abajo: si ``k_a = k_b``, todo a ``k_a``; si no, ``z_{k_a+1} − a`` a ``k_a``, ``b − z_{k_b}`` a
``k_b`` y una rodaja entera a cada una de en medio por **diferencias acumuladas** (``+w`` en
``k_a + 1`` y ``−w`` en ``k_b``; al final, la suma acumulada por el espesor de la rodaja): coste
proporcional a las celdas, no a las rodajas. Restar dos cotas cercanas es exacto en float64
(lema de Sterbenz): los trozos de un intervalo suman su espesor salvo el redondeo de las sumas.
Con altura y anclaje, las cotas son las de ``slices.bounds`` sobre lo cubicado (de la mínima a la
máxima de los intervalos que cuentan) y todas salen, también las vacías. Con una lista, la lista
tal cual; lo que queda por debajo de la primera cota o por encima de la última no cae en ninguna
rodaja: se lleva **aparte** (``below_*`` y ``above_*``), así que todo suma el total.

**Unidades (A7; D-10, D-7).** Solo en las celdas de **desmonte**, de arriba abajo con ``techo =
+∞``: la base de cada unidad (la última no tiene: ``−∞``); **ausente** si su base no tiene dato
o, en una antrópica, si su espesor no **pasa** del umbral de presencia (``espesor > umbral``;
sin dato, ausente): su espesor pasa a la de abajo. **Base efectiva** = ``min(base, techo)``: si
la base sube por encima del techo, **cruce** (espesor 0). La unidad ocupa ``[base efectiva,
techo)`` y su volumen es lo que de ella cae en ``[final, partida]``; después, ``techo = base
efectiva``. Así una antrópica tiene su volumen desde su base hacia arriba y las de debajo quedan
cortadas en esa base (en su sitio: nunca se descuenta en proporción; errores 18 y 63). Las
unidades parten el intervalo de cada celda, así que suman el desmonte salvo el redondeo; el
terraplén no se reparte. Por unidad y fila, el área ausente, la de sin dato (base o espesor) y
la de cruce (m², de las celdas de desmonte); las rodajas de cada unidad, con A3 sobre su trozo.
Un espesor negativo es :class:`NegativeThickness` (``reserves.materials.negative_thickness`` da
el error para el usuario).

Python puro con numpy (nivel 9). Las entradas solo se leen.
"""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .slices import Slices, bounds, index

if TYPE_CHECKING:
    from ..gis.grid import Grid
    from .polygons import Weights

__all__ = [
    "ALL",
    "Accumulators",
    "BandValues",
    "KernelResult",
    "NegativeThickness",
    "band_step",
]

ALL = 0
"""La fila del total de la cubicación (``'*'`` en la tabla)."""

type _Layer = np.ndarray | float | None


class NegativeThickness(ValueError):
    """Una rejilla de espesores con espesores negativos (RF-011-14): ``unit``, la posición de
    la unidad en la columna, y ``value``, el menor (m). No se ha sumado nada de esa llamada;
    quien lo recibe lanza ``reserves.materials.negative_thickness`` (``res.thickness_negative``)
    con la unidad y su rejilla."""

    def __init__(self, unit: int, value: float) -> None:
        super().__init__(f"la unidad {unit} tiene espesores negativos (el menor, {value!r} m)")
        self.unit = unit
        self.value = value


@dataclass(frozen=True, slots=True, eq=False)
class BandValues:
    """Las cotas (m, float64) de la banda de filas que empieza en ``first_row`` (la fila 0 es la
    del norte): ``start``, la superficie de partida, y ``final``, la final, arrays ``(filas,
    columnas)`` de la rejilla (NaN = sin dato) o un número (una cota constante).

    Con unidades (A7), una por unidad de la columna, de arriba abajo: ``bases``, la cota de su
    base (array o número; la de la última, ``None``: no tiene) y ``thicknesses``, el espesor de
    una antrópica (m, array o número; ``None`` en las demás)."""

    first_row: int
    start: np.ndarray | float
    final: np.ndarray | float
    bases: tuple[_Layer, ...] = ()
    thicknesses: tuple[_Layer, ...] = ()


@dataclass(frozen=True, slots=True, eq=False)
class KernelResult:
    """El resultado del núcleo (m³ y m²), por filas: :data:`ALL` (el total) y, con dominios, cada
    dominio y «Fuera de los dominios» (:attr:`outside`).

    - ``cut_m3``, ``fill_m3``, ``net_m3`` (desmonte − terraplén), ``area_m2`` (con dato en las
      dos superficies), ``nodata_area_m2`` (sin dato en alguna) y ``still_area_m2`` (con dato y
      sin movimiento): arrays ``(filas,)``.
    - Sin rodajas, ``bounds`` y lo demás de las rodajas son ``None``. Con ellas, ``bounds`` son
      sus cotas (``n + 1``, crecientes; ninguna si nada se mueve con altura y anclaje),
      ``slice_cut_m3`` y ``slice_fill_m3``, ``(filas, n)``, y ``below_*`` y ``above_*``,
      ``(filas,)``, lo que queda fuera de una lista de cotas (ceros con altura y anclaje).
    - Sin unidades (``units == 0``), lo de las unidades es ``None``. Con ellas, ``(filas,
      unidades)``: ``unit_volume_m3`` (el desmonte de cada unidad), ``unit_absent_m2`` (el área
      de desmonte donde no está), ``unit_nodata_m2`` (la parte de esa área con su base o su
      espesor sin dato) y ``unit_crossed_m2`` (donde su base sube por encima de la de encima);
      con rodajas, ``unit_slice_m3`` ``(filas, unidades, n)`` y ``unit_below_m3`` y
      ``unit_above_m3`` ``(filas, unidades)``."""

    cell_area_m2: float
    domains: int
    cut_m3: np.ndarray
    fill_m3: np.ndarray
    net_m3: np.ndarray
    area_m2: np.ndarray
    nodata_area_m2: np.ndarray
    still_area_m2: np.ndarray
    bounds: np.ndarray | None = None
    slice_cut_m3: np.ndarray | None = None
    slice_fill_m3: np.ndarray | None = None
    below_cut_m3: np.ndarray | None = None
    below_fill_m3: np.ndarray | None = None
    above_cut_m3: np.ndarray | None = None
    above_fill_m3: np.ndarray | None = None
    units: int = 0
    unit_volume_m3: np.ndarray | None = None
    unit_absent_m2: np.ndarray | None = None
    unit_nodata_m2: np.ndarray | None = None
    unit_crossed_m2: np.ndarray | None = None
    unit_slice_m3: np.ndarray | None = None
    unit_below_m3: np.ndarray | None = None
    unit_above_m3: np.ndarray | None = None

    @property
    def outside(self) -> int:
        """La fila de «Fuera de los dominios» (con dominios)."""
        return 1 + self.domains


@dataclass(eq=False)
class _Spread:
    """Lo que se lleva de las rodajas de un lado (desmonte o terraplén): ``part``, los trozos de
    cada fila y rodaja; ``whole``, las diferencias de las rodajas enteras (su suma acumulada es
    el peso de las celdas que la cruzan entera). Las columnas son las rodajas ``k`` desde
    ``Accumulators._k_low``."""

    part: np.ndarray
    whole: np.ndarray


def _non_negative(value: object, name: str) -> float:
    """``value`` como float finito ≥ 0; si no, ``ValueError``."""
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise ValueError(f"{name} es un número, no {value!r}")
    number = float(value)
    if not (math.isfinite(number) and number >= 0.0):
        raise ValueError(f"{name} es un número finito ≥ 0, no {value!r}")
    return number


def _count(value: object, name: str) -> int:
    """``value`` como entero ≥ 0; si no, ``ValueError``."""
    if isinstance(value, bool) or not isinstance(value, int | np.integer) or value < 0:
        raise ValueError(f"{name} es un entero ≥ 0, no {value!r}")
    return int(value)


@dataclass(eq=False)
class Accumulators:
    """Lo sumado de una cubicación (float64), con lo que la fija: la rejilla (``grid``), las
    rodajas (``slices``; ``None`` sin ellas), el número de dominios de los pesos (``domains``;
    0 sin ellos), el espesor mínimo (``min_thickness_m``, m), el número de unidades de la
    columna de materiales (``units``; 0 sin repartir por unidades) y el umbral de presencia de
    lo antrópico (``presence_m``, m); los espesores, números finitos ≥ 0 (si no,
    ``ValueError``). Cada fila de la rejilla se suma una vez, y cada unidad de cada fila, una
    vez (:func:`band_step`); :meth:`result` da las cifras cuando están todas."""

    grid: Grid
    slices: Slices | None = None
    domains: int = 0
    min_thickness_m: float = 0.0
    units: int = 0
    presence_m: float = 0.0
    _rows: int = field(init=False)
    _seen: np.ndarray = field(init=False)
    _cut: np.ndarray = field(init=False)
    _fill: np.ndarray = field(init=False)
    _data: np.ndarray = field(init=False)
    _nodata: np.ndarray = field(init=False)
    _still: np.ndarray = field(init=False)
    _unit_seen: np.ndarray = field(init=False)
    _unit_volume: np.ndarray = field(init=False)
    _unit_absent: np.ndarray = field(init=False)
    _unit_nodata: np.ndarray = field(init=False)
    _unit_crossed: np.ndarray = field(init=False)
    _k_low: int = field(init=False, default=0)
    _sides: tuple[_Spread, _Spread] | None = field(init=False, default=None)
    _unit_side: _Spread | None = field(init=False, default=None)
    _zmin: float = field(init=False, default=math.inf)
    _zmax: float = field(init=False, default=-math.inf)

    def __post_init__(self) -> None:
        self.min_thickness_m = _non_negative(self.min_thickness_m, "min_thickness_m")
        self.presence_m = _non_negative(self.presence_m, "presence_m")
        self.domains = _count(self.domains, "domains")
        self.units = _count(self.units, "units")
        if self.slices is not None and not isinstance(self.slices, Slices):
            raise ValueError(f"slices es un reserves.slices.Slices, no {self.slices!r}")
        self._rows = 1 if self.domains == 0 else self.domains + 2
        self._seen = np.zeros(self.grid.nrows, dtype=bool)
        self._cut, self._fill, self._data, self._nodata, self._still = (
            np.zeros(self._rows) for _ in range(5))
        self._unit_seen = np.zeros((self.grid.nrows, self.units), dtype=bool)
        self._unit_volume, self._unit_absent, self._unit_nodata, self._unit_crossed = (
            np.zeros((self._rows, self.units)) for _ in range(4))
        if self.slices is not None:
            width = 0
            if self.slices.levels is not None:  # −1 (abajo), 0 … n − 1 y n (arriba)
                self._k_low, width = -1, len(self.slices.levels) + 1
            self._sides = (self._spread(self._rows, width), self._spread(self._rows, width))
            if self.units:  # una fila por fila y unidad: fila · unidades + unidad
                self._unit_side = self._spread(self._rows * self.units, width)

    @staticmethod
    def _spread(count: int, width: int) -> _Spread:
        return _Spread(np.zeros((count, width)), np.zeros((count, width)))

    def _grow(self, low: int, high: int) -> None:
        """Amplía las columnas de las rodajas para que vayan de ``low`` a ``high`` (con altura y
        anclaje; con una lista ya están todas)."""
        assert self._sides is not None
        width = self._sides[0].part.shape[1]
        if width == 0:
            before, after, first = 0, high - low + 1, low
        else:
            before = max(self._k_low - low, 0)
            after = max(high - (self._k_low + width - 1), 0)
            if before == 0 and after == 0:
                return
            first = self._k_low - before
        pad = ((0, 0), (before, after))

        def padded(side: _Spread) -> _Spread:
            return _Spread(np.pad(side.part, pad), np.pad(side.whole, pad))

        self._sides = (padded(self._sides[0]), padded(self._sides[1]))
        if self._unit_side is not None:
            self._unit_side = padded(self._unit_side)
        self._k_low = first

    def result(self) -> KernelResult:
        """Las cifras de la cubicación (m³ y m²): ``ValueError`` si falta alguna fila de la
        rejilla (o alguna unidad de una fila) por sumar."""
        if not self._seen.all():
            missing = int(np.count_nonzero(~self._seen))
            raise ValueError(f"faltan {missing} filas de la rejilla por sumar")
        if not self._unit_seen.all():
            missing = int(np.count_nonzero(~self._unit_seen.all(axis=1)))
            raise ValueError(f"faltan unidades de {missing} filas de la rejilla por sumar")
        area = self.grid.cell_area
        cut, fill = self._cut * area, self._fill * area
        totals = {
            "cut_m3": cut, "fill_m3": fill, "net_m3": cut - fill,
            "area_m2": self._data * area, "nodata_area_m2": self._nodata * area,
            "still_area_m2": self._still * area,
        }
        if self.units:
            totals |= {
                "units": self.units, "unit_volume_m3": self._unit_volume * area,
                "unit_absent_m2": self._unit_absent * area,
                "unit_nodata_m2": self._unit_nodata * area,
                "unit_crossed_m2": self._unit_crossed * area,
            }
        if self.slices is None or self._sides is None:
            return KernelResult(area, self.domains, **totals)
        levels, columns = self._bounds()
        thickness = np.diff(levels)
        figures: dict[str, np.ndarray] = {}
        edges = self._edge_columns()
        sides = [("slice_cut_m3", "below_cut_m3", "above_cut_m3", self._sides[0]),
                 ("slice_fill_m3", "below_fill_m3", "above_fill_m3", self._sides[1])]
        if self._unit_side is not None:
            sides.append(("unit_slice_m3", "unit_below_m3", "unit_above_m3", self._unit_side))
        for name, below, above, side in sides:
            whole = np.cumsum(side.whole, axis=1)
            figures[name] = (_take(side.part, columns)
                             + _take(whole, columns) * thickness) * area
            for edge, column in zip((below, above), edges, strict=True):
                found = (np.zeros(side.part.shape[0]) if column is None
                         else side.part[:, column])
                figures[edge] = found * area
        if self._unit_side is not None:
            shape = (self._rows, self.units)
            figures["unit_slice_m3"] = figures["unit_slice_m3"].reshape(*shape, -1)
            figures["unit_below_m3"] = figures["unit_below_m3"].reshape(shape)
            figures["unit_above_m3"] = figures["unit_above_m3"].reshape(shape)
        return KernelResult(area, self.domains, bounds=levels, **totals, **figures)

    def _bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Las cotas de las rodajas y la columna de cada rodaja en lo sumado."""
        assert self.slices is not None
        if self.slices.levels is not None:
            levels = np.array(self.slices.levels, dtype=np.float64)
            return levels, np.arange(levels.size - 1) - self._k_low
        if not math.isfinite(self._zmin):
            return np.zeros(0), np.zeros(0, dtype=np.int64)
        levels = bounds(self.slices, self._zmin, self._zmax)
        first = int(index(self.slices, levels[0]))
        return levels, np.arange(levels.size - 1) + first - self._k_low

    def _edge_columns(self) -> tuple[int | None, int | None]:
        """Las columnas de lo que queda por debajo y por encima de una lista de cotas (``None``
        con altura y anclaje, que cubren todo lo cubicado)."""
        assert self.slices is not None
        if self.slices.levels is None:
            return None, None
        return -1 - self._k_low, len(self.slices.levels) - 1 - self._k_low


def _take(values: np.ndarray, columns: np.ndarray) -> np.ndarray:
    """Las columnas ``columns`` de ``values`` (ceros donde no las hay)."""
    found = np.zeros((values.shape[0], columns.size))
    inside = (columns >= 0) & (columns < values.shape[1])
    found[:, inside] = values[:, columns[inside]]
    return found


@dataclass(frozen=True, slots=True, eq=False)
class _Entries:
    """Las entradas celda-dominio-peso de una banda: la celda (índice plano en la banda), el
    dominio (``0 … domains``; ``domains`` es «Fuera de los dominios») y el peso."""

    cell: np.ndarray
    domain: np.ndarray
    weight: np.ndarray


def band_step(accumulators: Accumulators, band: BandValues, weights: Weights | None = None,
              *, units: slice | None = None) -> None:
    """Suma la banda ``band`` a ``accumulators`` (A2, A3, A7): totales, áreas, dominios, rodajas
    y unidades, en un solo cálculo (RF-011-10). ``weights`` son los de
    ``reserves.polygons.weights`` para esa banda (su ámbito y sus entradas celda-dominio-peso),
    ``None`` sin ámbito ni dominios; con dominios hacen falta.

    ``units`` trocea la banda por unidades (para que cada paso quepa en su presupuesto,
    RNF-011-04): ``None`` es la banda entera (totales y todas las unidades); un ``slice(a, b)``,
    solo las unidades ``a … b − 1`` de la banda, y también los totales si es su primer trozo
    (``slice(0, 0)``: solo los totales). En cualquier orden, da lo mismo que de una vez.

    Son errores del programa (``ValueError``, sin sumar nada): una banda que no es de la anchura
    de la rejilla o se sale de ella, que repite filas o unidades ya sumadas, o unos pesos de otra
    banda, de otro número de dominios o que faltan; unas bases o unos espesores que no son uno
    por unidad (la última, sin base; las demás, con ella) o de otra forma; un trozo fuera de la
    columna o con paso. Un espesor negativo de una unidad del trozo es :class:`NegativeThickness`
    (sin sumar nada)."""
    grid = accumulators.grid
    first, start, final = _band_arrays(band, grid)
    rows = slice(first, first + start.shape[0])
    scope, entries = _band_weights(accumulators, weights, rows, start.shape[0])
    low, high = _unit_range(accumulators, units)
    bases, thicknesses = _unit_layers(accumulators, band, start.shape)
    seen = accumulators._seen[rows]
    totals = units is None or not seen.any()
    if (seen.any() and (totals or not seen.all())) \
            or accumulators._unit_seen[rows, low:high].any():
        raise ValueError(f"las filas {rows.start}–{rows.stop - 1} (o sus unidades {low}–"
                         f"{high - 1}) ya se sumaron")
    _check_thickness(thicknesses, low, high)
    accumulators._seen[rows] = True
    accumulators._unit_seen[rows, low:high] = True
    e = accumulators.min_thickness_m
    valid = np.isfinite(start) & np.isfinite(final)
    with np.errstate(invalid="ignore"):
        difference = start - final
    if totals:
        _add_totals(accumulators, valid, difference, scope, e)
        if entries is not None:
            _add_domains(accumulators, valid, difference, entries, e)
        if accumulators.slices is not None:
            _add_slices(accumulators, valid, difference, start, final, scope, entries, e)
    if high > low:
        _add_units(accumulators, valid, difference, start, final, scope, entries, e,
                   bases, thicknesses, low, high)


def _band_arrays(band: BandValues, grid: Grid) -> tuple[int, np.ndarray, np.ndarray]:
    """La primera fila de la banda y sus dos superficies como arrays float64 ``(filas,
    columnas)``; una cota constante, extendida a la banda."""
    shapes = [np.shape(values) for values in (band.start, band.final) if np.ndim(values)]
    if not shapes:
        raise ValueError("una banda necesita las filas de al menos una superficie")
    shape = shapes[0]
    if isinstance(band.first_row, bool):
        raise ValueError(f"la primera fila es un entero, no {band.first_row!r}")
    first = operator.index(band.first_row)
    if len(shape) != 2 or shape[1] != grid.ncols or shape[0] < 1 or any(
            other != shape for other in shapes):
        raise ValueError(f"una banda es (filas, {grid.ncols}) en las dos superficies, no "
                         f"{shapes}")
    if first < 0 or first + shape[0] > grid.nrows:
        raise ValueError(f"las filas {first}–{first + shape[0] - 1} no están en la rejilla de "
                         f"{grid.nrows} filas")
    arrays = []
    for values in (band.start, band.final):
        array = np.asarray(values, dtype=np.float64)
        arrays.append(np.broadcast_to(array, shape) if array.ndim == 0 else array)
    return first, arrays[0], arrays[1]


def _unit_range(accumulators: Accumulators, units: slice | None) -> tuple[int, int]:
    """Las unidades ``low … high − 1`` de un trozo (todas sin él)."""
    count = accumulators.units
    if units is None:
        return 0, count
    if not isinstance(units, slice) or units.step not in (None, 1):
        raise ValueError(f"un trozo de unidades es un slice sin paso, no {units!r}")
    low, high = units.start, units.stop
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (low, high)) \
            or not 0 <= low <= high <= count:
        raise ValueError(f"el trozo de unidades {units!r} no está en las {count} de la columna")
    return low, high


def _unit_layers(accumulators: Accumulators, band: BandValues, shape: tuple[int, int]
                 ) -> tuple[list[np.ndarray | None], list[np.ndarray | None]]:
    """Las bases y los espesores de las unidades de la banda, aplanados (float64; ``None`` la
    base de la última y el espesor de las que no son antrópicas), comprobados."""
    count = accumulators.units
    bases, thicknesses = tuple(band.bases), tuple(band.thicknesses)
    if len(bases) != count or len(thicknesses) != count:
        raise ValueError(f"una banda lleva una base y un espesor por unidad ({count}), no "
                         f"{len(bases)} y {len(thicknesses)}")
    if count and (bases[-1] is not None or any(base is None for base in bases[:-1])):
        raise ValueError("la última unidad no tiene base y las demás sí")

    def flat(values: _Layer) -> np.ndarray | None:
        if values is None:
            return None
        array = np.asarray(values, dtype=np.float64)
        if array.ndim == 0:
            return np.full(shape[0] * shape[1], float(array))
        if array.shape != shape:
            raise ValueError(f"una base o un espesor de la banda es {shape}, no {array.shape}")
        return array.ravel()

    return [flat(base) for base in bases], [flat(item) for item in thicknesses]


def _check_thickness(thicknesses: list[np.ndarray | None], low: int, high: int) -> None:
    """:class:`NegativeThickness` si una unidad ``low … high − 1`` tiene un espesor negativo
    (sin dato no es negativo)."""
    for unit in range(low, high):
        values = thicknesses[unit]
        if values is None or not values.size:
            continue
        smallest = float(np.min(values, initial=math.inf, where=~np.isnan(values)))
        if smallest < 0.0:
            raise NegativeThickness(unit, smallest)


def _band_weights(accumulators: Accumulators, weights: Weights | None, rows: slice,
                  height: int) -> tuple[np.ndarray | None, _Entries | None]:
    """La fracción de cada celda dentro del ámbito (``None`` sin él) y las entradas de los
    dominios (``None`` sin ellos), comprobados contra la banda."""
    if weights is None:
        if accumulators.domains:
            raise ValueError(f"una cubicación con {accumulators.domains} dominios necesita "
                             "los pesos de cada banda")
        return None, None
    if (weights.start, weights.stop) != (rows.start, rows.stop):
        raise ValueError(f"los pesos son de las filas {weights.start}–{weights.stop - 1}, no "
                         f"de {rows.start}–{rows.stop - 1}")
    if weights.count != accumulators.domains:
        raise ValueError(f"los pesos son de {weights.count} dominios, no de "
                         f"{accumulators.domains}")
    scope = weights.scope
    if scope is not None and scope.shape != (height, accumulators.grid.ncols):
        raise ValueError(f"el ámbito de los pesos es {scope.shape}")
    if not accumulators.domains:
        return scope, None
    cell = (weights.rows - rows.start) * accumulators.grid.ncols + weights.cols
    return scope, _Entries(cell, weights.domain, weights.weight)


def _add_totals(accumulators: Accumulators, valid: np.ndarray, difference: np.ndarray,
                scope: np.ndarray | None, e: float) -> None:
    """La fila del total. Sin ámbito, como ``volume_between``: las restas de las celdas con dato,
    en un array en el orden de la rejilla, sumado por pares; las áreas, contando celdas."""
    d = difference[valid]
    cut = d > e
    fill = -d > e
    if scope is None:
        accumulators._cut[ALL] += np.sum(np.where(cut, d, 0.0))
        accumulators._fill[ALL] += np.sum(np.where(fill, -d, 0.0))
        moving = int(np.count_nonzero(cut)) + int(np.count_nonzero(fill))
        accumulators._data[ALL] += d.size
        accumulators._nodata[ALL] += valid.size - d.size
        accumulators._still[ALL] += d.size - moving
        return
    w = scope[valid]
    accumulators._cut[ALL] += np.sum(np.where(cut, w * d, 0.0))
    accumulators._fill[ALL] += np.sum(np.where(fill, w * -d, 0.0))
    accumulators._data[ALL] += np.sum(w)
    accumulators._nodata[ALL] += np.sum(scope[~valid])
    accumulators._still[ALL] += np.sum(np.where(cut | fill, 0.0, w))


def _add_domains(accumulators: Accumulators, valid: np.ndarray, difference: np.ndarray,
                 entries: _Entries, e: float) -> None:
    """Las filas de los dominios y de «Fuera de los dominios», con las entradas de la banda."""
    count = accumulators._rows - 1
    with_data = valid.ravel()[entries.cell]
    d = difference.ravel()[entries.cell]
    with np.errstate(invalid="ignore"):
        cut = with_data & (d > e)
        fill = with_data & (-d > e)
    still = with_data & ~cut & ~fill
    domain, weight = entries.domain, entries.weight

    def add(target: np.ndarray, mask: np.ndarray, values: np.ndarray) -> None:
        target[1:] += np.bincount(domain[mask], weights=values, minlength=count)

    add(accumulators._cut, cut, weight[cut] * d[cut])
    add(accumulators._fill, fill, weight[fill] * -d[fill])
    add(accumulators._data, with_data, weight[with_data])
    add(accumulators._nodata, ~with_data, weight[~with_data])
    add(accumulators._still, still, weight[still])


def _add_slices(accumulators: Accumulators, valid: np.ndarray, difference: np.ndarray,
                start: np.ndarray, final: np.ndarray, scope: np.ndarray | None,
                entries: _Entries | None, e: float) -> None:
    """Las rodajas (A3) del total y de cada dominio: los intervalos de desmonte ``[final,
    partida]`` y de terraplén ``[partida, final]`` de las celdas que cuentan en alguna fila."""
    assert accumulators._sides is not None
    flat_valid, flat_d = valid.ravel(), difference.ravel()
    counted = _counted(flat_valid.size, scope, entries)
    flat_start, flat_final = start.ravel(), final.ravel()
    with np.errstate(invalid="ignore"):
        sides = ((flat_valid & (flat_d > e), flat_final, flat_start),
                 (flat_valid & (-flat_d > e), flat_start, flat_final))
    for number, (moving, lower, upper) in enumerate(sides):
        cells = np.flatnonzero(moving & counted)
        if not cells.size:
            continue
        a, b = lower[cells], upper[cells]
        k_a, k_b, low, high = _intervals(accumulators, a, b)
        rows, at, weight = _contributions(cells, flat_valid.size, scope, entries)
        _spread(accumulators, accumulators._sides[number], rows, weight, k_a[at], k_b[at],
                low[at], high[at])


def _counted(size: int, scope: np.ndarray | None, entries: _Entries | None) -> np.ndarray:
    """Las celdas de la banda que cuentan en alguna fila: con peso en el ámbito (todas sin él)
    o en algún dominio."""
    counted = np.ones(size, dtype=bool) if scope is None else scope.ravel() != 0.0
    if entries is not None:
        counted[entries.cell] = True
    return counted


def _contributions(cells: np.ndarray, size: int, scope: np.ndarray | None,
                   entries: _Entries | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Las contribuciones de las celdas ``cells`` (índices planos de la banda) a las filas: la
    del total (las celdas con peso en el ámbito, o todas sin él) y las de los dominios (sus
    entradas). Da la fila, la posición en ``cells`` y el peso de cada una."""
    if scope is None:
        at = np.arange(cells.size)
        weight = np.ones(cells.size)
    else:
        all_weight = scope.ravel()
        at = np.flatnonzero(all_weight[cells] != 0.0)
        weight = all_weight[cells[at]]
    rows = np.full(at.size, ALL, dtype=np.int64)
    if entries is not None:
        position = np.full(size, -1, dtype=np.int64)
        position[cells] = np.arange(cells.size)
        found = position[entries.cell]
        used = found >= 0
        rows = np.concatenate([rows, entries.domain[used] + 1])
        at = np.concatenate([at, found[used]])
        weight = np.concatenate([weight, entries.weight[used]])
    return rows, at, weight


def _add_units(accumulators: Accumulators, valid: np.ndarray, difference: np.ndarray,
               start: np.ndarray, final: np.ndarray, scope: np.ndarray | None,
               entries: _Entries | None, e: float, bases: list[np.ndarray | None],
               thicknesses: list[np.ndarray | None], low: int, high: int) -> None:
    """Las unidades ``low … high − 1`` (A7) en las celdas de desmonte de la banda: su volumen,
    sus áreas (ausente, sin dato y cruce) y sus rodajas, en el total y en cada dominio. El techo
    de la primera del trozo sale de las bases de las de encima, así que los trozos dan lo mismo
    que la banda entera."""
    flat_valid, flat_d = valid.ravel(), difference.ravel()
    with np.errstate(invalid="ignore"):
        cut = flat_valid & (flat_d > e)
    cells = np.flatnonzero(cut & _counted(flat_valid.size, scope, entries))
    if not cells.size:
        return
    rows = _UnitRows.of(cells, flat_valid.size, scope, entries, accumulators._rows - 1)
    lower, upper = final.ravel()[cells], start.ravel()[cells]
    top = np.full(cells.size, math.inf)
    with np.errstate(invalid="ignore"):
        for unit in range(high):
            layer = bases[unit]
            if layer is None:  # la última: llega hasta abajo
                base = np.full(cells.size, -math.inf)
                missing = np.zeros(cells.size, dtype=bool)
            else:
                base = layer[cells]
                missing = ~np.isfinite(base)
            present = ~missing
            thickness = thicknesses[unit]
            if thickness is not None:
                values = thickness[cells]
                finite = np.isfinite(values)
                missing |= ~finite
                present &= finite & (values > accumulators.presence_m)
            effective = np.minimum(base, top)
            if unit >= low:
                bottom = np.maximum(effective, lower)
                ceiling = np.minimum(top, upper)
                piece = present & (ceiling > bottom)
                rows.add(accumulators._unit_volume, unit, piece, ceiling - bottom)
                rows.add(accumulators._unit_absent, unit, ~present)
                rows.add(accumulators._unit_nodata, unit, missing)
                rows.add(accumulators._unit_crossed, unit, present & (base > top))
                if accumulators._unit_side is not None and piece.any():
                    _add_unit_slices(accumulators, unit, np.flatnonzero(piece), bottom, ceiling,
                                     rows)
            top = np.where(present, effective, top)


@dataclass(frozen=True, slots=True, eq=False)
class _UnitRows:
    """Cómo suman las celdas de desmonte de una banda (``cells``, índices planos) a las filas:
    al total, cada una con su peso en el ámbito (``scope``: ``None`` sin él, todas con 1), y a
    los dominios, por sus entradas (``entries``: la posición en ``cells``, el dominio y el peso;
    ``None`` sin dominios)."""

    scope: np.ndarray | None
    entries: tuple[np.ndarray, np.ndarray, np.ndarray] | None
    count: int

    @classmethod
    def of(cls, cells: np.ndarray, size: int, scope: np.ndarray | None,
           entries: _Entries | None, count: int) -> _UnitRows:
        found = None
        if entries is not None:
            position = np.full(size, -1, dtype=np.int64)
            position[cells] = np.arange(cells.size)
            at = position[entries.cell]
            used = at >= 0
            found = (at[used], entries.domain[used], entries.weight[used])
        return cls(None if scope is None else scope.ravel()[cells], found, count)

    def add(self, target: np.ndarray, unit: int, mask: np.ndarray,
            values: np.ndarray | None = None) -> None:
        """Suma a la columna ``unit`` de ``target`` las celdas de ``mask`` (``values`` en ellas;
        sin ``values``, su área: 1 por celda), por su peso: el total, directamente; los
        dominios, por sus entradas."""
        chosen = np.flatnonzero(mask)
        if not chosen.size:
            return
        if self.scope is None:
            target[ALL, unit] += (chosen.size if values is None else np.sum(values[chosen]))
        else:
            weight = self.scope[chosen]
            target[ALL, unit] += np.sum(weight if values is None else weight * values[chosen])
        if self.entries is None:
            return
        at, domain, weight = self.entries
        used = mask[at]
        weight = weight[used] if values is None else weight[used] * values[at[used]]
        target[1:, unit] += np.bincount(domain[used], weights=weight, minlength=self.count)


def _add_unit_slices(accumulators: Accumulators, unit: int, inside: np.ndarray,
                     bottom: np.ndarray, ceiling: np.ndarray, rows: _UnitRows) -> None:
    """Las rodajas (A3) del trozo ``[bottom, ceiling]`` de la unidad ``unit`` en las celdas de
    desmonte ``inside`` (sus posiciones), en el total y en cada dominio."""
    assert accumulators._unit_side is not None
    k_a, k_b, low, high = _intervals(accumulators, bottom[inside], ceiling[inside])
    at = np.arange(inside.size)
    row = np.full(inside.size, ALL, dtype=np.int64)
    weight = np.ones(inside.size) if rows.scope is None else rows.scope[inside]
    if rows.entries is not None:
        position = np.full(bottom.size, -1, dtype=np.int64)
        position[inside] = at
        cell, domain, entry_weight = rows.entries
        found = position[cell]
        used = found >= 0
        row = np.concatenate([row, domain[used] + 1])
        at = np.concatenate([at, found[used]])
        weight = np.concatenate([weight, entry_weight[used]])
    _spread(accumulators, accumulators._unit_side, row * accumulators.units + unit, weight,
            k_a[at], k_b[at], low[at], high[at])


def _intervals(accumulators: Accumulators, a: np.ndarray,
               b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Las rodajas ``k_a`` y ``k_b`` de los extremos de los intervalos ``[a, b]`` (``b > a``;
    el de arriba justo en una cota, a la de abajo) y lo que cae en ``k_a`` y en ``k_b``; amplía
    las columnas de lo sumado y el rango cubicado."""
    slices = accumulators.slices
    assert slices is not None
    low_z, high_z = float(np.min(a)), float(np.max(b))
    accumulators._zmin = min(accumulators._zmin, low_z)
    accumulators._zmax = max(accumulators._zmax, high_z)
    if slices.levels is None:
        levels = bounds(slices, low_z, high_z)
        first = int(index(slices, levels[0]))
    else:
        levels, first = np.array(slices.levels, dtype=np.float64), 0
    last = levels.size - 1
    k_a = index(slices, a)
    k_b = index(slices, b)
    at_b = k_b - first
    on_level = (at_b >= 0) & (levels[np.clip(at_b, 0, last)] == b)
    k_b = k_b - on_level
    same = k_a == k_b
    above_a = levels[np.clip(k_a + 1 - first, 0, last)]
    below_b = levels[np.clip(k_b - first, 0, last)]
    low = np.where(same, b - a, above_a - a)
    high = np.where(same, 0.0, b - below_b)
    if slices.levels is None:
        accumulators._grow(int(np.min(k_a)), int(np.max(k_b)))
    return k_a, k_b, low, high


def _spread(accumulators: Accumulators, side: _Spread, rows: np.ndarray, weight: np.ndarray,
            k_a: np.ndarray, k_b: np.ndarray, low: np.ndarray, high: np.ndarray) -> None:
    """Reparte en ``side`` los intervalos con su fila y su peso: el trozo de abajo en ``k_a``,
    el de arriba en ``k_b`` y las rodajas enteras de en medio por diferencias acumuladas."""
    count, width = side.part.shape
    size = count * width
    column_a = k_a - accumulators._k_low
    column_b = k_b - accumulators._k_low
    side.part += np.bincount(rows * width + column_a, weights=low * weight,
                             minlength=size).reshape(count, width)
    many = k_a != k_b
    if not many.any():
        return
    side.part += np.bincount(rows[many] * width + column_b[many],
                             weights=high[many] * weight[many],
                             minlength=size).reshape(count, width)
    inner = (k_b - k_a) > 1
    if not inner.any():
        return
    base = rows[inner] * width
    side.whole += (np.bincount(base + column_a[inner] + 1, weights=weight[inner],
                               minlength=size)
                   - np.bincount(base + column_b[inner], weights=weight[inner],
                                 minlength=size)).reshape(count, width)
