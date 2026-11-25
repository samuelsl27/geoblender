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

**Los bancos dobles** (T12; RF-018-08): con ``n > 1`` la berma se deja cada ``n`` bancos y la cara entre bermas es la de ``n·h`` (el avance, ``n·h/tan α
+ B``): cada paso del bucle sube o baja ``n·h`` y el banco ``k`` es el que parte de ``z₀ + k·n·h`` (los fondos de una ascendente, en esa retícula). El
``n`` es **uno** para toda la corta (el del perfil base y el de sus sectores, que si no coinciden se rechazan con un error del programa: aún no se
mezclan bancos simples y dobles). **Los bancos fijados** (RF-018-23 y 24): una línea cerrada con su Z que sustituye, tal cual (``Polyline.fixed``), al
**pie** de su banco en la ascendente y a la **cresta** de su banco (``k >= 1``) en la descendente; el bucle sigue desde ella con las mismas piezas.
Se rechazan con el banco y el lugar (``des.pit_fixed_cross``, ``des.pit_fixed_level``) los que se cortan entre sí, los que cortan o caen fuera del
banco que los contiene, los que no dejan sitio al siguiente y los que la corta no alcanza; nunca se mueve la línea del usuario. **«Un paso»**
(:func:`expand_one_steps`, RF-018-22, A7): el desfase de una sola polilínea, con su comprobación de inclinación y berma, sin escribir nada.

**No hace todavía** (lo hacen las tareas siguientes): las rampas (T15 a T17) ni el cierre morfológico. Los anillos van en **locales** (m desde la
esquina suroeste de la rejilla, ADR-0005) y las polilíneas salen absolutas. Python puro con numpy (nivel 8); no lo importa el arranque.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Generator, Iterator
from contextlib import closing
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.offset import simplify_ring
from ..gis.polygons import chain, crossings, overlay
from .messages import DesignError
from .pit_bench_ramp import RampLoop, RingPlan as RampPlan
from .pit_model import (MAX_BENCHES, MAX_VERTICES, FixedBench, PitCode, PitJob, PitMode, PitSource, Polyline, PolylineKind,
                        StopCriterion)
from .pit_offset import PolylineOffset, Step, edge_distances, offset_polyline_steps
from .pit_ramp import RampChecked
from .pit_report import inscribed_width
from .preview import Notice
from .road_section import sample_terrain
from .seeds import pace_progress

__all__ = ["MAX_BENCHES", "MAX_PARTS", "MAX_VERTICES", "Benches", "Expansion", "ascend", "ascend_steps", "descend", "descend_steps",
           "expand_one", "expand_one_steps", "face_volume_m3"]

MAX_PARTS: int = 50
"""El tope de partes en que se divide el interior de un banco de la descendente (RF-018-14): un límite de validez, no una cifra minera."""
_PHASE = "pit_bench"
_EXIT_TOL_M = 1e-9
"""Lo que un pie puede quedar por debajo del terreno y salir (m): el error de redondeo del muestreo bilineal."""
_LATTICE_TOL_M = 1e-6
"""Lo que una cota de fondo puede apartarse de ``z₀ + j·h`` (m)."""
_LEVEL_TOL_M = 1e-9
"""Lo que la Z de un banco fijado puede apartarse de la cota de su banco (m, RF-018-23)."""
_CLEAR_TOL_M = 1e-3
"""Lo que un banco fijado debe separarse como mínimo de la cresta o el pie vecinos (m, RF-018-24: «no deja sitio»): una berma de menos de un milímetro no existe."""


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
    ramps: tuple[RampChecked, ...] = ()


@dataclass(slots=True, eq=False)
class _Ring:
    points: np.ndarray
    label: str = ""
    slack_m: float = 0.0
    fixed: FixedBench | None = None


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
    _n_berm(job)


def _n_berm(job: PitJob) -> int:
    """Los bancos por berma de la corta (RF-018-08): el del perfil base y el de sus sectores, que deben coincidir (un error del programa si no:
    mezclar bancos simples y dobles es de una tarea posterior)."""
    found = {job.params.n_berm, *(sector.n_berm for sector in job.sectors if sector.n_berm is not None)}
    if len(found) > 1:
        raise ValueError(f"los bancos por berma de los sectores ({sorted(found)}) no coinciden con los de la corta: mezclar bancos simples y "
                         "dobles no se admite todavía (RF-018-08)")
    return found.pop()


# --- Las ayudas de los bancos fijados --------------------------------------------------------------------------------------


