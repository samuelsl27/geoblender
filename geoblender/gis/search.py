# SPDX-License-Identifier: GPL-3.0-or-later
"""La búsqueda de intocables: la distancia exacta de cada entidad de unas capas a un sector
(spec 012, RF-012-08; plan 012 A6 y D-5).

:func:`search_steps` recorre las capas (``gis.vector.FeatureLayer``: puntos, líneas o polígonos)
por trozos de entidades y devuelve, en el último ``Progress``, cada entidad a una distancia del
sector ≤ ``distance_m`` (:class:`Found`: su capa, su número, su distancia en m y sus atributos),
en el orden de las capas y, en cada una, en el de sus entidades.

**A6.** La distancia es 0 si un vértice de la entidad cae dentro del sector, si uno del sector
(el primero de cada anillo) cae dentro de un polígono de la entidad o si dos aristas se cortan;
si no, la menor de las distancias entre sus segmentos y los del sector
(``gis.polygons.segment_distance``; un punto es un segmento nulo). Dentro y fuera, por par-impar
sobre todos los anillos (el sector puede tener varias partes y huecos; un polígono con un hueco
que rodea el sector no lo contiene). Las parejas de segmentos se filtran por sus cajas agrandadas
la distancia (por cubetas), y, con ``prefilter`` (por defecto), las entidades por su caja frente
a la del sector agrandada la distancia: el prefiltro solo ahorra trabajo, no cambia el resultado.

Todo en coordenadas locales float64 respecto a la esquina suroeste del sector (restar un origen
cercano es exacto). Las entradas solo se leen. Python puro con numpy (nivel 2).
"""

from __future__ import annotations

import math
import time
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.project.model import Progress
from .polygons import _box_pairs, _boxes, _inside, _ray_counts, segment_distance
from .vector import FeatureLayer

__all__ = [
    "FEATURES_PER_STEP",
    "STEP_BUDGET_S",
    "VERTICES_PER_STEP",
    "Found",
    "search",
    "search_steps",
]

STEP_BUDGET_S = 0.05
"""Duración máxima (s) de un paso por defecto (RNF-012-06)."""

FEATURES_PER_STEP = 256
"""Entidades de un trozo, como mucho."""

VERTICES_PER_STEP = 4096
"""Vértices de un trozo, aproximadamente (un trozo cierra al pasarlos)."""

_WORK_FRACTION = 0.5
"""Fracción del presupuesto que se llena de trozos antes de ceder el paso."""

_PHASE = "search"


@dataclass(frozen=True, slots=True)
class Found:
    """Una entidad hallada (RF-012-08): su capa (la clave de las capas o su posición), su
    número en la capa, su distancia al sector (m; 0 si lo toca o se solapan) y sus atributos."""

    layer: str | int
    fid: int
    distance_m: float
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _Sector:
    origin: np.ndarray
    edges: np.ndarray            # (n, 2, 2) locales
    boxes: np.ndarray            # (n, 4) de las aristas
    firsts: np.ndarray           # (r, 2) el primer vértice de cada anillo
    box: np.ndarray              # (4,) la del sector


def search_steps(sector_rings: Sequence[np.ndarray],
                 layers: Mapping[str, FeatureLayer] | Sequence[FeatureLayer],
                 distance_m: float, *, budget_s: float = STEP_BUDGET_S,
                 features_per_step: int = FEATURES_PER_STEP,
                 prefilter: bool = True) -> Iterator[Progress]:
    """Los pasos de buscar, en ``layers`` (un diccionario nombre → capa o una lista, cuyas
    entidades se nombran por su posición), las entidades a ≤ ``distance_m`` (m) del sector de
    anillos absolutos ``sector_rings`` (véase el módulo), de ``budget_s`` como mucho. El último
    ``Progress`` lleva ``tuple[Found, ...]``. ``ValueError`` si un argumento no vale."""
    if isinstance(distance_m, bool) or not isinstance(distance_m, int | float) or not (
            math.isfinite(distance_m) and distance_m >= 0.0):
        raise ValueError(f"la distancia de búsqueda es un número finito ≥ 0 m, no {distance_m!r}")
    if isinstance(budget_s, bool) or not isinstance(budget_s, int | float) or not budget_s > 0:
        raise ValueError(f"el presupuesto de un paso es un número positivo, no {budget_s!r}")
    if isinstance(features_per_step, bool) or not isinstance(features_per_step, int) or (
            features_per_step < 1):
        raise ValueError(f"un trozo tiene al menos una entidad, no {features_per_step!r}")
    named = _named(layers)
    sector = _sector(sector_rings)
    work = _work(sector, named, float(distance_m), features_per_step, bool(prefilter))
    total = sum(len(found) for _, found in named)
    return _paced(work, float(budget_s), total)


