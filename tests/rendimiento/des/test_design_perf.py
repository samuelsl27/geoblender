# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de las envolventes y del escalonado (spec 013, T30; RNF-013-01 a RNF-013-04 y
RNF-013-06; plan 013 §2.2, §7.3 y §7.4, ``tests/rendimiento/des``).

Se ejecuta con ``tools/check.py --rendimiento``, nunca en el «verde»: el Python de Blender (su numpy
2.3.4), en el PC de referencia de la spec 001 §5 y en disco local (``%TEMP%``). Cada cifra se
imprime en una línea ``RNF-013-nn: …`` con el equipo y el intérprete (``tools/check.py`` las
recoge) y se compara con su presupuesto, sin relajarlo (mediana de 5, spec 013 §5).

**Datos** (plan §2.2; se generan en ``tests/support/design_perf.py`` y no se versionan): la
rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M) con un terreno ondulado de 145 a 215 m y ruido de
5 cm, semillas en un anillo de radio 600 m (5.3 mil celdas), en un anillo más grueso (10 mil, el
tope de RNF-013-01) y en un disco rugoso de 160 mil, 20 sectores en franjas y 10 perfiles de
banco con dos taludes impuestos (10,6° y 18°).

- RNF-013-01 (:class:`EnvelopeTest`): la envolvente *chamfer* 5×5 de pendiente constante ≤ 3 s; la
  euclídea exacta ≤ 6 s con semillas de contorno de hasta 10.000 celdas y ≤ 30 s con una zona
  maciza de 160.000 semillas (D-22); el hueco entre dos avances ≤ 1 s y Esc (con el avance a la
  mitad: la llamada más larga más cerrar los pasos) ≤ 2 s.
- RNF-013-02 (:class:`SectorsTest`): el *chamfer* con la pendiente de 20 sectores, hasta converger,
  ≤ 10 s.
- RNF-013-03 (:class:`DesignTest`): el cálculo completo (envolvente por sectores, regularización,
  escalonado en corte, recorte final, composición e informe) de «Calcular» a «Crear» de las dos
  órdenes, en un proyecto en disco local, ≤ 12 s. En ``Z:`` se mide con las órdenes reales (T31).
- RNF-013-04 (:class:`SectorsTest`, :class:`DesignTest`, :class:`EnvelopeTest`): el pico de memoria
  adicional (``tracemalloc``, con la de numpy; aparte de las de tiempo: multiplica por 1,6 la
  búsqueda exacta) ≤ 1 GB.
- RNF-013-06 (:class:`PreviewTest`): el resumen de la preparación (semillas, dominio y sectores)
  sobre las 2,81 M celdas ≤ 1 s.

