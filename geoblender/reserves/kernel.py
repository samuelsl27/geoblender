# SPDX-License-Identifier: GPL-3.0-or-later
"""El núcleo de la cubicación: totales, umbral, dominios y rodajas en una sola pasada por bandas
de filas (spec 011; RF-011-01, RF-011-04, RF-011-07, RF-011-09, RF-011-10; plan 011 A2, A3 y
D-20).

Una cubicación es **un solo cálculo** celda a celda (RF-011-10): las dos superficies se leen por
bandas de filas y cada banda se suma, de una vez, a todos los repartos, con las mismas
superficies, el mismo ámbito y el mismo espesor mínimo.

- :class:`Accumulators`: lo que se lleva sumado (float64), con la rejilla, las rodajas, el
  número de dominios y el espesor mínimo de la cubicación, fijados al crearlo.
- :class:`BandValues`: las cotas de una banda de filas de la superficie de partida y de la final
  (una cota constante, como un número).
- :func:`band_step`: suma una banda (A2, A3), con los pesos de ``reserves.polygons.weights``
  si hay ámbito o dominios.
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
    "band_step",
]

ALL = 0
"""La fila del total de la cubicación (``'*'`` en la tabla)."""


@dataclass(frozen=True, slots=True, eq=False)
class BandValues:
    """Las cotas (m, float64) de la banda de filas que empieza en ``first_row`` (la fila 0 es la
    del norte): ``start``, la superficie de partida, y ``final``, la final, arrays ``(filas,
    columnas)`` de la rejilla (NaN = sin dato) o un número (una cota constante)."""

    first_row: int
    start: np.ndarray | float
    final: np.ndarray | float


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
      ``(filas,)``, lo que queda fuera de una lista de cotas (ceros con altura y anclaje)."""

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


@dataclass(eq=False)
class Accumulators:
    """Lo sumado de una cubicación (float64), con lo que la fija: la rejilla (``grid``), las
    rodajas (``slices``; ``None`` sin ellas), el número de dominios de los pesos (``domains``;
    0 sin ellos) y el espesor mínimo (``min_thickness_m``, m, un número finito ≥ 0; si no,
    ``ValueError``). Cada fila de la rejilla se suma una vez (:func:`band_step`);
    :meth:`result` da las cifras cuando están todas."""

    grid: Grid
    slices: Slices | None = None
    domains: int = 0
    min_thickness_m: float = 0.0
    _rows: int = field(init=False)
    _seen: np.ndarray = field(init=False)
    _cut: np.ndarray = field(init=False)
    _fill: np.ndarray = field(init=False)
    _data: np.ndarray = field(init=False)
    _nodata: np.ndarray = field(init=False)
    _still: np.ndarray = field(init=False)
    _k_low: int = field(init=False, default=0)
    _sides: tuple[_Spread, _Spread] | None = field(init=False, default=None)
    _zmin: float = field(init=False, default=math.inf)
    _zmax: float = field(init=False, default=-math.inf)

    def __post_init__(self) -> None:
        thickness = self.min_thickness_m
        if isinstance(thickness, bool) or not isinstance(
                thickness, int | float | np.integer | np.floating):
            raise ValueError(f"min_thickness_m es un número, no {thickness!r}")
        self.min_thickness_m = float(thickness)
        if not (math.isfinite(self.min_thickness_m) and self.min_thickness_m >= 0.0):
            raise ValueError(f"min_thickness_m es un número finito ≥ 0, no {thickness!r}")
        if isinstance(self.domains, bool) or not isinstance(self.domains, int | np.integer) \
                or self.domains < 0:
            raise ValueError(f"domains es un entero ≥ 0, no {self.domains!r}")
        if self.slices is not None and not isinstance(self.slices, Slices):
            raise ValueError(f"slices es un reserves.slices.Slices, no {self.slices!r}")
        self.domains = int(self.domains)
        self._rows = 1 if self.domains == 0 else self.domains + 2
        self._seen = np.zeros(self.grid.nrows, dtype=bool)
        self._cut, self._fill, self._data, self._nodata, self._still = (
            np.zeros(self._rows) for _ in range(5))
        if self.slices is not None:
            width = 0
            if self.slices.levels is not None:  # −1 (abajo), 0 … n − 1 y n (arriba)
                self._k_low, width = -1, len(self.slices.levels) + 1
            self._sides = (self._spread(width), self._spread(width))

    def _spread(self, width: int) -> _Spread:
        return _Spread(np.zeros((self._rows, width)), np.zeros((self._rows, width)))

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
        self._sides = tuple(_Spread(np.pad(side.part, pad), np.pad(side.whole, pad))
                            for side in self._sides)  # type: ignore[assignment]
        self._k_low = first

    def result(self) -> KernelResult:
        """Las cifras de la cubicación (m³ y m²): ``ValueError`` si falta alguna fila de la
        rejilla por sumar."""
        if not self._seen.all():
            missing = int(np.count_nonzero(~self._seen))
            raise ValueError(f"faltan {missing} filas de la rejilla por sumar")
        area = self.grid.cell_area
        cut, fill = self._cut * area, self._fill * area
        totals = {
            "cut_m3": cut, "fill_m3": fill, "net_m3": cut - fill,
            "area_m2": self._data * area, "nodata_area_m2": self._nodata * area,
            "still_area_m2": self._still * area,
        }
        if self.slices is None or self._sides is None:
            return KernelResult(area, self.domains, **totals)
        levels, columns = self._bounds()
        thickness = np.diff(levels)
        figures: dict[str, np.ndarray] = {}
        for name, side in zip(("cut", "fill"), self._sides, strict=True):
            whole = np.cumsum(side.whole, axis=1)
            figures[f"slice_{name}_m3"] = (_take(side.part, columns)
                                           + _take(whole, columns) * thickness) * area
            for edge, column in zip(("below", "above"), self._edge_columns(), strict=True):
                found = np.zeros(self._rows) if column is None else side.part[:, column]
                figures[f"{edge}_{name}_m3"] = found * area
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


