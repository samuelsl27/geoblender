# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la superficie de la corta (spec 018, T18; RF-018-28 y 31; CE-018-03 y 11; D-11; P-10).

La corta circular de CE-018-03 con celdas de 2 y 1 m: el volumen de la rejilla contra los 961.661,57 m³ analíticos a ≤ 0,1 %, el volumen
por banco contra los troncos de cono a mano y contra el núcleo de la cubicación de la 011 (``reserves.kernel``, P-10) a ≤ 10⁻⁹ relativo."""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")
pit_surface = import_geoblender("design.pit_surface")
kernel = import_geoblender("reserves.kernel")
slices = import_geoblender("reserves.slices")


def surface_of(step_m: float) -> tuple[object, object]:
    job = h1.up_job(pd.grid_of(step_m))
    return job, pit_surface.rasterize(job, pit_bench.ascend(job), crs=pd.CRS, vertical=pd.VERTICAL)


class CircleSurfaceReferenceTest(unittest.TestCase):
    def test_volume_and_benches(self) -> None:
        """CE-018-03 y CE-018-11: el volumen a ≤ 0,1 %, cada rodaja su tronco de cono, y el reparto igual al de la 011 a ≤ 10⁻⁹."""
        exact = pd.circle_volume_by_hand()
        for step in (2.0, 1.0):
            with self.subTest(cell_m=step):
                job, found = surface_of(step)
                self.assertLess(abs(found.cut_m3 / exact - 1.0), 1e-3)
                accumulators = kernel.Accumulators(job.grid, slices=slices.Slices(job.height_m, job.anchor_m, None))
                kernel.band_step(accumulators, kernel.BandValues(0, job.start, found.surface))
                result = accumulators.result()
                self.assertAlmostEqual(found.cut_m3 / float(result.cut_m3[kernel.ALL]), 1.0, delta=1e-9)
                self.assertTrue(np.array_equal(found.bench_levels, result.bounds))
                self.assertLess(float(np.max(np.abs(found.bench_m3 - result.slice_cut_m3[kernel.ALL]))) / found.cut_m3, 1e-9)
                slack = len(found.bench_m3) - pd.BENCHES
                for k, (foot, crest) in enumerate(pd.circle_radii_by_hand()):
                    frustum = math.pi * 10.0 / 3.0 * (foot * foot + foot * crest + crest * crest)
                    self.assertLess(abs(found.bench_m3[slack + k] / frustum - 1.0), 1e-3)


if __name__ == "__main__":
    unittest.main()
