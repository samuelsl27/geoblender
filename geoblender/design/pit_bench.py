# SPDX-License-Identifier: GPL-3.0-or-later
"""Los bancos de la corta: la corta **ascendente** (spec 018, T10; HU-018-1; RF-018-11, 14 y 25; CE-018-01 y 03; plan 018 §5.4 A5) y la
**descendente** (T11; RF-018-12 a 14; CE-018-04; A6, al final del módulo).

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

**La descendente** (:func:`descend_steps`) parte de cada límite (su cresta: el terreno vértice a vértice, densificado a ≤ el paso de la rejilla, o
la cota dada) y baja hacia dentro: ``pie_k = desfase_dentro(cresta_k, h/tan α)`` (el primer banco, de altura variable: ``(z − z_ancla)/tan α``
con el ancla la primera ``z₀ + j·h`` **estrictamente por debajo** del mínimo de la cresta, H-2) y ``cresta_{k+1} = desfase_dentro(pie_k, B)``.
Para por el primero de: el **ancho mínimo** (un pie que no contiene un círculo de diámetro ``w`` ⇔ su desfase hacia dentro de ``w/2`` queda vacío;
ese banco no se hace), la **cota de fondo** (el pie que bajaría de ella no se hace) y el **máximo de bancos**. Cada parte en que se divide el
interior es una polilínea propia (hasta 50). Da el fondo (cota, área y ancho útil, por bisección sobre el mismo motor) y el criterio que paró.

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
from ..gis.offset import offset_ring, simplify_ring
from ..gis.polygons import chain, overlay
from .messages import DesignError
from .pit_model import MAX_BENCHES, MAX_VERTICES, PitCode, PitJob, PitMode, PitSource, Polyline, PolylineKind, StopCriterion
from .pit_offset import PolylineOffset, Step, offset_polyline_steps
from .preview import Notice
from .road_section import sample_terrain
from .seeds import pace_progress

__all__ = ["MAX_BENCHES", "MAX_PARTS", "MAX_VERTICES", "Benches", "ascend", "ascend_steps", "descend", "descend_steps", "face_volume_m3"]

MAX_PARTS: int = 50
"""El tope de partes en que se divide el interior de un banco de la descendente (RF-018-14): un límite de validez, no una cifra minera."""
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
    el terreno es llano a la cota de la última cresta, CE-018-03). La descendente da además el **fondo** final (RF-018-13): su cota
    (``floor_level_m``), su área (``floor_area_m2``, m²) y su ancho útil (``floor_width_m``, m: el diámetro del mayor círculo que contiene, de
    la parte más ancha); la ascendente los deja en ``None`` y 0."""

    polylines: tuple[Polyline, ...]
    stop: StopCriterion
    count: int
    notices: tuple[Notice, ...]
    reliable: bool
    face_volume_m3: float
    floor_level_m: float | None = None
    floor_area_m2: float = 0.0
    floor_width_m: float | None = None


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


def _check_supported(job: PitJob, mode: PitMode = PitMode.UP) -> None:
    if job.mode is not mode:
        raise ValueError(f"la corta {'ascendente' if mode is PitMode.UP else 'descendente'} es la del modo «{mode.value}»")
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


def _offset(job: PitJob, ring: _Ring, step: Step, origin: np.ndarray, *, side: int = 1, z_m: np.ndarray | None = None,
            anchor_m: float | None = None) -> Generator[None, None, PolylineOffset]:
    """Los pasos del desfase de ``ring`` (cada ``Progress`` del motor, una unidad) y el :class:`PolylineOffset`; ``side`` es ``+1`` hacia
    fuera (la ascendente) o ``-1`` hacia dentro (la descendente) y ``z_m`` con ``anchor_m``, el primer banco de altura variable."""
    steps = offset_polyline_steps(
        ring.points, step=step, side=side, tol=job.params.arc_tol_m, corner=str(job.params.corner), simplify_m=ring.slack_m,
        profile=job.profile, rose=job.rose, n_berm=1, sectors=job.sectors, origin=origin, az_window_m=job.params.az_window_m,
        z_m=z_m, anchor_m=anchor_m)
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


# --- La corta descendente (A6) ---------------------------------------------------------------------------------------------


