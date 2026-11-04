# SPDX-License-Identifier: GPL-3.0-or-later
"""El escalonado en corte y en relleno (spec 013, T09; HU-013-5; RF-013-22, RF-013-23, RF-013-24;
plan 013 A8).

Convierte una superficie continua ``S`` (una envolvente de la versión) en bancos y bermas **anclados
a las cotas absolutas** ``z₀ + n·h``. Cada celda se escalona con el perfil que le toca (su altura
de banco ``h``, la tangente de su cara ``tan α``, su berma ``B`` y su ancla ``z₀``), con
``a = h/tan α + B`` (el avance del perfil), ``u = (S − z₀)/h``, ``n = ⌊u⌋`` y ``f = u − n``:

- **Corte** (:func:`bench_cut`; RF-013-22, *cara primero*): ``z₀ + n·h + mín(f·a·tan α, h)``. Sube
  por la cara con la inclinación ``α`` hasta el piso de arriba y allí se queda (la berma). Queda
  por **encima** de ``S`` y a menos de ``h`` de ella: excava de menos (errores 12 a 15).
- **Relleno** (:func:`bench_fill`; RF-013-23, *berma primero*):
  ``z₀ + n·h + máx((f·a − B)·tan α, 0)``. Se queda en el piso (la berma) y luego sube por la cara.
  Queda por **debajo** de ``S`` y a menos de ``h`` de ella: rellena de menos. Es el corte visto en
  el espejo: ``relleno(S, z₀) = −corte(−S, −z₀)``.

**El ancla** (RF-013-24; D-12, D-18): ``z₀`` es un número (el ancla del perfil) o una rejilla (una
cota por celda, de la versión activa), y el paso es siempre la altura de banco ``h``. Las cotas de
las bermas son ``z₀ + n·h`` para cualquier superficie: no dependen de la cota mínima de la rejilla
ni de ningún ajuste posterior, y este módulo no recibe nada que pueda moverlas (el cierre del
balance que las sacó de sus cotas es el error 12). Un ancla y su desplazada un número entero de
alturas dan la misma escalera.

Cada celda depende solo de su propia cota, su perfil y su ancla (es una función punto a punto):
quien llama puede partir la rejilla en bandas de filas sin cambiar ni un bit del resultado, que es
como las tareas por pasos de ``design`` se mantienen dentro de su presupuesto (RNF-013-07).

**Los datos.** ``S`` puede ser cualquier forma (escalar incluido) y el resto de argumentos,
escalares o arrays que se difundan a ella, **sin ampliarla**. Se calcula en float64 y se devuelve
un array **nuevo**; ninguna entrada se modifica. Una celda sin dato (``NaN``) o sin envolvente
(``±inf``) sale ``NaN``, sin avisos de numpy, y no hace falta que tenga perfil ni ancla (solo
cuentan los de las celdas con superficie). Una altura o una tangente que no sea finita y mayor que
0, una berma que no sea finita y no negativa o un ancla no finita en una celda con superficie son
un error del programa (:class:`ValueError`: ``BenchProfile`` ya no deja crear un perfil así, y
quien trae una rejilla de anclas con huecos los rechaza antes con su ``DesignError``). Por
redondeo, la propia superficie podría quedar 10⁻¹³ m del lado equivocado donde la cara sigue a
``S`` (berma 0): se recorta contra ``S`` (``máx`` en el corte, ``mín`` en el relleno), de modo que
el contrato de «por encima» y «por debajo» es exacto; las cotas de las bermas no se tocan (están a
``h·(1 − f)`` de ``S`` o más).

**La berma impuesta** (T10; RF-013-25, D-11): un sector con talud general máximo ``β`` impuesto
recibe la berma ``B_s = máx(B, h/tan β − h/tan α)`` (:func:`sector_berm`): la que hace que su talud
general ``atan(h/a)`` no pase de ``β``, nunca menor que la mínima del perfil, y sin deducirla de la
pendiente local de ninguna envolvente (error 13).

**La regularización entre sectores** (T10; RF-013-26, A7): antes de escalonar un frente de sectores
con taludes generales distintos, :func:`regularize_steps` calcula la envolvente ascendente de la
propia envolvente (cada celda es semilla de su cota) con la tangente más empinada de los sectores
implicados (:func:`implicated_cells`): la mayor superficie con esa pendiente por debajo de la
envolvente, que quita las paredes del borde entre sectores (error 15). Una envolvente calculada con
la pendiente por sectores del *chamfer* (entrar en una celda cuesta con la pendiente de la celda de
llegada) ya es regular y no cambia. Una más empinada que esa tangente (calculada con una pendiente
constante mayor que el talud general de un sector) **baja**: :class:`Regularization` lleva las
celdas bajadas y el descenso máximo para que quien calcula lo avise (spec 0.4, RF-013-30), sin
cambiar la regularización ni el escalonado.

**El recorte final** (T10; RF-013-27, A9): :func:`final_trim_steps` calcula la envolvente ascendente
del resultado escalonado con la tangente de la cara del perfil de cada celda por su factor de malla,
para que ninguna inclinación entre vecinas pase de la cara más la tolerancia (error 14), y no deja
el corte por debajo de ``S`` ni el relleno por encima (``máx(recorte, S)`` en el corte,
``mín(recorte, S)`` en el relleno). Ambas son pasos de ``design`` con el mismo *chamfer* 5×5
escalado de las envolventes (:func:`~design.envelopes.chamfer_units`).

Python puro (nivel 8), con numpy, sin importar ``reserves`` ni ``bl``.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .envelopes import CELLS_PER_UNIT, TOLERANCE_M, SlopeField, chamfer_units
from .model import BenchProfile, BenchSense, Direction
from .seeds import pace_progress

__all__ = [
    "Regularization",
    "Trim",
    "bench_cut",
    "bench_fill",
    "final_trim_steps",
    "implicated_cells",
    "regularize_steps",
    "sector_berm",
]

Number = float | np.ndarray

_HEIGHT = "height"
_TAN_FACE = "tan_face"
_BERM = "berm"
_ANCHOR = "anchor"


def _all_valid(values: np.ndarray, low: float, strict: bool) -> bool:
    """Si todo ``values`` es finito y está por encima de ``low`` (``strict``) o no por debajo
    (con NaN, ``False``). Dos reducciones: mucho más barato que una máscara."""
    if values.size == 0:
        return True
    smallest = float(values.min())
    largest = float(values.max())
    if not (math.isfinite(smallest) and math.isfinite(largest)):
        return False
    return smallest > low if strict else smallest >= low


def _valid(values: np.ndarray, low: float, strict: bool) -> np.ndarray:
    """Qué celdas de ``values`` son finitas y están por encima de ``low`` (``strict``) o no por
    debajo."""
    return np.isfinite(values) & ((values > low) if strict else (values >= low))


def _parameter(name: str, meaning: str, value: Number, expected: str, low: float, strict: bool,
               finite: np.ndarray, shape: tuple[int, ...]) -> Number:
    """Un parámetro comprobado: un escalar (``float``) o un array float64 que se difunde a ``shape``
    sin ampliarlo. Falla si un escalar no cumple, o si un array no cumple en alguna celda con
    superficie (``finite``)."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 0:
        number = float(array)
        if not bool(_valid(array, low, strict)):
            raise ValueError(f"{meaning} ({name}) {expected}: vale {number!r}")
        return number
    try:
        fits = np.broadcast_shapes(array.shape, shape) == shape
    except ValueError:
        fits = False
    if not fits:
        raise ValueError(f"{meaning} ({name}) tiene la forma {array.shape}, que no cabe en la "
                         f"forma {shape} de la superficie")
    if _all_valid(array, low, strict):
        return array
    bad = np.broadcast_to(~_valid(array, low, strict) & finite, shape)
    if bad.any():
        first = tuple(int(index) for index in np.argwhere(bad)[0])
        value_there = float(np.broadcast_to(array, shape)[first])
        raise ValueError(f"{meaning} ({name}) {expected}: falla en {int(np.count_nonzero(bad))} "
                         f"celdas con superficie, la primera en {first} (vale {value_there!r})")
    return array


