# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la corta por bancos (spec 018, T13, H1; RF-018-11, 12; CE-018-03, CE-018-04; D-11).

La fila de ``tests/referencia/des/`` del hito H1: la corta circular de CE-018-03 (volumen de las polilíneas del motor, rasterizadas con
celdas de 4 y 2 m, contra los 961.661,57 m³ analíticos a ≤ 0,1 %) y el límite cuadrado de CE-018-04 (lados de pie a mano y volumen con
celdas de 2 m a ≤ 0,1 %). Las celdas de 1 m y la batería rugosa, en ``tests/unit/design/milestone_pit_h1.py``."""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support import pit_raster as pr
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")


class CircleReferenceTest(unittest.TestCase):
    def test_volume_matches_the_analytic_one(self) -> None:
        """CE-018-03: 961.661,57 m³ a mano; el de las polilíneas con celdas de 4 y 2 m, a ≤ 0,1 % (D-11)."""
        exact = pd.circle_volume_by_hand()
        self.assertAlmostEqual(exact, 961661.57, delta=0.01)
        for step in (4.0, 2.0):
            with self.subTest(cell_m=step):
                grid = pd.grid_of(step)
                found = pit_bench.ascend(h1.up_job(grid))
                volume = pr.volume_m3(pr.circle_rings(found, grid), outer_first=False, grid=grid, terrain_m=pd.TOP_Z_M,
                                      floor_m=pd.FLOOR_Z_M, height_m=10.0, tan_face=math.tan(math.radians(60.0)))
                self.assertAlmostEqual(volume / exact, 1.0, delta=1e-3)


class LimitReferenceTest(unittest.TestCase):
    def test_sides_and_volume(self) -> None:
        """CE-018-04: lados de pie 180, 148, 116, 84 y 52 m a ≤ 10⁻⁶ m; volumen con celdas de 2 m a ≤ 0,1 % de los troncos de pirámide."""
        grid = pd.grid_of(2.0)
        found = pit_bench.descend(h1.down_job(grid))
        by_hand, _ = pd.limit_benches_by_hand()
        for k, bench in enumerate(by_hand):
            xy = pr.local_ring(h1.of_kind(found, "foot", k)[0], grid)
            self.assertAlmostEqual(float(max(np.ptp(xy[:, 0]), np.ptp(xy[:, 1]))), bench.foot_side_m, delta=1e-6)
        volume = pr.volume_m3(pr.square_rings(found, grid), outer_first=True, grid=grid, terrain_m=pd.LIMIT_TERRAIN_Z_M,
                              floor_m=pd.LIMIT_FLOOR_Z_M, height_m=10.0, tan_face=1.0)
        self.assertAlmostEqual(volume / pr.hand_square_volume_m3(), 1.0, delta=1e-3)


if __name__ == "__main__":
    unittest.main()
