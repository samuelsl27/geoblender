# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de la corta por bancos (spec 018, T36; RNF-018-01 a 07; plan 018 §7.3, ``tests/rendimiento/des``), con la forma de ``test_roads_perf.py`` de la 017: los guiones de medida de
``plan.md`` §7.3 (que vivían en el *scratchpad* de la sesión del plan y no estaban versionados) convertidos en pruebas.

Se ejecuta con ``tools/check.py --rendimiento``, nunca en el «verde»: el Python de Blender (su numpy 2.3.4), en el PC de referencia y en disco local. Cada cifra se imprime en una línea
``RNF-018-nn: …`` con el equipo y el intérprete (``tools/check.py`` las recoge) y se compara con su presupuesto, **sin relajarlo**. Mediana de 5 las medidas de hasta unos 3 s, **de 3** las de
más.

**Datos** (``tests/support/pit_perf.py``, que no versiona ninguno): la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M) de la 013; la corta **ascendente de 40 bancos** desde un fondo rugoso de
2.000 vértices (los 80 desfases de pie y cresta; ≈ 33.000 vértices tras simplificar a 5 cm) y **60 bancos con 160.000 vértices** como polilíneas hechas (``pit_data.scale_rings``).

- RNF-018-01 (:class:`BenchesTest`): los bancos de la ascendente de 40 bancos con 2.000 vértices por polilínea, ≤ 60 s (previsto 1 a 5 s).
- RNF-018-02 (:class:`RampTest`): lo que añade una rampa, ≤ 10 s. **Nota:** la espiral de CE-018-05 solo cabe en este fondo hasta unos 24 bancos (a partir de ahí el radio que cabe es menor que el
  mínimo del perfil de pista: un rechazo legítimo, no un fallo de plazo) y el zig-zag de CE-018-06 en 5: se mide la espiral sobre 20 bancos y el zig-zag sobre 5, y se anota lo que cuestan **de
  más** que la misma corta sin rampa, y lo que cuestan en total.
- RNF-018-03 (:class:`SurfaceTest`): rasterizar 160.000 vértices de 60 bancos en las 2,81 M celdas (triangulación pura por pasos y cota por celda), ≤ 30 s.
- RNF-018-04 (:class:`SurfaceTest`): la línea de cielo sobre 2,81 M celdas, ≤ 5 s.
- RNF-018-05 (:class:`SurfaceTest`): los hallazgos, las cifras y el volumen por banco de las 60 bancos y 160.000 vértices, ≤ 10 s.
- RNF-018-06 (:class:`ComputeTest`): cada llamada del hilo de «Calcular» (cada ``next`` de ``pit_store.compute_steps`` con el presupuesto de la interfaz, 0,05 s), en CPU del proceso, ≤ 0,2 s;
  **con el margen del 25 % por la carga ajena que Samuel aceptó para RNF-017-04 y RNF-018-06 (23/11/2026): entre 0,2 y 0,25 s sale una línea ``RNF-018-06: AVISO …`` y por encima de 0,25 s falla.**
- RNF-018-07 (``test_z_memory`` de cada clase): el pico de memoria adicional (``tracemalloc``, con la de numpy) ≤ 1,5 GB, en una pasada aparte.