Lo que hace Geoblender en cada llamada del hilo de Blender con las órdenes reales (RNF-013-05 y
RNF-013-07) se mide dentro de Blender (T31, ``perf_design.py``); aquí se anota la llamada más larga
de cada cálculo, sin presupuesto propio.
"""

from __future__ import annotations

import gc
import statistics
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np

from tests.support import design_perf as dperf
from tests.support import gis_perf
from tests.support import versions_perf as vperf
from tests.support.package import import_geoblender

envelopes = import_geoblender("design.envelopes")
steps = import_geoblender("design.steps")

CHAMFER_BUDGET_S = 3.0  # RNF-013-01
CONTOUR_BUDGET_S = 6.0  # RNF-013-01: la exacta con semillas de contorno
SOLID_BUDGET_S = 30.0  # RNF-013-01: la exacta con una zona maciza (D-22)
SECTORS_BUDGET_S = 10.0  # RNF-013-02
DESIGN_BUDGET_S = 12.0  # RNF-013-03, en disco local
PREVIEW_BUDGET_S = 1.0  # RNF-013-06
MEMORY_BUDGET_BYTES = 1024**3  # RNF-013-04: 1 GB
PROGRESS_GAP_S = 1.0  # RNF-013-01: avance cada ≤ 1 s
CANCEL_BUDGET_S = 2.0  # RNF-013-01: cancelación efectiva en ≤ 2 s
CANCEL_AT = 0.5  # Esc con el avance a la mitad
STEP_BUDGET_S = 0.05  # el ritmo con que las órdenes agrupan sus unidades en pasos
RUNS = 5  # spec 013 §5: mediana de 5
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count
GEOMETRY = dperf.grid()
DOWN = "down"


def repeat(start: Callable[[], Iterator[Any]]) -> list[vperf.Driven]:
    """:data:`RUNS` ejecuciones seguidas de los pasos que da ``start`` (con la basura recogida
    antes de cada una), llevados como el temporizador del modal."""
    found = []
    for _ in range(RUNS):
        gc.collect()
        found.append(vperf.drive(start))
    return found


def totals(found: list[vperf.Driven]) -> list[float]:
    return [driven.total_s for driven in found]


def longest(found: list[vperf.Driven]) -> tuple[float, float, str]:
    """La llamada más larga de las ejecuciones (mediana de las de cada una, la peor de todas y la
    fase de la peor), en segundos."""
    per_run = [driven.longest_s for driven in found]
    worst = max(found, key=lambda driven: driven.longest_s)
    return statistics.median(per_run), worst.longest_s, worst.longest_phase


def gaps(found: list[vperf.Driven]) -> tuple[float, float]:
    """El hueco entre dos avances (mediana de las ejecuciones y el peor de todos), en segundos."""
    values = [driven.gap_s for driven in found]
    return statistics.median(values), max(values)


def calls_text(found: list[vperf.Driven]) -> str:
    median, worst, phase = longest(found)
    return (f"{found[-1].steps} llamadas, la más larga {number(median * 1000, 0)} ms (la peor, "
            f"{number(worst * 1000, 0)} ms en «{phase}»)")


def chamfer(seed: np.ndarray, slope: Any, name: str) -> Callable[[], Iterator[Any]]:
    return lambda: envelopes.chamfer_steps(seed, GEOMETRY, slope, DOWN, name=name,
                                           budget_s=STEP_BUDGET_S)


def exact(seed: np.ndarray, name: str) -> Callable[[], Iterator[Any]]:
    slope = envelopes.constant_slope(dperf.GENERAL_DEG)
    return lambda: envelopes.exact_steps(seed, GEOMETRY, slope, DOWN, name=name,
                                         budget_s=STEP_BUDGET_S)


def drain(start: Callable[[], Iterator[Any]]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el resultado del último."""
    result = None
    for step in start():
        if step.result is not None:
            result = step.result
    return result


def memory_text(peak: int) -> str:
    return (f"{number(peak / 2**20, 0)} MiB; presupuesto "
            f"{number(MEMORY_BUDGET_BYTES / 2**20, 0)} MiB")


# --- RNF-013-01: las envolventes de pendiente constante ------------------------------------------