def _stairs(surface: Number, height: Number, tan_face: Number, berm: Number, anchor: Number,
            *, fill: bool) -> np.ndarray:
    """El escalonado de ``surface`` en corte (``fill=False``) o en relleno."""
    shape = np.shape(surface)
    cells = np.atleast_1d(np.asarray(surface, dtype=np.float64))  # solo se lee: no se copia
    finite = np.isfinite(cells)
    h = _parameter(_HEIGHT, "la altura de banco", height, "debe ser finita y mayor que 0", 0.0,
                   True, finite, shape)
    t = _parameter(_TAN_FACE, "la tangente de la cara", tan_face, "debe ser finita y mayor que 0",
                   0.0, True, finite, shape)
    b = _parameter(_BERM, "la berma", berm, "debe ser finita y no negativa", 0.0, False, finite,
                   shape)
    z = _parameter(_ANCHOR, "el ancla", anchor, "debe ser finita", -math.inf, True, finite, shape)
    with np.errstate(invalid="ignore", over="ignore"):
        level = cells - z
        level /= h
        number = np.floor(level)
        level -= number  # f, la fracción de banco: 0 ≤ f < 1
        if fill:
            # (f·a − B)·tan α con a = h/tan α + B, sin pasar de la berma hacia abajo
            rise = level * (h / t + b)
            rise -= b
            rise *= t
            np.maximum(rise, 0.0, out=rise)
        else:
            # mín(f·a·tan α, h); a·tan α = h + B·tan α
            rise = level * (h + b * t)
            np.minimum(rise, h, out=rise)
        number *= h
        number += z
        number += rise
        if fill:
            np.minimum(number, cells, out=number)
        else:
            np.maximum(number, cells, out=number)
    if not finite.all():
        number[~finite] = np.nan
    return number.reshape(shape)


