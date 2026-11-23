# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de las cifras y el contraste de la corta (spec 018, T20; RF-018-27 y 31; CE-018-11 y 12; D-11; P-10).

La corta circular de CE-018-03 con celdas de 2 y 1 m: el volumen por banco de las cifras igual al reparto del núcleo de la cubicación de la 011
(``reserves.kernel``) a ≤ 10⁻⁹ relativo y al tronco de cono a mano a ≤ 0,1 %, y el contraste con el escalonado de la 013 (mismo perfil, ancla y
semillas) a ≤ 1 % en volumen (CE-018-12, sintético: no necesita el banco de Silvestre)."""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")
pit_surface = import_geoblender("design.pit_surface")
pit_report = import_geoblender("design.pit_report")
pit_check013 = import_geoblender("design.pit_check013")
kernel = import_geoblender("reserves.kernel")
slices = import_geoblender("reserves.slices")

VOLUME_TOL = 1e-2
"""CE-018-12 (HIPÓTESIS, D-11): ≤ 1 % con celdas de ≤ 2 m."""


class CircleFiguresReferenceTest(unittest.TestCase):
    def test_bench_volumes_match_the_011_and_the_frusta(self) -> None:
        """CE-018-11: el volumen por banco de las cifras es el reparto de la 011 (≤ 10⁻⁹) y cada banco su tronco de cono (≤ 0,1 %)."""
        for step in (2.0, 1.0):
            with self.subTest(cell_m=step):
                job = h1.up_job(pd.grid_of(step))
                found = pit_bench.ascend(job)
                surface = pit_surface.rasterize(job, found, crs=pd.CRS, vertical=pd.VERTICAL)
                figures = pit_report.figures(job, found.polylines, surface, crs=pd.CRS, vertical=pd.VERTICAL)
                accumulators = kernel.Accumulators(job.grid, slices=slices.Slices(job.height_m, job.anchor_m, None))
                kernel.band_step(accumulators, kernel.BandValues(0, job.start, surface.surface))
                result = accumulators.result()
                self.assertAlmostEqual(sum(item.cut_m3 for item in figures.benches) / float(result.cut_m3[kernel.ALL]), 1.0, delta=1e-9)
                slack = len(result.slice_cut_m3[kernel.ALL]) - pd.BENCHES
                for item, (foot, crest) in zip(figures.benches, pd.circle_radii_by_hand(), strict=True):
                    self.assertAlmostEqual(item.cut_m3 / float(result.slice_cut_m3[kernel.ALL][slack + item.bench]), 1.0, delta=1e-9)
                    frustum = math.pi * 10.0 / 3.0 * (foot * foot + foot * crest + crest * crest)
                    self.assertLess(abs(item.cut_m3 / frustum - 1.0), 1e-3)
                self.assertEqual(figures.values["des.pit_cut_m3"], surface.cut_m3)


class ContrastWith013ReferenceTest(unittest.TestCase):
    def test_circle_against_the_013_stairs(self) -> None:
        """CE-018-12 (sintético): la corta circular y el escalonado en corte de la 013 con el mismo perfil y las mismas semillas difieren ≤ 1 % en
        volumen con celdas de 2 y 1 m; la diferencia de cota máxima es de pocas celdas y la inclinación máxima de celda es la de la cara (60°)."""
        for step in (2.0, 1.0):
            with self.subTest(cell_m=step):
                job = h1.up_job(pd.grid_of(step))
                surface = pit_surface.rasterize(job, pit_bench.ascend(job), crs=pd.CRS, vertical=pd.VERTICAL)
                found = pit_check013.contrast(job, surface)
                self.assertLess(abs(found.volume_diff_pct) / 100.0, VOLUME_TOL)
                self.assertLess(found.max_diff_m, 4.0 * step)
                self.assertAlmostEqual(found.max_deg, 60.0, delta=0.5)
                self.assertTrue(found.p90_deg <= found.p99_deg <= found.max_deg)
                self.assertTrue(np.isfinite(found.volume_013_m3))


if __name__ == "__main__":
    unittest.main()
