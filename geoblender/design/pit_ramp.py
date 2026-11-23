# SPDX-License-Identifier: GPL-3.0-or-later
"""La rampa de la corta, en espiral (T15) y en zig-zag (T16) (spec 018; HU-018-3; RF-018-16, 17, 25; CE-018-05 y 06; plan 018 §5.4 A8 y A9, §5.7 P-15, §5.9).

**La construcción** (DIFF-018-2 y DIFF-018b, spec 0.4; el oráculo a mano es ``tests/support/pit_ramp_hand.py``):

- La rampa del banco ``k`` sube **pegada al pie** de ese banco, en la cara: su eje es el pie desplazado ``W/2`` hacia la cara (fuera
  del pie, tanto en la ascendente como en la descendente; ``W`` es la anchura de la sección del perfil de pista) y su banda mide ``W``.
- ``s`` se mide **por banco**, a lo largo del eje, en el sentido pedido (``cw`` o ``ccw``) desde el punto de inicio (el punto del pie más
  cercano al pedido y, a igual distancia, el primero en sentido horario desde el norte: P-15, RF-018-25). El tramo sube ``rise`` (la
  altura del banco) con la pendiente ``g`` en ``R = rise/g`` m de eje, y la cota del eje es ``z_k + g·s`` (``s`` de 0 a ``R``): la
  pendiente es exactamente ``g`` en cada trozo, porque la cota se calcula sobre la propia longitud del eje.
- **La transición** ``L_t`` (decidida por defecto, G-2; revisable): el tramo mide ``L_k = R + L_t`` y, tras ``R``, lleva ``L_t`` m
  planos a ``z_{k+1}``; la cresta del banco vuelve linealmente de la distancia de la rampa a la base en esa cola y entra linealmente en
  la rampa en los ``L_t`` m anteriores al inicio (el plan dice «a cada lado»). Con ``L_t = 0`` no hay transición (CE-018-05).
- **El término de distancia por arista** (:func:`edge_extra_m`): la cresta del banco ``k`` se retranquea ``W + (z_{k+1} − z(s))/tan α``
  (la pared sobre la rampa mide ``rise − g·s``, de ``rise`` a 0), que es la distancia base ``rise/tan α`` más un término que
  ``design.pit_offset.edge_distances`` suma por arista (``extra_m``): ``W − g·s/tan α`` en la rampa.
- **El enlace** (:func:`chain_start`): el tramo ``k + 1`` empieza en el punto del pie ``k + 1`` más cercano al fin del tramo ``k``, y el eje
  los une con un **enlace horizontal recto** a ``z_{k+1}`` que cuenta en la longitud del eje y no en la de rampa (con la corta circular de
  CE-018-05, ``W + B``).
- Una rampa que cruza el punto de inicio sigue sin envolver (G-3); solo se rechaza si ``L_k`` supera el perímetro del eje del banco
  (:class:`RampDoesNotFit`; los diagnósticos de RF-018-20 son de T17).

**El zig-zag** (T16, RF-018-17, CE-018-06; :func:`build_zigzag`, :func:`zigzag_steps`): cada banco sube por un **lado recto** de su pie
(el eje, desplazado ``W/2`` hacia fuera), un tramo recto de ``h/g`` m; el del banco 0 es el lado más largo que contiene el punto de
inicio y arranca en su extremo (decisión por defecto, revisable: el punto elige el lado, no la posición en él) en el sentido pedido
(``ccw``: el del anillo; ``cw``: el contrario). La **plataforma de retorno** es horizontal, a ``z_{k+1}``, y hace de enlace (cuenta en el
eje y no en la rampa): una recta de ``P − d`` m (``d`` = lo que separa el eje del lado de ``k`` del eje del de ``k + 1``, la anchura
más la berma) y el paso lateral de ``d`` m, de ``P = max(min_platform, π·Rgiro)`` m de eje (G-5); sus vértices los redondea después la
regla de la 017 (``axis_of``, T17). El tramo ``k + 1`` vuelve en sentido contrario. «Cabe» si ``h/g + P`` ≤ lado recto
(:class:`ZigzagDoesNotFit`, RF-018-20). El término de la cresta es el de la espiral (:func:`zigzag_edge_extra_m`); sin transición.

**Las reglas de la 017 y los diagnósticos** (T17; :func:`check_ramp`, RF-018-18 a 21; P-11: **se llaman, no se repiten**): el eje de la rampa pasa por
``road_axis.axis_of`` (``R``, ``Rmín`` y ``w`` del perfil de pista; si las tangentes no caben el radio baja y es un aviso; por debajo de ``Rmín``,
rechazo con el banco y el lugar) y por ``road_gradient.check_axis_3d`` (un aviso por incumplimiento con su banco, su abscisa y su lugar; el eje no
se corrige). La Z de cada estación es la del eje de la construcción en su abscisa (``Axis.line_abscissa``, como el modo «eje 3D» de la 017). La
media por encima de pm pide la confirmación con su motivo (:func:`confirm_mean`, ``provenance.RampConfirmation``). Si no cabe (RF-018-20) no se
registra nada y se dice por qué (:func:`no_fit_error`; zona sin rampa o intocable sobre el eje, a ≤ medio paso de rejilla). La banda
(:class:`Band`, RF-018-21) es el eje y sus bordes a ``W/2`` a la cota del eje. **Encima no se aplica una pista «eje 3D» de la 017** (D-3): este
módulo no importa el grabado ni la sección de la pista; :attr:`RampChecked.line` es una línea comprobable con ella (P2).

Las funciones por banco (:func:`build_tramo`, :func:`edge_extra_m`, :func:`chain_start`) trabajan en **el marco de coordenadas que se les
dé** (locales o absolutas, el mismo para el anillo, el punto y el tramo) con anillos antihorarios y abiertos, como el desfase de la corta;
:func:`spiral_steps` encadena los bancos de unos :class:`~design.pit_bench.Benches` ya calculados. Python puro con numpy (nivel 8); no lo
importa el arranque.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.project.model import Progress
from ..gis.masks.compile import STEP_BUDGET_S
from .messages import DesignError
from .params import PitRampParam, RoadProfileParam, pitramp_key, road_profile_key
from .pit_model import PitJob, Polyline, PolylineKind, RampDef, RampPath
from .preview import Notice
from .provenance import RampConfirmation
from .road_axis import Axis, RadiusBelowMinimum, axis_of, stations_for
from .road_gradient import check_axis_3d, mean_gradient
from .road_profiles import derived as road_derived
from .seeds import pace_progress
from .zones import polygons_cells

__all__ = [
    "Band",
    "RampChecked",
    "RampDoesNotFit",
    "Spiral",
    "check_ramp",
    "confirm_mean",
    "no_fit_error",
    "Tramo",
    "Zigzag",
    "ZigzagDoesNotFit",
    "ZigzagStepper",
    "foot_breaks",
    "split_ring",
    "spiral_of",
    "zigzag_foot_breaks",
    "zigzag_of",
    "build_tramo",
    "build_zigzag",
    "platform_length_m",
    "zigzag_edge_extra_m",
    "zigzag_steps",
    "chain_start",
    "crest_distance_m",
    "edge_extra_m",
    "nearest_on_ring",
    "spiral_steps",
    "wall_height_m",
]

_PHASE = "pit_ramp"
_TIE_M = 1e-9
"""A menos de esto (m) de la mínima, dos distancias al pie son la misma (el desempate de RF-018-25)."""
_NORTH_WRAP_DEG = 1e-7
"""Un azimut a menos de esto de 360° es el norte."""
_MITER_FLOOR = 0.25
"""Cota inferior de ``1 + n₁·n₂`` en el vértice del eje (limita el inglete en los giros agudos)."""
_LEVEL_TOL_M = 1e-6
"""Lo que el pie de un banco puede apartarse de la cresta del anterior (m)."""


class RampDoesNotFit(ValueError):
    """El tramo del banco ``bench`` mide ``needed_m`` y el perímetro del eje solo ``available_m`` (G-3, RF-018-20): :func:`no_fit_error` lo
    convierte en el rechazo de la persona. ``place`` es el lugar ``(x, y)`` (en el marco del anillo con que se calculó; las
    ``*_steps`` lo dan absoluto) y ``reason`` lo que impide."""

    reason = "el perímetro del eje del banco"

    def __init__(self, bench: int, needed_m: float, available_m: float, place: Sequence[float] | None = None) -> None:
        super().__init__(f"la rampa del banco {bench} necesita {needed_m:.3f} m y el perímetro del eje solo mide {available_m:.3f} m")
        self.bench = bench
        self.needed_m = needed_m
        self.available_m = available_m
        self.place: tuple[float, float] | None = None if place is None else (float(place[0]), float(place[1]))


@dataclass(frozen=True, slots=True, eq=False)
class Tramo:
    """El tramo de rampa de un banco (RF-018-16): su ``bench``, el punto del pie donde empieza (``foot_start``, ``(2,)``), el ``sense``
    (``cw`` o ``ccw``), la cota del pie (``z_foot_m``), lo que sube (``rise_m``), la pendiente (``gradient``, fracción), la anchura de la
    banda (``width_m``) y la transición (``transition_m``), la abscisa de inicio sobre el pie (``abscissa_m``: ``s_k``, en el sentido
    pedido desde el vértice 0), lo que mide la rampa (``ramp_m`` = ``rise/g``) y el tramo (``length_m`` = ``ramp_m + transition_m``) y el
    ``axis`` ``(k, 3)``: sus estaciones, del inicio al fin, con su Z (el marco del anillo con que se construyó)."""

    bench: int
    foot_start: np.ndarray
    sense: str
    z_foot_m: float
    rise_m: float
    gradient: float
    width_m: float
    transition_m: float
    abscissa_m: float
    ramp_m: float
    length_m: float
    axis: np.ndarray

    @property
    def start_xy(self) -> np.ndarray:
        """El inicio del eje (``(2,)``)."""
        return self.axis[0, :2]

    @property
    def end_xy(self) -> np.ndarray:
        """El fin del eje (``(2,)``), a la cota del banco siguiente."""
        return self.axis[-1, :2]


@dataclass(frozen=True, slots=True, eq=False)
class Spiral:
    """La rampa en espiral de una corta (:func:`spiral_steps`): su ``path`` (el eje entero con los enlaces y el semiancho ``W/2``), los
    ``tramos`` por banco, los metros de ``ramp_m`` (suma de los tramos), de ``links_m`` (enlaces horizontales) y de eje (``axis_m``)."""

    path: RampPath
    tramos: tuple[Tramo, ...]
    ramp_m: float
    links_m: float

    @property
    def axis_m(self) -> float:
        """La longitud del eje en planta (m): la rampa más los enlaces."""
        return self.ramp_m + self.links_m


# --- La geometría de un anillo ------------------------------------------------------------------------------------------------


def _area2(points: np.ndarray) -> float:
    """El doble del área con signo del anillo (positivo: antihorario)."""
    following = np.roll(points, -1, axis=0)
    return float((points[:, 0] * following[:, 1] - following[:, 0] * points[:, 1]).sum())


def _ring(ring: object) -> np.ndarray:
    points = np.asarray(ring, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError(f"El anillo es un array finito (n, 2) con n ≥ 3, no de forma {points.shape}")
    if _area2(points) <= 0.0:
        raise ValueError("El anillo de la rampa es antihorario (área positiva)")
    return points


def _sense(sense: str) -> str:
    if sense not in ("cw", "ccw"):
        raise ValueError(f"El sentido de la rampa es «cw» o «ccw», no {sense!r}")
    return sense


def _azimuth_deg(vector: np.ndarray) -> np.ndarray:
    """El azimut (° de 0 a 360, desde el norte y en sentido horario) de ``vector`` ``(k, 2)``; el norte, 0."""
    found = np.degrees(np.arctan2(vector[:, 0], vector[:, 1])) % 360.0
    found[found > 360.0 - _NORTH_WRAP_DEG] = 0.0
    return found


def nearest_on_ring(ring: object, point: Sequence[float]) -> tuple[np.ndarray, int, float, float]:
    """El punto del anillo ``ring`` (antihorario, abierto) más cercano a ``point`` y, a igual distancia (``1e-9`` m), el primero en sentido
    horario desde el norte visto desde ``point`` (P-15, RF-018-25): ``(punto (2,), arista, fracción de la arista, distancia)``."""
    points = _ring(ring)
    target = np.asarray(point, dtype=np.float64)
    if target.shape != (2,) or not np.isfinite(target).all():
        raise ValueError(f"El punto son dos coordenadas finitas, no {target.shape}")
    edge = np.roll(points, -1, axis=0) - points
    length2 = np.einsum("ij,ij->i", edge, edge)
    if bool((length2 <= 0.0).any()):
        raise ValueError("El anillo de la rampa tiene una arista de longitud 0")
    fraction = np.clip(np.einsum("ij,ij->i", target - points, edge) / length2, 0.0, 1.0)
    foot = points + fraction[:, None] * edge
    distance = np.hypot(*(foot - target).T)
    near = np.flatnonzero(distance <= float(distance.min()) + _TIE_M)
    if len(near) > 1:
        near = near[np.argsort(_azimuth_deg(foot[near] - target), kind="stable")[:1]]
    index = int(near[0])
    return foot[index], index, float(fraction[index]), float(distance[index])


@dataclass(frozen=True, slots=True, eq=False)
class _Geometry:
    """El anillo, su eje (desplazado ``W/2`` hacia fuera) y el recorrido desde el punto de inicio en el sentido pedido."""

    foot_path: np.ndarray
    axis_path: np.ndarray
    cumulative: np.ndarray
    perimeter_m: float
    mid_u: np.ndarray
    abscissa_m: float
    start: np.ndarray


def _geometry(ring: np.ndarray, point: Sequence[float], sense: str, half_m: float) -> _Geometry:
    count = len(ring)
    following = np.roll(ring, -1, axis=0)
    edge = following - ring
    length = np.hypot(*edge.T)
    out = np.column_stack([edge[:, 1], -edge[:, 0]]) / length[:, None]  # normal exterior de un anillo antihorario
    before = np.roll(out, 1, axis=0)
    denominator = np.maximum(1.0 + np.einsum("ij,ij->i", before, out), _MITER_FLOOR)
    axis = ring + half_m * (before + out) / denominator[:, None]
    start, e, f, _distance = nearest_on_ring(ring, point)
    axis_edge = np.roll(axis, -1, axis=0) - axis
    axis_length = np.hypot(*axis_edge.T)
    start_axis = axis[e] + f * axis_edge[e]
    if sense == "ccw":
        order = [(e + 1 + i) % count for i in range(count)]
    else:
        order = [(e - i) % count for i in range(count)]
    foot_path = np.vstack([start, ring[order], start])
    axis_path = np.vstack([start_axis, axis[order], start_axis])
    moves = np.hypot(*np.diff(axis_path, axis=0).T) > 1e-12  # el inicio en un vértice no deja un trozo de longitud 0
    keep = np.concatenate([[True], moves])
    foot_path, axis_path = foot_path[keep], axis_path[keep]
    cumulative = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(axis_path, axis=0).T))])
    skeleton = _skeleton_keep(axis_path, 2.0 * half_m)
    spare = _despike_keep(axis_path if skeleton is None else axis_path[skeleton])
    if spare is not None:
        skeleton = spare if skeleton is None else skeleton[spare]
    perimeter_before = float(cumulative[-1])
    if skeleton is not None:
        axis_path, foot_path = axis_path[skeleton], foot_path[skeleton]
        knots = cumulative[skeleton]
        cumulative = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(axis_path, axis=0).T))])
    perimeter = float(cumulative[-1])
    around = np.concatenate([[0.0], np.cumsum(axis_length)])[:-1]
    s0 = float(around[e] + f * axis_length[e])
    mid = around + 0.5 * axis_length
    u = (mid - s0) % perimeter_before if sense == "ccw" else (s0 - mid) % perimeter_before
    if skeleton is not None:
        u = np.interp(u, knots, cumulative)  # la abscisa de cada arista, medida sobre el eje esqueleto (la muesca cuenta como el inicio)
    foot_around = np.concatenate([[0.0], np.cumsum(length)])[:-1]
    foot_s0 = float(foot_around[e] + f * length[e])
    foot_total = float(length.sum())
    abscissa = foot_s0 if sense == "ccw" else (foot_total - foot_s0) % foot_total
    return _Geometry(foot_path, axis_path, cumulative, perimeter, u, abscissa, start)


# --- El tramo de un banco ------------------------------------------------------------------------------------------------------


_HAIRPIN_DEG = 120.0
"""Un giro de más de esto (°) entre dos trozos del eje es un retroceso, no una curva."""
_NOTCH_REACH_W = 6.0
"""Hasta dónde (en anchuras ``W`` de la sección, desde el inicio) se busca la muesca del pie de un tramo."""


_MIN_LEG_M = 0.1
"""Un trozo del eje más corto que esto (m) es ruido del desfase del pie (un vértice a un palmo del anterior), no una curva: se quita."""


def _despike_keep(path: np.ndarray) -> np.ndarray | None:
    """Los índices de ``path`` que quedan al quitar los vértices a menos de ``_MIN_LEG_M`` m del anterior que se conserva (el primero y el último se conservan siempre; el
    penúltimo cede ante el último); ``None`` si no se quita ninguno. Es lo que deja al eje esqueleto sin curvas de radio de centímetros por trozos de milímetros."""
    last = len(path) - 1
    kept = [0]
    for index in range(1, last):
        if float(np.hypot(*(path[index] - path[kept[-1]]))) >= _MIN_LEG_M and float(np.hypot(*(path[last] - path[index]))) >= _MIN_LEG_M:
            kept.append(index)
    kept.append(last)
    return None if len(kept) == len(path) else np.array(kept)


def _skeleton_keep(path: np.ndarray, width_m: float) -> np.ndarray | None:
    """**DIFF-018c (opción i): el eje esqueleto** de un tramo, como los índices de ``path`` (``(n, 2)``, el eje del pie desde el inicio) que se conservan, o ``None`` si no hay
    nada que quitar. El pie del banco ``k + 1`` tiene, donde empieza el tramo, una **muesca** (el pie sigue la cresta ``k``, que salta ``W`` de retranqueo donde acaba la rampa):
    su desfase ``W/2`` es un bucle de retrocesos (giros de más de 120°) con cuerdas gruesas y arcos densos, y el eje no puede heredarlo. Si en los primeros ``6·W`` m hay **dos o
    más retrocesos** (uno solo es una esquina cerrada real del pie y no se toca), el eje esqueleto es el inicio del tramo, la recta hasta el primer punto liso más allá del
    último retroceso (a ``2·W`` m del inicio como poco) y, desde allí, el arco denso del pie sin los puntos a menos de ``W`` m (para que el giro de la recta al arco quepa)."""
    steps = np.diff(path, axis=0)
    if len(steps) < 3:
        return None
    along = np.concatenate([[0.0], np.cumsum(np.hypot(*steps.T))])
    heading = np.degrees(np.arctan2(steps[:, 0], steps[:, 1]))
    turn = np.abs((np.diff(heading) + 180.0) % 360.0 - 180.0)  # el giro en el vértice i + 1
    hairpins = np.flatnonzero((turn > _HAIRPIN_DEG) & (along[1:-1] <= _NOTCH_REACH_W * width_m)) + 1
    if len(hairpins) < 2:
        return None
    last = int(hairpins[-1])
    far = np.hypot(*(path[last + 1:] - path[0]).T) >= 2.0 * width_m
    if not bool(far.any()):
        return None
    first = last + 1 + int(np.argmax(far))
    index = first + 1
    while index < len(path) - 1 and float(np.hypot(*(path[index] - path[first]))) < width_m:
        index += 1
    return np.concatenate([[0], np.arange(first, first + 1), np.arange(index, len(path))])


def build_tramo(ring: object, point: Sequence[float], *, bench: int, z_foot_m: float, rise_m: float, gradient_pct: float,
                width_m: float, transition_m: float = 0.0, sense: str = "ccw") -> Tramo:
    """El tramo del banco ``bench`` sobre su pie ``ring`` (antihorario, abierto) desde el punto del pie más cercano a ``point`` y en el
    ``sense`` pedido (RF-018-16, RF-018-25): sube ``rise_m`` desde ``z_foot_m`` con la pendiente ``gradient_pct`` (%) a lo largo del eje
    (el pie desplazado ``width_m / 2`` hacia fuera) y lleva ``transition_m`` m planos al final. Las estaciones son los vértices del eje
    más el fin, y la pendiente de cada trozo es exactamente la de diseño. :class:`RampDoesNotFit` si el tramo no cabe en el perímetro
    del eje (G-3); ``ValueError`` si algún valor no es de su forma (errores del programa: la preparación ya los comprobó)."""
    points = _ring(ring)
    sense = _sense(sense)
    for name, value in (("la cota del pie", z_foot_m), ("lo que sube", rise_m), ("la pendiente", gradient_pct), ("la anchura", width_m)):
        if not math.isfinite(value):
            raise ValueError(f"{name} no es finita: {value!r}")
    if rise_m <= 0.0 or gradient_pct <= 0.0 or width_m <= 0.0 or transition_m < 0.0 or not math.isfinite(transition_m):
        raise ValueError("Lo que sube, la pendiente y la anchura son > 0 y la transición ≥ 0")
    gradient = gradient_pct / 100.0
    ramp = rise_m / gradient
    total = ramp + transition_m
    found = _geometry(points, point, sense, 0.5 * width_m)
    if total > found.perimeter_m:
        raise RampDoesNotFit(bench, total, found.perimeter_m, found.start)
    cumulative = found.cumulative
    inside = cumulative < total - 1e-12
    s = np.concatenate([cumulative[inside], [total]])
    x = np.concatenate([found.axis_path[inside, 0], [np.interp(total, cumulative, found.axis_path[:, 0])]])
    y = np.concatenate([found.axis_path[inside, 1], [np.interp(total, cumulative, found.axis_path[:, 1])]])
    z = z_foot_m + gradient * np.minimum(s, ramp)
    z[-1] = z_foot_m + rise_m
    return Tramo(bench, found.start, sense, z_foot_m, rise_m, gradient, width_m, transition_m, found.abscissa_m, ramp, total,
                 np.column_stack([x, y, z]))


def wall_height_m(tramo: Tramo, s: object) -> np.ndarray:
    """La altura de la pared sobre la rampa en la abscisa ``s`` del tramo (m, de 0 a ``ramp_m``): ``rise − g·s``, de ``rise`` a 0; 0 pasada
    la rampa."""
    along = np.asarray(s, dtype=np.float64)
    return np.clip(tramo.rise_m - tramo.gradient * along, 0.0, tramo.rise_m)


def crest_distance_m(tramo: Tramo, s: object, face_deg: object) -> np.ndarray:
    """La distancia de la cresta al pie en la abscisa ``s`` de la rampa (DIFF-018-2): ``W + (z_{k+1} − z(s))/tan α``; con la inclinación
    de la cara ``α`` (``face_deg``, °). De ``W + rise/tan α`` al empezar a ``W`` al acabar."""
    return tramo.width_m + wall_height_m(tramo, s) / np.tan(np.radians(np.asarray(face_deg, dtype=np.float64)))


def edge_extra_m(tramo: Tramo, ring: object, face_deg: object) -> np.ndarray:
    """El **término de la rampa** ``(n,)`` de la distancia por arista de ``ring`` (el pie del tramo: antihorario, abierto, el mismo marco
    que el tramo): lo que hay que sumar a la distancia base ``rise/tan α`` de cada arista para que la cresta quede a ``W + (z_{k+1} −
    z(s))/tan α`` en la rampa (``extra_m`` de :func:`design.pit_offset.edge_distances`). ``face_deg`` es ``α`` (° ; un número o uno por
    arista). La abscisa de cada arista es la de su punto medio sobre el eje; la transición entra linealmente antes del inicio y sale en la
    cola plana. Puede ser **negativo** (cresta más cerca que la base) si ``W < rise/tan α``. Con una roseta de varios rangos, ``face_deg``
    de cada arista es el de su rango (los bancos por berma > 1 no se contemplan: el término es el de una cara de ``rise``)."""
    points = _ring(ring)
    found = _geometry(points, tramo.foot_start, tramo.sense, 0.5 * tramo.width_m)
    angle = np.broadcast_to(np.asarray(face_deg, dtype=np.float64), (len(points),))
    if not np.isfinite(angle).all() or bool(((angle <= 0.0) | (angle >= 90.0)).any()):
        raise ValueError("El ángulo de cara es un número entre 0° y 90° (excluidos)")
    cot = 1.0 / np.tan(np.radians(angle))
    u = found.mid_u
    lead = tramo.transition_m
    if lead > 0.0:
        u = np.where((u >= found.perimeter_m - lead) & (u > tramo.length_m), u - found.perimeter_m, u)
    ramp, width, rise = tramo.ramp_m, tramo.width_m, tramo.rise_m
    extra = np.zeros(len(points))
    on_ramp = (u >= 0.0) & (u <= ramp)
    extra[on_ramp] = width - tramo.gradient * u[on_ramp] * cot[on_ramp]
    if lead > 0.0:
        before = (u < 0.0) & (u >= -lead)
        extra[before] = width * (1.0 + u[before] / lead)
        tail = (u > ramp) & (u <= ramp + lead)
        extra[tail] = (width - rise * cot[tail]) * (1.0 - (u[tail] - ramp) / lead)
    return extra


_SPLIT_MIN_M = 1e-3
"""Un punto a menos de esto (m) de un vértice del anillo ya es ese vértice: no se parte la arista (no deja aristas de longitud casi 0)."""
_SPLIT_ON_M = 1e-6
"""A más de esto (m) del anillo, un punto no está sobre una arista y no se inserta."""


def foot_breaks(tramo: Tramo, ring: object) -> np.ndarray:
    """Los puntos ``(k, 2)`` del pie ``ring`` (el del tramo ``tramo`` de una espiral: antihorario, abierto, el mismo marco) donde el término de la cresta cambia de forma: el inicio y el
    fin de la rampa y, con transición, también ``L_t`` m antes y ``L_t`` m después (T21c; RF-018-16). Las aristas del pie se parten ahí (:func:`split_ring`) para que la abscisa del punto
    medio de cada arista, con que :func:`edge_extra_m` evalúa el término, no cruce un cambio de forma."""
    points = _ring(ring)
    found = _geometry(points, tramo.foot_start, tramo.sense, 0.5 * tramo.width_m)
    lead = tramo.transition_m
    marks = [0.0, tramo.ramp_m] if lead <= 0.0 else [-lead, 0.0, tramo.ramp_m, tramo.ramp_m + lead]
    perimeter = found.perimeter_m
    found_points = []
    for mark in marks:
        along = mark + perimeter if mark < 0.0 else mark
        if along >= perimeter - 1e-9:
            continue
        index = min(int(np.searchsorted(found.cumulative, along, side="right")) - 1, len(found.cumulative) - 2)
        span = float(found.cumulative[index + 1] - found.cumulative[index])
        fraction = 0.0 if span <= 0.0 else (along - float(found.cumulative[index])) / span
        found_points.append(found.foot_path[index] + fraction * (found.foot_path[index + 1] - found.foot_path[index]))
    return np.array(found_points).reshape(-1, 2)


def zigzag_foot_breaks(tramo: Tramo) -> np.ndarray:
    """Los dos puntos ``(2, 2)`` del pie donde empieza y acaba el tramo recto de un zig-zag (el eje es el pie desplazado ``W/2``: se restan ``W/2`` a lo largo de su normal)."""
    shift = tramo.axis[0, :2] - tramo.foot_start
    return np.array([tramo.foot_start, tramo.axis[-1, :2] - shift])


def split_ring(ring: object, points: object) -> np.ndarray:
    """El anillo ``ring`` (abierto) con ``points`` ``(k, 2)`` insertados como vértices en la arista a la que pertenecen (a ≤ 1 µm de ella): geométricamente el mismo anillo, con
    las aristas partidas. Un punto a menos de 1 mm de un vértice no se inserta; uno que no está sobre el anillo, tampoco. Es determinista."""
    base = np.asarray(ring, dtype=np.float64)
    found = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(found) == 0:
        return base
    edge = np.roll(base, -1, axis=0) - base
    length2 = np.einsum("ij,ij->i", edge, edge)
    inserts: dict[int, list[tuple[float, np.ndarray]]] = {}
    for point in found:
        fraction = np.clip(np.einsum("ij,ij->i", point - base, edge) / length2, 0.0, 1.0)
        foot = base + fraction[:, None] * edge
        distance = np.hypot(*(foot - point).T)
        index = int(np.argmin(distance))
        if float(distance[index]) > _SPLIT_ON_M:
            continue
        here = base[index] + fraction[index] * edge[index]
        if min(float(np.hypot(*(here - base[index]))), float(np.hypot(*(here - base[(index + 1) % len(base)])))) < _SPLIT_MIN_M:
            continue
        inserts.setdefault(index, []).append((float(fraction[index]), here))
    rows: list[np.ndarray] = []
    for index in range(len(base)):
        rows.append(base[index][None, :])
        for fraction, here in sorted(inserts.get(index, []), key=lambda item: item[0]):
            if float(np.hypot(*(here - rows[-1][-1]))) >= _SPLIT_MIN_M:
                rows.append(here[None, :])
    return np.vstack(rows)


def chain_start(next_ring: object, tramo: Tramo, *, width_m: float | None = None) -> tuple[np.ndarray, np.ndarray, float]:
    """El inicio del tramo del banco siguiente (DIFF-018b): el punto del pie ``next_ring`` más cercano al fin de ``tramo`` (P-15 para los
    empates) y el inicio del eje allí (el pie desplazado ``W/2`` hacia fuera), con la longitud del **enlace horizontal** recto que los une
    (m): ``(punto del pie, inicio del eje, enlace)``."""
    points = _ring(next_ring)
    half = 0.5 * (tramo.width_m if width_m is None else width_m)
    found = _geometry(points, tramo.end_xy, tramo.sense, half)
    start_axis = found.axis_path[0]
    return found.start, start_axis, float(np.hypot(*(start_axis - tramo.end_xy)))


# --- Los bancos encadenados ----------------------------------------------------------------------------------------------------


def _absolute(error: RampDoesNotFit, origin: np.ndarray) -> RampDoesNotFit:
    """``error`` con su lugar en absolutas (``origin`` es el del marco con que se calculó)."""
    if error.place is not None:
        error.place = (error.place[0] + float(origin[0]), error.place[1] + float(origin[1]))
    return error


def _ccw(vertices: np.ndarray) -> np.ndarray:
    ring = np.asarray(vertices, dtype=np.float64)[:, :2]
    return ring if _area2(ring) > 0.0 else ring[::-1]


_END_REACH_W = 1.5
"""La recta con que acaba el eje esqueleto de un tramo, en anchuras ``W`` de la sección: lo bastante larga para que quepa la tangente del giro del enlace."""


def _coarse_end(axis: np.ndarray, reach_m: float) -> np.ndarray:
    """``axis`` (``(n, 3)``, de un tramo) sin los vértices a menos de ``reach_m`` m (de arco) de su final: el eje esqueleto acaba en **una recta** hasta el fin del tramo, donde gira
    el enlace (DIFF-018c). Las cotas de los vértices que quedan son las del tramo (la pendiente de la recta cambia en una parte en mil)."""
    if len(axis) < 3:
        return axis
    along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(axis[:, :2], axis=0).T))])
    keep = along <= along[-1] - reach_m
    keep[[0, -1]] = True
    return axis[keep]


def _spiral_units(job: PitJob, polylines: Sequence[Polyline], ramp: RampDef, start: Sequence[float]) -> Generator[None, None, Spiral]:
    if ramp.type != "spiral":
        raise ValueError(f"La rampa {ramp.code!r} es de tipo {ramp.type!r}, no «spiral»")
    profile = next(item for item in job.road_profiles if item.code == ramp.road_profile)
    width = road_derived(profile).section_m
    feet = sorted((item for item in polylines if item.kind == PolylineKind.FOOT), key=lambda item: (item.z_m, item.bench, item.part))
    crests = {item.bench: item.z_m for item in polylines if item.kind == PolylineKind.CREST}
    if not feet:
        raise ValueError("La rampa en espiral necesita los pies de los bancos")
    origin = np.array(feet[0].vertices[0, :2])
    tramos: list[Tramo] = []
    point = np.asarray(start, dtype=np.float64) - origin
    level = feet[0].z_m
    while True:
        here = [item for item in feet if abs(item.z_m - level) <= _LEVEL_TOL_M]
        if not here:
            break
        best: tuple[float, int] | None = None
        for index, item in enumerate(here):
            distance = nearest_on_ring(_ccw(item.vertices) - origin, point)[3]
            if best is None or distance < best[0] - _TIE_M:
                best = (distance, index)
        assert best is not None
        chosen = here[best[1]]
        top = crests.get(chosen.bench, chosen.z_m + job.height_m)
        try:
            tramo = build_tramo(_ccw(chosen.vertices) - origin, point, bench=chosen.bench, z_foot_m=chosen.z_m, rise_m=top - chosen.z_m,
                                gradient_pct=ramp.gradient_pct, width_m=width, transition_m=ramp.transition_m, sense=ramp.sense)
        except RampDoesNotFit as error:
            raise _absolute(error, origin) from None
        tramos.append(tramo)
        point = tramo.end_xy
        level = top
        yield
    yield
    return spiral_of(tramos, origin, width, ramp)


def spiral_of(tramos: Sequence[Tramo], origin: Sequence[float], width_m: float, ramp: RampDef) -> Spiral:
    """La :class:`Spiral` de los ``tramos`` de ``ramp`` (calculados en un marco local con el ``origin`` absoluto dado): el eje esqueleto de cada tramo (acaba en una recta de
    ``1,5·W``), en absolutas, con sus enlaces horizontales, y los metros de rampa y de enlace."""
    shift = np.array([origin[0], origin[1], 0.0])
    axis = np.vstack([_coarse_end(tramo.axis, _END_REACH_W * width_m) + shift for tramo in tramos])
    run = np.hypot(*np.diff(axis[:, :2], axis=0).T)
    ramp_m = math.fsum(item.length_m for item in tramos)
    path = RampPath(ramp.code, tramos[0].bench, axis, np.full(len(axis), 0.5 * width_m))
    return Spiral(path, tuple(tramos), ramp_m, float(run.sum()) - ramp_m)


def spiral_steps(job: PitJob, polylines: Sequence[Polyline], ramp: RampDef, start: Sequence[float], *,
                 budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A8** (RF-018-16, 25): la rampa en espiral ``ramp`` sobre los pies de ``polylines`` (las de unos :class:`~design.pit_bench.Benches`,
    absolutas; los pies de los bancos ya calculados **con el término de la rampa** de :func:`edge_extra_m`), desde el punto ``start``
    (``(x, y)`` absolutas: el de la capa o el banco que la definición cita lo resuelve la preparación). Tramo a tramo: el del banco ``k``
    sube hasta la cresta ``k`` pegado al pie y el del ``k + 1`` empieza en el punto del pie ``k + 1`` más cercano a su fin, unido por un
    enlace horizontal. El último ``Progress`` lleva en ``result`` la :class:`Spiral`. :class:`RampDoesNotFit` al avanzar si un tramo no
    cabe; no se escribe nada."""
    return pace_progress(_spiral_units(job, polylines, ramp, start), budget_s, phase=_PHASE, running="Calculando la rampa…",
                         finished="Rampa calculada", total=max(2, len({item.bench for item in polylines})))


