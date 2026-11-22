# SPDX-License-Identifier: GPL-3.0-or-later
"""Polígonos en planta: validarlos, buscar sus solapes y recortarlos (spec 011, RF-011-01 y
RF-011-08, plan 011 A6 y D-21; bajados de ``reserves.polygons`` a ``gis`` en la spec 012,
plan 012 §5.6, D-18 y T2, para las máscaras de las restricciones, RF-012-07 y RF-012-12, y el
diseño).

Un polígono son sus anillos ABSOLUTOS en float64 (arrays ``(k, 2)``, cerrados o no; el primero,
el exterior, y los demás, sus huecos, en cualquier sentido). Los errores son **neutros**: una
posición en la lista y el problema (:class:`PolygonProblem`), sin códigos de nota de ningún
módulo; ``reserves.polygons`` los convierte en los suyos (``res.domain_*``, ``res.scope_*``).

- :func:`problems` y :func:`problem_steps`: cada polígono **simple** (dos aristas no contiguas
  que se cortan o se tocan a ≤ :data:`TOLERANCE_M`, o un lado que vuelve sobre el anterior:
  ``self_intersecting``), **con área** (más de :data:`AREA_TOLERANCE_M2`; ``no_area``), con sus
  huecos dentro del exterior y fuera de los demás huecos (``hole_outside``), y ningún par
  **solapado** en más de 1 mm² (``overlap``, con el otro y el área). Por pasos: uno por polígono
  y uno por par cuyas cajas se tocan.
- :func:`overlaps`: los pares que se solapan, con el área del solape (:class:`Overlap`).
- :func:`clip`: las aristas orientadas de ``polígono ∩ recorte``; :func:`local_edges`, las de
  un polígono con la misma copia de trabajo, relativas a un origen.
- :func:`overlay` (plan 012 A4): unión, intersección o diferencia de dos conjuntos de polígonos
  con huecos, con el mismo recorte por clasificación de aristas; la :class:`Region` resultante,
  con sus partes (:class:`Part`: área y centro absoluto), encadenando las aristas en anillos.
- :func:`segment_distance` (plan 012 A6): la distancia entre pares de segmentos.

**Recorte por clasificación de aristas** (A6 de la 011). En coordenadas locales float64 (restar
un origen cercano es exacto, lema de Sterbenz): (1) cada vértice de un polígono a ≤
:data:`TOLERANCE_M` de uno del otro pasa a ser ese (la tolerancia de 1 mm de la 006); (2) los
vértices de cada uno que caen a ≤ 1 mm del interior de una arista del otro se insertan en ella
(el propio vértice, no su proyección: así los lados comunes tienen los mismos vértices en los
dos); (3) las aristas se parten en sus **cruces propios**, cada cruce calculado una vez e
insertado en las dos (cada coordenada, desde la arista que menos varía en ella: en rectángulos
sale exacta); (4) los trozos **comunes** (los mismos extremos) se quedan una vez si los dos los
recorren en el mismo sentido y ninguna si en sentidos opuestos; (5) los demás, si su punto medio
está dentro del otro polígono (par-impar de un rayo hacia +X). Lo que queda es el borde orientado
de la intersección: su área con signo es la del solape, y con él se calcula la fracción de celda
(``gis.coverage``). Los pares de aristas y de puntos cercanos se buscan por cubetas (una rejilla
de celdas sobre la zona común); el rayo, por franjas de Y.

Python puro con numpy (nivel 2). Las entradas del usuario solo se leen: lo que se ajusta a la
tolerancia es una copia de trabajo.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Sequence
from dataclasses import dataclass

import numpy as np

from .coverage import signed_area

__all__ = [
    "AREA_TOLERANCE_M2",
    "OPERATIONS",
    "PROBLEMS",
    "TOLERANCE_M",
    "Overlap",
    "Part",
    "PolygonProblem",
    "Region",
    "Rings",
    "box_pairs",
    "chain",
    "clip",
    "crossings",
    "drain",
    "expand",
    "following",
    "local_edges",
    "overlaps",
    "overlay",
    "problem_steps",
    "problems",
    "ray_counts",
    "segment_distance",
    "splice",
]

Rings = Sequence[np.ndarray]
"""Los anillos ABSOLUTOS de un polígono (el primero, el exterior; los demás, sus huecos)."""

PROBLEMS = ("self_intersecting", "no_area", "hole_outside", "overlap")
"""Los problemas que da :func:`problems`."""

OPERATIONS = ("union", "intersection", "difference")
"""Las operaciones de :func:`overlay`."""

TOLERANCE_M = 1e-3
"""Distancia (m) a la que un vértice está sobre otro vértice o sobre una arista, y dos aristas no
contiguas se tocan: la tolerancia de la 006 (D-5 de su spec)."""

AREA_TOLERANCE_M2 = 1e-6
"""Área (m², 1 mm²) por debajo de la cual un polígono no tiene área y un solape no lo es."""

_ZERO_M = 1e-9
"""Distancia con signo (m) de un punto a una recta que se toma por cero en un cruce propio."""

_MAX_CELLS = 256
"""Celdas por eje, como mucho, de la rejilla de cubetas que busca los pares cercanos."""

_MAX_STRIPS = 1024
"""Franjas de Y, como mucho, del rayo par-impar."""

_MIX = np.array([0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9,
                 0x27D4EB2F165667C5], dtype=np.uint64)
"""Multiplicadores (impares) de la huella de un trozo: sus cuatro coordenadas en una clave."""


# Datos ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Overlap:
    """Dos polígonos que se solapan: sus posiciones en la secuencia (``first < second``) y el
    área del solape (m², más de :data:`AREA_TOLERANCE_M2`)."""

    first: int
    second: int
    area_m2: float


@dataclass(frozen=True, slots=True)
class PolygonProblem:
    """Un problema del polígono de posición ``index`` en la lista: ``problem`` (uno de
    :data:`PROBLEMS`) y, en un solape, el área del solape (``area_m2``, m²) y la posición del
    otro polígono (``other``, mayor que ``index``)."""

    index: int
    problem: str
    area_m2: float | None = None
    other: int | None = None


@dataclass(frozen=True, slots=True)
class Part:
    """Una parte de una :class:`Region` (un exterior con sus huecos): su área (m², > 0) y el
    centro de su área en coordenadas ABSOLUTAS ``(x, y)``."""

    area_m2: float
    centroid: tuple[float, float]


@dataclass(frozen=True, slots=True, eq=False)
class Region:
    """El resultado de :func:`overlay`: las aristas orientadas ``(n, 2, 2)`` de su borde
    (relativas al origen dado; lo de dentro, a la izquierda), sus partes (de mayor a menor
    área) y su área (m², la suma con signo de las aristas)."""

    edges_local: np.ndarray
    parts: tuple[Part, ...]
    area_m2: float


# Validación y solapes ------------------------------------------------------------------------


def problems(rings_list: Sequence[Rings]) -> tuple[PolygonProblem, ...]:
    """Los problemas de los polígonos ``rings_list``, en su orden y después los solapes: «se
    corta a sí mismo», «no tiene área», un hueco fuera de su contorno o dentro de otro, y cada
    par que se solapa en más de 1 mm², con su área. Los solapes se buscan entre los polígonos de
    geometría válida."""
    return drain(problem_steps(rings_list))


def problem_steps(rings_list: Sequence[Rings]
                  ) -> Generator[None, None, tuple[PolygonProblem, ...]]:
    """:func:`problems` por pasos (plan 011 A10): un paso por polígono y otro por cada par de
    polígonos cuyas cajas se tocan (recortar un par es lo más lento); lo mismo que
    :func:`problems` en ``StopIteration.value``."""
    origin = _origin(rings_list)
    found: list[PolygonProblem] = []
    valid: list[tuple[int, list[np.ndarray]]] = []
    for index, rings in enumerate(rings_list):
        local = _local_rings(rings, origin)
        problem = _geometry_problem(local)
        if problem is None:
            valid.append((index, local))
        else:
            found.append(PolygonProblem(index, problem))
        yield
    for overlap in (yield from _overlap_steps(valid)):
        found.append(PolygonProblem(overlap.first, "overlap", overlap.area_m2, overlap.second))
    return tuple(found)


def overlaps(rings_list: Sequence[Rings]) -> tuple[Overlap, ...]:
    """Los pares de ``rings_list`` (válidos: simples y con área) que se solapan en más de
    :data:`AREA_TOLERANCE_M2`, con el área del solape (m²), por posiciones. Dos que comparten un
    lado (también en parte, o a ≤ 1 mm) o que solo se tocan no se solapan."""
    origin = _origin(rings_list)
    local = [(index, _local_rings(rings, origin)) for index, rings in enumerate(rings_list)]
    return tuple(_overlaps([(index, rings) for index, rings in local if rings]))


def _overlaps(valid: list[tuple[int, list[np.ndarray]]]) -> list[Overlap]:
    return drain(_overlap_steps(valid))


def _overlap_steps(valid: list[tuple[int, list[np.ndarray]]]
                   ) -> Generator[None, None, list[Overlap]]:
    """Los solapes de ``valid``, un paso por par de cajas que se tocan."""
    if len(valid) < 2:
        return []
    boxes = np.array([[*ring.min(axis=0), *ring.max(axis=0)]
                      for ring in (rings[0] for _, rings in valid)])
    padded = boxes + np.array([-TOLERANCE_M, -TOLERANCE_M, TOLERANCE_M, TOLERANCE_M])
    first, second = box_pairs(padded, boxes)
    keep = first < second
    found = []
    for i, j in sorted(zip(first[keep].tolist(), second[keep].tolist(), strict=True)):
        area = _edges_area(_intersection(valid[i][1], valid[j][1]))
        if area > AREA_TOLERANCE_M2:
            found.append(Overlap(valid[i][0], valid[j][0], area))
        yield
    return found


def drain[T](steps: Generator[None, None, T]) -> T:
    """Recorre ``steps`` de una vez y da lo que devuelve."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def _geometry_problem(rings: list[np.ndarray]) -> str | None:
    """El código del problema de la geometría (anillos locales, normalizados) o ``None``."""
    if not rings:
        return "no_area"
    points, ring = _flatten(rings)
    crossing, touching = _self_contacts(points, ring)
    if crossing:
        return "self_intersecting"
    if abs(math.fsum(signed_area(part) for part in rings)) <= AREA_TOLERANCE_M2:
        return "no_area"
    if touching:
        return "self_intersecting"
    if len(rings) > 1 and _holes_misplaced(rings):
        return "hole_outside"
    return None