@dataclass(slots=True, eq=False)
class _Fixed:
    """Un banco fijado ya preparado: su ``bench`` y su ``level`` (m; ``None`` hasta que se sabe, en la descendente), el anillo local antihorario
    (una copia: la línea del usuario no se toca) y si la corta lo ha usado."""

    item: FixedBench
    bench: int | None
    level: float | None
    ring: np.ndarray
    used: bool = False

    @property
    def label(self) -> object:
        return self.bench if self.bench is not None else self.item.name


def _inside(point: np.ndarray, ring: np.ndarray) -> bool:
    """Si ``point`` está dentro de ``ring`` (rayo hacia +X)."""
    x, y = float(point[0]), float(point[1])
    ahead = np.roll(ring, -1, axis=0)
    straddles = (ring[:, 1] > y) != (ahead[:, 1] > y)
    a, b = ring[straddles], ahead[straddles]
    crossing_x = a[:, 0] + (y - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
    return bool(np.count_nonzero(x < crossing_x) % 2)


def _crossing(first: np.ndarray, second: np.ndarray) -> np.ndarray | None:
    """El primer punto en que se cortan dos anillos, o ``None``."""
    if (first[:, 0].max() < second[:, 0].min() or second[:, 0].max() < first[:, 0].min()
            or first[:, 1].max() < second[:, 1].min() or second[:, 1].max() < first[:, 1].min()):
        return None
    found = crossings(first, np.roll(first, -1, axis=0), second, np.roll(second, -1, axis=0))
    return found[4][0] if len(found[4]) else None


def _near(first: np.ndarray, second: np.ndarray, tol_m: float) -> np.ndarray | None:
    """El primer vértice de un anillo a menos de ``tol_m`` del otro (el punto), o ``None``: dos anillos que casi coinciden no dejan sitio entre ellos (T40b: una línea
    fijada igual a la cresta calculada, a una milésima, pasaba por «sin cortes» y la triangulación de la superficie la rechazaba sin banco ni lugar)."""
    for ring, other in ((first, second), (second, first)):
        a, b = other, np.roll(other, -1, axis=0)
        edge = b - a
        length2 = np.maximum((edge * edge).sum(axis=1), 1e-300)
        for start in range(0, len(ring), 256):
            chunk = ring[start:start + 256]
            t = np.clip(((chunk[:, None, :] - a[None]) * edge[None]).sum(axis=2) / length2[None], 0.0, 1.0)
            nearest = a[None] + t[:, :, None] * edge[None]
            distance = np.hypot(*(chunk[:, None, :] - nearest).transpose(2, 0, 1))
            hit = np.flatnonzero(distance.min(axis=1) < tol_m)
            if hit.size:
                return chunk[int(hit[0])]
    return None


def _touch(first: np.ndarray, second: np.ndarray) -> bool:
    """Si dos anillos se solapan: se cortan o uno está dentro del otro."""
    return _crossing(first, second) is not None or _inside(first[0], second) or _inside(second[0], first)


def _ccw(ring: np.ndarray) -> np.ndarray:
    return ring[::-1] if _area(ring) < 0.0 else ring


def _fixed_error(job: PitJob, fixed: _Fixed, other: object, point: np.ndarray, origin: np.ndarray, note: str = "") -> DesignError:
    """``des.pit_fixed_cross`` en ``point`` (local; ``origin`` lo lleva a absoluto): las dos coordenadas van como números (``x``, ``y``, al decímetro), para que el mensaje las escriba con el formato
    de las demás cifras (coma decimal y espacio de miles en español; T40e, H3-7), y ``note`` es lo que sigue al lugar."""
    name = job.request.name
    x, y = point + origin
    return DesignError(PitCode.FIXED_CROSS.value, obj=name, field=fixed.item.name, value=fixed.label, name=name, bench=fixed.label,
                       other=other, x=round(float(x), 1), y=round(float(y), 1), note=note)


def _level_error(job: PitJob, item: FixedBench, value: float, bench: object, level: float) -> DesignError:
    name = job.request.name
    return DesignError(PitCode.FIXED_LEVEL.value, obj=name, field=item.name, value=value, name=name, bench=bench, level=level)


def _check_level(job: PitJob, fixed: _Fixed, level: float) -> None:
    """La cota de un banco fijado: la de su banco (la dada y la Z de cada vértice, a <= 1e-9 m) o se rechaza con el banco y las dos cotas."""
    item = fixed.item
    if item.level_m is not None and abs(item.level_m - level) > _LEVEL_TOL_M:
        raise _level_error(job, item, item.level_m, fixed.label, level)
    worst = float(item.vertices[int(np.argmax(np.abs(item.vertices[:, 2] - level))), 2])
    if abs(worst - level) > _LEVEL_TOL_M:
        raise _level_error(job, item, worst, fixed.label, level)


def _resolve_fixed(job: PitJob, origin: np.ndarray, *, up: bool, n: int) -> list[_Fixed]:
    """Los bancos fijados de ``job`` (RF-018-23): cerrados, con la cota de su banco (la ascendente la sabe: ``z₀ + b·n·h``; la descendente la
    comprueba al usarlos) y sin cortarse entre sí (RF-018-24)."""
    found: list[_Fixed] = []
    for item in job.fixed:
        if not item.closed:
            raise ValueError(f"el banco fijado «{item.name}» es una línea abierta: un banco es un anillo (la preparación cierra los polígonos)")
        bench, level = item.bench, None
        if up:
            step = n * job.height_m
            if bench is None:
                assert item.level_m is not None
                bench = round((item.level_m - job.anchor_m) / step)
            level = job.anchor_m + bench * step
        elif bench is not None and bench < 1:
            raise ValueError(f"el banco fijado «{item.name}» es la cresta de su banco y los de una descendente empiezan en la cresta 1 "
                             f"(la cresta 0 es el límite), no en {bench!r}")
        fixed = _Fixed(item, bench, level, _ccw(np.asarray(item.vertices[:, :2], dtype=np.float64) - origin))
        if level is not None:
            _check_level(job, fixed, level)
        found.append(fixed)
    for i, first in enumerate(found):
        for second in found[i + 1:]:
            point = _crossing(first.ring, second.ring)
            if point is not None:
                raise _fixed_error(job, first, second.label, point, origin)
    return found


def _unused(job: PitJob, fixed: list[_Fixed], origin: np.ndarray) -> None:
    """Un banco fijado que la corta no alcanza se rechaza (RF-018-24): no se ignora."""
    for item in fixed:
        if not item.used:
            above = item.bench - 1 if item.bench is not None else "anterior"
            raise _fixed_error(job, item, above, item.ring[0], origin, " (la corta no llega a ese banco)")


def _prepared(job: PitJob, origin: np.ndarray, n: int = 1) -> list[_Source]:
    """Los fondos como anillos de trabajo (locales, antihorarios, simplificados con ``simplify_m``: A1), con su banco de entrada; la copia de
    trabajo no toca la entrada (RF-018-01)."""
    found: list[_Source] = []
    for order, source in enumerate(job.sources):
        assert source.level_m is not None
        index = round((source.level_m - job.anchor_m) / job.height_m)
        if abs(source.level_m - (job.anchor_m + index * job.height_m)) > _LATTICE_TOL_M:
            raise ValueError(f"la cota {source.level_m!r} del fondo «{source.name}» no es z₀ + j·h (z₀ = {job.anchor_m!r}, h = {job.height_m!r}): "
                             "los bancos son planos continuos (D-4) y la preparación lo rechaza antes")
        if index % n:
            raise ValueError(f"la cota {source.level_m!r} del fondo «{source.name}» no es z₀ + j·n·h con n = {n}: con bancos dobles los fondos "
                             "están en la retícula de n·h (RF-018-08) y la preparación lo rechaza antes")
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
                              name=job.request.name, start=job.request.start)
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


