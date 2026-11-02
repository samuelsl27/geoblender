# SPDX-License-Identifier: GPL-3.0-or-later
"""Las envolventes de pendiente acotada: el *chamfer* 5×5 por filas (spec 013; RF-013-11,
RF-013-12, RF-013-13, RF-013-15; plan 013 A2, A3, A4, D-21, D-33; ADR-0014).

La envolvente **ascendente** de unas semillas es ``E↑(p) = mín_q [s(q) + t·d(p, q)]`` (la mayor
superficie que no pasa de ellas con esa pendiente) y la **descendente**, ``E↓(p) = máx_q [s(q) −
t·d(p, q)] = −E↑(−s)``. La distancia ``d`` es la del *chamfer* 5×5 de la rejilla de paso exacto
(ADR-0014): los 16 desplazamientos de la máscara de 5×5 con los pesos 1, √2 y √5 por la escala
``0,98644`` y el paso ``h``, que la dejan a −1,356 % … +1,355 % de la euclídea (RF-013-12: ≤ 1,4 %).
**Nunca el *chamfer* 3×3.** Una pared alineada con la rejilla queda así un 1,356 % corta a lo largo
del eje; la exactitud de la pared es de la euclídea exacta (T08).

- **La pendiente por celda** (A2): :class:`SlopeField` es la tangente efectiva de cada celda, la
  pedida por la persona por el factor de malla del perfil (RF-013-11): una constante
  (:func:`constant_slope`) o, en el modo por sectores, el talud general de cada sector —el
  máximo impuesto o el de su perfil— pintado con las etiquetas de sector (:func:`sector_slope`; un
  :class:`SlopeRule` por sector y otro para las celdas sin sector). **Entrar en una celda cuesta
  con la tangente de la celda de llegada**, de modo que un sector más tendido gobierna sus propias
  paredes. Quien llama resuelve antes qué talud tiene cada sector (``design.sectors.imposed_slopes``
  y el perfil asignado): aquí no se lee ningún parámetro.
- **El barrido** (A3, D-21): por filas, con ``np.cumsum`` y ``np.minimum.accumulate`` para la
  propagación dentro de la fila; ida de arriba abajo y vuelta de abajo arriba, repetidas hasta el
  punto fijo (con una pendiente constante basta una vuelta; con sectores, de 2 a 8). Cada unidad
  de trabajo son las filas que caben en ``CELLS_PER_UNIT`` celdas y se agrupan en pasos de
  ``budget_s`` como mucho (``gis.masks.compile.pace_units``). Todo en float64; cada llamada da un
  array nuevo y no se modifica ninguna entrada.
- **La comprobación de RF-013-15** (A4), en cada ejecución: tras cada vuelta, la mayor violación de
  las 16 relajaciones ``E(p) ≤ E(q) + coste(q → p)`` (equivale a «usar la envolvente como semilla en
  todas sus celdas no cambia ninguna más de 10⁻⁹ m», y a que entre vecinas no se pasa la pendiente
  efectiva: los pesos de vecino son menores que la distancia); al terminar, que en cada semilla
  ``E↑ ≤ f`` (``E↓ ≥ f``), exactamente. Si tras :data:`MAX_ITERATIONS` vueltas aún falla, o falla
  una semilla, es un ``DesignError`` con la celda absoluta y la diferencia (m) y **no se entrega
  nada**.

- **El alcance** (RF-013-14, A6): :func:`reach_steps` da la distancia a la semilla más próxima con
  la misma métrica y ``t = 1`` (el *chamfer* con costes de entrada ``(1, √2, √5)·h·escala``) y
  ``NaN`` donde pasa del alcance; :func:`envelope_steps` deja sin dato (``NaN``) las celdas de la
  envolvente que pasan de él, que es el tope de la propagación (errores 17, 31 y 66). Sin alcance,
  ninguno. Todas las semillas cuentan, también las que quedan fuera del dominio de trabajo (el
  recorte al dominio es posterior).
- **Los rechazos de RF-013-16**, antes de calcular y sin registrar nada: :func:`check_request` (la
  pendiente, el factor de malla, el alcance y la euclídea exacta con sectores: lo que no necesita
  leer nada) y :func:`check_seed_set` (unas semillas sin ninguna celda con cota finita, un dominio
  de trabajo vacío) salen, como ``DesignError`` que nombra la envolvente, el campo y el valor y la
  orden que lo resuelve, al avanzar :func:`envelope_steps`, antes de ceder un solo paso. Que las
  semillas o la superficie de partida estén en otra rejilla, CRS o datum vertical lo rechaza antes
  ``design.surfaces`` al leerlas (``des.surface_mismatch``).

Python puro (nivel 8), con numpy. La euclídea exacta es de T08.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .messages import DesignError
from .model import Direction, EnvelopeRequest, Metric, SlopeMode
from .seeds import SeedSet, pace_progress

__all__ = [
    "CELLS_PER_UNIT",
    "CHAMFER_SCALE",
    "MAX_ITERATIONS",
    "TOLERANCE_M",
    "Envelope",
    "SlopeField",
    "SlopeRule",
    "chamfer_steps",
    "check_envelope",
    "check_request",
    "check_seed_set",
    "constant_slope",
    "envelope_steps",
    "reach_steps",
    "request_slope",
    "sector_slope",
]

CHAMFER_SCALE = 0.98644
"""La escala del *chamfer* 5×5 (ADR-0014): el error de distancia queda en −1,356 % … +1,355 %."""
TOLERANCE_M = 1e-9
"""τ de D-33: lo que puede violar una relajación (m) para tener por convergida una envolvente."""
MAX_ITERATIONS = 8
"""Las vueltas (ida y vuelta) como mucho hasta el punto fijo (A3)."""
CELLS_PER_UNIT = 400_000
"""Las celdas de una unidad de trabajo de un barrido (≈ 10 ms); la comprobación usa la cuarta
parte, porque cada celda cuesta unas cuatro veces más."""

_SQRT2 = math.sqrt(2.0)
_SQRT5 = math.sqrt(5.0)
_OBJECT = "Envolvente"
_FIELD = "punto fijo"
_SEED_FIELD = "semilla"
_ROUNDED_M = 3  # decimales de las coordenadas que se dicen (mm)
_SLOPE_FIELD = "slope_deg"
_MESH_FIELD = "mesh_factor"
_REACH_FIELD = "reach_m"
_MODE_FIELD = "slope_mode"
_SEEDS_FIELD = "seeds"
_DOMAIN_FIELD = "domain"
_NO_VALUE = "—"

Mask = tuple[tuple[int, int, float], ...]


def _mask() -> Mask:
    """Los 16 desplazamientos de la máscara 5×5 del *chamfer* con su peso (en celdas): 4 de eje
    (1), 4 diagonales (√2) y 8 de caballo (√5)."""
    found: list[tuple[int, int, float]] = []
    for sign_row in (1, -1):
        for sign_col in (1, -1):
            found.append((sign_row, sign_col, _SQRT2))
            found.append((2 * sign_row, sign_col, _SQRT5))
            found.append((sign_row, 2 * sign_col, _SQRT5))
    for sign in (1, -1):
        found.append((sign, 0, 1.0))
        found.append((0, sign, 1.0))
    return tuple(found)


_MASK: Mask = _mask()


# --- La pendiente por celda (A2) ---------------------------------------------------------------


def _tan_of(degrees: float) -> float:
    """``tan`` de una pendiente en grados de 0 (incluido) a 90 (excluido); ``ValueError`` si no."""
    value = float(degrees)
    if not math.isfinite(value) or not 0.0 <= value < 90.0:
        raise ValueError("la pendiente debe ser un número de 0 (incluido) a 90 (excluido) "
                         f"grados, no {degrees!r}")
    return math.tan(math.radians(value))


def _mesh_of(factor: float) -> float:
    """El factor de malla, entre 0 (excluido) y 1; ``ValueError`` si no."""
    value = float(factor)
    if not math.isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError(f"el factor de malla debe estar entre 0 (excluido) y 1, no {factor!r}")
    return value


@dataclass(frozen=True, slots=True)
class SlopeRule:
    """La pendiente de un sector (o de las celdas sin sector): la tangente de su talud general
    ``tan`` (el máximo impuesto, ``tan β``, o el de su perfil, ``h / avance``) y el ``mesh_factor``
    de su perfil (—, entre 0 excluido y 1). La efectiva es su producto (RF-013-11)."""

    tan: float
    mesh_factor: float = 1.0

    def __post_init__(self) -> None:
        value = float(self.tan)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"la tangente del talud debe ser un número finito ≥ 0, no "
                             f"{self.tan!r}")
        object.__setattr__(self, "tan", value)
        object.__setattr__(self, "mesh_factor", _mesh_of(self.mesh_factor))

    @classmethod
    def from_degrees(cls, degrees: float, mesh_factor: float = 1.0) -> SlopeRule:
        """La regla de un talud en grados (de 0, incluido, a 90, excluido)."""
        return cls(_tan_of(degrees), mesh_factor)

    @property
    def effective(self) -> float:
        """``tan · mesh_factor``: la tangente con la que se entra en la celda."""
        return self.tan * self.mesh_factor


@dataclass(frozen=True, slots=True, eq=False)
class SlopeField:
    """La tangente efectiva de la pendiente (con el factor de malla) para entrar en cada celda
    (A2): un escalar (``uniform``: la misma en toda la rejilla) o un mapa de la forma de la rejilla
    (``float64``, finito y ≥ 0). Nunca se modifica (ni se copia más de lo necesario)."""

    tan: float | np.ndarray

    def __post_init__(self) -> None:
        values = np.asarray(self.tan, dtype=np.float64)
        if values.ndim == 0:
            object.__setattr__(self, "tan", float(values))
        elif values.ndim == 2:
            object.__setattr__(self, "tan", values)
        else:
            raise ValueError(f"la pendiente es un número o un mapa de 2 dimensiones, no de "
                             f"{values.ndim}")
        if not np.isfinite(values).all() or (values < 0.0).any():
            raise ValueError("la pendiente (tan) debe ser finita y ≥ 0 en todas las celdas")

    @property
    def uniform(self) -> bool:
        """Si es la misma en toda la rejilla (un escalar)."""
        return not isinstance(self.tan, np.ndarray)

    @property
    def max_tan(self) -> float:
        """La mayor tangente efectiva de la rejilla."""
        return float(np.max(self.tan))


def constant_slope(degrees: float, mesh_factor: float = 1.0) -> SlopeField:
    """La pendiente constante de ``degrees`` (de 0, incluido, a 90, excluido) por el factor de
    malla (RF-013-11, RF-013-13). ``ValueError`` si no son de su rango: el rechazo para la persona
    (RF-013-16) lo hace quien arma la petición."""
    return SlopeField(_tan_of(degrees) * _mesh_of(mesh_factor))


def sector_slope(labels: np.ndarray, rules: Sequence[SlopeRule | None],
                 base: SlopeRule | None = None) -> SlopeField:
    """La pendiente por sectores (RF-013-13, A2): cada celda toma la regla de su sector —la
    etiqueta ``k`` (1 a n, como ``design.seeds.DomainSet.labels``) es ``rules[k − 1]``— y las
    celdas de etiqueta 0, sin sector, la regla ``base`` (la del perfil base, RF-013-21). Una regla
    ``None`` es un sector sin pendiente resuelta: ``ValueError`` solo si alguna celda lo usa, como
    una etiqueta que no es de ningún sector o negativa, o celdas sin sector sin ``base``. Las
    etiquetas no se modifican; la rejilla es nueva."""
    codes = np.asarray(labels)
    if codes.ndim != 2 or codes.dtype.kind not in "iu":
        raise ValueError("las etiquetas de sector son una rejilla de enteros de 2 dimensiones")
    if codes.size and int(codes.min()) < 0:
        raise ValueError("hay etiquetas de sector negativas")
    counts = np.bincount(codes.ravel(), minlength=len(rules) + 1)
    if counts.size > len(rules) + 1:
        raise ValueError(f"hay etiquetas de sector hasta {counts.size - 1} y solo {len(rules)} "
                         "reglas")
    table = np.full(len(rules) + 1, np.nan)
    if base is not None:
        table[0] = base.effective
    for index, rule in enumerate(rules, start=1):
        if rule is not None:
            table[index] = rule.effective
    missing = [index for index in range(table.size) if counts[index] > 0 and np.isnan(table[index])]
    if missing:
        raise ValueError("celdas sin pendiente resuelta: " + ", ".join(
            "las que no son de ningún sector" if index == 0 else f"el sector {index}"
            for index in missing))
    return SlopeField(table[codes])


# --- El resultado ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Envelope:
    """Una envolvente calculada: ``grid`` (m, float64, nueva, de la forma de la rejilla; ``+inf``
    —``−inf`` en la descendente— donde no hay envolvente porque no hay semilla alguna y ``NaN``
    donde pasa del alcance, RF-013-14), las ``iterations`` (vueltas de ida y vuelta) y la
    ``violation`` (m): la mayor violación de las relajaciones, que es ≤ :data:`TOLERANCE_M`."""

    grid: np.ndarray
    iterations: int
    violation: float


# --- Los costes de entrar en una celda ---------------------------------------------------------


class _Weights:
    """Los costes de entrar en una celda por un desplazamiento de eje (``a``), diagonal (``b``) o de
    caballo (``c``): ``t(llegada)·h·escala·(1, √2, √5)``, de una fila (``forward``/``backward``,
    con la suma acumulada de ``a`` en el sentido de la fila) y, para la comprobación, ``unit``
    (``t·h·escala``: un escalar o el mapa entero)."""

    def __init__(self, slope: SlopeField, ncols: int, step: float) -> None:
        scale = step * CHAMFER_SCALE
        if isinstance(slope.tan, np.ndarray):
            self.unit: float | np.ndarray = slope.tan * scale
            self._row: tuple[np.ndarray, ...] | None = None
        else:
            value = slope.tan * scale
            self.unit = value
            axis = np.full(ncols, value)
            self._row = (axis, axis * _SQRT2, axis * _SQRT5, np.cumsum(axis))

    def forward(self, row: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if self._row is not None:
            return self._row  # type: ignore[return-value]
        assert isinstance(self.unit, np.ndarray)
        axis = self.unit[row]
        return axis, axis * _SQRT2, axis * _SQRT5, np.cumsum(axis)

    def backward(self, row: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if self._row is not None:
            return self._row  # type: ignore[return-value]
        assert isinstance(self.unit, np.ndarray)
        axis = self.unit[row]
        return axis, axis * _SQRT2, axis * _SQRT5, np.cumsum(axis[::-1])


def _spread(row: np.ndarray, sums: np.ndarray) -> None:
    """La propagación dentro de una fila: ``D[x] = mín(D[x], W[x] + mín_{j < x}(D[j] − W[j]))`` con
    ``W`` la suma acumulada de los costes de entrada (en el sentido de la fila). Sin el término
    ``j = x`` y con el ``mín`` con lo que había, un valor nunca sube ni se redondea: una semilla
    que nadie baja conserva su cota exactamente."""
    spread = row - sums
    np.minimum.accumulate(spread, out=spread)
    spread[:-1] += sums[1:]
    np.minimum(row[1:], spread[:-1], out=row[1:])


def _relax(row: np.ndarray, near: np.ndarray, far: np.ndarray | None, axis: np.ndarray,
           diagonal: np.ndarray, knight: np.ndarray) -> None:
    """Los candidatos de una fila desde la anterior ``near`` (5 vecinos: ``x−2 … x+2``) y la
    anterior a esa ``far`` (``x ± 1``), ya con sus costes de entrada."""
    cand = near + axis
    np.minimum(cand[1:], near[:-1] + diagonal[1:], out=cand[1:])
    np.minimum(cand[:-1], near[1:] + diagonal[:-1], out=cand[:-1])
    np.minimum(cand[2:], near[:-2] + knight[2:], out=cand[2:])
    np.minimum(cand[:-2], near[2:] + knight[:-2], out=cand[:-2])
    if far is not None:
        np.minimum(cand[1:], far[:-1] + knight[1:], out=cand[1:])
        np.minimum(cand[:-1], far[1:] + knight[:-1], out=cand[:-1])
    np.minimum(row, cand, out=row)


def _forward_rows(values: np.ndarray, weights: _Weights, start: int, stop: int) -> None:
    """La ida sobre las filas ``start … stop − 1`` (de arriba abajo, propagando de izquierda a
    derecha)."""
    for index in range(start, stop):
        axis, diagonal, knight, sums = weights.forward(index)
        row = values[index]
        if index >= 1:
            _relax(row, values[index - 1], values[index - 2] if index >= 2 else None, axis,
                   diagonal, knight)
        _spread(row, sums)


def _backward_rows(values: np.ndarray, weights: _Weights, start: int, stop: int) -> None:
    """La vuelta sobre las filas ``stop − 1 … start`` (de abajo arriba, propagando de derecha a
    izquierda)."""
    last = values.shape[0] - 1
    for index in range(stop - 1, start - 1, -1):
        axis, diagonal, knight, sums = weights.backward(index)
        row = values[index]
        if index <= last - 1:
            _relax(row, values[index + 1], values[index + 2] if index <= last - 2 else None,
                   axis, diagonal, knight)
        _spread(row[::-1], sums)


def _sweep(values: np.ndarray, weights: _Weights, rows: int, *, forward: bool
           ) -> Generator[None, None, None]:
    """Una pasada completa (ida o vuelta) en unidades de ``rows`` filas."""
    nrows = values.shape[0]
    for first in range(0, nrows, rows):
        stop = min(first + rows, nrows)
        if forward:
            _forward_rows(values, weights, first, stop)
        else:
            _backward_rows(values, weights, nrows - stop, nrows - first)
        yield None


# --- La comprobación de RF-013-15 (A4) ---------------------------------------------------------


def _band_worst(values: np.ndarray, unit: float | np.ndarray, start: int, stop: int, *,
                locate: bool = False) -> tuple[float, int, int]:
    """La mayor violación (m, ≥ 0) de las 16 relajaciones ``E(p) ≤ E(q) + peso·coste(p)`` con ``p``
    en las filas ``start … stop − 1``; con ``locate``, también la fila y la columna de ``p``."""
    nrows, ncols = values.shape
    worst, where = 0.0, (0, 0)
    with np.errstate(invalid="ignore"):  # inf − inf: sin envolvente en los dos lados
        for d_row, d_col, weight in _MASK:
            first, last = max(start, d_row), min(stop, nrows + d_row)
            left, right = max(d_col, 0), ncols + min(d_col, 0)
            if first >= last or left >= right:
                continue
            arrival = values[first:last, left:right]
            origin = values[first - d_row:last - d_row, left - d_col:right - d_col]
            if isinstance(unit, np.ndarray):
                excess = unit[first:last, left:right] * weight
                excess += origin
            else:
                excess = origin + weight * unit
            np.subtract(arrival, excess, out=excess)
            top = float(np.fmax.reduce(excess, axis=None))
            if top > worst:
                worst = top
                if locate:
                    cell = int(np.argmax(np.where(np.isnan(excess), -np.inf, excess)))
                    where = (first + cell // (right - left), left + cell % (right - left))
    return worst, where[0], where[1]


def _violation_units(values: np.ndarray, weights: _Weights, rows: int
                     ) -> Generator[None, None, float]:
    """La mayor violación de las relajaciones de toda la rejilla, en unidades de ``rows`` filas."""
    worst = 0.0
    for first in range(0, values.shape[0], rows):
        worst = max(worst, _band_worst(values, weights.unit, first,
                                       min(first + rows, values.shape[0]))[0])
        yield None
    return worst


def _position(geometry: Grid, row: int, col: int) -> tuple[float, float]:
    """El centro (x, y) absoluto de la celda ``(row, col)`` en float64, al milímetro."""
    return (round(geometry.west + (col + 0.5) * geometry.dx, _ROUNDED_M),
            round(geometry.north - (row + 0.5) * geometry.dy, _ROUNDED_M))


def _shown(value: float) -> float:
    """Una diferencia (m) con tres cifras significativas, para decirla."""
    return float(f"{value:.3g}")


def _name_of(name: str) -> str:
    return f"{_OBJECT} «{name}»" if name else _OBJECT


def _not_fixed_point(values: np.ndarray, weights: _Weights, geometry: Grid, name: str,
                     iterations: int | None, tolerance: float, rows: int) -> DesignError:
    """El error de una envolvente que no es un punto fijo, con la celda más violada."""
    best = (0.0, 0, 0)
    for first in range(0, values.shape[0], rows):
        found = _band_worst(values, weights.unit, first, min(first + rows, values.shape[0]),
                            locate=True)
        if found[0] > best[0]:
            best = found
    diff, row, col = best
    x, y = _position(geometry, row, col)
    return DesignError("des.envelope_not_fixed_point", obj=_name_of(name), field=_FIELD,
                       value=_shown(diff), envelope=name, row=row, col=col, x=x, y=y,
                       tolerance=tolerance, iterations=iterations)


def _seed_error(values: np.ndarray, seed: np.ndarray, direction: Direction, geometry: Grid,
                name: str, cells: np.ndarray, excess: np.ndarray) -> DesignError:
    """El error de una semilla que queda del lado equivocado de su cota."""
    pick = int(np.argmax(excess))
    row, col = divmod(int(cells[pick]), values.shape[1])
    x, y = _position(geometry, row, col)
    code = ("des.envelope_seed_above" if direction is Direction.UP
            else "des.envelope_seed_below")
    return DesignError(code, obj=_name_of(name), field=_SEED_FIELD,
                       value=_shown(float(excess[pick])), envelope=name, row=row, col=col, x=x,
                       y=y, seed=float(seed[row, col]))


def _check_seeds(values: np.ndarray, seed: np.ndarray, direction: Direction, geometry: Grid,
                 name: str) -> None:
    """En cada semilla, ``E↑ ≤ f`` (``E↓ ≥ f``) exactamente. ``values`` está en la cara de la
    ascendente (``E↑`` o ``−E↓``)."""
    sign = 1.0 if direction is Direction.UP else -1.0
    cells = np.flatnonzero(np.isfinite(seed))
    if not cells.size:
        return
    excess = values.ravel()[cells] - sign * seed.ravel()[cells]
    if float(excess.max()) > 0.0:
        raise _seed_error(values, seed, direction, geometry, name, cells, excess)


# --- Lo que se pide ----------------------------------------------------------------------------


def _check_inputs(seed: np.ndarray, geometry: Grid, slope: SlopeField, direction: Direction | str,
                  max_iterations: int, cells_per_unit: int) -> Direction:
    """Los errores del programa de las entradas (``ValueError``); la dirección, como enumerado."""
    way = Direction(direction)
    if seed.ndim != 2 or seed.shape != geometry.shape:
        raise ValueError(f"las semillas {seed.shape} no son de la forma de la rejilla "
                         f"{geometry.shape}")
    if geometry.dx != geometry.dy:
        raise ValueError("las envolventes se calculan en una rejilla de celdas cuadradas (la del "
                         f"proyecto, ADR-0014), no de {geometry.dx} × {geometry.dy} m")
    if isinstance(slope.tan, np.ndarray) and slope.tan.shape != geometry.shape:
        raise ValueError(f"el mapa de pendientes {slope.tan.shape} no es de la forma de la "
                         f"rejilla {geometry.shape}")
    if max_iterations < 1 or cells_per_unit < 1:
        raise ValueError("las vueltas y las celdas por unidad deben ser al menos 1")
    return way


def _work(seed: np.ndarray, geometry: Grid, slope: SlopeField, way: Direction, name: str,
          max_iterations: int, cells_per_unit: int) -> Generator[None, None, Envelope]:
    """Las unidades de :func:`chamfer_steps`: el barrido hasta el punto fijo y su comprobación."""
    nrows, ncols = seed.shape
    sign = 1.0 if way is Direction.UP else -1.0
    values = np.where(np.isfinite(seed), seed * sign, np.inf)
    weights = _Weights(slope, ncols, geometry.dx)
    rows = max(1, cells_per_unit // ncols)
    check_rows = max(1, cells_per_unit // (4 * ncols))
    yield None
    iterations, worst = 0, math.inf
    while True:
        yield from _sweep(values, weights, rows, forward=True)
        yield from _sweep(values, weights, rows, forward=False)
        iterations += 1
        worst = yield from _violation_units(values, weights, check_rows)
        if worst <= TOLERANCE_M or iterations >= max_iterations:
            break
    if worst > TOLERANCE_M:
        raise _not_fixed_point(values, weights, geometry, name, iterations, TOLERANCE_M,
                               check_rows)
    _check_seeds(values, seed, way, geometry, name)
    yield None
    if way is Direction.DOWN:
        np.negative(values, out=values)
    return Envelope(values, iterations, worst)


def chamfer_steps(seed: np.ndarray, geometry: Grid, slope: SlopeField,
                  direction: Direction | str, *, name: str = "",
                  budget_s: float = STEP_BUDGET_S, max_iterations: int = MAX_ITERATIONS,
                  cells_per_unit: int = CELLS_PER_UNIT) -> Iterator[Progress]:
    """La envolvente *chamfer* 5×5 de las semillas ``seed`` (m, se toman como float64; es semilla
    toda celda con cota finita, ``+inf`` y NaN no) sobre ``geometry`` (la rejilla del proyecto:
    celdas cuadradas) con la pendiente ``slope`` y en la ``direction`` (``up`` o ``down``)
    pedidas (RF-013-11, RF-013-12, RF-013-13), por pasos de ``budget_s`` como mucho: el último
    ``Progress`` lleva en ``result`` la :class:`Envelope`. Cerrar el generador a mitad no deja
    nada; las entradas no se modifican.

    Comprueba en cada ejecución el RF-013-15 (véase el módulo) y lanza ``DesignError``
    (``des.envelope_not_fixed_point``, ``des.envelope_seed_above`` o ``des.envelope_seed_below``,
    con la celda absoluta y la diferencia) si falla, sin entregar nada; ``name`` es el de la
    envolvente en esos mensajes. Una entrada que no casa (la forma, celdas no cuadradas, una
    dirección desconocida) es un error del programa (``ValueError``) al llamar. ``cells_per_unit``
    afina el tamaño de las unidades de trabajo (las pruebas lo bajan)."""
    cotas = np.asarray(seed, dtype=np.float64)
    way = _check_inputs(cotas, geometry, slope, direction, max_iterations, cells_per_unit)
    work = _work(cotas, geometry, slope, way, name, max_iterations, cells_per_unit)
    return pace_progress(work, budget_s, phase="envelope", running="Calculando la envolvente…",
                         finished="Envolvente calculada")


def check_envelope(envelope: np.ndarray, seed: np.ndarray, slope: SlopeField, geometry: Grid,
                   direction: Direction | str, *, name: str = "",
                   tolerance: float = TOLERANCE_M) -> None:
    """Comprueba el RF-013-15 de una ``envelope`` ya calculada (m, la cota de cada celda) de las
    semillas ``seed``: que es un punto fijo —ninguna de las 16 relajaciones se viola más de
    ``tolerance`` m— y que cada semilla queda del lado de su cota (``E↑ ≤ f``, ``E↓ ≥ f``). Lanza
    ``DesignError`` con la celda absoluta y la diferencia; no devuelve nada si todo cumple. Es la
    comprobación que :func:`chamfer_steps` hace en cada ejecución, aplicable a cualquier
    envolvente."""
    seed = np.asarray(seed, dtype=np.float64)
    way = _check_inputs(seed, geometry, slope, direction, 1, 1)
    values = np.asarray(envelope, dtype=np.float64)
    if values.shape != seed.shape:
        raise ValueError(f"la envolvente {values.shape} no es de la forma de las semillas "
                         f"{seed.shape}")
    sign = 1.0 if way is Direction.UP else -1.0
    values = values * sign
    weights = _Weights(slope, seed.shape[1], geometry.dx)
    rows = max(1, CELLS_PER_UNIT // (4 * seed.shape[1]))
    steps = _violation_units(values, weights, rows)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            worst = stop.value
            break
    if worst > tolerance:
        raise _not_fixed_point(values, weights, geometry, name, None, tolerance, rows)
    _check_seeds(values, seed, way, geometry, name)


# --- El alcance (RF-013-14, A6) ----------------------------------------------------------------

_DISTANCE = SlopeField(1.0)
"""La pendiente de la distancia pura: ``t = 1`` (con la misma escala del *chamfer*)."""


def _shown_number(value: float | None) -> float | str:
    """Un número tal como se dice en un rechazo: el finito, tal cual; NaN o infinito, su texto; ni
    número, «—»."""
    if value is None:
        return _NO_VALUE
    return value if math.isfinite(value) else str(value)


def _check_reach(name: str, reach_m: float) -> None:
    """El alcance (m) ha de ser un número finito mayor que 0 (RF-013-14); si no,
    ``des.reach_range``."""
    if not math.isfinite(reach_m) or reach_m <= 0.0:
        raise DesignError("des.reach_range", obj=_name_of(name), field=_REACH_FIELD,
                          value=_shown_number(reach_m), envelope=name)


def _reach_work(seed: np.ndarray, geometry: Grid, reach_m: float, name: str,
                cells_per_unit: int) -> Generator[None, None, np.ndarray]:
    """Las unidades de :func:`reach_steps`: la distancia *chamfer* a la semilla más próxima (la
    envolvente ascendente de unas semillas a 0 con ``t = 1``) y ``NaN`` donde pasa del alcance."""
    origin = np.where(np.isfinite(seed), 0.0, np.inf)
    found = yield from _work(origin, geometry, _DISTANCE, Direction.UP,
                             f"{name} (alcance)" if name else "alcance", MAX_ITERATIONS,
                             cells_per_unit)
    distance = found.grid
    distance[distance > reach_m] = np.nan
    return distance


def reach_steps(seed: np.ndarray, geometry: Grid, reach_m: float,
                metric: Metric | str = Metric.CHAMFER5, *, name: str = "",
                budget_s: float = STEP_BUDGET_S, cells_per_unit: int = CELLS_PER_UNIT
                ) -> Iterator[Progress]:
    """La distancia (m) de cada celda de ``geometry`` a la semilla más próxima de ``seed`` (m;
    semilla es toda celda con cota finita) con la ``metric`` y ``t = 1`` (RF-013-14, A6), y ``NaN``
    donde pasa de ``reach_m``; las celdas de semilla, a 0. Por pasos de ``budget_s`` como mucho,
    de la fase «reach»: el último ``Progress`` lleva en ``result`` el array (float64, nuevo). Un
    alcance que no es un número mayor que 0 es ``des.reach_range`` (``DesignError``, ``name`` es
    la envolvente); una forma que no casa, un error del programa (``ValueError``). Hoy, solo con
    el *chamfer* 5×5; la euclídea exacta es de la T08. No modifica ``seed``."""
    cotas = np.asarray(seed, dtype=np.float64)
    reach = float(reach_m)
    _check_reach(name, reach)
    _check_inputs(cotas, geometry, _DISTANCE, Direction.UP, MAX_ITERATIONS, cells_per_unit)
    if Metric(metric) is not Metric.CHAMFER5:
        raise NotImplementedError("la euclídea exacta es de la tarea T08 de la spec 013")
    work = _reach_work(cotas, geometry, reach, name, cells_per_unit)
    return pace_progress(work, budget_s, phase="reach", running="Calculando el alcance…",
                         finished="Alcance calculado")


# --- Los rechazos de RF-013-16 antes de calcular -----------------------------------------------


def _check_constant(request: EnvelopeRequest) -> None:
    """La pendiente (de 0, incluido, a 90 grados, excluido) y el factor de malla (de 0, excluido,
    a 1) de una petición de pendiente constante."""
    degrees = request.slope_deg
    if degrees is None or not math.isfinite(degrees) or not 0.0 <= degrees < 90.0:
        raise DesignError("des.slope_range", obj=_name_of(request.name), field=_SLOPE_FIELD,
                          value=_shown_number(degrees), envelope=request.name)
    mesh = request.mesh_factor
    if not math.isfinite(mesh) or not 0.0 < mesh <= 1.0:
        raise DesignError("des.mesh_factor_range", obj=_name_of(request.name), field=_MESH_FIELD,
                          value=_shown_number(mesh), envelope=request.name)


def check_request(request: EnvelopeRequest) -> None:
    """RF-013-16 sobre la petición sola, antes de leer nada: con pendiente constante, que sea un
    número de 0 (incluido) a 90 grados (excluido) y que el factor de malla esté entre 0
    (excluido) y 1 (``des.slope_range``, ``des.mesh_factor_range``); que la euclídea exacta no se
    pida con la pendiente por sectores (``des.exact_needs_constant_slope``) y que el alcance, si
    lo hay, sea un número de metros mayor que 0 (``des.reach_range``). Con la pendiente por
    sectores no se comprueban el grado ni el factor de malla de la petición: salen de cada sector
    y de su perfil. ``DesignError`` con la envolvente, el campo y el valor y la orden que lo
    resuelve; no devuelve nada si todo cumple."""
    if SlopeMode(request.slope_mode) is SlopeMode.CONSTANT:
        _check_constant(request)
    elif Metric(request.metric) is Metric.EXACT:
        raise DesignError("des.exact_needs_constant_slope", obj=_name_of(request.name),
                          field=_MODE_FIELD, value=SlopeMode(request.slope_mode).value,
                          envelope=request.name)
    if request.reach_m is not None:
        _check_reach(request.name, request.reach_m)


def check_seed_set(request: EnvelopeRequest, seeds: SeedSet) -> None:
    """RF-013-16 sobre las semillas ya formadas: que alguna celda tenga cota finita
    (``des.seeds_empty``, con las celdas de su zona que no la tenían) y que el dominio de trabajo
    tenga alguna celda (``des.domain_empty``); en ese orden. Las semillas fuera del dominio no
    bastan. ``DesignError`` con la envolvente, el campo y el valor y la orden que lo resuelve; no
    devuelve nada si todo cumple."""
    if not np.isfinite(seeds.grid).any():
        raise DesignError("des.seeds_empty", obj=_name_of(request.name), field=_SEEDS_FIELD,
                          value=0, envelope=request.name, nodata=seeds.nodata_cells)
    if seeds.domain.cells == 0:
        raise DesignError("des.domain_empty", obj=_name_of(request.name), field=_DOMAIN_FIELD,
                          value=0, envelope=request.name)


def request_slope(request: EnvelopeRequest) -> SlopeField:
    """La pendiente de una petición de pendiente constante: ``tan(°)·factor de malla`` en toda la
    rejilla (:func:`constant_slope`), con los rechazos de :func:`check_request` para la pendiente y
    el factor de malla (``des.slope_range``, ``des.mesh_factor_range``). La de los sectores la
    resuelve quien llama con :func:`sector_slope` (``ValueError`` si se pide aquí)."""
    if SlopeMode(request.slope_mode) is not SlopeMode.CONSTANT:
        raise ValueError("la pendiente por sectores la resuelve quien llama (sector_slope), no la "
                         "petición")
    _check_constant(request)
    assert request.slope_deg is not None  # _check_constant
    return constant_slope(request.slope_deg, request.mesh_factor)


# --- La petición -------------------------------------------------------------------------------


def _envelope_units(request: EnvelopeRequest, seeds: SeedSet, slope: SlopeField
                    ) -> Generator[None, None, Envelope]:
    """Las unidades de :func:`envelope_steps`: los rechazos, el barrido hasta el punto fijo y,
    con alcance, la distancia que deja sin dato (``NaN``) lo que pasa de él."""
    check_request(request)
    check_seed_set(request, seeds)
    if Metric(request.metric) is not Metric.CHAMFER5:
        raise NotImplementedError("la euclídea exacta es de la tarea T08 de la spec 013")
    way = Direction(request.direction)
    cotas = np.asarray(seeds.grid, dtype=np.float64)
    _check_inputs(cotas, seeds.geometry, slope, way, MAX_ITERATIONS, CELLS_PER_UNIT)
    found = yield from _work(cotas, seeds.geometry, slope, way, request.name, MAX_ITERATIONS,
                             CELLS_PER_UNIT)
    if request.reach_m is None:
        return found
    distance = yield from _reach_work(cotas, seeds.geometry, request.reach_m, request.name,
                                      CELLS_PER_UNIT)
    found.grid[np.isnan(distance)] = np.nan
    return Envelope(found.grid, found.iterations, found.violation)


def envelope_steps(request: EnvelopeRequest, seeds: SeedSet, slope: SlopeField, *,
                   budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """La envolvente que pide ``request`` (su dirección, su nombre y su alcance) de las ``seeds``
    (su rejilla de cotas y su geometría) con la pendiente ``slope``, por pasos: el último
    ``Progress`` lleva la :class:`Envelope`. Antes de calcular, y al avanzar el generador, aplica
    los rechazos de RF-013-16 (:func:`check_request`, :func:`check_seed_set`): ninguno cede un
    paso ni registra nada. Con ``request.reach_m`` deja ``NaN`` lo que pasa de ese alcance de las
    semillas (RF-013-14, :func:`reach_steps`); sin él, ninguna celda. La rejilla es la entera; el
    recorte al dominio de trabajo es posterior. Hoy, solo con el *chamfer* 5×5; la euclídea
    exacta (RF-013-12) es de la T08. Ninguna entrada se modifica."""
    return pace_progress(_envelope_units(request, seeds, slope), budget_s, phase="envelope",
                         running="Calculando la envolvente…", finished="Envolvente calculada")
