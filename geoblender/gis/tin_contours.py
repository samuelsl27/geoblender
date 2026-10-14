# SPDX-License-Identifier: GPL-3.0-or-later
"""TIN desde curvas de nivel con corrección de triángulos planos (spec 006; plan 006
§5.3.2 y §5.4 A12; RF-006-16; D-6).

Triangular curvas de nivel solo con sus tramos como aristas obligatorias deja triángulos
**planos** (sus tres vértices a la misma cota) en cimas, fondos, divisorias, vaguadas y
collados: «terrazas» que falsean pendientes y volúmenes (inv. 08 §6.3: 47 de 243 en tres
curvas concéntricas). :func:`tin_from_contours` (A12; Thibault y Gold, 2000; Civil 3D
«Minimize Flat Areas»):

1. **Densificar** cada curva a tramos de ≤ ``gis.tin.contour_densify_m`` (5 m) en planta:
   vértices nuevos a + k/n·(b − a), de origen «curva»; los de entrada, bit a bit.
2. **Restricciones** (A7 y A8): los puntos acotados duplicados se resuelven con la política
   elegida y ``gis.breaklines.prepare_constraints`` hace de las curvas aristas obligatorias;
   dos curvas que se cruzan, o un punto acotado sobre una curva, con cotas distintas, son un
   conflicto (``ConflictError``, RF-006-14) y no se triangula.
3. **Antes**: el % de triángulos planos de la triangulación de las curvas solas (sin los
   puntos acotados), la de inv. 08 §6.3; si no se puede triangular (p. ej. una sola curva
   recta), ``None``. El TIN de trabajo lleva siempre los puntos acotados: son datos.
4. **Corrección**, hasta ``gis.tin.flat_max_passes`` (3) pasadas, mientras el % de planos no
   baje de ``gis.tin.max_flat_pct`` (1 %): las **regiones planas** son los triángulos planos
   unidos por aristas que no son de curva (todos a la misma cota z). Una región es
   **abierta** si toca, por una arista que no es de curva, un triángulo con otra cota: el
   vértice de enfrente (de una curva vecina, un punto acotado u otro añadido) es una «cota
   vecina» z′ ≠ z que la región alcanza sin cruzar su curva. Cada triángulo plano de una
   región abierta recibe un punto p en su circuncentro (en su baricentro si el circuncentro
   cae fuera de la región) con z(p) = z + (z′ − z)·d/(d + d′): d, la distancia en planta a
   lo más cercano de la cota z de la región (sus vértices y los tramos de curva que salen de
   ellos) y d′ y z′, los de la cota vecina más cercana (los vértices de enfrente y sus
   tramos de curva). Así, en una vaguada, los planos de dentro de la V bajan hacia la curva
   de abajo, la que alcanzan por la boca, y no suben hacia la de arriba, más cercana en
   planta pero al otro lado de su curva. Los puntos a ≤ :data:`SPACING_FACTOR`·``tol_xy``
   (1 cm) de su curva, de su cota vecina, de un vértice o de otro punto nuevo se descartan.
   Se vuelve a triangular con los puntos añadidos (origen «añadido por corrección», 4). La
   corrección para también cuando no queda ningún plano en una región abierta.
5. **Cimas y fondos sin acotar** (D-6): una región cerrada (rodeada de su curva o del borde
   del TIN) sin punto acotado dentro queda plana; el informe da su número y su área y una
   nota (``gis.flat_regions_unresolved``). También lo son los entrantes de una curva en el
   borde del TIN: un contorno los quita. Una región cerrada con un punto acotado a su misma
   cota (una meseta) es llana según los datos: queda plana y no se cuenta.
6. **Contorno** (RF-006-15): fuera los triángulos con el centroide fuera, como en
   ``build_tin``; los porcentajes son de lo que queda.

Todo en float64: los vértices del TIN son ABSOLUTOS y el triangulador recibe locales
(``core.georef.world_to_local``); los puntos nuevos se calculan en locales y se guardan en
absolutas (``local_to_world``). Las entradas no se modifican.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from ..core.georef import GeoOrigin, local_to_world, world_to_local
from . import params
from .breaklines import (
    SOURCE_ADDED,
    SOURCE_CONTOUR,
    SOURCE_HARD,
    SOURCE_POINT,
    prepare_constraints,
)
from .messages import render
from .points import (
    Breakline,
    DuplicatePolicy,
    PointSet,
    _close_pairs,
    _expand,
    duplicate_tolerances,
    find_duplicates,
    resolve_duplicates,
)
from .ports import Cancelled, Progress, TriangulationError, Triangulator
from .reports import TinReport
from .tin import (
    DEGENERATE_AREA_M2,
    Tin,
    _faces,
    _finish,
    _inside,
    _local_rings,
    _oriented,
    _plan_areas,
    _region,
    _stage,
    sample_tin,
)
from .validate import _roots

__all__ = [
    "DENSIFY_KEY",
    "MAX_FLAT_KEY",
    "PASSES_KEY",
    "SPACING_FACTOR",
    "tin_from_contours",
]

DENSIFY_KEY = "gis.tin.contour_densify_m"
PASSES_KEY = "gis.tin.flat_max_passes"
MAX_FLAT_KEY = "gis.tin.max_flat_pct"

SPACING_FACTOR = 10.0
"""Un punto añadido queda a más de 10 veces la tolerancia en planta (``tol_xy``: 1 mm →
1 cm) de su curva, de su cota vecina, de cualquier vértice y de otro punto nuevo: ni se
funde con nada ni cambia la cota (≤ 1 cm de 5 m de equidistancia → < 1 mm)."""

_PAIR_BUDGET = 1 << 22  # parejas (punto, elemento) por bloque como mucho


def tin_from_contours(
    contours: Sequence[Breakline],
    *,
    spot_heights: PointSet | None = None,
    triangulator: Triangulator,
    origin: GeoOrigin,
    boundary: object = None,
    densify_m: float | None = None,
    max_passes: int | None = None,
    max_flat_pct: float | None = None,
    tol_xy: float | None = None,
    tol_z: float | None = None,
    duplicate_policy: DuplicatePolicy | str = DuplicatePolicy.ASK,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[Tin, TinReport]:
    """El TIN de las curvas de nivel ``contours`` y los puntos acotados ``spot_heights`` con
    la corrección de triángulos planos (RF-006-16; plan A12; ver el módulo), triangulado con
    ``triangulator`` en coordenadas locales respecto a ``origin``.

    ``boundary``: el contorno (una región, como en ``build_tin``); ``densify_m``,
    ``max_passes`` y ``max_flat_pct``: los parámetros ``gis.tin.contour_densify_m``,
    ``gis.tin.flat_max_passes`` y ``gis.tin.max_flat_pct`` (``None``, el valor por
    defecto; uno no válido → ``ParamError`` ``core.param_*`` con la clave); tolerancias y
    política de los puntos acotados duplicados como en ``build_tin``; ``name``, el del TIN en
    los mensajes. Conflictos → ``ConflictError``; un triangulador que no cumple →
    ``TriangulationError``; si el contorno lo quita todo, ``gis.tin_empty``. El informe
    (``TinReport``) lleva el % de planos antes (curvas solas) y después, los puntos añadidos
    y las regiones planas cerradas que quedan (número y área, D-6). Avance por etapas y
    cancelación (``JobCancelled``) entre ellas. ``TypeError`` si las curvas no son
    ``Breakline`` o los puntos acotados no son un ``PointSet``."""
    lines = list(contours)
    if not all(isinstance(line, Breakline) for line in lines):
        raise TypeError("contours son curvas de nivel (Breakline)")
    if spot_heights is None:
        spots = PointSet(np.empty((0, 3), dtype=np.float64), (), (), ())
    elif isinstance(spot_heights, PointSet):
        spots = spot_heights
    else:
        raise TypeError("spot_heights es un PointSet (puntos acotados) o None")
    policy = DuplicatePolicy(duplicate_policy)
    step = float(_setting(DENSIFY_KEY, densify_m))
    passes = int(_setting(PASSES_KEY, max_passes))
    threshold = float(_setting(MAX_FLAT_KEY, max_flat_pct))
    rings = None if boundary is None else _region(boundary, "boundary")
    tol_xy, tol_z = duplicate_tolerances(tol_xy, tol_z)
    input_points = len(spots) + sum(len(line.xyz) for line in lines)

    _stage(progress, cancelled, 0.0, "puntos acotados duplicados")
    merged = 0
    if len(spots):
        labels = [pid or f"#{row}" for pid, row in zip(spots.point_ids, spots.source_rows,
                                                       strict=True)]
        duplicates = find_duplicates(spots.xyz, tol_xy=tol_xy, tol_z=tol_z, ids=labels)
        merged = duplicates.duplicates
        spots = resolve_duplicates(spots, duplicates, policy, name=name)
    _stage(progress, cancelled, 0.05, "curvas de nivel")
    prepared = prepare_constraints(spots, [_densify(line, step) for line in lines],
                                   tol_xy=tol_xy, tol_z=tol_z, name=name)
    xyz = prepared.xyz
    edges = prepared.edges
    source = prepared.vertex_source.copy()
    source[source == SOURCE_HARD] = SOURCE_CONTOUR
    xy = world_to_local(xyz[:, :2], origin)
    local_rings = None if rings is None else _local_rings(rings, origin)
    free = source == SOURCE_POINT
    free[edges.ravel()] = False  # un punto acotado que parte un tramo es de la curva

    before = None
    if free.any():
        _stage(progress, cancelled, 0.1, "triangulación de las curvas solas")
        before = _contours_only(triangulator, xy, xyz[:, 2], edges, ~free, local_rings)
    _stage(progress, cancelled, 0.2, f"triangulación de {len(xy)} vértices")
    faces = _triangulate(triangulator, xy, edges)
    if not free.any():
        before = _flat_pct(xyz[:, 2], faces, _kept(xy, faces, local_rings))

    gap = SPACING_FACTOR * tol_xy
    for number in range(passes):
        keep = _kept(xy, faces, local_rings)
        pct = _flat_pct(xyz[:, 2], faces, keep)
        if pct is None or pct < threshold:
            break
        new_xy, new_z = _correction_points(xy, xyz[:, 2], faces, edges, keep, gap)
        if not len(new_z):
            break
        _stage(progress, cancelled, 0.3 + 0.6 * number / passes,
               f"corrección de triángulos planos, pasada {number + 1} de {passes}")
        xyz = np.concatenate([xyz, np.column_stack([local_to_world(new_xy, origin), new_z])])
        source = np.concatenate([source, np.full(len(new_z), SOURCE_ADDED, dtype=np.uint8)])
        xy = world_to_local(xyz[:, :2], origin)
        faces = _triangulate(triangulator, xy, edges)

    _stage(progress, cancelled, 0.95, "filtros")
    final = replace(prepared, xyz=np.ascontiguousarray(xyz), vertex_source=source)
    tin, report = _finish(final, faces, xy, origin=origin, boundary=rings, holes=[],
                          max_edge=None, name=name, triangulator=triangulator.name)
    count, area = _unresolved(tin)
    notes = ()
    if count:
        notes = (render("gis.flat_regions_unresolved", tin=name, value=count,
                        area=round(area, 1)),)
    report = replace(
        report,
        input_points=input_points,
        duplicates_merged=merged + prepared.merged,
        flat_pct_before=before,
        points_added=int(np.count_nonzero(tin.vertex_source == SOURCE_ADDED)),
        unresolved_flat_regions=count,
        unresolved_flat_area_m2=area,
        notes=notes,
    )
    _stage(progress, None, 1.0, "terminado")
    return tin, report


def _setting(key: str, value: object) -> params.ParamValue:
    """El valor del parámetro ``key``: el de ``gis/params.py`` si ``value`` es ``None``;
    si no, comprobado (``ParamError`` ``core.param_*`` con la clave como campo)."""
    definition = params.param(key)
    return definition.default if value is None else definition.check(value)


def _densify(line: Breakline, step: float) -> Breakline:
    """La curva ``line`` con tramos de ≤ ``step`` m en planta (cada tramo de longitud L, en
    ⌈L/step⌉ trozos iguales): los vértices de entrada, bit a bit; los nuevos,
    a + k/n·(b − a). Siempre dura: una curva es una restricción."""
    xyz = line.xyz
    start, end = xyz[:-1], xyz[1:]
    length = np.hypot(end[:, 0] - start[:, 0], end[:, 1] - start[:, 1])
    pieces = np.maximum(1, np.ceil(length / step)).astype(np.int64)
    if (pieces == 1).all():
        return Breakline(line.line_id, xyz, hard=True, code=line.code,
                         source_rows=line.source_rows)
    segment, k = _expand(np.zeros(len(pieces), dtype=np.int64), pieces)
    t = (k / pieces[segment])[:, None]
    dense = start[segment] + t * (end - start)[segment]
    dense[k == 0] = start[segment[k == 0]]  # los de entrada, tal cual
    return Breakline(line.line_id, np.concatenate([dense, xyz[-1:]]), hard=True,
                     code=line.code)


def _triangulate(triangulator: Triangulator, xy: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Los triángulos (int64, antihorarios) de ``xy`` locales con las aristas ``edges``."""
    faces = _faces(triangulator.triangulate(xy, edges), len(xy), triangulator.name)
    return _oriented(xy, faces)