OFFSET_EDGES_PER_STEP = 400
"""Las aristas por bloque con que cede el desfase de una polilínea (T22b; RNF-018-06): el motor (``gis.offset``, 2.000 por defecto) tarda hasta ≈ 0,25 s por bloque con celdas de 1 m
y una corta con rampa; con 400 cada unidad queda muy por debajo de los 0,2 s. No es una cifra minera: solo reparte el trabajo (el resultado no cambia)."""


def _offset(job: PitJob, ring: _Ring, step: Step, origin: np.ndarray, *, side: int = 1, z_m: np.ndarray | None = None,
            anchor_m: float | None = None, extra_m: np.ndarray | None = None) -> Generator[None, None, PolylineOffset]:
    """Los pasos del desfase de ``ring`` (cada ``Progress`` del motor, una unidad) y el :class:`PolylineOffset`; ``side`` es ``+1`` hacia
    fuera (la ascendente) o ``-1`` hacia dentro (la descendente) y ``z_m`` con ``anchor_m``, el primer banco de altura variable."""
    steps = offset_polyline_steps(
        ring.points, step=step, side=side, tol=job.params.arc_tol_m, corner=str(job.params.corner), simplify_m=ring.slack_m,
        profile=job.profile, rose=job.rose, n_berm=_n_berm(job), sectors=job.sectors, origin=origin, az_window_m=job.params.az_window_m,
        z_m=z_m, anchor_m=anchor_m, extra_m=extra_m, edges_per_step=OFFSET_EDGES_PER_STEP)
    with closing(steps):
        for progress in steps:
            if progress.result is None:
                yield
                continue
            assert isinstance(progress.result, PolylineOffset)
            return progress.result
    raise AssertionError("el desfase no dio su resultado")


