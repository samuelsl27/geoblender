# SPDX-License-Identifier: GPL-3.0-or-later
"""La rasante acotada de una pista (spec 017, T11; HU-017-1 y HU-017-4; RF-017-15 a RF-017-18; CE-017-03; RNF-017-03; plan 017 §5.4 A5, §5.3.1 y
§5.8 H-4).

El plan y la tarea nombran este módulo y sus funciones con la palabra inglesa de la **ley** del mineral, que en ``design`` no aparece (glosario §14 y
``GlossaryTest`` de la 014): la pendiente de la rasante es ``gradient`` (decisión de la sesión principal tras la T02). Los textos para la persona
siguen diciendo «rasante» y «pendiente».

Lo que da, todo en el dominio (Python y numpy, sin Blender), en float64 y **vectorizado** (``minimum.accumulate``; sin bucle por estación):

- **La rasante** (:func:`gradient_line`; A5, RF-017-15, D-9): sobre las estaciones ``s_i`` del eje (cada ``w`` m y una última en su extremo,
  :attr:`design.road_axis.Axis.stations`) y el terreno ``t_i`` de la superficie de partida en ellas (la interpolación bilineal en la rejilla del proyecto
  la hace quien llama), la **mayor minorante** ``Baja_i = mín_j (t_j + pd·|s_i − s_j|)`` y la **menor mayorante** ``Alta_i = máx_j (t_j − pd·|s_i − s_j|)``
  pd-Lipschitz del perfil, calculadas en O(n) con la minorante desde la izquierda ``F_i = pd·s_i + mín.acumulado(t − pd·s)`` y desde la derecha
  ``B_i = −pd·s_i + mín.acumulado inverso(t + pd·s)`` (``Baja = mín(F, B)``; ``Alta`` es lo mismo con ``máx``). La rasante es su **media**, **limitada a la
  banda que dejan los extremos** ``[máx(z₀ − pd·s, z₁ − pd·(S − s)), mín(z₀ + pd·s, z₁ + pd·(S − s))]`` y con ``z₀`` y ``z₁`` fijos: la pendiente de
  cada tramo es ≤ pd (a ≤ 10⁻⁹) y, donde el terreno no pasa de pd, la rasante **es** el terreno (movimiento 0), porque entonces ``Baja = t = Alta``. Es una
  media de dos funciones pd-Lipschitz limitada por otras dos: sigue siendo pd-Lipschitz.
- **El desnivel imposible** (:class:`DropTooSteep`; RF-017-16): si ``|z₁ − z₀| > pd·S`` (``S`` es la longitud del **eje**, con sus curvas, que acortan la ruta),
  **rechazo** con la longitud del eje, la necesaria (``|Δz| / pd``) y el desnivel, sin cambiar las cotas ni la pendiente por su cuenta.
- **La media** (:func:`mean_gradient`, :func:`mean_gradient_notice`, :func:`steepest_stretches`; RF-017-17, D-7): ``Σ|Δcota| / S`` y, si pasa de ``pm``, el
  aviso (``des.road_mean_gradient``) con la media, el límite y los tramos de mayor pendiente con su abscisa y su lugar. La **confirmación expresa y el
  motivo** (que van a los ajustes de la operación) los pide y los registra la operación de la pista, no este módulo.
- **El modo «eje 3D»** (:func:`check_axis_3d`; RF-017-18): la Z de la línea **es** la rasante y no se recalcula; se comprueba la pendiente entre estaciones
  cada ``w`` m (≤ pd), la media (≤ pm) y los radios de su planta (≥ Rmín) y **cada incumplimiento es un aviso** con su abscisa y su lugar. **La línea no se
  corrige** (es una entrada, principio 7; es el contrato de R-35).

Unidades: ``pd`` y las pendientes que devuelven las funciones de números son **tanto por uno** (0,10 = 10 %); las cifras que llegan a una persona (los
avisos y :class:`Stretch`), en **%**, como las del perfil (``max_gradient_pct``, ``max_mean_gradient_pct``).

**Perezoso** (RNF-001-03): ni ``design.model`` ni nada del arranque lo importan; lo pide quien da la rasante a un eje.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Any

import numpy as np

from .messages import DesignError
from .preview import Named, Notice
from .road_axis import Axis

__all__ = [
    "LISTED_STRETCHES",
    "DropTooSteep",
    "Stretch",
    "check_axis_3d",
    "gradient_line",
    "mean_gradient",
    "mean_gradient_notice",
    "steepest_stretches",
]

LISTED_STRETCHES = 5
"""Cuántos tramos de mayor pendiente enseña el aviso de la media (de presentación, para la persona que lee: no es una cifra minera)."""
_DROP_TOLERANCE_M = 1e-10
"""El margen (m) con que el desnivel se compara con ``pd·S``: un desnivel igual a ``pd·S`` más el ruido de la última cifra cabe."""
_GRADIENT_TOLERANCE = 1e-9
"""El margen (tanto por uno) con que una pendiente se compara con pd o pm: RF-017-15 pide la pendiente de cada tramo ≤ pd a ≤ 10⁻⁹."""
_TIE_DECIMALS = 9
"""Las pendientes (tanto por uno) que difieren menos de 10⁻⁹ son la misma al ordenar los tramos: el ruido de la última cifra no decide el orden."""


# --- Las entradas -------------------------------------------------------------------------------------------------------


def _real(value: object, what: str, *, positive: bool = False) -> float:
    """``value`` como un número real finito (con ``positive``, además mayor que 0): ``TypeError`` si no es un número real, ``ValueError`` si no es
    finito o no es positivo (errores del programa: la preparación de la pista rechazó antes, con su capa, su pista y su valor, RF-017-04)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise ValueError(f"{what} es un número finito{' y positivo' if positive else ''}, no {value!r}")
    return number