def _kept(xy: np.ndarray, faces: np.ndarray, rings: list[np.ndarray] | None) -> np.ndarray:
    """Los triángulos que deja el contorno (centroide dentro), como ``tin._finish``."""
    if rings is None:
        return np.ones(len(faces), dtype=bool)
    return _inside(xy[faces].mean(axis=1), rings)


def _flat_mask(z: np.ndarray, faces: np.ndarray) -> np.ndarray:
    corner = z[faces]
    return (corner[:, 0] == corner[:, 1]) & (corner[:, 1] == corner[:, 2])


def _flat_pct(z: np.ndarray, faces: np.ndarray, keep: np.ndarray) -> float | None:
    """El % de triángulos planos de los que deja el contorno (``None`` si no queda
    ninguno)."""
    kept = int(np.count_nonzero(keep))
    if not kept:
        return None
    return 100.0 * int(np.count_nonzero(_flat_mask(z, faces) & keep)) / kept


def _contours_only(triangulator: Triangulator, xy: np.ndarray, z: np.ndarray,
                   edges: np.ndarray, base: np.ndarray,
                   rings: list[np.ndarray] | None) -> float | None:
    """El % de planos de la triangulación de los vértices ``base`` (las curvas, sin los
    puntos acotados sueltos): ``None`` si no se pueden triangular solos."""
    chosen = np.flatnonzero(base)
    index = np.full(len(xy), -1, dtype=np.int64)
    index[chosen] = np.arange(chosen.size)
    try:
        faces = _triangulate(triangulator, np.ascontiguousarray(xy[chosen]),
                             index[edges].astype(np.int32).reshape(-1, 2))
    except TriangulationError:
        return None
    faces = chosen[faces]
    return _flat_pct(z, faces, _kept(xy, faces, rings))