class EnvelopeTest(unittest.TestCase):
    """RNF-013-01 y RNF-013-04 con los anillos y el disco de §2.2 sobre 2,81 M celdas."""

    ring: ClassVar[np.ndarray]
    thick: ClassVar[np.ndarray]
    solid: ClassVar[np.ndarray]

    @classmethod
    def setUpClass(cls) -> None:
        cls.ring = dperf.ring_seeds(dperf.RING_HALF_WIDTH_M)
        cls.thick = dperf.ring_seeds(dperf.THICK_HALF_WIDTH_M)
        cls.solid = dperf.disc_seeds()

    @staticmethod
    def seeds_of(seed: np.ndarray) -> int:
        return int(np.count_nonzero(np.isfinite(seed)))

    def report_exact(self, rnf_text: str, seed: np.ndarray, found: list[vperf.Driven],
                     budget_s: float) -> None:
        reduction = found[-1].result.reduction
        gis_perf.report(
            f"RNF-013-01: envolvente euclídea exacta {rnf_text} ({count(self.seeds_of(seed))} "
            f"semillas; tras reducirlas quedan {count(reduction.kept)}: "
            f"{count(reduction.dominated)} dominadas y {count(reduction.redundant)} redundantes) "
            f"con {number(dperf.GENERAL_DEG, 0)}° sobre {count(dperf.CELLS)} celdas de 1 m, de la "
            f"primera llamada al último paso "
            f"(con su comprobación; {MACHINE}): {gis_perf.median_line(totals(found))}; "
            f"{calls_text(found)}; hueco entre avances {number(gaps(found)[0], 3)} s; "
            f"presupuesto {number(budget_s, 0)} s")

    def test_chamfer(self) -> None:
        """RNF-013-01: la envolvente *chamfer* 5×5 de pendiente constante (35°) de las semillas
        en anillo sobre 2,81 M celdas, de la primera llamada al último paso con la comprobación del
        punto fijo, en ≤ 3 s (mediana de 5), con un avance como mucho cada 1 s."""
        slope = envelopes.constant_slope(dperf.GENERAL_DEG)
        found = repeat(chamfer(self.ring, slope, "Anillo"))
        median_gap, worst_gap = gaps(found)
        gis_perf.report(
            f"RNF-013-01: envolvente chamfer 5×5 de {count(self.seeds_of(self.ring))} semillas en "
            f"un anillo de {number(dperf.RING_RADIUS_M, 0)} m con {number(dperf.GENERAL_DEG, 0)}° "
            f"sobre {count(dperf.CELLS)} celdas de 1 m, de la primera llamada al último paso (con "
            f"la comprobación del punto fijo; {MACHINE}): {gis_perf.median_line(totals(found))}; "
            f"{found[-1].result.iterations} vuelta(s); {calls_text(found)}; hueco entre avances "
            f"{number(median_gap, 3)} s (el peor, {number(worst_gap, 3)} s); presupuesto "
            f"{number(CHAMFER_BUDGET_S, 0)} s")
        self.assertLessEqual(statistics.median(totals(found)), CHAMFER_BUDGET_S)
        self.assertLessEqual(median_gap, PROGRESS_GAP_S)

    def test_exact_contour(self) -> None:
        """RNF-013-01: la euclídea exacta con semillas de contorno (el anillo de §2.2, 5.3 mil
        celdas) sobre 2,81 M celdas en ≤ 6 s (mediana de 5)."""
        self.assertLess(self.seeds_of(self.ring), dperf.CONTOUR_MAX_SEEDS)
        found = repeat(exact(self.ring, "Anillo"))
        self.report_exact("con semillas de contorno (anillo de 600 m)", self.ring, found,
                          CONTOUR_BUDGET_S)
        self.assertLessEqual(statistics.median(totals(found)), CONTOUR_BUDGET_S)
        self.assertLessEqual(gaps(found)[0], PROGRESS_GAP_S)

    def test_exact_thick_contour(self) -> None:
        """RNF-013-01: la euclídea exacta con un contorno del tope de la spec (hasta 10.000
        celdas: el anillo más grueso) sobre 2,81 M celdas en ≤ 6 s (mediana de 5)."""
        seeds = self.seeds_of(self.thick)
        self.assertLessEqual(seeds, dperf.CONTOUR_MAX_SEEDS)
        self.assertGreater(seeds, 0.9 * dperf.CONTOUR_MAX_SEEDS)
        found = repeat(exact(self.thick, "Anillo grueso"))
        self.report_exact("con el contorno más grueso del tope (anillo de 600 m)", self.thick,
                          found, CONTOUR_BUDGET_S)
        self.assertLessEqual(statistics.median(totals(found)), CONTOUR_BUDGET_S)
        self.assertLessEqual(gaps(found)[0], PROGRESS_GAP_S)

    def test_exact_solid_zone(self) -> None:
        """RNF-013-01: la euclídea exacta con una zona maciza rugosa de hasta 160.000 semillas
        (±2 m y ruido de 0,3 m) sobre 2,81 M celdas en ≤ 30 s (mediana de 5, D-22)."""
        seeds = self.seeds_of(self.solid)
        self.assertLessEqual(seeds, dperf.SOLID_MAX_SEEDS)
        self.assertGreater(seeds, 0.99 * dperf.SOLID_MAX_SEEDS)
        found = repeat(exact(self.solid, "Zona maciza"))
        self.report_exact("con una zona maciza rugosa (disco de 225 m)", self.solid, found,
                          SOLID_BUDGET_S)
        self.assertLessEqual(statistics.median(totals(found)), SOLID_BUDGET_S)
        self.assertLessEqual(gaps(found)[0], PROGRESS_GAP_S)

    def test_cancel(self) -> None:
        """RNF-013-01: Esc con el avance a la mitad de la envolvente (la llamada más larga más
        cerrar los pasos) se atiende en ≤ 2 s con el *chamfer* y con la exacta, en el contorno y
        en la zona maciza, sin dejar nada (el cálculo solo escribe en memoria)."""
        slope = envelopes.constant_slope(dperf.GENERAL_DEG)
        cases = (("chamfer", chamfer(self.ring, slope, "Anillo")),
                 ("exacta con contorno", exact(self.ring, "Anillo")),
                 ("exacta con zona maciza", exact(self.solid, "Zona maciza")))
        lines, worst = [], 0.0
        for label, start in cases:
            gc.collect()
            driven = vperf.drive(start, cancel_at=CANCEL_AT)
            self.assertIsNotNone(driven.cancelled_s, f"{label}: no llegó a la mitad")
            assert driven.cancelled_s is not None
            effective = max(driven.calls) + driven.cancelled_s
            worst = max(worst, effective)
            lines.append(f"{label} {number(effective * 1000, 0)} ms (cerrar "
                         f"{number(driven.cancelled_s * 1000, 1)} ms, con el avance en "
                         f"{number((driven.cancelled_at or 0.0) * 100, 0)} %)")
        gis_perf.report(
            f"RNF-013-01: Esc a la mitad del cálculo de una envolvente sobre {count(dperf.CELLS)} "
            f"celdas (la llamada más larga más cerrar los pasos): {'; '.join(lines)}; "
            f"presupuesto {number(CANCEL_BUDGET_S, 0)} s ({MACHINE})")
        self.assertLessEqual(worst, CANCEL_BUDGET_S)

    def test_memory(self) -> None:
        """RNF-013-04: el pico de memoria adicional (``tracemalloc``, con la de numpy) de la
        envolvente *chamfer* y de la exacta (contorno y zona maciza) ≤ 1 GB."""
        slope = envelopes.constant_slope(dperf.GENERAL_DEG)
        cases = (("chamfer", chamfer(self.ring, slope, "Anillo")),
                 ("exacta con contorno", exact(self.ring, "Anillo")),
                 ("exacta con zona maciza", exact(self.solid, "Zona maciza")))
        peaks = {label: gis_perf.peak_bytes(lambda start=start: drain(start))
                 for label, start in cases}
        gis_perf.report(
            f"RNF-013-04: pico de memoria adicional (tracemalloc, con la de numpy) de la "
            f"envolvente sobre {count(dperf.CELLS)} celdas: "
            + "; ".join(f"{label} {number(peak / 2**20, 0)} MiB" for label, peak in peaks.items())
            + f"; presupuesto {number(MEMORY_BUDGET_BYTES / 2**20, 0)} MiB ({MACHINE})")
        for label, peak in peaks.items():
            self.assertLessEqual(peak, MEMORY_BUDGET_BYTES, label)


