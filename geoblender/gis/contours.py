# SPDX-License-Identifier: GPL-3.0-or-later
"""Curvas de nivel de una rejilla o de un TIN (spec 006; plan 006 §5.3.2 y §5.4 A14;
RF-006-18).

:func:`contours_from_raster` y :func:`contours_from_tin` dan las curvas de nivel de una
superficie como :class:`ContourLine`: polilíneas 3D ABSOLUTAS en float64, con Z igual a su
cota, marcadas como maestras o no y cerradas o abiertas (A14):

1. **Cotas**: L = base + k·equidistancia (``gis.contours.interval_m``, 1 m) entre la mínima y
   la máxima de la superficie. Cada vértice de la superficie está «arriba» si su cota es ≥ L y
   «abajo» si no: una cota igual a la máxima da la curva que rodea esa meseta y una igual a la
   mínima, ninguna. Es **maestra** si L/``gis.contours.index_every_m`` (5 m) es entero (±
   :data:`INDEX_TOLERANCE`). Con ``gis.contours.index_offset_m`` ≠ 0, una maestra se traza a
   L + desfase y conserva Z = L (las demás no cambian).
2. **Rejilla** (*marching squares*): cada cuadro de 4 centros con dato (los que tienen algún
   sin dato se omiten: la curva queda abierta en el borde de los datos), para cada cota entre
   su mínima (excluida) y su máxima (pares (cuadro, cota) con ``numpy.repeat``), da por su caso
   de 4 bits uno o dos segmentos entre sus aristas. Las **sillas** (casos 5 y 10: esquinas
   opuestas arriba) se resuelven con el valor medio del cuadro: si es ≥ L, sus esquinas altas
   quedan unidas y se recortan las bajas; si no, al revés. Así las curvas no se cruzan. Cada
   vértice está en una arista entre dos centros, interpolado linealmente (exacto sobre la
   superficie lineal por aristas, salvo los apartados de un nodo a la cota: 5), con la otra
   coordenada igual a la del centro, bit a bit.
3. **TIN**: por triángulo y cota, el segmento entre las dos aristas que cortan la cota. Los
   triángulos se orientan antes en sentido antihorario (``gis.tin._oriented``).
4. **Encadenado**: cada punto de corte es un par (cota, arista); cada segmento va de uno a
   otro con lo alto a su izquierda, así que a cada punto llega un segmento como mucho y sale
   otro como mucho. Las cadenas se ordenan por saltos de puntero (vectorizado); una cadena sin
   principio es un **anillo cerrado**, que empieza en su menor punto de corte y no repite su
   primer vértice. Una curva queda abierta solo en el borde de la superficie o de sus huecos.
   Los anillos de una cima son antihorarios y los de un fondo, horarios.
5. **Nodos a la cota** (T56; spec §8, «Silla en curvas de nivel»): un centro de la rejilla
   o un vértice del TIN justo a la cota está arriba (≥ L), y los puntos de corte de sus
   aristas hacia vecinos de abajo caen en él. Si las curvas de esa cota pasan por él una sola
   vez (una racha de vértices seguidos de una cadena), la curva pasa por el nodo y nada
   cambia. Si pasan dos veces o más (vecinos de abajo separados por otros de arriba: una
   silla justo en el nodo, o dos curvas a lo largo de una misma arista), se tocarían: cada uno
   de esos puntos se aparta del nodo **a lo largo de su arista**, hacia su extremo de abajo,
   hasta donde la superficie lineal está :data:`NODE_SHIFT_DZ_M` (0,5 mm) por debajo de la
   cota trazada (la mitad de la distancia a la siguiente cota trazada más baja, si es menor; y
   la mitad de la arista como mucho). Así la curva rodea el nodo por el lado de abajo, como
   pide «≥ L», ninguna curva toca a otra ni a sí misma, el vértice sigue en su arista y
   |Δz| ≤ 0,5 mm (RF-006-18 admite 1 mm). En la silla de 1 m que baja 0,025 m al norte y al
   sur del nodo, cada curva pasa a 0,02 m de él.
6. **Limpieza**: fuera los vértices repetidos seguidos (una cota justo igual a la de un
   centro o un vértice hace coincidir puntos de corte de varias aristas) y las curvas que se
   quedan con menos de dos vértices (longitud nula).
7. **Simplificación** de Douglas–Peucker en planta con ``gis.contours.simplify_m`` (0: no).
   Una curva abierta conserva sus extremos; una cerrada, su primer vértice, el más alejado de
   él y, en cada mitad, el más alejado de su cuerda (no se reduce a un segmento). Cada
   vértice quitado queda a ≤ la tolerancia del tramo que lo sustituye. No se comprueba que una
   curva simplificada no toque a otra.
8. **Longitud mínima** (``gis.contours.min_length_m``, 0: no): fuera las curvas más cortas
   (:attr:`ContourLine.length_m`, con el tramo de cierre de las cerradas).

Orden de las curvas: por cota y, en cada cota, por su primer punto de corte (por filas y
columnas de la rejilla; por el índice de la arista en el TIN). Todo en float64 y con las
coordenadas absolutas (las diferencias entre vecinos son exactas). Las entradas no se
modifican. Avance y cancelación (``JobCancelled``) por bloques de cuadros o triángulos.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.i18n import format_number
from ..jobs.worker_api import JobCancelled
from . import params
from .messages import GisError
from .points import _attribute, _expand, _report, _role_check
from .ports import Cancelled, Progress
from .raster import Raster
from .reports import Rejection, TopoReport
from .tin import Tin, _oriented

if TYPE_CHECKING:
    from .vector import FeatureSet

__all__ = [
    "INDEX_EVERY_KEY",
    "INDEX_OFFSET_KEY",
    "INDEX_TOLERANCE",
    "INTERVAL_KEY",
    "MAX_LEVELS",
    "MIN_LENGTH_KEY",
    "NODE_SHIFT_DZ_M",
    "SIMPLIFY_KEY",
    "ContourLine",
    "contours_from_features",
    "contours_from_raster",
    "contours_from_tin",
]

INTERVAL_KEY = "gis.contours.interval_m"
INDEX_EVERY_KEY = "gis.contours.index_every_m"
INDEX_OFFSET_KEY = "gis.contours.index_offset_m"
SIMPLIFY_KEY = "gis.contours.simplify_m"
MIN_LENGTH_KEY = "gis.contours.min_length_m"

INDEX_TOLERANCE = 1e-9
"""Una cota es de maestra si L/``index_every_m`` dista de un entero ≤ 10⁻⁹ (plan A14)."""

MAX_LEVELS = 1_000_000
"""Como mucho tantas cotas entre la mínima y la máxima de la superficie: una equidistancia
mucho menor que el desnivel (p. ej. 10⁻⁵ m) es un error de entrada, no un cálculo."""

NODE_SHIFT_DZ_M = 0.0005
"""Un punto de corte que cae en un nodo a la cota por el que pasarían dos veces las curvas de
esa cota se aparta del nodo, a lo largo de su arista, hasta donde la superficie lineal está
tantos metros por debajo de la cota trazada (0,5 mm, la mitad del |Δz| que admite RF-006-18;
menos si la siguiente cota trazada más baja está a menos del doble; la mitad de la arista como
mucho): ver el módulo, 5."""

_QUAD_BLOCK = 1 << 18  # cuadros por bloque de filas de la rejilla (avance y cancelación)
_TRIANGLE_BLOCK = 1 << 18  # triángulos por bloque del TIN
_PAIR_BUDGET = 1 << 20  # parejas (cuadro o triángulo, cota) por parte, como mucho
_BASE_FIELD = "cota base"
_OBJECT = "Curvas de nivel"


@dataclass(frozen=True, slots=True, eq=False)
class ContourLine:
    """Una curva de nivel: ``xyz`` float64 ``(n ≥ 2, 3)`` ABSOLUTO con Z = ``elevation``
    (la cota, m), ``is_index`` (maestra) y ``closed`` (anillo; el primer vértice no se repite
    al final). No copia ``xyz``. ``TypeError`` o ``ValueError`` si no cumple tipo y forma."""

    xyz: np.ndarray
    elevation: float
    is_index: bool
    closed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.xyz, np.ndarray) or self.xyz.dtype != np.float64:
            found = self.xyz.dtype if isinstance(self.xyz, np.ndarray) else type(self.xyz)
            raise TypeError(f"ContourLine.xyz es un ndarray float64, no {found}")
        if self.xyz.ndim != 2 or self.xyz.shape[1] != 3 or len(self.xyz) < 2:
            raise ValueError(f"ContourLine.xyz es (n ≥ 2, 3) y llega {self.xyz.shape}")

    @property
    def length_m(self) -> float:
        """Longitud en planta (m), con el tramo de cierre si es cerrada (CALCULADO)."""
        xy = self.xyz[:, :2]
        if self.closed:
            xy = np.vstack([xy, xy[:1]])
        step = np.diff(xy, axis=0)
        return float(np.hypot(step[:, 0], step[:, 1]).sum())


# Parámetros y cotas ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Settings:
    interval: float
    base: float
    index_every: float
    offset: float
    simplify: float
    min_length: float


def _setting(key: str, value: object) -> float:
    """El valor del parámetro ``key``: el de ``gis/params.py`` si ``value`` es ``None``; si
    no, comprobado (``ParamError`` ``core.param_*`` con la clave como campo)."""
    definition = params.param(key)
    return float(definition.default if value is None else definition.check(value))


def _is_finite_real(value: object) -> bool:
    """Verdadero si ``value`` es un número real finito que cabe en un float64 (no un
    booleano): la cota base, que no es un parámetro."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # un entero que no cabe en un float64
        return False