# --- El zig-zag ----------------------------------------------------------------------------------------------------------------


class ZigzagDoesNotFit(RampDoesNotFit):
    """El zig-zag del banco ``bench`` necesita ``needed_m`` de lado recto y solo hay ``available_m`` (RF-018-20: :func:`no_fit_error`)."""

    reason = "el lado recto del pie"

    def __init__(self, bench: int, needed_m: float, available_m: float, place: Sequence[float] | None = None) -> None:
        ValueError.__init__(self, f"el zig-zag del banco {bench} necesita {needed_m:.3f} m de lado recto y solo hay {available_m:.3f} m")
        self.bench = bench
        self.needed_m = needed_m
        self.available_m = available_m
        self.place = None if place is None else (float(place[0]), float(place[1]))


@dataclass(frozen=True, slots=True, eq=False)
class Zigzag:
    """El zig-zag de una corta: su ``path`` (el eje entero, con las plataformas, y el semiancho ``W/2``), los ``tramos`` por banco, las
    ``platforms`` (``(3, 3)`` por retorno: fin del tramo, fin de la recta e inicio del siguiente, a ``z_{k+1}``), los metros de
    ``ramp_m`` y de plataformas (``platforms_m``), la ``platform_m`` pedida y el desnivel (``rise_m``)."""

    path: RampPath
    tramos: tuple[Tramo, ...]
    platforms: tuple[np.ndarray, ...]
    ramp_m: float
    platforms_m: float
    platform_m: float
    rise_m: float

    @property
    def returns(self) -> int:
        """El número de retornos."""
        return len(self.platforms)

    @property
    def axis_m(self) -> float:
        """La longitud del eje en planta (m): la rampa más las plataformas."""
        return self.ramp_m + self.platforms_m


