# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparación de las restricciones de un TIN (spec 006; plan 006 §5.3.2 y §5.4 A8; RF-006-13,
RF-006-14).

Antes de triangular, los puntos y las líneas de rotura se convierten en lo que pide el puerto
``Triangulator``: vértices sin duplicados y aristas obligatorias que no se cruzan
(:class:`PreparedInput`). Los vértices nuevos se calculan aquí, en float64 y con su cota, y no
los crea la triangulación (que los daría en float32 y sin cota; plan §6, D5). Las roturas
duras dan aristas; las blandas solo aportan sus vértices como puntos.

:func:`prepare_constraints` repite, hasta que no queda nada que hacer, tres comprobaciones con
las tolerancias ``tol_xy`` (1 mm) y ``tol_z`` (0,01 m) de ``gis/params.py`` (D-5):

1. Vértices a ≤ ``tol_xy`` entre sí (puntos, vértices de roturas y de cruces; plan A7): se
   funden si sus cotas difieren ≤ ``tol_z``, conservando las coordenadas exactas del de una
   rotura dura, si lo hay, y si no, del primero de entrada (un vértice de entrada antes que
   uno de un cruce); si no, conflicto.
2. Vértices a ≤ ``tol_xy`` del interior de un segmento de rotura dura (un punto sobre la
   rotura, una rotura que acaba sobre otra, un solape colineal): si la cota del vértice y la
   de la rotura allí (interpolada) difieren ≤ ``tol_z``, el vértice parte el segmento y
   conserva sus coordenadas (RF-006-13); si no, conflicto.
3. Segmentos de roturas duras que se cruzan en su interior (y no se tocan a ≤ ``tol_xy``,
   que es el caso 2): intersección exacta en float64 local y la cota de cada rotura en el
   cruce; si difieren ≤ ``tol_z``, vértice nuevo con la cota media, de origen «rotura
   dura», que parte los dos segmentos; si no, conflicto con la posición del cruce.

Los candidatos salen de cubetas: de lado ``tol_xy`` para los vértices y, para los segmentos,
de lado ≈ su longitud mediana (cada segmento, en trozos de ese lado como mucho). Si hay algún
conflicto, no se sigue: :class:`~gis.reports.ConflictError` los lista todos (con sus
identificadores, su posición y sus dos cotas), ordenados por su posición, y el TIN no se crea
hasta que se corrijan las líneas en su fuente o se resuelvan los puntos
(``gis.points.resolve_duplicates``). Con ``progress``, avisa tras cada comprobación de cada
pasada (spec 006, T35: con 300.000 vértices, ninguna pasa de unas décimas de segundo,
RNF-006-09).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from .points import (
    Breakline,
    PointSet,
    _check_points,
    _cluster,
    _expand,
    duplicate_tolerances,
)
from .reports import Conflict, ConflictError, ConflictKind

__all__ = [
    "SOURCE_ADDED",
    "SOURCE_CELL",
    "SOURCE_CONTOUR",
    "SOURCE_HARD",
    "SOURCE_POINT",
    "SOURCE_SOFT",
    "Conflict",
    "ConflictError",
    "ConflictKind",
    "PreparedInput",
    "prepare_constraints",
]

SOURCE_POINT = 0
"""``vertex_source`` de un punto (plan §5.2.2)."""
SOURCE_HARD = 1
"""``vertex_source`` de un vértice de rotura dura o de un cruce de roturas."""
SOURCE_SOFT = 2
"""``vertex_source`` de un vértice de rotura blanda."""
SOURCE_CONTOUR = 3
"""``vertex_source`` de un vértice de curva de nivel (T20)."""
SOURCE_ADDED = 4
"""``vertex_source`` de un punto añadido por la corrección de triángulos planos (T20)."""
SOURCE_CELL = 5
"""``vertex_source`` de un centro de celda (rejilla → TIN, T19)."""

MAX_PASSES = 8
"""Pasadas como mucho: con los cruces partidos, la segunda ya no encuentra nada."""

_HARD, _INPUT, _COMPUTED = 0, 1, 2  # prioridad para conservar un vértice al fundir
_MAX_CELLS = 2**24  # cubetas de segmentos por eje como mucho
_PIECES_PER_SEGMENT = 8  # trozos de media por segmento antes de agrandar las cubetas


