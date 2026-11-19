# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de los acopios, con datos sintéticos y sin el banco (spec 016, T22; CE-016-08; RF-016-02).

``tests/banco/silvestre/test_stockpiles.py`` solo la ejecuta el arnés de los bancos con el banco real (``tools/check.py --banco``). Aquí, en el «verde», se
comprueba que se omite sin la variable (con la orden que la activa) y sus ayudas con un levantamiento **sintético** (un tronco de pirámide de 40 m de pie y
4 m de altura sobre un plano de 3°, como raster de espesor de 1 m y MDT de 0,5 m): las etiquetas del stock sin las astillas, llevarlas a otra rejilla,
crecerlas sin que dos marcas compartan celdas, las marcas con sus celdas en la rejilla entera y la detección con ellas (un acopio, convergido, con el volumen
del cálculo a mano a ≤ 5 %: la diferencia entre la rejilla de 1 m del stock y la de 0,5 m del MDT, el umbral y el borde).
"""

from __future__ import annotations

import contextlib
import io
import os
import types
import unittest
from unittest import mock

import numpy as np

from tests.banco.silvestre import test_stockpiles as bank
from tests.support import stockpile_data as sdata

MOUND = sdata.Mound("Montón", "pyramid", 60.0, 60.0, 20.0, 12.0, 4.0)
"""El tronco de pirámide sintético: pie de 20 m de semilado, cima de 12 m y 4 m de altura, sobre un plano de 3° (4.184 m³ en celdas de 1 m)."""


def raster(step_m: float, *, stock: bool) -> object:
    """El MDT (o, con ``stock``, el espesor) del montón sintético en la rejilla de ``step_m`` m (un objeto con ``grid`` y ``values``)."""
    grid = sdata.window_grid(step_m)
    heights = sdata.mound_heights(grid.shape, grid.dx, (MOUND,))
    values = np.where(heights > 0.0, heights, np.nan) if stock else sdata.plane(3.0).values(grid) + heights
    return types.SimpleNamespace(grid=grid, values=values)


class SkippedTest(unittest.TestCase):
    """CE-016-08: sin ``GEOBLENDER_SILVESTRE_DIR`` la comparación se omite con la orden que la activa."""

    def test_it_is_skipped_without_the_variable_and_says_how_to_run_it(self) -> None:
        """CE-016-08: sin la variable, ninguna prueba se ejecuta y la omisión dice ``OMITIDO: silvestre`` y ``tools/check.py --banco``."""
        environ = {key: value for key, value in os.environ.items() if key != bank.bank.ENV}
        suite = unittest.TestLoader().loadTestsFromTestCase(bank.StockpilesBankTest)
        result = unittest.TestResult()
        with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stderr(io.StringIO()):
            suite.run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 0)
        ((_, reason),) = result.skipped
        self.assertIn("OMITIDO: silvestre", reason)
        self.assertIn("tools/check.py --banco", reason)


class HelpersTest(unittest.TestCase):
    """CE-016-08, RF-016-02: las ayudas con el levantamiento sintético."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.stock, cls.dem = raster(1.0, stock=True), raster(0.5, stock=False)

    def test_the_labels_are_the_stockpiles_without_the_slivers(self) -> None:
        """Una etiqueta por componente conexa del stock; las de menos de ``skip_cells`` celdas (astillas) quedan en 0."""
        values = np.full((12, 12), np.nan)
        values[1:6, 1:6] = 2.0
        values[9:11, 9:11] = 0.4
        labels = bank.stock_labels(values, skip_cells=10)
        self.assertEqual(sorted(np.unique(labels).tolist()), [0, 1])
        self.assertEqual(int((labels == 1).sum()), 25)

    def test_the_labels_are_carried_to_the_other_grid_by_the_cell_that_contains_each_centre(self) -> None:
        """Las etiquetas de la rejilla de 1 m en la de 0,5 m: cada celda de 1 m son cuatro de 0,5 m (el área se conserva)."""
        labels = bank.stock_labels(self.stock.values)
        carried = bank.carry(labels, self.stock.grid, self.dem.grid)
        self.assertEqual(carried.shape, self.dem.grid.shape)
        self.assertEqual(int((carried > 0).sum()), 4 * int((labels > 0).sum()))

    def test_the_marks_grow_without_sharing_cells(self) -> None:
        """Dos acopios a 3 celdas uno de otro, crecidos 4 celdas, no comparten ninguna: las marcas son disjuntas y contienen su acopio."""
        labels = np.zeros((20, 40), dtype=np.int32)
        labels[5:10, 5:10] = 1
        labels[5:10, 13:18] = 2
        grown = bank.grow(labels, 4)
        self.assertTrue(np.all(grown[labels == 1] == 1) and np.all(grown[labels == 2] == 2))
        self.assertGreater(int((grown == 1).sum()), 25)
        marks = bank.marks_of(grown)
        self.assertEqual([mark.key for mark in marks], ["Acopio 1", "Acopio 2"])
        self.assertEqual(np.intersect1d(marks[0].cells, marks[1].cells).size, 0)
        self.assertEqual(int(marks[0].cells.size), int((grown == 1).sum()))

    def test_the_tolerance_names_what_is_outside(self) -> None:
        """S-4: la huella y el volumen se comparan por separado, a ≤ 1 %."""
        wanted = bank.Figures(1_000.0, 5_000.0)
        self.assertEqual(bank.outside(bank.Figures(1_009.0, 5_049.0), wanted), [])
        self.assertEqual(bank.outside(bank.Figures(1_011.0, 5_049.0), wanted), ["huella"])
        self.assertEqual(bank.outside(bank.Figures(1_000.0, 4_900.0), wanted), ["volumen"])
        self.assertAlmostEqual(bank.relative(103.0, 100.0), 0.03, places=12)

    def test_the_detection_with_the_derived_marks_finds_the_synthetic_stockpile(self) -> None:
        """RF-016-02: con la marca derivada del stock de 1 m, la detección sobre el MDT de 0,5 m da **un** acopio, sin rechazar nada, con el volumen y la
        huella del cálculo a mano (``Σ altura · área`` de las celdas de 0,5 m con más de 0,3 m) a ≤ 5 %."""
        wanted, found, rejected = bank.derive_and_detect(self.stock, self.dem)
        self.assertEqual((list(wanted), list(found), rejected), ([1], [1], []))
        grid = self.dem.grid
        heights = sdata.mound_heights(grid.shape, grid.dx, (MOUND,))
        volume = float(heights[heights > bank.THRESHOLD_M].sum()) * grid.dx * grid.dy
        self.assertLessEqual(abs(bank.relative(found[1].volume_m3, volume)), 0.05, (found[1], volume))
        area = float((heights > bank.THRESHOLD_M).sum()) * grid.dx * grid.dy
        self.assertLessEqual(abs(bank.relative(found[1].area_m2, area)), 0.05, (found[1], area))


if __name__ == "__main__":
    unittest.main()