def _settings(name: str, interval_m: object, base_m: object, index_every_m: object,
              index_offset_m: object, simplify_m: object,
              min_length_m: object) -> _Settings:
    if not _is_finite_real(base_m):
        raise GisError("gis.contours_base_invalid", obj=_OBJECT, field=_BASE_FIELD,
                       value=base_m, surface=name)
    return _Settings(
        interval=_setting(INTERVAL_KEY, interval_m),
        base=float(base_m),  # type: ignore[arg-type]
        index_every=_setting(INDEX_EVERY_KEY, index_every_m),
        offset=_setting(INDEX_OFFSET_KEY, index_offset_m),
        simplify=_setting(SIMPLIFY_KEY, simplify_m),
        min_length=_setting(MIN_LENGTH_KEY, min_length_m),
    )


@dataclass(frozen=True, slots=True)
class _Levels:
    """Las cotas, por ``elevation`` creciente: si son maestras, a qué cota se trazan
    (``trace``: L, o L + desfase en las maestras), su orden por ``trace`` y cuánto se aparta
    de un nodo un punto de corte que se tocaría con otro (``node_drop``, m bajo su
    ``trace``: :data:`NODE_SHIFT_DZ_M` o la mitad de la distancia a la siguiente cota
    trazada más baja)."""

    elevation: np.ndarray
    is_index: np.ndarray
    trace: np.ndarray
    order: np.ndarray
    sorted_trace: np.ndarray
    node_drop: np.ndarray


