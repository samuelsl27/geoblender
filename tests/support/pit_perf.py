# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de la corta por bancos (spec 018, T36; plan 018 §7.3; ``tests/rendimiento/des/test_pit_perf.py``).

Solo sintéticos, se generan al pedirlos y no se versionan datos de clientes. Son los guiones de medida de ``plan.md`` §7.3 (que vivían en el *scratchpad*
de la sesión del plan) convertidos en funciones:

- :func:`ascending_job`: la corta **ascendente de 40 bancos** sobre la rejilla de 2,81 M celdas (1.654 × 1.699 de 1 m, la de la 013) con un fondo rugoso de
  2.000 vértices (≈ 160.000 desfasados con los 80 de pie y cresta), terreno llano que la corta alcanza al banco 40.
- :func:`scale_polylines` y :func:`scale_job`: **60 bancos con 160.000 vértices** (``pit_data.scale_rings``) como polilíneas ya hechas, para medir la superficie, los
  hallazgos y las cifras sin pasar por el desfase.
- :func:`spiral_ascending_job` y :func:`zigzag_ascending_job`: la misma corta con una rampa (RNF-018-02).

Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np

from tests.support import pit_data as pd
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_model = import_geoblender("design.pit_model")
ramp_def = import_geoblender("design.pit_ramp_def")

BENCHES = 40
"""Los bancos de la corta de RNF-018-01 y 02."""
FLOOR_VERTICES = 2_000
"""Los vértices del fondo de RNF-018-01 (la spec: polilíneas de 2.000 vértices)."""
FLOOR_RADIUS_M = 150.0
FLOOR_NOISE_M = 0.15
SPIRAL_RADIUS_M = 300.0
"""El fondo circular de la espiral (m): con el de 150 m el radio que cabe en los primeros bancos es menor que el mínimo del perfil de pista."""
SEED = 7
ARC_M = 0.05
SIMPLIFY_M = 0.05
"""HIPÓTESIS de prueba (D-14, P-5): las de ``pit_data.HYPOTHESES`` (arco y simplificación de 5 cm)."""
RAMP_ARC_M = pd.HYPOTHESES.arc_m
STEP_BUDGET_S = 0.05
"""El presupuesto con que la interfaz lleva los pasos (``STEP_BUDGET_S`` de ``gis.masks.compile``)."""


def center() -> tuple[float, float]:
    """El centro de la rejilla de escala (m, locales)."""
    grid = pd.scale_grid()
    return grid.ncols * grid.dx / 2.0, grid.nrows * grid.dy / 2.0


def job_of(grid: Any, top_m: float, **changes: Any) -> Any:
    """Un ``PitJob`` ascendente sobre ``grid`` con terreno llano a ``top_m``, todo cortable y sin intocables."""
    values: dict[str, Any] = {
        "start": np.full(grid.shape, top_m), "cut_allowed": np.ones(grid.shape, bool), "fill_allowed": np.zeros(grid.shape, bool),
        "untouchable": np.zeros(grid.shape, bool),
        "params": pit_model.PitParams(arc_tol_m=ARC_M, simplify_m=SIMPLIFY_M)}
    values.update(changes)
    return h1.up_job(grid, **values)


def ascending_job(benches: int = BENCHES, vertices: int = FLOOR_VERTICES, noise_m: float = FLOOR_NOISE_M, **changes: Any) -> Any:
    """La corta ascendente de ``benches`` bancos desde un fondo rugoso de ``vertices`` vértices en la rejilla de escala."""
    grid = pd.scale_grid()
    ring = pd.rough_ring(SEED, vertices, noise_m, FLOOR_RADIUS_M, center())
    source = pit_model.PitSource("fondo", pd.absolute(ring, grid), pd.FLOOR_Z_M)
    changes.setdefault("sources", (source,))
    return job_of(grid, pd.FLOOR_Z_M + benches * 10.0 - 5.0, **changes)


def spiral_ascending_job(benches: int = BENCHES, **changes: Any) -> Any:
    """:func:`ascending_job` con la espiral de CE-018-05 (8 %) desde el banco 0 (RNF-018-02)."""
    profile = rd.road_profile(dataclasses.replace(rd.PROFILE, min_radius_m=7.0))
    ramp = ramp_def.PitRampDef("rampa", "Rampa 1", "spiral", "ccw", "banco 0", pd.SPIRAL_GRADE_PCT, profile.code, 0.0)
    grid = pd.scale_grid()
    floor = pit_model.PitSource("fondo", pd.absolute(pd.circle_ring(SPIRAL_RADIUS_M, FLOOR_VERTICES, center()), grid), pd.FLOOR_Z_M)
    values: dict[str, Any] = {"ramps": (ramp,), "road_profiles": (profile,), "ramp_starts": (pit_model.RampStart("rampa", bench=0),), "sources": (floor,),
                              "params": pit_model.PitParams(arc_tol_m=RAMP_ARC_M, simplify_m=1e-6)}
    values.update(changes)
    return ascending_job(benches, **values)