def band_step(accumulators: Accumulators, band: BandValues,
              weights: Weights | None = None) -> None:
    """Suma la banda ``band`` a ``accumulators`` (A2, A3): totales, áreas, dominios y rodajas, en
    un solo cálculo (RF-011-10). ``weights`` son los de ``reserves.polygons.weights`` para esa
    banda (su ámbito y sus entradas celda-dominio-peso), ``None`` sin ámbito ni dominios; con
    dominios hacen falta.

    Son errores del programa (``ValueError``, sin sumar nada): una banda que no es de la anchura
    de la rejilla o se sale de ella, que repite filas ya sumadas, o unos pesos de otra banda, de
    otro número de dominios o que faltan."""
    grid = accumulators.grid
    first, start, final = _band_arrays(band, grid)
    rows = slice(first, first + start.shape[0])
    scope, entries = _band_weights(accumulators, weights, rows, start.shape[0])
    if accumulators._seen[rows].any():
        raise ValueError(f"las filas {rows.start}–{rows.stop - 1} ya se sumaron")
    accumulators._seen[rows] = True
    e = accumulators.min_thickness_m
    valid = np.isfinite(start) & np.isfinite(final)
    with np.errstate(invalid="ignore"):
        difference = start - final
    _add_totals(accumulators, valid, difference, scope, e)
    if entries is not None:
        _add_domains(accumulators, valid, difference, entries, e)
    if accumulators.slices is not None:
        _add_slices(accumulators, valid, difference, start, final, scope, entries, e)


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
    counted = np.ones(flat_valid.size, dtype=bool) if scope is None else scope.ravel() != 0.0
    if entries is not None:
        counted[entries.cell] = True
    all_weight = None if scope is None else scope.ravel()
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
        # Las contribuciones: la fila del total (las celdas con peso) y las de los dominios.
        if all_weight is None:
            at = np.arange(cells.size)
            weight = np.ones(cells.size)
        else:
            at = np.flatnonzero(all_weight[cells] != 0.0)
            weight = all_weight[cells[at]]
        rows = np.full(at.size, ALL, dtype=np.int64)
        if entries is not None:
            position = np.full(flat_valid.size, -1, dtype=np.int64)
            position[cells] = np.arange(cells.size)
            found = position[entries.cell]
            used = found >= 0
            rows = np.concatenate([rows, entries.domain[used] + 1])
            at = np.concatenate([at, found[used]])
            weight = np.concatenate([weight, entries.weight[used]])
        _spread(accumulators, accumulators._sides[number], rows, weight, k_a[at], k_b[at],
                low[at], high[at])


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
