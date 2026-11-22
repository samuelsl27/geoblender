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

import numpy as np

from ..core.project.model import Progress
from ..gis.masks.compile import STEP_BUDGET_S
from .pit_model import PitJob, Polyline, PolylineKind, RampDef, RampPath
from .road_profiles import derived as road_derived
from .seeds import pace_progress

__all__ = [
    "RampDoesNotFit",
    "Spiral",
    "Tramo",
    "Zigzag",
    "ZigzagDoesNotFit",
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
    """El tramo del banco ``bench`` mide ``needed_m`` y el perímetro del eje solo ``available_m`` (G-3, RF-018-20): lo diagnostica T17."""

    def __init__(self, bench: int, needed_m: float, available_m: float) -> None:
        super().__init__(f"la rampa del banco {bench} necesita {needed_m:.3f} m y el perímetro del eje solo mide {available_m:.3f} m")
        self.bench = bench
        self.needed_m = needed_m
        self.available_m = available_m


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
    perimeter = float(cumulative[-1])
    around = np.concatenate([[0.0], np.cumsum(axis_length)])[:-1]
    s0 = float(around[e] + f * axis_length[e])
    mid = around + 0.5 * axis_length
    u = (mid - s0) % perimeter if sense == "ccw" else (s0 - mid) % perimeter
    foot_around = np.concatenate([[0.0], np.cumsum(length)])[:-1]
    foot_s0 = float(foot_around[e] + f * length[e])
    foot_total = float(length.sum())
    abscissa = foot_s0 if sense == "ccw" else (foot_total - foot_s0) % foot_total
    return _Geometry(foot_path, axis_path, cumulative, perimeter, u, abscissa, start)


# --- El tramo de un banco ------------------------------------------------------------------------------------------------------


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
        raise RampDoesNotFit(bench, total, found.perimeter_m)
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


def _ccw(vertices: np.ndarray) -> np.ndarray:
    ring = np.asarray(vertices, dtype=np.float64)[:, :2]
    return ring if _area2(ring) > 0.0 else ring[::-1]


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
        tramo = build_tramo(_ccw(chosen.vertices) - origin, point, bench=chosen.bench, z_foot_m=chosen.z_m, rise_m=top - chosen.z_m,
                            gradient_pct=ramp.gradient_pct, width_m=width, transition_m=ramp.transition_m, sense=ramp.sense)
        tramos.append(tramo)
        point = tramo.end_xy
        level = top
        yield
    stations: list[np.ndarray] = []
    for tramo in tramos:
        stations.append(tramo.axis + np.array([origin[0], origin[1], 0.0]))
    axis = np.vstack(stations)
    run = np.hypot(*np.diff(axis[:, :2], axis=0).T)
    ramp_m = math.fsum(item.length_m for item in tramos)
    path = RampPath(ramp.code, tramos[0].bench, axis, np.full(len(axis), 0.5 * width))
    yield
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
    """El zig-zag del banco ``bench`` necesita ``needed_m`` de lado recto y solo hay ``available_m`` (RF-018-20: lo diagnostica T17)."""

    def __init__(self, bench: int, needed_m: float, available_m: float) -> None:
        ValueError.__init__(self, f"el zig-zag del banco {bench} necesita {needed_m:.3f} m de lado recto y solo hay {available_m:.3f} m")
        self.bench = bench
        self.needed_m = needed_m
        self.available_m = available_m


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


def _side_after(ring: np.ndarray, end: np.ndarray, back: np.ndarray, out: np.ndarray, half_m: float) -> tuple[_Side, float]:
    """El lado del pie siguiente: el paralelo al anterior (el tramo vuelve en ``back``) y el más cercano por fuera del eje de ``end``,
    con la distancia lateral ``d`` (m)."""
    best: tuple[float, float, _Side] | None = None
    for side in _sides(ring, half_m):
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
        raise ZigzagDoesNotFit(bench, ramp, room)
    needed = ramp + (0.0 if last else platform_m)
    if needed > side.length + 1e-9:
        raise ZigzagDoesNotFit(bench, needed, side.length)
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
        end = tramo.end_xy
        travel = sigma * side.u
        following, lateral = _side_after(points[index + 1], end, -travel, side.n, half)
        turn = end + max(platform_m - lateral, 0.0) * travel
        landing = turn + lateral * side.n
        landing = landing - ((landing - following.p0) @ following.n) * following.n  # al eje del lado siguiente
        z_next = z_first_m + (index + 1) * rise_m
        platforms.append(np.array([[end[0], end[1], z_next], [turn[0], turn[1], z_next], [landing[0], landing[1], z_next]]))
        side, sigma = following, -sigma
        t = float((landing - following.p0) @ following.u)
        if not -1e-9 <= t <= following.length + 1e-9:
            raise ZigzagDoesNotFit(first_bench + index + 1, t, following.length)
        t = min(max(t, 0.0), following.length)
    return _assemble(tramos, platforms, half, code, platform_m)


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
    found = build_zigzag([_ccw(item.vertices) - origin for item in chosen_feet], point, z_first_m=first.z_m, rise_m=rise,
                         gradient_pct=ramp.gradient_pct, width_m=width, platform_m=platform, sense=ramp.sense, code=ramp.code,
                         first_bench=first.bench)
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