def zigzag_ascending_job(benches: int = BENCHES, **changes: Any) -> Any:
    """La corta ascendente de ``benches`` bancos desde un fondo rectangular de 200 × 60 m con el zig-zag de CE-018-06 (10 %) desde el banco 0 (RNF-018-02)."""
    grid = pd.scale_grid()
    profile = rd.road_profile(dataclasses.replace(rd.PROFILE, min_radius_m=8.0))
    ramp = ramp_def.PitRampDef("rampa", "Rampa 1", "zigzag", "ccw", "banco 0", pd.ZIGZAG_GRADE_PCT, profile.code, 0.0, 12.0, 40.0)
    ring = pd.rect_ring(pd.ZIGZAG_LENGTH_M, pd.ZIGZAG_WIDTH_M, center())
    source = pit_model.PitSource("fondo", pd.absolute(ring, grid), pd.FLOOR_Z_M)
    values: dict[str, Any] = {"ramps": (ramp,), "road_profiles": (profile,), "ramp_starts": (pit_model.RampStart("rampa", bench=0),),
                              "params": pit_model.PitParams(arc_tol_m=RAMP_ARC_M, simplify_m=1e-6)}
    values.update(changes)
    values.setdefault("sources", (source,))
    return job_of(grid, pd.FLOOR_Z_M + benches * 10.0 - 5.0, **values)


def scale_polylines(benches: int = 60, total_vertices: int = pd.SCALE_VERTICES) -> tuple[Any, ...]:
    """Las ``2·benches`` polilíneas (pie y cresta de cada banco) de ``pit_data.scale_rings`` con su Z, en absolutas: ≈ ``total_vertices`` vértices."""
    grid = pd.scale_grid()
    rings = pd.scale_rings(benches, total_vertices)
    made = []
    for bench in range(benches):
        for offset, kind in enumerate(("foot", "crest")):
            xy = pd.absolute(rings[2 * bench + offset], grid)
            z = np.full(len(xy), pd.FLOOR_Z_M + (bench + offset) * 10.0)
            made.append(pit_model.Polyline(kind, bench, np.column_stack([xy, z])))
    return tuple(made)


def scale_job(benches: int = 60) -> Any:
    """El ``PitJob`` de las polilíneas de :func:`scale_polylines` (terreno llano 5 m por encima de la última cresta)."""
    grid = pd.scale_grid()
    source = pit_model.PitSource("fondo", pd.absolute(pd.circle_ring(100.0, 720, center()), grid), pd.FLOOR_Z_M)
    return job_of(grid, pd.FLOOR_Z_M + benches * 10.0 + 5.0, sources=(source,))


@dataclasses.dataclass(frozen=True, slots=True)
class Driven:
    """Unos pasos llevados hasta el final: el último resultado, el tiempo de pared (s) y las llamadas (``count``; la más larga en pared y en CPU del proceso)."""

    result: Any
    wall_s: float
    count: int
    longest_s: float
    longest_cpu_s: float


def drive(work: Iterator[Any]) -> Driven:
    """Lleva ``work`` (pasos ``Progress``) como el temporizador del modal: cada ``next`` medido en pared y en CPU del proceso."""
    result, count, longest, longest_cpu = None, 0, 0.0, 0.0
    began = time.perf_counter()
    iterator = iter(work)
    while True:
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            step = next(iterator)
        except StopIteration as done:
            if done.value is not None:  # un generador de unidades (sin ``Progress``): lo que devuelve
                result = done.value
            break
        longest = max(longest, time.perf_counter() - wall)
        longest_cpu = max(longest_cpu, time.process_time() - cpu)
        count += 1
        if getattr(step, "result", None) is not None:
            result = step.result
    return Driven(result, time.perf_counter() - began, count, longest, longest_cpu)


def timed[T](action: Callable[[], T]) -> tuple[T, float]:
    """``action()`` y lo que tardó (s de pared)."""
    began = time.perf_counter()
    found = action()
    return found, time.perf_counter() - began