# Regiones planas ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Regions:
    """Las regiones planas de una triangulación: la de cada triángulo (−1 si no es plano o
    el contorno lo quita), si cada región es abierta y, por cada arista que la abre, su
    región y el vértice de enfrente (la cota vecina)."""

    face_region: np.ndarray
    is_open: np.ndarray
    open_region: np.ndarray
    open_vertex: np.ndarray


def _flat_regions(xy: np.ndarray, z: np.ndarray, faces: np.ndarray, edges: np.ndarray,
                  keep: np.ndarray) -> _Regions:
    """Las regiones planas (ver el módulo) de los triángulos ``faces`` (int64) que deja
    ``keep``: componentes de los planos unidos por aristas que no son de ``edges``
    (unión–búsqueda); una arista de un plano que no es de curva y tiene al otro lado (en un
    triángulo que el contorno deja) un vértice con otra cota abre la región. Un triángulo
    degenerado (área en planta < ``DEGENERATE_AREA_M2``) no es de ninguna región: las
    astillas de 10⁻¹⁰ m² que deja en el borde del TIN un tramo recto densificado (vértices
    casi alineados) no son una zona plana."""
    count, size = len(faces), len(z)
    flat = keep & _flat_mask(z, faces) & (_plan_areas(xy, faces) >= DEGENERATE_AREA_M2)
    tail = faces.ravel()
    head = np.roll(faces, -1, axis=1).ravel()
    across = np.roll(faces, 1, axis=1).ravel()  # el vértice de enfrente de cada arista
    owner = np.repeat(np.arange(count, dtype=np.int64), 3)
    key = np.minimum(tail, head) * size + np.maximum(tail, head)
    order = np.argsort(key, kind="stable")
    paired = np.flatnonzero(key[order][1:] == key[order][:-1])
    one, two = order[paired], order[paired + 1]
    twin = np.full(3 * count, -1, dtype=np.int64)
    twin[one] = two
    twin[two] = one
    pairs = edges.astype(np.int64).reshape(-1, 2)
    constrained = np.isin(key, np.minimum(pairs[:, 0], pairs[:, 1]) * size
                          + np.maximum(pairs[:, 0], pairs[:, 1]))
    flat_faces = np.flatnonzero(flat)
    index = np.full(count, -1, dtype=np.int64)
    index[flat_faces] = np.arange(flat_faces.size)
    link = flat[owner[one]] & flat[owner[two]] & ~constrained[one]
    roots = _roots(flat_faces.size, index[owner[one[link]]], index[owner[two[link]]])
    first, label = np.unique(roots, return_inverse=True)
    face_region = np.full(count, -1, dtype=np.int64)
    face_region[flat_faces] = label
    half = np.flatnonzero(flat[owner] & (twin >= 0) & ~constrained)
    vertex = across[twin[half]]
    opening = keep[owner[twin[half]]] & (z[vertex] != z[across[half]])
    half, vertex = half[opening], vertex[opening]
    open_region = face_region[owner[half]]
    is_open = np.zeros(first.size, dtype=bool)
    is_open[open_region] = True
    return _Regions(face_region, is_open, open_region, vertex)


