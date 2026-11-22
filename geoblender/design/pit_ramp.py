# SPDX-License-Identifier: GPL-3.0-or-later
"""La rampa en espiral de la corta (spec 018, T15; HU-018-3; RF-018-16, RF-018-25; CE-018-05; plan 018 §5.4 A8, §5.7 P-15, §5.9).

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

Las funciones por banco (:func:`build_tramo`, :func:`edge_extra_m`, :func:`chain_start`) trabajan en **el marco de coordenadas que se les
dé** (locales o absolutas, el mismo para el anillo, el punto y el tramo) con anillos antihorarios y abiertos, como el desfase de la corta;
:func:`spiral_steps` encadena los bancos de unos :class:`~design.pit_bench.Benches` ya calculados. Python puro con numpy (nivel 8); no lo
importa el arranque.
"""

from __future__ import annotations

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
    "build_tramo",
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
