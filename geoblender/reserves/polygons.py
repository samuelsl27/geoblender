# SPDX-License-Identifier: GPL-3.0-or-later
"""Polígonos de una capa: validarlos, recortarlos por el ámbito y repartir cada celda entre ellos
(spec 011; RF-011-01, RF-011-07, RF-011-08; plan 011 A6 y D-21).

Una cubicación se reparte por **dominios** (los polígonos de una capa y el campo que los nombra:
fase, zona o sector) y, si se declara, solo dentro de un **ámbito** (otro polígono). Antes de
cubicar, la capa se comprueba (RF-011-08) y cada dominio que cruza el borde del ámbito se
sustituye por su **recorte exacto** (D-21); con esas aristas, la fracción exacta de cada celda
(``reserves.coverage``, A5) reparte la celda entre los dominios y la fila «Fuera de los
dominios».

- :class:`Polygon`: un polígono de la capa (``fid``, el valor de su campo y sus anillos
  ABSOLUTOS; el primero, el exterior); :func:`domain_polygons`, los de las entidades de una capa
  de dominios del proyecto (``gis.store.DomainFeature``), uno por parte (T32).
- :func:`problems` y :func:`validate`: cada polígono **simple** (dos aristas no contiguas que se
  cortan o se tocan a ≤ :data:`TOLERANCE_M`, o un lado que vuelve sobre el anterior: «se corta a
  sí mismo»), **con área** (más de :data:`AREA_TOLERANCE_M2`), con sus huecos dentro del exterior
  y fuera de los demás huecos, y con el campo lleno; ningún par **solapado** (más de 1 mm²). La
  lista dice el ``fid``, el valor del campo, el problema y, en un solape, su área en m²
  (:class:`Problem`); :func:`validate` la lanza como ``res.domains_invalid``
  (:class:`DomainsError`), y :func:`problem_steps` la busca por pasos (uno por polígono y por
  par que recortar: los de una cubicación, A10).
- :func:`scope_problems`, :func:`scope_problem_steps` y :func:`validate_scope`: lo mismo para
  un **ámbito** (RF-011-01; T37), sin el campo (no lo tiene), con los códigos ``res.scope_*``
  y el error ``res.scope_invalid`` (:class:`ScopeError`): dos partes que se solapan contarían
  dos veces el solape, y una que se corta a sí misma daría pesos con signo.
- :func:`overlaps`: los pares que se solapan, con el área del solape.
- :func:`clip_to_scope`: las aristas orientadas de ``polígono ∩ ámbito``.
- :func:`domain_edges` y :func:`scope_edges`: las aristas de cada dominio (los polígonos con el
  mismo valor, juntos; recortados por el ámbito si lo hay) y las del ámbito, relativas a la
  esquina suroeste de la rejilla, listas para :func:`weights`.
- :func:`weights`: las entradas (celda, dominio, peso) de una banda de filas, con la fila «Fuera
  de los dominios» = fracción del ámbito − Σ fracciones de los dominios (1 − Σ sin ámbito): las
  filas suman la del ámbito por construcción (RF-011-07).

**Recorte por clasificación de aristas** (A6). En coordenadas locales float64 (restar un origen
cercano es exacto, lema de Sterbenz): (1) cada vértice de un polígono a ≤ :data:`TOLERANCE_M` de
uno del otro pasa a ser ese (la tolerancia de 1 mm de la 006); (2) los vértices de cada uno que
caen a ≤ 1 mm del interior de una arista del otro se insertan en ella (el propio vértice, no su
proyección: así los lados comunes tienen los mismos vértices en los dos); (3) las aristas se
parten en sus **cruces propios**, cada cruce calculado una vez e insertado en las dos (cada
coordenada, desde la arista que menos varía en ella: en rectángulos sale exacta); (4) los trozos
**comunes** (los mismos extremos) se quedan una vez si los dos los recorren en el mismo sentido y
ninguna si en sentidos opuestos; (5) los demás, si su punto medio está dentro del otro polígono
(par-impar de un rayo hacia +X). Lo que queda es el borde orientado de la intersección: su área
con signo es la del solape, y con él se calcula la fracción de celda. Los pares de aristas y de
puntos cercanos se buscan por cubetas (una rejilla de celdas sobre la zona común); el rayo, por
franjas de Y.

Python puro con numpy (nivel 9). Las entradas del usuario solo se leen: lo que se ajusta a la
tolerancia es una copia de trabajo.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.i18n import format_number
from .coverage import FRACTION_EPSILON, band_coverage, polygon_edges, signed_area
from .messages import ResError, render

if TYPE_CHECKING:
    from ..gis.grid import Grid
    from ..gis.store import DomainFeature

__all__ = [
    "AREA_TOLERANCE_M2",
    "TOLERANCE_M",
    "DomainEdges",
    "DomainsError",
    "Overlap",
    "Polygon",
    "Problem",
    "ScopeError",
    "Weights",
    "clip_to_scope",
    "domain_edges",
    "domain_polygons",
    "overlaps",
    "problem_steps",
    "problems",
    "scope_edges",
    "scope_problem_steps",
    "scope_problems",
    "validate",
    "validate_scope",
    "weights",
]

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


# Datos ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Polygon:
    """Un polígono de una capa (dominios o ámbito): ``fid``, el valor del campo que lo nombra
    (``value``; vacío, ``""``) y sus anillos ABSOLUTOS en float64 (``rings``: arrays ``(k, 2)``,
    cerrados o no; el primero, el exterior, y los demás, sus huecos, en cualquier sentido)."""

    fid: int
    value: str
    rings: tuple[np.ndarray, ...]


@dataclass(frozen=True, slots=True)
class Overlap:
    """Dos polígonos que se solapan: sus posiciones en la secuencia (``first < second``) y el
    área del solape (m², más de :data:`AREA_TOLERANCE_M2`)."""

    first: int
    second: int
    area_m2: float


@dataclass(frozen=True, slots=True)
class Problem:
    """Un problema de un polígono de la capa (RF-011-08): su código de nota (``res.domain_*``),
    ``fid`` y valor del campo, y en un solape, el otro polígono y el área (m²)."""

    code: str
    fid: int
    value: str
    other_fid: int | None = None
    other_value: str | None = None
    area_m2: float | None = None

    def text(self, attribute: str, language: str = "es") -> str:
        """El problema como un elemento de la lista de ``res.domains_invalid``, con el nombre
        del campo (``attribute``), en ``language`` (el área, en el formato de la interfaz)."""
        area = None if self.area_m2 is None else _area_text(self.area_m2)
        return render(self.code, language=language, fid=self.fid, domain=self.value,
                      attribute=attribute, other_fid=self.other_fid,
                      other_domain=self.other_value, area=area)


class DomainsError(ResError):
    """``res.domains_invalid``: la capa de dominios no sirve; ``problems`` es la lista
    (:class:`Problem`) y el valor del error, cuántos problemas hay."""

    def __init__(self, found: Sequence[Problem], *, field: str, layer: str) -> None:
        found = tuple(found)
        super().__init__("res.domains_invalid", obj=f"Capa de dominios «{layer}»", field=field,
                         value=len(found), layer=layer, attribute=field,
                         problems="; ".join(problem.text(field) for problem in found))
        self.problems = found


class ScopeError(ResError):
    """``res.scope_invalid``: el ámbito no sirve (RF-011-01; T37); ``problems`` es la lista
    (:class:`Problem`, códigos ``res.scope_*``) y el valor del error, cuántos problemas hay."""

    def __init__(self, found: Sequence[Problem], *, layer: str) -> None:
        found = tuple(found)
        super().__init__("res.scope_invalid", obj=f"Capa del ámbito «{layer}»", field="ámbito",
                         value=len(found), layer=layer,
                         problems="; ".join(problem.text("") for problem in found))
        self.problems = found


@dataclass(frozen=True, slots=True, eq=False)
class DomainEdges:
    """Un dominio (el valor del campo) y las aristas orientadas de sus polígonos, recortados por
    el ámbito si lo hay, ``(n, 2, 2)`` en metros relativos a la esquina suroeste de la rejilla."""

    value: str
    edges: np.ndarray


@dataclass(frozen=True, slots=True, eq=False)
class Weights:
    """El reparto de las celdas de una banda de filas ``[start, stop)`` (la fila 0 es la del
    norte).

    - ``scope``: ``(stop − start, ncols)``, la fracción de cada celda dentro del ámbito; ``None``
      sin ámbito (cada celda cuenta entera).
    - Las entradas (celda, dominio, peso): ``rows`` y ``cols`` (int64, de la rejilla),
      ``domain`` (int64: la posición del dominio, o ``count`` para «Fuera de los dominios») y
      ``weight`` (float64). En cada celda suman su fracción del ámbito (1 sin él) salvo el
      redondeo. Sin dominios (``count == 0``) no hay entradas."""

    start: int
    stop: int
    scope: np.ndarray | None
    rows: np.ndarray
    cols: np.ndarray
    domain: np.ndarray
    weight: np.ndarray
    count: int

    @property
    def outside(self) -> int:
        """El índice de la fila «Fuera de los dominios» en ``domain``."""
        return self.count


def domain_polygons(features: Sequence[DomainFeature], field: str) -> tuple[Polygon, ...]:
    """Los polígonos de la capa de dominios ``features`` (sus entidades,
    ``gis.store.DomainFeature``: número, atributos por columna y polígonos) para repartir por su
    columna ``field``
    (RF-011-07; plan D-32): uno por parte de cada entidad, en su orden, con el número de la
    entidad y el valor de su campo como texto (un número, sus cifras; sin valor, ``""``, que
    rechaza :func:`validate`: RF-011-08) y sus anillos tal como llegan (no se copian).
    ``ValueError`` si alguna entidad no tiene la columna ``field``."""
    found: list[Polygon] = []
    for feature in features:
        if field not in feature.attributes:
            raise ValueError(f"la entidad {feature.fid} de la capa de dominios no tiene el campo "
                             f"«{field}»: tiene {', '.join(map(str, feature.attributes))}")
        value = feature.attributes[field]
        text = "" if value is None else str(value)
        found.extend(Polygon(int(feature.fid), text, tuple(part)) for part in feature.polygons)
    return tuple(found)


# Validación y solapes (RF-011-08) --------------------------------------------------------------


def problems(polygons: Sequence[Polygon]) -> tuple[Problem, ...]:
    """Los problemas de la capa (RF-011-08), en el orden de sus polígonos y después los
    solapes: el campo vacío, «se corta a sí mismo», «no tiene área», un hueco fuera de su
    contorno o dentro de otro, y cada par que se solapa en más de 1 mm², con su área. Los
    solapes se buscan entre los polígonos de geometría válida."""
    return _drain(problem_steps(polygons))


def problem_steps(polygons: Sequence[Polygon]) -> Generator[None, None, tuple[Problem, ...]]:
    """:func:`problems` por pasos (plan 011 A10; RNF-011-04): un paso por polígono y otro por
    cada par de polígonos cuyas cajas se tocan (recortar un par es lo más lento: unos 11 ms con
    miles de vértices); lo mismo que :func:`problems` en ``StopIteration.value``."""
    return (yield from _problem_steps(polygons, domains=True))


def scope_problems(polygons: Sequence[Polygon]) -> tuple[Problem, ...]:
    """Los problemas de un ámbito (RF-011-01, con la regla de RF-011-08; T37): los de
    :func:`problems` salvo el campo vacío (un ámbito no tiene campo), con los códigos
    ``res.scope_*``. Dos partes que se solapan contarían dos veces el solape, y una que se corta
    a sí misma daría pesos con signo."""
    return _drain(scope_problem_steps(polygons))


def scope_problem_steps(polygons: Sequence[Polygon]
                        ) -> Generator[None, None, tuple[Problem, ...]]:
    """:func:`scope_problems` por pasos, como :func:`problem_steps`."""
    return (yield from _problem_steps(polygons, domains=False))


def _problem_steps(polygons: Sequence[Polygon], *, domains: bool
                   ) -> Generator[None, None, tuple[Problem, ...]]:
    prefix = "res.domain_" if domains else "res.scope_"
    origin = _origin(polygons)
    found: list[Problem] = []
    valid: list[tuple[int, list[np.ndarray]]] = []
    for index, polygon in enumerate(polygons):
        value = _value(polygon)
        if domains and not value.strip():
            found.append(Problem("res.domain_value_empty", polygon.fid, value))
        rings = _local_rings(polygon.rings, origin)
        code = _geometry_problem(rings)
        if code is None:
            valid.append((index, rings))
        else:
            found.append(Problem(code.replace("res.domain_", prefix), polygon.fid, value))
        yield
    for overlap in (yield from _overlap_steps(valid)):
        first, second = polygons[overlap.first], polygons[overlap.second]
        found.append(Problem(prefix + "overlap", first.fid, _value(first), second.fid,
                             _value(second), overlap.area_m2))
    return tuple(found)


def validate(polygons: Sequence[Polygon], *, field: str, layer: str) -> None:
    """Comprueba la capa de dominios ``layer`` para repartir por su campo ``field``
    (RF-011-08): con algún problema (:func:`problems`), :class:`DomainsError`
    (``res.domains_invalid``, con la lista) y no se cubica con ella."""
    found = problems(polygons)
    if found:
        raise DomainsError(found, field=field, layer=layer)


def validate_scope(polygons: Sequence[Polygon], *, layer: str) -> None:
    """Comprueba el ámbito de la capa ``layer`` (:func:`scope_problems`): con algún problema,
    :class:`ScopeError` (``res.scope_invalid``, con la lista) y no se cubica con él."""
    found = scope_problems(polygons)
    if found:
        raise ScopeError(found, layer=layer)


def overlaps(polygons: Sequence[Polygon]) -> tuple[Overlap, ...]:
    """Los pares de ``polygons`` (válidos: simples y con área) que se solapan en más de
    :data:`AREA_TOLERANCE_M2`, con el área del solape (m²), por posiciones. Dos que comparten un
    lado (también en parte, o a ≤ 1 mm) o que solo se tocan no se solapan."""
    origin = _origin(polygons)
    local = [(index, _local_rings(polygon.rings, origin))
             for index, polygon in enumerate(polygons)]
    return tuple(_overlaps([(index, rings) for index, rings in local if rings]))


def _overlaps(valid: list[tuple[int, list[np.ndarray]]]) -> list[Overlap]:
    return _drain(_overlap_steps(valid))


def _overlap_steps(valid: list[tuple[int, list[np.ndarray]]]
                   ) -> Generator[None, None, list[Overlap]]:
    """Los solapes de ``valid``, un paso por par de cajas que se tocan."""
    if len(valid) < 2:
        return []
    boxes = np.array([[*ring.min(axis=0), *ring.max(axis=0)]
                      for ring in (rings[0] for _, rings in valid)])
    padded = boxes + np.array([-TOLERANCE_M, -TOLERANCE_M, TOLERANCE_M, TOLERANCE_M])
    first, second = _box_pairs(padded, boxes)
    keep = first < second
    found = []
    for i, j in sorted(zip(first[keep].tolist(), second[keep].tolist(), strict=True)):
        area = _edges_area(_intersection(valid[i][1], valid[j][1]))
        if area > AREA_TOLERANCE_M2:
            found.append(Overlap(valid[i][0], valid[j][0], area))
        yield
    return found


def _drain[T](steps: Generator[None, None, T]) -> T:
    """Recorre ``steps`` de una vez y da lo que devuelve."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def _geometry_problem(rings: list[np.ndarray]) -> str | None:
    """El código del problema de la geometría (anillos locales, normalizados) o ``None``."""
    if not rings:
        return "res.domain_no_area"
    points, ring = _flatten(rings)
    crossing, touching = _self_contacts(points, ring)
    if crossing:
        return "res.domain_self_intersecting"
    if abs(math.fsum(signed_area(part) for part in rings)) <= AREA_TOLERANCE_M2:
        return "res.domain_no_area"
    if touching:
        return "res.domain_self_intersecting"
    if len(rings) > 1 and _holes_misplaced(rings):
        return "res.domain_hole_outside"
    return None