def bench_cut(surface: Number, height: Number, tan_face: Number, berm: Number,
              anchor: Number) -> np.ndarray:
    """El escalonado en **corte** (*cara primero*; RF-013-22): ``z₀ + n·h + mín(f·a·tan α, h)``,
    con ``a = h/tan α + B``, ``u = (S − z₀)/h``, ``n = ⌊u⌋`` y ``f = u − n``. Queda por encima de
    ``S`` y a menos de ``h`` de ella en toda celda, y sus bermas, en las cotas ``z₀ + n·h``.

    ``surface`` es la superficie ``S`` (m, absolutas, float64); ``height`` (``h``, m), ``tan_face``
    (``tan α``, la de la inclinación máxima de la cara), ``berm`` (``B``, m, la mínima o la de un
    sector con talud impuesto) y ``anchor`` (``z₀``, m) son escalares o arrays por celda (el perfil
    de cada sector; el ancla, una rejilla de cotas). Devuelve un array nuevo de la forma de
    ``surface``; ``NaN`` donde ``surface`` no es finita. El módulo dice qué datos rechaza."""
    return _stairs(surface, height, tan_face, berm, anchor, fill=False)


def bench_fill(surface: Number, height: Number, tan_face: Number, berm: Number,
               anchor: Number) -> np.ndarray:
    """El escalonado en **relleno** (*berma primero*; RF-013-23):
    ``z₀ + n·h + máx((f·a − B)·tan α, 0)``, con los mismos significados que :func:`bench_cut`.
    Queda por debajo de ``S`` y a menos de ``h`` de ella en toda celda, y sus bermas, en las cotas
    ``z₀ + n·h``. Es el corte en el espejo: ``bench_fill(S, …, z₀) = −bench_cut(−S, …, −z₀)``."""
    return _stairs(surface, height, tan_face, berm, anchor, fill=True)


# --- La berma de un sector con talud impuesto (T10; RF-013-25, D-11) ------------------------------