def _unresolved(tin: Tin) -> tuple[int, float]:
    """Las regiones planas cerradas de ``tin`` sin ningún punto acotado (cimas y fondos sin
    acotar, D-6): número y área en planta (m²). Una con un punto acotado a su misma cota es
    llana según los datos (una meseta) y no se cuenta."""
    faces = tin.faces.astype(np.int64)
    xy = tin.vertices[:, :2]
    regions = _flat_regions(xy, tin.vertices[:, 2], faces, tin.constraint_edges,
                            np.ones(len(faces), dtype=bool))
    region = regions.face_region
    flat = np.flatnonzero(region >= 0)
    spotted = np.zeros(regions.is_open.size, dtype=bool)
    with_spot = (tin.vertex_source[faces[flat]] == SOURCE_POINT).any(axis=1)
    spotted[region[flat[with_spot]]] = True
    unresolved = ~regions.is_open & ~spotted
    if not unresolved.any():
        return 0, 0.0
    inside = flat[unresolved[region[flat]]]
    area = _plan_areas(xy, faces[inside])
    return int(np.count_nonzero(unresolved)), float(area.sum())


# Puntos de corrección ----------------------------------------------------------------------


def _correction_points(xy: np.ndarray, z: np.ndarray, faces: np.ndarray, edges: np.ndarray,
                       keep: np.ndarray, gap: float) -> tuple[np.ndarray, np.ndarray]:
    """Los puntos que se añaden en una pasada (A12; ver el módulo): posición ``(k, 2)`` en
    el mismo sistema que ``xy`` (locales) y cota ``(k,)``. ``faces`` int64; ``keep``, los
    triángulos que deja el contorno; ``gap``, la distancia mínima (m)."""
    faces = faces.astype(np.int64)
    regions = _flat_regions(xy, z, faces, edges, keep)
    chosen = np.flatnonzero(regions.face_region >= 0)
    chosen = chosen[regions.is_open[regions.face_region[chosen]]]
    if not chosen.size:
        return np.empty((0, 2), dtype=np.float64), np.empty(0, dtype=np.float64)
    label = regions.face_region[chosen]
    corners = xy[faces[chosen]]
    center = _circumcenters(corners)
    inside = _in_regions(corners, label, center)
    candidate = np.where(inside[:, None], center, corners.mean(axis=1))
    level = z[faces[chosen, 0]]
    neighbours = _level_neighbours(edges, z)
    own = _features(np.repeat(label, 3), faces[chosen].ravel(), xy, z, neighbours)
    near, _level = _nearest(candidate, label, *own)
    reached = _features(regions.open_region, regions.open_vertex, xy, z, neighbours)
    far, other = _nearest(candidate, label, *reached)
    with np.errstate(invalid="ignore", divide="ignore"):
        height = level + (other - level) * near / (near + far)
    usable = (near > gap) & (far > gap) & np.isfinite(height)
    candidate, height = candidate[usable], height[usable]
    spaced = _spaced(xy, candidate, gap)
    return np.ascontiguousarray(candidate[spaced]), np.ascontiguousarray(height[spaced])