def _self_contacts(points: np.ndarray, ring: np.ndarray) -> tuple[bool, bool]:
    """(dos aristas no contiguas se cruzan; dos no contiguas pasan a ≤ :data:`TOLERANCE_M` o un
    lado vuelve sobre el contiguo)."""
    following = _following(ring)
    a, b = points, points[following]
    i, j = _box_pairs(_boxes(a, b, TOLERANCE_M), _boxes(a, b))
    keep = i < j
    i, j = i[keep], j[keep]
    adjacent = (following[i] == j) | (following[j] == i)
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
    forward = following[ai] == aj
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
    counts = _ray_counts(firsts, points, points[_following(group)], group, len(holes))
    inside = counts % 2 == 1
    np.fill_diagonal(inside, False)
    return bool(inside.any())


# Recorte (A6) ---------------------------------------------------------------------------------


def clip_to_scope(polygon: Polygon, scope: Polygon, *, origin: Sequence[float]) -> np.ndarray:
    """Las aristas orientadas ``(n, 2, 2)`` del borde de ``polygon ∩ scope`` (el exterior
    antihorario y los huecos horarios), en metros relativos a ``origin`` (``(x, y)`` absolutos;
    para la fracción de celda, la esquina suroeste de la rejilla, ``(grid.west,
    grid.extent.ymin)``). Un polígono entero dentro del ámbito da sus aristas; entero fuera,
    ninguna. Los dos, válidos (:func:`validate`)."""
    corner = np.asarray(origin, dtype=np.float64).reshape(2)
    return _intersection(_local_rings(polygon.rings, corner), _local_rings(scope.rings, corner))


