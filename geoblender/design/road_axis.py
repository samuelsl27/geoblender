# SPDX-License-Identifier: GPL-3.0-or-later
"""El eje de una pista con curvas circulares y radio mínimo (spec 017, T10; HU-017-1 y HU-017-4; RF-017-13 y RF-017-14; CE-017-02; RNF-017-03;
plan 017 §5.4 A4 y §5.3.1).

Lo que da, todo en el dominio (Python y numpy, sin Blender), con las coordenadas absolutas en float64 (regla 4 de AGENTS.md) y el cálculo en el
**marco local de su primer vértice** (la diferencia de dos coordenadas absolutas cercanas es exacta; un norte de 4,4 Mm tiene un ulp de 0,93 nm):

- **El eje** (:func:`axis_of` → :class:`Axis`; A4): la ruta (los nodos de :mod:`design.road_route`) se simplifica con **Douglas–Peucker** a
  ``simplify_m`` (cada nodo que se quita queda a no más de la tolerancia de la poligonal que queda; los extremos se conservan) y, con el
  origen y el destino **exactos** (el punto de la capa, no el centro del nodo), cada vértice interior con cambio de dirección ``Δ`` (azimut desde
  el norte en sentido horario, normalizado a (−π, π]) se sustituye por un **arco de radio R tangente a sus dos tramos**, con la tangente
  ``T = R·tan(|Δ|/2)`` (el eje, continuo en tangente y sin vértices puntiagudos: B-PRONT4). Un vértice sin cambio de dirección no es una curva.
  La misma función forma el eje de una **línea dibujada** («sobre un eje»): sin simplificar (``simplify_m = 0``) y **sin modificarla** (se copia).
- **El radio que cabe** (RF-017-14): si las tangentes de un vértice no caben en los tramos que une —la suma de las de dos curvas contiguas pasa del
  tramo que las separa; en un tramo de extremo la tangente cabe como mucho entera—, el radio de esa curva baja al **mayor que cabe en una pasada**:
  ``f = mín(tramo / necesario)`` de sus dos tramos (con las tangentes de diseño), ``R' = R·f``; así las tangentes de cada tramo caben en él (cada
  vértice se reduce por el menor de los ``f`` de sus dos tramos, que es a lo sumo el de cada uno). Cada curva reducida es un aviso
  (:meth:`Axis.notices`: ``des.road_radius_reduced``, con el vértice, el radio y su lugar). Si el que cabe es **menor que Rmín**, **rechazo**
  (:class:`RadiusBelowMinimum`, que se convierte con :meth:`~RadiusBelowMinimum.error` en ``des.road_radius_below_min`` con el vértice, los tramos y
  el radio que cabría): **no baja de Rmín por su cuenta**. En el modo **«eje 3D»** (RF-017-18; decisión de la sesión principal tras la T10) la línea es
  una entrada que no se corrige y un radio menor que Rmín es un **aviso**, no un rechazo: con ``reject_below_minimum=False`` el eje se devuelve como
  viene y :attr:`Axis.below_minimum` lista las curvas por debajo de Rmín (``road_gradient.check_axis_3d`` las avisa); «trazar» y «sobre un eje»
  siguen rechazando.
- **El muestreo** (:meth:`Axis.sample`, :func:`stations_for`): cada ``w`` m y con una última estación en el extremo (RF-017-15), con
  ``searchsorted`` sobre el comienzo de cada pieza (rectas y arcos) y fórmulas vectorizadas: **sin bucle por estación** (RNF-017-03). Da el punto y
  el azimut de cada abscisa; el primero y el último punto son **exactamente** el origen y el destino.
- **Las cifras** (RF-017-13): la longitud (``length_m``), el número de curvas (``curve_count``), el radio mínimo real (``min_radius_m``; ``None`` sin
  curvas) y la **desviación máxima** (``deviation_m``, m) frente a la ruta o la línea: la suma de la desviación de los arcos (``curve_deviation_m``,
  analítica: ``R·(1/cos(|Δ|/2) − 1)`` del vértice al arco, la mayor) y la de la simplificación (``simplification_m``: lo que se separa de la ruta
  el nodo quitado más lejano, y lo que se movieron los nodos extremos al poner el origen y el destino exactos). Es una **cota** de la distancia
  entre el eje y la ruta, y **exacta** para una línea dibujada o con ``simplify_m = 0`` (la de los arcos, a ≤ 10⁻⁹ m del cálculo analítico).

La rasante (``design.road_gradient``, T11), la sección (T12) y el grabado (T13) usan este eje: ``Axis.points`` y ``Axis.stations`` (cada ``w`` m) y, a
otro paso (la huella, cada 1 m), :meth:`Axis.sample`.

**Perezoso** (RNF-001-03): ni ``design.model`` ni nada del arranque lo importan; lo pide quien traza una pista.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .messages import DesignError
from .preview import Notice

__all__ = [
    "Axis",
    "Curve",
    "RadiusBelowMinimum",
    "axis_of",
    "stations_for",
]

_STRAIGHT_RAD = 1e-9
"""El cambio de dirección (rad) por debajo del cual un vértice es recto: no es una curva (un arco de 10⁻⁹ rad en un radio de 20 m son 2·10⁻⁸ m)."""
_REPEAT_M = 1e-6
"""La distancia (m) por debajo de la cual un punto repite al anterior: no es un tramo (no tiene dirección)."""
_FIT_REL_TOL = 1e-12
"""Lo que las tangentes pueden pasar del tramo (relativo) sin que el radio baje: el ruido de la última cifra no es un aviso (3·10⁻¹¹ m en 30 m)."""
_MINIMUM_TOL_M = 1e-9
"""El margen (m) con que el radio que cabe se compara con Rmín: un radio de 12,000000000000004 m no es menor que 12 m."""
_STATION_TOL_M = 1e-9
"""La distancia (m) por debajo de la cual la última estación es la del extremo (no se repite)."""


# --- Las entradas -------------------------------------------------------------------------------------------------------


def _number(value: object, what: str, *, zero: bool = False) -> float:
    """``value`` como un número real finito y positivo (con ``zero``, no negativo): ``TypeError`` si no es un número real, ``ValueError`` si no es
    finito o no es positivo (errores del programa: la preparación de la pista rechazó antes, con su capa, su pista y su valor, RF-017-04)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or (number == 0.0 and not zero):
        raise ValueError(f"{what} es un número finito {'no negativo' if zero else 'positivo'}, no {value!r}")
    return number