def platform_length_m(turn_radius_m: float, min_platform_m: float) -> float:
    """La longitud de eje de la plataforma de retorno (G-5): ``max(min_platform, π·Rgiro)``."""
    for name, value in (("el radio de giro", turn_radius_m), ("la plataforma mínima", min_platform_m)):
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} es un número > 0, no {value!r}")
    return max(float(min_platform_m), math.pi * float(turn_radius_m))


@dataclass(frozen=True, slots=True, eq=False)
class _Side:
    """Un lado recto de un pie: el inicio de su eje ``p0`` (el lado desplazado ``W/2`` hacia fuera), su dirección ``u``, su normal
    exterior ``n``, su longitud y su arista."""

    p0: np.ndarray
    u: np.ndarray
    n: np.ndarray
    length: float
    edge: int


def _sides(ring: np.ndarray, half_m: float) -> list[_Side]:
    edge = np.roll(ring, -1, axis=0) - ring
    length = np.hypot(*edge.T)
    if bool((length <= 0.0).any()):
        raise ValueError("El anillo de la rampa tiene una arista de longitud 0")
    u = edge / length[:, None]
    n = np.column_stack([u[:, 1], -u[:, 0]])
    return [_Side(ring[i] + half_m * n[i], u[i], n[i], float(length[i]), i) for i in range(len(ring))]