_BISECT_M = 5e-3
"""La resolución de la bisección del ancho útil (m): el ancho sale a ≤ 1 cm."""


@dataclass(slots=True, eq=False)
class _Crest:
    points: np.ndarray
    label: str
    z: np.ndarray
    slack_m: float = 0.0


@dataclass(slots=True, eq=False)
class _DownBench:
    """Un banco de un límite: las crestas que tienen pie, los pies, los huecos y la cota del pie."""

    index: int
    foot_z: float
    crests: list[_Crest]
    feet: list[tuple[np.ndarray, str]]
    holes: list[tuple[np.ndarray, str]]


@dataclass(slots=True, eq=False)
class _Descent:
    benches: list[_DownBench]
    stop: StopCriterion
    volume_m3: float


def _centroid_place(ring: np.ndarray, origin: np.ndarray) -> str:
    return _place(ring.mean(axis=0), origin)


def _fits(job: PitJob, ring: np.ndarray, width_m: float) -> bool:
    """Si ``ring`` contiene un círculo de diámetro ``width_m``: su desfase hacia dentro de ``width_m / 2`` no queda vacío (A6 i)."""
    found = offset_ring(ring, np.full(len(ring), 0.5 * width_m), -1, tol=job.params.arc_tol_m, corner=str(job.params.corner))
    return bool(found.rings)


def _useful_width(job: PitJob, ring: np.ndarray) -> float:
    """El ancho útil de ``ring`` (m): el doble de la distancia máxima a la que sobrevive su interior, por bisección sobre el mismo motor."""
    ring = simplify_ring(ring, job.params.arc_tol_m)  # el error de la simplificación es el del arco: el ancho sale a ≤ 2·arc_tol_m
    low, high = 0.0, 0.5 * float(min(np.ptp(ring[:, 0]), np.ptp(ring[:, 1]))) + _BISECT_M
    while high - low > _BISECT_M:
        middle = 0.5 * (low + high)
        found = offset_ring(ring, np.full(len(ring), middle), -1, tol=job.params.arc_tol_m, corner=str(job.params.corner))
        low, high = (middle, high) if found.rings else (low, middle)
    return 2.0 * low


def _first_anchor(z: np.ndarray, anchor_m: float, height_m: float) -> float:
    """La primera cota ``z₀ + j·h`` **por debajo** del mínimo de la cresta (H-2): una cresta sobre la retícula toma la siguiente."""
    index = math.ceil((float(z.min()) - anchor_m - _LATTICE_TOL_M) / height_m) - 1
    return anchor_m + index * height_m


def _descent_start(job: PitJob, source: PitSource, origin: np.ndarray) -> _Crest:
    """La cresta superior de un límite como anillo de trabajo (locales, antihorario, simplificado; con el terreno, densificado a ≤ el paso de la
    rejilla) y la cota de cada vértice (A1): la copia de trabajo no toca la entrada (RF-018-01)."""
    ring = np.asarray(source.ring, dtype=np.float64) - origin
    if _area(ring) < 0.0:
        ring = ring[::-1]
    ring = simplify_ring(ring, job.params.simplify_m)
    if source.level_m is None:
        dense = _samples(ring, min(job.grid.dx, job.grid.dy))
        ground = sample_terrain(job.start, job.grid, dense[:, 0] + origin[0], dense[:, 1] + origin[1])
        if np.isnan(ground).any():
            raise ValueError(f"el límite «{source.name}» sale de la rejilla o cae sin dato de terreno: la preparación lo rechaza antes (RF-018-04)")
        if float(np.ptp(ground)) <= _EXIT_TOL_M:
            # Un terreno llano en todo el contorno: la densificación no cambia ninguna distancia y solo añade vértices alineados.
            ground, dense = np.full(len(ring), float(ground[0])), ring
        ring, z = dense, ground
    else:
        z = np.full(len(ring), float(source.level_m))
    return _Crest(ring, "", z, job.params.simplify_m)