@dataclass(frozen=True, slots=True, eq=False)
class PreparedInput:
    """Lo que recibe el triangulador (RF-006-13): ``xyz`` float64 ``(n, 3)`` ABSOLUTOS (los
    vértices de entrada que quedan, en su orden y bit a bit, y después los de los cruces),
    ``edges`` int32 ``(k, 2)`` (aristas obligatorias, ``i`` < ``j``, ordenadas y sin
    cruces) y ``vertex_source`` uint8 ``(n,)`` (plan §5.2.2). Recuentos: vértices de
    entrada (puntos y de roturas), fundidos con otro, vértices nuevos en cruces y
    segmentos partidos por un vértice que estaba sobre ellos."""

    xyz: np.ndarray
    edges: np.ndarray
    vertex_source: np.ndarray
    input_vertices: int
    merged: int
    crossings: int
    splits: int


@dataclass(frozen=True, slots=True)
class _Segments:
    """Segmentos de las roturas duras sin repetir: extremos (``a`` < ``b``), la primera
    rotura que lo tiene y su posición por clave ``(a, b)``."""

    a: np.ndarray
    b: np.ndarray
    line: np.ndarray
    index: dict[tuple[int, int], int]


@dataclass(frozen=True, slots=True)
class _Crossing:
    """Un cruce sin conflicto: los dos segmentos, el parámetro en cada uno (desde su
    extremo ``a``), el punto en coordenadas locales y su cota media."""

    first: int
    second: int
    t_first: float
    t_second: float
    x: float
    y: float
    z: float


def prepare_constraints(
    points: PointSet,
    breaklines: Sequence[Breakline],
    *,
    tol_xy: float | None = None,
    tol_z: float | None = None,
    name: str = "",
    progress: Callable[[str], None] | None = None,
) -> PreparedInput:
    """Los vértices y las aristas obligatorias de un TIN desde ``points`` y ``breaklines``
    (RF-006-13, RF-006-14; plan A8): sin duplicados, sin cruces y con los vértices nuevos
    de los cruces calculados en float64. Las tolerancias, las de
    ``gis.points.duplicate_tolerances``. Si hay conflictos, :class:`ConflictError`
    (``gis.constraint_conflicts``, TIN ``name``) con todos. ``progress(etapa)``, si se da,
    tras cada comprobación de cada pasada. Las entradas no se modifican; ``TypeError`` si no
    son un ``PointSet`` y ``Breakline`` (error del programa)."""
    if not isinstance(points, PointSet):
        raise TypeError("points es un PointSet")
    lines = list(breaklines)
    if not all(isinstance(line, Breakline) for line in lines):
        raise TypeError("breaklines son Breakline")
    tol_xy, tol_z = duplicate_tolerances(tol_xy, tol_z)

    def step(stage: str) -> None:
        if progress is not None:
            progress(stage)

    work = _Preparation(points, lines, tol_xy, tol_z)
    for _ in range(MAX_PASSES):
        conflicts: list[Conflict] = []
        merged = work.merge(conflicts)
        step("vértices a menos de la tolerancia")
        segments = work.segments()
        grid = work.grid(segments)
        insertions = work.on_segments(segments, grid, conflicts)
        step("vértices sobre las líneas de rotura")
        crossings = work.crossings(segments, grid, conflicts)
        step("cruces de las líneas de rotura")
        if conflicts:
            conflicts.sort(key=lambda c: (c.x, c.y, c.ids, c.kind.value))
            raise ConflictError("gis.constraint_conflicts", conflicts, tin=name,
                                tol_xy=tol_xy, tol_z=tol_z)
        if not merged and not insertions and not crossings:
            return work.prepared()
        work.split(segments, insertions, crossings)
    raise ValueError(f"las restricciones del TIN «{name}» no se resuelven en {MAX_PASSES} "
                     "pasadas")


