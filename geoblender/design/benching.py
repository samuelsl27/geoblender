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

Python puro (nivel 8), con numpy, sin importar ``reserves`` ni ``bl``.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "bench_cut",
    "bench_fill",
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