def _descend_limit(job: PitJob, source: PitSource, origin: np.ndarray, notices: list[Notice], flags: dict[str, bool]
                   ) -> Generator[None, None, _Descent]:
    name, params = job.request.name, job.params
    height = job.height_m
    width = params.min_floor_width_m
    crest = _descent_start(job, source, origin)
    first_foot_z = _first_anchor(crest.z, job.anchor_m, height)
    if params.bottom_level_m is not None and first_foot_z < params.bottom_level_m - _EXIT_TOL_M:
        raise ValueError(f"la cota de fondo {params.bottom_level_m!r} queda por encima del primer pie ({first_foot_z!r}) del límite "
                         f"«{source.name}»: la preparación lo rechaza antes")
    crests = [crest]
    benches: list[_DownBench] = []
    volumes: list[float] = []
    stop = StopCriterion.FLOOR_WIDTH
    index = 0
    while True:
        foot_z = first_foot_z - index * height
        if params.bottom_level_m is not None and foot_z < params.bottom_level_m - _EXIT_TOL_M:
            stop = StopCriterion.BOTTOM_LEVEL
            break
        used: list[_Crest] = []
        feet: list[tuple[np.ndarray, str]] = []
        holes: list[tuple[np.ndarray, str]] = []
        dead: list[np.ndarray] = []
        for item in crests:
            first = index == 0
            face = yield from _offset(job, _Ring(item.points, item.label, item.slack_m), Step.FACE, origin, side=-1,
                                      z_m=item.z if first else None, anchor_m=first_foot_z if first else None)
            if not face.result.verified:
                flags["reliable"] = False
                notices.append(Notice(PitCode.OFFSET_UNRELIABLE.value, {"name": name, "bench": index, "value": face.result.max_defect_m,
                                                                    "limit": params.arc_tol_m}))
            mine: list[tuple[np.ndarray, str]] = []
            for i, ring in enumerate(face.result.rings):
                if width is None or _fits(job, ring, width):
                    mine.append((ring, _label(face, i)))
                else:
                    dead.append(ring)
            for i, hole in enumerate(face.result.holes):
                holes.append((hole, _label(face, len(face.result.rings) + i)))
            if face.result.holes:
                notices.append(Notice(PitCode.HOLES.value, {"name": name, "bench": index, "count": len(face.result.holes)}))
            if mine:
                used.append(item)
                feet.extend(mine)
                top = float(item.z.mean()) if first else foot_z + height
                volumes.append(face_volume_m3(math.fsum(_area(r) for r, _l in mine), math.fsum(_perimeter(r) for r, _l in mine),
                                              _area(item.points), _perimeter(item.points), top - foot_z))
        if not feet:
            remaining = max((_useful_width(job, ring) for ring in dead), default=0.0)
            if index == 0:
                where = _centroid_place(max(dead, key=len) if dead else crests[0].points, origin)
                raise DesignError(PitCode.EMPTY.value, obj=name, field=source.name, value=remaining, name=name, bench=index, width=remaining,
                                  limit=0.0 if width is None else width, place=where)
            if width is not None:
                notices.append(Notice(PitCode.FLOOR_TOO_SMALL.value, {"name": name, "bench": index, "width": remaining, "minimum": width}))
            break
        if len(feet) > MAX_PARTS:
            raise DesignError(PitCode.TOO_MANY_PARTS.value, obj=name, field=source.name, value=len(feet), name=name, bench=index,
                              count=len(feet), limit=MAX_PARTS, place=_centroid_place(feet[MAX_PARTS][0], origin))
        if index >= MAX_BENCHES:
            raise DesignError(PitCode.TOO_MANY_BENCHES.value, obj=name, field="max_benches", value=index, name=name, limit=MAX_BENCHES,
                              vertices=max(len(r) for r, _l in feet))
        benches.append(_DownBench(index, foot_z, used, feet, holes))
        if params.bottom_level_m is not None and foot_z <= params.bottom_level_m + _EXIT_TOL_M:
            stop = StopCriterion.BOTTOM_LEVEL
            break
        if params.max_benches is not None and index + 1 >= params.max_benches:
            stop = StopCriterion.MAX_BENCHES
            break
        carried: list[_Crest] = []
        for foot, label in feet:
            berm = yield from _offset(job, _Ring(foot, label, 0.0), Step.BERM, origin, side=-1)
            if not berm.result.verified:
                flags["reliable"] = False
                notices.append(Notice(PitCode.OFFSET_UNRELIABLE.value, {"name": name, "bench": index + 1, "value": berm.result.max_defect_m,
                                                                    "limit": params.arc_tol_m}))
            carried.extend(_Crest(ring, _label(berm, i), np.full(len(ring), foot_z)) for i, ring in enumerate(berm.result.rings))
        if not carried:
            break
        crests = carried
        index += 1
        yield
    return _Descent(benches, stop, math.fsum(volumes))