def _first_side(ring: np.ndarray, point: Sequence[float], half_m: float) -> _Side:
    """El lado más largo que contiene el punto del pie más cercano a ``point`` (en un vértice, el más largo de los dos; a igual longitud, el primero)."""
    distance = nearest_on_ring(ring, point)[3]
    target = np.asarray(point, dtype=np.float64)
    edge = np.roll(ring, -1, axis=0) - ring
    fraction = np.clip(np.einsum("ij,ij->i", target - ring, edge) / np.einsum("ij,ij->i", edge, edge), 0.0, 1.0)
    reach = np.hypot(*(ring + fraction[:, None] * edge - target).T)
    near = [item for item, value in zip(_sides(ring, half_m), reach, strict=True) if value <= distance + _TIE_M]
    return max(near, key=lambda item: (item.length, -item.edge))


def _side_after(ring: np.ndarray, end: np.ndarray, back: np.ndarray, out: np.ndarray, half_m: float, min_length_m: float = 0.0) -> tuple[_Side, float]:
    """El lado del pie siguiente: el paralelo al anterior (el tramo vuelve en ``back``) y el más cercano por fuera del eje de ``end``,
    con la distancia lateral ``d`` (m). Con ``min_length_m`` (un pie real, con el escalón que deja el término de la cresta, tiene lados paralelos cortos), solo los que miden
    al menos eso; si ninguno llega, todos (el rechazo lo da quien lo construye)."""
    best: tuple[float, float, _Side] | None = None
    sides = _sides(ring, half_m)
    if min_length_m > 0.0 and any(item.length >= min_length_m - 1e-9 for item in sides):
        sides = [item for item in sides if item.length >= min_length_m - 1e-9]
    for side in sides:
        if abs(float(side.u @ back)) < 0.999:
            continue
        lateral = float((side.p0 - end) @ out)
        if lateral <= 1e-6:
            continue
        key = (lateral, -side.length)
        if best is None or key < best[:2]:
            best = (lateral, -side.length, side)
    if best is None:
        raise ValueError("El pie del banco siguiente no tiene un lado paralelo por fuera del eje de la rampa")
    return best[2], best[0]