def _points(points: object) -> np.ndarray:
    """Una **copia** float64 ``(k, 2)`` de los puntos (``x`` e ``y``: la Z de una línea de «eje 3D» no entra), finitos y al menos dos: ``ValueError``
    si no."""
    try:
        array = np.array(points, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"los puntos del eje no son un array de números (x, y): {error}") from error
    if array.ndim != 2 or array.shape[1] < 2 or array.shape[0] < 2:
        raise ValueError(f"los puntos del eje son al menos dos, cada uno con x e y: forma {array.shape}")
    if not bool(np.isfinite(array[:, :2]).all()):
        raise ValueError("los puntos del eje son finitos")
    return np.array(array[:, :2])


def _point(value: object, what: str) -> np.ndarray:
    """Un punto ``(x, y)`` finito como array float64: ``ValueError`` si no."""
    try:
        array = np.array(value, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{what} no es un punto (x, y): {error}") from error
    if array.shape != (2,) or not bool(np.isfinite(array).all()):
        raise ValueError(f"{what} es un punto (x, y) finito, no {value!r}")
    return array


def _frozen(array: np.ndarray) -> np.ndarray:
    """``array`` (propio de quien lo crea) de solo lectura."""
    array.flags.writeable = False
    return array


def _shown(value: float) -> float:
    """Una cifra de un rechazo como la lee una persona: a milésimas de metro."""
    return round(float(value), 3)


def _wrap(angle: np.ndarray) -> np.ndarray:
    """``angle`` (rad) en (−π, π]."""
    wrapped = (angle + math.pi) % (2.0 * math.pi) - math.pi
    return np.where(wrapped == -math.pi, math.pi, wrapped)


# --- Douglas–Peucker ---------------------------------------------------------------------------------------------------


def _segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La distancia (m) de cada punto de ``points`` al **segmento** ``ab`` (no a su recta: lo que se quita queda de verdad a la tolerancia de lo que
    queda)."""
    ab = b - a
    length2 = float(ab @ ab)
    relative = points - a
    if length2 == 0.0:
        return np.hypot(relative[:, 0], relative[:, 1])
    t = np.clip((relative @ ab) / length2, 0.0, 1.0)
    return np.hypot(relative[:, 0] - t * ab[0], relative[:, 1] - t * ab[1])


def _simplify(points: np.ndarray, tolerance: float) -> tuple[np.ndarray, float]:
    """Douglas–Peucker: los índices de los puntos que se conservan (los extremos siempre) y la mayor distancia (m) de un punto quitado a la poligonal
    que queda (≤ ``tolerance``). Iterativo y determinista (el primero de los más lejanos); la distancia de todo un rango, vectorizada."""
    count = len(points)
    keep = np.zeros(count, dtype=bool)
    keep[0] = keep[-1] = True
    deviation = 0.0
    pending = [(0, count - 1)]
    while pending:
        low, high = pending.pop()
        if high - low < 2:
            continue
        distance = _segment_distance(points[low + 1:high], points[low], points[high])
        farthest = int(np.argmax(distance))
        if float(distance[farthest]) > tolerance:
            middle = low + 1 + farthest
            keep[middle] = True
            pending.append((middle, high))
            pending.append((low, middle))
        else:
            deviation = max(deviation, float(distance[farthest]))
    return np.flatnonzero(keep), deviation


# --- El resultado ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Curve:
    """Una curva circular del eje (RF-017-13, RF-017-14): el ``vertex`` (el número, desde 1, del vértice de la ruta o de la línea que sustituye) y su
    lugar (``x`` e ``y``, absolutos, float64), el radio que se usó (``radius_m``) y el de diseño que se pidió (``design_radius_m``), el cambio de
    dirección (``deflection``, rad, con signo: **positivo en sentido horario**, a la derecha), la tangente (``tangent_m``), el largo del arco
    (``length_m``), la abscisa donde empieza (``station_m``, m desde el origen) y la longitud de los dos tramos que une (``before_m`` y ``after_m``, de la
    poligonal simplificada)."""

    vertex: int
    x: float
    y: float
    radius_m: float
    design_radius_m: float
    deflection: float
    tangent_m: float
    length_m: float
    station_m: float
    before_m: float
    after_m: float

    @property
    def reduced(self) -> bool:
        """Si el radio bajó del de diseño porque las tangentes no cabían (RF-017-14)."""
        return self.radius_m < self.design_radius_m


class RadiusBelowMinimum(Exception):
    """El rechazo de RF-017-14: en algún vértice solo cabría un radio menor que Rmín y **no se baja de Rmín por su cuenta**. Lleva todos los vértices
    en ese caso (``offenders``, en el orden del eje; cada uno una :class:`Curve` con el radio que cabría y los tramos que une), el de menor radio
    (``curve``) y Rmín (``minimum_m``). :meth:`error` lo convierte en el rechazo del catálogo (``des.road_radius_below_min``) con la capa, la pista y
    el perfil."""

    def __init__(self, offenders: Sequence[Curve], minimum_m: float) -> None:
        self.offenders: tuple[Curve, ...] = tuple(offenders)
        self.minimum_m = float(minimum_m)
        self.curve: Curve = min(self.offenders, key=lambda curve: curve.radius_m)
        super().__init__(
            f"en el vértice {self.curve.vertex} (x = {self.curve.x} m, y = {self.curve.y} m) solo cabría un radio de {self.curve.radius_m} m, "
            f"menor que el radio mínimo ({self.minimum_m} m)")

    def error(self, *, layer: str, entity: str, profile: Any) -> DesignError:
        """El rechazo de la persona (``des.road_radius_below_min``, RF-017-14) con la capa, la pista (``entity``) y el perfil (un
        :class:`~design.road_profiles.RoadProfile`: su nombre y la clave de su radio mínimo), el vértice, su lugar, los dos tramos, el radio que cabría y
        el mínimo; qué hacer (mover el vértice, simplificar más o menos, otro perfil) lo dice el texto del catálogo."""
        from .params import RoadProfileParam, road_profile_key  # solo al rechazar: los módulos de la pista son perezosos

        curve = self.curve
        return DesignError(
            "des.road_radius_below_min", obj=f"Pista «{entity}» de la capa «{layer}»",
            field=road_profile_key(profile.code, RoadProfileParam.MIN_RADIUS), value=self.minimum_m, layer=layer, entity=entity,
            vertex=curve.vertex, x=_shown(curve.x), y=_shown(curve.y), length_before=_shown(curve.before_m), length_after=_shown(curve.after_m),
            fitted=_shown(curve.radius_m), minimum=_shown(self.minimum_m), profile=profile.name)


@dataclass(frozen=True, slots=True, eq=False)
class _Pieces:
    """Las piezas del eje en su orden (rectas y arcos), en el marco local del primer vértice: la abscisa donde empieza cada una (``start``, no
    decreciente: una recta de longitud 0 es una pieza más), si es un arco, su referencia (el comienzo de la recta o el centro del arco), el azimut al
    comenzar, el radio (0 en una recta) y el signo del giro (+1 horario, −1 antihorario, 0 en una recta)."""

    start: np.ndarray
    is_arc: np.ndarray
    ref: np.ndarray
    azimuth0: np.ndarray
    radius: np.ndarray
    sign: np.ndarray


def stations_for(length_m: float, step_m: float) -> np.ndarray:
    """Las estaciones de un eje de ``length_m`` m cada ``step_m`` m, con una última en su extremo (RF-017-15): ``0, w, 2w, …`` y la longitud (sin
    repetirla si es un múltiplo de ``w``). Una vista de solo lectura sobre un array nuevo."""
    length = _number(length_m, "la longitud del eje", zero=True)
    step = _number(step_m, "el paso de las estaciones")
    count = int(math.floor(length / step + 1e-9))
    stations = np.arange(count + 1, dtype=np.float64) * step
    if length - stations[-1] > _STATION_TOL_M:
        stations = np.append(stations, length)
    else:
        stations[-1] = length
    return _frozen(stations)


def _evaluate(pieces: _Pieces, offset: np.ndarray, first: np.ndarray, last: np.ndarray, length: float, stations: np.ndarray
              ) -> tuple[np.ndarray, np.ndarray]:
    """El punto (absoluto) y el azimut (rad, en (−π, π]) del eje en cada abscisa de ``stations`` (ya acotada a ``[0, length]``): la pieza de cada una
    con ``searchsorted`` y las fórmulas de la recta y del arco, vectorizadas. El primer punto y el último son exactamente ``first`` y ``last``."""
    count = len(pieces.start)
    index = np.clip(np.searchsorted(pieces.start, stations, side="right") - 1, 0, count - 1)
    along = stations - pieces.start[index]
    points = np.empty((len(stations), 2))
    azimuth = np.empty(len(stations))
    arc = pieces.is_arc[index]
    line = ~arc
    where = index[line]
    heading = pieces.azimuth0[where]
    points[line, 0] = pieces.ref[where, 0] + along[line] * np.sin(heading)
    points[line, 1] = pieces.ref[where, 1] + along[line] * np.cos(heading)
    azimuth[line] = heading
    where = index[arc]
    radius, sign = pieces.radius[where], pieces.sign[where]
    turn = sign * along[arc] / radius
    # el vector del centro al punto va a 90° del rumbo, del lado del centro, y gira con el rumbo
    angle = pieces.azimuth0[where] - sign * (math.pi / 2.0) + turn
    points[arc, 0] = pieces.ref[where, 0] + radius * np.sin(angle)
    points[arc, 1] = pieces.ref[where, 1] + radius * np.cos(angle)
    azimuth[arc] = pieces.azimuth0[where] + turn
    points += offset
    points[stations <= 0.0] = first
    points[stations >= length] = last
    return points, _wrap(azimuth)


@dataclass(frozen=True, slots=True, eq=False)
class Axis:
    """El eje de una pista (RF-017-13): rectas y arcos tangentes entre sí. ``vertices`` son los vértices de la poligonal simplificada sobre la que
    se forman las curvas (absolutos, float64: nodos de la ruta, con el origen y el destino exactos si se pidieron) y ``kept``, su índice en los puntos
    de entrada; ``curves``, las curvas en su orden; ``length_m``, la longitud; ``step_m``, el paso ``w``; ``stations`` (``(n,)``, m), los puntos
    (``points``, ``(n, 2)``, absolutos float64) y el azimut (``azimuth``, rad desde el norte en sentido horario, en (−π, π]) del eje cada ``w`` m y en
    su extremo; y las desviaciones (``curve_deviation_m`` y ``simplification_m``). Los arrays son de solo lectura.

    :attr:`curve_count`, :attr:`min_radius_m` y :attr:`deviation_m` son las cifras de RF-017-13; :meth:`sample` evalúa el eje en otras abscisas
    (la huella de la sección, cada 1 m); :meth:`notices`, los avisos de RF-017-14. ``minimum_m`` es el radio mínimo Rmín con que se formó y
    :attr:`below_minimum`, las curvas por debajo de él (solo en el modo «eje 3D», que no rechaza: RF-017-18)."""

    vertices: np.ndarray
    kept: np.ndarray
    curves: tuple[Curve, ...]
    length_m: float
    step_m: float
    stations: np.ndarray
    points: np.ndarray
    azimuth: np.ndarray
    curve_deviation_m: float
    simplification_m: float
    minimum_m: float
    _pieces: _Pieces

    @property
    def curve_count(self) -> int:
        """El número de curvas (los vértices con cambio de dirección)."""
        return len(self.curves)

    @property
    def min_radius_m(self) -> float | None:
        """El radio mínimo real (m): el menor de los radios usados; ``None`` si el eje no tiene curvas."""
        return min((curve.radius_m for curve in self.curves), default=None)

    @property
    def deviation_m(self) -> float:
        """La desviación máxima (m) frente a la ruta o la línea: la de los arcos más la de la simplificación (una cota; exacta sin simplificar)."""
        return self.curve_deviation_m + self.simplification_m

    @property
    def below_minimum(self) -> tuple[Curve, ...]:
        """Las curvas por debajo del radio mínimo (``radius_m`` < ``minimum_m``, con el mismo margen que el rechazo), en el orden del eje: siempre
        vacía en un eje formado con el rechazo (el de «trazar» y «sobre un eje»: o cumple o no existe) y, en el modo «eje 3D»
        (``reject_below_minimum=False``), lo que ``road_gradient.check_axis_3d`` avisa (RF-017-18)."""
        return tuple(curve for curve in self.curves if curve.radius_m < self.minimum_m - _MINIMUM_TOL_M)

    def sample(self, stations: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """El punto ``(n, 2)`` (absoluto, float64) y el azimut ``(n,)`` (rad) del eje en las abscisas ``stations`` (``(n,)``, m desde el origen; las que
        quedan fuera del eje, en el extremo más próximo): sin bucle por estación. ``ValueError`` si no es un vector de números finitos."""
        s = np.array(stations, dtype=np.float64)
        if s.ndim != 1 or not bool(np.isfinite(s).all()):
            raise ValueError("las abscisas del eje son un vector de números finitos")
        s = np.clip(s, 0.0, self.length_m)
        return _evaluate(self._pieces, self.vertices[0], self.vertices[0], self.vertices[-1], self.length_m, s)

    def notices(self, entity: str) -> tuple[Notice, ...]:
        """Los avisos de RF-017-14, en el orden del eje: uno (``des.road_radius_reduced``) por curva cuyo radio bajó del de diseño, con la pista
        (``entity``), el vértice, el radio pedido y el que cabe y su lugar. Las curvas por debajo de Rmín del modo «eje 3D» (:attr:`below_minimum`) no
        están: las dice el aviso del radio de ese modo (``des.road_axis3d_radius``), que no se repite como «el radio baja»."""
        narrow = {curve.vertex for curve in self.below_minimum}
        return tuple(
            Notice("des.road_radius_reduced", {"entity": entity, "vertex": curve.vertex, "radius": curve.design_radius_m, "fitted": curve.radius_m,
                                               "x": curve.x, "y": curve.y})
            for curve in self.curves if curve.reduced and curve.vertex not in narrow)


# --- El eje ------------------------------------------------------------------------------------------------------------


def _distinct(points: np.ndarray) -> np.ndarray:
    """Los índices de los puntos que no repiten al anterior (a ``_REPEAT_M``); si el último repite, se queda **él** (el destino exacto) y se quita el
    anterior. ``ValueError`` si quedan menos de dos."""
    step = np.hypot(*np.diff(points, axis=0).T)
    distinct = np.ones(len(points), dtype=bool)
    distinct[1:] = step > _REPEAT_M
    if not distinct[-1]:
        previous = np.flatnonzero(distinct)[-1]
        if previous > 0:
            distinct[previous] = False
            distinct[-1] = True
    index = np.flatnonzero(distinct)
    if len(index) < 2:
        raise ValueError("el eje necesita al menos dos puntos distintos (no todos son el mismo)")
    return index


def axis_of(points: Any, radius_m: float, rmin_m: float, step_m: float, *, simplify_m: float = 0.0,
            origin: Any = None, destination: Any = None, reject_below_minimum: bool = True) -> Axis:
    """El eje con curvas de una ruta o de una línea dibujada (A4; RF-017-13, RF-017-14): ``points`` (``(k, 2)`` o ``(k, 3)``; los nodos de la ruta,
    absolutos, o los vértices de la línea, que **no se modifica**), el radio de curva ``R`` (``radius_m``), el mínimo ``Rmín`` (``rmin_m``) y el paso
    de las estaciones ``w`` (``step_m``), todos en metros. ``simplify_m`` (0, sin simplificar: la línea dibujada) es la tolerancia de Douglas–Peucker
    de la ruta; ``origin`` y ``destination`` (``(x, y)``), el punto de la capa que sustituye al nodo extremo para que el eje empiece y acabe
    **exactamente** en ellos.

    Si las tangentes de una curva no caben, su radio baja al que cabe (:meth:`Axis.notices`); si el que cabe es menor que Rmín,
    :class:`RadiusBelowMinimum` (que no baja de Rmín por su cuenta). Con ``reject_below_minimum=False`` (el modo «eje 3D», RF-017-18: la línea es
    una entrada que no se corrige y el radio es un **aviso**) no se rechaza: el eje se devuelve como viene y :attr:`Axis.below_minimum` lista las
    curvas por debajo de Rmín. :class:`TypeError` o :class:`ValueError` si una entrada no es de su forma o sale de su rango (errores del
    programa: la preparación de la pista rechazó antes, con su capa, su pista y su valor)."""
    radius = _number(radius_m, "el radio de curva")
    minimum = _number(rmin_m, "el radio mínimo de curva")
    step = _number(step_m, "el paso de las estaciones")
    tolerance = _number(simplify_m, "la tolerancia de simplificación", zero=True)
    if not isinstance(reject_below_minimum, bool):
        raise TypeError(f"reject_below_minimum es un booleano, no {reject_below_minimum!r}")
    if minimum > radius:
        raise ValueError(f"el radio mínimo ({minimum} m) no puede ser mayor que el radio de curva ({radius} m)")
    given = _points(points)
    work, shift = given.copy(), 0.0
    if origin is not None:
        work[0] = _point(origin, "el origen del eje")
        shift = max(shift, float(np.hypot(*(work[0] - given[0]))))
    if destination is not None:
        work[-1] = _point(destination, "el destino del eje")
        shift = max(shift, float(np.hypot(*(work[-1] - given[-1]))))
    source = _distinct(work)
    work = work[source]
    local = work - work[0]
    if tolerance > 0.0 and len(work) > 2:
        kept, dropped = _simplify(local, tolerance)
    else:
        kept, dropped = np.arange(len(work)), 0.0
    vertices, loc = work[kept], local[kept]
    curves, pieces, length, curve_deviation = _form(loc, vertices, source[kept], radius)
    offenders = tuple(curve for curve in curves if curve.radius_m < minimum - _MINIMUM_TOL_M)
    if offenders and reject_below_minimum:
        raise RadiusBelowMinimum(offenders, minimum)
    stations = stations_for(length, step)
    points_at, azimuth = _evaluate(pieces, vertices[0], vertices[0], vertices[-1], length, stations)
    return Axis(
        vertices=_frozen(np.array(vertices)), kept=_frozen(np.array(source[kept])), curves=curves, length_m=length, step_m=step,
        stations=stations, points=_frozen(points_at), azimuth=_frozen(azimuth), curve_deviation_m=curve_deviation,
        simplification_m=max(dropped, shift), minimum_m=minimum, _pieces=pieces)


def _form(loc: np.ndarray, vertices: np.ndarray, numbers_: np.ndarray, radius: float) -> tuple[tuple[Curve, ...], _Pieces, float, float]:
    """Las curvas, las piezas, la longitud y la desviación de los arcos de la poligonal ``loc`` (local) de ``vertices`` (absolutos), cuyos puntos de
    la ruta son ``numbers_`` (el vértice ``k`` es el ``numbers_[k] + 1``): los radios que caben (RF-017-14: una pasada), los puntos de tangencia, los
    centros y el orden rectas–arcos."""
    count = len(loc)
    chords = np.diff(loc, axis=0)
    legs = np.hypot(chords[:, 0], chords[:, 1])
    unit = chords / legs[:, None]
    azimuth = np.arctan2(chords[:, 0], chords[:, 1])
    delta = _wrap(azimuth[1:] - azimuth[:-1])  # el cambio de dirección de cada vértice interior (+: a la derecha)
    curved = np.abs(delta) > _STRAIGHT_RAD
    unit_tangent = np.zeros(count)
    unit_tangent[1:-1] = np.where(curved, np.tan(np.abs(delta) / 2.0), 0.0)
    needed = radius * (unit_tangent[:-1] + unit_tangent[1:])  # lo que piden las tangentes de diseño en cada tramo
    over = needed > legs * (1.0 + _FIT_REL_TOL)
    factor = np.ones(count - 1)
    factor[over] = legs[over] / needed[over]
    scale = np.ones(count)
    scale[1:-1] = np.minimum(factor[:-1], factor[1:])  # el menor de los dos tramos del vértice: una pasada
    used = radius * scale
    tangent = used * unit_tangent
    vertex = np.flatnonzero(curved) + 1
    straight_length = np.maximum(legs - tangent[:-1] - tangent[1:], 0.0)
    straight_start = loc[:-1] + unit * tangent[:-1, None]
    previous = unit[vertex - 1]
    arc_start = loc[vertex] - previous * tangent[vertex, None]
    sign = np.sign(delta[vertex - 1])
    right = np.column_stack([previous[:, 1], -previous[:, 0]])  # la normal a la derecha del sentido de la marcha
    centre = arc_start + (sign * used[vertex])[:, None] * right
    arc_length = used[vertex] * np.abs(delta[vertex - 1])
    lines = len(legs)
    # rectas (clave 2j) y arcos (clave 2i − 1 en el vértice i): recta, arco, recta, arco…
    order = np.argsort(np.concatenate([2 * np.arange(lines), 2 * vertex - 1]), kind="stable")
    lengths = np.concatenate([straight_length, arc_length])[order]
    start = np.concatenate([[0.0], np.cumsum(lengths)[:-1]])
    pieces = _Pieces(
        start=_frozen(start), is_arc=_frozen(np.concatenate([np.zeros(lines, dtype=bool), np.ones(len(vertex), dtype=bool)])[order]),
        ref=_frozen(np.concatenate([straight_start, centre])[order]), azimuth0=_frozen(np.concatenate([azimuth, azimuth[vertex - 1]])[order]),
        radius=_frozen(np.concatenate([np.zeros(lines), used[vertex]])[order]), sign=_frozen(np.concatenate([np.zeros(lines), sign])[order]))
    position = np.empty(len(order), dtype=np.intp)
    position[order] = np.arange(len(order))
    curves = tuple(
        Curve(vertex=int(numbers_[at]) + 1, x=float(vertices[at, 0]), y=float(vertices[at, 1]), radius_m=float(used[at]), design_radius_m=radius,
              deflection=float(delta[at - 1]), tangent_m=float(tangent[at]), length_m=float(arc_length[k]),
              station_m=float(start[position[lines + k]]), before_m=float(legs[at - 1]), after_m=float(legs[at]))
        for k, at in enumerate(vertex.tolist()))
    deviation = float((tangent[vertex] * np.tan(np.abs(delta[vertex - 1]) / 4.0)).max(initial=0.0))
    return curves, pieces, math.fsum(lengths.tolist()), deviation