def _face_of(job: PitJob, origin: np.ndarray, side: int = 1) -> Callable[[np.ndarray], np.ndarray]:
    """El ángulo de cara (°) de cada arista de un pie (de una cresta en la descendente, ``side = -1``), con la roseta y los sectores de la corta (el de su primer trozo si un sector la parte)."""

    def face(ring: np.ndarray) -> np.ndarray:
        found = edge_distances(ring, step=Step.FACE, side=side, profile=job.profile, rose=job.rose, n_berm=_n_berm(job), sectors=job.sectors, origin=origin,
                               az_window_m=job.params.az_window_m)
        angle = np.empty(len(ring))
        angle[found.source_edge[::-1]] = found.face_deg[::-1]
        return angle

    return face


def _ascend_units(job: PitJob) -> Generator[None, None, Benches]:
    _check_supported(job)
    name, params = job.request.name, job.params
    n = _n_berm(job)
    height, anchor = job.height_m, job.anchor_m
    grid = job.grid
    origin = np.array([grid.west, grid.north - grid.nrows * grid.dy], dtype=np.float64)
    limit = MAX_BENCHES if params.max_benches is None else min(MAX_BENCHES, params.max_benches)
    pending = sorted(_prepared(job, origin, n), key=lambda item: (item.level_index, item.order))
    fixed = _resolve_fixed(job, origin, up=True, n=n)
    polylines: list[Polyline] = []
    notices: list[Notice] = []
    volumes: list[float] = []
    reliable = True
    active: list[_Ring] = []
    foot_holes: list[np.ndarray] = []
    level_index = min([pending[0].level_index, *(item.bench * n for item in fixed if item.bench is not None)])
    done = 0
    stop = StopCriterion.SURFACE
    crests_below: list[np.ndarray] = []
    ramps = RampLoop(job, origin, n)
    face_of = _face_of(job, origin)

    def line(kind: PolylineKind, bench: int, ring: np.ndarray, level: float, part: int, label: str,
             user: FixedBench | None = None) -> Polyline:
        if user is not None:
            return Polyline(kind, bench, user.vertices, sector=label, part=part, fixed=True)
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
        for mine in fixed:
            if mine.bench is not None and mine.bench * n == level_index:
                for crest in crests_below:
                    point = _crossing(mine.ring, crest)
                    if point is None:
                        point = _near(mine.ring, crest, _CLEAR_TOL_M)
                    if point is not None or _inside(mine.ring[0], crest):
                        raise _fixed_error(job, mine, mine.bench - 1, mine.ring[0] if point is None else point, origin)
                active = [ring for ring in active if not _touch(ring.points, mine.ring)]
                active.append(_Ring(mine.ring, "", params.simplify_m, mine.item))
                mine.used = True
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
            crests_below = []
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
        crest_rings: list[tuple[np.ndarray, str]] = []
        bench = level_index // n
        top = level + n * height
        plans = ramps.plan(bench, level, top - level, [ring.points for ring in active], face_of) if ramps.active else {}
        for position, ring in enumerate(active):
            plan = plans.get(position)
            offsetting = ring if plan is None else _Ring(plan.points, ring.label, ring.slack_m, ring.fixed)
            polylines.append(line(PolylineKind.FOOT, bench, offsetting.points, level, parts[PolylineKind.FOOT], ring.label, ring.fixed))
            parts[PolylineKind.FOOT] += 1
            face = yield from _offset(job, offsetting, Step.FACE, origin, extra_m=None if plan is None else plan.extra)
            if not face.result.verified:
                reliable = False
                notices.append(Notice(PitCode.OFFSET_UNRELIABLE.value, {"name": name, "bench": bench, "value": face.result.max_defect_m,
                                                                    "limit": params.arc_tol_m}))
            crests = [(crest, _label(face, i)) for i, crest in enumerate(face.result.rings)]
            crest_rings.extend(crests)
            for index, (crest, label) in enumerate(crests):
                polylines.append(line(PolylineKind.CREST, bench, crest, top, parts[PolylineKind.CREST], label))
                parts[PolylineKind.CREST] += 1
            for index, hole in enumerate(face.result.holes):
                polylines.append(line(PolylineKind.CREST, bench, hole, top, parts[PolylineKind.CREST],
                                      _label(face, len(crests) + index)))
                parts[PolylineKind.CREST] += 1
            if face.result.holes:
                notices.append(Notice(PitCode.HOLES.value, {"name": name, "bench": bench, "count": len(face.result.holes)}))
            loops = [*face.result.rings, *face.result.holes]
            volumes.append(face_volume_m3(_area(ring.points), _perimeter(ring.points), math.fsum(_area(loop) for loop in loops),
                                          math.fsum(_perimeter(loop) for loop in loops), n * height))
            for crest, label in crests:
                berm = yield from _offset(job, _Ring(crest, label, 0.0), Step.BERM, origin)
                if not berm.result.verified:
                    reliable = False
                    notices.append(Notice(PitCode.OFFSET_UNRELIABLE.value, {"name": name, "bench": bench + 1, "value": berm.result.max_defect_m,
                                                                        "limit": params.arc_tol_m}))
                carried.extend(_Ring(foot, _label(berm, i)) for i, foot in enumerate(berm.result.rings))
                foot_holes.extend(berm.result.holes)
        for hole in foot_holes:
            polylines.append(line(PolylineKind.FOOT, bench, hole, level, parts[PolylineKind.FOOT], ""))
            parts[PolylineKind.FOOT] += 1
        if foot_holes:
            notices.append(Notice(PitCode.HOLES.value, {"name": name, "bench": bench, "count": len(foot_holes)}))
        foot_holes = []
        crests_below = [item[0] for item in crest_rings]
        active = carried
        done += 1
        level_index += n
        yield

    _unused(job, fixed, origin)
    checked, ramp_notices = ramps.result()
    return Benches(tuple(polylines), stop, done, (*notices, *ramp_notices), reliable, math.fsum(volumes), ramps=checked)


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