def _zigzag_tramo(side: _Side, t: float, sigma: float, *, bench: int, z_foot_m: float, rise_m: float, gradient_pct: float,
                  width_m: float, platform_m: float, last: bool, sense: str) -> Tramo:
    gradient = gradient_pct / 100.0
    ramp = rise_m / gradient
    room = side.length - t if sigma > 0.0 else t
    if ramp > room + 1e-9:
        raise ZigzagDoesNotFit(bench, ramp, room, side.p0 + t * side.u)
    needed = ramp + (0.0 if last else platform_m)
    if needed > side.length + 1e-9:
        raise ZigzagDoesNotFit(bench, needed, side.length, side.p0 + t * side.u)
    start = side.p0 + t * side.u
    end = start + sigma * ramp * side.u
    axis = np.array([[start[0], start[1], z_foot_m], [end[0], end[1], z_foot_m + rise_m]])
    return Tramo(bench, start - 0.5 * width_m * side.n, sense, z_foot_m, rise_m, gradient, width_m, 0.0, t, ramp, ramp, axis)


def _assemble(tramos: Sequence[Tramo], platforms: Sequence[np.ndarray], half_m: float, code: str, platform_m: float) -> Zigzag:
    rows: list[np.ndarray] = [tramos[0].axis]
    for platform, tramo in zip(platforms, tramos[1:], strict=True):
        rows.append(platform[1:])
        rows.append(tramo.axis[1:])
    axis = np.vstack(rows)
    axis = axis[np.concatenate([[True], np.hypot(*np.diff(axis[:, :2], axis=0).T) > 1e-12])]
    ramp_m = math.fsum(item.ramp_m for item in tramos)
    platforms_m = math.fsum(float(np.hypot(*np.diff(item[:, :2], axis=0).T).sum()) for item in platforms)
    path = RampPath(code, tramos[0].bench, axis, np.full(len(axis), half_m))
    return Zigzag(path, tuple(tramos), tuple(platforms), ramp_m, platforms_m, platform_m, float(axis[-1, 2] - axis[0, 2]))