def domain_edges(polygons: Sequence[Polygon], grid: Grid, *,
                 scope: Polygon | Sequence[Polygon] | None = None) -> tuple[DomainEdges, ...]:
    """Las aristas de cada dominio (los polígonos con el mismo valor, juntos; en el orden en que
    aparece cada valor), relativas a la esquina suroeste de ``grid``: con un ámbito (uno o varios
    polígonos que no se solapan), su recorte por él (:func:`clip_to_scope`); sin él, las del
    polígono (``coverage.polygon_edges``)."""
    corner = _corner(grid)
    parts = _parts(scope)
    groups: dict[str, list[np.ndarray]] = {}
    for polygon in polygons:
        if parts is None:
            edges = polygon_edges(polygon.rings, grid)
        else:
            edges = _concatenate([clip_to_scope(polygon, part, origin=corner) for part in parts])
        groups.setdefault(_value(polygon), []).append(edges)
    return tuple(DomainEdges(value, _concatenate(items)) for value, items in groups.items())


def scope_edges(scope: Polygon | Sequence[Polygon], grid: Grid) -> np.ndarray:
    """Las aristas orientadas del ámbito (uno o varios polígonos que no se solapan), relativas a
    la esquina suroeste de ``grid``, con la misma copia de trabajo que usa el recorte."""
    corner = _corner(grid)
    return _concatenate([_ring_edges(_local_rings(part.rings, corner))
                         for part in _parts(scope) or ()])