def _vector(values: object, what: str, size: int | None = None) -> np.ndarray:
    """Una **copia** float64 unidimensional de ``values`` con al menos dos números finitos (y ``size`` si se pide): ``ValueError`` si no."""
    try:
        array = np.array(values, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{what} no es un array de números: {error}") from error
    if array.ndim != 1 or array.shape[0] < 2:
        raise ValueError(f"{what} es un vector con al menos dos números: forma {array.shape}")
    if size is not None and array.shape[0] != size:
        raise ValueError(f"{what} tiene {array.shape[0]} valores y se esperaban {size} (uno por estación del eje)")
    if not bool(np.isfinite(array).all()):
        raise ValueError(f"{what} es finito (sin celdas sin dato)")
    return array


def _stations(values: object) -> np.ndarray:
    """Las estaciones (copia float64): al menos dos, finitas y **estrictamente crecientes**: ``ValueError`` si no."""
    s = _vector(values, "las estaciones del eje")
    if not bool((np.diff(s) > 0.0).all()):
        raise ValueError("las estaciones del eje crecen estrictamente (sin repetir ni volver atrás)")
    return s


def _frozen(array: np.ndarray) -> np.ndarray:
    """``array`` (propio de quien lo crea) de solo lectura."""
    array.flags.writeable = False
    return array


def _shown(value: float) -> float:
    """Una cifra de un rechazo como la lee una persona: a milésimas."""
    return round(float(value), 3)


# --- El desnivel imposible ---------------------------------------------------------------------------------------------


class DropTooSteep(Exception):
    """El rechazo de RF-017-16: el desnivel entre la cota de inicio y la de fin pasa de ``pd`` por la longitud del eje (con sus curvas) y **no se cambian las
    cotas ni la pendiente por su cuenta**. Lleva la longitud del eje (``length_m``), el desnivel en valor absoluto (``drop_m``), la pendiente de diseño
    (``max_gradient``, tanto por uno) y la longitud necesaria (``needed_m`` = ``drop_m / max_gradient``). :meth:`error` lo convierte en el rechazo del
    catálogo (``des.road_drop_too_steep``) con la capa, la pista y el perfil."""

    def __init__(self, length_m: float, drop_m: float, max_gradient: float) -> None:
        self.length_m = float(length_m)
        self.drop_m = abs(float(drop_m))
        self.max_gradient = float(max_gradient)
        self.needed_m = self.drop_m / self.max_gradient
        super().__init__(
            f"el desnivel de {_shown(self.drop_m)} m pide un eje de {_shown(self.needed_m)} m y el eje mide {_shown(self.length_m)} m")

    def error(self, *, layer: str, entity: str, profile: Any) -> DesignError:
        """El rechazo de la persona (``des.road_drop_too_steep``, RF-017-16) con la capa, la pista (``entity``) y el perfil (un
        :class:`~design.road_profiles.RoadProfile`: la clave de su pendiente máxima es el campo y su valor, el valor), la longitud del eje, la necesaria y
        el desnivel; que no se cambian las cotas ni la pendiente por su cuenta y que no se crea nada lo dice el texto del catálogo."""
        from .params import RoadProfileParam, road_profile_key  # solo al rechazar: los módulos de la pista son perezosos

        return DesignError(
            "des.road_drop_too_steep", obj=f"Pista «{entity}» de la capa «{layer}»",
            field=road_profile_key(profile.code, RoadProfileParam.MAX_GRADIENT), value=profile.max_gradient_pct, layer=layer, entity=entity,
            drop=_shown(self.drop_m), gradient=profile.max_gradient_pct, length=_shown(self.length_m), needed=_shown(self.needed_m))


# --- La rasante --------------------------------------------------------------------------------------------------------


def gradient_line(stations_s: Any, terrain: Any, pd: float, z_start: float, z_end: float) -> np.ndarray:
    """La rasante acotada de un eje (A5; RF-017-15, RF-017-16, D-9): su cota en cada estación de ``stations_s`` (m desde el origen, estrictamente crecientes:
    cada ``w`` m y una última en el extremo) con el ``terrain`` (m; la superficie de partida en esas estaciones, sin celdas sin dato), la pendiente de
    diseño ``pd`` (**tanto por uno**) y las cotas de inicio y de fin ``z_start`` y ``z_end`` (m).

    Es la media de la mayor minorante y la menor mayorante pd-Lipschitz del perfil, limitada a la banda de los extremos y con los extremos fijos: la
    pendiente de cada tramo es ≤ pd (a ≤ 10⁻⁹) y, donde el perfil no pasa de pd, igual al terreno. :class:`DropTooSteep` si ``|z_end − z_start| > pd·S``
    (``S`` = la última estación menos la primera: la longitud del eje). Los arrays no se modifican; el resultado es float64 nuevo y de solo lectura.
    ``TypeError`` o ``ValueError`` si una entrada no es de su forma o sale de su rango (errores del programa)."""
    s = _stations(stations_s)
    t = _vector(terrain, "el terreno bajo el eje", len(s))
    gradient = _real(pd, "la pendiente de diseño", positive=True)
    start = _real(z_start, "la cota de inicio")
    end = _real(z_end, "la cota de fin")
    rel = s - s[0]
    length = float(rel[-1])
    drop = abs(end - start)
    if drop > gradient * length + _DROP_TOLERANCE_M:
        raise DropTooSteep(length, end - start, gradient)
    rise = gradient * rel
    from_left = rise + np.minimum.accumulate(t - rise)
    from_right = np.minimum.accumulate((t + rise)[::-1])[::-1] - rise
    lower = np.minimum(from_left, from_right)  # la mayor minorante pd-Lipschitz del perfil
    above_left = np.maximum.accumulate(t + rise) - rise
    above_right = rise + np.maximum.accumulate((t - rise)[::-1])[::-1]
    upper = np.maximum(above_left, above_right)  # la menor mayorante
    left = gradient * (length - rel)
    line = np.clip(0.5 * (lower + upper), np.maximum(start - rise, end - left), np.minimum(start + rise, end + left))
    line[0], line[-1] = start, end
    return _frozen(line)


# --- La pendiente media y sus tramos -----------------------------------------------------------------------------------


def mean_gradient(s: Any, z: Any) -> float:
    """La pendiente media de una rasante (D-7; RF-017-17): ``Σ|Δcota| / S`` en **tanto por uno**, con ``S`` la longitud del eje (la última estación menos la
    primera): una subida de 6 m y una bajada de 2 m en 200 m son 8 / 200, no el desnivel entre los extremos. ``ValueError`` si las estaciones no crecen o
    ``z`` tiene otra longitud."""
    stations = _stations(s)
    levels = _vector(z, "la rasante", len(stations))
    return float(np.abs(np.diff(levels)).sum() / (stations[-1] - stations[0]))


@dataclass(frozen=True, slots=True)
class Stretch:
    """Un tramo de la rasante entre dos estaciones (RF-017-17, RF-017-18): la abscisa donde empieza (``station_m``, m desde el origen del eje), su longitud
    (``length_m``), su lugar (``x`` e ``y`` absolutos, float64: el punto del eje en esa abscisa) y su pendiente en valor absoluto (``gradient_pct``, %)."""

    station_m: float
    length_m: float
    x: float
    y: float
    gradient_pct: float

    def named(self) -> Named:
        """El tramo como elemento de la lista de un aviso (``des.road_stretch``: abscisa, lugar y pendiente), que se escribe en el idioma pedido."""
        return Named("des.road_stretch", {"station": self.station_m, "x": self.x, "y": self.y, "gradient": self.gradient_pct})


def _gradients(s: np.ndarray, z: np.ndarray) -> np.ndarray:
    """La pendiente en valor absoluto (tanto por uno) de cada tramo entre estaciones."""
    return np.abs(np.diff(z)) / np.diff(s)


def steepest_stretches(axis: Axis, z: Any, *, listed: int = LISTED_STRETCHES) -> tuple[Stretch, ...]:
    """Los ``listed`` tramos de mayor pendiente de la rasante ``z`` (una cota por estación de ``axis``): de mayor a menor pendiente y, a igual pendiente (a
    10⁻⁹), por abscisa; solo los que tienen pendiente (una rasante horizontal no da ninguno). Cada tramo es el intervalo entre dos estaciones (``w`` m) y su
    lugar, el del eje en su estación de comienzo. ``ValueError`` si ``z`` no tiene una cota por estación o ``listed`` no es un entero positivo."""
    if isinstance(listed, bool) or not isinstance(listed, int):
        raise TypeError(f"el número de tramos es un entero, no {listed!r}")
    if listed < 1:
        raise ValueError(f"el número de tramos es al menos 1, no {listed}")
    s = axis.stations
    levels = _vector(z, "la rasante", len(s))
    gradient = _gradients(s, levels)
    key = np.round(gradient, _TIE_DECIMALS)
    order = np.lexsort((np.arange(len(gradient)), -key))[:listed]
    order = order[key[order] > 0.0]
    return tuple(
        Stretch(station_m=float(s[i]), length_m=float(s[i + 1] - s[i]), x=float(axis.points[i, 0]), y=float(axis.points[i, 1]),
                gradient_pct=float(gradient[i] * 100.0))
        for i in order.tolist())


def mean_gradient_notice(axis: Axis, z: Any, profile: Any, entity: str, *, listed: int = LISTED_STRETCHES) -> Notice | None:
    """El aviso de la pendiente media (RF-017-17; ``des.road_mean_gradient``): ``None`` si la media de la rasante ``z`` (una cota por estación de ``axis``) no
    pasa de la pendiente media máxima del perfil (``profile.max_mean_gradient_pct``, a 10⁻⁹); si pasa, el aviso con la pista (``entity``), la media y el límite
    (%) y los ``listed`` tramos de mayor pendiente con su abscisa y su lugar (:func:`steepest_stretches`). El aviso va **antes de crear**: la pista no se
    crea sin la confirmación expresa del usuario y un motivo, que registra la operación en sus ajustes (T21), no este aviso."""
    levels = _vector(z, "la rasante", len(axis.stations))
    mean = mean_gradient(axis.stations, levels)
    limit = float(profile.max_mean_gradient_pct)
    if mean <= limit / 100.0 + _GRADIENT_TOLERANCE:
        return None
    stretches = tuple(stretch.named() for stretch in steepest_stretches(axis, levels, listed=listed))
    return Notice("des.road_mean_gradient", {"entity": entity, "mean": mean * 100.0, "limit": limit, "stretches": stretches})


# --- El modo «eje 3D» ---------------------------------------------------------------------------------------------------


def check_axis_3d(axis: Axis, z: Any, profile: Any, entity: str) -> tuple[Notice, ...]:
    """La comprobación del modo «eje 3D» (RF-017-18): la Z de la línea **es** la rasante (``z``: su cota en cada estación de ``axis``) y **no se corrige**;
    cada incumplimiento es un aviso con su abscisa y su lugar, en este orden: (1) cada **tramo entre estaciones** cada ``w`` m cuya pendiente pasa de pd
    (``profile.max_gradient_pct``, a 10⁻⁹; ``des.road_axis3d_gradient``), por abscisa; (2) la **media** si pasa de pm (``des.road_mean_gradient``, el de
    RF-017-17, con sus tramos más empinados); (3) cada **curva por debajo de Rmín** de la planta (``des.road_axis3d_radius``, de
    :attr:`~design.road_axis.Axis.below_minimum`: el eje se formó con ``reject_below_minimum=False``), por abscisa. Sin incumplimientos, ``()``.
    ``entity`` es el nombre de la pista; ``ValueError`` si ``z`` no tiene una cota por estación."""
    s = axis.stations
    levels = _vector(z, "la Z de la línea", len(s))
    limit = float(profile.max_gradient_pct)
    gradient = _gradients(s, levels)
    notices: list[Notice] = [
        Notice("des.road_axis3d_gradient", {"entity": entity, "station": float(s[i]), "gradient": float(gradient[i] * 100.0), "limit": limit,
                                            "x": float(axis.points[i, 0]), "y": float(axis.points[i, 1])})
        for i in np.flatnonzero(gradient > limit / 100.0 + _GRADIENT_TOLERANCE).tolist()]
    mean = mean_gradient_notice(axis, levels, profile, entity)
    if mean is not None:
        notices.append(mean)
    notices.extend(
        Notice("des.road_axis3d_radius", {"entity": entity, "station": curve.station_m, "radius": curve.radius_m, "minimum": axis.minimum_m,
                                          "x": curve.x, "y": curve.y})
        for curve in axis.below_minimum)
    return tuple(notices)