def _k_range(low: float, high: float, shift: float, settings: _Settings) -> np.ndarray:
    """Los k con L = base + k·equidistancia a la que, trazada a L + ``shift``, puede cortar
    entre ``low`` y ``high`` (con uno de margen a cada lado por el redondeo)."""
    first = math.floor((low - shift - settings.base) / settings.interval) - 1
    last = math.ceil((high - shift - settings.base) / settings.interval) + 1
    return np.arange(first, last + 1, dtype=np.float64)


def _levels(low: float, high: float, settings: _Settings, name: str) -> _Levels | None:
    """Las cotas que cortan la superficie (trazadas en (``low``, ``high``]); ``None`` si
    ninguna. Demasiadas → ``GisError`` ``gis.contours_too_many``."""
    if not high > low:
        return None
    span = (high - low) / settings.interval
    if not span < MAX_LEVELS:
        count = math.floor(span) + 1 if math.isfinite(span) else span
        raise GisError("gis.contours_too_many", obj=_OBJECT, field=INTERVAL_KEY, value=count,
                       surface=name, interval=settings.interval, low=format_number(low, 2),
                       high=format_number(high, 2), limit=MAX_LEVELS)
    k = _k_range(low, high, 0.0, settings)
    if settings.offset != 0.0:
        k = np.union1d(k, _k_range(low, high, settings.offset, settings))
    elevation = settings.base + k * settings.interval
    ratio = elevation / settings.index_every
    is_index = np.abs(ratio - np.round(ratio)) <= INDEX_TOLERANCE
    trace = np.where(is_index, elevation + settings.offset, elevation)
    keep = (trace > low) & (trace <= high)
    if not keep.any():
        return None
    elevation, is_index, trace = elevation[keep], is_index[keep], trace[keep]
    order = np.argsort(trace, kind="stable")
    sorted_trace = trace[order]
    lower = np.searchsorted(sorted_trace, trace, side="left") - 1  # la trazada más baja más cerca
    gap = np.where(lower >= 0, trace - sorted_trace[np.maximum(lower, 0)], np.inf)
    return _Levels(elevation, is_index, trace, order, sorted_trace,
                   np.minimum(NODE_SHIFT_DZ_M, 0.5 * gap))


def _parts(lo: np.ndarray, hi: np.ndarray) -> list[np.ndarray]:
    """Los elementos (cuadros o triángulos) en partes de unas :data:`_PAIR_BUDGET` parejas
    (elemento, cota) como mucho (un elemento con más va solo), en orden."""
    sizes = hi - lo
    total = int(sizes.sum())
    items = np.arange(len(sizes), dtype=np.int64)
    if not total:
        return []
    if total <= _PAIR_BUDGET:
        return [items]
    cuts = np.searchsorted(np.cumsum(sizes), np.arange(_PAIR_BUDGET, total, _PAIR_BUDGET),
                           side="left")
    return [part for part in np.split(items, np.unique(cuts) + 1) if part.size]


# Tablas de casos -------------------------------------------------------------------------


def _directed(start: tuple[float, float], stop: tuple[float, float],
              corner: tuple[float, float], corner_above: bool, a: int,
              b: int) -> tuple[int, int]:
    """(a, b) si, de la arista ``a`` a la ``b`` (de punto medio a punto medio), la esquina
    ``corner`` queda a la izquierda cuando está arriba (o a la derecha cuando está abajo);
    si no, (b, a): lo alto, siempre a la izquierda."""
    cross = ((stop[0] - start[0]) * (corner[1] - start[1])
             - (stop[1] - start[1]) * (corner[0] - start[0]))
    return (a, b) if (cross > 0.0) == corner_above else (b, a)


def _square_table() -> np.ndarray:
    """``[caso, centro arriba, segmento]`` → (arista de salida, arista de llegada) de un
    cuadro, o (−1, −1). Esquinas en orden cíclico NO, NE, SE, SO con los bits 8, 4, 2, 1
    (sillas: 5 y 10); la arista e une las esquinas e y e + 1 (0 norte, 1 este, 2 sur,
    3 oeste)."""
    corners = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
    bits = (8, 4, 2, 1)
    middles = ((0.5, 1.0), (1.0, 0.5), (0.5, 0.0), (0.0, 0.5))
    table = np.full((16, 2, 2, 2), -1, dtype=np.int64)
    for case in range(16):
        above = [bool(case & bit) for bit in bits]
        cut = [e for e in range(4) if above[e] != above[(e + 1) % 4]]
        for centre in (0, 1):
            if len(cut) == 2:
                segments = [(cut[0], cut[1], 0)]
            elif len(cut) == 4:  # silla: se recortan las esquinas de la otra clase que el centro
                segments = [((c - 1) % 4, c, c) for c in range(4) if above[c] != bool(centre)]
            else:
                segments = []
            for slot, (a, b, ref) in enumerate(segments):
                table[case, centre, slot] = _directed(middles[a], middles[b], corners[ref],
                                                      above[ref], a, b)
    return table