def search(sector_rings: Sequence[np.ndarray],
           layers: Mapping[str, FeatureLayer] | Sequence[FeatureLayer],
           distance_m: float, **options: Any) -> tuple[Found, ...]:
    """:func:`search_steps` de una vez."""
    result: tuple[Found, ...] = ()
    for progress in search_steps(sector_rings, layers, distance_m, **options):
        if progress.result is not None:
            result = progress.result  # type: ignore[assignment]
    return result


# --- Preparación ------------------------------------------------------------------------------


def _named(layers: Mapping[str, FeatureLayer] | Sequence[FeatureLayer]
           ) -> list[tuple[str | int, FeatureLayer]]:
    if isinstance(layers, Mapping):
        items: list[tuple[str | int, Any]] = list(layers.items())
    elif isinstance(layers, Sequence) and not isinstance(layers, str | bytes):
        items = list(enumerate(layers))
    else:
        raise TypeError(f"las capas son un diccionario o una lista, no {type(layers).__name__}")
    for key, found in items:
        if not isinstance(found, FeatureLayer):
            raise TypeError(f"la capa {key!r} es una FeatureLayer, no {type(found).__name__}")
    return items


def _open_ring(ring: object) -> np.ndarray:
    points = np.asarray(ring, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2:
        raise ValueError(f"un anillo es un array (k, 2) de vértices, no de forma {points.shape}")
    points = points[:, :2]
    if not np.all(np.isfinite(points)):
        raise ValueError("un anillo del sector tiene vértices no finitos")
    if len(points) > 1 and np.array_equal(points[0], points[-1]):
        points = points[:-1]
    return points


def _sector(sector_rings: Sequence[np.ndarray]) -> _Sector:
    rings = [_open_ring(ring) for ring in sector_rings]
    rings = [ring for ring in rings if len(ring) >= 3]
    if not rings:
        raise ValueError("el sector no tiene ningún anillo de tres vértices o más")
    origin = np.min([ring.min(axis=0) for ring in rings], axis=0)
    local = [ring - origin for ring in rings]
    edges = np.ascontiguousarray(np.concatenate(
        [np.stack([ring, np.roll(ring, -1, axis=0)], axis=1) for ring in local]))
    points = np.concatenate(local)
    box = np.concatenate([points.min(axis=0), points.max(axis=0)])
    return _Sector(origin, edges, _boxes(edges[:, 0], edges[:, 1]),
                   np.array([ring[0] for ring in local]), box)


# --- El trabajo -------------------------------------------------------------------------------


def _work(sector: _Sector, layers: list[tuple[str | int, FeatureLayer]], distance: float,
          features_per_step: int, prefilter: bool) -> Generator[None, None, tuple[Found, ...]]:
    found: list[Found] = []
    for key, layer in layers:
        start, count = 0, len(layer)
        while start < count:
            stop, vertices = start, 0
            while stop < count and stop - start < features_per_step and (
                    vertices < VERTICES_PER_STEP):
                vertices += sum(len(path) for part in layer.parts[stop] for path in part)
                stop += 1
            distances = _chunk(sector, layer, range(start, stop), distance, prefilter)
            for offset, value in enumerate(distances.tolist()):
                if value <= distance:
                    index = start + offset
                    found.append(Found(key, layer.fids[index], float(value),
                                       MappingProxyType({name: column[index] for name, column
                                                         in layer.values.items()})))
            start = stop
            yield None
    return tuple(found)


def _chunk(sector: _Sector, layer: FeatureLayer, indices: range, distance: float,
           prefilter: bool) -> np.ndarray:
    """La distancia (m) al sector de las entidades ``indices`` (``inf`` si es mayor que
    ``distance`` y no hizo falta calcularla)."""
    count = len(indices)
    result = np.full(count, np.inf)
    paths: list[np.ndarray] = []
    owners: list[int] = []
    for offset, index in enumerate(indices):
        for part in layer.parts[index]:
            for path in part:
                paths.append(path)
                owners.append(offset)
    if not paths:
        return result
    lengths = np.array([len(path) for path in paths], dtype=np.int64)
    vertices = np.concatenate(paths)[:, :2] - sector.origin
    path_owner = np.array(owners, dtype=np.int64)
    vertex_owner = np.repeat(path_owner, lengths)
    vertex_path = np.repeat(np.arange(len(paths)), lengths)

    keep = np.ones(count, dtype=bool)
    if prefilter:
        low = np.full((count, 2), np.inf)
        high = np.full((count, 2), -np.inf)
        np.minimum.at(low, vertex_owner, vertices)
        np.maximum.at(high, vertex_owner, vertices)
        keep = ((low[:, 0] <= sector.box[2] + distance) & (high[:, 0] >= sector.box[0] - distance)
                & (low[:, 1] <= sector.box[3] + distance)
                & (high[:, 1] >= sector.box[1] - distance))
        if not keep.any():
            return result
        chosen = keep[vertex_owner]
        vertices, vertex_owner, vertex_path = (vertices[chosen], vertex_owner[chosen],
                                               vertex_path[chosen])

    segments, segment_owner = _segments(layer.kind, vertices, vertex_owner, vertex_path)

    # Dentro: un vértice de la entidad en el sector, o uno del sector en un polígono de ella.
    inside = np.zeros(count, dtype=bool)
    hit = _inside(vertices, sector.edges[:, 0], sector.edges[:, 1])
    inside[vertex_owner[hit]] = True
    if layer.kind == "polygon":
        counts = _ray_counts(sector.firsts, segments[:, 0], segments[:, 1], segment_owner, count)
        inside |= np.any(counts % 2 == 1, axis=0)
    result[inside] = 0.0

    # Fuera: la menor distancia entre segmentos, con las parejas cuyas cajas agrandadas se tocan.
    pending = ~inside[segment_owner]
    if pending.any():
        which = np.flatnonzero(pending)
        mine = segments[which]
        a, b = _box_pairs(_boxes(mine[:, 0], mine[:, 1], distance), sector.boxes)
        if a.size:
            values = segment_distance(mine[a], sector.edges[b])
            np.minimum.at(result, segment_owner[which[a]], values)
    result[~keep] = np.inf
    return result


def _segments(kind: str, vertices: np.ndarray, owner: np.ndarray, path: np.ndarray
              ) -> tuple[np.ndarray, np.ndarray]:
    """Los segmentos locales de las entidades y su dueño: un punto, nulo; un camino, sus
    tramos; un anillo, sus aristas (cerrado, sin repetir el primer vértice)."""
    if kind == "point" or not len(vertices):
        return np.stack([vertices, vertices], axis=1), owner
    same = path[1:] == path[:-1]
    if kind == "line":
        starts = np.flatnonzero(same)
        segments = np.stack([vertices[starts], vertices[starts + 1]], axis=1)
        # Un camino de un solo vértice es un punto.
        first = np.r_[True, ~same]
        last = np.r_[~same, True]
        lone = np.flatnonzero(first & last)
        if lone.size:
            segments = np.concatenate([segments, np.stack([vertices[lone], vertices[lone]],
                                                          axis=1)])
            starts = np.concatenate([starts, lone])
        return np.ascontiguousarray(segments), owner[starts]
    # Polígonos: cada anillo cerrado; sin el vértice repetido al final.
    first = np.r_[True, ~same]
    ring_start = np.maximum.accumulate(np.where(first, np.arange(len(path)), 0))
    last = np.r_[~same, True]
    closing_dup = last & np.all(vertices == vertices[ring_start], axis=1) & ~first
    keep = ~closing_dup
    vertices, owner, path = vertices[keep], owner[keep], path[keep]
    same = path[1:] == path[:-1]
    first = np.r_[True, ~same]
    ring_start = np.maximum.accumulate(np.where(first, np.arange(len(path)), 0))
    nxt = np.r_[np.arange(1, len(path)), 0]
    last = np.r_[~same, True]
    nxt = np.where(last, ring_start, nxt)
    return np.ascontiguousarray(np.stack([vertices, vertices[nxt]], axis=1)), owner


# --- Los pasos --------------------------------------------------------------------------------


def _paced(work: Generator[None, None, tuple[Found, ...]], budget_s: float,
           total: int) -> Iterator[Progress]:
    target = budget_s * _WORK_FRACTION
    steps = 0
    with closing(work):  # cerrar los pasos cierra el trabajo
        while True:
            start = last = time.perf_counter()
            slowest = 0.0
            try:
                while True:
                    next(work)
                    steps += 1
                    now = time.perf_counter()
                    slowest = max(slowest, now - last)
                    last = now
                    if now - start + slowest > target:
                        break
            except StopIteration as stop:
                result: tuple[Found, ...] = stop.value
                break
            yield Progress(_PHASE, steps, max(steps + 1, 1), "Buscando intocables…")
    yield Progress(_PHASE, max(steps, 1), max(steps, 1),
                   f"Búsqueda: {len(result)} de {total} entidades a la distancia de búsqueda",
                   result=result)