@dataclass(slots=True, eq=False)
class _Crest:
    points: np.ndarray
    label: str
    z: np.ndarray
    slack_m: float = 0.0
    fixed: _Fixed | None = None


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
    """Si ``ring`` contiene un círculo de diámetro ``width_m`` (A6 i): su ancho útil (:func:`_useful_width`) lo supera. Antes era el desfase hacia dentro de ``width_m / 2``, que con un anillo de
    cientos de vértices que se colapsa tardaba minutos (T36); el ancho inscrito no usa el motor."""
    return _useful_width(job, ring) > width_m


def _useful_width(job: PitJob, ring: np.ndarray) -> float:
    """El ancho útil de ``ring`` (m): el diámetro del mayor círculo inscrito (:func:`~design.pit_report.inscribed_width`: una estimación por abajo, exacta en un anillo convexo, a ≤ 1 mm),
    sin el motor de desfase (T36: la bisección sobre él se colgaba minutos con un círculo de 720 vértices que se colapsa)."""
    return inscribed_width(simplify_ring(ring, job.params.arc_tol_m))  # el error de la simplificación es el del arco: el ancho sale a ≤ 2·arc_tol_m


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


def _descend_limit(job: PitJob, source: PitSource, origin: np.ndarray, notices: list[Notice], flags: dict[str, bool],
                   fixed: list[_Fixed], n: int, ramps: RampLoop, face_of: Callable[[np.ndarray], np.ndarray]) -> Generator[None, None, _Descent]:
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
        foot_z = first_foot_z - index * n * height
        if params.bottom_level_m is not None and foot_z < params.bottom_level_m - _EXIT_TOL_M:
            stop = StopCriterion.BOTTOM_LEVEL
            break
        used: list[_Crest] = []
        feet: list[tuple[np.ndarray, str]] = []
        holes: list[tuple[np.ndarray, str]] = []
        dead: list[np.ndarray] = []
        plans: dict[int, RampPlan] = {}
        if ramps.active and ramps.wants(index):
            if any(float(np.ptp(item.z)) > _EXIT_TOL_M for item in crests):
                raise ValueError(f"la cresta del banco {index} sigue el terreno (primer banco de altura variable): una rampa de la corta descendente no se calcula todavía sobre "
                                 "un banco de altura variable (T21c2b, DIFF-018f); empiece la rampa en el banco 1 o dé la cota de la cresta")
            plans = ramps.plan(index, foot_z, float(crests[0].z.mean()) - foot_z, [item.points for item in crests], face_of)
        for position, item in enumerate(crests):
            first = index == 0
            plan = plans.get(position)
            if plan is not None:  # la cresta con las aristas partidas en los extremos del tramo de la rampa (DIFF-018f)
                item = _Crest(plan.points, item.label, np.full(len(plan.points), float(item.z[0])), item.slack_m, item.fixed)
            face = yield from _offset(job, _Ring(item.points, item.label, item.slack_m), Step.FACE, origin, side=-1,
                                      z_m=item.z if first else None, anchor_m=first_foot_z if first else None, extra_m=None if plan is None else plan.extra)
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
            if item.fixed is not None and not mine:
                raise _fixed_error(job, item.fixed, index + 1, item.points.mean(axis=0), origin)
            if mine:
                used.append(item)
                feet.extend(mine)
                top = float(item.z.mean()) if first else foot_z + n * height
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
        for mine in fixed:
            carried = _use_fixed(job, mine, carried, feet, index, foot_z, origin)
        if not carried:
            break
        crests = carried
        index += 1
        yield
    return _Descent(benches, stop, math.fsum(volumes))