class _Preparation:
    """Vértices (los de entrada y los de los cruces) y roturas duras como cadenas de
    vértices, mientras se preparan."""

    def __init__(self, points: PointSet, lines: list[Breakline], tol_xy: float,
                 tol_z: float) -> None:
        _check_points(points.xyz, "PointSet.xyz")
        self.tol_xy = tol_xy
        self.tol_z = tol_z
        blocks = [points.xyz]
        sources = [np.full(len(points), SOURCE_POINT, dtype=np.uint8)]
        ranks = [np.full(len(points), _INPUT, dtype=np.int64)]
        owners = [np.full(len(points), -1, dtype=np.int64)]
        self.labels = [pid or f"#{row}" for pid, row in zip(points.point_ids,
                                                            points.source_rows, strict=True)]
        self.line_ids = [line.line_id for line in lines]
        self.chains: list[list[int]] = []
        self.chain_lines: list[int] = []
        count = len(points)
        for number, line in enumerate(lines):
            _check_points(line.xyz, f"Breakline «{line.line_id}».xyz")
            size = len(line.xyz)
            blocks.append(line.xyz)
            hard = bool(line.hard)
            sources.append(np.full(size, SOURCE_HARD if hard else SOURCE_SOFT, dtype=np.uint8))
            ranks.append(np.full(size, _HARD if hard else _INPUT, dtype=np.int64))
            owners.append(np.full(size, number if hard else -1, dtype=np.int64))
            self.labels += [line.line_id] * size
            if hard:
                self.chains.append(_squeeze(range(count, count + size)))
                self.chain_lines.append(number)
            count += size
        self.xyz = np.concatenate(blocks).reshape(-1, 3).astype(np.float64)
        self.source = np.concatenate(sources)
        self.rank = np.concatenate(ranks)
        self.line = np.concatenate(owners)
        self.inputs = count
        self.rep = np.arange(count, dtype=np.int64)
        self.origin = np.floor(self.xyz[:, :2].min(axis=0)) if count else np.zeros(2)
        self.splits = 0

    # Vértices ----------------------------------------------------------------------------

    def alive(self) -> np.ndarray:
        """Los vértices que quedan (los que no se han fundido con otro)."""
        return np.flatnonzero(self.rep == np.arange(len(self.rep)))

    def local(self) -> np.ndarray:
        """Coordenadas X, Y locales (float64) de todos los vértices: absolutas − origen,
        exactas para las de entrada."""
        return self.xyz[:, :2] - self.origin

    def is_line(self, vertex: int) -> bool:
        """Si el vértice es de una rotura dura (de entrada o de un cruce)."""
        return int(self.rank[vertex]) != _INPUT

    def merge(self, conflicts: list[Conflict]) -> int:
        """Funde los vértices a ≤ ``tol_xy`` (paso 1) y devuelve cuántos se han fundido;
        añade a ``conflicts`` las parejas con cotas que difieren más de ``tol_z``."""
        alive = self.alive()
        if len(alive) < 2:
            return 0
        order = np.lexsort((alive, self.rank[alive]))
        priority = np.empty(len(alive), dtype=np.int64)
        priority[order] = np.arange(len(alive), dtype=np.int64)
        xyz = self.xyz[alive]
        kept, _in_conflict, pairs = _cluster(xyz[:, :2], xyz[:, 2], self.tol_xy, self.tol_z,
                                             priority)
        moved = kept != np.arange(len(alive))
        if not moved.any():
            return 0
        if len(pairs):
            edges = self.edges()
            for first, second in pairs.tolist():
                conflicts.append(self._merge_conflict(int(alive[first]), int(alive[second]),
                                                      edges))
        self.rep[alive] = alive[kept]
        self.chains = [_squeeze(self.rep[chain]) for chain in self.chains]
        return int(moved.sum())

    def _merge_conflict(self, u: int, v: int, edges: np.ndarray) -> Conflict:
        """El conflicto de dos vértices a ≤ ``tol_xy`` con cotas distintas."""
        u_line, v_line = self.is_line(u), self.is_line(v)
        if not u_line and not v_line:
            return self._conflict(ConflictKind.DUPLICATE_POINTS, u, v, *self.xyz[u, :2],
                                  self.xyz[u, 2], self.xyz[v, 2])
        if u_line != v_line:
            point, line = (v, u) if u_line else (u, v)
            return self._conflict(ConflictKind.POINT_ON_LINE, point, line,
                                  *self.xyz[point, :2], self.xyz[point, 2], self.xyz[line, 2])
        first, second = sorted((u, v), key=lambda w: (int(self.line[w]), w))
        kind = (ConflictKind.COLLINEAR_OVERLAP if self._parallel_at(first, second, edges)
                else ConflictKind.CROSSING_LINES)
        return self._conflict(kind, first, second, *self.xyz[first, :2], self.xyz[first, 2],
                              self.xyz[second, 2])

    def _conflict(self, kind: ConflictKind, first: int, second: int, x: float, y: float,
                  first_z: float, second_z: float, *, second_label: str | None = None,
                  ) -> Conflict:
        label = self.labels[second] if second_label is None else second_label
        return Conflict(kind, (self.labels[first], label), float(x), float(y),
                        (float(first_z), float(second_z)))

    def _neighbours(self, vertex: int, edges: np.ndarray) -> list[int]:
        """Los vértices unidos a ``vertex`` por una arista de rotura dura, lejos de él."""
        local = self.local()
        found = np.concatenate([edges[edges[:, 0] == vertex, 1],
                                edges[edges[:, 1] == vertex, 0]])
        far = np.hypot(*(local[found] - local[vertex]).T) > self.tol_xy
        return found[far].tolist()

    def _parallel_at(self, u: int, v: int, edges: np.ndarray) -> bool:
        """Si dos roturas que coinciden en ``u`` ≈ ``v`` siguen juntas (solape colineal):
        un segmento de cada una, en el mismo sentido, con el extremo de una a ≤ ``tol_xy``
        de la recta de la otra."""
        local = self.local()
        for w in self._neighbours(u, edges):
            for w2 in self._neighbours(v, edges):
                ahead = float(np.dot(local[w] - local[u], local[w2] - local[v])) > 0.0
                if ahead and _line_distance(local[w2], local[u], local[w]) <= self.tol_xy:
                    return True
        return False

    # Segmentos ---------------------------------------------------------------------------

    def edges(self) -> np.ndarray:
        """Las aristas de las roturas duras, ``(k, 2)`` con ``i`` < ``j``, sin repetir y en
        el orden de las roturas (la primera vez que aparece cada una)."""
        pairs = [np.column_stack([chain[:-1], chain[1:]]) for chain in self.chains
                 if len(chain) > 1]
        if not pairs:
            return np.empty((0, 2), dtype=np.int64)
        both = np.concatenate(pairs).astype(np.int64)
        both.sort(axis=1)
        _unique, first = np.unique(both, axis=0, return_index=True)
        return both[np.sort(first)]

    def segments(self) -> _Segments:
        """Los segmentos de las roturas duras sin repetir, con su primera rotura."""
        a_parts, b_parts, line_parts = [], [], []
        for chain, line in zip(self.chains, self.chain_lines, strict=True):
            if len(chain) < 2:
                continue
            ends = np.array(chain, dtype=np.int64)
            a_parts.append(np.minimum(ends[:-1], ends[1:]))
            b_parts.append(np.maximum(ends[:-1], ends[1:]))
            line_parts.append(np.full(len(ends) - 1, line, dtype=np.int64))
        if not a_parts:
            empty = np.empty(0, dtype=np.int64)
            return _Segments(empty, empty, empty, {})
        a = np.concatenate(a_parts)
        b = np.concatenate(b_parts)
        lines = np.concatenate(line_parts)
        _unique, first = np.unique(np.column_stack([a, b]), axis=0, return_index=True)
        first.sort()
        a, b, lines = a[first], b[first], lines[first]
        index = {(int(p), int(q)): k for k, (p, q) in enumerate(zip(a.tolist(), b.tolist(),
                                                                    strict=True))}
        return _Segments(a, b, lines, index)

    def grid(self, segments: _Segments) -> _SegmentGrid | None:
        """Las cubetas de los segmentos (``None`` si no hay ninguno)."""
        if not len(segments.a):
            return None
        local = self.local()
        return _SegmentGrid(local[segments.a], local[segments.b], self.tol_xy,
                            local[self.alive()])

    def on_segments(self, segments: _Segments, grid: _SegmentGrid | None,
                    conflicts: list[Conflict]) -> list[tuple[int, float, int]]:
        """Vértices a ≤ ``tol_xy`` del interior de un segmento (paso 2): las inserciones
        (segmento, parámetro desde su extremo ``a``, vértice) con la cota de acuerdo y los
        conflictos de las demás."""
        if grid is None:
            return []
        local = self.local()
        alive = self.alive()
        position, segment = grid.vertex_pairs(local[alive])
        vertex = alive[position]
        a, b = segments.a[segment], segments.b[segment]
        apart = (vertex != a) & (vertex != b)
        vertex, segment, a, b = vertex[apart], segment[apart], a[apart], b[apart]
        t, distance = _project(local[vertex], local[a], local[b])
        near = (t > 0.0) & (t < 1.0) & (distance <= self.tol_xy)
        vertex, segment, a, b, t = vertex[near], segment[near], a[near], b[near], t[near]
        z_line = self.xyz[a, 2] + t * (self.xyz[b, 2] - self.xyz[a, 2])
        steep = np.abs(self.xyz[vertex, 2] - z_line) > self.tol_z
        if steep.any():
            edges = self.edges()
            for k in np.flatnonzero(steep).tolist():
                conflicts.append(self._segment_conflict(
                    int(vertex[k]), int(segment[k]), float(z_line[k]), segments, edges))
        keep = ~steep
        return list(zip(segment[keep].tolist(), t[keep].tolist(), vertex[keep].tolist(),
                        strict=True))

    def _segment_conflict(self, vertex: int, segment: int, z_line: float,
                          segments: _Segments, edges: np.ndarray) -> Conflict:
        """El conflicto de un vértice sobre un segmento con otra cota."""
        line = int(segments.line[segment])
        label = self.line_ids[line]
        x, y = self.xyz[vertex, :2]
        z = self.xyz[vertex, 2]
        if not self.is_line(vertex):
            return self._conflict(ConflictKind.POINT_ON_LINE, vertex, vertex, x, y, z, z_line,
                                  second_label=label)
        local = self.local()
        a, b = local[segments.a[segment]], local[segments.b[segment]]
        along = any(_line_distance(local[w], a, b) <= self.tol_xy
                    for w in self._neighbours(vertex, edges))
        kind = ConflictKind.COLLINEAR_OVERLAP if along else ConflictKind.CROSSING_LINES
        if int(self.line[vertex]) <= line:
            return self._conflict(kind, vertex, vertex, x, y, z, z_line, second_label=label)
        return Conflict(kind, (label, self.labels[vertex]), float(x), float(y),
                        (float(z_line), float(z)))

    def crossings(self, segments: _Segments, grid: _SegmentGrid | None,
                  conflicts: list[Conflict]) -> list[_Crossing]:
        """Segmentos que se cruzan en su interior sin tocarse a ≤ ``tol_xy`` (paso 3): los
        cruces con la cota de acuerdo y los conflictos de los demás."""
        if grid is None or len(segments.a) < 2:
            return []
        local = self.local()
        first, second = grid.segment_pairs()
        a1, b1, a2, b2 = (segments.a[first], segments.b[first], segments.a[second],
                          segments.b[second])
        apart = (a1 != a2) & (a1 != b2) & (b1 != a2) & (b1 != b2)
        first, second = first[apart], second[apart]
        a1, b1, a2, b2 = a1[apart], b1[apart], a2[apart], b2[apart]
        p1, q1, p2, q2 = local[a1], local[b1], local[a2], local[b2]
        touching = ((_segment_distance(p2, p1, q1) <= self.tol_xy)
                    | (_segment_distance(q2, p1, q1) <= self.tol_xy)
                    | (_segment_distance(p1, p2, q2) <= self.tol_xy)
                    | (_segment_distance(q1, p2, q2) <= self.tol_xy))
        d1, d2 = q1 - p1, q2 - p2
        proper = (~touching
                  & (_cross(d1, p2 - p1) * _cross(d1, q2 - p1) < 0.0)
                  & (_cross(d2, p1 - p2) * _cross(d2, q1 - p2) < 0.0))
        found: list[_Crossing] = []
        for k in np.flatnonzero(proper).tolist():
            offset = p2[k] - p1[k]
            denominator = float(_cross(d1[k], d2[k]))
            t1 = float(_cross(offset, d2[k])) / denominator
            t2 = float(_cross(offset, d1[k])) / denominator
            point = p1[k] + t1 * d1[k]
            z1 = self.xyz[a1[k], 2] + t1 * (self.xyz[b1[k], 2] - self.xyz[a1[k], 2])
            z2 = self.xyz[a2[k], 2] + t2 * (self.xyz[b2[k], 2] - self.xyz[a2[k], 2])
            x, y = point + self.origin
            if abs(z1 - z2) > self.tol_z:
                # Los segmentos van en el orden de las roturas: la del primero no es posterior.
                one, other = int(segments.line[first[k]]), int(segments.line[second[k]])
                conflicts.append(Conflict(
                    ConflictKind.CROSSING_LINES, (self.line_ids[one], self.line_ids[other]),
                    float(x), float(y), (float(z1), float(z2))))
                continue
            found.append(_Crossing(int(first[k]), int(second[k]), t1, t2, float(x), float(y),
                                   float(0.5 * (z1 + z2))))
        return found

    def split(self, segments: _Segments, insertions: list[tuple[int, float, int]],
              crossings: list[_Crossing]) -> None:
        """Añade los vértices de los cruces y parte los segmentos por los vértices que
        tienen encima (pasos 2 y 3)."""
        table: dict[int, list[tuple[float, int]]] = {}
        for segment, t, vertex in insertions:
            table.setdefault(segment, []).append((t, vertex))
        if crossings:
            start = len(self.xyz)
            added = np.array([(c.x, c.y, c.z) for c in crossings], dtype=np.float64)
            self.xyz = np.concatenate([self.xyz, added])
            count = len(crossings)
            self.source = np.concatenate([self.source,
                                          np.full(count, SOURCE_HARD, dtype=np.uint8)])
            self.rank = np.concatenate([self.rank, np.full(count, _COMPUTED, dtype=np.int64)])
            lines = [int(segments.line[c.first]) for c in crossings]
            self.line = np.concatenate([self.line, np.array(lines, dtype=np.int64)])
            self.rep = np.concatenate([self.rep, np.arange(start, start + count)])
            for offset, crossing in enumerate(crossings):
                vertex = start + offset
                one = self.line_ids[int(segments.line[crossing.first])]
                other = self.line_ids[int(segments.line[crossing.second])]
                self.labels.append(f"{one} × {other}")
                table.setdefault(crossing.first, []).append((crossing.t_first, vertex))
                table.setdefault(crossing.second, []).append((crossing.t_second, vertex))
        self.splits += len(insertions)
        chains = []
        for chain in self.chains:
            out = [chain[0]]
            for p, q in pairwise(chain):
                items = table.get(segments.index[(min(p, q), max(p, q))])
                if items:
                    inside = [vertex for _t, vertex in sorted(items)]
                    out += inside if p < q else inside[::-1]
                out.append(q)
            chains.append(_squeeze(out))
        self.chains = chains

    # Resultado ---------------------------------------------------------------------------

    def prepared(self) -> PreparedInput:
        alive = self.alive()
        index = np.full(len(self.rep), -1, dtype=np.int64)
        index[alive] = np.arange(len(alive), dtype=np.int64)
        edges = index[self.edges()]
        edges.sort(axis=1)
        if len(edges):
            edges = np.unique(edges, axis=0)
        edges = edges.reshape(-1, 2).astype(np.int32)
        return PreparedInput(
            xyz=np.ascontiguousarray(self.xyz[alive]),
            edges=edges,
            vertex_source=self.source[alive].astype(np.uint8),
            input_vertices=self.inputs,
            merged=int(self.inputs - np.count_nonzero(alive < self.inputs)),
            crossings=int(np.count_nonzero(alive >= self.inputs)),
            splits=self.splits,
        )


