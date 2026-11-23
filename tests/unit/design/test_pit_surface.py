# SPDX-License-Identifier: GPL-3.0-or-later
"""La superficie de la corta en la rejilla (spec 018, T18; HU-018-4; RF-018-28 y 31; CE-018-03 y 11; plan 018 §5.4 A10).

El círculo de CE-018-03 con celdas de 4, 2 y 1 m contra el volumen analítico a ≤ 0,1 % (D-11), la verificación por recinto (fuera de lo
admitido, la de partida bit a bit), el volumen por banco (suma el total y cada rodaja es su tronco de cono), el borde de una rampa como
arista obligatoria y la cancelación a mitad. Sin proyecto y sin Blender; rejillas de ≤ 200 × 200."""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")
pit_surface = import_geoblender("design.pit_surface")

TOL = 1e-3
"""D-11 (HIPÓTESIS): ≤ 0,1 % con celdas de ≤ 2 m."""


def run(job: object, found: object | None = None, ramps: tuple = ()) -> object:
    found = pit_bench.ascend(job) if found is None else found
    return pit_surface.rasterize(job, found, ramps, crs=pd.CRS, vertical=pd.VERTICAL)


def surface_of(step_m: float, **changes: object) -> tuple[object, object]:
    job = h1.up_job(pd.grid_of(step_m), **changes)
    return job, run(job)


class CircleVolumeTest(unittest.TestCase):
    def test_volume_matches_the_analytic_one(self) -> None:
        """RF-018-28, CE-018-03: el volumen de la superficie de la rejilla frente a los 961.661,57 m³ con celdas de 4 m (las de 2 y 1 m, en la prueba de referencia)."""
        exact = pd.circle_volume_by_hand()
        for step in (4.0,):
            with self.subTest(cell_m=step):
                _, found = surface_of(step)
                self.assertLess(abs(found.cut_m3 / exact - 1.0), TOL)

    def test_cut_is_the_sum_of_the_cells(self) -> None:
        """RF-018-31: el corte es ``Σ (partida − corta) · área de celda``, a ≤ 10⁻⁹ relativo."""
        job, found = surface_of(4.0)
        by_hand = float(np.nansum(np.maximum(job.start - found.surface, 0.0))) * job.grid.cell_area
        self.assertAlmostEqual(found.cut_m3 / by_hand, 1.0, delta=1e-9)

    def test_surface_height_matches_the_analytic_surface(self) -> None:
        """CE-018-03: la cota de la superficie frente a la analítica (salvo las celdas de una cara, que cambian rápido) y el terreno arriba."""
        job, found = surface_of(4.0)
        exact = pd.circle_surface(job.grid)
        difference = np.abs(found.surface - exact)
        self.assertLess(float(np.median(difference)), 1e-6)
        self.assertLess(float(difference.max()), 5.0)
        self.assertEqual(float(np.nanmax(found.surface)), pd.TOP_Z_M)