def _use_fixed(job: PitJob, mine: _Fixed, carried: list[_Crest], feet: list[tuple[np.ndarray, str]], index: int, foot_z: float,
               origin: np.ndarray) -> list[_Crest]:
    """Las crestas ``carried`` del banco ``index + 1`` (a ``foot_z``) con el banco fijado ``mine`` en lugar de las que solapa (RF-018-23); lo
    rechaza si corta un pie del banco ``index`` o cae fuera de ellos (RF-018-24). Si no es de este banco o de este límite, no cambia nada."""
    if mine.used:
        return carried
    level = mine.item.level_m
    if not (mine.bench == index + 1 or (mine.bench is None and level is not None and abs(level - foot_z) <= _LEVEL_TOL_M)):
        return carried
    hit = [crest for crest in carried if _touch(crest.points, mine.ring)]
    if not hit:
        return carried
    mine.bench = index + 1
    _check_level(job, mine, foot_z)
    for foot, _label_ in feet:
        point = _crossing(mine.ring, foot)
        if point is None:
            point = _near(mine.ring, foot, _CLEAR_TOL_M)
        if point is not None:
            raise _fixed_error(job, mine, index, point, origin)
    if not any(_inside(mine.ring[0], foot) for foot, _label_ in feet):
        raise _fixed_error(job, mine, index, mine.ring[0], origin)
    mine.used = True
    kept = [crest for crest in carried if crest not in hit]
    kept.append(_Crest(mine.ring, "", np.full(len(mine.ring), foot_z), job.params.simplify_m, mine))
    return kept


def _polyline(job: PitJob, origin: np.ndarray, kind: PolylineKind, bench: int, ring: np.ndarray, z: np.ndarray, part: int, label: str,
              user: _Fixed | None = None) -> Polyline:
    if user is not None:
        return Polyline(kind, bench, user.item.vertices, sector=label, part=part, fixed=True)
    if len(ring) > MAX_VERTICES:
        raise DesignError(PitCode.TOO_MANY_BENCHES.value, obj=job.request.name, field="vertices", value=len(ring), name=job.request.name,
                          limit=MAX_BENCHES, vertices=len(ring))
    return Polyline(kind, bench, np.column_stack([ring + origin, z]), sector=label, part=part)


def _by_position(items: list[tuple[np.ndarray, str, np.ndarray, _Fixed | None]]) -> list[tuple[np.ndarray, str, np.ndarray, _Fixed | None]]:
    return sorted(items, key=lambda item: (float(item[0][:, 0].min()), float(item[0][:, 1].min()), len(item[0])))