def _zigzag_link(ring: np.ndarray, tramo: Tramo, side: _Side, sigma: float, half_m: float, platform_m: float, z_next_m: float, bench: int
                 ) -> tuple[np.ndarray, _Side, float, float]:
    """La plataforma de retorno tras ``tramo`` (que va por ``side`` en el sentido ``sigma``) hacia el pie ``ring`` del banco ``bench``: ``(plataforma ``(3, 3)``, el lado siguiente, su
    sentido, la abscisa de inicio sobre él)``. :class:`ZigzagDoesNotFit` si el tramo y la plataforma no caben en su lado o el aterrizaje cae fuera del lado siguiente."""
    needed = tramo.ramp_m + platform_m
    if needed > side.length + 1e-9:
        raise ZigzagDoesNotFit(tramo.bench, needed, side.length, side.p0 + tramo.abscissa_m * side.u)
    end = tramo.end_xy
    travel = sigma * side.u
    try:
        following, lateral = _side_after(ring, end, -travel, side.n, half_m, tramo.ramp_m)
    except ValueError:
        raise ZigzagDoesNotFit(bench, tramo.ramp_m, 0.0, end) from None
    turn = end + max(platform_m - lateral, 0.0) * travel
    landing = turn + lateral * side.n
    landing = landing - ((landing - following.p0) @ following.n) * following.n  # al eje del lado siguiente
    platform = np.array([[end[0], end[1], z_next_m], [turn[0], turn[1], z_next_m], [landing[0], landing[1], z_next_m]])
    t = float((landing - following.p0) @ following.u)
    if not -1e-9 <= t <= following.length + 1e-9:
        raise ZigzagDoesNotFit(bench, t, following.length, landing)
    return platform, following, -sigma, min(max(t, 0.0), following.length)


def build_zigzag(rings: Sequence[object], point: Sequence[float], *, z_first_m: float, rise_m: float, gradient_pct: float, width_m: float,
                 platform_m: float, sense: str = "ccw", code: str = "zigzag", first_bench: int = 0) -> Zigzag:
    """El zig-zag sobre los pies ``rings`` (de abajo arriba; antihorarios y abiertos, en el mismo marco que ``point``; el banco ``i`` es
    ``first_bench + i`` y su pie está a ``z_first_m + i·rise_m``): tramos de ``rise/g`` m con la pendiente ``gradient_pct`` (%) y
    plataformas de retorno horizontales de ``platform_m`` m de eje (:func:`platform_length_m`). :class:`ZigzagDoesNotFit` si un tramo
    o ``h/g + P`` no caben en el lado recto (RF-018-20); ``ValueError`` si algo no es de su forma (errores del programa)."""
    if not rings:
        raise ValueError("El zig-zag necesita al menos un pie")
    sense = _sense(sense)
    for name, value in (("lo que sube", rise_m), ("la pendiente", gradient_pct), ("la anchura", width_m), ("la plataforma", platform_m),
                        ("la cota del primer pie", z_first_m)):
        if not math.isfinite(value) or (value <= 0.0 and name != "la cota del primer pie"):
            raise ValueError(f"{name} es un número finito > 0, no {value!r}")
    half = 0.5 * width_m
    points = [_ring(item) for item in rings]
    side = _first_side(points[0], point, half)
    sigma = 1.0 if sense == "ccw" else -1.0
    t = 0.0 if sigma > 0.0 else side.length
    tramos: list[Tramo] = []
    platforms: list[np.ndarray] = []
    for index in range(len(points)):
        last = index == len(points) - 1
        tramo = _zigzag_tramo(side, t, sigma, bench=first_bench + index, z_foot_m=z_first_m + index * rise_m, rise_m=rise_m,
                              gradient_pct=gradient_pct, width_m=width_m, platform_m=platform_m, last=last, sense=sense)
        tramos.append(tramo)
        if last:
            break
        platform, side, sigma, t = _zigzag_link(points[index + 1], tramo, side, sigma, half, platform_m, z_first_m + (index + 1) * rise_m,
                                                first_bench + index + 1)
        platforms.append(platform)
    return _assemble(tramos, platforms, half, code, platform_m)


class ZigzagStepper:
    """El zig-zag de ``ramp`` banco a banco (T21c): cada pie, al calcularse, pide su tramo (:meth:`tramo`) y, al acabar, :meth:`result` da el :class:`Zigzag` en absolutas. Es
    :func:`build_zigzag` con los pies de uno en uno (el lado siguiente y la plataforma salen del pie del banco que sigue, ya con el término de la cresta anterior)."""

    def __init__(self, ramp: RampDef, width_m: float) -> None:
        if ramp.type != "zigzag":
            raise ValueError(f"La rampa {ramp.code!r} es de tipo {ramp.type!r}, no «zigzag»")
        if ramp.turn_radius_m is None or ramp.min_platform_m is None:
            raise ValueError(f"La rampa {ramp.code!r} en zig-zag necesita el radio de giro y la plataforma mínima")
        self.ramp = ramp
        self.width_m = width_m
        self.platform_m = platform_length_m(ramp.turn_radius_m, ramp.min_platform_m)
        self.tramos: list[Tramo] = []
        self.platforms: list[np.ndarray] = []
        self._side: _Side | None = None
        self._sigma = 1.0 if ramp.sense == "ccw" else -1.0

    def tramo(self, ring: object, point: Sequence[float], *, bench: int, z_foot_m: float, rise_m: float) -> Tramo:
        """El tramo del banco ``bench`` sobre su pie ``ring`` (antihorario, abierto): en el primero, el lado más largo que contiene ``point``; en los demás, tras la plataforma de
        retorno. :class:`ZigzagDoesNotFit` si no cabe."""
        points = _ring(ring)
        half = 0.5 * self.width_m
        if self._side is None:
            side = _first_side(points, point, half)
            t = 0.0 if self._sigma > 0.0 else side.length
            sigma = self._sigma
        else:
            platform, side, sigma, t = _zigzag_link(points, self.tramos[-1], self._side, self._sigma, half, self.platform_m, z_foot_m, bench)
            self.platforms.append(platform)
        found = _zigzag_tramo(side, t, sigma, bench=bench, z_foot_m=z_foot_m, rise_m=rise_m, gradient_pct=self.ramp.gradient_pct, width_m=self.width_m,
                              platform_m=self.platform_m, last=True, sense=self.ramp.sense)
        self._side, self._sigma = side, sigma
        self.tramos.append(found)
        return found

    def result(self, origin: Sequence[float]) -> Zigzag:
        """El :class:`Zigzag` de los tramos calculados hasta ahora (``origin``: el absoluto del marco local)."""
        return zigzag_of(self.tramos, self.platforms, origin, self.width_m, self.platform_m, self.ramp)


def zigzag_of(tramos: Sequence[Tramo], platforms: Sequence[np.ndarray], origin: Sequence[float], width_m: float, platform_m: float, ramp: RampDef) -> Zigzag:
    """El :class:`Zigzag` de los ``tramos`` y ``platforms`` de ``ramp`` (calculados en un marco local con el ``origin`` absoluto dado), en absolutas."""
    shift = np.array([origin[0], origin[1], 0.0])
    found = _assemble(tramos, platforms, 0.5 * width_m, ramp.code, platform_m)
    path = RampPath(ramp.code, found.path.bench, found.path.axis + shift, found.path.half_width_m)
    return Zigzag(path, tuple(dataclasses.replace(item, axis=item.axis + shift) for item in found.tramos), tuple(item + shift for item in found.platforms),
                  found.ramp_m, found.platforms_m, found.platform_m, found.rise_m)


def zigzag_edge_extra_m(tramo: Tramo, ring: object, face_deg: object) -> np.ndarray:
    """El **término del tramo** ``(n,)`` de la distancia por arista de ``ring`` (el pie del tramo, el mismo marco): ``W − g·s/tan α`` para
    cada arista cuyo punto medio está en el pie del tramo (a ``W/2`` del eje) con ``s`` su abscisa de 0 a ``ramp_m`` (RF-018-17), de modo
    que la cresta quede a ``W + (z_{k+1} − z(s))/tan α``; 0 en las demás. Como en la espiral, la abscisa es la del punto medio: la
    preparación parte las aristas en los extremos del tramo."""
    points = _ring(ring)
    angle = np.broadcast_to(np.asarray(face_deg, dtype=np.float64), (len(points),))
    if not np.isfinite(angle).all() or bool(((angle <= 0.0) | (angle >= 90.0)).any()):
        raise ValueError("El ángulo de cara es un número entre 0° y 90° (excluidos)")
    start, end = tramo.axis[0, :2], tramo.axis[-1, :2]
    along = (end - start) / np.hypot(*(end - start))
    mid = 0.5 * (points + np.roll(points, -1, axis=0))
    s = (mid - start) @ along
    lateral = np.abs((mid - start) @ np.array([-along[1], along[0]]))
    on = (np.abs(lateral - 0.5 * tramo.width_m) <= 1e-6) & (s >= -1e-9) & (s <= tramo.ramp_m + 1e-9)
    extra = np.zeros(len(points))
    extra[on] = tramo.width_m - tramo.gradient * s[on] / np.tan(np.radians(angle[on]))
    return extra