def _self_contacts(points: np.ndarray, ring: np.ndarray) -> tuple[bool, bool]:
    """(dos aristas no contiguas se cruzan; dos no contiguas pasan a ≤ :data:`TOLERANCE_M` o un
    lado vuelve sobre el contiguo)."""
    nxt = following(ring)
    a, b = points, points[nxt]
    i, j = box_pairs(_boxes(a, b, TOLERANCE_M), _boxes(a, b))
    keep = i < j
    i, j = i[keep], j[keep]
    adjacent = (nxt[i] == j) | (nxt[j] == i)
    ni, nj = i[~adjacent], j[~adjacent]
    r, s = b[ni] - a[ni], b[nj] - a[nj]
    side_p, side_q = _cross(r, a[nj] - a[ni]), _cross(r, b[nj] - a[ni])
    side_a, side_b = _cross(s, a[ni] - a[nj]), _cross(s, b[ni] - a[nj])
    crossing = bool(np.any((side_p * side_q < 0.0) & (side_a * side_b < 0.0)))
    near = np.minimum.reduce([
        _segment_distance(a[nj], a[ni], b[ni]), _segment_distance(b[nj], a[ni], b[ni]),
        _segment_distance(a[ni], a[nj], b[nj]), _segment_distance(b[ni], a[nj], b[nj]),
    ]) if ni.size else np.zeros(0)
    ai, aj = i[adjacent], j[adjacent]
    forward = nxt[ai] == aj
    before, after = np.where(forward, ai, aj), np.where(forward, aj, ai)
    # «before» llega al vértice común y «after» sale de él: vuelve si un extremo lejano cae
    # sobre la otra arista.
    fold = ((_segment_distance(a[before], a[after], b[after]) <= TOLERANCE_M)
            | (_segment_distance(b[after], a[before], b[before]) <= TOLERANCE_M))
    return crossing, bool(np.any(near <= TOLERANCE_M) or np.any(fold))


