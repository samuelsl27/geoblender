# SPDX-License-Identifier: GPL-3.0-or-later
"""La parte pesada de los datos de prueba de la corta por bancos (spec 018, T01; plan 018 §7.1, §7.3 y §7.4; CE-018-03;
RF-018-28, RF-018-31; RNF-018-10).

Va al paso «hito» (P-16; ``milestone_*.py`` no lo descubre el «verde»): el proyecto con los tres terrenos (se crea una vez
por proceso y paso de rejilla, en ≤ 2 s de CPU), la rejilla de 1 m de CE-018-03 (160.000 celdas) y las cortas de escala
de 40 y 60 bancos con 160.000 vértices. Lo que cabe en mallas de ≤ 200 × 200 está en ``test_pit_fixtures.py``.
"""

from __future__ import annotations

import math
import time
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

gis_store = import_geoblender("gis.store")

COPY_BUDGET_S = 1.0
"""Una copia del proyecto por clase, en menos de 1 s de CPU."""
BUILD_BUDGET_S = 2.0
"""Cada forma de ``pit_data`` se construye en ≤ 2 s por clase (T01)."""


class PitProjectTest(pd.PitProjectCase):
    """El proyecto de la cantera de la 015 con los terrenos de la corta, en la rejilla gruesa de 2 m."""

    def test_built_once_within_budget(self) -> None:
        """La plantilla se crea una vez por proceso y paso en ≤ 2 s de CPU y cada clase la copia en menos de 1 s."""
        template = pd.project_template(qfx.COARSE_STEP_M)
        self.assertIs(template, pd.project_template(qfx.COARSE_STEP_M))
        self.assertLessEqual(template["build_s"], pd.BUILD_BUDGET_S)
        started = time.process_time()
        with pd.open_pit_project(step_m=qfx.COARSE_STEP_M) as (_project, _clock):
            elapsed = time.process_time() - started
        self.assertLess(elapsed, COPY_BUDGET_S)

    def test_the_015_project_is_still_there(self) -> None:
        """Lo de la cantera y de la 015 sigue igual: V01 y V02, la rejilla gruesa y el terreno de partida."""
        self.assertEqual((self.v1.code, self.v2.code), ("V01", "V02"))
        self.assertEqual(self.grid, qfx.grid_of(qfx.COARSE_STEP_M))
        raster = gis_store.load_raster(self.project, qfx.START_DATASET)
        np.testing.assert_array_equal(raster.values, qfx.terrain(self.grid))

    def test_rasters_read_back(self) -> None:
        """Cada terreno, escrito como rejilla del proyecto, vuelve igual bit a bit a lo que dan las funciones del módulo."""
        for label, make in pd.RASTERS.items():
            name = pd.dataset_of(label)
            self.assertIsNotNone(self.record(name), name)
            raster = gis_store.load_raster(self.project, name)
            self.assertEqual(raster.grid, self.grid, name)
            self.assertEqual((raster.crs.epsg, raster.vertical.epsg), (25830, 5782))
            np.testing.assert_array_equal(raster.values, make(self.grid), name)


class FineGridTest(unittest.TestCase):
    """CE-018-03 con celdas de 1 m (D-11)."""

    def test_circle_volume_on_the_1m_grid(self) -> None:
        """La superficie analítica muestreada en celdas de 1 m da el volumen a ≤ 0,1 % del analítico, construida en ≤ 2 s."""
        started = time.process_time()
        grid = pd.grid_of(1.0)
        cut = pd.flat_terrain(grid) - pd.circle_surface(grid)
        self.assertLessEqual(time.process_time() - started, BUILD_BUDGET_S)
        volume = float(cut.sum())
        self.assertLessEqual(abs(volume / pd.circle_volume_by_hand() - 1.0), 1e-3)

    def test_inclined_terrain_cuts_the_circle_at_different_benches(self) -> None:
        """CE-018-07: en el terreno inclinado el borde oeste está a 130 + 0,1·97 = 139,7 m (la cresta del banco 2, a 145 m, es la primera por encima)
        y el este a 160,3 m (la del banco 4, a 165 m): la corta sale a superficie en bancos distintos por lado (aproximado con el radio de la quinta cresta)."""
        grid = pd.grid_of(1.0)
        terrain = pd.inclined_terrain(grid)
        outer = pd.circle_radii_by_hand()[-1][1]
        west = 130.0 + 0.1 * (200.0 - outer)
        east = 130.0 + 0.1 * (200.0 + outer)
        self.assertAlmostEqual(west, 139.713, places=2)
        self.assertAlmostEqual(east, 160.287, places=2)
        exit_bench = [next(k for k in range(1, 20) if pd.FLOOR_Z_M + 10.0 * k >= z) for z in (west, east)]
        self.assertEqual(exit_bench, [2, 4])  # la cresta del banco k está a 125 + 10·k m
        self.assertAlmostEqual(float(terrain[0, 0]), 130.05, places=9)


class ScaleBuildTest(unittest.TestCase):
    """La escala de plan §7.3: se construye una vez, en ≤ 2 s, con ≈ 160.000 vértices."""

    def test_the_scale_rings(self) -> None:
        for benches in pd.SCALE_BENCH_COUNTS:
            started = time.process_time()
            rings = pd.scale_rings(benches)
            self.assertLessEqual(time.process_time() - started, BUILD_BUDGET_S)
            self.assertEqual(rings.shape[0], 2 * benches)
            self.assertLessEqual(rings.shape[0] * rings.shape[1], pd.SCALE_VERTICES)
            self.assertGreater(rings.shape[0] * rings.shape[1], pd.SCALE_VERTICES - 2 * benches)
            outer = pd.circle_radii_by_hand(radius_m=100.0, benches=benches)[-1][1]
            self.assertLess(outer, 827.0)
            self.assertTrue(math.isfinite(float(rings.sum())))


if __name__ == "__main__":
    unittest.main()