Lo que va a Blender (cada llamada de las órdenes reales, la vista previa RNF-018-08, el TIN y el sólido RNF-018-09) y el disco (RNF-018-11) son de ``perf_pit.py`` y de la T36b.
"""

from __future__ import annotations

import statistics
import unittest
from collections.abc import Callable
from typing import Any

from tests.support import gis_perf
from tests.support import pit_data as pd
from tests.support import pit_perf as pp
from tests.support.package import import_geoblender

pit_bench = import_geoblender("design.pit_bench")
pit_report = import_geoblender("design.pit_report")
pit_sky = import_geoblender("design.pit_sky")
pit_store = import_geoblender("design.pit_store")
pit_surface = import_geoblender("design.pit_surface")
provenance = import_geoblender("design.provenance")
seeds = import_geoblender("design.seeds")

BENCHES_BUDGET_S = 60.0  # RNF-018-01
RAMP_BUDGET_S = 10.0  # RNF-018-02
RASTER_BUDGET_S = 30.0  # RNF-018-03
SKY_BUDGET_S = 5.0  # RNF-018-04
REPORT_BUDGET_S = 10.0  # RNF-018-05
CALL_BUDGET_S = 0.2  # RNF-018-06: cada llamada del hilo de Blender, en CPU
CALL_MARGIN = 1.25  # el margen del 25 % por la carga ajena (Samuel, 23/11/2026)
MEMORY_BUDGET_BYTES = int(1.5 * 1024**3)  # RNF-018-07
MIB = 1024**2
RUNS = 5
HEAVY_RUNS = 3
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count
COMMON = {provenance.TOLERANCE_FACE: 1.0}
WINDOW_FACE_DEG = 1.0


def ms(value: float) -> str:
    return number(value * 1000, 0)


def window_of(job: Any) -> tuple[slice, slice]:
    return slice(0, job.grid.nrows), slice(0, job.grid.ncols)


def median_of(runs: int, make: Callable[[], Any]) -> tuple[list[float], Any]:
    """``runs`` ejecuciones de ``make()`` (cada una devuelve un ``Driven`` o un valor y su tiempo): los tiempos y el último resultado."""
    times, last = [], None
    for _ in range(runs):
        last, wall = pp.timed(make)
        times.append(wall)
    return times, last


def call_verdict(longest_cpu_s: float) -> str | None:
    """El aviso de RNF-018-06 (``None`` si cabe en 0,2 s): empieza por «RNF-018-06:» para que ``tools/check.py`` lo recoja."""
    if longest_cpu_s <= CALL_BUDGET_S:
        return None
    return (f"RNF-018-06: AVISO, una llamada del hilo pasa de {ms(CALL_BUDGET_S)} ms ({ms(longest_cpu_s)} ms de CPU) pero cabe en el margen del 25 % por carga ajena "
            f"({ms(CALL_BUDGET_S * CALL_MARGIN)} ms); por encima de ese margen la prueba falla")


class CallCase(unittest.TestCase):
    def check_call(self, longest_cpu_s: float, what: str) -> None:
        """La llamada más larga (CPU del proceso) no pasa de 0,2 s (con el margen del 25 % y su aviso)."""
        notice = call_verdict(longest_cpu_s)
        if notice is not None:
            gis_perf.report(f"{notice}; {what}")
        self.assertLessEqual(longest_cpu_s, CALL_BUDGET_S * CALL_MARGIN, f"{what}: una llamada del hilo pasa de 0,25 s de CPU")


class BenchesTest(CallCase):
    """RNF-018-01 y RNF-018-06: los bancos de la ascendente de 40 bancos."""

    def test_a_forty_benches(self) -> None:
        """RNF-018-01: 40 bancos desde un fondo de 2.000 vértices (80 desfases), con dos ruidos de fondo (0,15 y 0,4 m), ≤ 60 s (mediana de 5), con cada llamada ≤ 0,2 s de CPU."""
        for noise in (pp.FLOOR_NOISE_M, 0.4):
            job = pp.ascending_job(noise_m=noise)
            driven: list[Any] = []
            times, _ = median_of(RUNS, lambda: driven.append(pp.drive(pit_bench.ascend_steps(job))) or driven[-1])
            found = driven[-1].result
            gis_perf.report(
                f"RNF-018-01: los bancos de la ascendente de {found.count} bancos con fondo rugoso de {count(pp.FLOOR_VERTICES)} vértices (ruido {number(noise, 2)} m; {count(sum(len(p.vertices) for p in found.polylines))} "
                f"vértices de polilíneas; {MACHINE}): {gis_perf.median_line(times)}; la llamada más larga {ms(max(d.longest_cpu_s for d in driven))} ms de CPU; presupuesto {number(BENCHES_BUDGET_S, 0)} s")
            self.assertEqual((found.count, found.reliable), (pp.BENCHES, True))
            self.assertLessEqual(statistics.median(times), BENCHES_BUDGET_S)
            self.check_call(max(d.longest_cpu_s for d in driven), f"los bancos (ruido {noise} m)")


class RampTest(CallCase):
    """RNF-018-02: la espiral y el zig-zag sobre la corta."""

    def test_a_spiral(self) -> None:
        """RNF-018-02: lo que añade la espiral de CE-018-05 (con su eje, sus curvas y su banda) a 20 bancos, ≤ 10 s (mediana de 3), y lo que cuesta en total."""
        plain, _ = median_of(HEAVY_RUNS, lambda: pp.drive(pit_bench.ascend_steps(pp.spiral_ascending_job(benches=20, ramps=(), road_profiles=(), ramp_starts=()))))
        driven: list[Any] = []
        times, _ = median_of(HEAVY_RUNS, lambda: driven.append(pp.drive(pit_bench.ascend_steps(pp.spiral_ascending_job(benches=20)))) or driven[-1])
        extra = statistics.median(times) - statistics.median(plain)
        found = driven[-1].result
        gis_perf.report(f"RNF-018-02: la espiral de 8 % sobre {found.count} bancos de un fondo de {count(pp.FLOOR_VERTICES)} vértices ({MACHINE}): en total {gis_perf.median_line(times)}; la misma corta sin rampa "
                        f"{gis_perf.median_line(plain)}; la rampa añade {number(extra, 2)} s; la llamada más larga {ms(max(d.longest_cpu_s for d in driven))} ms de CPU; presupuesto {number(RAMP_BUDGET_S, 0)} s")
        self.assertEqual(len(found.ramps), 1)
        self.assertLessEqual(extra, RAMP_BUDGET_S)
        self.check_call(max(d.longest_cpu_s for d in driven), "la espiral")

    def test_b_zigzag(self) -> None:
        """RNF-018-02: el zig-zag de CE-018-06 (con su eje, sus curvas y su banda) a 5 bancos, ≤ 10 s (mediana de 5)."""
        driven: list[Any] = []
        times, _ = median_of(RUNS, lambda: driven.append(pp.drive(pit_bench.ascend_steps(pp.zigzag_ascending_job(benches=5)))) or driven[-1])
        found = driven[-1].result
        gis_perf.report(f"RNF-018-02: el zig-zag de 10 % sobre {found.count} bancos ({MACHINE}): {gis_perf.median_line(times)}; la llamada más larga "
                        f"{ms(max(d.longest_cpu_s for d in driven))} ms de CPU; presupuesto {number(RAMP_BUDGET_S, 0)} s")
        self.assertEqual(len(found.ramps), 1)
        self.assertLessEqual(statistics.median(times), RAMP_BUDGET_S)
        self.check_call(max(d.longest_cpu_s for d in driven), "el zig-zag")


class SurfaceTest(CallCase):
    """RNF-018-03, 04, 05 y 06 con 60 bancos y 160.000 vértices sobre la rejilla de 2,81 M celdas."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = pp.scale_job()
        cls.polylines = pp.scale_polylines()
        cls.vertices = sum(len(item.vertices) for item in cls.polylines)

    def surface(self) -> Any:
        return pp.drive(pit_surface.rasterize_steps(self.job, self.polylines, crs=pd.CRS, vertical=pd.VERTICAL, budget_s=pp.STEP_BUDGET_S))

    def test_a_rasterize(self) -> None:
        """RNF-018-03: la triangulación pura por pasos y la cota de 2,81 M celdas con 160.000 vértices de 60 bancos, ≤ 30 s (mediana de 3), con cada llamada ≤ 0,2 s de CPU."""
        driven: list[Any] = []
        times, _ = median_of(HEAVY_RUNS, lambda: driven.append(self.surface()) or driven[-1])
        found = driven[-1].result
        gis_perf.report(f"RNF-018-03: rasterizar {count(self.vertices)} vértices de 60 bancos en {count(self.job.grid.ncols * self.job.grid.nrows)} celdas ({count(found.triangles)} triángulos; {MACHINE}): "
                        f"{gis_perf.median_line(times)}; la llamada más larga {ms(max(d.longest_cpu_s for d in driven))} ms de CPU; presupuesto {number(RASTER_BUDGET_S, 0)} s")
        self.assertGreater(found.cut_m3, 0.0)
        self.assertLessEqual(statistics.median(times), RASTER_BUDGET_S)

    def test_a2_rasterize_calls(self) -> None:
        """RNF-018-06 **no se cumple todavía** con 160.000 vértices de 60 bancos sobre 2,81 M celdas: la llamada más larga de la superficie mide ≈ 0,31-0,34 s de CPU (0,2 s con el margen del 25 % de
        0,25 s) por cuatro fases de numpy que no ceden el hilo (la comprobación del casco de ``gis.cdt``, ≈ 0,31 s; las bandas de ``_row_costs`` del rasterizado, ≈ 0,27 s; el volumen por banco, ≈ 0,20 s;
        el orden de Hilbert, ≈ 0,19 s). Con la corta de 40 bancos de ≈ 115.000 puntos que calcula «Calcular» (:class:`ComputeTest`) la llamada más larga sí cabe (≈ 0,16 s). Es un fallo real
        hasta que Samuel decida (T36, informe): **esta prueba falla a propósito** (no se relaja el techo ni se esconde con una marca de fallo esperado, TST-07); pasa cuando se parta esa fase."""
        found = self.surface()
        self.check_call(found.longest_cpu_s, "la superficie de 160.000 vértices")

    def test_b_skyline(self) -> None:
        """RNF-018-04: la línea de cielo sobre 2,81 M celdas, ≤ 5 s (mediana de 5), con cada llamada ≤ 0,2 s de CPU."""
        found = self.surface().result
        driven: list[Any] = []
        times, _ = median_of(RUNS, lambda: driven.append(pp.drive(pit_sky.skyline_steps(self.job.start, found.stepped, self.job.grid, crs=pd.CRS, vertical=pd.VERTICAL))) or driven[-1])
        line = driven[-1].result
        gis_perf.report(f"RNF-018-04: la línea de cielo sobre {count(self.job.grid.ncols * self.job.grid.nrows)} celdas ({line.n_parts} curvas; {MACHINE}): {gis_perf.median_line(times)}; la llamada más larga "
                        f"{ms(max(d.longest_cpu_s for d in driven))} ms de CPU; presupuesto {number(SKY_BUDGET_S, 0)} s")
        self.assertGreater(line.n_parts, 0)
        self.assertLessEqual(statistics.median(times), SKY_BUDGET_S)
        self.check_call(max(d.longest_cpu_s for d in driven), "la línea de cielo")

    def test_c_report(self) -> None:
        """RNF-018-05: los hallazgos, las cifras (con el volumen por banco) y el contraste de 60 bancos con 160.000 vértices, ≤ 10 s (mediana de 3), con cada llamada ≤ 0,2 s de CPU."""
        found = self.surface().result
        sky = pit_sky.skyline(self.job.start, found.stepped, self.job.grid, crs=pd.CRS, vertical=pd.VERTICAL)
        driven: list[Any] = []

        def make() -> Any:
            work = seeds.pace_progress(
                pit_report.findings_units(self.job, self.polylines, found, face_tolerance_deg=WINDOW_FACE_DEG), pp.STEP_BUDGET_S, phase="pit_report", running="…", finished="…")
            said = pp.drive(work)
            driven.append(said)
            return pit_report.figures(self.job, self.polylines, found, crs=pd.CRS, vertical=pd.VERTICAL, skyline=sky, found=said.result)

        times, figures = median_of(HEAVY_RUNS, make)
        gis_perf.report(f"RNF-018-05: los hallazgos y las cifras de 60 bancos con {count(self.vertices)} vértices ({len(figures.benches)} cifras de banco; {MACHINE}): {gis_perf.median_line(times)}; "
                        f"la llamada más larga {ms(max(d.longest_cpu_s for d in driven))} ms de CPU; presupuesto {number(REPORT_BUDGET_S, 0)} s")
        self.assertEqual(len(figures.benches), 60)
        self.assertLessEqual(statistics.median(times), REPORT_BUDGET_S)
        self.check_call(max(d.longest_cpu_s for d in driven), "los hallazgos")

    def test_z_memory(self) -> None:
        """RNF-018-07: el pico de memoria adicional (``tracemalloc``) de rasterizar y de la línea de cielo con 60 bancos y 160.000 vértices ≤ 1,5 GB."""
        self.surface()
        peak = gis_perf.peak_bytes(lambda: pit_sky.skyline(self.job.start, self.surface().result.stepped, self.job.grid, crs=pd.CRS, vertical=pd.VERTICAL))
        gis_perf.report(f"RNF-018-07: pico de memoria adicional (tracemalloc, con la de numpy) de la superficie y la línea de cielo de 60 bancos ({MACHINE}): {number(peak / MIB, 0)} MiB; "
                        f"presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


class ComputeTest(CallCase):
    """RNF-018-06 y RNF-018-07 con «Calcular» entero (``pit_store.compute_steps``) de la corta de 40 bancos sobre 2,81 M celdas."""

    def compute(self) -> pp.Driven:
        job = pp.ascending_job()
        return pp.drive(pit_store.compute_steps(job, window_of(job), COMMON, crs=pd.CRS, vertical=pd.VERTICAL, budget_s=pp.STEP_BUDGET_S))

    def test_a_every_call(self) -> None:
        """RNF-018-06: cada llamada de «Calcular» (bancos, superficie, línea de cielo, hallazgos, cifras y contraste) de 40 bancos sobre 2,81 M celdas ≤ 0,2 s de CPU (mediana de 3 del total)."""
        driven: list[pp.Driven] = []
        times, _ = median_of(HEAVY_RUNS, lambda: driven.append(self.compute()) or driven[-1])
        longest = max(d.longest_cpu_s for d in driven)
        gis_perf.report(f"RNF-018-06: «Calcular» de 40 bancos sobre {count(2_810_000)} celdas ({driven[-1].count} llamadas; {MACHINE}): total {gis_perf.median_line(times)}; la llamada más larga de todas "
                        f"{ms(longest)} ms de CPU (presupuesto {ms(CALL_BUDGET_S)} ms)")
        self.check_call(longest, "«Calcular» entero")

    def test_z_memory(self) -> None:
        """RNF-018-07: el pico de memoria adicional (``tracemalloc``) de «Calcular» entero de 40 bancos sobre 2,81 M celdas ≤ 1,5 GB, en una pasada aparte."""
        self.compute()
        peak = gis_perf.peak_bytes(self.compute)
        gis_perf.report(f"RNF-018-07: pico de memoria adicional (tracemalloc, con la de numpy) de «Calcular» de 40 bancos sobre 2,81 M celdas ({MACHINE}): {number(peak / MIB, 0)} MiB; "
                        f"presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


if __name__ == "__main__":
    unittest.main()