def _descend_units(job: PitJob) -> Generator[None, None, Benches]:
    _check_supported(job, PitMode.DOWN)
    n = _n_berm(job)
    params = job.params
    if params.min_floor_width_m is None and params.bottom_level_m is None and params.max_benches is None:
        raise ValueError("una corta descendente lleva al menos un criterio de parada: el ancho mínimo de fondo, la cota de fondo o el máximo de "
                         "bancos (RF-018-13, D-8); la preparación lo rechaza antes")
    grid = job.grid
    origin = np.array([grid.west, grid.north - grid.nrows * grid.dy], dtype=np.float64)
    notices: list[Notice] = []
    flags = {"reliable": True}
    descents: list[_Descent] = []
    fixed = _resolve_fixed(job, origin, up=False, n=n)
    ramps = RampLoop(job, origin, n, down=True)
    if ramps.active and len(job.sources) > 1:
        raise ValueError("las rampas de la corta descendente con varios límites no se calculan todavía (T21c2b, DIFF-018f): una rampa baja por un solo límite")
    face_of = _face_of(job, origin, -1)
    for source in job.sources:
        descents.append((yield from _descend_limit(job, source, origin, notices, flags, fixed, n, ramps, face_of)))
    _unused(job, fixed, origin)
    checked, ramp_notices = ramps.result()
    notices.extend(ramp_notices)
    polylines: list[Polyline] = []
    for index in range(max(len(item.benches) for item in descents)):
        here = [item.benches[index] for item in descents if index < len(item.benches)]
        crests = _by_position([(c.points, c.label, c.z, c.fixed) for bench in here for c in bench.crests])
        feet = _by_position([(r, label, np.full(len(r), bench.foot_z), None) for bench in here for r, label in bench.feet])
        feet += _by_position([(r, label, np.full(len(r), bench.foot_z), None) for bench in here for r, label in bench.holes])
        for part, (ring, label, z, user) in enumerate(crests):
            polylines.append(_polyline(job, origin, PolylineKind.CREST, index, ring, z, part, label, user))
        for part, (ring, label, z, user) in enumerate(feet):
            polylines.append(_polyline(job, origin, PolylineKind.FOOT, index, ring, z, part, label, user))
    deepest = min(item.benches[-1].foot_z for item in descents)
    chosen = [item for item in descents if item.benches[-1].foot_z == deepest]
    floors = [ring for item in chosen for ring, _label_ in item.benches[-1].feet]
    return Benches(
        tuple(polylines), chosen[0].stop, max(len(item.benches) for item in descents), tuple(notices), flags["reliable"],
        math.fsum(item.volume_m3 for item in descents), deepest, math.fsum(_area(ring) for ring in floors),
        max(_useful_width(job, ring) for ring in floors), ramps=checked)


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


# --- «Expandir banco…»: un solo paso (A7) --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Expansion:
    """El resultado de **un** paso sobre una polilínea (RF-018-22): las ``polylines`` siguientes (de tipo ``kind``, a ``level_m``), los ``notices``,
    si el desfase se verificó (``reliable``) y la comprobación: en un paso de cara, la inclinación real (``slope_deg``, la mayor de los vértices
    nuevos, con ``slope_limit_deg``, el ángulo de cara α de ese vértice, y ``slope_ok``); en un paso de berma, la berma real
    (``berm_min_m``, la menor, con ``berm_limit_m``, la B mínima pedida, y ``berm_ok``). Lo que no es del paso queda en ``None``."""

    polylines: tuple[Polyline, ...]
    kind: PolylineKind
    level_m: float
    notices: tuple[Notice, ...]
    reliable: bool
    slope_deg: float | None = None
    slope_limit_deg: float | None = None
    slope_ok: bool = True
    berm_min_m: float | None = None
    berm_limit_m: float | None = None
    berm_ok: bool = True


_CHECK_TOL = 1e-6
_CHUNK = 256


def _distances(points: np.ndarray, ring: np.ndarray) -> Generator[None, None, np.ndarray]:
    """La distancia (m) de cada punto de ``points`` al contorno de ``ring`` (por fuerza bruta en bloques; cede entre bloques)."""
    start, span = ring, np.roll(ring, -1, axis=0) - ring
    length2 = np.maximum((span ** 2).sum(axis=1), 1e-300)
    found = np.empty(len(points))
    for first in range(0, len(points), _CHUNK):
        block = points[first:first + _CHUNK, None, :]
        t = np.clip(((block - start[None]) * span[None]).sum(axis=2) / length2[None], 0.0, 1.0)
        found[first:first + _CHUNK] = np.hypot(*(block - (start[None] + t[..., None] * span[None])).transpose(2, 0, 1)).min(axis=1)
        yield
    return found


