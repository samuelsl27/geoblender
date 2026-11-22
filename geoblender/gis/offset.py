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

- :func:`offset_ring_steps`: el **desfase completo** (T07, plan §5.4 A4), por pasos. La curva cruda
  puede cruzarse a sí misma: se le calculan los cruces propios una vez (``crossings``, insertados
  en las dos aristas con ``splice``), a cada trozo se le da la **vuelta a su izquierda y a su
  derecha** (número de vueltas con signo, por rayos) y se queda con los de ``(1, 0)``, que se
  encadenan por la salida más a la izquierda (``chain``) en anillos; los de menos de 1 mm² se
  descartan y uno de área negativa es un hueco. Se **verifica** (:func:`check_offset`): simple y
  cada vértice a ``≥ d − tol − simplify`` de la fuente; si no, ``verified = False`` con el lugar
  y el defecto: nunca un resultado dudoso en silencio.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import closing as closing_generator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from .polygons import box_pairs, chain, crossings, drain, expand, ray_counts, splice

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
    dist = np.broadcast_to(np.asarray(distance, dtype=np.float64), (len(points),)).copy()
    curve = raw_offset(points, dist, tol=tol, side=side, corner=corner)
    return _paced(_offset_work(points, dist, curve, tol, simplify_m, edges_per_step))


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