# --- RNF-013-02: la pendiente de 20 sectores -----------------------------------------------------


class SectorsTest(unittest.TestCase):
    """RNF-013-02 y RNF-013-04 con la pendiente de los 20 sectores de §2.2 (diez perfiles y dos
    taludes impuestos, de 10,6° y 18°) sobre 2,81 M celdas."""

    ring: ClassVar[np.ndarray]
    labels: ClassVar[np.ndarray]
    rules: ClassVar[list[Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.ring = dperf.ring_seeds(dperf.RING_HALF_WIDTH_M)
        cls.labels = dperf.strip_labels()
        cls.rules = dperf.sector_rules()

    def start(self) -> Callable[[], Iterator[Any]]:
        """Los pasos del *chamfer* con la pendiente por sectores (construirla es parte del
        cálculo: es lo que hace la orden antes de la envolvente)."""
        return lambda: envelopes.chamfer_steps(
            self.ring, GEOMETRY,
            envelopes.sector_slope(self.labels, self.rules, dperf.base_rule()), DOWN,
            name="Sectores", budget_s=STEP_BUDGET_S)

    def test_sectors(self) -> None:
        """RNF-013-02: la envolvente *chamfer* con la pendiente de 20 sectores sobre 2,81 M
        celdas, hasta converger, de la primera llamada al último paso, en ≤ 10 s (mediana de 5)."""
        found = repeat(self.start())
        result = found[-1].result
        median_gap, _ = gaps(found)
        gis_perf.report(
            f"RNF-013-02: envolvente chamfer 5×5 con la pendiente de {len(self.rules)} sectores "
            f"(tangentes de {number(min(r.effective for r in self.rules), 2)} a "
            f"{number(max(r.effective for r in self.rules), 2)}) sobre {count(dperf.CELLS)} celdas "
            f"de 1 m, hasta converger ({result.iterations} vueltas, punto fijo a "
            f"{number(result.violation, 15)} m; {MACHINE}): {gis_perf.median_line(totals(found))};"
            f" {calls_text(found)}; hueco entre avances {number(median_gap, 3)} s; presupuesto "
            f"{number(SECTORS_BUDGET_S, 0)} s")
        self.assertGreater(result.iterations, 1, "los datos no obligan a iterar: no miden nada")
        self.assertLessEqual(statistics.median(totals(found)), SECTORS_BUDGET_S)
        self.assertLessEqual(median_gap, PROGRESS_GAP_S)

    def test_sectors_memory(self) -> None:
        """RNF-013-04: el pico de memoria adicional (``tracemalloc``, con la de numpy) de la
        envolvente de 20 sectores, con la construcción de su pendiente por celdas, ≤ 1 GB."""
        start = self.start()
        peak = gis_perf.peak_bytes(lambda: drain(start))
        gis_perf.report(
            f"RNF-013-04: pico de memoria adicional (tracemalloc, con la de numpy) de la "
            f"envolvente chamfer de {len(self.rules)} sectores sobre {count(dperf.CELLS)} celdas "
            f"({MACHINE}): {memory_text(peak)}")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


# --- El proyecto de escala (RNF-013-03 y RNF-013-06) ---------------------------------------------

_SCALE: dict[str, Any] = {}
"""El proyecto de escala del módulo (se crea al pedirlo la primera vez y se cierra en
:func:`tearDownModule`): lo comparten :class:`PreviewTest` y :class:`DesignTest`."""


def scale() -> dperf.DesignScale:
    if "data" not in _SCALE:
        stack = ExitStack()
        _SCALE["stack"] = stack
        try:
            _SCALE["data"] = stack.enter_context(dperf.scale_project())
        except BaseException:
            stack.close()
            _SCALE.clear()
            raise
    return _SCALE["data"]  # type: ignore[no-any-return]


def tearDownModule() -> None:  # noqa: N802
    stack = _SCALE.pop("stack", None)
    _SCALE.clear()
    if stack is not None:
        stack.close()


class PreviewTest(unittest.TestCase):
    """RNF-013-06 con el proyecto de escala (máscaras al día, 20 sectores con su búsqueda
    cerrada)."""

    def test_preview(self) -> None:
        """RNF-013-06: el resumen de la preparación (semillas, dominio de trabajo y sectores
        tocados) de las semillas en anillo sobre 2,81 M celdas y 20 sectores, de la primera
        llamada al resumen, en ≤ 1 s (mediana de 5); y, aparte, el de una superficie entera como
        semillas (2,7 M celdas)."""
        data = scale()
        cases = (("semillas en anillo", dperf.ring_request(data, "Vista previa")),
                 ("toda la superficie como semillas", dperf.surface_request(data, "Vista previa")))
        lines, worst = [], 0.0
        for label, request in cases:
            found = repeat(lambda request=request: steps.preview_steps(
                data.project, request, data.v1.uid, budget_s=STEP_BUDGET_S))
            summary = found[-1].result
            self.assertEqual(len(summary.sectors), dperf.SECTORS)
            self.assertGreater(summary.seeds.cells, 0)
            median = statistics.median(totals(found))
            worst = max(worst, median)
            lines.append(f"{label} ({count(summary.seeds.cells)} semillas, "
                         f"{count(summary.domain.cells)} celdas de dominio): "
                         f"{gis_perf.median_line(totals(found))}; {calls_text(found)}")
        gis_perf.report(
            f"RNF-013-06: resumen de la preparación (vista previa) sobre {count(dperf.CELLS)} "
            f"celdas de 1 m y {dperf.SECTORS} sectores, de la primera llamada al resumen "
            f"({MACHINE}): " + "; ".join(lines) + f"; presupuesto {number(PREVIEW_BUDGET_S, 0)} s")
        self.assertLessEqual(worst, PREVIEW_BUDGET_S)


@dataclass(frozen=True, slots=True)
class Chain:
    """Un cálculo completo: lo que tardó en total, la llamada más larga de «Calcular» de cada
    orden, lo que tardó cada «Crear» y los números del resultado."""

    total_s: float
    longest_s: float
    longest_phase: str
    create_s: tuple[float, float]
    moved_cells: int
    berm_rows: int


class DesignTest(unittest.TestCase):
    """RNF-013-03 y RNF-013-04 con el proyecto de escala: el cálculo completo de las dos órdenes
    (la envolvente por sectores y su escalonado en corte), cada una con su «Calcular» y su «Crear»,
    en disco local."""

    made: ClassVar[int] = 0

    def chain(self) -> Chain:
        data = scale()
        type(self).made += 1
        envelope = dperf.sectors_request(data, f"Hueco {self.made}")
        design = dperf.design_request(data, f"Bancos {self.made}", envelope.name)
        began = time.perf_counter()
        first = vperf.drive(lambda: steps.envelope_run(data.project, envelope, version=data.v1.uid,
                                                       budget_s=STEP_BUDGET_S))
        with first.result as calculation:
            started = time.perf_counter()
            calculation.create()
            created_envelope = time.perf_counter() - started
        second = vperf.drive(lambda: steps.design_run(
            data.project, design, dperf.START, version=data.v1.uid, budget_s=STEP_BUDGET_S))
        with second.result as calculation:
            started = time.perf_counter()
            calculation.create()
            created_design = time.perf_counter() - started
            outcome = calculation.outcome
        total = time.perf_counter() - began
        slowest = max((first, second), key=lambda driven: driven.longest_s)
        return Chain(total, slowest.longest_s, slowest.longest_phase,
                     (created_envelope, created_design), outcome.report.moved_cells,
                     outcome.berms.count)

    def test_design(self) -> None:
        """RNF-013-03: el cálculo completo (envolvente por sectores, regularización, escalonado
        en corte, recorte final, composición e informe) sobre 2,81 M celdas, de la primera llamada
        de «Calcular» de la envolvente a las cifras registradas por el «Crear» del escalonado, en un
        proyecto en disco local, en ≤ 12 s (mediana de 5; la primera, que calienta la caché de
        lectura, no cuenta)."""
        self.chain()
        found = []
        for _ in range(RUNS):
            gc.collect()
            found.append(self.chain())
        seconds = [chain.total_s for chain in found]
        worst = max(found, key=lambda chain: chain.longest_s)
        gis_perf.report(
            f"RNF-013-03: cálculo completo de una envolvente por {dperf.SECTORS} sectores y su "
            f"escalonado en corte sobre {count(dperf.CELLS)} celdas de 1 m (de «Calcular» de la "
            f"envolvente a las cifras registradas del escalonado: lectura de la partida y de las "
            f"máscaras, cálculo, tres rejillas con su hash y las dos transacciones; "
            f"{count(found[-1].moved_cells)} celdas movidas y {found[-1].berm_rows} filas de "
            f"bermas; proyecto en disco local; {MACHINE}): {gis_perf.median_line(seconds)}; la "
            f"llamada más larga de «Calcular», {number(worst.longest_s * 1000, 0)} ms "
            f"(«{worst.longest_phase}»); «Crear» de la envolvente "
            f"{number(statistics.median(c.create_s[0] for c in found) * 1000, 0)} ms y del "
            f"escalonado {number(statistics.median(c.create_s[1] for c in found) * 1000, 0)} ms; "
            f"presupuesto {number(DESIGN_BUDGET_S, 0)} s")
        self.assertGreater(found[-1].moved_cells, 0)
        self.assertGreater(found[-1].berm_rows, 0)
        self.assertLessEqual(statistics.median(seconds), DESIGN_BUDGET_S)

    def test_design_memory(self) -> None:
        """RNF-013-04: el pico de memoria adicional (``tracemalloc``, con la de numpy) del cálculo
        completo de las dos órdenes sobre 2,81 M celdas ≤ 1 GB."""
        self.chain()  # sin caché de lectura
        peak = gis_perf.peak_bytes(self.chain)
        gis_perf.report(
            f"RNF-013-04: pico de memoria adicional (tracemalloc, con la de numpy) del cálculo "
            f"completo de la envolvente por {dperf.SECTORS} sectores y su escalonado sobre "
            f"{count(dperf.CELLS)} celdas ({MACHINE}): {memory_text(peak)}")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


if __name__ == "__main__":
    unittest.main()