class EnclosureTest(unittest.TestCase):
    def test_outside_the_enclosure_is_the_start_bit_for_bit(self) -> None:
        """RF-018-28 (P-7): fuera del recinto la superficie es la de partida, bit a bit."""
        job, found = surface_of(4.0)
        self.assertTrue(found.enclosure.any() and not found.enclosure.all())
        self.assertTrue(np.array_equal(found.surface[~found.enclosure], job.start[~found.enclosure]))
        self.assertTrue(np.isnan(found.stepped[~found.enclosure]).all())

    def test_nothing_moves_where_the_cut_is_not_admitted(self) -> None:
        """RF-018-28, CE-018-11: donde las máscaras no admiten el corte la superficie es la de partida (0 m³) y se da aparte."""
        grid = pd.grid_of(4.0)
        allowed = np.ones(grid.shape, bool)
        allowed[:, : grid.ncols // 2] = False
        job = h1.up_job(grid, cut_allowed=allowed)
        found = run(job)
        self.assertTrue(np.array_equal(found.surface[~allowed], job.start[~allowed]))
        self.assertTrue(found.blocked.any() and not (found.blocked & allowed).any())
        self.assertLess(found.cut_m3, run(h1.up_job(grid)).cut_m3)

    def test_untouchable_cells_do_not_move(self) -> None:
        """RF-018-05: una celda intocable no cambia aunque el corte se admita."""
        grid = pd.grid_of(4.0)
        blocked = np.zeros(grid.shape, bool)
        blocked[40:60, 40:60] = True
        job = h1.up_job(grid, untouchable=blocked)
        found = run(job)
        self.assertTrue(np.array_equal(found.surface[blocked], job.start[blocked]))


class BenchVolumeTest(unittest.TestCase):
    def test_slices_sum_to_the_total_and_match_the_frusta(self) -> None:
        """RF-018-31, CE-018-11: las rodajas ``z₀ + k·h`` suman el corte a ≤ 10⁻⁹ y cada una es el tronco de cono de su banco."""
        _, found = surface_of(2.0)
        self.assertAlmostEqual(float(found.bench_m3.sum()) / found.cut_m3, 1.0, delta=1e-9)
        # la interpolación del fondo llano puede quedar 10⁻¹³ m por debajo de su cota: la 011 abre entonces una rodaja más debajo, vacía
        slack = len(found.bench_m3) - pd.BENCHES
        self.assertIn(slack, (0, 1))
        self.assertLess(float(found.bench_m3[:slack].sum()), 1e-6)
        self.assertAlmostEqual(float(found.bench_levels[slack]), pd.FLOOR_Z_M, delta=1e-12)
        sliced = found.bench_m3[slack:]
        for k, (foot, crest) in enumerate(pd.circle_radii_by_hand()):
            exact = math.pi * 10.0 / 3.0 * (foot * foot + foot * crest + crest * crest)
            with self.subTest(bench=k):
                self.assertLess(abs(sliced[k] / exact - 1.0), TOL)

    def test_by_hand_with_levels_on_the_limits(self) -> None:
        """RF-018-31: un extremo superior justo en una cota va a la rodaja de abajo; los trozos de en medio son enteros; sin dato no cuenta."""
        start = np.array([[10.0, 10.0, 10.0, np.nan]])
        surface = np.array([[2.5, 0.0, 9.0, 0.0]])
        levels, volume = pit_surface.bench_volumes(start, surface, 2.0, 0.0, 5.0)
        self.assertEqual(levels.tolist(), [0.0, 5.0, 10.0])
        self.assertEqual(volume.tolist(), [15.0, 22.0])

    def test_no_cut_gives_nothing(self) -> None:
        levels, volume = pit_surface.bench_volumes(np.ones((2, 2)), np.ones((2, 2)), 1.0, 0.0, 5.0)
        self.assertEqual((len(levels), len(volume)), (0, 0))


class RampBreaklineTest(unittest.TestCase):
    def test_band_edges_are_constraints(self) -> None:
        """RF-018-28 y 21: el borde izquierdo, el eje y el borde derecho de una rampa son aristas obligatorias con su Z por estaciones."""
        grid = pd.grid_of(2.0)
        job = h1.up_job(grid)
        found = pit_bench.ascend(job)
        x = np.linspace(170.0, 230.0, 31)
        origin = np.asarray(pd.origin_of(grid))

        def line(y: float) -> np.ndarray:
            return np.column_stack([x + origin[0], np.full_like(x, y) + origin[1], 126.0 + (x - 170.0) * 4.0 / 60.0])

        ramp = SimpleNamespace(band=SimpleNamespace(breaklines=(line(205.0), line(201.0), line(197.0))))
        result = run(job, found, (ramp,))
        plain = run(job, found)
        row = int(round(grid.nrows - 201.0 / grid.dy - 0.5))
        centre = (np.arange(grid.ncols) + 0.5) * grid.dx
        chosen = (centre > 175.0) & (centre < 225.0)
        expected = 126.0 + (centre[chosen] - 170.0) * 4.0 / 60.0
        self.assertLess(float(np.abs(result.surface[row, chosen] - expected).max()), 1e-9)
        self.assertLess(result.cut_m3, plain.cut_m3)


class StepsTest(unittest.TestCase):
    def test_steps_end_with_the_same_surface(self) -> None:
        """RNF-018-06: por pasos sale lo mismo que de una vez, bit a bit."""
        job = h1.up_job(pd.grid_of(4.0))
        found = pit_bench.ascend(job)
        steps = list(pit_surface.rasterize_steps(job, found, crs=pd.CRS, vertical=pd.VERTICAL, budget_s=0.0))
        self.assertGreater(len(steps), 3)
        whole = run(job, found)
        self.assertTrue(np.array_equal(steps[-1].result.surface, whole.surface, equal_nan=True))
        self.assertEqual(steps[-1].result.cut_m3, whole.cut_m3)

    def test_closing_midway_leaves_nothing(self) -> None:
        """RF-018-35: cerrar el generador a mitad no deja nada ni toca las entradas."""
        job = h1.up_job(pd.grid_of(4.0))
        found = pit_bench.ascend(job)
        before = job.start.copy()
        steps = pit_surface.rasterize_steps(job, found, crs=pd.CRS, vertical=pd.VERTICAL, budget_s=0.0)
        next(steps)
        steps.close()
        self.assertTrue(np.array_equal(job.start, before, equal_nan=True))

    def test_needs_a_closed_polyline(self) -> None:
        with self.assertRaises(ValueError):
            run(h1.up_job(), [])


if __name__ == "__main__":
    unittest.main()