def _zigzag_units(job: PitJob, polylines: Sequence[Polyline], ramp: RampDef, start: Sequence[float]) -> Generator[None, None, Zigzag]:
    if ramp.type != "zigzag":
        raise ValueError(f"La rampa {ramp.code!r} es de tipo {ramp.type!r}, no «zigzag»")
    if ramp.turn_radius_m is None or ramp.min_platform_m is None:
        raise ValueError(f"La rampa {ramp.code!r} en zig-zag necesita el radio de giro y la plataforma mínima")
    profile = next(item for item in job.road_profiles if item.code == ramp.road_profile)
    width = road_derived(profile).section_m
    platform = platform_length_m(ramp.turn_radius_m, ramp.min_platform_m)
    feet = sorted((item for item in polylines if item.kind == PolylineKind.FOOT), key=lambda item: (item.z_m, item.bench, item.part))
    crests = {item.bench: item.z_m for item in polylines if item.kind == PolylineKind.CREST}
    if not feet:
        raise ValueError("La rampa en zig-zag necesita los pies de los bancos")
    origin = np.array(feet[0].vertices[0, :2])
    point = np.asarray(start, dtype=np.float64) - origin
    level = feet[0].z_m
    chosen_feet: list[Polyline] = []
    while True:
        here = [item for item in feet if abs(item.z_m - level) <= _LEVEL_TOL_M]
        if not here:
            break
        best: tuple[float, int] | None = None
        for index, item in enumerate(here):
            distance = nearest_on_ring(_ccw(item.vertices) - origin, point)[3]
            if best is None or distance < best[0] - _TIE_M:
                best = (distance, index)
        assert best is not None
        chosen = here[best[1]]
        chosen_feet.append(chosen)
        level = crests.get(chosen.bench, chosen.z_m + job.height_m)
        yield
    first = chosen_feet[0]
    rise = crests.get(first.bench, first.z_m + job.height_m) - first.z_m
    try:
        found = build_zigzag([_ccw(item.vertices) - origin for item in chosen_feet], point, z_first_m=first.z_m, rise_m=rise,
                             gradient_pct=ramp.gradient_pct, width_m=width, platform_m=platform, sense=ramp.sense, code=ramp.code,
                             first_bench=first.bench)
    except RampDoesNotFit as error:
        raise _absolute(error, origin) from None
    shift = np.array([origin[0], origin[1], 0.0])
    path = RampPath(ramp.code, found.path.bench, found.path.axis + shift, found.path.half_width_m)
    yield
    return Zigzag(path, tuple(dataclasses.replace(item, axis=item.axis + shift) for item in found.tramos),
                  tuple(item + shift for item in found.platforms), found.ramp_m, found.platforms_m, found.platform_m, found.rise_m)


def zigzag_steps(job: PitJob, polylines: Sequence[Polyline], ramp: RampDef, start: Sequence[float], *,
                 budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A9** (RF-018-17, 25): la rampa en zig-zag ``ramp`` sobre los pies de ``polylines`` (como :func:`spiral_steps`; los pies ya llevan
    el término de :func:`zigzag_edge_extra_m`) desde el punto ``start`` (absoluto). El último ``Progress`` lleva en ``result`` el
    :class:`Zigzag`; :class:`ZigzagDoesNotFit` al avanzar si no cabe; no se escribe nada."""
    return pace_progress(_zigzag_units(job, polylines, ramp, start), budget_s, phase=_PHASE, running="Calculando la rampa…",
                         finished="Rampa calculada", total=max(2, len({item.bench for item in polylines})))


# --- Las reglas de la 017, los diagnósticos y la banda (T17) -------------------------------------------------------------------


_SPIRAL_SIMPLIFY_M = 0.1
"""La tolerancia (m) con que el eje denso de una espiral se reduce a su esqueleto (Douglas–Peucker, la de ``axis_of``) antes de redondear los giros."""
_MEAN_TOL_PCT = 1e-6
"""Lo que una media nueva puede pasar de la confirmada (puntos de porcentaje) y seguir siendo la misma: el ruido de la última cifra."""
_BLOCK_REASONS = {"noramp": "zona sin rampa", "untouchable": "intocable"}
"""Lo que impide una rampa (RF-018-20) en el rechazo de la persona."""


def _place(x: float, y: float) -> str:
    return f"{x:.1f}, {y:.1f}"


def no_fit_error(error: RampDoesNotFit, ramp: RampDef) -> DesignError:
    """El rechazo de la persona (``des.pit_no_ramp_fit``, RF-018-20) de la excepción ``error`` de un constructor (:func:`build_tramo`, :func:`build_zigzag`,
    :func:`spiral_steps`, :func:`zigzag_steps`) para ``ramp``: el banco, la longitud necesaria y la disponible (m), lo que lo impide y el lugar; qué probar
    (otro tipo, otro sentido u otro punto de inicio) lo dice el catálogo. No relaja ``g``, ``Rmín`` ni la plataforma ni cambia nada."""
    place = "?" if error.place is None else _place(*error.place)
    return DesignError("des.pit_no_ramp_fit", obj=f"Rampa «{ramp.name}»", field=pitramp_key(ramp.code, PitRampParam.TYPE), value=ramp.type,
                       profile=ramp.name, bench=error.bench, needed=round(error.needed_m, 3), available=round(error.available_m, 3),
                       reason=error.reason, place=place)


@dataclass(frozen=True, slots=True, eq=False)
class Band:
    """La banda de una rampa (RF-018-21): el ``axis`` ``(n, 3)`` en las estaciones y sus bordes ``left`` y ``right`` (``(n, 3)``): a ``half_width_m`` del eje
    a cada lado, perpendiculares a su dirección y a la cota del eje (horizontal en su anchura). :attr:`breaklines` son las aristas obligatorias de la superficie."""

    half_width_m: float
    axis: np.ndarray
    left: np.ndarray
    right: np.ndarray

    @property
    def breaklines(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Borde izquierdo, eje y borde derecho (``(n, 3)`` cada uno), con su Z por estaciones."""
        return self.left, self.axis, self.right


def _band(axis: Axis, levels: np.ndarray, half_m: float) -> Band:
    heading = np.column_stack([np.sin(axis.azimuth), np.cos(axis.azimuth)])
    left_normal = np.column_stack([-heading[:, 1], heading[:, 0]])
    arrays = [np.column_stack([axis.points, levels]), np.column_stack([axis.points + half_m * left_normal, levels]),
              np.column_stack([axis.points - half_m * left_normal, levels])]
    for array in arrays:
        array.flags.writeable = False
    return Band(half_m, arrays[0], arrays[1], arrays[2])


@dataclass(frozen=True, slots=True, eq=False)
class RampChecked:
    """Una rampa con las reglas de la 017 aplicadas (:func:`check_ramp`): ``code`` y ``name`` de su definición, el ``profile`` de pista, el ``axis`` de la 017
    (``road_axis.Axis``), la cota (``z``) y el banco (``benches``) de cada estación, el ``path`` (el eje redondeado con su Z y el semiancho), la ``band``, los
    ``notices`` de RF-018-19 (radios reducidos, pendientes sobre pd y la media sobre pm, cada uno con su banco, su abscisa y su lugar), la pendiente media y la
    mayor (%) y si la media pasa de pm (``mean_exceeded``: no se crea sin :func:`confirm_mean`)."""

    code: str
    name: str
    profile: Any
    axis: Axis
    z: np.ndarray
    benches: np.ndarray
    path: RampPath
    band: Band
    notices: tuple[Notice, ...]
    mean_gradient_pct: float
    max_gradient_pct: float
    mean_exceeded: bool

    @property
    def length_m(self) -> float:
        """La longitud del eje en planta (m), con sus curvas."""
        return self.axis.length_m

    @property
    def line(self) -> np.ndarray:
        """El eje con su Z por estaciones, ``(n, 3)`` absolutas: la línea comprobable con la 017 (P2)."""
        return self.path.axis


def _levels(axis: Axis, raw: np.ndarray, stations: np.ndarray) -> np.ndarray:
    """La cota del eje en las abscisas ``stations`` del eje redondeado: la de la construcción ``raw`` en su abscisa **a lo largo de la línea** (``Axis.line_abscissa``) en las rectas,
    y **lineal en el arco** entre las cotas de sus dos puntos de tangencia (DIFF-018c). Con la correspondencia por la línea, el arco de una esquina de 90° donde empieza un tramo
    reparte los ``2T`` de línea sobre un arco más corto y sube la pendiente de la mitad que sube a ``g·4/π`` (8 % → 10,19 %, con pd = 10 %: aviso); lineal en el arco no pasa de ``g``
    (y baja a ``0,64·g`` en un giro de 90°). La cota de cada punto de tangencia y la de cada banco siguen siendo las de la construcción."""
    along = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(axis.vertices, axis=0).T))))
    z_line = raw[axis.kept, 2]
    if not axis.curves:
        return np.interp(axis.line_abscissa(stations), along, z_line)
    at = np.searchsorted(axis.kept, np.array([curve.vertex - 1 for curve in axis.curves]))
    tangent = np.array([curve.tangent_m for curve in axis.curves])
    first = np.array([curve.station_m for curve in axis.curves])
    arc = np.array([curve.length_m for curve in axis.curves])
    on_axis = np.concatenate(([0.0], np.column_stack([first, first + arc]).ravel(), [axis.length_m]))
    on_line = np.concatenate(([0.0], np.column_stack([along[at] - tangent, along[at] + tangent]).ravel(), [float(along[-1])]))
    return np.interp(np.clip(np.asarray(stations, dtype=np.float64), 0.0, axis.length_m), on_axis, np.interp(on_line, along, z_line))


