# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de la corta con datos sintéticos (spec 018, T38 y T38b; CE-018-12; DIFF-018l; RF-018-27; D-11).

``tests/banco/silvestre/test_pit.py`` solo lo ejecuta el arnés de los bancos con el banco real. Aquí se comprueba, en el «verde», que se omite sin la
variable y la comparación (``outside``, ``excavation_m3``, ``perimeter_of``) con arrays sintéticos, sin banco."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import unittest
from unittest import mock

import numpy as np

from tests.banco.silvestre import test_pit as bank
from tests.support import pit_data as pd
from tests.support.package import import_geoblender

grid_mod = import_geoblender("gis.grid")
design_model = import_geoblender("design.model")
EXPL = design_model.BenchProfile(**dataclasses.asdict(pd.EXPL))


class SkippedTest(unittest.TestCase):
    def test_it_is_skipped_without_the_variable_and_says_how_to_run_it(self) -> None:
        """CE-018-12: sin ``GEOBLENDER_SILVESTRE_DIR`` la comparación se omite con la orden que la activa."""
        environ = {key: value for key, value in os.environ.items() if key != bank.bank.ENV}
        suite = unittest.TestLoader().loadTestsFromTestCase(bank.ReferenceBankPitTest)
        result = unittest.TestResult()
        with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stderr(io.StringIO()):
            suite.run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 0)
        ((_, reason),) = result.skipped
        self.assertIn("OMITIDO: silvestre", reason)
        self.assertIn("tools/check.py --banco", reason)


class ComparisonTest(unittest.TestCase):
    def test_tolerance_is_the_one_of_d_11(self) -> None:
        """D-11 (HIPÓTESIS): ≤ 1 %; una comparación que no cierra (2 %) queda fuera y la que cierra (0,5 %) dentro."""
        self.assertEqual(bank.VOLUME_TOL, 1e-2)
        self.assertTrue(bank.outside(102.0, 100.0))
        self.assertTrue(bank.outside(98.0, 100.0))
        self.assertFalse(bank.outside(100.5, 100.0))
        self.assertTrue(bank.outside(1.0, 0.0))
        self.assertFalse(bank.outside(0.0, 0.0))

    def test_excavation_counts_only_what_goes_down_inside_the_area(self) -> None:
        """La excavación suma ``(partida − superficie) · área`` donde baja y dentro de la máscara; ignora lo que sube, el NaN y lo de fuera."""
        start = np.full((2, 3), 10.0)
        surface = np.array([[8.0, 12.0, np.nan], [9.0, 10.0, 5.0]])
        area = np.array([[True, True, True], [True, True, False]])
        self.assertEqual(bank.excavation_m3(start, surface, area, 4.0), (2.0 + 1.0) * 4.0)

    def test_perimeter_is_the_closed_contour_of_the_mask(self) -> None:
        """El perímetro de una máscara cuadrada de 10 × 10 celdas de 2 m es su contorno cerrado: unos 80 m de longitud (el contorno recorta las esquinas)."""
        grid = grid_mod.Grid(west=500_000.0, north=4_400_100.0, dx=2.0, dy=2.0, ncols=30, nrows=30)
        area = np.zeros(grid.shape, bool)
        area[10:20, 10:20] = True
        ring = bank.perimeter_of(area, grid, pd.CRS, pd.VERTICAL)
        closed = np.vstack([ring, ring[:1]])
        self.assertAlmostEqual(float(np.hypot(*np.diff(closed, axis=0).T).sum()), 80.0, delta=3.0)


class FloorsTest(unittest.TestCase):
    """DIFF-018l: los fondos de la referencia y la corta ascendente desde ellos, con una referencia sintética de dos fondos (sin banco)."""

    cell = 2.0

    def _two_floor_reference(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        grid = pd.GRID
        start = pd.flat_terrain(grid, 175.0)
        west = pd.circle_surface(grid, pd.EXPL, 25.0, 5, 175.0, 125.0, center=(100.0, 200.0))
        east = pd.circle_surface(grid, pd.EXPL, 25.0, 3, 175.0, 145.0, center=(300.0, 200.0))
        return start, np.minimum(west, east), np.ones(grid.shape, bool)

    def test_floors_are_the_plateaus_without_lower_ground_around_and_not_the_berms(self) -> None:
        """Dos cortas circulares a 125 y a 145 m: ``floors_of`` da exactamente sus dos fondos (sus cotas y su centro), no las bermas (que tienen su cara hacia dentro)."""
        start, reference, area = self._two_floor_reference()
        floors = bank.floors_of(reference, start, area, 125.0, 10.0, float(pd.GRID.cell_area))
        self.assertEqual(sorted(level for level, _ in floors), [125.0, 145.0])
        x, y = pd.local_centers(pd.GRID)
        for level, mask in floors:
            centre = 100.0 if level == 125.0 else 300.0
            self.assertAlmostEqual(float(x[mask].mean()), centre, delta=1.0)
            self.assertAlmostEqual(float(y[mask].mean()), 200.0, delta=1.0)

    def test_a_pit_rebuilt_from_its_own_floors_matches_the_reference_within_one_percent(self) -> None:
        """Ida y vuelta (D-11): la corta ascendente desde los dos fondos detectados, con el perfil de la referencia, excava lo de la referencia a ≤ 1 %."""
        start, reference, area = self._two_floor_reference()
        grid = pd.GRID
        floors = bank.floors_of(reference, start, area, 125.0, 10.0, float(grid.cell_area))
        surface = bank.pit_surface_from_floors(floors, start, grid, pd.CRS, pd.VERTICAL, EXPL)
        found = bank.excavation_m3(start, surface, area, float(grid.cell_area))
        expected = bank.excavation_m3(start, reference, area, float(grid.cell_area))
        self.assertGreater(expected, 0.0)
        self.assertFalse(bank.outside(found, expected), f"{found} frente a {expected}")

    def test_without_a_floor_there_are_none(self) -> None:
        """Un terreno sin excavar no tiene fondos; una referencia sin meseta a una cota de la retícula, tampoco."""
        grid = pd.GRID
        start = pd.flat_terrain(grid, 175.0)
        area = np.ones(grid.shape, bool)
        self.assertEqual(bank.floors_of(start.copy(), start, area, 125.0, 10.0, float(grid.cell_area)), [])
        x, _ = pd.local_centers(grid)
        slope = start - np.clip((x - 100.0) * 0.1, 0.0, 30.0)
        self.assertEqual(bank.floors_of(slope, start, area, 125.0, 10.0, float(grid.cell_area)), [])


if __name__ == "__main__":
    unittest.main()
