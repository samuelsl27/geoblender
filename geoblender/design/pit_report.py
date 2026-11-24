# SPDX-License-Identifier: GPL-3.0-or-later
"""Los hallazgos y las cifras de la corta (spec 018, T20; HU-018-2, HU-018-4; RF-018-26 y 31; CE-018-08 y 11; plan 018 §5.4 A12, §5.7 P-14).

Lo que se mide de una corta **ya calculada**: sus polilíneas (pies y crestas), su superficie en la rejilla (:class:`~design.pit_surface.PitSurface`), sus
rampas comprobadas (:class:`~design.pit_ramp.RampChecked`) y su línea de cielo (:class:`~design.pit_sky.Skyline`). Nada se corrige ni se cambia.

**Los hallazgos** (:func:`findings`, RF-018-26): cada uno con su banco, su tipo, el valor, el límite, su lugar y su unidad (:class:`~design.pit_model.Finding`).

- ``FACE_SLOPE``: la inclinación real de la celda (la mayor tangente a sus ocho vecinas, :func:`design.report.max_tangents`) frente a ``α + la
  tolerancia de cara`` (RF-013-27) del perfil que le corresponde por su sector; un hallazgo por banco, con la peor celda.
- ``BERM_WIDTH``: la berma real (la menor distancia entre una cresta y el pie de su mismo nivel y sector, vértice a arista) menor que ``B`` menos la tolerancia
  del arco; las polilíneas de una zona de rampa no se miden aquí (allí manda la sección de la rampa).
- ``FLOOR_WIDTH``: el ancho útil del fondo menor que el mínimo (solo si se pidió).
- ``OUTSIDE_PERIMETER`` y ``ON_UNTOUCHABLE``: la longitud de cresta fuera del perímetro de actuación (el recorte, exacto sobre las aristas) o sobre un
  intocable (muestreada a ≤ un cuarto de celda), con el lugar de su punto medio.
- ``UNEXCAVATED``: el área de las celdas donde la corta baja y las máscaras no dejan (``PitSurface.blocked``).
- ``RAMP``: cada aviso de la comprobación de la rampa (RF-018-19 y 20), con su banco y su lugar.
- ``NO_PROFILE``: un banco cuyo sector no tiene perfil **es un hallazgo, no un «cumple»**: no se mide nada de él.

**Las cifras** (:func:`figures`, RF-018-31), CALCULADO con su unidad: bancos, cotas, longitud de pies y de crestas (**solo lo que está a la cota del
terreno o por debajo**, P-14: un trozo en el aire no se cuenta; una celda sin dato de terreno, sí), áreas de bermas y de fondo (las celdas de la rejilla
donde la corta es llana a la cota del banco), el volumen de corte y el área con movimiento, el volumen **por banco** (el reparto de la 011 de
:attr:`PitSurface.bench_m3`), la línea de cielo, y por rampa su longitud, su pendiente media y máxima y el volumen de corte de su banda.

Las entradas no se modifican. Perezoso (RNF-001-03): nada del arranque lo importa. Python puro con numpy."""

from __future__ import annotations

import math
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from ..core.provenance.figures import FigureSpec
from ..gis.raster import Raster, sample
from .pit_model import BenchFigures, Finding, FindingKind, PitJob, PitMode, Polyline, PolylineKind
from .pit_sky import Skyline
from .pit_surface import PitSurface
from .provenance import pit_figures
from .report import max_tangents, padded_rows
from .zones import polygons_cells

__all__ = ["BLOCK_PAIRS", "inscribed_width", "TERRAIN_TOL_M", "FLAT_TOL_M", "Figures", "figures", "findings", "findings_units"]

TERRAIN_TOL_M: float = 0.01
"""Lo que un trozo de polilínea puede estar por encima del terreno para contar como «existente» (m; P-14)."""
FLAT_TOL_M: float = 1e-6
"""Lo que una celda puede apartarse de la cota de un banco para contar como llana a ella (m)."""
BLOCK_PAIRS: int = 1 << 21
"""Parejas (punto, arista) por bloque de las distancias."""
_LEVEL_TOL_M = 1e-6
_SAMPLE_FRACTION = 0.25
"""El largo de un trozo de muestreo de una polilínea, en celdas."""


# --- Geometría de las polilíneas ----------------------------------------------------------------------------------------------


def _segments(vertices: np.ndarray, closed: bool) -> tuple[np.ndarray, np.ndarray]:
    first = np.asarray(vertices, dtype=np.float64)
    nxt = np.roll(first, -1, axis=0) if closed else first[1:]
    return (first if closed else first[:-1]), nxt


