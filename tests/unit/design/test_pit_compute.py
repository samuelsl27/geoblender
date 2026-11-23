# SPDX-License-Identifier: GPL-3.0-or-later
"""El cálculo completo de la corta, por pasos y sin escribir (spec 018, T22; HU-018-1, HU-018-4; RF-018-03, 25, 26, 31, 35; RNF-018-06; CE-018-03, 05, 11 y 12).

``pit_store.compute_steps`` encadena, sin proyecto, los bancos (A5 o A6), las rampas, la superficie, la línea de cielo, los hallazgos, las cifras y el
contraste con la 013, y deja un ``PitOutcome``: cada paso cede en ≤ 0,2 s, cerrar el generador a mitad no deja nada, dos ejecuciones dan lo mismo bit a bit y
un desfase que no se pudo verificar **rechaza** el cálculo con el banco y el defecto. La confirmación de la pendiente media de la rampa (RF-018-19) queda
pendiente o cubierta, sin rechazar el cálculo (la pide «Crear», T23)."""

from __future__ import annotations

import time
import unittest
from unittest import mock

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1
from tests.unit.design import test_pit_bench_ramp as rp

pit_bench = import_geoblender("design.pit_bench")
pit_model = import_geoblender("design.pit_model")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")

STEP_M = 4.0
COMMON = {provenance.TOLERANCE_FACE: 1.0}
STEP_LIMIT_S = 0.2
"""RNF-018-06: cada paso cede el hilo en ≤ 0,2 s."""
RAMP_STEP_LIMIT_S = 1.0


def window_of(job: object) -> tuple[slice, slice]:
    return (slice(0, job.grid.nrows), slice(0, job.grid.ncols))


def run(job: object, confirmed: tuple = (), common: dict | None = None) -> tuple[object, list[float]]:
    """El ``PitOutcome`` de ``job`` y lo que tardó cada paso (s)."""
    work = pit_store.compute_steps(job, window_of(job), COMMON if common is None else common, crs=pd.CRS, vertical=pd.VERTICAL, confirmed=confirmed)
    times: list[float] = []
    outcome = None
    while True:
        started = time.perf_counter()
        try:
            step = next(work)
        except StopIteration as done:
            times.append(time.perf_counter() - started)
            outcome = done.value
            break
        times.append(time.perf_counter() - started)
        assert step.result is None
    return outcome, times


class UpCircleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = pd.grid_of(STEP_M)
        cls.job = h1.up_job(cls.grid)
        cls.outcome, cls.times = run(cls.job)

    def test_everything_is_in_the_outcome(self) -> None:
        """RF-018-25, 26, 31: polilíneas, superficie compuesta, huella, línea de cielo, cifras por banco, hallazgos y contraste."""
        out = self.outcome
        self.assertIsInstance(out, pit_model.PitOutcome)
        self.assertEqual((out.name, out.code, out.mode, out.stop), ("Corta 1", "PIT-001", "up", pit_model.StopCriterion.SURFACE))
        found = pit_bench.ascend(self.job)
        self.assertEqual(len(out.polylines), len(found.polylines))
        self.assertTrue(all(np.array_equal(a.vertices, b.vertices) for a, b in zip(out.polylines, found.polylines, strict=True)))
        self.assertEqual(len(out.benches), 5)
        self.assertGreater(len(out.skyline), 0)
        self.assertEqual(out.ramps, ())
        values = {item.key: item.value for item in out.figures}
        self.assertEqual(values["des.pit_benches"], 5)
        self.assertGreater(values["des.pit_cut_m3"], 0.0)
        self.assertAlmostEqual(sum(item.cut_m3 for item in out.benches), values["des.pit_cut_m3"], delta=1e-9 * values["des.pit_cut_m3"])
        self.assertEqual(values["des.pit_findings"], len(out.findings))
        whole = out.compose(self.job.start)
        self.assertTrue(np.array_equal(whole[out.footprint], out.surface[out.footprint]))
        self.assertEqual(int(out.footprint.sum()), int(values["des.pit_area_m2"] / self.grid.cell_area))
        contrast = out.extra["contrast"]
        self.assertAlmostEqual(contrast.volume_pit_m3, values["des.pit_cut_m3"], delta=1e-9 * values["des.pit_cut_m3"])
        self.assertEqual(out.extra["mean_pending"], ())
        self.assertIn("calculada", out.message)

    def test_every_step_yields_in_at_most_0_2_s(self) -> None:
        """RNF-018-06, RF-018-35: ningún paso pasa de 0,2 s."""
        self.assertGreater(len(self.times), 4)
        self.assertLessEqual(max(self.times), STEP_LIMIT_S, [round(t, 3) for t in self.times])

    def test_deterministic_bit_by_bit(self) -> None:
        """RF-018-25, P-15: dos ejecuciones dan lo mismo (superficie, vértices y cifras, bit a bit)."""
        again, _times = run(self.job)
        self.assertTrue(np.array_equal(again.surface, self.outcome.surface, equal_nan=True))
        self.assertTrue(np.array_equal(again.footprint, self.outcome.footprint))
        self.assertEqual([a.value for a in again.figures], [b.value for b in self.outcome.figures])
        self.assertTrue(all(np.array_equal(a.vertices, b.vertices) for a, b in zip(again.polylines, self.outcome.polylines, strict=True)))
        self.assertEqual(again.findings, self.outcome.findings)

    def test_closing_midway_leaves_nothing(self) -> None:
        """RF-018-35: cerrar el generador a mitad no lanza ni deja estado: la ejecución siguiente da el mismo resultado."""
        work = pit_store.compute_steps(self.job, window_of(self.job), COMMON, crs=pd.CRS, vertical=pd.VERTICAL)
        next(work)
        next(work)
        work.close()
        again, _times = run(self.job)
        self.assertTrue(np.array_equal(again.surface, self.outcome.surface, equal_nan=True))

    def test_inputs_are_not_modified(self) -> None:
        """RF-018-01: la partida y las máscaras de la entrada no cambian."""
        start = self.job.start.copy()
        run(self.job)
        self.assertTrue(np.array_equal(start, self.job.start))

    def test_a_window_that_misses_the_movement_is_a_program_error(self) -> None:
        """Una ventana que no contiene todo el movimiento es un error del programa (no se corta el resultado en silencio)."""
        small = (slice(0, 5), slice(0, 5))
        with self.assertRaises(ValueError):
            list(pit_store.compute_steps(self.job, small, COMMON, crs=pd.CRS, vertical=pd.VERTICAL))


class DescentTest(unittest.TestCase):
    def test_square_limit_by_descent(self) -> None:
        """CE-018-04: la descendente da su fondo, su criterio de parada y sus cifras; el contraste con la 013 no avisa de la ascendente."""
        job = h1.down_job(pd.grid_of(STEP_M))
        outcome, times = run(job)
        self.assertEqual((outcome.mode, outcome.stop), ("down", pit_model.StopCriterion.FLOOR_WIDTH))
        self.assertEqual(len(outcome.benches), 5)
        self.assertLessEqual(max(times), STEP_LIMIT_S, [round(t, 3) for t in times])
        values = {item.key: item.value for item in outcome.figures}
        self.assertGreater(values["des.pit_cut_m3"], 0.0)
        self.assertNotIn("des.pit_ramp_len_m", values)