def _circumcenters(corners: np.ndarray) -> np.ndarray:
    """El circuncentro de cada triángulo ``(c, 3, 2)`` (no finito si es degenerado), con
    las diferencias respecto a su primer vértice."""
    a = corners[:, 0]
    b = corners[:, 1] - a
    c = corners[:, 2] - a
    bb = np.einsum("ij,ij->i", b, b)
    cc = np.einsum("ij,ij->i", c, c)
    den = 2.0 * (b[:, 0] * c[:, 1] - b[:, 1] * c[:, 0])
    with np.errstate(invalid="ignore", divide="ignore"):
        ux = (c[:, 1] * bb - b[:, 1] * cc) / den
        uy = (b[:, 0] * cc - c[:, 0] * bb) / den
    return a + np.column_stack([ux, uy])


def _in_regions(corners: np.ndarray, label: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    """Si cada punto ``candidate[i]`` cae en algún triángulo de su región ``label[i]``:
    muestreo de un TIN con los triángulos ``corners`` sueltos y la región como cota (la
    misma regla que ``sample_tin``: el primero que lo contiene, borde incluido)."""
    count = len(corners)
    vertices = np.column_stack([corners.reshape(-1, 2), np.repeat(label.astype(np.float64), 3)])
    probe = Tin(vertices=vertices,
                faces=np.arange(3 * count, dtype=np.int32).reshape(-1, 3),
                constraint_edges=np.empty((0, 2), dtype=np.int32),
                vertex_source=np.zeros(3 * count, dtype=np.uint8))
    found = sample_tin(probe, np.ascontiguousarray(candidate, dtype=np.float64))
    with np.errstate(invalid="ignore"):
        return np.rint(found) == label


def _level_neighbours(edges: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Los tramos de curva por vértice (los dos extremos a la misma cota): desplazamientos
    ``start`` (``len(z) + 1``) y el otro extremo de cada tramo."""
    pairs = edges.astype(np.int64).reshape(-1, 2)
    pairs = pairs[z[pairs[:, 0]] == z[pairs[:, 1]]]
    tail = np.concatenate([pairs[:, 0], pairs[:, 1]])
    head = np.concatenate([pairs[:, 1], pairs[:, 0]])
    order = np.argsort(tail, kind="stable")
    start = np.searchsorted(tail[order], np.arange(len(z) + 1), side="left")
    return start, head[order]


def _features(region: np.ndarray, vertex: np.ndarray, xy: np.ndarray, z: np.ndarray,
              neighbours: tuple[np.ndarray, np.ndarray],
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Lo que una región «ve» de una cota: los vértices ``vertex`` de cada región
    ``region`` (como puntos) y los tramos de curva que salen de ellos. Región, extremos
    ``a`` y ``b`` (iguales en un punto) y cota de cada elemento."""
    size = len(z)
    unique = np.unique(region * size + vertex)
    region, vertex = np.divmod(unique, size)
    start, head = neighbours
    owner, position = _expand(start[vertex], start[vertex + 1])
    return (np.concatenate([region, region[owner]]),
            np.concatenate([xy[vertex], xy[vertex[owner]]]),
            np.concatenate([xy[vertex], xy[head[position]]]),
            np.concatenate([z[vertex], z[vertex[owner]]]))


def _nearest(candidate: np.ndarray, label: np.ndarray, region: np.ndarray, a: np.ndarray,
             b: np.ndarray, level: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada punto ``candidate[i]``, la distancia en planta al elemento más cercano de
    su región ``label[i]`` (segmento ``a``–``b``) y la cota de ese elemento (∞ y NaN si no
    hay ninguno), por bloques de como mucho :data:`_PAIR_BUDGET` parejas."""
    order = np.argsort(region, kind="stable")
    sorted_region = region[order]
    start = np.searchsorted(sorted_region, label, side="left")
    stop = np.searchsorted(sorted_region, label, side="right")
    best = np.full(len(candidate), np.inf)
    best_level = np.full(len(candidate), np.nan)
    sizes = stop - start
    cuts = np.searchsorted(np.cumsum(sizes),
                           np.arange(_PAIR_BUDGET, int(sizes.sum()), _PAIR_BUDGET),
                           side="left")
    for part in np.split(np.arange(len(candidate)), cuts + 1):
        owner, position = _expand(start[part], stop[part])
        if not owner.size:
            continue
        who = part[owner]
        element = order[position]
        distance = _distance(candidate[who], a[element], b[element])
        rank = np.lexsort((distance, who))
        first = rank[np.concatenate([[True], who[rank][1:] != who[rank][:-1]])]
        best[who[first]] = distance[first]
        best_level[who[first]] = level[element[first]]
    return best, best_level


def _distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La distancia en planta de cada ``p`` a su segmento ``a``–``b`` (un punto si
    ``a`` = ``b``)."""
    d = b - a
    dd = np.einsum("ij,ij->i", d, d)
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(dd > 0.0, np.einsum("ij,ij->i", p - a, d) / dd, 0.0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(p[:, 0] - (a[:, 0] + t * d[:, 0]), p[:, 1] - (a[:, 1] + t * d[:, 1]))


def _spaced(xy: np.ndarray, candidate: np.ndarray, gap: float) -> np.ndarray:
    """Qué puntos nuevos se quedan: ninguno a ≤ ``gap`` de un vértice y, de los que están a
    ≤ ``gap`` entre sí (componentes), solo el primero."""
    count, new = len(xy), len(candidate)
    if not new:
        return np.zeros(0, dtype=bool)
    first, second = _close_pairs(np.concatenate([xy, candidate]), gap)
    crowded = np.zeros(new, dtype=bool)
    mixed = (first < count) & (second >= count)
    crowded[second[mixed] - count] = True
    both = first >= count
    roots = _roots(new, first[both] - count, second[both] - count)
    return ~crowded & (roots == np.arange(new))