def sector_berm(profile: BenchProfile, imposed_deg: float | None) -> float:
    """La berma (m) de un sector con talud general máximo ``imposed_deg`` (``β``, °; ``None`` si el
    sector no lo tiene) para un perfil de altura ``h``, cara ``α`` y berma mínima ``B``:
    ``B_s = máx(B, h/tan β − h/tan α)`` (RF-013-25; D-11). Es la que hace que el talud general de
    los bancos, ``atan(h/(h/tan α + B_s))``, no pase de ``β``; si la fórmula da menos que la mínima
    del perfil (el talud impuesto es igual o más empinado que el general del perfil), la mínima. Sin
    talud impuesto, la mínima. **No mira ninguna superficie**: la berma no se deduce de la pendiente
    local de la envolvente (error 13).

    ``profile`` es cualquier objeto con ``height_m``, ``face_deg`` y ``berm_m`` (un
    :class:`~design.model.BenchProfile`). Un ``imposed_deg`` que no sea un número de 0 a 90 grados
    (ambos excluidos) es un error del programa (:class:`ValueError`): la persona lo ve antes, con
    :func:`~design.params.check_sector_slope`."""
    berm = float(profile.berm_m)
    if imposed_deg is None:
        return berm
    beta = float(imposed_deg)
    if not math.isfinite(beta) or not 0.0 < beta < 90.0:
        raise ValueError("el talud general máximo impuesto debe ser un número de 0 a 90 grados "
                         f"(ambos excluidos), no {imposed_deg!r}")
    height = float(profile.height_m)
    face = height / math.tan(math.radians(float(profile.face_deg)))
    general = height / math.tan(math.radians(beta))
    return max(berm, general - face)


# --- Comprobaciones de las entradas de los pasos --------------------------------------------------


def _check_surface(cells: np.ndarray, geometry: Grid, meaning: str) -> None:
    """``ValueError`` si ``cells`` no es una rejilla de 2 dimensiones de la forma de ``geometry`` o
    si ``geometry`` no tiene celdas cuadradas (ADR-0014)."""
    if cells.ndim != 2 or cells.shape != geometry.shape:
        raise ValueError(f"{meaning} {cells.shape} no es de la forma de la rejilla "
                         f"{geometry.shape}")
    if geometry.dx != geometry.dy:
        raise ValueError("las envolventes se calculan en una rejilla de celdas cuadradas (la del "
                         f"proyecto, ADR-0014), no de {geometry.dx} × {geometry.dy} m")


def _check_units(cells_per_unit: int) -> None:
    if cells_per_unit < 1:
        raise ValueError("las celdas por unidad deben ser al menos 1")


# --- La regularización entre sectores (T10; RF-013-26, A7) ----------------------------------------


def implicated_cells(tangents: np.ndarray, domain: np.ndarray | None = None) -> np.ndarray:
    """Qué celdas implica una frontera entre sectores (A7): las que tienen, en las cuatro
    direcciones, una vecina con otra tangente de pendiente (``tangents``: la ``SlopeField.tan`` de
    la pendiente por sectores). Con ``domain`` (booleano, de la forma del mapa), solo cuentan las
    celdas del dominio de trabajo y sus vecinas del dominio. Un array booleano **nuevo**; el mapa y
    el dominio no se tocan. ``ValueError`` si el mapa no es de 2 dimensiones o el dominio no es
    booleano de su forma."""
    values = np.asarray(tangents)
    if values.ndim != 2:
        raise ValueError(f"el mapa de pendientes es de 2 dimensiones, no de {values.ndim}")
    inside: np.ndarray | None = None
    if domain is not None:
        inside = np.asarray(domain)
        if inside.dtype != np.bool_ or inside.shape != values.shape:
            raise ValueError("el dominio de trabajo es una máscara booleana de la forma del mapa "
                             f"de pendientes {values.shape}")
    found = np.zeros(values.shape, dtype=np.bool_)
    everything = slice(None)
    for first, second in (((everything, slice(0, -1)), (everything, slice(1, None))),
                          ((slice(0, -1), everything), (slice(1, None), everything))):
        differ = values[first] != values[second]
        if inside is not None:
            differ &= inside[first]
            differ &= inside[second]
        found[first] |= differ
        found[second] |= differ
    return found