def _holes_misplaced(rings: list[np.ndarray]) -> bool:
    """Si un hueco (de un polígono sin contactos) está fuera del exterior o dentro de otro."""
    firsts = np.array([hole[0] for hole in rings[1:]])
    outer = rings[0]
    if not np.all(_inside(firsts, outer, np.roll(outer, -1, axis=0))):
        return True
    holes = rings[1:]
    if len(holes) < 2:
        return False
    points, group = _flatten(holes)
    counts = ray_counts(firsts, points, points[following(group)], group, len(holes))
    inside = counts % 2 == 1
    np.fill_diagonal(inside, False)
    return bool(inside.any())


# Recorte (A6) --------------------------------------------------------------------------------


def clip(rings: Rings, clip_rings: Rings, *, origin: Sequence[float]) -> np.ndarray:
    """Las aristas orientadas ``(n, 2, 2)`` del borde de ``rings ∩ clip_rings`` (el exterior
    antihorario y los huecos horarios), en metros relativos a ``origin`` (``(x, y)`` absolutos;
    para la fracción de celda, la esquina suroeste de la rejilla, ``(grid.west,
    grid.extent.ymin)``). Un polígono entero dentro del recorte da sus aristas; entero fuera,
    ninguna. Los dos, válidos (:func:`problems` vacío)."""
    corner = np.asarray(origin, dtype=np.float64).reshape(2)
    return _intersection(_local_rings(rings, corner), _local_rings(clip_rings, corner))


def local_edges(rings: Rings, origin: Sequence[float]) -> np.ndarray:
    """Las aristas orientadas ``(n, 2, 2)`` del polígono ``rings``, relativas a ``origin``, con
    la misma copia de trabajo que usa :func:`clip` (sin vértices seguidos a ≤ 1 mm, el exterior
    antihorario y los huecos horarios)."""
    corner = np.asarray(origin, dtype=np.float64).reshape(2)
    return _ring_edges(_local_rings(rings, corner))


# Superposición (A4 de la 012) ----------------------------------------------------------------


def overlay(a: Sequence[Rings], b: Sequence[Rings], op: str, *,
            origin: Sequence[float]) -> Region:
    """La superposición ``A <op> B`` de dos conjuntos de polígonos (cada uno, sus anillos
    ABSOLUTOS con sus huecos; válidos, :func:`problems` vacío), con ``op`` en
    :data:`OPERATIONS`: ``"union"``, ``"intersection"`` o ``"difference"`` (``A ∖ B``). Cada
    conjunto es la unión de sus polígonos (dos contiguos, sin el lado común). El resultado
    (:class:`Region`) son sus aristas orientadas relativas a ``origin`` (``(x, y)`` absolutos),
    su área y sus partes con su área y su centro absoluto (plan 012 A4; RF-012-05, RF-012-06)."""
    if op not in OPERATIONS:
        raise ValueError(f"Operación de superposición desconocida: {op!r} (una de {OPERATIONS})")
    corner = np.asarray(origin, dtype=np.float64).reshape(2)
    first = _union_all([_local_rings(rings, corner) for rings in a])
    second = _union_all([_local_rings(rings, corner) for rings in b])
    edges = _combine(first, second, op) if op != "union" or (first and second) else (
        _ring_edges(first or second))
    return _region(edges, corner)