def _polyline(job: PitJob, origin: np.ndarray, kind: PolylineKind, bench: int, ring: np.ndarray, z: np.ndarray, part: int, label: str
              ) -> Polyline:
    if len(ring) > MAX_VERTICES:
        raise DesignError(PitCode.TOO_MANY_BENCHES.value, obj=job.request.name, field="vertices", value=len(ring), name=job.request.name,
                          limit=MAX_BENCHES, vertices=len(ring))
    return Polyline(kind, bench, np.column_stack([ring + origin, z]), sector=label, part=part)


def _by_position(items: list[tuple[np.ndarray, str, np.ndarray]]) -> list[tuple[np.ndarray, str, np.ndarray]]:
    return sorted(items, key=lambda item: (float(item[0][:, 0].min()), float(item[0][:, 1].min()), len(item[0])))


def _descend_units(job: PitJob) -> Generator[None, None, Benches]:
    _check_supported(job, PitMode.DOWN)
    params = job.params
    if params.min_floor_width_m is None and params.bottom_level_m is None and params.max_benches is None:
        raise ValueError("una corta descendente lleva al menos un criterio de parada: el ancho mínimo de fondo, la cota de fondo o el máximo de "
                         "bancos (RF-018-13, D-8); la preparación lo rechaza antes")
    grid = job.grid
    origin = np.array([grid.west, grid.north - grid.nrows * grid.dy], dtype=np.float64)
    notices: list[Notice] = []
    flags = {"reliable": True}
    descents: list[_Descent] = []
    for source in job.sources:
        descents.append((yield from _descend_limit(job, source, origin, notices, flags)))
    polylines: list[Polyline] = []
    for index in range(max(len(item.benches) for item in descents)):
        here = [item.benches[index] for item in descents if index < len(item.benches)]
        crests = _by_position([(c.points, c.label, c.z) for bench in here for c in bench.crests])
        feet = _by_position([(r, label, np.full(len(r), bench.foot_z)) for bench in here for r, label in bench.feet])
        feet += _by_position([(r, label, np.full(len(r), bench.foot_z)) for bench in here for r, label in bench.holes])
        for part, (ring, label, z) in enumerate(crests):
            polylines.append(_polyline(job, origin, PolylineKind.CREST, index, ring, z, part, label))
        for part, (ring, label, z) in enumerate(feet):
            polylines.append(_polyline(job, origin, PolylineKind.FOOT, index, ring, z, part, label))
    deepest = min(item.benches[-1].foot_z for item in descents)
    chosen = [item for item in descents if item.benches[-1].foot_z == deepest]
    floors = [ring for item in chosen for ring, _label_ in item.benches[-1].feet]
    return Benches(
        tuple(polylines), chosen[0].stop, max(len(item.benches) for item in descents), tuple(notices), flags["reliable"],
        math.fsum(item.volume_m3 for item in descents), deepest, math.fsum(_area(ring) for ring in floors),
        max(_useful_width(job, ring) for ring in floors))


def descend_steps(job: PitJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A6** (RF-018-12 a 14): los bancos de la corta descendente de ``job`` por pasos de ``budget_s`` como mucho (cada desfase cede al motor;
    cerrar el generador a mitad no deja nada): el último ``Progress`` (fase ``pit_bench``) lleva los :class:`Benches`, con el fondo y el criterio que
    paró. Los rechazos (``DesignError``: ``des.pit_empty``, ``des.pit_too_many_parts``, ``des.pit_too_many_benches``) salen al avanzar; no se
    escribe nada ni se relaja ningún parámetro."""
    return pace_progress(_descend_units(job), budget_s, phase=_PHASE, running="Calculando los bancos…", finished="Bancos calculados")


def descend(job: PitJob) -> Benches:
    """:func:`descend_steps` hasta el final, sin pasos: los :class:`Benches` de ``job``. Los mismos rechazos."""
    work = _descend_units(job)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: Benches = done.value
            return result