def _expand_units(job: PitJob, polyline: Polyline, direction: PitMode | str) -> Generator[None, None, Expansion]:
    mode = PitMode(direction)
    _check_supported(job, mode)
    if not polyline.closed:
        raise ValueError("«Expandir banco» parte de un anillo: una polilínea abierta no es un banco")
    kind = PolylineKind(polyline.kind)
    z = polyline.vertices[:, 2]
    if float(np.ptp(z)) > _LEVEL_TOL_M:
        raise ValueError("una polilínea de banco es plana: «Expandir banco» no admite una con Z variable")
    n, params, height = _n_berm(job), job.params, job.height_m
    grid = job.grid
    origin = np.array([grid.west, grid.north - grid.nrows * grid.dy], dtype=np.float64)
    ring = _ccw(np.asarray(polyline.vertices[:, :2], dtype=np.float64) - origin)
    up = mode is PitMode.UP
    face_step = (kind is PolylineKind.FOOT) == up
    step = Step.FACE if face_step else Step.BERM
    level = float(z[0]) + (n * height if up else -n * height) * face_step
    result_kind = (PolylineKind.CREST if kind is PolylineKind.FOOT else PolylineKind.FOOT)
    bench = polyline.bench + (0 if face_step else 1)
    offset = yield from _offset(job, _Ring(ring, polyline.sector, params.simplify_m), step, origin, side=1 if up else -1)
    notices: list[Notice] = []
    if not offset.result.verified:
        notices.append(Notice(PitCode.OFFSET_UNRELIABLE.value, {"name": job.request.name, "bench": bench, "value": offset.result.max_defect_m,
                                                                "limit": params.arc_tol_m}))
    loops = [*offset.result.rings, *offset.result.holes]
    lines: list[Polyline] = []
    for index, loop in enumerate(loops):
        if len(loop) > MAX_VERTICES:
            raise DesignError(PitCode.TOO_MANY_BENCHES.value, obj=job.request.name, field="vertices", value=len(loop), name=job.request.name,
                              limit=MAX_BENCHES, vertices=len(loop))
        lines.append(Polyline(result_kind, bench, np.column_stack([loop + origin, np.full(len(loop), level)]), sector=_label(offset, index),
                              part=index))
    if offset.result.holes:
        notices.append(Notice(PitCode.HOLES.value, {"name": job.request.name, "bench": bench, "count": len(offset.result.holes)}))
    slope: tuple[float, float, bool] | None = None
    berm: tuple[float, float, bool] | None = None
    if loops:
        found = yield from _distances(np.vstack(loops), ring)
        edge = np.maximum(np.concatenate([np.asarray(item) for item in offset.result.source_edge_of_vertex]), 0)
        if face_step:
            angle = np.degrees(np.arctan2(n * height, np.maximum(found, 1e-300)))
            limit = offset.edges.face_deg[edge]
            worst = int(np.argmax(angle))
            slope = (float(angle[worst]), float(limit[worst]), bool(np.all(angle <= limit + _CHECK_TOL)))
        else:
            wanted = offset.edges.berm_m[edge]
            berm = (float(found.min()), float(wanted.min()), bool(np.all(found >= wanted - _LEVEL_TOL_M)))
    return Expansion(tuple(lines), result_kind, level, tuple(notices), offset.result.verified,
                     *(slope if slope else (None, None, True)), *(berm if berm else (None, None, True)))


def expand_one_steps(job: PitJob, polyline: Polyline, direction: PitMode | str, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A7** (RF-018-22): **un** paso de A5 (``direction`` ``up``) o A6 (``down``) sobre la ``polyline`` dada (un pie o una cresta cerrados y
    planos), por pasos de ``budget_s`` como mucho, sin escribir nada: de un pie, hacia arriba, su cresta (``n·h/tan α``, a ``n·h`` más) y, hacia
    abajo, la cresta del banco siguiente (la berma ``B``); de una cresta, hacia arriba, el pie del banco siguiente (la berma) y, hacia abajo, su
    pie (la cara). Es el mismo desfase del bucle con las mismas piezas: da la misma polilínea. El último ``Progress`` lleva la
    :class:`Expansion`, con su comprobación de inclinación y berma. El perfil, la roseta y los sectores son los de ``job``."""
    return pace_progress(_expand_units(job, polyline, direction), budget_s, phase=_PHASE, running="Calculando el banco…",
                         finished="Banco calculado")


def expand_one(job: PitJob, polyline: Polyline, direction: PitMode | str) -> Expansion:
    """:func:`expand_one_steps` hasta el final, sin pasos."""
    work = _expand_units(job, polyline, direction)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: Expansion = done.value
            return result
