# SPDX-License-Identifier: GPL-3.0-or-later
"""Desfase de una polilínea cerrada con distancia por arista: simplificar, curva cruda y
desfase completo (spec 018, RF-018-10; plan 018 §5.4 A1, A3 y A4, P-2 y P-3).

Geometría plana genérica (la usarán la corta, R-49 y R-61), solo numpy. Los anillos son arrays
``(k, 2)`` float64 **abiertos** (sin repetir el primer vértice) en coordenadas locales, cerca del
origen: restar un origen cercano es exacto (lema de Sterbenz) y el float64 solo basta ahí
(ADR-0005). Un anillo de entrada solo se lee.

- :func:`simplify_ring`: Douglas–Peucker en anillo (el anillo se parte en el vértice más lejano
  del primero); ningún vértice quitado queda a más de la tolerancia del anillo resultante.
- :func:`raw_offset`: la **curva cruda** del desfase, con una distancia por arista. Con el giro
  ``Δ`` entre las normales de las dos aristas de un vértice y el ``paso`` del arco (tal que un
  polígono circunscrito de ese paso queda a ``tol`` de la circunferencia): si ``|Δ| < paso``, **un
  solo punto, el inglete** (así un desfase no duplica los vértices en cada pasada: trampa T-1 del
  plan); si no, y el giro abre el lado del desfase, un **abanico de arcos circunscritos**
  (el extremo de cada arista y un vértice por sector a ``d / cos(δ/2)``: el error es de un solo
  signo, ``d ≤ distancia ≤ d + tol``); si no abre, los **dos extremos** de las aristas (se
  cruzarán y los quitará la regla de la vuelta). Con ``corner = "miter"``, siempre el inglete,
  con el límite de 4·d para los giros agudos. Todo vectorizado.
- :func:`closing`: cierre morfológico (D-15, dilatar y erosionar): **solo ensancha**, nunca
  abre. Compone dos desfases con el que se le pase (por defecto, la curva cruda).

- :func:`offset_ring_steps`: el **desfase completo** (T07, plan §5.4 A4; T09b, S-1 b), por pasos,
  por **unión de losas**: el desfase es el borde de ``P ∪ losas`` (fuera) o ``P ∖ losas``
  (dentro), con ``P`` el polígono de la fuente y las losas, polígonos convexos que son el entorno
  de cada arista a su distancia (un rectángulo del lado del desfase por arista, un sector de arcos
  circunscritos en cada vértice que abre el lado con la misma distancia a los dos lados, y el
  círculo de la mayor distancia donde esta cambia: la tapa que la curva cruda recortaba). Los
  lados que dos losas comparten se quitan, se buscan los cruces de los demás (``crossings``,
  insertados con ``splice``), cada trozo se clasifica por su punto medio (dentro de otra losa o
  de ``P`` o no) y los que quedan se encadenan (``chain``) en anillos; los de menos de 1 mm² se
  descartan y uno de área negativa es un hueco. Se **verifica** (:func:`check_offset`): simple y
  cada vértice a ``≥ d_j − tol − simplify`` de **cada** arista ``j`` de la fuente; si no,
  ``verified = False`` con el lugar y el defecto: nunca un resultado dudoso en silencio.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import closing as closing_generator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from .polygons import box_pairs, chain, crossings, drain, expand, following, ray_counts, splice

__all__ = [
    "CORNERS",
    "EDGES_PER_STEP",
    "MITER_LIMIT",
    "OffsetResult",
    "RawCurve",
    "arc_step",
    "check_offset",
    "check_offset_steps",
    "closing",
    "offset_ring",
    "offset_ring_steps",
    "raw_offset",
    "simplify_ring",
]

CORNERS = ("round", "miter")
"""Las esquinas del desfase: redondeadas (arcos circunscritos) o a inglete."""

MITER_LIMIT = 4.0
"""Longitud máxima del inglete, en veces la distancia: más allá, los dos extremos de las aristas."""

_PARALLEL = 1e-9
"""Seno del giro por debajo del cual dos aristas se toman por paralelas."""

_SAME_M = 1e-12
"""Diferencia (m) de dos distancias que se toma por cero."""

EDGES_PER_STEP = 2000
"""Aristas que se tratan entre dos cesiones (un ``Progress``) de :func:`offset_ring_steps`."""

MIN_AREA_M2 = 1e-6
"""Área (m²) por debajo de la cual un anillo del resultado se descarta (D-14: 1 mm²)."""

MERGE_M = 1e-9
"""Distancia (m) a la que dos vértices seguidos de la curva cruda se funden: un arco que colapsa
(un desfase hacia dentro del mismo radio que un arco) deja decenas de trozos de 1e-17 m cuya
vuelta no tiene sentido."""

TOUCH_M = 1e-9
"""Distancia (m) a la que un vértice de la curva cruda se toma por sobre una arista que no es suya."""

PROBE_M = 1e-6
"""Separación (m) del punto de prueba de la vuelta a cada lado de un trozo."""

_VERIFY_SLACK_M = 1e-9
"""Holgura numérica (m) de la verificación de distancias."""

MIN_DISTANCE_M = 1e-6
"""Distancia mínima (m) de una losa: una arista con distancia 0 se trata como esta (si todas son 0, el
resultado es la propia fuente)."""

STRAIGHT_M = 1e-9
"""Distancia (m) a la que un vértice del resultado se toma por alineado con sus vecinos y se quita."""

_STRAIGHT = 1e-7
"""Seno del giro por debajo del cual dos aristas de la misma distancia comparten los extremos de sus
rectángulos (se toman por rectas)."""

_EDGE_M = 1e-9
"""Distancia (m) a la que un punto se toma por sobre el borde de una losa."""

_SLAB_FACTOR = 6
"""Lados de losa por arista de la fuente: un bloque de ``edges_per_step`` aristas son tantos lados."""

_PHASE = "gis.offset"

Offset = Callable[[np.ndarray, float, int], np.ndarray]
"""Un desfase de un anillo: ``(anillo, distancia, lado) -> anillo`` (lado ``+1`` fuera, ``-1`` dentro)."""


@dataclass(frozen=True, slots=True, eq=False)
class RawCurve:
    """La curva cruda de :func:`raw_offset`: sus vértices ``(m, 2)`` y, de cada uno, la arista de
    origen (el índice del vértice que la empieza) de la que sale."""

    points: np.ndarray
    source_edge: np.ndarray


def arc_step(distance_max: float, tol: float) -> float:
    """El paso angular (rad) de un arco circunscrito a una circunferencia de radio
    ``distance_max``: el vértice de un polígono tangente de ese paso queda a ``tol`` de ella
    (``d / cos(paso / 2) = d + tol``)."""
    if not distance_max > 0.0 or not tol > 0.0:
        raise ValueError(f"Distancia y tolerancia de arco deben ser positivas: {distance_max}, {tol}")
    return 2.0 * math.acos(distance_max / (distance_max + tol))


# Simplificar ---------------------------------------------------------------------------------


def _ring(ring: object) -> np.ndarray:
    points = np.asarray(ring, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        raise ValueError(f"Un anillo son al menos 3 vértices (k, 2), no {points.shape}")
    if not np.all(np.isfinite(points)):
        raise ValueError("El anillo tiene coordenadas no finitas")
    return points


def _distance_to_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = b - a
    length2 = float(d @ d)
    w = p - a
    if length2 == 0.0:
        return np.hypot(w[:, 0], w[:, 1])
    t = np.clip((w @ d) / length2, 0.0, 1.0)
    return np.hypot(w[:, 0] - t * d[0], w[:, 1] - t * d[1])


def simplify_ring(ring: object, tol: float) -> np.ndarray:
    """Douglas–Peucker de un anillo abierto: el anillo se parte en el vértice más lejano del
    primero y cada mitad se simplifica. Ningún vértice quitado queda a más de ``tol`` del
    resultado (distancia al segmento). Con ``tol <= 0``, una copia. El orden y el sentido se
    conservan; el resultado tiene al menos tres vértices."""
    points = _ring(ring)
    count = len(points)
    if not tol > 0.0 or count <= 3:
        return points.copy()
    far = int(np.argmax(np.hypot(points[:, 0] - points[0, 0], points[:, 1] - points[0, 1])))
    closed = np.vstack([points, points[:1]])
    keep = np.zeros(count, dtype=bool)
    keep[0] = keep[far] = True
    stack = [(0, far), (far, count)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        dist = _distance_to_segment(closed[first + 1:last], closed[first], closed[last])
        at = int(np.argmax(dist))
        if dist[at] > tol:
            middle = first + 1 + at
            keep[middle] = True
            stack.append((first, middle))
            stack.append((middle, last))
    if int(keep.sum()) < 3:
        dist = _distance_to_segment(points, points[0], points[far])
        dist[[0, far]] = -1.0
        keep[int(np.argmax(dist))] = True
    return points[keep]


# Curva cruda ---------------------------------------------------------------------------------


def raw_offset(ring: object, distance: object, *, tol: float, side: int = 1,
               corner: str = "round") -> RawCurve:
    """La curva cruda del desfase de un anillo abierto con una distancia por arista.

    ``distance`` es un escalar o un array ``(k,)`` con la distancia (m, ≥ 0) de la arista que
    sale de cada vértice. ``side`` es ``+1`` hacia el lado derecho de la marcha (hacia fuera en
    un anillo antihorario) o ``-1`` hacia el izquierdo. ``tol`` es la tolerancia de arco (m).
    Devuelve los vértices y la arista de origen de cada uno (:class:`RawCurve`)."""
    points = _ring(ring)
    count = len(points)
    if side not in (1, -1):
        raise ValueError(f"El lado es +1 o -1, no {side!r}")
    if corner not in CORNERS:
        raise ValueError(f"La esquina es una de {CORNERS}, no {corner!r}")
    if not tol > 0.0:
        raise ValueError(f"La tolerancia de arco debe ser positiva: {tol}")
    dist = np.broadcast_to(np.asarray(distance, dtype=np.float64), (count,)).copy()
    if not np.all(np.isfinite(dist)) or np.any(dist < 0.0):
        raise ValueError("Las distancias del desfase deben ser finitas y no negativas")
    along = np.roll(points, -1, axis=0) - points
    length = np.hypot(along[:, 0], along[:, 1])
    if np.any(length == 0.0):
        raise ValueError("El anillo tiene una arista de longitud 0 (simplifícalo antes)")
    tangent = along / length[:, None]
    normal = side * np.column_stack([tangent[:, 1], -tangent[:, 0]])
    d_max = float(dist.max())
    index = np.arange(count, dtype=np.int64)
    if d_max == 0.0:
        return RawCurve(points.copy(), index)

    n_prev, n_next = np.roll(normal, 1, axis=0), normal
    d_prev, d_next = np.roll(dist, 1), dist
    cross = n_prev[:, 0] * n_next[:, 1] - n_prev[:, 1] * n_next[:, 0]
    dot = np.einsum("ij,ij->i", n_prev, n_next)
    delta = np.arctan2(cross, dot)
    step = arc_step(d_max, tol)
    opens = side * delta > 0.0

    # El inglete: el punto a d_prev de la recta anterior y a d_next de la siguiente.
    well = np.abs(cross) > _PARALLEL
    safe = np.where(well, cross, 1.0)
    miter = np.column_stack([(d_prev * n_next[:, 1] - d_next * n_prev[:, 1]) / safe,
                             (n_prev[:, 0] * d_next - n_next[:, 0] * d_prev) / safe])
    same = (np.abs(d_prev - d_next) <= _SAME_M) & (dot > 0.0)
    straight = ~well & same
    miter[straight] = n_prev[straight] * d_prev[straight, None]
    reach = np.hypot(miter[:, 0], miter[:, 1])
    usable = (well | straight) & (reach <= MITER_LIMIT * np.maximum(d_prev, d_next) + _SAME_M)

    single = usable & ((np.abs(delta) < step) | (corner == "miter"))
    fan = ~single & opens & (corner == "round")
    arcs = np.maximum(np.ceil(np.abs(delta) / step).astype(np.int64), 1)
    number = np.where(single, 1, np.where(fan, 2 + arcs, 2))

    owner, k = expand(number)
    out_count = number[owner]
    base = points[owner]
    is_single = out_count == 1
    last = (out_count > 1) & (k == out_count - 1)
    first = (out_count > 1) & (k == 0)
    middle = (out_count > 2) & ~first & ~last

    out = np.empty((len(owner), 2), dtype=np.float64)
    source = np.empty(len(owner), dtype=np.int64)
    out[is_single] = base[is_single] + miter[owner[is_single]]
    source[is_single] = owner[is_single]
    out[first] = base[first] + n_prev[owner[first]] * d_prev[owner[first], None]
    source[first] = (owner[first] - 1) % count
    out[last] = base[last] + n_next[owner[last]] * d_next[owner[last], None]
    source[last] = owner[last]
    if middle.any():
        v, j, m = owner[middle], k[middle], arcs[owner[middle]]
        theta = np.arctan2(n_prev[v, 1], n_prev[v, 0]) + (j - 0.5) * delta[v] / m
        early = (j - 0.5) < m / 2.0
        radius = np.where(early, d_prev[v], d_next[v]) / np.cos(np.abs(delta[v]) / (2.0 * m))
        out[middle] = base[middle] + radius[:, None] * np.column_stack([np.cos(theta), np.sin(theta)])
        source[middle] = np.where(early, (v - 1) % count, v)
    return RawCurve(out, source)


# Desfase completo -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class OffsetResult:
    """El desfase completo de :func:`offset_ring_steps`.

    ``rings`` son los contornos (antihorarios) y ``holes`` los huecos (horarios), arrays
    ``(k, 2)`` abiertos. ``source_edge_of_vertex`` tiene un array por cada anillo y después uno
    por cada hueco: la arista de la fuente (el índice de su vértice inicial) de la que sale cada
    vértice. ``verified`` es verdadero si el resultado es simple y está a la distancia que toca
    de la fuente (:func:`check_offset`); si no, ``defect_at`` es el lugar, ``defect`` el qué
    (``"crossing"`` o ``"distance"``) y ``max_defect_m`` lo que le falta de distancia (m)."""

    rings: tuple[np.ndarray, ...]
    holes: tuple[np.ndarray, ...]
    source_edge_of_vertex: tuple[np.ndarray, ...]
    verified: bool
    max_defect_m: float
    defect_at: tuple[float, float] | None = None
    defect: str = ""


def _signed_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _blocks(count: int, size: int) -> range:
    return range(0, count, size)


def offset_ring_steps(ring: object, distance: object, side: int = 1, *, tol: float,
                      corner: str = "round", simplify_m: float = 0.0,
                      edges_per_step: int = EDGES_PER_STEP) -> Iterator[Progress]:
    """Los pasos del desfase completo de un anillo antihorario abierto ``ring`` (``(k, 2)``,
    sin aristas de longitud 0: simplifícalo antes), con la distancia ``distance`` (escalar o
    ``(k,)``, por arista) hacia el ``side`` ``+1`` (fuera) o ``-1`` (dentro). Cede un
    ``Progress`` cada ≈ ``edges_per_step`` aristas tratadas; el último lleva el
    :class:`OffsetResult` en ``result``. Cerrar el iterador cancela sin dejar nada.
    ``simplify_m`` es lo que el anillo pudo moverse al simplificarlo (holgura de la
    verificación). ``ValueError`` si un argumento no vale."""
    points = _ring(ring)
    if not _signed_area(points) > 0.0:
        raise ValueError("El anillo del desfase debe ser antihorario y con área")
    if edges_per_step < 1:
        raise ValueError(f"Las aristas por paso deben ser al menos 1: {edges_per_step}")
    if np.any(np.all(np.roll(points, -1, axis=0) == points, axis=1)):
        raise ValueError("El anillo tiene una arista de longitud 0 (simplifícalo antes)")
    if side not in (1, -1):
        raise ValueError(f"El lado es +1 o -1, no {side!r}")
    if corner not in CORNERS:
        raise ValueError(f"La esquina es una de {CORNERS}, no {corner!r}")
    if not tol > 0.0:
        raise ValueError(f"La tolerancia de arco debe ser positiva: {tol}")
    dist = np.broadcast_to(np.asarray(distance, dtype=np.float64), (len(points),)).copy()
    if not np.all(np.isfinite(dist)) or np.any(dist < 0.0):
        raise ValueError("Las distancias del desfase deben ser finitas y no negativas")
    return _paced(_offset_work(points, dist, side, tol, corner, simplify_m, edges_per_step))


def offset_ring(ring: object, distance: object, side: int = 1, *, tol: float,
                corner: str = "round", simplify_m: float = 0.0) -> OffsetResult:
    """:func:`offset_ring_steps` de una vez."""
    result: object = None
    for step in offset_ring_steps(ring, distance, side, tol=tol, corner=corner,
                                  simplify_m=simplify_m):
        result = step.result
    assert isinstance(result, OffsetResult)
    return result


def _paced(work: Generator[int, None, OffsetResult]) -> Iterator[Progress]:
    done = 0
    with closing_generator(work):  # cerrar los pasos cierra el trabajo
        while True:
            try:
                done += next(work)
            except StopIteration as stop:
                result = stop.value
                break
            yield Progress(_PHASE, done, done + 1, "Desfasando…")
    yield Progress(_PHASE, max(done, 1), max(done, 1), "Desfase hecho", result=result)


def _step_of(radius: np.ndarray, tol: float) -> np.ndarray:
    """:func:`arc_step` de cada radio (vectorizado)."""
    return 2.0 * np.arccos(radius / (radius + tol))


@dataclass(frozen=True, slots=True, eq=False)
class _Discs:
    """Los círculos de las losas, que son los últimos polígonos: el índice del primero, y de cada uno
    el centro, el radio (la apotema) y el paso angular. Un polígono regular circunscrito tiene los
    lados a ``k·paso``, y la distancia de un punto a su interior sale sin recorrer los lados."""

    first: int
    centre: np.ndarray
    radius: np.ndarray
    share: np.ndarray


def _slabs(points: np.ndarray, dist: np.ndarray, side: int, tol: float, corner: str
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, _Discs]:
    """Las **losas** del desfase (plan §5.4 A4, S-1 b): polígonos convexos antihorarios cuya unión
    es el entorno de la fuente a la distancia de cada arista (la unión de las cápsulas de cada
    arista: la arista engrosada ``d`` a cada lado y un círculo de radio ``d`` en cada extremo).
    Devuelve los vértices de todos, el polígono de cada vértice (bloques seguidos), la arista de
    la fuente de la que sale cada vértice, si el lado que sale de él va por la fuente y los
    círculos (:class:`_Discs`, los últimos polígonos). Son:

    - un **rectángulo** por arista, del lado del desfase (``d`` de ancho);
    - en cada vértice con la misma distancia a los dos lados y que abre el lado del desfase, un
      **sector** de arcos circunscritos (un solo punto, el inglete, si el giro es menor que el
      paso del arco: así un desfase no duplica los vértices en cada pasada, T-1); si no abre, nada;
    - en cada vértice con distinta distancia a los dos lados, un **círculo** (polígono
      circunscrito) de la mayor: la tapa de la arista más lejana, que el desfase de una sola
      curva recortaba (T09)."""
    count = len(points)
    forward = np.roll(points, -1, axis=0) - points
    length = np.hypot(forward[:, 0], forward[:, 1])
    if np.any(length == 0.0):
        raise ValueError("El anillo tiene una arista de longitud 0 (simplifícalo antes)")
    tangent = forward / length[:, None]
    normal = side * np.column_stack([tangent[:, 1], -tangent[:, 0]])
    index = np.arange(count, dtype=np.int64)
    n_prev, n_next = np.roll(normal, 1, axis=0), normal
    d_prev, d_next = np.roll(dist, 1), dist
    cross = n_prev[:, 0] * n_next[:, 1] - n_prev[:, 1] * n_next[:, 0]
    dot = np.einsum("ij,ij->i", n_prev, n_next)
    delta = np.arctan2(cross, dot)
    same = np.abs(d_prev - d_next) <= _SAME_M * np.maximum(1.0, d_next)
    straight = same & (np.abs(cross) <= _STRAIGHT) & (dot > 0.0)
    fan = same & ~straight & (side * delta > 0.0)
    disc = ~same
    radius = np.maximum(d_prev, d_next)
    step = _step_of(radius, tol)

    # Rectángulos: solo del lado del desfase (el otro cae dentro o fuera de la fuente); en un
    # vértice recto, los mismos extremos. El lado que va por la arista de la fuente se anota.
    a, b = points, np.roll(points, -1, axis=0)
    a_off = a + dist[:, None] * normal
    b_off = b + dist[:, None] * normal
    a_off = np.where(straight[:, None], np.roll(b_off, 1, axis=0), a_off)
    if side > 0:
        rect = np.stack([a, a_off, b_off, b], axis=1)
        flag = np.tile(np.array([False, False, False, True]), count)
    else:
        rect = np.stack([a, b, b_off, a_off], axis=1)
        flag = np.tile(np.array([True, False, False, False]), count)
    out_points = [rect.reshape(-1, 2)]
    out_poly = [np.repeat(index, 4)]
    out_source = [np.repeat(index, 4)]
    out_flag = [flag]
    made = count

    fans = np.flatnonzero(fan)
    if fans.size:
        arcs = np.maximum(np.ceil(np.abs(delta[fans]) / step[fans]).astype(np.int64), 1)
        if corner == "miter":
            arcs = np.ones_like(arcs)
        size = arcs + 3
        owner, k = expand(size)
        v = fans[owner]
        m = arcs[owner]
        sign = np.where(delta[v] > 0.0, 1.0, -1.0)
        # Orden antihorario: el vértice, el extremo de la arista anterior, los puntos del arco y
        # el extremo de la siguiente; al revés si el giro es horario.
        position = np.where(delta[v] > 0.0, k, size[owner] - 1 - k)
        d = d_next[v]
        theta = np.arctan2(n_prev[v, 1], n_prev[v, 0])
        share = np.abs(delta[v]) / m
        angle = theta + sign * (position - 1.5) * share
        reach = d / np.cos(share / 2.0)
        base = points[v]
        out = base + reach[:, None] * np.column_stack([np.cos(angle), np.sin(angle)])
        out[position == 0] = base[position == 0]
        first = position == 1
        out[first] = base[first] + d[first, None] * n_prev[v[first]]
        last = position == m + 2
        out[last] = base[last] + d[last, None] * n_next[v[last]]
        origin = np.where(position <= (m + 2) / 2.0, (v - 1) % count, v)
        out_points.append(out)
        out_poly.append(made + owner)
        out_source.append(origin)
        out_flag.append(np.zeros(len(out), dtype=bool))
        made += fans.size

    discs = np.flatnonzero(disc)
    found = _Discs(made, np.zeros((0, 2)), np.zeros(0), np.zeros(0))
    if discs.size:
        total = np.maximum(np.ceil(2.0 * math.pi / step[discs]).astype(np.int64), 3)
        owner, k = expand(total)
        v = discs[owner]
        share = 2.0 * math.pi / total[owner]
        angle = (k + 0.5) * share
        reach = radius[v] / np.cos(share / 2.0)
        out = points[v] + reach[:, None] * np.column_stack([np.cos(angle), np.sin(angle)])
        out_points.append(out)
        out_poly.append(made + owner)
        out_source.append(np.where(d_prev[v] > d_next[v], (v - 1) % count, v))
        out_flag.append(np.zeros(len(out), dtype=bool))
        found = _Discs(made, points[discs], radius[discs], 2.0 * math.pi / total)
        made += discs.size
    return (np.concatenate(out_points), np.concatenate(out_poly), np.concatenate(out_source),
            np.concatenate(out_flag), found)


def _depth(points: np.ndarray, which: np.ndarray, vertices: np.ndarray, start: np.ndarray,
           size: np.ndarray) -> np.ndarray:
    """La distancia con signo de cada punto ``points[k]`` al interior del polígono convexo
    antihorario ``which[k]`` (la menor de las distancias a la recta de cada lado: positiva dentro)."""
    if not len(points):
        return np.zeros(0)
    n = size[which]
    owner, k = expand(n)
    first = start[which][owner]
    a = vertices[first + k]
    d = vertices[first + (k + 1) % n[owner]] - a
    w = points[owner] - a
    long = np.hypot(d[:, 0], d[:, 1])
    with np.errstate(divide="ignore", invalid="ignore"):
        inner = (d[:, 0] * w[:, 1] - d[:, 1] * w[:, 0]) / long
    inner = np.where(long > 0.0, inner, np.inf)
    return np.minimum.reduceat(inner, np.cumsum(n) - n)


def _frame(points: np.ndarray, dist: np.ndarray, side: int
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """El marco de cada rectángulo: su origen, la tangente, la normal hacia el lado del desfase, el
    largo y la distancia."""
    forward = np.roll(points, -1, axis=0) - points
    length = np.hypot(forward[:, 0], forward[:, 1])
    tangent = forward / length[:, None]
    normal = side * np.column_stack([tangent[:, 1], -tangent[:, 0]])
    return points, tangent, normal, length, dist


def _slab_depth(points: np.ndarray, which: np.ndarray, rects: int,
                frame: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
                circle: tuple[np.ndarray, np.ndarray], vertices: np.ndarray, start: np.ndarray,
                size: np.ndarray, discs: _Discs) -> np.ndarray:
    """:func:`_depth` de cada punto a su losa; los rectángulos (los ``rects`` primeros), con sus
    dos proyecciones y no con sus cuatro lados, y los demás, fuera de su círculo envolvente, ``-1``
    (fuera), sin recorrer sus lados."""
    out = np.empty(len(points))
    is_rect = which < rects
    r = np.flatnonzero(is_rect)
    if r.size:
        origin, tangent, normal, length, wide = frame
        e = which[r]
        w = points[r] - origin[e]
        along = w[:, 0] * tangent[e, 0] + w[:, 1] * tangent[e, 1]
        across = w[:, 0] * normal[e, 0] + w[:, 1] * normal[e, 1]
        out[r] = np.minimum(np.minimum(along, length[e] - along), np.minimum(across, wide[e] - across))
    is_disc = which >= discs.first
    c = np.flatnonzero(is_disc)
    if c.size:
        e = which[c] - discs.first
        w = points[c] - discs.centre[e]
        reach = np.hypot(w[:, 0], w[:, 1])
        angle = np.arctan2(w[:, 1], w[:, 0])
        share = discs.share[e]
        out[c] = discs.radius[e] - reach * np.cos(angle - np.round(angle / share) * share)
    o = np.flatnonzero(~is_rect & ~is_disc)
    if o.size:
        centre, radius = circle
        out[o] = -1.0
        near = o[np.hypot(*(points[o] - centre[which[o]]).T) < radius[which[o]]]
        if near.size:
            out[near] = _depth(points[near], which[near], vertices, start, size)
    return out


def _offset_work(points: np.ndarray, dist: np.ndarray, side: int, tol: float, corner: str,
                 simplify_m: float, block: int) -> Generator[int, None, OffsetResult]:
    """El trabajo de :func:`offset_ring_steps`: cede el número de bloques tratados.

    El resultado es el borde de ``P ∪ losas`` (fuera) o de ``P ∖ losas`` (dentro), ``P`` el
    polígono de la fuente: solo se buscan los cruces de los lados de las losas que no están
    claramente dentro de otra, cada trozo se clasifica por un punto de prueba a su derecha (la
    izquierda es siempre su losa) y se encadenan los que quedan."""
    count = len(points)
    if not float(dist.max()) > 0.0:
        return OffsetResult((points.copy(),), (), (np.arange(count, dtype=np.int64),), True, 0.0)
    eff = np.maximum(dist, MIN_DISTANCE_M)
    verts, poly, vsource, on_source, discs = _slabs(points, eff, side, tol, corner)
    total = len(verts)
    nxt = following(poly)
    size = np.bincount(poly)
    start = np.cumsum(size) - size
    poly_boxes = np.concatenate([np.minimum.reduceat(verts, start, axis=0),
                                 np.maximum.reduceat(verts, start, axis=0)], axis=1)
    chunk = max(block, 1) * _SLAB_FACTOR
    src_a, src_b = points, np.roll(points, -1, axis=0)
    frame = _frame(points, eff, side)
    centre = 0.5 * (poly_boxes[:, :2] + poly_boxes[:, 2:])
    circle = (centre, np.maximum.reduceat(np.hypot(*(verts - centre[poly]).T), start) * (1.0 + 1e-9))

    # (1) Los lados que dos losas comparten (el mismo en sentidos opuestos: lo de los dos lados es
    # interior) o que van por la fuente no son borde; de dos iguales y en el mismo sentido, uno.
    _, ident = np.unique(verts, axis=0, return_inverse=True)
    ident = ident.reshape(-1)
    forward = ident * total + ident[nxt]
    backward = ident[nxt] * total + ident
    skip = on_source | (ident == ident[nxt]) | np.isin(forward, backward)
    _, first_one = np.unique(np.where(skip, -1 - np.arange(total), forward), return_index=True)
    twin = np.ones(total, dtype=bool)
    twin[first_one] = False
    skip |= twin
    # Un lado cuyos dos extremos están dentro de otra misma losa (convexa) va por dentro de ella: no
    # es borde ni cruza el borde de la unión (que son lados que quedan), y no hace falta partirlo.
    known: list[np.ndarray] = []
    for low in _blocks(total, chunk):
        part = verts[low:low + chunk]
        k, q = box_pairs(np.concatenate([part, part], axis=1), poly_boxes)
        keep = q != poly[low + k]
        k, q = k[keep], q[keep]
        deep = _slab_depth(part[k], q, count, frame, circle, verts, start, size, discs) > _EDGE_M
        k, q = k[deep], q[deep]
        if k.size:
            pairs = (low + k).astype(np.int64) * len(size) + q
            known.append(pairs)
        yield 1
    if known:
        inner = np.concatenate(known)
        vertex_of, slab_of = inner // len(size), inner % len(size)
        ahead = nxt[vertex_of].astype(np.int64) * len(size) + slab_of
        skip[vertex_of[np.isin(ahead, inner)]] = True
    live = np.flatnonzero(~skip)
    a_live, b_live = verts[live], verts[nxt[live]]
    edge_boxes = np.concatenate([np.minimum(a_live, b_live), np.maximum(a_live, b_live)], axis=1)

    # (2) Cruces entre los lados que quedan y con los de la fuente, y vértices sobre un lado (un
    # extremo que toca otro lado: hay que partirlo ahí, o el trozo cambia de lado a medias).
    cut_edge: list[np.ndarray] = []
    cut_at: list[np.ndarray] = []
    cut_point: list[np.ndarray] = []
    for low in _blocks(len(live), chunk):
        part = slice(low, min(low + chunk, len(live)))
        i, j, t, u, cut = crossings(a_live[part], b_live[part], a_live, b_live)
        i = i + low
        keep = i < j
        cut_edge += [live[i[keep]], live[j[keep]]]
        cut_at += [t[keep], u[keep]]
        cut_point += [cut[keep], cut[keep]]
        i, _, t, _, cut = crossings(a_live[part], b_live[part], src_a, src_b)
        cut_edge.append(live[i + low])
        cut_at.append(t)
        cut_point.append(cut)
        yield 1
    touching = np.concatenate([a_live, points])
    for low in _blocks(len(touching), chunk):
        part = touching[low:low + chunk]
        v, e = box_pairs(np.concatenate([part - TOUCH_M, part + TOUCH_M], axis=1), edge_boxes)
        if v.size:
            along = b_live[e] - a_live[e]
            at = part[v]
            t = np.einsum("ij,ij->i", at - a_live[e], along) / np.einsum("ij,ij->i", along, along)
            off = at - (a_live[e] + t[:, None] * along)
            touch = ((np.hypot(off[:, 0], off[:, 1]) < TOUCH_M)
                     & (np.hypot(*(at - a_live[e]).T) > TOUCH_M)
                     & (np.hypot(*(at - b_live[e]).T) > TOUCH_M))
            cut_edge.append(live[e[touch]])
            cut_at.append(t[touch])
            cut_point.append(at[touch])
        yield 1
    joined, vertex = splice(verts, np.arange(total, dtype=np.int64),
                            np.concatenate(cut_edge) if cut_edge else np.zeros(0, dtype=np.int64),
                            np.concatenate(cut_at) if cut_at else np.zeros(0),
                            np.concatenate(cut_point) if cut_point else np.zeros((0, 2)))
    joined = _merged(joined, MERGE_M)
    yield 1
    follow = following(poly[vertex])
    keep_piece = (~skip[vertex]) & np.any(joined != joined[follow], axis=1)
    pick = np.flatnonzero(keep_piece)
    begin, end = joined[pick], joined[follow[pick]]
    owner = vsource[vertex[pick]]

    # (3) Cada trozo (menos los que van por la fuente), por su punto medio: dentro de otra losa, o
    # de la fuente, o no. Un trozo no cruza el borde de otra losa (se partió en los cruces), salvo
    # que vaya por él: ahí se mira un punto a su derecha.
    own = poly[vertex[pick]]
    along = end - begin
    long = np.hypot(along[:, 0], along[:, 1])
    mid = 0.5 * (begin + end)
    right = np.column_stack([along[:, 1], -along[:, 0]]) / long[:, None]
    covered = np.zeros(len(mid), dtype=bool)
    winding = np.zeros(len(mid), dtype=np.int64)
    on_border = np.zeros(len(mid), dtype=bool)
    group = (src_b[:, 1] <= src_a[:, 1]).astype(np.int64)
    for low in _blocks(len(mid), chunk):
        part = slice(low, min(low + chunk, len(mid)))
        k, q = box_pairs(np.concatenate([mid[part] - _EDGE_M, mid[part] + _EDGE_M], axis=1),
                         poly_boxes)
        other = q != own[part][k]
        k, q = k[other], q[other]
        depth = _slab_depth(mid[part][k], q, count, frame, circle, verts, start, size, discs)
        covered[part] = np.bincount(k[depth > _EDGE_M], minlength=part.stop - part.start) > 0
        edge = np.unique(k[np.abs(depth) <= _EDGE_M])
        if edge.size:  # va por el borde de otra losa: un punto a su derecha
            probe = mid[part][edge] + PROBE_M * right[part][edge]
            kk, qq = box_pairs(np.concatenate([probe, probe], axis=1), poly_boxes)
            hit = ((_slab_depth(probe[kk], qq, count, frame, circle, verts, start, size, discs) > 0.0)
                   & (qq != own[part][edge][kk]))
            covered[low + edge] = np.bincount(kk[hit], minlength=len(edge)) > 0
        turns = ray_counts(mid[part], src_a, src_b, group, 2)
        winding[part] = turns[:, 0] - turns[:, 1]
        yield 1
    # Un trozo que va por el borde de la fuente (el lado perpendicular de un rectángulo en una
    # esquina, o el de otra losa con vértices alineados) no es nunca el desfase (d > 0): lo que
    # dice el rayo desde un punto sobre el borde es arbitrario.
    edge_boxes_src = np.concatenate([np.minimum(src_a, src_b), np.maximum(src_a, src_b)], axis=1)
    for low in _blocks(len(mid), chunk):
        part = mid[low:low + chunk]
        k, e = box_pairs(np.concatenate([part - _EDGE_M, part + _EDGE_M], axis=1), edge_boxes_src)
        if k.size:
            near = _point_edge_distance(part[k], src_a[e], src_b[e]) <= _EDGE_M
            on_border[low + k[near]] = True
        yield 1
    in_source = winding == 1
    if side > 0:
        border = ~(covered | in_source)
    else:
        border = in_source & ~covered
    border &= ~on_source[vertex[pick]] & ~on_border
    begin, end, owner = begin[border], end[border], owner[border]
    if side < 0:
        begin, end = end, begin
    pieces = np.stack([begin, end], axis=1)
    if len(pieces):
        _, first = np.unique(pieces.reshape(-1, 4), axis=0, return_index=True)
        first.sort()
        pieces, owner = pieces[first], owner[first]

    from_edge = {(x + 0.0, y + 0.0): int(o)
                 for (x, y), o in zip(pieces[:, 0].tolist(), owner.tolist(), strict=True)}
    rings: list[np.ndarray] = []
    holes: list[np.ndarray] = []
    ring_sources: list[np.ndarray] = []
    hole_sources: list[np.ndarray] = []
    for loop in chain(pieces):
        loop = _straight(loop)
        area = _signed_area(loop)
        if abs(area) < MIN_AREA_M2:
            continue
        sources = np.array([from_edge[(x + 0.0, y + 0.0)] for x, y in loop.tolist()],
                           dtype=np.int64)
        if area > 0.0:
            rings.append(loop)
            ring_sources.append(sources)
        else:
            holes.append(loop)
            hole_sources.append(sources)
    loops, sources_all = rings + holes, ring_sources + hole_sources
    ok, defect_at, defect, worst = yield from check_offset_steps(
        points, dist, loops, sources_all, tol=tol, simplify_m=simplify_m, block=block)
    return OffsetResult(tuple(rings), tuple(holes), tuple(sources_all), ok, worst, defect_at,
                        defect)


def _merged(points: np.ndarray, radius: float) -> np.ndarray:
    """Los puntos a ``radius`` o menos unos de otros, todos el mismo (el de menor índice de su
    grupo): un arco que colapsa deja decenas de cruces en un punto que el cálculo da por separado,
    y los trozos de 1e-17 m entre ellos no encadenan."""
    order = np.argsort(points[:, 0], kind="stable")
    xs = points[order, 0]
    ahead = np.searchsorted(xs, xs + radius, side="right") - np.arange(len(xs)) - 1
    first, k = expand(np.maximum(ahead, 0))
    i = order[first]
    j = order[first + k + 1]
    near = np.hypot(points[i, 0] - points[j, 0], points[i, 1] - points[j, 1]) <= radius
    i, j = i[near], j[near]
    if not i.size:
        return points
    label = np.arange(len(points), dtype=np.int64)
    while True:
        low = np.minimum(label[i], label[j])
        before = label.copy()
        np.minimum.at(label, i, low)
        np.minimum.at(label, j, low)
        label = label[label]
        if np.array_equal(label, before):
            break
    return points[label]


def _straight(loop: np.ndarray) -> np.ndarray:
    """El anillo sin los vértices alineados con sus vecinos (a ≤ 1 nm de la recta que los une): las
    tangentes de los arcos y los extremos de las losas contiguas no son vértices del desfase."""
    if len(loop) <= 3:
        return loop
    before, after = np.roll(loop, 1, axis=0), np.roll(loop, -1, axis=0)
    span = after - before
    reach = np.hypot(span[:, 0], span[:, 1])
    off = span[:, 0] * (loop[:, 1] - before[:, 1]) - span[:, 1] * (loop[:, 0] - before[:, 0])
    ahead = np.einsum("ij,ij->i", loop - before, after - loop) > 0.0
    line = (np.abs(off) <= STRAIGHT_M * reach) & ahead & (reach > 0.0)
    return loop[~line] if int((~line).sum()) >= 3 else loop


def check_offset(source: object, distance: object, loops: Sequence[np.ndarray],
                 sources: Sequence[np.ndarray], *, tol: float, simplify_m: float = 0.0
                 ) -> tuple[bool, tuple[float, float] | None, str, float]:
    """:func:`check_offset_steps` de una vez."""
    return drain(check_offset_steps(source, distance, loops, sources, tol=tol,
                                    simplify_m=simplify_m))


def check_offset_steps(source: object, distance: object, loops: Sequence[np.ndarray],
                       sources: Sequence[np.ndarray], *, tol: float, simplify_m: float = 0.0,
                       block: int = EDGES_PER_STEP
                       ) -> Generator[int, None, tuple[bool, tuple[float, float] | None, str,
                                                       float]]:
    """Comprueba un desfase (plan §5.4 A4): que ``loops`` (anillos y huecos) son **simples** (ningún
    par de aristas se cruza, dentro de un anillo ni entre ellos) y que cada vértice está a ``≥ d_j −
    tol − simplify_m`` de **cada** arista ``j`` de ``source`` (``d_j`` la distancia de esa arista:
    el desfase es el borde de la unión de las cápsulas de las aristas, y la tapa de la de mayor
    distancia pasa más cerca de una vecina de menor distancia; T09b). ``sources`` (la arista de
    origen de cada vértice) ya no interviene: se conserva por compatibilidad. Da ``(verificado,
    lugar, defecto, falta)``; ``falta`` es la mayor distancia (m) que le falta a un vértice. Cede
    el número de bloques tratados."""
    src = _ring(source)
    dist = np.broadcast_to(np.asarray(distance, dtype=np.float64), (len(src),))
    if not loops:
        return True, None, "", 0.0
    a = np.concatenate(loops)
    b = np.concatenate([np.roll(loop, -1, axis=0) for loop in loops])
    for low in _blocks(len(a), block):
        part = slice(low, min(low + block, len(a)))
        i, j, _, _, cut = crossings(a[part], b[part], a, b)
        found = np.flatnonzero(i + low < j)
        if found.size:
            at = cut[int(found[0])]
            return False, (float(at[0]), float(at[1])), "crossing", 0.0
        yield 1
    # Cada vértice, a ``≥ d_j − tol − simplify_m`` de cada arista ``j`` de la fuente (la distancia
    # de la arista: el desfase es la unión de sus cápsulas, y un vértice de la tapa de la más
    # lejana puede estar más cerca de otra arista de menor distancia).
    edge_a, edge_b = src, np.roll(src, -1, axis=0)
    limit = dist - tol - simplify_m - _VERIFY_SLACK_M
    wide = np.flatnonzero(limit > 0.0)
    worst, worst_at = 0.0, None
    if wide.size:
        pad = limit[wide][:, None]
        edge_boxes = np.concatenate([np.minimum(edge_a[wide], edge_b[wide]) - pad,
                                     np.maximum(edge_a[wide], edge_b[wide]) + pad], axis=1)
        for low in _blocks(len(a), block):
            part = a[low:low + block]
            v, e = box_pairs(np.concatenate([part, part], axis=1), edge_boxes)
            if v.size:
                e = wide[e]
                gap = limit[e] - _point_edge_distance(part[v], edge_a[e], edge_b[e])
                top = int(np.argmax(gap))
                if gap[top] > worst:
                    worst = float(gap[top])
                    at = part[v[top]]
                    worst_at = (float(at[0]), float(at[1]))
            yield 1
    if worst_at is not None:
        return False, worst_at, "distance", worst
    return True, None, "", 0.0


def _point_edge_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La distancia de cada punto ``p`` a su segmento ``a–b`` (de longitud no nula)."""
    d, w = b - a, p - a
    t = np.clip((w[:, 0] * d[:, 0] + w[:, 1] * d[:, 1])
                / (d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]), 0.0, 1.0)
    return np.hypot(w[:, 0] - t * d[:, 0], w[:, 1] - t * d[:, 1])