def _pieces(vertices: np.ndarray, closed: bool, max_len: float) -> tuple[np.ndarray, np.ndarray]:
    """Los trozos de una polilínea de a lo sumo ``max_len`` m: sus puntos medios ``(m, 3)`` (la Z lineal) y sus longitudes ``(m,)``."""
    a, b = _segments(vertices, closed)
    length = np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])
    parts = np.maximum(np.ceil(length / max_len), 1.0).astype(np.int64)
    owner = np.repeat(np.arange(len(a)), parts)
    along = np.arange(int(parts.sum())) - (np.cumsum(parts) - parts)[owner]
    middle = ((along + 0.5) / parts[owner])[:, None]
    points = a[owner] + (b[owner] - a[owner]) * middle
    return points, length[owner] / parts[owner]


def _inside_parts(points: np.ndarray, parts: Sequence[Sequence[np.ndarray]]) -> np.ndarray:
    """Qué ``points`` ``(m, 2)`` están dentro de alguno de los polígonos ``parts`` (anillos absolutos, par-impar por polígono)."""
    inside = np.zeros(len(points), dtype=bool)
    for polygon in parts:
        count = np.zeros(len(points), dtype=np.int64)
        for ring in polygon:
            ring = np.asarray(ring, dtype=np.float64)[:, :2]
            nxt = np.roll(ring, -1, axis=0)
            block = max(1, BLOCK_PAIRS // max(1, len(ring)))
            for first in range(0, len(points), block):
                x, y = points[first:first + block, 0:1], points[first:first + block, 1:2]
                straddle = (ring[:, 1] > y) != (nxt[:, 1] > y)
                with np.errstate(divide="ignore", invalid="ignore"):
                    cross = ring[:, 0] + (y - ring[:, 1]) * (nxt[:, 0] - ring[:, 0]) / (nxt[:, 1] - ring[:, 1])
                count[first:first + block] += np.count_nonzero(straddle & (x < cross), axis=1)
        inside |= count % 2 == 1
    return inside


def _edges_of(parts: Sequence[Sequence[np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    starts, ends = [], []
    for polygon in parts:
        for ring in polygon:
            ring = np.asarray(ring, dtype=np.float64)[:, :2]
            starts.append(ring)
            ends.append(np.roll(ring, -1, axis=0))
    return np.vstack(starts), np.vstack(ends)


def _cross(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]


def _outside_pieces(vertices: np.ndarray, closed: bool, parts: Sequence[Sequence[np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    """Los trozos de la polilínea que quedan **fuera** de ``parts`` (cortada exactamente en sus aristas): sus puntos medios ``(m, 2)`` y longitudes."""
    a, b = _segments(vertices[:, :2], closed)
    c, d = _edges_of(parts)
    seg_len = np.hypot(*(b - a).T)
    cuts: list[list[float]] = [[] for _ in range(len(a))]
    block = max(1, BLOCK_PAIRS // max(1, len(c)))
    for first in range(0, len(a), block):
        r = (b - a)[first:first + block, None, :]
        s = (d - c)[None, :, :]
        qp = c[None, :, :] - a[first:first + block, None, :]
        denom = _cross(r, s)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = _cross(qp, s) / denom
            u = _cross(qp, r) / denom
        hit = (denom != 0.0) & (t > 0.0) & (t < 1.0) & (u >= 0.0) & (u <= 1.0)
        for row, col in zip(*np.nonzero(hit), strict=True):
            cuts[first + int(row)].append(float(t[row, col]))
    starts, stops, owner = [], [], []
    for index, found in enumerate(cuts):
        ts = [0.0, *sorted(found), 1.0]
        starts.extend(ts[:-1])
        stops.extend(ts[1:])
        owner.extend([index] * (len(ts) - 1))
    t0, t1, own = np.asarray(starts), np.asarray(stops), np.asarray(owner)
    middle = a[own] + (b[own] - a[own]) * (0.5 * (t0 + t1))[:, None]
    lengths = (t1 - t0) * seg_len[own]
    out = ~_inside_parts(middle, parts) & (lengths > 0.0)
    return middle[out], lengths[out]


def _halfway(points: np.ndarray, lengths: np.ndarray) -> tuple[float, float]:
    """El punto de ``points`` donde la longitud acumulada llega a la mitad de la total: un punto sobre la línea, no su centroide."""
    at = int(np.searchsorted(np.cumsum(lengths), 0.5 * float(lengths.sum())))
    at = min(at, len(points) - 1)
    return float(points[at, 0]), float(points[at, 1])


def _drain[T](work: Generator[None, None, T]) -> T:
    """Las unidades de ``work`` hasta el final, sin ceder el hilo: lo que devuelve."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: T = done.value
            return result


def _nearest(points: np.ndarray, line: np.ndarray, closed: bool) -> tuple[float, int]:
    """La menor distancia en planta de los ``points`` ``(m, 2)`` a las aristas de ``line`` y el índice del punto que la da."""
    return _drain(_nearest_units(points, line, closed))


_NEAREST_BLOCK = 32
"""Los puntos y las aristas por cajita de :func:`_nearest_units` (T36)."""
_NEAREST_DENSE_PAIRS = 1 << 16
"""Hasta cuántas parejas (punto, arista) se miden todas, sin descartar por cajas."""


def _pair_distances(p: np.ndarray, a: np.ndarray, delta: np.ndarray, length2: np.ndarray) -> np.ndarray:
    """La distancia en planta de cada punto de ``p`` ``(m, 1, 2)`` a cada arista ``a → a + delta`` ``(1, e, 2)``: ``(m, e)``."""
    w = p - a
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.clip(np.where(length2 > 0.0, (w * delta).sum(axis=2) / length2, 0.0), 0.0, 1.0)
    near = a + t[:, :, None] * delta
    return np.hypot(*(p - near).transpose(2, 0, 1))


def _nearest_units(points: np.ndarray, line: np.ndarray, closed: bool) -> Generator[None, None, tuple[float, int]]:
    """:func:`_nearest` con una unidad (``yield``) por bloque de parejas (T22: para ceder el hilo en ≤ 0,05 s). Con muchas parejas (T36: dos anillos de 1.300 vértices eran 1,8 M
    parejas por banco y ≈ 12 s con 60 bancos) **descarta por cajas**: los puntos van en cajitas de :data:`_NEAREST_BLOCK` consecutivos y las aristas también, y una cajita de puntos solo se
    mide contra las cajitas de aristas a menos de la mejor distancia conocida (una cota superior de una muestra de puntos); el mínimo y el punto que lo da (el menor índice entre los empates)
    son los de la fuerza bruta, bit a bit."""
    a, b = _segments(line[:, :2], closed)
    delta = b - a
    length2 = (delta ** 2).sum(axis=1)
    best, where = math.inf, 0
    if len(points) * len(a) <= _NEAREST_DENSE_PAIRS:
        block = max(1, BLOCK_PAIRS // max(1, len(a)))
        for first in range(0, len(points), block):
            found = _pair_distances(points[first:first + block, None, :], a[None, :, :], delta[None, :, :], length2).min(axis=1)
            index = int(np.argmin(found))
            if float(found[index]) < best:
                best, where = float(found[index]), first + index
            yield
        return best, where
    step = max(1, len(points) // _NEAREST_BLOCK)
    sample = points[::step]
    bound = float(_pair_distances(sample[:, None, :], a[None, :, :], delta[None, :, :], length2).min())
    yield
    low_e, high_e = np.minimum(a, b), np.maximum(a, b)
    chunks = [(first, min(first + _NEAREST_BLOCK, len(a))) for first in range(0, len(a), _NEAREST_BLOCK)]
    box_low = np.array([low_e[x:y].min(axis=0) for x, y in chunks])
    box_high = np.array([high_e[x:y].max(axis=0) for x, y in chunks])
    for first in range(0, len(points), _NEAREST_BLOCK):
        part = points[first:first + _NEAREST_BLOCK]
        low_p, high_p = part.min(axis=0), part.max(axis=0)
        gap = np.maximum(np.maximum(box_low - high_p, low_p - box_high), 0.0)
        near = np.hypot(gap[:, 0], gap[:, 1]) <= bound * (1.0 + 1e-9) + 1e-9
        if near.any():
            edges = np.concatenate([np.arange(chunks[i][0], chunks[i][1]) for i in np.flatnonzero(near)])
            found = _pair_distances(part[:, None, :], a[edges][None, :, :], delta[edges][None, :, :], length2[edges]).min(axis=1)
            index = int(np.argmin(found))
            if float(found[index]) < best:
                best, where = float(found[index]), first + index
                bound = min(bound, best)
        yield
    return best, where


# --- Qué polilíneas, qué perfil ---------------------------------------------------------------------------------------------


def _profile_of(job: PitJob, sector: str) -> Any:
    """El perfil de banco de un sector (``""``: el perímetro, el base); ``None`` si no lo hay (el sector es desconocido o todo sector lleva el suyo)."""
    if sector == "":
        return job.profile
    for item in job.sectors:
        if item.code == sector:
            return item.profile if item.profile is not None else job.profile
    return None


def _by_bench(polylines: Sequence[Polyline]) -> dict[int, list[Polyline]]:
    found: dict[int, list[Polyline]] = {}
    for item in polylines:
        found.setdefault(item.bench, []).append(item)
    return dict(sorted(found.items()))


def _limit_map(job: PitJob) -> np.ndarray:
    """La inclinación máxima de la cara (°) del perfil de cada celda por su sector (``NaN``: sin perfil)."""
    limit = np.full(job.grid.shape, np.nan)
    if job.profile is not None:
        limit[:] = job.profile.face_deg
    for sector in reversed(job.sectors):  # el primero que contiene la celda gana, como en ``sector_labels``
        if sector.profile is not None:
            limit[polygons_cells(sector.parts, job.grid)] = sector.profile.face_deg
        elif job.profile is None:
            limit[polygons_cells(sector.parts, job.grid)] = np.nan
    return limit


def _ranges(polylines: Sequence[Polyline]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los intervalos de cota ``[zlo, zhi]`` de cada banco ordenados por ``zlo``: ``(zlo, zhi, banco)``."""
    rows = []
    for bench, items in _by_bench(polylines).items():
        z = [float(item.vertices[:, 2].min()) for item in items] + [float(item.vertices[:, 2].max()) for item in items]
        rows.append((min(z), max(z), bench))
    rows.sort()
    return (np.array([row[0] for row in rows]), np.array([row[1] for row in rows]), np.array([row[2] for row in rows], dtype=np.int64))


def _cell_place(job: PitJob, row: int, col: int) -> tuple[float, float]:
    grid = job.grid
    return float(grid.west + (col + 0.5) * grid.dx), float(grid.north - (row + 0.5) * grid.dy)


# --- Los hallazgos ---------------------------------------------------------------------------------------------------------------


def _face_findings(job: PitJob, polylines: Sequence[Polyline], surface: PitSurface, tolerance_deg: float) -> list[Finding]:
    moved = surface.cut_cells
    if not moved.any():
        return []
    rows, cols = surface.surface.shape
    tangents = max_tangents(padded_rows(surface.surface, 0, rows), job.grid.dx, job.grid.dy)[1:rows + 1, 1:cols + 1]
    angle = np.degrees(np.arctan(tangents))
    limit = _limit_map(job) + tolerance_deg
    with np.errstate(invalid="ignore"):
        over = moved & np.isfinite(angle) & (angle > limit)
    if not over.any():
        return []
    where = np.argwhere(over)
    z = surface.surface[over]
    zlo, zhi, benches = _ranges(polylines)
    index = np.clip(np.searchsorted(zlo, z + _LEVEL_TOL_M, side="right") - 1, 0, len(zlo) - 1)
    owner = np.where(z <= zhi[index] + _LEVEL_TOL_M, benches[index], -(10 ** 9))
    found = []
    for bench in sorted(set(owner.tolist())):
        pick = np.flatnonzero(owner == bench)
        worst = pick[int(np.argmax(angle[over][pick]))]
        row, col = (int(v) for v in where[worst])
        found.append(Finding(FindingKind.FACE_SLOPE, float(angle[row, col]), float(limit[row, col]), _cell_place(job, row, col),
                             None if bench == -(10 ** 9) else int(bench), detail=f"{len(pick)} celdas"))
    return found


def _berm_findings(job: PitJob, polylines: Sequence[Polyline], tolerance_m: float) -> list[Finding]:
    return _drain(_berm_units(job, polylines, tolerance_m))


def _berm_units(job: PitJob, polylines: Sequence[Polyline], tolerance_m: float) -> Generator[None, None, list[Finding]]:
    found = []
    items = [item for item in polylines if item.zone == ""]
    for crest in (item for item in items if item.kind == PolylineKind.CREST):
        profile = _profile_of(job, crest.sector)
        if profile is None:
            continue
        feet = [item for item in items if item.kind == PolylineKind.FOOT and item.sector == crest.sector
                and abs(item.z_m - crest.z_m) <= _LEVEL_TOL_M]
        best, place = math.inf, None
        for foot in feet:
            distance, at = yield from _nearest_units(crest.vertices[:, :2], foot.vertices, foot.closed)
            if distance < best:
                best, place = distance, crest.vertices[at, :2]
            distance, at = yield from _nearest_units(foot.vertices[:, :2], crest.vertices, crest.closed)
            if distance < best:
                best, place = distance, foot.vertices[at, :2]
        if place is not None and best < profile.berm_m - tolerance_m:
            found.append(Finding(FindingKind.BERM_WIDTH, best, profile.berm_m, (float(place[0]), float(place[1])), crest.bench))
    return found


def inscribed_width(ring: np.ndarray) -> float:
    """El ancho útil de ``ring`` (m): el diámetro del mayor círculo inscrito, buscado desde una malla de candidatos dentro de la polilínea y refinado
    por tanteo a ≤ 1 mm (sin el motor de desfase, que con un anillo de cientos de vértices que se colapsa tarda minutos). Es una **estimación por
    abajo** (un máximo local de la distancia al borde); para un anillo convexo es exacta."""
    ring = np.asarray(ring, dtype=np.float64)[:, :2]

    def distance(points: np.ndarray) -> np.ndarray:
        inside = _inside_parts(points, [[ring]])
        best = np.full(len(points), np.inf)
        a, b = _segments(ring, True)
        delta = b - a
        length2 = (delta ** 2).sum(axis=1)
        block = max(1, BLOCK_PAIRS // max(1, len(a)))
        for first in range(0, len(points), block):
            p = points[first:first + block, None, :]
            w = p - a[None, :, :]
            with np.errstate(divide="ignore", invalid="ignore"):
                t = np.clip(np.where(length2 > 0.0, (w * delta).sum(axis=2) / length2, 0.0), 0.0, 1.0)
            best[first:first + block] = np.hypot(*(p - (a[None] + t[:, :, None] * delta[None])).transpose(2, 0, 1)).min(axis=1)
        return np.where(inside, best, -1.0)

    low, high = ring.min(axis=0), ring.max(axis=0)
    xs, ys = np.meshgrid(np.linspace(low[0], high[0], 41), np.linspace(low[1], high[1], 41))
    candidates = np.column_stack([xs.ravel(), ys.ravel()])
    values = distance(candidates)
    top = np.argsort(-values)[:5]
    best = 0.0
    for index in top:
        if values[index] <= 0.0:
            continue
        point, step, here = candidates[index].copy(), float(max(high - low)) / 40.0, float(values[index])
        while step > 5e-4:
            moves = point + step * np.array([[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]], dtype=np.float64)
            found = distance(moves)
            at = int(np.argmax(found))
            if found[at] > here:
                point, here = moves[at], float(found[at])
            else:
                step *= 0.5
        best = max(best, here)
    return 2.0 * best


def _floor_findings(job: PitJob, polylines: Sequence[Polyline], floor_width_m: float | None) -> list[Finding]:
    minimum = job.params.min_floor_width_m
    if minimum is None:
        return []
    found = []
    if job.mode is PitMode.UP:
        for source in job.sources:
            width = inscribed_width(np.asarray(source.ring, dtype=np.float64))
            if width < minimum:
                centre = np.asarray(source.ring).mean(axis=0)
                found.append(Finding(FindingKind.FLOOR_WIDTH, width, minimum, (float(centre[0]), float(centre[1])), None, detail=source.name))
    elif floor_width_m is not None and floor_width_m < minimum:
        low = min((item for item in polylines if item.kind == PolylineKind.FOOT), key=lambda item: item.z_m, default=None)
        centre = np.zeros(2) if low is None else low.vertices[:, :2].mean(axis=0)
        found.append(Finding(FindingKind.FLOOR_WIDTH, floor_width_m, minimum, (float(centre[0]), float(centre[1])), None))
    return found


def _crest_findings(job: PitJob, polylines: Sequence[Polyline]) -> list[Finding]:
    found = []
    per_bench = {bench: [item for item in items if item.kind == PolylineKind.CREST] for bench, items in _by_bench(polylines).items()}
    grid = job.grid
    for bench, crests in per_bench.items():
        if job.perimeter is not None:
            points, lengths = [], []
            for item in crests:
                found_points, found_lengths = _outside_pieces(item.vertices, item.closed, job.perimeter)
                points.append(found_points)
                lengths.append(found_lengths)
            total = float(np.concatenate(lengths).sum()) if lengths else 0.0
            if total > 0.0:
                found.append(Finding(FindingKind.OUTSIDE_PERIMETER, total, 0.0, _halfway(np.vstack(points), np.concatenate(lengths)), bench))
        if job.untouchable.any():
            points, lengths = [], []
            for item in crests:
                middle, length = _pieces(item.vertices, item.closed, _SAMPLE_FRACTION * min(grid.dx, grid.dy))
                col = np.floor((middle[:, 0] - grid.west) / grid.dx).astype(np.int64)
                row = np.floor((grid.north - middle[:, 1]) / grid.dy).astype(np.int64)
                ok = (row >= 0) & (row < grid.nrows) & (col >= 0) & (col < grid.ncols)
                hit = np.zeros(len(middle), dtype=bool)
                hit[ok] = job.untouchable[row[ok], col[ok]]
                points.append(middle[hit, :2])
                lengths.append(length[hit])
            total = float(np.concatenate(lengths).sum()) if lengths else 0.0
            if total > 0.0:
                found.append(Finding(FindingKind.ON_UNTOUCHABLE, total, 0.0, _halfway(np.vstack(points), np.concatenate(lengths)), bench))
    return found


_RAMP_UNITS = {"des.pit_ramp_gradient": "%", "des.pit_ramp_mean_gradient": "%", "des.pit_ramp_radius_reduced": "m",
               "des.pit_ramp_radius_below_min": "m", "des.pit_ramp_prolonged": "m"}


def _ramp_findings(ramps: Sequence[Any]) -> list[Finding]:
    found = []
    for ramp in ramps:
        start = np.asarray(ramp.path.axis)[0]
        for notice in ramp.notices:
            values = notice.values
            value = next((values[key] for key in ("gradient", "mean", "fitted", "value") if key in values), None)
            limit = next((values[key] for key in ("limit", "radius") if key in values), None)
            x, y = float(values.get("x", start[0])), float(values.get("y", start[1]))
            bench = values.get("bench")
            found.append(Finding(FindingKind.RAMP, None if value is None else float(value), None if limit is None else float(limit), (x, y),
                                 int(bench) if isinstance(bench, int) and not isinstance(bench, bool) else None,
                                 unit=_RAMP_UNITS.get(notice.code, ""), detail=f"{ramp.name}: {notice.code}"))
    return found


def findings(job: PitJob, polylines: Sequence[Polyline], surface: PitSurface, *, face_tolerance_deg: float, ramps: Sequence[Any] = (),
             floor_width_m: float | None = None) -> tuple[Finding, ...]:
    """:func:`findings_units` hasta el final, sin ceder el hilo (A12; RF-018-26): los hallazgos de la corta."""
    return _drain(findings_units(job, polylines, surface, face_tolerance_deg=face_tolerance_deg, ramps=ramps, floor_width_m=floor_width_m))


def findings_units(job: PitJob, polylines: Sequence[Polyline], surface: PitSurface, *, face_tolerance_deg: float, ramps: Sequence[Any] = (),
                   floor_width_m: float | None = None) -> Generator[None, None, tuple[Finding, ...]]:
    """**A12** (RF-018-26): los hallazgos de la corta de ``job`` con sus ``polylines``, su ``surface`` y sus ``ramps`` (:class:`~design.pit_ramp.RampChecked`),
    en un orden estable (por tipo y por banco). ``face_tolerance_deg`` es la tolerancia de cara del proyecto (RF-013-27) y ``floor_width_m`` el ancho útil
    del fondo de una descendente (``Benches.floor_width_m``; en la ascendente se mide desde los fondos). No corrige nada; una lista vacía es «sin
    hallazgos» solo si todos los bancos tenían perfil: un banco sin él es el hallazgo ``NO_PROFILE``."""
    if face_tolerance_deg < 0.0 or not math.isfinite(face_tolerance_deg):
        raise ValueError(f"la tolerancia de cara es finita y no negativa, no {face_tolerance_deg!r}")
    profiled = [item for item in polylines if _profile_of(job, item.sector) is not None]
    out: list[Finding] = []
    unprofiled = {(item.bench, item.sector): item for item in polylines if _profile_of(job, item.sector) is None}
    for (bench, sector), item in sorted(unprofiled.items()):
        out.append(Finding(FindingKind.NO_PROFILE, None, None, (float(item.vertices[0, 0]), float(item.vertices[0, 1])), bench,
                           detail=sector or "perímetro"))
    if profiled:
        out += _face_findings(job, profiled, surface, face_tolerance_deg)
        yield
        out += yield from _berm_units(job, profiled, job.params.arc_tol_m + job.params.simplify_m + _LEVEL_TOL_M)
    out += _floor_findings(job, polylines, floor_width_m)
    out += _crest_findings(job, polylines)
    if surface.blocked.any():
        cells = np.argwhere(surface.blocked)
        centre = cells.mean(axis=0)
        row, col = cells[int(np.argmin(np.hypot(cells[:, 0] - centre[0], cells[:, 1] - centre[1])))]
        out.append(Finding(FindingKind.UNEXCAVATED, float(surface.blocked.sum()) * job.grid.cell_area, 0.0, _cell_place(job, int(row), int(col))))
    out += _ramp_findings(ramps)
    order = {kind: number for number, kind in enumerate(FindingKind)}
    return tuple(sorted(out, key=lambda item: (order[item.kind], -1 if item.bench is None else item.bench)))


# --- Las cifras -----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Figures:
    """Las cifras de una corta (RF-018-31): ``values`` (por la clave de ``provenance.PIT_FIGURES``; ``None``: no existe), ``benches`` (las de cada banco,
    :class:`~design.pit_model.BenchFigures`) y ``specs`` (las cifras CALCULADO con su unidad y su ámbito, ``provenance.pit_figures``)."""

    values: Mapping[str, float | int | None]
    benches: tuple[BenchFigures, ...]
    specs: tuple[FigureSpec, ...]


def _existing_length(item: Polyline, terrain: Raster, step_m: float) -> float:
    """La longitud (m) de ``item`` que está a la cota del terreno o por debajo (P-14); sin dato de terreno cuenta."""
    middle, length = _pieces(item.vertices, item.closed, step_m)
    ground = sample(terrain, middle[:, :2])
    with np.errstate(invalid="ignore"):
        above = middle[:, 2] > ground + TERRAIN_TOL_M
    return float(length[~above].sum())


def _flat_area(surface: PitSurface, levels: Sequence[float], cell_area: float) -> dict[float, float]:
    """El área (m²) de las celdas con corte donde la superficie es llana a cada cota de ``levels``."""
    wanted = np.array(sorted(set(levels)))
    if not len(wanted) or not surface.cut_cells.any():
        return dict.fromkeys(wanted.tolist(), 0.0)
    z = surface.surface[surface.cut_cells]
    at = np.searchsorted(wanted, z)
    low, high = np.clip(at - 1, 0, len(wanted) - 1), np.clip(at, 0, len(wanted) - 1)
    pick = np.where(np.abs(z - wanted[low]) <= np.abs(z - wanted[high]), low, high)
    flat = np.abs(z - wanted[pick]) <= FLAT_TOL_M
    counts = np.bincount(pick[flat], minlength=len(wanted))
    return {float(level): float(count) * cell_area for level, count in zip(wanted, counts, strict=True)}


def _band_volume(job: PitJob, surface: PitSurface, ramp: Any) -> float:
    """El volumen de corte (m³) de las celdas dentro de la banda de ``ramp`` (a su semiancho del eje, tramo a tramo)."""
    axis = np.asarray(ramp.path.axis, dtype=np.float64)
    half = np.asarray(ramp.path.half_width_m, dtype=np.float64)
    grid = job.grid
    inside = np.zeros(grid.shape, dtype=bool)
    for k in range(len(axis) - 1):
        a, b = axis[k, :2], axis[k + 1, :2]
        width = float(max(half[k], half[k + 1]))
        low, high = np.minimum(a, b) - width, np.maximum(a, b) + width
        col0 = max(int(math.floor((low[0] - grid.west) / grid.dx)), 0)
        col1 = min(int(math.ceil((high[0] - grid.west) / grid.dx)) + 1, grid.ncols)
        row0 = max(int(math.floor((grid.north - high[1]) / grid.dy)), 0)
        row1 = min(int(math.ceil((grid.north - low[1]) / grid.dy)) + 1, grid.nrows)
        if col1 <= col0 or row1 <= row0:
            continue
        x = grid.west + (np.arange(col0, col1) + 0.5) * grid.dx
        y = grid.north - (np.arange(row0, row1) + 0.5) * grid.dy
        gx, gy = np.meshgrid(x, y)
        delta = b - a
        length2 = float(delta @ delta)
        t = np.clip(((gx - a[0]) * delta[0] + (gy - a[1]) * delta[1]) / length2, 0.0, 1.0) if length2 > 0.0 else np.zeros_like(gx)
        distance = np.hypot(gx - (a[0] + t * delta[0]), gy - (a[1] + t * delta[1]))
        inside[row0:row1, col0:col1] |= distance <= width
    cut = np.where(surface.cut_cells & inside, job.start - surface.surface, 0.0)
    return math.fsum(cut.sum(axis=1).tolist()) * grid.cell_area


def figures(job: PitJob, polylines: Sequence[Polyline], surface: PitSurface, *, crs: CrsRef, vertical: VerticalRef, skyline: Skyline | None = None,
            ramps: Sequence[Any] = (), found: Sequence[Finding] = ()) -> Figures:
    """**A12** (RF-018-31): las cifras de la corta de ``job`` (ver el módulo). ``skyline`` (T19) da las de la línea de cielo, ``ramps`` las de las rampas
    y ``found`` (:func:`findings`) el recuento de hallazgos. ``crs`` y ``vertical`` son los del proyecto (solo para leer el terreno de partida)."""
    grid = job.grid
    terrain = Raster(grid, job.start, crs, vertical)
    step = _SAMPLE_FRACTION * min(grid.dx, grid.dy)
    height = job.height_m
    grouped = _by_bench(polylines)
    levels_up = job.mode is PitMode.UP
    z_all = np.concatenate([item.vertices[:, 2] for item in polylines])
    bottom = float(z_all.min())
    cell_levels: list[float] = []
    plan: dict[int, tuple[float, float, float, float, float]] = {}
    for bench, items in grouped.items():
        feet = [item for item in items if item.kind == PolylineKind.FOOT]
        crests = [item for item in items if item.kind == PolylineKind.CREST]
        z_foot = min((item.z_m for item in feet), default=None)
        z_crest_max = max((float(item.vertices[:, 2].max()) for item in crests), default=None)
        if z_foot is None:
            z_foot = min(item.z_m for item in crests) - height
        if z_crest_max is None:
            z_crest_max = z_foot + height
        z_crest = min((item.z_m for item in crests), default=z_foot + height)
        len_foot = math.fsum(_existing_length(item, terrain, step) for item in feet)
        len_crest = math.fsum(_existing_length(item, terrain, step) for item in crests)
        plan[bench] = (z_foot, z_crest, len_foot, len_crest, z_crest_max)
        cell_levels += [z_foot, z_crest]
    flat = _flat_area(surface, cell_levels, grid.cell_area)
    levels = surface.bench_levels
    entries: list[BenchFigures] = []
    for bench, (z_foot, z_crest, len_foot, len_crest, z_crest_max) in plan.items():
        berm_level, floor_level = (z_crest, z_foot) if levels_up else (z_foot, z_foot)
        area_floor = flat[floor_level] if abs(floor_level - bottom) <= _LEVEL_TOL_M else None
        area_berm = None if (not levels_up and area_floor is not None) else flat[berm_level]
        pick = (levels[:-1] >= z_foot - _LEVEL_TOL_M) & (levels[:-1] < z_crest_max - _LEVEL_TOL_M) if len(levels) > 1 else np.zeros(0, dtype=bool)
        cut = float(surface.bench_m3[pick].sum()) if len(pick) else 0.0
        entries.append(BenchFigures(bench, z_foot, z_crest, len_foot, len_crest, cut, area_berm, area_floor))
    values: dict[str, float | int | None] = {
        "des.pit_benches": len(plan),
        "des.pit_z_bottom_m": bottom,
        "des.pit_z_top_m": float(z_all.max()),
        "des.pit_len_foot_m": math.fsum(item.len_foot_m for item in entries),
        "des.pit_len_crest_m": math.fsum(item.len_crest_m for item in entries),
        "des.pit_area_berm_m2": math.fsum(item.area_berm_m2 or 0.0 for item in entries),
        "des.pit_area_floor_m2": math.fsum(item.area_floor_m2 or 0.0 for item in entries),
        "des.pit_cut_m3": float(surface.cut_m3),
        "des.pit_area_m2": float(np.count_nonzero(surface.cut_cells)) * grid.cell_area,
        "des.pit_findings": len(found),
    }
    sky = skyline
    values.update({
        "des.pit_sky_parts": None if sky is None else sky.n_parts,
        "des.pit_sky_len_m": None if sky is None else sky.length_m,
        "des.pit_sky_area_m2": None if sky is None else sky.area_m2,
        "des.pit_sky_z_min_m": None if sky is None else sky.z_min_m,
        "des.pit_sky_z_max_m": None if sky is None else sky.z_max_m,
        "des.pit_sky_dist_legal_m": None if sky is None or sky.legal is None else sky.legal.distance_m,
        "des.pit_sky_dist_perimeter_m": None if sky is None or sky.perimeter is None else sky.perimeter.distance_m,
    })
    if ramps:
        total = math.fsum(float(ramp.length_m) for ramp in ramps)
        rise = math.fsum(float(ramp.mean_gradient_pct) * float(ramp.length_m) for ramp in ramps)
        values.update({
            "des.pit_ramp_len_m": total,
            "des.pit_ramp_gradient_mean_pct": 0.0 if total <= 0.0 else rise / total,
            "des.pit_ramp_gradient_max_pct": max(float(ramp.max_gradient_pct) for ramp in ramps),
            "des.pit_ramp_band_m3": math.fsum(_band_volume(job, surface, ramp) for ramp in ramps),
        })
    else:
        values.update(dict.fromkeys(("des.pit_ramp_len_m", "des.pit_ramp_gradient_mean_pct", "des.pit_ramp_gradient_max_pct",
                                     "des.pit_ramp_band_m3")))
    return Figures(values, tuple(entries), pit_figures(job.request.name, job.code, values))
