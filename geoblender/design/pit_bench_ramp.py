# SPDX-License-Identifier: GPL-3.0-or-later
"""El bucle de la rampa dentro de los bancos de la corta (spec 018, T21c; HU-018-3; RF-018-15 a 21 y 25; CE-018-05 y 06; plan 018 §5.4 A8 y A9).

:mod:`design.pit_bench` pide a :class:`RampLoop`, banco a banco y **antes de desfasar la cara**, el plan de cada pie (:meth:`RampLoop.plan`): el tramo de cada rampa que sube por
ese pie (la espiral con :func:`design.pit_ramp.build_tramo`, el zig-zag con :class:`design.pit_ramp.ZigzagStepper`; no se reescribe nada de :mod:`design.pit_ramp`), el pie con
**las aristas partidas en los extremos del tramo** (:func:`design.pit_ramp.split_ring`: el término de la cresta se evalúa en el punto medio de cada arista y no puede cruzar un
cambio de forma) y el **término de la distancia por arista** (:func:`design.pit_ramp.edge_extra_m` o :func:`~design.pit_ramp.zigzag_edge_extra_m`) que el desfase suma a la cara. El
pie siguiente sale de la cresta con ese término, y la rampa continúa en él desde el fin del tramo (pie → rampa → cresta con el término → pie siguiente). Al acabar los bancos,
:meth:`RampLoop.result` arma la espiral o el zig-zag, lo pasa por las reglas de la 017 (:func:`design.pit_ramp.check_ramp`: curvas, pendiente, zonas sin rampa e intocables) y da las
rampas comprobadas y sus avisos.

Decisiones por defecto (revisables, T21c): (a) una rampa con inicio ``banco N`` parte del vértice **más al norte** del pie de mayor área de ese banco (el primero por el oeste en un
empate: P-15), y una con inicio ``fondo`` o de una capa de puntos parte del primer banco con pie (el ``fondo`` es el banco 0; en una corta con fondos a cotas distintas, el más bajo
que hay), desde el punto de la capa; (b) con varios pies en el banco, la rampa sube por el más cercano a su punto (a igual distancia, el primero por su posición); (c) dos rampas no
comparten una arista del pie (se rechaza); (d) la preparación (T21b) ya comprobó el perfil de pista y la pendiente; (e) con una roseta o sectores, el ángulo de cara de una arista es el
de su primer trozo si un límite de sector la parte. Los bancos dobles (``n > 1``) no llevan rampa todavía. Python puro con numpy (nivel 8); no lo importa el arranque.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from .messages import DesignError
from .params import PitRampParam, pitramp_key
from .pit_model import PitJob, RampDef, RampStart
from .pit_ramp import (RampChecked, RampDoesNotFit, Spiral, Tramo, Zigzag, ZigzagStepper, build_tramo, check_ramp, edge_extra_m, foot_breaks, nearest_on_ring,
                       no_fit_error, spiral_of, split_ring, zigzag_edge_extra_m, zigzag_foot_breaks)
from .preview import Notice
from .road_profiles import derived as road_derived

__all__ = ["RampLoop", "RingPlan"]

_TIE_M = 1e-9


@dataclass(frozen=True, slots=True, eq=False)
class RingPlan:
    """Lo que la rampa hace a un pie: ``points`` (el pie con las aristas partidas en los extremos de cada tramo: el mismo anillo, con más vértices) y ``extra`` (``(n,)``, el término
    de la cresta por arista de ``points``)."""

    points: np.ndarray
    extra: np.ndarray


@dataclass(slots=True, eq=False)
class _Run:
    """El estado de una rampa mientras sube: su definición, su inicio, el ancho de su sección, el punto por donde sigue (locales; ``None`` hasta que parte) y sus tramos."""

    ramp: RampDef
    start: RampStart
    width_m: float
    point: np.ndarray | None = None
    tramos: list[Tramo] = field(default_factory=list)
    stepper: ZigzagStepper | None = None


def _north(rings: Sequence[np.ndarray]) -> np.ndarray:
    """El vértice más al norte del pie de mayor área (el primero por el oeste en un empate: P-15)."""

    def area(ring: np.ndarray) -> float:
        following = np.roll(ring, -1, axis=0)
        return 0.5 * float((ring[:, 0] * following[:, 1] - following[:, 0] * ring[:, 1]).sum())

    biggest = max(range(len(rings)), key=lambda index: (area(rings[index]), -index))
    ring = rings[biggest]
    top = np.flatnonzero(ring[:, 1] >= float(ring[:, 1].max()) - _TIE_M)
    return ring[top[np.argmin(ring[top, 0])]]


def _place(point: np.ndarray, origin: np.ndarray) -> str:
    return f"{point[0] + origin[0]:.1f}, {point[1] + origin[1]:.1f}"


class RampLoop:
    """Las rampas de una corta mientras se calculan sus bancos: :meth:`plan` por banco y :meth:`result` al acabar. ``origin`` es la esquina suroeste de la rejilla (el marco local de los
    bancos); sin rampas, :attr:`active` es falso y no hace nada."""

    def __init__(self, job: PitJob, origin: np.ndarray, n_berm: int = 1) -> None:
        self.job = job
        self.arc_tol_m = job.params.arc_tol_m
        self.origin = np.asarray(origin, dtype=np.float64)
        self.runs: list[_Run] = []
        if not job.ramps:
            return
        if n_berm > 1:
            raise ValueError("las rampas de una corta con bancos dobles (n > 1) no se calculan todavía (RF-018-08, T21c)")
        starts = {item.ramp: item for item in job.ramp_starts}
        profiles = {item.code: item for item in job.road_profiles}
        for ramp in job.ramps:
            if ramp.code not in starts:
                raise ValueError(f"la rampa «{ramp.code}» no trae su punto de inicio resuelto: la preparación (T21b) lo da")
            profile = profiles.get(ramp.road_profile)
            if profile is None:
                raise ValueError(f"la rampa «{ramp.code}» cita el perfil de pista «{ramp.road_profile}», que la corta no lleva")
            width = road_derived(profile).section_m
            run = _Run(ramp, starts[ramp.code], width)
            if ramp.type == "zigzag":
                run.stepper = ZigzagStepper(ramp, width)
            self.runs.append(run)

    @property
    def active(self) -> bool:
        return bool(self.runs)

    def _wanted(self, run: _Run, bench: int) -> bool:
        """Si la rampa sube por el banco ``bench``: ya parte (continúa) o este es el banco de su inicio (o el primero que hay, desde ``fondo`` o una capa)."""
        if run.tramos:
            return True
        wanted = run.start.bench
        return wanted is None or wanted == 0 or bench >= wanted

    def _start_point(self, run: _Run, rings: Sequence[np.ndarray]) -> np.ndarray:
        if run.start.point is not None:
            return np.asarray(run.start.point, dtype=np.float64) - self.origin
        return _north(rings)

    def plan(self, bench: int, level_m: float, rise_m: float, rings: Sequence[np.ndarray], face_of: Callable[[np.ndarray], np.ndarray]
             ) -> dict[int, RingPlan]:
        """El plan de los pies ``rings`` (antihorarios y abiertos, locales; ``level_m`` su cota, ``rise_m`` lo que sube el banco ``bench``) por el índice del pie: solo los que llevan
        rampa. ``face_of(anillo)`` da el ángulo de cara (°) de cada arista de un pie. :class:`~design.messages.DesignError` ``des.pit_no_ramp_fit`` si un tramo no cabe (RF-018-20)."""
        mine: dict[int, list[tuple[_Run, Tramo]]] = {}
        for run in self.runs:
            if not self._wanted(run, bench):
                continue
            point = self._start_point(run, rings) if run.point is None else run.point
            best = min(range(len(rings)), key=lambda index: (nearest_on_ring(rings[index], point)[3], index))
            for index in range(len(rings)):  # el primero de los empatados, por su posición (los pies llegan ordenados)
                if nearest_on_ring(rings[index], point)[3] <= nearest_on_ring(rings[best], point)[3] + _TIE_M:
                    best = index
                    break
            try:
                if run.stepper is not None:
                    tramo = run.stepper.tramo(rings[best], point, bench=bench, z_foot_m=level_m, rise_m=rise_m)
                else:
                    tramo = build_tramo(rings[best], point, bench=bench, z_foot_m=level_m, rise_m=rise_m, gradient_pct=run.ramp.gradient_pct, width_m=run.width_m,
                                        transition_m=run.ramp.transition_m, sense=run.ramp.sense)
            except RampDoesNotFit as error:
                if error.place is not None:
                    error.place = (error.place[0] + float(self.origin[0]), error.place[1] + float(self.origin[1]))
                raise no_fit_error(error, run.ramp) from None
            run.point = tramo.end_xy
            run.tramos.append(tramo)
            mine.setdefault(best, []).append((run, tramo))
        found: dict[int, RingPlan] = {}
        for index, items in mine.items():
            ring = rings[index]
            breaks = [zigzag_foot_breaks(tramo) if run.stepper is not None else foot_breaks(tramo, ring) for run, tramo in items]
            split = split_ring(ring, np.vstack(breaks))
            face = face_of(split)
            extras = [zigzag_edge_extra_m(tramo, split, face) if run.stepper is not None else edge_extra_m(tramo, split, face) for run, tramo in items]
            dense = self._dense(split, extras, face, items)
            if len(dense) != len(split):
                split = dense
                face = face_of(split)
                extras = [zigzag_edge_extra_m(tramo, split, face) if run.stepper is not None else edge_extra_m(tramo, split, face) for run, tramo in items]
            total = np.zeros(len(split))
            taken = np.zeros(len(split), dtype=bool)
            for (run, tramo), extra in zip(items, extras, strict=True):
                used = extra != 0.0
                if bool((used & taken).any()):
                    where = int(np.argmax(used & taken))
                    raise DesignError("des.pit_no_ramp_fit", obj=f"Rampa «{run.ramp.name}»", field=pitramp_key(run.ramp.code, PitRampParam.TYPE), value=run.ramp.type,
                                      profile=run.ramp.name, bench=bench, needed=round(tramo.length_m, 3), available=0.0, reason="otra rampa en el mismo tramo del pie",
                                      place=_place(split[where], self.origin))
                taken |= used
                total += extra
            found[index] = RingPlan(split, total)
        return found

    def _dense(self, ring: np.ndarray, extras: Sequence[np.ndarray], face: np.ndarray, items: Sequence[tuple[_Run, Tramo]]) -> np.ndarray:
        """El pie con las aristas que llevan término partidas en trozos de ≤ ``2·tol/pendiente`` m (entre 0,5 y 5 m): el desfase da **una distancia por arista**, y la cresta sigue la
        pared (que baja ``g/tan α`` por metro de rampa) con un error de arco ≤ ``tol`` solo si el trozo es corto."""
        used = np.zeros(len(ring), dtype=bool)
        for extra in extras:
            used |= extra != 0.0
        if not bool(used.any()):
            return ring
        slope = max(tramo.gradient for _run, tramo in items) / float(np.tan(np.radians(face[used].min())))
        step = min(5.0, max(0.5, 2.0 * self.arc_tol_m / slope)) if slope > 0.0 else 5.0
        following = np.roll(ring, -1, axis=0)
        length = np.hypot(*(following - ring).T)
        rows: list[np.ndarray] = []
        for index in range(len(ring)):
            rows.append(ring[index][None, :])
            if used[index] and length[index] > step:
                pieces = int(np.ceil(length[index] / step))
                fractions = np.arange(1, pieces) / pieces
                rows.append(ring[index] + fractions[:, None] * (following[index] - ring[index]))
        return np.vstack(rows)

    def result(self, origin_abs: Sequence[float] | None = None) -> tuple[tuple[RampChecked, ...], tuple[Notice, ...]]:
        """Las rampas armadas y comprobadas con las reglas de la 017 (:func:`design.pit_ramp.check_ramp`) y sus avisos, en el orden de las definiciones. ``DesignError`` si una no
        cabe, cruza una zona sin rampa o un intocable o su radio no alcanza el mínimo (RF-018-20), o si el banco de su inicio (``banco N``) no se alcanza."""
        frame = self.origin if origin_abs is None else np.asarray(origin_abs, dtype=np.float64)
        checked: list[RampChecked] = []
        notices: list[Notice] = []
        for run in self.runs:
            if not run.tramos:
                raise DesignError("des.pit_start_invalid", obj=f"Rampa «{run.ramp.name}»", field=pitramp_key(run.ramp.code, PitRampParam.START), value=run.ramp.start,
                                  layer=self.job.request.layer, entity=self.job.request.name, ramp=run.ramp.name,
                                  reason=f"el banco {run.start.bench} no se alcanza en la corta")
            found: Spiral | Zigzag
            if run.stepper is not None:
                found = run.stepper.result(frame)
            else:
                found = spiral_of(run.tramos, frame, run.width_m, run.ramp)
            one = check_ramp(found, self.job, run.ramp)
            checked.append(one)
            notices.extend(one.notices)
        return tuple(checked), tuple(notices)