def _triangle_table() -> np.ndarray:
    """``[caso]`` → (arista de salida, arista de llegada) de un triángulo antihorario
    (esquinas 0, 1, 2 con los bits 4, 2, 1; la arista e une las esquinas e y e + 1)."""
    corners = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    bits = (4, 2, 1)
    middles = ((0.5, 0.0), (0.5, 0.5), (0.0, 0.5))
    table = np.full((8, 2), -1, dtype=np.int64)
    for case in range(1, 7):
        above = [bool(case & bit) for bit in bits]
        cut = [e for e in range(3) if above[e] != above[(e + 1) % 3]]
        table[case] = _directed(middles[cut[0]], middles[cut[1]], corners[0], above[0],
                                cut[0], cut[1])
    return table


_SQUARE = _square_table()
_TRIANGLE = _triangle_table()
_SQUARE_BITS = np.array([8, 4, 2, 1], dtype=np.int64)
_TRIANGLE_BITS = np.array([4, 2, 1], dtype=np.int64)


# Avance y cancelación --------------------------------------------------------------------


def _stage(progress: Progress | None, cancelled: Cancelled | None, fraction: float,
           what: str) -> None:
    if cancelled is not None and cancelled():
        raise JobCancelled(f"Cancelado al generar las curvas de nivel: {what}")
    if progress is not None:
        progress(fraction, f"Generando las curvas de nivel: {what}")


def _block_start(cancelled: Cancelled | None, index: int, total: int) -> None:
    if cancelled is not None and cancelled():
        raise JobCancelled(
            f"Cancelado al generar las curvas de nivel en el bloque {index + 1} de {total}")


def _block_done(progress: Progress | None, index: int, total: int) -> None:
    if progress is not None:
        progress(0.8 * (index + 1) / total,
                 f"Generando las curvas de nivel: bloque {index + 1} de {total}")


