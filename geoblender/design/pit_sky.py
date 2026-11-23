# SPDX-License-Identifier: GPL-3.0-or-later
"""La línea de cielo de la corta (spec 018, T19; HU-018-4; RF-018-29; CE-018-07; plan 018 §5.4 A11, §5.7 P-9).

La **línea de cielo** es donde la corta corta el terreno de la partida: las polilíneas 3D donde la diferencia de cotas ``partida − corta`` vale
0, con la cota del terreno en cada vértice. Sale de :func:`~geoblender.gis.contours.contours_from_raster` (P-9; el motor de curvas no se toca)
sobre esa diferencia **acotada a ±0,9 m** con intervalo de 1 m, de modo que la única cota que la corta es la 0.

**La corta que se compara** (``design``) es la de las polilíneas sola, dentro del recinto de la polilínea más externa y ``NaN`` fuera de él
(``PitSurface.stepped``), no la compuesta con la partida: en esa la diferencia vale 0 en todo lo no excavado y no cruza nada. Una celda con
dato en la partida y sin él en la corta es **exterior** a la corta: nada se excava ahí. Para que la línea no se detenga a medio camino cuando
la corta toca el terreno justo en el borde del recinto (la corta descendente, cuya cresta es el límite), las celdas exteriores contiguas a las
del recinto toman el **espejo** de la profundidad vecina (``−`` su media, nunca positiva: donde la corta queda por encima del terreno no se
inventa un cruce) y la línea cae a media celda del borde del recinto; las demás exteriores valen −0,9. Las máscaras no intervienen: la línea
de cielo no es una restricción y no declara nada (RF-018-29).

**Cifras** (CALCULADO): partes, longitud en planta y en 3D (m), área que encierra (m²; los anillos cerrados con la regla par-impar, así que
una isla se resta), cotas mínima y máxima (m) y la distancia mínima (m, con su lugar) al límite legal y al perímetro de actuación, por
:func:`~geoblender.gis.polygons.segment_distance` (0 si se cortan). Sin línea, ninguna de las cotas ni de las distancias (``None``).

Las entradas no se modifican. Perezoso (RNF-001-03): nada del arranque lo importa. Python puro con numpy."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from ..gis.contours import contours_from_raster
from ..gis.grid import Grid
from ..gis.polygons import segment_distance
from ..gis.ports import Cancelled, Progress
from ..gis.raster import Raster, sample

__all__ = ["BAND_M", "SkyDistance", "SkyPart", "Skyline", "limit_distances", "skyline"]

BAND_M: float = 0.9
"""El valor absoluto al que se acota la diferencia de cotas (m): menor que el intervalo de 1 m, para que solo cruce la cota 0."""
_PAIR_BUDGET = 1 << 20
"""Parejas de segmentos por bloque de la distancia."""


@dataclass(frozen=True, slots=True, eq=False)
class SkyPart:
    """Una parte de la línea de cielo: ``xyz`` float64 ``(n ≥ 2, 3)`` ABSOLUTO con Z la cota del terreno (de solo lectura) y ``closed`` (el primer
    vértice no se repite al final)."""

    xyz: np.ndarray
    closed: bool

    def __post_init__(self) -> None:
        self.xyz.flags.writeable = False


@dataclass(frozen=True, slots=True, eq=False)
class SkyDistance:
    """La distancia mínima ``distance_m`` (m, en planta) de la línea a un borde y su lugar: ``on_line`` (x, y, z absolutos del punto de la línea;
    la Z es la del terreno) y ``on_boundary`` (x, y absolutos del punto del borde)."""

    distance_m: float
    on_line: np.ndarray
    on_boundary: np.ndarray


@dataclass(frozen=True, slots=True, eq=False)
class Skyline:
    """La línea de cielo y sus cifras: ``parts``, ``n_parts``, ``length_m`` (en planta), ``length3d_m``, ``area_m2``, ``z_min_m`` y ``z_max_m``
    (``None`` sin línea) y ``legal`` y ``perimeter`` (:class:`SkyDistance`, o ``None`` si no hay límite o no hay línea)."""

    parts: tuple[SkyPart, ...]
    length_m: float
    length3d_m: float
    area_m2: float
    z_min_m: float | None
    z_max_m: float | None
    legal: SkyDistance | None = None
    perimeter: SkyDistance | None = None

    @property
    def n_parts(self) -> int:
        return len(self.parts)


# --- La diferencia acotada ---------------------------------------------------------------------------------------------------


def _neighbours(values: np.ndarray) -> np.ndarray:
    """La suma de los cuatro vecinos de cada celda (0 fuera de la rejilla)."""
    padded = np.pad(values, 1)
    return padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:]


def _difference(start: np.ndarray, design: np.ndarray) -> np.ndarray:
    """``partida − corta`` acotada a ±:data:`BAND_M`, con el espejo de las celdas exteriores contiguas (ver el módulo); ``NaN`` sin partida."""
    has_start = np.isfinite(start)
    inside = has_start & np.isfinite(design)
    gap = np.full(start.shape, np.nan)
    gap[inside] = np.clip(start[inside] - design[inside], -BAND_M, BAND_M)
    outside = has_start & ~inside
    deep = np.where(inside, np.maximum(np.nan_to_num(gap), 0.0), 0.0)
    count = _neighbours(inside.astype(np.float64))
    mean = np.divide(_neighbours(deep), count, out=np.zeros_like(deep), where=count > 0.0)
    near = outside & (count > 0.0)
    gap[outside] = -BAND_M
    gap[near] = -np.maximum(mean[near], 1e-3)
    return gap


# --- Las cifras --------------------------------------------------------------------------------------------------------------


def _contains(ring: np.ndarray, point: np.ndarray) -> bool:
    """Si ``point`` está dentro de ``ring`` (regla del rayo; anillo implícitamente cerrado)."""
    x, y = ring[:, 0], ring[:, 1]
    nx, ny = np.roll(x, -1), np.roll(y, -1)
    straddle = (y > point[1]) != (ny > point[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        cross = x + (point[1] - y) * (nx - x) / (ny - y)
    return bool((straddle & (point[0] < cross)).sum() % 2)


def _shoelace(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def _area(parts: Sequence[SkyPart], origin: np.ndarray) -> float:
    """El área que encierran los anillos cerrados: par-impar por profundidad de anidamiento."""
    rings = [part.xyz[:, :2] - origin for part in parts if part.closed]
    total = 0.0
    for index, ring in enumerate(rings):
        depth = sum(_contains(other, ring[0]) for other_index, other in enumerate(rings) if other_index != index)
        total += (-1.0 if depth % 2 else 1.0) * _shoelace(ring)
    return total


def _length(xyz: np.ndarray, closed: bool, with_z: bool) -> float:
    points = xyz if with_z else xyz[:, :2]
    if closed:
        points = np.vstack([points, points[:1]])
    return float(np.sqrt((np.diff(points, axis=0) ** 2).sum(axis=1)).sum())


def _segments(rings: Sequence[np.ndarray], closed: Sequence[bool]) -> np.ndarray:
    pieces = []
    for ring, is_closed in zip(rings, closed, strict=True):
        end = np.vstack([ring[1:], ring[:1]]) if is_closed else ring[1:]
        pieces.append(np.stack([ring[: len(end)], end], axis=1))
    return np.concatenate(pieces) if pieces else np.empty((0, 2, 2))


def _closest(first: np.ndarray, second: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Los puntos más próximos entre dos segmentos ``(2, 2)``: ``(sobre el primero, sobre el segundo)``; si se cortan, el de corte en ambos."""
    (ax, ay), (bx, by) = first
    (cx, cy), (dx, dy) = second
    r, s = np.array([bx - ax, by - ay]), np.array([dx - cx, dy - cy])
    denominator = r[0] * s[1] - r[1] * s[0]
    if denominator != 0.0:
        t = ((cx - ax) * s[1] - (cy - ay) * s[0]) / denominator
        u = ((cx - ax) * r[1] - (cy - ay) * r[0]) / denominator
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            at = first[0] + t * r
            return at, at.copy()

    def onto(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        edge = b - a
        length2 = float(edge @ edge)
        fraction = 0.0 if length2 == 0.0 else min(1.0, max(0.0, float((point - a) @ edge) / length2))
        return a + fraction * edge

    pairs = [(first[0], onto(first[0], *second)), (first[1], onto(first[1], *second)),
             (onto(second[0], *first), second[0]), (onto(second[1], *first), second[1])]
    return min(pairs, key=lambda pair: float(np.hypot(*(pair[0] - pair[1]))))


def _nearest(line: np.ndarray, boundary: np.ndarray, cancelled: Cancelled | None) -> tuple[float, np.ndarray, np.ndarray]:
    """La distancia mínima entre dos juegos de segmentos ``(n, 2, 2)`` y los puntos que la dan, por bloques y descartando por cajas."""
    best = math.inf
    pair: tuple[np.ndarray, np.ndarray] | None = None
    low, high = boundary.min(axis=1), boundary.max(axis=1)
    block = max(1, _PAIR_BUDGET // max(1, len(boundary)))
    for first in range(0, len(line), block):
        if cancelled is not None and cancelled():
            _raise_cancelled()
        chunk = line[first : first + block]
        box_low, box_high = chunk.min(axis=(0, 1)), chunk.max(axis=(0, 1))
        gap = np.maximum(np.maximum(low - box_high, box_low - high), 0.0)
        keep = np.flatnonzero(np.hypot(gap[:, 0], gap[:, 1]) <= best)
        if not len(keep):
            continue
        p = np.repeat(chunk, len(keep), axis=0)
        q = np.tile(boundary[keep], (len(chunk), 1, 1))
        distance = segment_distance(p, q)
        at = int(np.argmin(distance))
        if float(distance[at]) < best:
            best = float(distance[at])
            pair = (p[at], q[at])
        if best == 0.0:
            break
    assert pair is not None
    on_line, on_boundary = _closest(*pair)
    return best, on_line, on_boundary


def _raise_cancelled() -> None:
    from ..jobs.worker_api import JobCancelled

    raise JobCancelled()


def _distance(parts: Sequence[SkyPart], limit: tuple[tuple[np.ndarray, ...], ...], origin: np.ndarray,
              cancelled: Cancelled | None) -> SkyDistance:
    line = _segments([part.xyz[:, :2] - origin for part in parts], [part.closed for part in parts])
    rings = [ring - origin for part in limit for ring in part]
    boundary = _segments(rings, [True] * len(rings))
    distance, on_line, on_boundary = _nearest(line, boundary, cancelled)
    # La Z del punto de la línea: la de su vértice más próximo (la línea es de cota casi constante entre vértices contiguos).
    vertices = np.vstack([part.xyz for part in parts])
    nearest = int(np.argmin(np.hypot(vertices[:, 0] - origin[0] - on_line[0], vertices[:, 1] - origin[1] - on_line[1])))
    return SkyDistance(distance, np.array([on_line[0] + origin[0], on_line[1] + origin[1], vertices[nearest, 2]]),
                       on_boundary + origin)


# --- La línea ----------------------------------------------------------------------------------------------------------------


def skyline(start: np.ndarray, design: np.ndarray, grid: Grid, *, crs: CrsRef, vertical: VerticalRef,
            legal: Sequence[Sequence[np.ndarray]] | None = None, perimeter: Sequence[Sequence[np.ndarray]] | None = None,
            progress: Progress | None = None, cancelled: Cancelled | None = None) -> Skyline:
    """La línea de cielo de la corta ``design`` (la de las polilíneas sola: ``NaN`` fuera del recinto) sobre la partida ``start`` (m, de la forma de
    ``grid``), con las distancias a ``legal`` y a ``perimeter`` (partes de polígonos con sus anillos absolutos; ``None``: sin distancia).
    ``progress`` y ``cancelled`` (``JobCancelled``) por bloques del motor de curvas. :class:`ValueError` si un array no es de la forma de la
    rejilla (error del programa)."""
    start = np.asarray(start, dtype=np.float64)
    design = np.asarray(design, dtype=np.float64)
    if start.shape != grid.shape or design.shape != grid.shape:
        raise ValueError(f"la partida {start.shape} y la corta {design.shape} son de la forma de la rejilla {grid.shape}")
    gap = _difference(start, design)
    lines = contours_from_raster(Raster(grid, gap, crs, vertical), interval_m=1.0, base_m=0.0, simplify_m=0.0, min_length_m=0.0,
                                 name="línea de cielo", progress=progress, cancelled=cancelled)
    terrain = Raster(grid, start, crs, vertical)
    parts: list[SkyPart] = []
    for line in lines:
        z = sample(terrain, line.xyz[:, :2])
        parts.append(SkyPart(np.column_stack([line.xyz[:, :2], z]), line.closed))
    if not parts:
        return Skyline((), 0.0, 0.0, 0.0, None, None)
    origin = np.array([grid.west, grid.north - grid.nrows * grid.dy])
    heights = np.concatenate([part.xyz[:, 2] for part in parts])
    found = Skyline(
        tuple(parts), math.fsum(_length(p.xyz, p.closed, False) for p in parts), math.fsum(_length(p.xyz, p.closed, True) for p in parts),
        _area(parts, origin), float(heights.min()), float(heights.max()))
    distances = {name: None if limit is None else _distance(parts, tuple(tuple(part) for part in limit), origin, cancelled)
                 for name, limit in (("legal", legal), ("perimeter", perimeter))}
    return Skyline(found.parts, found.length_m, found.length3d_m, found.area_m2, found.z_min_m, found.z_max_m, **distances)


def limit_distances(parts: Sequence[SkyPart], *, legal: Sequence[Sequence[np.ndarray]] | None = None, perimeter: Sequence[Sequence[np.ndarray]] | None = None,
                    cancelled: Cancelled | None = None) -> tuple[SkyDistance | None, SkyDistance | None]:
    """Las distancias mínimas (y su lugar) de una línea de cielo **ya guardada** (``parts``) al límite legal y al perímetro de actuación (spec 018, T33; RF-018-29, RF-018-33): lo mismo que da
    :func:`skyline` con sus límites, sin la rejilla (la guardan las polilíneas ``des_psk_``, no el lugar de la distancia). ``(None, None)`` sin línea; ``None`` de un límite que no se da."""
    if not parts:
        return None, None
    origin = np.asarray(parts[0].xyz[0, :2], dtype=np.float64)
    found = tuple(None if limit is None else _distance(parts, tuple(tuple(part) for part in limit), origin, cancelled) for limit in (legal, perimeter))
    return found[0], found[1]