def _bench_of(levels: np.ndarray, found: Spiral | Zigzag) -> np.ndarray:
    """El banco de cada cota: el del tramo cuyo pie queda por debajo (un enlace o plataforma, a ``z_{k+1}``, es del banco que alcanza)."""
    feet = np.array([item.z_foot_m for item in found.tramos])
    ids = np.array([item.bench for item in found.tramos])
    return ids[np.clip(np.searchsorted(feet, np.asarray(levels) + 1e-6, side="right") - 1, 0, len(feet) - 1)]


def _hits(mask: np.ndarray, grid: Any, xy: np.ndarray) -> np.ndarray:
    col = np.floor((xy[:, 0] - grid.west) / grid.dx).astype(np.int64)
    row = np.floor((grid.north - xy[:, 1]) / grid.dy).astype(np.int64)
    inside = (row >= 0) & (row < grid.nrows) & (col >= 0) & (col < grid.ncols)
    hit = np.zeros(len(xy), dtype=bool)
    hit[inside] = mask[row[inside], col[inside]]
    return hit


def _blocked(axis: Axis, raw: np.ndarray, job: PitJob, found: Spiral | Zigzag, ramp: RampDef) -> None:
    """RF-018-20: ``DesignError`` ``des.pit_no_ramp_fit`` si el eje cruza una zona sin rampa o un intocable: el banco, lo que mide el eje de ese banco (necesaria) y lo que
    queda libre hasta el obstáculo (disponible), lo que lo impide y el lugar. Se mira cada ``w`` m o cada medio paso de rejilla si es menor."""
    masks: dict[str, np.ndarray] = {}
    if job.noramp:
        masks["noramp"] = polygons_cells(job.noramp, job.grid)
    if bool(job.untouchable.any()):
        masks["untouchable"] = job.untouchable
    if not masks:
        return
    s = stations_for(axis.length_m, min(axis.step_m, 0.5 * min(job.grid.dx, job.grid.dy)))
    xy, _azimuth = axis.sample(s)
    blocked = np.zeros(len(s), dtype=bool)
    why = np.full(len(s), "", dtype=object)
    for reason, mask in masks.items():
        hit = _hits(mask, job.grid, xy) & ~blocked
        blocked |= hit
        why[hit] = reason
    if not blocked.any():
        return
    first = int(np.argmax(blocked))
    benches = _bench_of(_levels(axis, raw, s), found)
    mine = benches == benches[first]
    start = float(s[mine][0])
    raise DesignError("des.pit_no_ramp_fit", obj=f"Rampa «{ramp.name}»", field=pitramp_key(ramp.code, PitRampParam.TYPE), value=ramp.type, profile=ramp.name,
                      bench=int(benches[first]), needed=round(float(s[mine][-1]) - start, 3), available=round(float(s[first]) - start, 3),
                      reason=_BLOCK_REASONS[str(why[first])], place=_place(float(xy[first, 0]), float(xy[first, 1])))


def check_ramp(found: Spiral | Zigzag, job: PitJob, ramp: RampDef, *, simplify_m: float | None = None) -> RampChecked:
    """**RF-018-18 a 21**: el eje de ``found`` (la :class:`Spiral` o el :class:`Zigzag` de ``ramp``, con el perfil de pista de ``job``) con las reglas de la 017, sin
    cambiar ni escribir nada. (1) Las curvas: ``road_axis.axis_of`` con ``R``, ``Rmín`` y ``w`` del perfil (``simplify_m``: Douglas–Peucker, 0 por defecto); el
    radio que baja al que cabe es el aviso ``des.pit_ramp_radius_reduced`` y por debajo de ``Rmín``, ``DesignError`` ``des.pit_ramp_radius_below_min`` con el banco y
    el lugar. (2) La Z de cada estación es la del eje en su abscisa y ``road_gradient.check_axis_3d`` avisa cada tramo sobre pd y la media sobre pm. (3) Una zona
    sin rampa o un intocable en el eje: ``des.pit_no_ramp_fit`` (el perímetro y el lado recto los dan los constructores: :func:`no_fit_error`). (4) La banda
    (:class:`Band`). ``ValueError`` si el perfil de pista de ``ramp`` no está en ``job`` (un error del programa)."""
    profile = next((item for item in job.road_profiles if item.code == ramp.road_profile), None)
    if profile is None:
        raise ValueError(f"La rampa {ramp.code!r} cita el perfil de pista {ramp.road_profile!r}, que la corta no tiene")
    raw = np.asarray(found.path.axis, dtype=np.float64)
    if simplify_m is None:
        simplify_m = _SPIRAL_SIMPLIFY_M if isinstance(found, Spiral) else 0.0
    try:
        axis = axis_of(raw[:, :2], profile.curve_radius_m, profile.min_radius_m, profile.station_step_m, simplify_m=simplify_m)
    except RadiusBelowMinimum as error:
        curve = error.curve
        bench = int(_bench_of(raw[[curve.vertex - 1], 2], found)[0])
        raise DesignError("des.pit_ramp_radius_below_min", obj=f"Rampa «{ramp.name}»", field=road_profile_key(profile.code, RoadProfileParam.MIN_RADIUS),
                          value=round(curve.radius_m, 3), profile=ramp.name, limit=error.minimum_m, bench=bench,
                          place=_place(curve.x, curve.y), link=round(min(curve.before_m, curve.after_m), 3)) from None
    _blocked(axis, raw, job, found, ramp)
    z = _levels(axis, raw, axis.stations)
    benches = _bench_of(z, found)
    notices: list[Notice] = []
    for item in axis.notices(ramp.name):
        at = int(_bench_of(raw[[int(item.values["vertex"]) - 1], 2], found)[0])
        notices.append(Notice("des.pit_ramp_radius_reduced", {**item.values, "entity": ramp.name, "bench": at}))
    mean_exceeded = False
    for item in check_axis_3d(axis, z, profile, ramp.name):
        if item.code == "des.road_axis3d_gradient":
            at = int(benches[int(np.searchsorted(axis.stations, item.values["station"]))])
            notices.append(Notice("des.pit_ramp_gradient", {**item.values, "entity": ramp.name, "bench": at}))
        elif item.code == "des.road_mean_gradient":
            mean_exceeded = True
            notices.append(Notice("des.pit_ramp_mean_gradient", {**item.values, "entity": ramp.name}))
    gradients = np.abs(np.diff(z)) / np.diff(axis.stations)
    half = float(found.path.half_width_m[0])
    line = np.column_stack([axis.points, z])
    line.flags.writeable = False
    path = RampPath(found.path.code, found.path.bench, line, np.full(len(line), half))
    return RampChecked(ramp.code, ramp.name, profile, axis, z, benches, path, _band(axis, z, half), tuple(notices),
                       mean_gradient(axis.stations, z) * 100.0, float(gradients.max(initial=0.0)) * 100.0, mean_exceeded)


def confirm_mean(checked: RampChecked, confirmation: RampConfirmation | None = None, *, tolerance_pct: float = _MEAN_TOL_PCT) -> RampConfirmation | None:
    """La confirmación de la pendiente media (RF-018-19, RF-017-17): ``None`` si la media no pasa de pm; si pasa, la ``confirmation`` que la cubre (la de esta rampa,
    con su motivo, de una media no menor que la actual a ``tolerance_pct``) o ``DesignError`` ``des.pit_ramp_mean_over``: la corta no se crea sin ella ni se corrige el eje."""
    if not checked.mean_exceeded:
        return None
    if confirmation is not None and confirmation.ramp == checked.code and confirmation.covers(checked.mean_gradient_pct, tolerance_pct):
        return confirmation
    raise DesignError("des.pit_ramp_mean_over", obj=f"Rampa «{checked.name}»", field=road_profile_key(checked.profile.code, RoadProfileParam.MAX_MEAN_GRADIENT),
                      value=round(checked.mean_gradient_pct, 2), profile=checked.name, limit=checked.profile.max_mean_gradient_pct)