def _distinct(points: np.ndarray, extra: np.ndarray,
              merge_m: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Sin vértices seguidos a ``merge_m`` o menos (el último de cada serie), y su ``extra``."""
    step = np.roll(points, -1, axis=0) - points
    keep = np.hypot(step[:, 0], step[:, 1]) > merge_m
    return points[keep], extra[keep]


def _offset_work(points: np.ndarray, dist: np.ndarray, curve: RawCurve, tol: float,
                 simplify_m: float, block: int) -> Generator[int, None, OffsetResult]:
    """El trabajo de :func:`offset_ring_steps`: cede el número de bloques tratados."""
    raw, source = _distinct(curve.points, curve.source_edge, MERGE_M)
    count = len(raw)
    if count < 3:
        return OffsetResult((), (), (), True, 0.0)
    a, b = raw, np.roll(raw, -1, axis=0)
    edge_boxes = np.concatenate([np.minimum(a, b), np.maximum(a, b)], axis=1)
    cut_edge: list[np.ndarray] = []
    cut_at: list[np.ndarray] = []
    cut_point: list[np.ndarray] = []
    marked = np.zeros(count, dtype=bool)
    for low in _blocks(count, block):
        part = slice(low, min(low + block, count))
        i, j, t, u, cut = crossings(a[part], b[part], a, b)
        i = i + low
        keep = i < j
        cut_edge += [i[keep], j[keep]]
        cut_at += [t[keep], u[keep]]
        cut_point += [cut[keep], cut[keep]]
        # Un vértice sobre una arista que no es suya (un pico que vuelve sobre sí mismo): se
        # inserta en ella, o el trozo que sigue no empieza donde acaba el anterior.
        vertex_boxes = np.concatenate([a[part] - TOUCH_M, a[part] + TOUCH_M], axis=1)
        v, e = box_pairs(vertex_boxes, edge_boxes)
        v = v + low
        own = (e != v) & (e != (v - 1) % count)
        v, e = v[own], e[own]
        if v.size:
            along = b[e] - a[e]
            length2 = np.einsum("ij,ij->i", along, along)
            t = np.einsum("ij,ij->i", a[v] - a[e], along) / length2
            off = a[v] - (a[e] + t[:, None] * along)
            inside = ((np.hypot(off[:, 0], off[:, 1]) < TOUCH_M)
                      & (np.hypot(*(a[v] - a[e]).T) > TOUCH_M)
                      & (np.hypot(*(a[v] - b[e]).T) > TOUCH_M))
            cut_edge.append(e[inside])
            cut_at.append(t[inside])
            cut_point.append(a[v][inside])
            marked[v[inside]] = True
        yield 1
    # Cada punto lleva un tercer número: 1 si es un cruce (o un vértice que toca otra arista),
    # donde puede cambiar la vuelta; entre dos así, todos los trozos tienen la misma.
    cuts = np.concatenate(cut_point) if cut_point else np.zeros((0, 2))
    tagged = np.column_stack([raw, marked.astype(np.float64)])
    new = np.column_stack([cuts, np.ones(len(cuts))])
    joined, vertex = splice(tagged, np.arange(count, dtype=np.int64), np.concatenate(cut_edge),
                            np.concatenate(cut_at), new)
    joined, vertex = _distinct(joined, vertex)
    spliced, flag = joined[:, :2], joined[:, 2] > 0.0
    origin = source[vertex]

    start, end = spliced, np.roll(spliced, -1, axis=0)
    along = end - start
    length = np.hypot(along[:, 0], along[:, 1])
    run = np.cumsum(flag) - 1
    runs = int(flag.sum())
    run = run % runs if runs else np.zeros(len(spliced), dtype=np.int64)
    runs = max(runs, 1)
    # El trozo más largo de cada tramo es el que se prueba.
    order = np.lexsort((-length, run))
    first = order[np.searchsorted(run[order], np.arange(runs))]
    left = np.column_stack([-along[:, 1], along[:, 0]]) / length[:, None]
    eps = np.minimum(PROBE_M, 0.25 * length)[:, None]
    mid = 0.5 * (start + end)
    group = (end[:, 1] <= start[:, 1]).astype(np.int64)  # 0: sube, 1: baja
    run_border = np.zeros(runs, dtype=bool)
    for low in _blocks(runs, block):
        pick = first[low:low + block]
        probes = np.concatenate([mid[pick] + eps[pick] * left[pick],
                                 mid[pick] - eps[pick] * left[pick]])
        turns = ray_counts(probes, start, end, group, 2)
        winding = turns[:, 0] - turns[:, 1]
        size = len(pick)
        run_border[low:low + size] = (winding[:size] == 1) & (winding[size:] == 0)
        yield 1
    border = run_border[run]

    kept = np.flatnonzero(border)
    edges = np.stack([start[kept], end[kept]], axis=1)
    from_edge = {(x + 0.0, y + 0.0): int(o)
                 for (x, y), o in zip(start[kept].tolist(), origin[kept].tolist(), strict=True)}
    rings: list[np.ndarray] = []
    holes: list[np.ndarray] = []
    ring_sources: list[np.ndarray] = []
    hole_sources: list[np.ndarray] = []
    for loop in chain(edges):
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
    """Comprueba un desfase (plan §5.4 A4): que ``loops`` (anillos y huecos, con la arista de
    ``source`` de la que sale cada vértice en ``sources``) son **simples** (ningún par de aristas
    se cruza, dentro de un anillo ni entre ellos) y que cada vértice está a ``≥ d − tol −
    simplify_m`` de **todas** las aristas de ``source``, con ``d`` la menor distancia de las
    aristas de origen del vértice y de sus dos vecinos (en un salto de distancia entre dos
    aristas el tramo de unión queda entre las dos). Da ``(verificado, lugar, defecto, falta)``;
    ``falta`` es la mayor distancia (m) que le falta a un vértice. Cede el número de bloques
    tratados."""
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
    d_here = np.concatenate([dist[s] for s in sources])
    d_before = np.concatenate([np.roll(dist[s], 1) for s in sources])
    d_after = np.concatenate([np.roll(dist[s], -1) for s in sources])
    limit = np.minimum(d_here, np.minimum(d_before, d_after)) - tol - simplify_m - _VERIFY_SLACK_M
    need = np.flatnonzero(limit > 0.0)
    worst, worst_at = 0.0, None
    edge_a, edge_b = src, np.roll(src, -1, axis=0)
    edge_boxes = np.concatenate([np.minimum(edge_a, edge_b), np.maximum(edge_a, edge_b)], axis=1)
    for low in _blocks(len(need), block):
        pick = need[low:low + block]
        pad = limit[pick][:, None]
        boxes = np.concatenate([a[pick] - pad, a[pick] + pad], axis=1)
        v, e = box_pairs(boxes, edge_boxes)
        if v.size:
            gap = limit[pick][v] - _point_edge_distance(a[pick][v], edge_a[e], edge_b[e])
            top = int(np.argmax(gap))
            if gap[top] > worst:
                worst = float(gap[top])
                at = a[pick][v[top]]
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