# Puntos de corte -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Cuts:
    """Los puntos de corte de unas claves y la arista que contiene cada uno: sus extremos
    ``a`` y ``b`` (número de nodo de la rejilla o de vértice del TIN) con sus coordenadas
    ABSOLUTAS y sus cotas, la cota a la que se traza (``trace``) y cuánto se apartaría de un
    nodo (``drop``, m bajo ``trace``)."""

    a: np.ndarray
    b: np.ndarray
    xa: np.ndarray
    ya: np.ndarray
    za: np.ndarray
    xb: np.ndarray
    yb: np.ndarray
    zb: np.ndarray
    trace: np.ndarray
    drop: np.ndarray

    def xy(self) -> tuple[np.ndarray, np.ndarray]:
        """Interpolación lineal en la arista, a s = (t − za)/(zb − za) de ``a``."""
        s = (self.trace - self.za) / (self.zb - self.za)
        return self.xa + s * (self.xb - self.xa), self.ya + s * (self.yb - self.ya)

    def node(self) -> np.ndarray:
        """El extremo justo a la cota trazada (el de arriba) en el que cae cada punto; −1 si
        cae dentro de su arista."""
        return np.where(self.za == self.trace, self.a,
                        np.where(self.zb == self.trace, self.b, -1))

    def away(self, which: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Los puntos ``which`` (que caen en su nodo) apartados de él a lo largo de su arista,
        hacia el otro extremo, hasta donde la superficie lineal está ``drop`` por debajo de la
        cota trazada (la mitad de la arista como mucho). En una arista de la rejilla, la
        coordenada que no cambia queda bit a bit."""
        at_a = self.za[which] == self.trace[which]
        xa, ya, xb, yb = self.xa[which], self.ya[which], self.xb[which], self.yb[which]
        node_x, node_y = np.where(at_a, xa, xb), np.where(at_a, ya, yb)
        ux, uy = np.where(at_a, xb - xa, xa - xb), np.where(at_a, yb - ya, ya - yb)
        fall = self.trace[which] - np.where(at_a, self.zb[which], self.za[which])  # > 0
        t = np.minimum(self.drop[which] / fall, 0.5)
        return node_x + t * ux, node_y + t * uy


def _touching(node: np.ndarray, level: np.ndarray, node_count: int, chain: np.ndarray,
              closed: np.ndarray) -> np.ndarray:
    """Los vértices (en orden de cadena) que caen en un nodo a la cota por el que las curvas
    de esa cota pasan más de una vez: cada paso es una racha de vértices seguidos de una
    cadena en ese nodo y cota (en una cerrada, la racha del final sigue en la del
    principio). ``node``: el nodo de cada vértice o −1; ``level``: su cota (índice)."""
    moved = np.zeros(len(node), dtype=bool)
    at = node >= 0
    if not at.any():
        return moved
    group = np.where(at, level * node_count + node, -1)
    run = at.copy()
    run[1:] &= ~((group[1:] == group[:-1]) & (chain[1:] == chain[:-1]))
    sizes = np.bincount(chain, minlength=len(closed))
    first = np.cumsum(sizes) - sizes
    last = first + sizes - 1
    wrap = closed & (first != last) & at[first] & (group[first] == group[last])
    run[first[wrap]] = False
    groups, passes = np.unique(group[run], return_counts=True)
    moved[at] = np.isin(group[at], groups[passes > 1])
    return moved


# Rejilla ---------------------------------------------------------------------------------


def contours_from_raster(
    raster: Raster,
    *,
    interval_m: float | None = None,
    base_m: float = 0.0,
    index_every_m: float | None = None,
    index_offset_m: float | None = None,
    simplify_m: float | None = None,
    min_length_m: float | None = None,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> list[ContourLine]:
    """Las curvas de nivel de ``raster`` (RF-006-18; plan A14; ver el módulo) por *marching
    squares* sobre los cuadros de 4 centros con dato.

    ``interval_m``, ``index_every_m``, ``index_offset_m``, ``simplify_m`` y
    ``min_length_m``: los parámetros ``gis.contours.*`` (``None``, el valor por defecto; uno
    no válido → ``ParamError`` ``core.param_*`` con la clave); ``base_m``, la cota base (si no
    es un número finito, ``gis.contours_base_invalid``); ``name``, el de la superficie en los
    mensajes. Sin cuadros con dato o sin ninguna cota que la corte, ``[]``. Avance y
    cancelación (``JobCancelled``) por bloques de filas de :data:`_QUAD_BLOCK` cuadros.
    ``TypeError`` si ``raster`` no es un ``Raster``."""
    if not isinstance(raster, Raster):
        raise TypeError(f"raster debe ser un Raster, no {type(raster).__name__}")
    settings = _settings(name, interval_m, base_m, index_every_m, index_offset_m,
                         simplify_m, min_length_m)
    _stage(progress, cancelled, 0.0, "cotas")
    values = raster.values
    grid = raster.grid
    nrows, ncols = grid.shape
    finite = np.isfinite(values)
    levels = None
    if nrows > 1 and ncols > 1 and finite.any():
        levels = _levels(float(values[finite].min()), float(values[finite].max()), settings,
                         name)
    if levels is None:
        _stage(progress, None, 1.0, "terminado")
        return []
    edge_count = 2 * nrows * ncols  # arista = 2·nodo (+1 si va hacia el sur)
    block = max(1, _QUAD_BLOCK // (ncols - 1))
    firsts = range(0, nrows - 1, block)
    starts, ends = [], []
    for index, first in enumerate(firsts):
        _block_start(cancelled, index, len(firsts))
        start, end = _grid_segments(values, first, min(first + block, nrows - 1), levels,
                                    edge_count)
        starts.append(start)
        ends.append(end)
        _block_done(progress, index, len(firsts))

    def cuts(keys: np.ndarray) -> _Cuts:
        return _grid_cuts(keys, raster, levels, edge_count)

    return _lines(np.concatenate(starts), np.concatenate(ends), edge_count, nrows * ncols,
                  cuts, levels, settings, progress, cancelled)


def _grid_segments(values: np.ndarray, first: int, stop: int, levels: _Levels,
                   edge_count: int) -> tuple[np.ndarray, np.ndarray]:
    """Los segmentos (claves de su punto de salida y de llegada) de los cuadros de las filas
    ``first``…``stop − 1``, por cuadros (filas y columnas), cotas y segmentos."""
    ncols = values.shape[1]
    corners = np.stack([values[first:stop, :-1].ravel(), values[first:stop, 1:].ravel(),
                        values[first + 1:stop + 1, 1:].ravel(),
                        values[first + 1:stop + 1, :-1].ravel()], axis=1)  # NO, NE, SE, SO
    valid = np.flatnonzero(np.isfinite(corners).all(axis=1))
    corners = corners[valid]
    node = (first + valid // (ncols - 1)) * ncols + valid % (ncols - 1)  # su esquina NO
    lo = np.searchsorted(levels.sorted_trace, corners.min(axis=1), side="right")
    hi = np.searchsorted(levels.sorted_trace, corners.max(axis=1), side="right")
    shifts = np.array([0, 3, 2 * ncols, 1], dtype=np.int64)  # aristas N, E, S y O
    starts, ends = [np.empty(0, dtype=np.int64)], [np.empty(0, dtype=np.int64)]
    for part in _parts(lo, hi):
        owner, position = _expand(lo[part], hi[part])
        quad = part[owner]
        level = levels.order[position]
        trace = levels.trace[level]
        z = corners[quad]
        case = ((z >= trace[:, None]) * _SQUARE_BITS).sum(axis=1)
        centre = (z.sum(axis=1) * 0.25 >= trace).astype(np.int64)
        codes = _SQUARE[case, centre]
        pair, slot = np.nonzero(codes[:, :, 0] >= 0)
        base = level[pair] * edge_count + 2 * node[quad[pair]]
        starts.append(base + shifts[codes[pair, slot, 0]])
        ends.append(base + shifts[codes[pair, slot, 1]])
    return np.concatenate(starts), np.concatenate(ends)


def _grid_cuts(keys: np.ndarray, raster: Raster, levels: _Levels, edge_count: int) -> _Cuts:
    """Los puntos de corte ``keys``: en la arista del nodo a = (fila, columna) al de su
    derecha o al de debajo (nodo = fila·columnas + columna), a s = (t − za)/(zb − za)."""
    grid = raster.grid
    level = keys // edge_count
    edge = keys - level * edge_count
    node = edge >> 1
    row, col = np.divmod(node, grid.ncols)
    south = (edge & 1).astype(bool)
    row_b = row + south
    col_b = col + ~south
    # Centros como Grid.centers, bit a bit: una de las dos coordenadas queda en el centro.
    xa = grid.west + (col.astype(np.float64) + 0.5) * grid.dx
    xb = grid.west + (col_b.astype(np.float64) + 0.5) * grid.dx
    ya = grid.north - (row.astype(np.float64) + 0.5) * grid.dy
    yb = grid.north - (row_b.astype(np.float64) + 0.5) * grid.dy
    return _Cuts(node, row_b * grid.ncols + col_b, xa, ya, raster.values[row, col], xb, yb,
                 raster.values[row_b, col_b], levels.trace[level], levels.node_drop[level])


# TIN ---------------------------------------------------------------------------------------


def contours_from_tin(
    tin: Tin,
    *,
    interval_m: float | None = None,
    base_m: float = 0.0,
    index_every_m: float | None = None,
    index_offset_m: float | None = None,
    simplify_m: float | None = None,
    min_length_m: float | None = None,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> list[ContourLine]:
    """Las curvas de nivel de ``tin`` (RF-006-18; plan A14; ver el módulo): por triángulo y
    cota, el segmento entre las dos aristas que la cortan. Los mismos parámetros, errores y
    resultado que :func:`contours_from_raster`; avance y cancelación por bloques de
    :data:`_TRIANGLE_BLOCK` triángulos. ``TypeError`` si ``tin`` no es un ``Tin``."""
    if not isinstance(tin, Tin):
        raise TypeError(f"tin debe ser un Tin, no {type(tin).__name__}")
    settings = _settings(name, interval_m, base_m, index_every_m, index_offset_m,
                         simplify_m, min_length_m)
    _stage(progress, cancelled, 0.0, "cotas")
    vertices = tin.vertices
    faces = _oriented(vertices[:, :2], tin.faces.astype(np.int64))
    corner_z = vertices[:, 2][faces]
    levels = _levels(float(corner_z.min()), float(corner_z.max()), settings, name)
    if levels is None:
        _stage(progress, None, 1.0, "terminado")
        return []
    count = len(vertices)
    ends_ab = np.stack([faces, np.roll(faces, -1, axis=1)], axis=2)  # arista e: esquinas e, e+1
    pair_keys = ends_ab.min(axis=2) * count + ends_ab.max(axis=2)
    edges, inverse = np.unique(pair_keys.ravel(), return_inverse=True)
    face_edges = inverse.reshape(faces.shape)
    edge_count = len(edges)
    firsts = range(0, len(faces), _TRIANGLE_BLOCK)
    starts, ends = [], []
    for index, first in enumerate(firsts):
        _block_start(cancelled, index, len(firsts))
        stop = first + _TRIANGLE_BLOCK
        start, end = _tin_segments(corner_z[first:stop], face_edges[first:stop], levels,
                                   edge_count)
        starts.append(start)
        ends.append(end)
        _block_done(progress, index, len(firsts))

    def cuts(keys: np.ndarray) -> _Cuts:
        level = keys // edge_count
        low, high = np.divmod(edges[keys - level * edge_count], count)
        return _Cuts(low, high, vertices[low, 0], vertices[low, 1], vertices[low, 2],
                     vertices[high, 0], vertices[high, 1], vertices[high, 2],
                     levels.trace[level], levels.node_drop[level])

    return _lines(np.concatenate(starts), np.concatenate(ends), edge_count, count, cuts,
                  levels, settings, progress, cancelled)


def _tin_segments(corner_z: np.ndarray, face_edges: np.ndarray, levels: _Levels,
                  edge_count: int) -> tuple[np.ndarray, np.ndarray]:
    """Los segmentos (claves de salida y de llegada) de un bloque de triángulos, por
    triángulos y cotas."""
    lo = np.searchsorted(levels.sorted_trace, corner_z.min(axis=1), side="right")
    hi = np.searchsorted(levels.sorted_trace, corner_z.max(axis=1), side="right")
    starts, ends = [np.empty(0, dtype=np.int64)], [np.empty(0, dtype=np.int64)]
    for part in _parts(lo, hi):
        owner, position = _expand(lo[part], hi[part])
        triangle = part[owner]
        level = levels.order[position]
        case = ((corner_z[triangle] >= levels.trace[level][:, None]) * _TRIANGLE_BITS).sum(axis=1)
        codes = _TRIANGLE[case]
        own = face_edges[triangle]
        rows = np.arange(len(triangle))
        base = level * edge_count
        starts.append(base + own[rows, codes[:, 0]])
        ends.append(base + own[rows, codes[:, 1]])
    return np.concatenate(starts), np.concatenate(ends)


# Encadenado y curvas -----------------------------------------------------------------------


def _chains(start: np.ndarray, end: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Encadena los segmentos (clave de salida → clave de llegada): las claves de los
    vértices de cada cadena seguidas, la cadena de cada vértice y si es cerrada.

    El sucesor de un segmento es el que sale de su punto de llegada (como mucho uno por
    segmento y uno por punto, aunque la entrada esté rota). Saltos de puntero: un segmento al
    que no llega ninguna cabeza está en un ciclo, que se corta en su segmento de menor clave
    de salida; después, la distancia de cada segmento a su cabeza (Wyllie). Las cadenas van
    por la clave de salida de su cabeza (cota y arista); una abierta termina en el punto de
    llegada de su último segmento."""
    m = len(start)
    index = np.arange(m, dtype=np.int64)
    by_start = np.argsort(start, kind="stable")
    ordered = start[by_start]
    at = np.minimum(np.searchsorted(ordered, end), m - 1)
    candidate = np.where(ordered[at] == end, by_start[at], -1)
    linked = np.flatnonzero(candidate >= 0)
    _unique, first = np.unique(candidate[linked], return_index=True)
    succ = np.full(m, -1, dtype=np.int64)
    succ[linked[first]] = candidate[linked[first]]
    pred = np.full(m, -1, dtype=np.int64)
    has = succ >= 0
    pred[succ[has]] = index[has]
    rounds = int(m).bit_length() + 1

    pointer = pred.copy()
    for _round in range(rounds):
        active = np.flatnonzero(pointer >= 0)
        if not active.size:
            break
        pointer[active] = pointer[pointer[active]]
    cyclic = pointer >= 0
    if cyclic.any():
        members = np.flatnonzero(cyclic)
        best = index.copy()
        step = succ.copy()
        for _round in range(rounds):
            mine = best[members]
            other = best[step[members]]
            better = (start[other] < start[mine]) | ((start[other] == start[mine])
                                                     & (other < mine))
            best[members] = np.where(better, other, mine)
            step[members] = step[step[members]]
        heads = members[best[members] == members]
        succ[pred[heads]] = -1
        pred[heads] = -1

    rank = (pred >= 0).astype(np.int64)
    head = np.where(pred >= 0, pred, index)
    pointer = pred.copy()
    while True:
        active = np.flatnonzero(pointer >= 0)
        if not active.size:
            break
        jump = pointer[active]
        rank[active] = rank[active] + rank[jump]
        head[active] = head[jump]
        pointer[active] = pointer[jump]

    order = np.lexsort((rank, head, start[head]))
    head_sorted = head[order]
    bounds = np.flatnonzero(head_sorted[1:] != head_sorted[:-1]) + 1
    begin = np.concatenate([[0], bounds])
    stop = np.concatenate([bounds, [m]])
    closed = cyclic[head_sorted[begin]]
    tails = stop[~closed]
    keys = np.insert(start[order], tails, end[order[tails - 1]])
    sizes = (stop - begin) + (~closed)
    chain = np.repeat(np.arange(len(begin), dtype=np.int64), sizes)
    return keys, chain, closed


def _clean(x: np.ndarray, y: np.ndarray, chain: np.ndarray,
           closed: np.ndarray) -> np.ndarray:
    """Los vértices que quedan: sin repetidos seguidos (ni el último de una cerrada igual al
    primero) y sin las curvas de menos de dos vértices."""
    same = np.zeros(len(x), dtype=bool)
    same[1:] = (x[1:] == x[:-1]) & (y[1:] == y[:-1]) & (chain[1:] == chain[:-1])
    keep = ~same
    sizes = np.bincount(chain[keep], minlength=len(closed))
    kept = np.flatnonzero(keep)
    stop = np.cumsum(sizes)
    begin, last = kept[stop - sizes], kept[stop - 1]
    wrap = closed & (sizes > 1) & (x[last] == x[begin]) & (y[last] == y[begin])
    keep[last[wrap]] = False
    keep &= (sizes - wrap >= 2)[chain]
    return keep


def _segment_distance(px: np.ndarray, py: np.ndarray, ax: np.ndarray, ay: np.ndarray,
                      bx: np.ndarray, by: np.ndarray) -> np.ndarray:
    """Distancia en planta de cada punto p al segmento a–b (al punto a si a = b)."""
    ux, uy = bx - ax, by - ay
    vx, vy = px - ax, py - ay
    length2 = ux * ux + uy * uy
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(length2 > 0.0, (vx * ux + vy * uy) / length2, 0.0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(vx - t * ux, vy - t * uy)


def _simplify(x: np.ndarray, y: np.ndarray, chain: np.ndarray, closed: np.ndarray,
              tolerance: float) -> np.ndarray:
    """Los vértices que deja Douglas–Peucker con ``tolerance`` (m, en planta), todas las
    curvas a la vez, un nivel de la recursión por vuelta. Una cerrada se trata como abierta
    con su primer vértice repetido al final; sus dos primeros niveles se parten siempre (si el
    más alejado no está en la cuerda), así conserva al menos tres vértices."""
    count = len(closed)
    sizes = np.bincount(chain, minlength=count)
    begin = np.cumsum(sizes) - sizes
    work = sizes + closed
    wstop = np.cumsum(work)
    wbegin = wstop - work
    owner, local = _expand(np.zeros(count, dtype=np.int64), work)
    source = begin[owner] + np.where(local < sizes[owner], local, 0)
    wx, wy = x[source], y[source]
    keep = np.zeros(len(source), dtype=bool)
    keep[wbegin] = True
    keep[wstop - 1] = True
    lo, hi = wbegin, wstop - 1
    forced = np.where(closed, 2, 0)
    while True:
        wide = hi - lo >= 2
        lo, hi, forced = lo[wide], hi[wide], forced[wide]
        if not lo.size:
            break
        interval, inner = _expand(lo + 1, hi)
        d = _segment_distance(wx[inner], wy[inner], wx[lo[interval]], wy[lo[interval]],
                              wx[hi[interval]], wy[hi[interval]])
        width = hi - lo - 1
        farthest = np.maximum.reduceat(d, np.cumsum(width) - width)
        best = np.flatnonzero(d == farthest[interval])
        _unique, first = np.unique(interval[best], return_index=True)
        split = inner[best[first]]
        go = (farthest > tolerance) | ((forced > 0) & (farthest > 0.0))
        keep[split[go]] = True
        child = np.maximum(forced[go] - 1, 0)
        lo = np.concatenate([lo[go], split[go]])
        hi = np.concatenate([split[go], hi[go]])
        forced = np.concatenate([child, child])
    copy = np.zeros(len(source), dtype=bool)
    copy[(wstop - 1)[closed]] = True
    result = np.zeros(len(x), dtype=bool)
    result[source[keep & ~copy]] = True
    return result


def _lines(start: np.ndarray, end: np.ndarray, edge_count: int, node_count: int,
           cuts: Callable[[np.ndarray], _Cuts], levels: _Levels, settings: _Settings,
           progress: Progress | None, cancelled: Cancelled | None) -> list[ContourLine]:
    """Las curvas de los segmentos: encadenado, coordenadas (apartadas de un nodo a la cota
    las que se tocarían), limpieza, simplificación y longitud mínima."""
    lines: list[ContourLine] = []
    if len(start):
        _stage(progress, cancelled, 0.85, "encadenado")
        keys, chain, closed = _chains(start, end)
        level = keys[np.searchsorted(chain, np.arange(len(closed)))] // edge_count
        _stage(progress, cancelled, 0.9, "vértices")
        found = cuts(keys)
        x, y = found.xy()
        moved = _touching(found.node(), keys // edge_count, node_count, chain, closed)
        if moved.any():
            x[moved], y[moved] = found.away(moved)
        del found
        keep = _clean(x, y, chain, closed)
        x, y, chain = x[keep], y[keep], chain[keep]
        if settings.simplify > 0.0 and len(x):
            _stage(progress, cancelled, 0.95, "simplificación")
            alive = np.unique(chain)
            local = np.searchsorted(alive, chain)
            keep = _simplify(x, y, local, closed[alive], settings.simplify)
            x, y, chain = x[keep], y[keep], chain[keep]
        alive = np.unique(chain)
        sizes = np.bincount(chain, minlength=len(closed))[alive]
        stops = np.cumsum(sizes)
        xyz = np.column_stack([x, y, levels.elevation[level][chain]])
        for c, first, stop in zip(alive.tolist(), (stops - sizes).tolist(), stops.tolist(),
                                  strict=True):
            line = ContourLine(xyz[first:stop], float(levels.elevation[level[c]]),
                               bool(levels.is_index[level[c]]), bool(closed[c]))
            if settings.min_length <= 0.0 or line.length_m >= settings.min_length:
                lines.append(line)
    _stage(progress, None, 1.0, "terminado")
    return lines


# Curvas de una capa importada (T29; RF-006-12) -------------------------------------------

_LINE_TYPES = ("LINESTRING", "MULTILINESTRING")


def _elevation(value: object) -> float | None:
    """La cota de un campo: un número finito (no booleano) o ``None``."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def contours_from_features(
    features: FeatureSet, *, elevation_field: str | None = None
) -> tuple[list[ContourLine], TopoReport]:
    """Las curvas de nivel de una capa con ese papel (RF-006-12): cada LineString o cada parte
    de un MultiLineString es una :class:`ContourLine` con sus vértices tal como llegan (la M,
    ya descartada al leer). La cota de la curva es la del campo ``elevation_field`` si lo hay
    y tiene un número; si no, la Z de su primer vértice. Una línea sin Z toma esa cota en
    todos sus vértices y, sin ella, se rechaza (``gis.feature_without_z``: una curva sin cota
    no se acepta); la Z de una línea que la tiene no se cambia. Una línea con su primer
    vértice repetido al final (4 o más) es **cerrada**, sin repetirlo (``gis.store`` lo
    vuelve a escribir al guardarla). Ninguna es maestra (la capa no lo dice). Una entidad de
    otro tipo se rechaza con su número (``gis.feature_role_mismatch``). ``ValueError`` si
    la capa no tiene el campo."""
    from .messages import render

    values = _attribute(features, elevation_field)
    rejected: list[Rejection] = []
    lines: list[ContourLine] = []
    layer = features.layer.name
    for index, fid in enumerate(features.fids):
        geometry = features.geometries[index]
        if geometry.geometry_type not in _LINE_TYPES:
            problem = _role_check(features, index, _LINE_TYPES, "curvas de nivel",
                                  "curva de nivel")
            if problem is not None:
                rejected.append(problem)
            continue
        field = None if values is None else _elevation(values[index])
        if not geometry.has_z and field is None:
            code = "gis.feature_without_z"
            rejected.append(Rejection(fid, render(code, layer=layer, row=fid,
                                                  role="curva de nivel"), code))
            continue
        parts = ([geometry.coords] if geometry.geometry_type == "LINESTRING"
                 else list(geometry.coords))
        for part in parts:
            xyz = (np.ascontiguousarray(part, dtype=np.float64) if geometry.has_z
                   else np.column_stack([part[:, 0], part[:, 1],
                                         np.full(len(part), field, dtype=np.float64)]))
            closed = len(xyz) >= 4 and bool(np.array_equal(xyz[0], xyz[-1]))
            if closed:
                xyz = np.ascontiguousarray(xyz[:-1])
            elevation = float(xyz[0, 2]) if field is None else field
            lines.append(ContourLine(xyz, elevation, False, closed))
    return lines, _report(features, rejected, points=0, lines=len(lines))