@dataclass(frozen=True, slots=True, eq=False)
class Regularization:
    """Una envolvente regularizada: ``grid`` (m, float64, nueva, de la forma de la rejilla; las
    celdas sin cota finita salen como entraron), la ``tan`` efectiva con la que se regularizó (la
    mayor de las celdas implicadas; ``None`` si no había sectores con otra pendiente y no se hizo
    nada), las ``cells`` implicadas, las celdas ``lowered`` (que bajaron más de
    :data:`~design.envelopes.TOLERANCE_M`: 0 si la envolvente ya era regular), el mayor descenso
    ``lowered_max_m`` (m, de esas celdas: ``surface − grid``; 0,0 si no bajó ninguna), las
    ``iterations`` del barrido y su ``violation`` (m, ≤ :data:`~design.envelopes.TOLERANCE_M`).

    Que baje es lo que la spec 0.4 manda avisar (RF-013-26, RF-013-30): una envolvente más empinada
    que la tangente de la regularización (calculada con una pendiente constante mayor que el talud
    general de un sector) queda más baja que la registrada."""

    grid: np.ndarray
    tan: float | None
    cells: int
    lowered: int
    lowered_max_m: float
    iterations: int
    violation: float


def _regularize_units(surface: np.ndarray, geometry: Grid, slope: SlopeField,
                      domain: np.ndarray | None, name: str, cells_per_unit: int
                      ) -> Generator[None, None, Regularization]:
    """Las unidades de :func:`regularize_steps`."""
    yield None
    count = 0
    tan = 0.0
    if not slope.uniform:
        tangents = np.asarray(slope.tan)
        involved = implicated_cells(tangents, domain)
        count = int(np.count_nonzero(involved))
        yield None
        if count:
            tan = float(tangents[involved].max())
        del involved
    if not count:
        return Regularization(surface.copy(), None, 0, 0, 0.0, 0, 0.0)
    found = yield from chamfer_units(surface, geometry, SlopeField(tan), Direction.UP, name=name,
                                     cells_per_unit=cells_per_unit)
    grid = found.grid
    yield None
    np.copyto(grid, surface, where=~np.isfinite(surface))  # sin cota, como entró
    yield None
    with np.errstate(invalid="ignore"):
        below = grid < surface - TOLERANCE_M
    lowered = int(np.count_nonzero(below))
    biggest = float((surface[below] - grid[below]).max()) if lowered else 0.0
    return Regularization(grid, tan, count, lowered, biggest, found.iterations, found.violation)


def regularize_steps(surface: np.ndarray, geometry: Grid, slope: SlopeField, *,
                     domain: np.ndarray | None = None, name: str = "",
                     budget_s: float = STEP_BUDGET_S,
                     cells_per_unit: int = CELLS_PER_UNIT) -> Iterator[Progress]:
    """Regulariza la envolvente ``surface`` (m, float64; se toma como tal) entre sectores con
    taludes distintos (RF-013-26, A7), por pasos de ``budget_s`` como mucho: la envolvente
    ascendente (*chamfer* 5×5) de ella misma —cada celda con cota finita es semilla de la suya— con
    la tangente más empinada de las celdas que :func:`implicated_cells` dice que están en una
    frontera entre sectores. ``slope`` es la pendiente por celdas de la envolvente
    (:func:`~design.envelopes.sector_slope`) y ``domain`` el dominio de trabajo (opcional: solo
    cuentan sus celdas).

    Es la mayor superficie con esa pendiente que no sube de ninguna celda: quita las paredes del
    borde entre sectores y no cambia una envolvente que ya cumple (la del *chamfer* con la pendiente
    por sectores). Con una pendiente igual en toda la rejilla no hay nada que regularizar. Las
    celdas sin cota finita (sin dato, sin envolvente o fuera del alcance) salen como entraron y no
    propagan nada. El último ``Progress`` (fase «regularize») lleva en ``result`` la
    :class:`Regularization`. Cerrar el generador a mitad no deja nada; las entradas no se modifican.
    Una forma que no casa, celdas no cuadradas, un dominio que no es booleano de la forma de la
    rejilla o un mapa de pendientes de otra forma son errores del programa (:class:`ValueError`)."""
    cells = np.asarray(surface, dtype=np.float64)
    _check_surface(cells, geometry, "la superficie")
    if not slope.uniform and np.shape(slope.tan) != geometry.shape:
        raise ValueError(f"el mapa de pendientes {np.shape(slope.tan)} no es de la forma de la "
                         f"rejilla {geometry.shape}")
    if domain is not None:
        domain = np.asarray(domain)
        if domain.dtype != np.bool_ or domain.shape != geometry.shape:
            raise ValueError("el dominio de trabajo es una máscara booleana de la forma de la "
                             f"rejilla {geometry.shape}")
    _check_units(cells_per_unit)
    work = _regularize_units(cells, geometry, slope, domain, name, cells_per_unit)
    return pace_progress(work, budget_s, phase="regularize",
                         running="Regularizando la envolvente entre sectores…",
                         finished="Envolvente regularizada")


