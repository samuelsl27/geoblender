# SPDX-License-Identifier: GPL-3.0-or-later
"""Los bancos de la corta: la corta **ascendente** (spec 018, T10; HU-018-1; RF-018-11, 14 y 25; CE-018-01 y 03; plan 018 §5.4 A5).

Desde cada polígono de fondo, a su cota, banco a banco (``k = 0, 1, …``): el **pie** ``k`` (a ``z₀ + k·h``), la **cresta** ``k`` (el pie desfasado
hacia fuera ``h/tan α`` por arista, a ``z₀ + (k + 1)·h``) y el pie ``k + 1`` (la cresta desfasada la berma ``B``). Todo es **la distancia por
arista** de :func:`design.pit_offset.edge_distances` y el desfase de :func:`gis.offset.offset_ring_steps`: este módulo solo es el bucle, sin saber
de geometría.

- **La salida a superficie.** Un pie **sale** cuando todos sus vértices y las muestras de sus aristas (una por celda de la rejilla, como mucho)
  están a una cota igual o mayor que la del terreno de la partida (muestreo bilineal, :func:`design.road_section.sample_terrain`); el pie que
  sale **no se emite** (ya no excava: es la línea de salida). Si el usuario da la cota de coronación (``top_level_m``), la corta para en el primer
  banco cuyo pie llega a ella (``TOP_LEVEL``); si las dos cosas coinciden, manda la superficie. Una corta que no sale en el máximo de bancos
  (200, o el ``max_benches`` del usuario si es menor) o que se sale de la rejilla antes de salir a superficie **se rechaza** con el banco, el
  límite y el lugar (RF-018-14); nada se relaja ni se registra. Un fondo que no queda por debajo del terreno en ningún punto de su contorno
  (RF-018-04) también.
- **Los fondos que se tocan** se unen al crecer (``overlay`` de la 012 sobre los anillos): desde el banco en que sus pies se solapan son **una**
  polilínea. Cada fondo empieza en el banco de su cota (``z₀ + j·h``; una cota fuera de esa retícula rompería los planos continuos, D-4, y es
  un error de la preparación). Los huecos del desfase (o de la unión) se guardan como polilíneas propias, con su aviso (``des.pit_holes``).
- **El resultado** (:class:`Benches`) lleva las polilíneas en su orden registrado (RF-018-25: por banco y, dentro del banco, por parte —ordenadas
  por su posición, no por el orden de entrada—, cada una con su pie y su cresta), el criterio que paró, los avisos (``des.pit_offset_unreliable``
  si un desfase no pasó su verificación: **nunca en silencio**; quien registra lo rechaza) y el **volumen de las caras sin la rejilla**
  (:func:`face_volume_m3`).

**No hace todavía** (lo hacen las tareas siguientes, y hasta entonces se pide con un error del programa, no se ignora): las bermas cada ``n``
bancos (``n > 1``) y los bancos fijados (T12), las rampas (T15 a T17) ni el cierre morfológico. Los anillos van en **locales** (m desde la esquina
suroeste de la rejilla, ADR-0005) y las polilíneas salen absolutas. Python puro con numpy (nivel 8); no lo importa el arranque.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.offset import simplify_ring
from ..gis.polygons import chain, overlay
from .messages import DesignError
from .pit_model import MAX_BENCHES, MAX_VERTICES, PitCode, PitJob, PitMode, Polyline, PolylineKind, StopCriterion
from .pit_offset import PolylineOffset, Step, offset_polyline_steps
from .preview import Notice
from .road_section import sample_terrain
from .seeds import pace_progress

__all__ = ["MAX_BENCHES", "MAX_VERTICES", "Benches", "ascend", "ascend_steps", "face_volume_m3"]

_PHASE = "pit_bench"
_EXIT_TOL_M = 1e-9
"""Lo que un pie puede quedar por debajo del terreno y salir (m): el error de redondeo del muestreo bilineal."""
_LATTICE_TOL_M = 1e-6
"""Lo que una cota de fondo puede apartarse de ``z₀ + j·h`` (m)."""


@dataclass(frozen=True, slots=True, eq=False)
class Benches:
    """Los bancos de una corta (RF-018-11): las ``polylines`` en su orden registrado (RF-018-25), el criterio que paró (``stop``:
    ``SURFACE`` o ``TOP_LEVEL``), los bancos calculados (``count``), los ``notices`` (avisos de ``design.messages``), si todos los desfases
    se verificaron (``reliable``) y el volumen de las caras sin rejilla (``face_volume_m3``, m³: de cada pie a su cresta; es el desmonte si
    el terreno es llano a la cota de la última cresta, CE-018-03)."""

    polylines: tuple[Polyline, ...]
    stop: StopCriterion
    count: int
    notices: tuple[Notice, ...]
    reliable: bool
    face_volume_m3: float


@dataclass(slots=True, eq=False)
class _Ring:
    points: np.ndarray
    label: str = ""
    slack_m: float = 0.0


@dataclass(slots=True, eq=False)
class _Source:
    level_index: int
    order: int
    ring: _Ring


def _area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _perimeter(ring: np.ndarray) -> float:
    return float(np.hypot(*(np.roll(ring, -1, axis=0) - ring).T).sum())


def face_volume_m3(foot_area: float, foot_perimeter: float, crest_area: float, crest_perimeter: float, height_m: float) -> float:
    """El volumen (m³) del sólido entre un pie y su cresta, de altura ``height_m``, **sin rejilla**: con el área de la sección como un
    polinomio de segundo grado en el avance (``A(t) = A₀ + P₀·t + c·t²``: la ley de un contorno desfasado a distancia constante), el volumen
    sale de las áreas y los perímetros de pie y cresta, ``h·[A_p + (A_c − A_p)·(2P_p + P_c)/(3·(P_p + P_c))]``. Exacto para el círculo (el
    tronco de cono, ``π·h/3·(r² + r·R + R²)``) y para todo desfase redondeado de distancia constante; con la roseta es una estimación."""
    total = foot_perimeter + crest_perimeter
    if not total > 0.0:
        return 0.0
    return height_m * (foot_area + (crest_area - foot_area) * (2.0 * foot_perimeter + crest_perimeter) / (3.0 * total))


# --- El terreno -----------------------------------------------------------------------------------------------------------


def _samples(ring: np.ndarray, step_m: float) -> np.ndarray:
    """Los vértices del anillo y, en cada arista, un punto cada ``step_m`` como mucho."""
    ahead = np.roll(ring, -1, axis=0)
    span = ahead - ring
    count = np.maximum(1, np.ceil(np.hypot(span[:, 0], span[:, 1]) / step_m)).astype(np.int64)
    edge = np.repeat(np.arange(len(ring)), count)
    first = np.cumsum(count) - count
    t = (np.arange(int(count.sum())) - np.repeat(first, count)) / count[edge]
    return ring[edge] + t[:, None] * span[edge]


def _place(point: np.ndarray, origin: np.ndarray, *, no_data: bool = False) -> str:
    x, y = point + origin
    return f"{x:.1f}, {y:.1f}" + (" (sin dato de terreno)" if no_data else "")


def _ground_gap(job: PitJob, ring: np.ndarray, level: float, origin: np.ndarray) -> tuple[float, str, bool]:
    """Lo que el terreno de la partida queda por encima de ``level`` en el anillo (m, el máximo; con el lugar) y si le falta el dato en algún punto
    (entonces, el primero que falta)."""
    points = _samples(ring, min(job.grid.dx, job.grid.dy))
    ground = sample_terrain(job.start, job.grid, points[:, 0] + origin[0], points[:, 1] + origin[1])
    missing = np.isnan(ground)
    if missing.any():
        return math.nan, _place(points[int(np.argmax(missing))], origin, no_data=True), True
    gap = ground - level
    worst = int(np.argmax(gap))
    return float(gap[worst]), _place(points[worst], origin), False


# --- El bucle -------------------------------------------------------------------------------------------------------------


def _check_supported(job: PitJob) -> None:
    if job.mode is not PitMode.UP:
        raise ValueError("la corta ascendente es la del modo «up»")
    if job.params.n_berm != 1 or any(sector.n_berm not in (None, 1) for sector in job.sectors):
        raise ValueError("las bermas cada n bancos (n > 1) son de la T12 de la spec 018: todavía no se admiten")
    if job.fixed:
        raise ValueError("los bancos fijados son de la T12 de la spec 018: todavía no se admiten")


def _prepared(job: PitJob, origin: np.ndarray) -> list[_Source]:
    """Los fondos como anillos de trabajo (locales, antihorarios, simplificados con ``simplify_m``: A1), con su banco de entrada; la copia de
    trabajo no toca la entrada (RF-018-01)."""
    found: list[_Source] = []
    for order, source in enumerate(job.sources):
        assert source.level_m is not None
        index = round((source.level_m - job.anchor_m) / job.height_m)
        if abs(source.level_m - (job.anchor_m + index * job.height_m)) > _LATTICE_TOL_M:
            raise ValueError(f"la cota {source.level_m!r} del fondo «{source.name}» no es z₀ + j·h (z₀ = {job.anchor_m!r}, h = {job.height_m!r}): "
                             "los bancos son planos continuos (D-4) y la preparación lo rechaza antes")
        ring = np.asarray(source.ring, dtype=np.float64) - origin
        if _area(ring) < 0.0:
            ring = ring[::-1]
        ring = simplify_ring(ring, job.params.simplify_m)
        level = job.anchor_m + index * job.height_m
        gap, _place_, missing = _ground_gap(job, ring, level, origin)
        if missing:
            raise ValueError(f"el fondo «{source.name}» sale de la rejilla o cae sin dato de terreno: la preparación lo rechaza antes (RF-018-04)")
        if gap <= _EXIT_TOL_M:
            raise DesignError(PitCode.NOTHING_TO_EXCAVATE.value, obj=job.request.name, field=source.name, value=source.level_m,
                              name=job.request.name)
        found.append(_Source(index, order, _Ring(ring, "", job.params.simplify_m)))
    return found


def _label(offset: PolylineOffset, index: int) -> str:
    """El sector común de los vértices del anillo ``index`` del desfase, o ``""`` si hay varios (o ninguno)."""
    found = {offset.sector_labels[int(item)] for item in offset.sector_of_vertex[index]}
    return found.pop() if len(found) == 1 else ""


def _sorted(rings: list[_Ring]) -> list[_Ring]:
    return sorted(rings, key=lambda ring: (float(ring.points[:, 0].min()), float(ring.points[:, 1].min()), len(ring.points)))


def _boxes_touch(rings: list[_Ring]) -> bool:
    boxes = [(r.points[:, 0].min(), r.points[:, 1].min(), r.points[:, 0].max(), r.points[:, 1].max()) for r in rings]
    return any(boxes[i][0] <= boxes[j][2] and boxes[j][0] <= boxes[i][2] and boxes[i][1] <= boxes[j][3] and boxes[j][1] <= boxes[i][3]
               for i in range(len(boxes)) for j in range(i + 1, len(boxes)))


def _united(rings: list[_Ring]) -> tuple[list[_Ring], list[np.ndarray]]:
    """Los anillos con los que se tocan unidos (``overlay`` de la 012); y los huecos que deja la unión."""
    if len(rings) < 2 or not _boxes_touch(rings):
        return rings, []
    region = overlay([[ring.points] for ring in rings], [], "union", origin=(0.0, 0.0))
    loops = chain(region.edges_local)
    slack = max(ring.slack_m for ring in rings)
    outer = [_Ring(loop, "", slack) for loop in loops if _area(loop) > 0.0]
    return outer, [loop for loop in loops if _area(loop) <= 0.0]


def _offset(job: PitJob, ring: _Ring, step: Step, origin: np.ndarray) -> Generator[None, None, PolylineOffset]:
    """Los pasos del desfase de ``ring`` (cada ``Progress`` del motor, una unidad) y el :class:`PolylineOffset`."""
    steps = offset_polyline_steps(
        ring.points, step=step, side=1, tol=job.params.arc_tol_m, corner=str(job.params.corner), simplify_m=ring.slack_m,
        profile=job.profile, rose=job.rose, n_berm=1, sectors=job.sectors, origin=origin, az_window_m=job.params.az_window_m)
    with closing(steps):
        for progress in steps:
            if progress.result is None:
                yield
                continue
            assert isinstance(progress.result, PolylineOffset)
            return progress.result
    raise AssertionError("el desfase no dio su resultado")


def _ascend_units(job: PitJob) -> Generator[None, None, Benches]:
    _check_supported(job)
    name, params = job.request.name, job.params
    height, anchor = job.height_m, job.anchor_m
    grid = job.grid
    origin = np.array([grid.west, grid.north - grid.nrows * grid.dy], dtype=np.float64)
    limit = MAX_BENCHES if params.max_benches is None else min(MAX_BENCHES, params.max_benches)
    pending = sorted(_prepared(job, origin), key=lambda item: (item.level_index, item.order))
    polylines: list[Polyline] = []
    notices: list[Notice] = []
    volumes: list[float] = []
    reliable = True
    active: list[_Ring] = []
    foot_holes: list[np.ndarray] = []
    level_index = pending[0].level_index
    done = 0
    stop = StopCriterion.SURFACE

    def line(kind: PolylineKind, bench: int, ring: np.ndarray, level: float, part: int, label: str) -> Polyline:
        if len(ring) > MAX_VERTICES:
            raise DesignError(PitCode.TOO_MANY_BENCHES.value, obj=name, field="vertices", value=len(ring), name=name, limit=MAX_BENCHES,
                              vertices=len(ring))
        xyz = np.column_stack([ring + origin, np.full(len(ring), level)])
        return Polyline(kind, bench, xyz, sector=label, part=part)

    while True:
        while pending and pending[0].level_index <= level_index:
            active.append(pending.pop(0).ring)
        active, holes = _united(active)
        foot_holes.extend(holes)
        active = _sorted(active)
        level = anchor + level_index * height
        growing: list[_Ring] = []
        worst = ""
        for ring in active:
            gap, where, missing = _ground_gap(job, ring.points, level, origin)
            if missing:
                raise DesignError(PitCode.NOT_REACHING_SURFACE.value, obj=name, field="max_benches", value=done, name=name, limit=done,
                                  bench=level_index, place=where)
            if gap > _EXIT_TOL_M:
                growing.append(ring)
                worst = worst or where
        active = growing
        if not active:
            foot_holes.clear()
            if pending:
                level_index = pending[0].level_index
                continue
            stop = StopCriterion.SURFACE
            break
        if params.top_level_m is not None and level >= params.top_level_m - _EXIT_TOL_M:
            stop = StopCriterion.TOP_LEVEL
            break
        if done >= limit:
            raise DesignError(PitCode.NOT_REACHING_SURFACE.value, obj=name, field="max_benches", value=limit, name=name, limit=limit,
                              bench=level_index, place=worst)
        parts = {PolylineKind.FOOT: 0, PolylineKind.CREST: 0}
        carried: list[_Ring] = []
        for ring in active:
            polylines.append(line(PolylineKind.FOOT, level_index, ring.points, level, parts[PolylineKind.FOOT], ring.label))
            parts[PolylineKind.FOOT] += 1
            face = yield from _offset(job, ring, Step.FACE, origin)
            if not face.result.verified:
                reliable = False
                notices.append(Notice(PitCode.OFFSET_UNRELIABLE.value, {"name": name, "bench": level_index, "value": face.result.max_defect_m,
                                                                    "limit": params.arc_tol_m}))
            crests = [(crest, _label(face, i)) for i, crest in enumerate(face.result.rings)]
            for index, (crest, label) in enumerate(crests):
                polylines.append(line(PolylineKind.CREST, level_index, crest, level + height, parts[PolylineKind.CREST], label))
                parts[PolylineKind.CREST] += 1
            for index, hole in enumerate(face.result.holes):
                polylines.append(line(PolylineKind.CREST, level_index, hole, level + height, parts[PolylineKind.CREST],
                                      _label(face, len(crests) + index)))
                parts[PolylineKind.CREST] += 1
            if face.result.holes:
                notices.append(Notice(PitCode.HOLES.value, {"name": name, "bench": level_index, "count": len(face.result.holes)}))
            loops = [*face.result.rings, *face.result.holes]
            volumes.append(face_volume_m3(_area(ring.points), _perimeter(ring.points), math.fsum(_area(loop) for loop in loops),
                                          math.fsum(_perimeter(loop) for loop in loops), height))
            for crest, label in crests:
                berm = yield from _offset(job, _Ring(crest, label, 0.0), Step.BERM, origin)
                if not berm.result.verified:
                    reliable = False
                    notices.append(Notice(PitCode.OFFSET_UNRELIABLE.value, {"name": name, "bench": level_index + 1, "value": berm.result.max_defect_m,
                                                                        "limit": params.arc_tol_m}))
                carried.extend(_Ring(foot, _label(berm, i)) for i, foot in enumerate(berm.result.rings))
                foot_holes.extend(berm.result.holes)
        for hole in foot_holes:
            polylines.append(line(PolylineKind.FOOT, level_index, hole, level, parts[PolylineKind.FOOT], ""))
            parts[PolylineKind.FOOT] += 1
        if foot_holes:
            notices.append(Notice(PitCode.HOLES.value, {"name": name, "bench": level_index, "count": len(foot_holes)}))
        foot_holes = []
        active = carried
        done += 1
        level_index += 1
        yield

    return Benches(tuple(polylines), stop, done, tuple(notices), reliable, math.fsum(volumes))


def ascend_steps(job: PitJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A5** (RF-018-11, 14, 25): los bancos de la corta ascendente de ``job`` por pasos de ``budget_s`` como mucho (cada desfase cede al motor;
    cerrar el generador a mitad no deja nada): el último ``Progress`` (fase ``pit_bench``) lleva los :class:`Benches`. Los rechazos
    (``DesignError``: ``des.pit_not_reaching_surface``, ``des.pit_nothing_to_excavate``, ``des.pit_too_many_benches``) salen al avanzar; no se
    escribe nada ni se relaja ningún parámetro."""
    return pace_progress(_ascend_units(job), budget_s, phase=_PHASE, running="Calculando los bancos…", finished="Bancos calculados")


def ascend(job: PitJob) -> Benches:
    """:func:`ascend_steps` hasta el final, sin pasos: los :class:`Benches` de ``job``. Los mismos rechazos."""
    work = _ascend_units(job)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: Benches = done.value
            return result