class _SegmentGrid:
    """Cubetas de segmentos (plan A8): lado ≈ longitud mediana (al menos 2·``tol``); cada
    segmento, en trozos de ese lado como mucho, ocupa las cubetas de la caja de cada trozo
    ampliada en ``tol`` (como mucho 3 × 3). ``points`` son los vértices, para el tamaño
    de la rejilla."""

    def __init__(self, start: np.ndarray, end: np.ndarray, tol: float,
                 points: np.ndarray) -> None:
        lengths = np.hypot(*(end - start).T)
        extent = float(max(points.max(initial=0.0), start.max(initial=0.0),
                           end.max(initial=0.0)))
        size = max(float(np.median(lengths)), 2.0 * tol, extent / _MAX_CELLS)
        budget = _PIECES_PER_SEGMENT * len(lengths) + 100_000
        while int(np.ceil(lengths / size).sum()) > budget:
            size *= 2.0
        pieces = np.maximum(1, np.ceil(lengths / size).astype(np.int64))
        owner, step = _expand(np.zeros(len(pieces), dtype=np.int64), pieces)
        delta = (end - start)[owner]
        p0 = start[owner] + (step / pieces[owner])[:, None] * delta
        p1 = start[owner] + ((step + 1) / pieces[owner])[:, None] * delta
        low = np.floor((np.minimum(p0, p1) - tol) / size).astype(np.int64) + 1
        high = np.floor((np.maximum(p0, p1) + tol) / size).astype(np.int64) + 1
        self.size = size
        self.stride = int(np.floor(extent / size)) + 4
        keys, owners = [], []
        for ox in range(3):
            for oy in range(3):
                cx, cy = low[:, 0] + ox, low[:, 1] + oy
                inside = (cx <= high[:, 0]) & (cy <= high[:, 1])
                keys.append(cx[inside] * self.stride + cy[inside])
                owners.append(owner[inside])
        key = np.concatenate(keys)
        segment = np.concatenate(owners)
        order = np.lexsort((segment, key))
        self.keys = key[order]
        self.segments = segment[order]
        self.count = len(lengths)

    def vertex_pairs(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Parejas (posición del punto, segmento) que comparten cubeta, sin repetir."""
        cells = np.floor(points / self.size).astype(np.int64) + 1
        keys = cells[:, 0] * self.stride + cells[:, 1]
        start = np.searchsorted(self.keys, keys, side="left")
        stop = np.searchsorted(self.keys, keys, side="right")
        position, entry = _expand(start, stop)
        pair = np.unique(position * self.count + self.segments[entry])
        return pair // self.count, pair % self.count

    def segment_pairs(self) -> tuple[np.ndarray, np.ndarray]:
        """Parejas de segmentos distintos (``s1`` < ``s2``) que comparten cubeta."""
        stop = np.searchsorted(self.keys, self.keys, side="right")
        entry, other = _expand(np.arange(1, len(self.keys) + 1), stop)
        one, two = self.segments[entry], self.segments[other]
        distinct = one != two
        low = np.minimum(one, two)[distinct]
        high = np.maximum(one, two)[distinct]
        pair = np.unique(low * self.count + high)
        return pair // self.count, pair % self.count


def _squeeze(chain: object) -> list[int]:
    """La cadena sin vértices repetidos seguidos."""
    values = np.asarray(chain, dtype=np.int64)
    if len(values) > 1:
        values = values[np.concatenate([[True], values[1:] != values[:-1]])]
    return values.tolist()


def _cross(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """El producto vectorial en planta, ``u × v``."""
    return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]


def _project(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """El parámetro de la proyección de ``p`` en la recta ``a``–``b`` y la distancia a
    ella."""
    d = b - a
    t = np.einsum("ij,ij->i", p - a, d) / np.einsum("ij,ij->i", d, d)
    foot = a + t[:, None] * d
    return t, np.hypot(*(p - foot).T)


def _segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La distancia de cada ``p`` a su segmento ``a``–``b``."""
    d = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, d) / np.einsum("ij,ij->i", d, d), 0.0, 1.0)
    return np.hypot(*(p - (a + t[:, None] * d)).T)


def _line_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """La distancia de ``p`` a la recta que pasa por ``a`` y ``b`` (distintos)."""
    d = b - a
    return abs(float(_cross(d, p - a))) / float(np.hypot(*d))