def segment_distance(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """La distancia (m) entre cada par de segmentos ``p[k]`` y ``q[k]`` (arrays ``(n, 2, 2)``:
    inicio y fin; uno de longitud nula es un punto): 0 si se cortan; si no, la menor de las
    cuatro distancias de un extremo al otro segmento (plan 012 A6). En coordenadas locales."""
    p = np.asarray(p, dtype=np.float64).reshape(-1, 2, 2)
    q = np.asarray(q, dtype=np.float64).reshape(-1, 2, 2)
    a, b, c, d = p[:, 0], p[:, 1], q[:, 0], q[:, 1]
    distance = np.minimum.reduce([_point_segment(a, c, d), _point_segment(b, c, d),
                                  _point_segment(c, a, b), _point_segment(d, a, b)])
    r, s = b - a, d - c
    crossing = ((_cross(r, c - a) * _cross(r, d - a) < 0.0)
                & (_cross(s, a - c) * _cross(s, b - c) < 0.0))
    return np.where(crossing, 0.0, distance)


def _point_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La distancia de cada punto ``p`` al segmento ``a–b`` (si es nulo, al punto ``a``)."""
    d, w = b - a, p - a
    length2 = d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]
    dot = w[:, 0] * d[:, 0] + w[:, 1] * d[:, 1]
    t = np.clip(np.divide(dot, length2, out=np.zeros_like(dot), where=length2 > 0.0), 0.0, 1.0)
    return np.hypot(w[:, 0] - t * d[:, 0], w[:, 1] - t * d[:, 1])


def _union_all(sets: list[list[np.ndarray]]) -> list[np.ndarray]:
    """La unión de los polígonos (anillos locales orientados), como anillos orientados."""
    rings: list[np.ndarray] = []
    for polygon in sets:
        if not polygon:
            continue
        rings = polygon if not rings else chain(_combine(rings, polygon, "union"))
    return rings


def _region(edges: np.ndarray, origin: np.ndarray) -> Region:
    """La región del borde orientado ``edges`` (relativo a ``origin``): sus partes."""
    rings = chain(edges)
    moments = [_ring_moments(ring) for ring in rings]
    outer = [k for k, (area, _, _) in enumerate(moments) if area > 0.0]
    holes = [k for k, (area, _, _) in enumerate(moments) if area <= 0.0]
    totals = {k: list(moments[k]) for k in outer}
    by_size = sorted(outer, key=lambda k: moments[k][0])
    for k in holes:
        owner = _hole_owner(rings[k], [rings[o] for o in by_size])
        if owner is not None:
            target = totals[by_size[owner]]
            for m in range(3):
                target[m] += moments[k][m]
    parts = []
    for k in outer:
        area, mx, my = totals[k]
        if area > AREA_TOLERANCE_M2:
            parts.append(Part(area, (float(origin[0] + mx / area),
                                     float(origin[1] + my / area))))
    parts.sort(key=lambda part: (-part.area_m2, part.centroid))
    return Region(edges, tuple(parts), _edges_area(edges))


def _ring_moments(ring: np.ndarray) -> tuple[float, float, float]:
    """(área con signo, momento en X, momento en Y) del anillo local ``ring`` (polígono)."""
    x, y = ring[:, 0], ring[:, 1]
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    cross = x * yn - xn * y
    return (0.5 * math.fsum(cross), math.fsum((x + xn) * cross) / 6.0,
            math.fsum((y + yn) * cross) / 6.0)


def _hole_owner(hole: np.ndarray, outers: list[np.ndarray]) -> int | None:
    """El exterior (de ``outers``, de menor a mayor área) que contiene el hueco: el primero que
    tiene dentro más de la mitad de sus vértices y de los puntos medios de sus lados (un hueco
    puede tocar su exterior o una isla en un punto)."""
    probes = np.concatenate([hole, 0.5 * (hole + np.roll(hole, -1, axis=0))])
    for index, outer in enumerate(outers):
        inside = _inside(probes, outer, np.roll(outer, -1, axis=0))
        if 2 * int(inside.sum()) > len(probes):
            return index
    return None


def chain(edges: np.ndarray) -> list[np.ndarray]:
    """Las aristas orientadas ``edges`` encadenadas en anillos por sus extremos (los mismos
    números). En un vértice con varias salidas, la que más gira a la izquierda (el anillo más
    ceñido: dos partes que se tocan en un vértice quedan separadas)."""
    if not len(edges):
        return []
    starts = edges[:, 0].tolist()
    ends = edges[:, 1].tolist()
    leaving: dict[tuple[float, float], list[int]] = {}
    for index, (x, y) in enumerate(starts):
        leaving.setdefault((x + 0.0, y + 0.0), []).append(index)
    used = [False] * len(starts)
    rings: list[np.ndarray] = []
    for first in range(len(starts)):
        if used[first]:
            continue
        used[first] = True
        ring = [first]
        home = (starts[first][0] + 0.0, starts[first][1] + 0.0)
        current = first
        while True:
            node = (ends[current][0] + 0.0, ends[current][1] + 0.0)
            options = [k for k in leaving.get(node, ()) if not used[k]]
            if node == home:
                options.append(first)
            if not options:
                break
            following = options[0] if len(options) == 1 else _leftmost(
                starts[current], ends[current], options, ends)
            if following == first:
                break
            used[following] = True
            ring.append(following)
            current = following
        if len(ring) >= 3:
            rings.append(np.ascontiguousarray(edges[ring, 0]))
    return rings


def _leftmost(start: list[float], node: list[float], options: list[int],
              ends: list[list[float]]) -> int:
    """De las aristas ``options`` que salen de ``node``, la que más gira a la izquierda
    viniendo de ``start`` (volver atrás, la última)."""
    dx, dy = node[0] - start[0], node[1] - start[1]
    best, best_angle = options[0], -math.inf
    for option in options:
        ex, ey = ends[option][0] - node[0], ends[option][1] - node[1]
        angle = math.atan2(dx * ey - dy * ex, dx * ex + dy * ey)
        if angle >= math.pi - 1e-12:
            angle = -math.pi
        if angle > best_angle:
            best, best_angle = option, angle
    return best


def _intersection(first: list[np.ndarray], second: list[np.ndarray]) -> np.ndarray:
    """Las aristas orientadas del borde de ``first ∩ second`` (anillos locales normalizados)."""
    return _combine(first, second, "intersection")


def _combine(first: list[np.ndarray], second: list[np.ndarray], op: str) -> np.ndarray:
    """Las aristas orientadas del borde de ``first <op> second`` (anillos locales orientados:
    lo de dentro, a la izquierda), con ``op`` en :data:`OPERATIONS` (plan 012 A4)."""
    if not first or not second:
        if op == "intersection" or not first:
            return _ring_edges(second) if op == "union" else _no_edges()
        return _ring_edges(first)
    p, p_ring = _flatten(first)
    q, q_ring = _flatten(second)
    low, high = q.min(axis=0) - TOLERANCE_M, q.max(axis=0) + TOLERANCE_M
    if np.any(p.max(axis=0) < low) or np.any(p.min(axis=0) > high):
        if op == "intersection":
            return _no_edges()
        return _concatenate([_ring_edges(first), _ring_edges(second)] if op == "union"
                            else [_ring_edges(first)])
    # (1) vértices a ≤ 1 mm de otro, el del otro; (2) vértices sobre aristas, insertados.
    p, p_ring = _dedupe(_snap(p, q), p_ring)
    if not p.size:
        return _ring_edges(second) if op == "union" else _no_edges()
    p_vertices, q_vertices = p, q
    p, p_ring = _insert_near(p, p_ring, q_vertices)
    q, q_ring = _insert_near(q, q_ring, p_vertices)
    p_next, q_next = p[following(p_ring)], q[following(q_ring)]
    # (3) cruces propios, el mismo punto en las dos aristas.
    i, j, t, u, cut = crossings(p, p_next, q, q_next)
    p_cut, p_cut_ring = splice(p, p_ring, i, t, cut)
    q_cut, q_cut_ring = splice(q, q_ring, j, u, cut)
    ps, pe = _pieces(p_cut, p_cut_ring)
    qs, qe = _pieces(q_cut, q_cut_ring)
    # (4) trozos comunes; (5) los demás, por su punto medio.
    p_same = _matches(ps, pe, qs, qe)
    p_opposite = _matches(ps, pe, qe, qs)
    p_rest = ~(p_same | p_opposite)
    q_rest = ~(_matches(qs, qe, ps, pe) | _matches(qe, qs, ps, pe))
    p_in = _inside(0.5 * (ps[p_rest] + pe[p_rest]), q, q_next)
    q_in = _inside(0.5 * (qs[q_rest] + qe[q_rest]), p, p_next)
    if op == "intersection":
        # Comunes en el mismo sentido, una vez; los de cada uno dentro del otro.
        starts = [ps[p_same], ps[p_rest][p_in], qs[q_rest][q_in]]
        ends = [pe[p_same], pe[p_rest][p_in], qe[q_rest][q_in]]
    elif op == "union":
        # Comunes en el mismo sentido, una vez (en sentidos opuestos, el lado es interior); los
        # de cada uno fuera del otro.
        starts = [ps[p_same], ps[p_rest][~p_in], qs[q_rest][~q_in]]
        ends = [pe[p_same], pe[p_rest][~p_in], qe[q_rest][~q_in]]
    else:
        # Diferencia: comunes en sentidos opuestos, el de ``first``; los de ``first`` fuera de
        # ``second`` y los de ``second`` dentro de ``first``, invertidos.
        starts = [ps[p_opposite], ps[p_rest][~p_in], qe[q_rest][q_in]]
        ends = [pe[p_opposite], pe[p_rest][~p_in], qs[q_rest][q_in]]
    return np.ascontiguousarray(np.stack([np.concatenate(starts), np.concatenate(ends)],
                                         axis=1))


def _snap(points: np.ndarray, others: np.ndarray) -> np.ndarray:
    """Cada vértice a ≤ :data:`TOLERANCE_M` de uno de ``others`` pasa a ser el más cercano."""
    i, j = box_pairs(_boxes(points, points, TOLERANCE_M), _boxes(others, others))
    if not i.size:
        return points
    gap = np.hypot(*(points[i] - others[j]).T)
    near = gap <= TOLERANCE_M
    i, j, gap = i[near], j[near], gap[near]
    if not i.size:
        return points
    order = np.lexsort((gap, i))
    i, j = i[order], j[order]
    first = np.concatenate([[True], i[1:] != i[:-1]])
    snapped = points.copy()
    snapped[i[first]] = others[j[first]]
    return snapped


def _insert_near(points: np.ndarray, ring: np.ndarray,
                 others: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Los vértices ``others`` a ≤ :data:`TOLERANCE_M` del interior de una arista (y a más de
    sus extremos), insertados en ella en su orden: el propio vértice, no su proyección."""
    a = points
    b = points[following(ring)]
    edge, vertex = box_pairs(_boxes(a, b, TOLERANCE_M), _boxes(others, others))
    if not edge.size:
        return points, ring
    start, end, point = a[edge], b[edge], others[vertex]
    d, w = end - start, point - start
    length2 = d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]
    t = (w[:, 0] * d[:, 0] + w[:, 1] * d[:, 1]) / length2
    distance = np.abs(_cross(d, w)) / np.sqrt(length2)
    ok = ((t > 0.0) & (t < 1.0) & (distance <= TOLERANCE_M)
          & (np.hypot(*w.T) > TOLERANCE_M) & (np.hypot(*(point - end).T) > TOLERANCE_M))
    if not ok.any():
        return points, ring
    return splice(points, ring, edge[ok], t[ok], point[ok])