def _intersection(first: list[np.ndarray], second: list[np.ndarray]) -> np.ndarray:
    """Las aristas orientadas del borde de ``first ∩ second`` (anillos locales normalizados)."""
    if not first or not second:
        return _no_edges()
    p, p_ring = _flatten(first)
    q, q_ring = _flatten(second)
    low, high = q.min(axis=0) - TOLERANCE_M, q.max(axis=0) + TOLERANCE_M
    if np.any(p.max(axis=0) < low) or np.any(p.min(axis=0) > high):
        return _no_edges()
    # (1) vértices a ≤ 1 mm de otro, el del otro; (2) vértices sobre aristas, insertados.
    p, p_ring = _dedupe(_snap(p, q), p_ring)
    if not p.size:
        return _no_edges()
    p_vertices, q_vertices = p, q
    p, p_ring = _insert_near(p, p_ring, q_vertices)
    q, q_ring = _insert_near(q, q_ring, p_vertices)
    p_next, q_next = p[_following(p_ring)], q[_following(q_ring)]
    # (3) cruces propios, el mismo punto en las dos aristas.
    i, j, t, u, cut = _crossings(p, p_next, q, q_next)
    p_cut, p_cut_ring = _splice(p, p_ring, i, t, cut)
    q_cut, q_cut_ring = _splice(q, q_ring, j, u, cut)
    ps, pe = _pieces(p_cut, p_cut_ring)
    qs, qe = _pieces(q_cut, q_cut_ring)
    # (4) trozos comunes; (5) los demás, por su punto medio.
    p_same = _matches(ps, pe, qs, qe)
    p_rest = ~(p_same | _matches(ps, pe, qe, qs))
    q_rest = ~(_matches(qs, qe, ps, pe) | _matches(qe, qs, ps, pe))
    p_in = _inside(0.5 * (ps[p_rest] + pe[p_rest]), q, q_next)
    q_in = _inside(0.5 * (qs[q_rest] + qe[q_rest]), p, p_next)
    starts = np.concatenate([ps[p_same], ps[p_rest][p_in], qs[q_rest][q_in]])
    ends = np.concatenate([pe[p_same], pe[p_rest][p_in], qe[q_rest][q_in]])
    return np.ascontiguousarray(np.stack([starts, ends], axis=1))