class UnreliableTest(unittest.TestCase):
    def test_an_unverified_offset_rejects_the_calculation(self) -> None:
        """RF-018-10: un desfase no fiable **rechaza** el cálculo con el banco y el defecto; nunca en silencio y sin llegar a la superficie."""
        job = h1.up_job(pd.grid_of(STEP_M))
        real = pit_bench.ascend(job)
        notice = preview.Notice("des.pit_offset_unreliable", {"name": "Corta 1", "bench": 3, "value": 0.25, "limit": 0.001})
        bad = pit_bench.Benches(real.polylines, real.stop, real.count, (*real.notices, notice), False, real.face_volume_m3)

        def fake(job_: object, *, budget_s: float = 0.05) -> object:
            yield pit_store.Progress("pit_bench", 1, 1, "Bancos calculados", result=bad)

        with mock.patch.object(pit_bench, "ascend_steps", fake), mock.patch.object(pit_store.pit_surface, "rasterize_steps") as surface:
            with self.assertRaises(pit_store.DesignError) as caught:
                list(pit_store.compute_steps(job, window_of(job), COMMON, crs=pd.CRS, vertical=pd.VERTICAL))
        surface.assert_not_called()
        self.assertEqual(caught.exception.code, "des.pit_offset_not_verified")
        self.assertEqual(caught.exception.values["bench"], 3)
        self.assertIn("0,25", str(caught.exception))
        self.assertEqual(messages.lookup("des.pit_offset_not_verified").severity, "error")
        self.assertNotEqual(messages.lookup("des.pit_offset_not_verified").msgid, messages.lookup("des.pit_offset_not_verified").es)


class RampTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.job = rp.spiral_job()
        cls.outcome, cls.times = run(cls.job)

    def test_ramp_paths_and_figures(self) -> None:
        """RF-018-16, 31: el eje de la rampa (con Z y semiancho), sus cifras (125 m por banco: ≥ 5 · 125 m de rampa) y las del hallazgo."""
        out = self.outcome
        self.assertEqual(len(out.ramps), 1)
        self.assertEqual(out.ramps[0].code, "rampa")
        values = {item.key: item.value for item in out.figures}
        self.assertGreater(values["des.pit_ramp_len_m"], 600.0)
        self.assertAlmostEqual(values["des.pit_ramp_gradient_max_pct"], 8.0, delta=0.3)
        self.assertGreater(values["des.pit_ramp_band_m3"], 0.0)
        self.assertEqual(out.extra["mean_pending"], ())
        # Con rampa, los pasos largos son de los motores de T21 (el bucle de la rampa y la disposición bajo la banda, con celdas de 1 m: hasta ≈ 0,5 s);
        # se reparten en la T36 (banco). Aquí solo se acota para que no crezca sin control.
        self.assertLessEqual(max(self.times), RAMP_STEP_LIMIT_S, [round(t, 3) for t in self.times])

    def test_mean_over_pm_is_pending_until_confirmed(self) -> None:
        """RF-018-19: con pm de 5 % la media de 8 % queda **pendiente** (no rechaza el cálculo); una confirmación que la cubre la deja confirmada
        y una de otra rampa, o de una media menor, no."""
        job = rp.spiral_job()
        profile = rp.road(min_radius_m=7.0, max_mean_gradient_pct=5.0)
        job = pit_store.replace(job, road_profiles=(profile,), ramps=(pit_store.replace(job.ramps[0], road_profile=profile.code),))
        pending, _times = run(job)
        self.assertEqual([item[0] for item in pending.extra["mean_pending"]], ["rampa"])
        code, mean, limit = pending.extra["mean_pending"][0]
        self.assertEqual(limit, 5.0)
        self.assertGreater(mean, 5.0)
        done = provenance.ramp_confirmation("rampa", mean, "Hay que cruzar el cauce", "Samuel", "2026-11-23T10:00:00Z")
        covered, _times = run(job, (done,))
        self.assertEqual(covered.extra["mean_pending"], ())
        self.assertEqual(covered.extra["mean_confirmed"], (done,))
        other = provenance.ramp_confirmation("otra", mean, "Motivo", "Samuel", "2026-11-23T10:00:00Z")
        less = provenance.ramp_confirmation("rampa", mean - 1.0, "Motivo", "Samuel", "2026-11-23T10:00:00Z")
        for wrong in (other, less):
            self.assertEqual(len(pit_store.confirm_ramps(pending.extra["checked_ramps"], (wrong,))[1]), 1)


if __name__ == "__main__":
    unittest.main()