# --- El recorte final (T10; RF-013-27, A9) --------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Trim:
    """Un escalonado recortado: ``grid`` (m, float64, nueva; sin dato donde el escalonado no lo
    tenía), las ``iterations`` y la ``violation`` (m) del barrido, las celdas ``lowered`` por el
    recorte (más de :data:`~design.envelopes.TOLERANCE_M` por debajo de lo escalonado) y las
    ``clamped``: las que el recorte dejó del lado equivocado de ``S`` (el corte por debajo, el
    relleno por encima, más de :data:`~design.envelopes.TOLERANCE_M`) y hubo que devolver a
    ``S``."""

    grid: np.ndarray
    iterations: int
    violation: float
    lowered: int
    clamped: int


def _per_cell(value: Number, name: str, shape: tuple[int, ...]) -> np.ndarray:
    """``value`` como array float64: un número (0 dimensiones) o un mapa de la forma de la
    rejilla."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim not in (0, 2) or (array.ndim == 2 and array.shape != shape):
        raise ValueError(f"{name} es un número o un mapa de la forma de la rejilla {shape}, "
                         f"no de forma {array.shape}")
    return array


def _invalid_cells(good: np.ndarray, finite: np.ndarray, values: np.ndarray, name: str,
                   expected: str) -> None:
    """``ValueError`` si alguna celda con escalonado (``finite``) no cumple (``good`` es falso)."""
    bad = finite & ~good
    if bad.any():
        first = tuple(int(index) for index in np.argwhere(bad)[0])
        raise ValueError(f"{name} {expected}: falla en {int(np.count_nonzero(bad))} celdas con "
                         f"escalonado, la primera en {first} (vale {float(values[first])!r})")


def _trim_slope(face: np.ndarray, mesh: np.ndarray, finite: np.ndarray
                ) -> Generator[None, None, SlopeField]:
    """La tangente efectiva del recorte, ``tan α·factor de malla``: un escalar si los dos lo son
    y, si no, un mapa (en las celdas sin escalonado, que el recorte no devuelve, la mayor tangente,
    para no cortar el paso a las demás)."""
    yield None
    if face.ndim == 0 and mesh.ndim == 0:
        value, factor = float(face), float(mesh)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("la tangente de la cara (tan_face) debe ser finita y mayor que 0, "
                             f"no {value!r}")
        if not math.isfinite(factor) or not 0.0 < factor <= 1.0:
            raise ValueError("el factor de malla (mesh_factor) debe estar entre 0 (excluido) y 1, "
                             f"no {factor!r}")
        return SlopeField(value * factor)
    shape = finite.shape
    face_map = np.broadcast_to(face, shape)
    mesh_map = np.broadcast_to(mesh, shape)
    with np.errstate(invalid="ignore"):
        good_face = np.isfinite(face_map) & (face_map > 0.0)
        good_mesh = np.isfinite(mesh_map) & (mesh_map > 0.0) & (mesh_map <= 1.0)
    _invalid_cells(good_face, finite, face_map, "la tangente de la cara (tan_face)",
                   "debe ser finita y mayor que 0")
    _invalid_cells(good_mesh, finite, mesh_map, "el factor de malla (mesh_factor)",
                   "debe estar entre 0 (excluido) y 1")
    yield None
    good_face &= good_mesh
    effective = np.multiply(face_map, mesh_map, where=good_face, out=np.zeros(shape))
    yield None
    effective[~good_face] = float(effective.max())
    return SlopeField(effective)


def _trim_units(stairs: np.ndarray, surface: np.ndarray, geometry: Grid, face: np.ndarray,
                mesh: np.ndarray, way: BenchSense, name: str, cells_per_unit: int
                ) -> Generator[None, None, Trim]:
    """Las unidades de :func:`final_trim_steps`."""
    yield None
    finite = np.isfinite(stairs)
    if not finite.any():
        return Trim(stairs.copy(), 0, 0.0, 0, 0)
    slope = yield from _trim_slope(face, mesh, finite)
    found = yield from chamfer_units(stairs, geometry, slope, Direction.UP, name=name,
                                     cells_per_unit=cells_per_unit)
    grid = found.grid
    yield None
    np.copyto(grid, stairs, where=~finite)  # sin escalonado, como entró
    both = finite & np.isfinite(surface)
    yield None
    cut = way is BenchSense.CUT
    with np.errstate(invalid="ignore"):
        wrong = grid < surface - TOLERANCE_M if cut else grid > surface + TOLERANCE_M
        clamped = int(np.count_nonzero(wrong & both))
    del wrong
    yield None
    if cut:
        np.maximum(grid, surface, out=grid, where=both)
    else:
        np.minimum(grid, surface, out=grid, where=both)
    yield None
    with np.errstate(invalid="ignore"):
        lowered = int(np.count_nonzero(grid < stairs - TOLERANCE_M))
    return Trim(grid, found.iterations, found.violation, lowered, clamped)


def final_trim_steps(stairs: np.ndarray, surface: np.ndarray, geometry: Grid,
                     tan_face: Number, mesh_factor: Number, sense: BenchSense | str, *,
                     name: str = "", budget_s: float = STEP_BUDGET_S,
                     cells_per_unit: int = CELLS_PER_UNIT) -> Iterator[Progress]:
    """El recorte final del resultado escalonado ``stairs`` (m, el de :func:`bench_cut` o
    :func:`bench_fill`) de la superficie ``surface`` (``S``) en el sentido ``sense`` (RF-013-27,
    A9), por pasos de ``budget_s`` como mucho: su envolvente ascendente (*chamfer* 5×5) con la
    tangente de la cara por el factor de malla de cada celda (``tan_face`` y ``mesh_factor``: un
    número o un mapa de la forma de la rejilla, el del perfil de cada sector), de modo que ninguna
    inclinación entre celdas vecinas pase de la cara del perfil. Después, el corte no queda por
    debajo de ``S`` (``máx(recorte, S)``) ni el relleno por encima (``mín(recorte, S)``); las
    celdas devueltas a ``S`` se cuentan en ``Trim.clamped``.

    Las celdas sin escalonado (sin cota finita) salen como entraron y no necesitan perfil (su
    tangente puede ser ``NaN``); en las que sí lo tienen, una tangente que no sea finita y mayor que
    0 o un factor de malla fuera de (0; 1] es un error del programa (:class:`ValueError`), como una
    forma que no casa, celdas no cuadradas o un sentido desconocido. El último ``Progress`` (fase
    «trim») lleva en ``result`` el :class:`Trim`. Cerrar el generador a mitad no deja nada; las
    entradas no se modifican."""
    way = BenchSense(sense)
    laid = np.asarray(stairs, dtype=np.float64)
    base = np.asarray(surface, dtype=np.float64)
    _check_surface(laid, geometry, "el escalonado")
    _check_surface(base, geometry, "la superficie")
    face = _per_cell(tan_face, "la tangente de la cara (tan_face)", geometry.shape)
    mesh = _per_cell(mesh_factor, "el factor de malla (mesh_factor)", geometry.shape)
    _check_units(cells_per_unit)
    work = _trim_units(laid, base, geometry, face, mesh, way, name, cells_per_unit)
    return pace_progress(work, budget_s, phase="trim", running="Recortando el escalonado…",
                         finished="Escalonado recortado")