def crossings(pa: np.ndarray, pb: np.ndarray, qa: np.ndarray, qb: np.ndarray
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Los cruces propios de las aristas ``pa→pb`` con las ``qa→qb`` (cada extremo, a más de
    :data:`_ZERO_M` de la recta de la otra y en lados opuestos): sus aristas, su posición en
    cada una (0..1) y el punto, el mismo para las dos."""
    i, j = box_pairs(_boxes(pa, pb), _boxes(qa, qb))
    a, b, p, q = pa[i], pb[i], qa[j], qb[j]
    r, s = b - a, q - p
    lr, ls = np.hypot(r[:, 0], r[:, 1]), np.hypot(s[:, 0], s[:, 1])
    # Una arista de longitud 0 (dos esquinas comunes que entran en la misma arista del otro
    # conjunto) da 0/0 = NaN: ninguna comparación de ``_opposite`` lo deja pasar, así que no
    # cruza nada y el resultado es el mismo; el aviso de numpy no aporta nada y saldría por la
    # consola de Blender (T42, O-5).
    with np.errstate(divide="ignore", invalid="ignore"):
        side_p, side_q = _cross(r, p - a) / lr, _cross(r, q - a) / lr
        side_a, side_b = _cross(s, a - p) / ls, _cross(s, b - p) / ls
    proper = (_opposite(side_p, side_q) & _opposite(side_a, side_b))
    i, j = i[proper], j[proper]
    side_p, side_q, side_a, side_b = side_p[proper], side_q[proper], side_a[proper], side_b[proper]
    a, r, p, s = a[proper], r[proper], p[proper], s[proper]
    t = side_a / (side_a - side_b)
    u = side_p / (side_p - side_q)
    on_p = a + t[:, None] * r
    on_q = p + u[:, None] * s
    # Cada coordenada, desde la arista que menos varía en ella (una vertical da su X exacta).
    cut = np.where(np.abs(r) <= np.abs(s), on_p, on_q)
    return i, j, t, u, cut


def _opposite(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return (((first < -_ZERO_M) & (second > _ZERO_M))
            | ((first > _ZERO_M) & (second < -_ZERO_M)))


def _pieces(points: np.ndarray, ring: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Los trozos (inicio, fin) de los anillos, sin los de longitud 0."""
    start, end = points, points[following(ring)]
    keep = np.any(start != end, axis=1)
    return start[keep], end[keep]


def _keys(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """Una huella uint64 de cada trozo (sus cuatro coordenadas; −0 como 0)."""
    bits = np.ascontiguousarray(np.concatenate([start, end], axis=1) + 0.0).view(np.uint64)
    return np.sum(bits * _MIX, axis=1, dtype=np.uint64)


def _matches(start: np.ndarray, end: np.ndarray, other_start: np.ndarray,
             other_end: np.ndarray) -> np.ndarray:
    """Si cada trozo ``start→end`` es exactamente uno de ``other_start→other_end``."""
    if not len(start) or not len(other_start):
        return np.zeros(len(start), dtype=bool)
    keys, others = _keys(start, end), _keys(other_start, other_end)
    order = np.argsort(others, kind="stable")
    ordered = others[order]
    position = np.minimum(np.searchsorted(ordered, keys), ordered.size - 1)
    found = order[position]
    return ((ordered[position] == keys) & np.all(start == other_start[found], axis=1)
            & np.all(end == other_end[found], axis=1))


# Ayudas --------------------------------------------------------------------------------------


def _no_edges() -> np.ndarray:
    return np.zeros((0, 2, 2), dtype=np.float64)


def _concatenate(edges: list[np.ndarray]) -> np.ndarray:
    return np.ascontiguousarray(np.concatenate(edges)) if edges else _no_edges()


def _open(ring: object) -> np.ndarray:
    """El anillo como ``(k, 2)`` float64, sin repetir el primer vértice al final."""
    points = np.asarray(ring, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2:
        raise ValueError(f"Un anillo es un array (k, 2) de vértices, no de forma {points.shape}")
    points = points[:, :2]
    if not np.all(np.isfinite(points)):
        raise ValueError("Un anillo tiene vértices no finitos")
    if len(points) > 1 and np.array_equal(points[0], points[-1]):
        points = points[:-1]
    return points


def _origin(rings_list: Sequence[Rings]) -> np.ndarray:
    """Un origen local cercano a todos los vértices (su mínimo en X y en Y)."""
    lows = [_open(ring).min(axis=0) for rings in rings_list for ring in rings if len(ring)]
    return np.min(lows, axis=0) if lows else np.zeros(2)


def _clean(points: np.ndarray) -> np.ndarray:
    """Sin vértices seguidos a ≤ :data:`TOLERANCE_M` (se queda el primero), también entre el
    último y el primero."""
    if len(points) < 2:
        return points
    step = np.hypot(*(np.roll(points, -1, axis=0) - points).T)
    if not np.any(step <= TOLERANCE_M):
        return points
    coords = points.tolist()
    keep = [0]
    last_x, last_y = coords[0]
    for index in range(1, len(coords)):
        x, y = coords[index]
        if math.hypot(x - last_x, y - last_y) > TOLERANCE_M:
            keep.append(index)
            last_x, last_y = x, y
    first_x, first_y = coords[0]
    while len(keep) > 1 and math.hypot(coords[keep[-1]][0] - first_x,
                                       coords[keep[-1]][1] - first_y) <= TOLERANCE_M:
        keep.pop()
    return points[keep]


def _local_rings(rings: Sequence[np.ndarray], origin: np.ndarray) -> list[np.ndarray]:
    """La copia de trabajo de un polígono: sus anillos relativos a ``origin``, abiertos, sin
    vértices seguidos a ≤ 1 mm, el exterior antihorario y los huecos horarios. Sin exterior de
    tres vértices, ``[]``; un hueco de menos de tres, fuera."""
    out: list[np.ndarray] = []
    for number, ring in enumerate(rings):
        points = _clean(_open(ring) - origin)
        if len(points) < 3:
            if number == 0:
                return []
            continue
        area = signed_area(points)
        if (area < 0.0) if number == 0 else (area > 0.0):
            points = points[::-1]
        out.append(np.ascontiguousarray(points))
    return out


def _ring_edges(rings: list[np.ndarray]) -> np.ndarray:
    return _concatenate([np.stack([ring, np.roll(ring, -1, axis=0)], axis=1) for ring in rings])


def _edges_area(edges: np.ndarray) -> float:
    """El área con signo (m²) del borde orientado ``edges``."""
    if not len(edges):
        return 0.0
    return 0.5 * float(np.sum(edges[:, 0, 0] * edges[:, 1, 1] - edges[:, 1, 0] * edges[:, 0, 1]))


def _flatten(rings: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Los vértices de todos los anillos, seguidos, y el anillo de cada uno."""
    points = np.concatenate(rings) if rings else np.zeros((0, 2))
    ring = np.repeat(np.arange(len(rings), dtype=np.int64), [len(part) for part in rings])
    return points, ring


def following(ring: np.ndarray) -> np.ndarray:
    """El índice del vértice siguiente en su anillo (los anillos, en bloques seguidos)."""
    nxt = np.arange(1, ring.size + 1, dtype=np.int64)
    if ring.size:
        last = np.flatnonzero(np.concatenate([ring[1:] != ring[:-1], [True]]))
        nxt[last] = np.concatenate([[0], last[:-1] + 1])
    return nxt


def _dedupe(points: np.ndarray, ring: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sin vértices repetidos seguidos y sin anillos de menos de tres vértices."""
    keep = ~np.all(points == points[following(ring)], axis=1)
    points, ring = points[keep], ring[keep]
    if ring.size:
        enough = np.bincount(ring)[ring] >= 3
        points, ring = points[enough], ring[enough]
    return points, ring


def splice(points: np.ndarray, ring: np.ndarray, edge: np.ndarray, t: np.ndarray,
            new: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Los puntos ``new`` insertados en las aristas ``edge`` (la que sale de ese vértice), en
    el orden de su posición ``t`` (0..1) en ella."""
    if not edge.size:
        return points, ring
    owner = np.concatenate([np.arange(len(points)), edge])
    where = np.concatenate([np.zeros(len(points)), t])
    order = np.lexsort((where, owner))
    return np.concatenate([points, new])[order], ring[owner[order]]


def _cross(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]


def _segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La distancia de cada punto ``p`` al segmento ``a–b`` (de longitud no nula)."""
    d, w = b - a, p - a
    t = np.clip((w[:, 0] * d[:, 0] + w[:, 1] * d[:, 1])
                / (d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]), 0.0, 1.0)
    return np.hypot(w[:, 0] - t * d[:, 0], w[:, 1] - t * d[:, 1])


def _boxes(a: np.ndarray, b: np.ndarray, pad: float = 0.0) -> np.ndarray:
    """Las cajas ``(xmin, ymin, xmax, ymax)`` de los segmentos ``a–b`` (o de los puntos, con
    ``a is b``), agrandadas ``pad``."""
    return np.concatenate([np.minimum(a, b) - pad, np.maximum(a, b) + pad], axis=1)


def expand(count: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada ``k``, ``count[k]`` entradas: (dueño, 0..count[k] − 1)."""
    owner = np.repeat(np.arange(count.size), count)
    offset = np.arange(owner.size) - np.repeat(np.cumsum(count) - count, count)
    return owner, offset


def _join(cell_a: np.ndarray, cell_b: np.ndarray, cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Las parejas (posición en ``cell_a``, posición en ``cell_b``) de la misma cubeta."""
    count_a = np.bincount(cell_a, minlength=cells)
    count_b = np.bincount(cell_b, minlength=cells)
    both = np.flatnonzero((count_a > 0) & (count_b > 0))
    if not both.size:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    order_a, order_b = np.argsort(cell_a, kind="stable"), np.argsort(cell_b, kind="stable")
    start_a, start_b = np.cumsum(count_a) - count_a, np.cumsum(count_b) - count_b
    width = count_b[both]
    group, k = expand(count_a[both] * width)
    cell = both[group]
    return (order_a[start_a[cell] + k // width[group]],
            order_b[start_b[cell] + k % width[group]])


def _cells(boxes: np.ndarray, west: float, south: float, sx: float, sy: float, nx: int,
           ny: int) -> tuple[np.ndarray, np.ndarray]:
    """Las cubetas que toca cada caja: (caja, cubeta)."""
    ix0 = np.clip(np.floor((boxes[:, 0] - west) / sx), 0, nx - 1).astype(np.int64)
    ix1 = np.clip(np.floor((boxes[:, 2] - west) / sx), 0, nx - 1).astype(np.int64)
    iy0 = np.clip(np.floor((boxes[:, 1] - south) / sy), 0, ny - 1).astype(np.int64)
    iy1 = np.clip(np.floor((boxes[:, 3] - south) / sy), 0, ny - 1).astype(np.int64)
    wide = ix1 - ix0 + 1
    owner, k = expand(wide * (iy1 - iy0 + 1))
    return owner, (iy0[owner] + k // wide[owner]) * nx + ix0[owner] + k % wide[owner]


def box_pairs(box_a: np.ndarray, box_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Las parejas (de ``box_a``, de ``box_b``) de cajas que se tocan, sin repetir, buscadas por
    cubetas sobre la zona común (unas pocas cajas por cubeta)."""
    none = (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64))
    if not len(box_a) or not len(box_b):
        return none
    west = max(float(box_a[:, 0].min()), float(box_b[:, 0].min()))
    south = max(float(box_a[:, 1].min()), float(box_b[:, 1].min()))
    east = min(float(box_a[:, 2].max()), float(box_b[:, 2].max()))
    north = min(float(box_a[:, 3].max()), float(box_b[:, 3].max()))
    if west > east or south > north:
        return none

    def within(boxes: np.ndarray) -> np.ndarray:
        return np.flatnonzero((boxes[:, 0] <= east) & (boxes[:, 2] >= west)
                              & (boxes[:, 1] <= north) & (boxes[:, 3] >= south))

    sel_a, sel_b = within(box_a), within(box_b)
    if not sel_a.size or not sel_b.size:
        return none
    width, height = east - west, north - south
    items = sel_a.size + sel_b.size
    if width * height > 0.0:
        side = math.sqrt(width * height / items)
    else:
        side = max(width, height) / items
    if not side > 0.0:
        side = 1.0
    nx = min(_MAX_CELLS, max(1, math.ceil(width / side)))
    ny = min(_MAX_CELLS, max(1, math.ceil(height / side)))
    sx = width / nx if width > 0.0 else 1.0
    sy = height / ny if height > 0.0 else 1.0
    owner_a, cell_a = _cells(box_a[sel_a], west, south, sx, sy, nx, ny)
    owner_b, cell_b = _cells(box_b[sel_b], west, south, sx, sy, nx, ny)
    pa, pb = _join(cell_a, cell_b, nx * ny)
    key = np.unique(sel_a[owner_a[pa]] * len(box_b) + sel_b[owner_b[pb]])
    ia, ib = key // len(box_b), key % len(box_b)
    touch = ((box_a[ia, 0] <= box_b[ib, 2]) & (box_b[ib, 0] <= box_a[ia, 2])
             & (box_a[ia, 1] <= box_b[ib, 3]) & (box_b[ib, 1] <= box_a[ia, 3]))
    return ia[touch], ib[touch]


def ray_counts(points: np.ndarray, a: np.ndarray, b: np.ndarray, group: np.ndarray | None = None,
                groups: int = 1) -> np.ndarray:
    """Cuántas aristas ``a→b`` de cada grupo cruza el rayo hacia +X desde cada punto
    (``(puntos, grupos)``; una arista cuenta si ``min(y) ≤ y < max(y)`` o al revés, como en el
    par-impar), por franjas de Y."""
    counts = np.zeros((len(points), groups), dtype=np.int64)
    if not len(points) or not len(a):
        return counts
    low, high = np.minimum(a[:, 1], b[:, 1]), np.maximum(a[:, 1], b[:, 1])
    bottom, top = float(low.min()), float(high.max())
    px, py = points[:, 0], points[:, 1]
    candidates = np.flatnonzero((py >= bottom) & (py <= top)
                                & (px <= float(np.maximum(a[:, 0], b[:, 0]).max())))
    if not candidates.size:
        return counts
    strips = min(_MAX_STRIPS, max(1, int(math.sqrt(len(a)))))
    sy = (top - bottom) / strips if top > bottom else 1.0
    first = np.clip(np.floor((low - bottom) / sy), 0, strips - 1).astype(np.int64)
    last = np.clip(np.floor((high - bottom) / sy), 0, strips - 1).astype(np.int64)
    owner, k = expand(last - first + 1)
    point_strip = np.clip(np.floor((py[candidates] - bottom) / sy), 0, strips - 1).astype(np.int64)
    pe, pp = _join(first[owner] + k, point_strip, strips)
    edge, point = owner[pe], candidates[pp]
    ay, by, y = a[edge, 1], b[edge, 1], py[point]
    spans = (ay > y) != (by > y)
    edge, point, ay, by, y = edge[spans], point[spans], ay[spans], by[spans], y[spans]
    ax, bx = a[edge, 0], b[edge, 0]
    hit = px[point] < ax + (y - ay) * (bx - ax) / (by - ay)
    owner_group = np.zeros(len(a), dtype=np.int64) if group is None else group
    np.add.at(counts, (point[hit], owner_group[edge[hit]]), 1)
    return counts


def _inside(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Si cada punto está dentro de las aristas ``a→b`` (par-impar)."""
    return ray_counts(points, a, b)[:, 0] % 2 == 1