# Cierre morfológico ----------------------------------------------------------------------------


def _raw_ring(ring: np.ndarray, distance: float, side: int, *, tol: float) -> np.ndarray:
    return raw_offset(ring, distance, tol=tol, side=side).points


def closing(ring: object, radius: float, *, tol: float, offset: Offset | None = None,
            merge_m: float = 1e-6) -> np.ndarray:
    """El cierre morfológico (D-15): dilatar ``radius`` y erosionar ``radius``. **Solo ensancha**
    (rellena entrantes más estrechos que ``2·radius``; nunca abre ni quita nada): con arcos
    circunscritos el resultado contiene al anillo. ``ring`` es antihorario. ``offset`` es el
    desfase a usar, ``(anillo, distancia, lado) -> anillo`` (``+1`` fuera, ``-1`` dentro); por
    defecto, la curva cruda, **válida solo en un anillo convexo** (en un vértice cóncavo se
    cruza); el desfase completo de la spec 018 T07 la sustituye. Los vértices a menos de ``merge_m``
    seguidos se funden (la erosión de un arco da el mismo punto varias veces)."""
    points = _ring(ring)
    if not radius > 0.0:
        raise ValueError(f"El radio del cierre debe ser positivo: {radius}")
    run: Offset = offset if offset is not None else (
        lambda r, d, s: _raw_ring(r, d, s, tol=tol))
    result = run(run(points, radius, 1), radius, -1)
    step = np.hypot(*(result - np.roll(result, 1, axis=0)).T)
    keep = step > merge_m
    return result[keep] if int(keep.sum()) >= 3 else result