def _snap(points: np.ndarray, others: np.ndarray) -> np.ndarray:
    """Cada vértice a ≤ :data:`TOLERANCE_M` de uno de ``others`` pasa a ser el más cercano."""
    i, j = _box_pairs(_boxes(points, points, TOLERANCE_M), _boxes(others, others))
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
    b = points[_following(ring)]
    edge, vertex = _box_pairs(_boxes(a, b, TOLERANCE_M), _boxes(others, others))
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
    return _splice(points, ring, edge[ok], t[ok], point[ok])


def _crossings(pa: np.ndarray, pb: np.ndarray, qa: np.ndarray, qb: np.ndarray
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Los cruces propios de las aristas ``pa→pb`` con las ``qa→qb`` (cada extremo, a más de
    :data:`_ZERO_M` de la recta de la otra y en lados opuestos): sus aristas, su posición en
    cada una (0..1) y el punto, el mismo para las dos."""
    i, j = _box_pairs(_boxes(pa, pb), _boxes(qa, qb))
    a, b, p, q = pa[i], pb[i], qa[j], qb[j]
    r, s = b - a, q - p
    lr, ls = np.hypot(r[:, 0], r[:, 1]), np.hypot(s[:, 0], s[:, 1])
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
    start, end = points, points[_following(ring)]
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


# Pesos de una banda (A5, RF-011-07) ----------------------------------------------------------


def weights(domains: Sequence[np.ndarray], scope: np.ndarray | None, grid: Grid,
            rows: slice) -> Weights:
    """Las entradas (celda, dominio, peso) de la banda de filas ``rows`` de ``grid`` (sin paso):
    ``domains``, las aristas de cada dominio (:func:`domain_edges`); ``scope``, las del ámbito
    (:func:`scope_edges`) o ``None``. Cada celda recibe la fracción exacta de su área dentro de
    cada dominio y, en «Fuera de los dominios» (``domain == count``), la del ámbito (1 sin él)
    menos la suma de las de los dominios; con |peso| ≤ ``coverage.FRACTION_EPSILON``, no se
    da. Por bandas sale bit a bit lo mismo que de una vez."""
    start, stop, step = rows.indices(grid.nrows)
    if step != 1:
        raise ValueError(f"Una banda son filas seguidas, no con paso {step}")
    stop = max(stop, start)
    band = slice(start, stop)
    shape = (stop - start, grid.ncols)
    fraction = None
    if scope is not None:
        fraction = np.zeros(shape)
        cells = band_coverage(scope, grid, band)
        fraction[cells.rows - start, cells.cols] = cells.fraction
    parts: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    if len(domains):
        covered = np.zeros(shape)
        for number, edges in enumerate(domains):
            cells = band_coverage(edges, grid, band)
            covered[cells.rows - start, cells.cols] += cells.fraction
            parts.append((cells.rows, cells.cols,
                          np.full(cells.rows.size, number, dtype=np.int64), cells.fraction))
        outside = (1.0 if fraction is None else fraction) - covered
        found_rows, found_cols = np.nonzero(np.abs(outside) > FRACTION_EPSILON)
        parts.append(((found_rows + start).astype(np.int64), found_cols.astype(np.int64),
                      np.full(found_rows.size, len(domains), dtype=np.int64),
                      np.ascontiguousarray(outside[found_rows, found_cols])))
    columns = [np.concatenate([part[k] for part in parts]) if parts else
               np.zeros(0, dtype=np.float64 if k == 3 else np.int64) for k in range(4)]
    return Weights(start, stop, fraction, columns[0], columns[1], columns[2], columns[3],
                   len(domains))


# Ayudas -----------------------------------------------------------------------------------------


def _value(polygon: Polygon) -> str:
    return "" if polygon.value is None else str(polygon.value)


def _area_text(area: float) -> str:
    """El área (m²) como texto: con dos decimales, o con los que hagan falta (hasta seis) para
    que se vea un área menor que 0,01 m²."""
    decimals = 2
    if 0.0 < abs(area) < 0.01:
        decimals = min(6, 1 - math.floor(math.log10(abs(area))))
    return format_number(area, decimals)


def _corner(grid: Grid) -> np.ndarray:
    return np.array([grid.west, grid.extent.ymin], dtype=np.float64)


def _parts(scope: Polygon | Sequence[Polygon] | None) -> tuple[Polygon, ...] | None:
    if scope is None:
        return None
    if isinstance(scope, Polygon):
        return (scope,)
    return tuple(scope)


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


def _origin(polygons: Sequence[Polygon]) -> np.ndarray:
    """Un origen local cercano a todos los vértices (su mínimo en X y en Y)."""
    lows = [_open(ring).min(axis=0) for polygon in polygons for ring in polygon.rings
            if len(ring)]
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


def _following(ring: np.ndarray) -> np.ndarray:
    """El índice del vértice siguiente en su anillo (los anillos, en bloques seguidos)."""
    following = np.arange(1, ring.size + 1, dtype=np.int64)
    if ring.size:
        last = np.flatnonzero(np.concatenate([ring[1:] != ring[:-1], [True]]))
        following[last] = np.concatenate([[0], last[:-1] + 1])
    return following


def _dedupe(points: np.ndarray, ring: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sin vértices repetidos seguidos y sin anillos de menos de tres vértices."""
    keep = ~np.all(points == points[_following(ring)], axis=1)
    points, ring = points[keep], ring[keep]
    if ring.size:
        enough = np.bincount(ring)[ring] >= 3
        points, ring = points[enough], ring[enough]
    return points, ring


def _splice(points: np.ndarray, ring: np.ndarray, edge: np.ndarray, t: np.ndarray,
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


def _expand(count: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
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
    group, k = _expand(count_a[both] * width)
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
    owner, k = _expand(wide * (iy1 - iy0 + 1))
    return owner, (iy0[owner] + k // wide[owner]) * nx + ix0[owner] + k % wide[owner]


def _box_pairs(box_a: np.ndarray, box_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
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


def _ray_counts(points: np.ndarray, a: np.ndarray, b: np.ndarray, group: np.ndarray | None = None,
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
    owner, k = _expand(last - first + 1)
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
    return _ray_counts(points, a, b)[:, 0] % 2 == 1
