# SPDX-License-Identifier: GPL-3.0-or-later
"""Dónde caen las celdas con dato de un MDT: fuera de la ventana de trabajo o a más de 8 km del
GeoOrigin (spec 006, T51; §8 «MDT que sale de la ventana de trabajo o a más de 8 km del
GeoOrigin»; RF-006-08, RF-006-11, RF-002-26).

- ``data_extent(grid, valid)``: la extensión (bordes de celda) de las celdas con dato, sin las
  filas y columnas del borde que no tienen ninguna; ``None`` si no hay ninguna.
- ``cells_precision(grid, valid, origin)``: el informe de ``core.georef.precision_report``
  (RF-002-26: cuántos puntos pasan de 8 000 m del GeoOrigin en X o en Y y el error máximo
  estimado en mm) de los **centros de las celdas con dato**, el mismo, campo a campo, que
  ``precision_report`` sobre esos centros, sin construirlos todos (un MDT de 100 M celdas).
- ``extent_in(extent, transform)``: esa extensión en el CRS del proyecto (la caja de sus
  esquinas y de los puntos medios de sus lados transformados); sin transformación, la misma; si
  la transformación no da un punto finito, ``None``.
- ``outside_window(extent, window)``: si sale de la ventana por algún lado (más de 1 µm); un
  borde sobre el de la ventana no sale.

Las entradas no se modifican. Coordenadas ABSOLUTAS (EPSG:25830) en float64.
"""

import itertools
import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

placement = import_geoblender("gis.placement")
gis = import_geoblender("gis")
georef = import_geoblender("core.georef")

ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)
WINDOW = georef.Window(699_990.0, 4_399_990.0, 700_040.0, 4_400_030.0)


def _valid(nrows: int, ncols: int, *, holes: tuple[tuple[int, int], ...] = ()) -> np.ndarray:
    valid = np.ones((nrows, ncols), dtype=bool)
    for row, col in holes:
        valid[row, col] = False
    valid.flags.writeable = False
    return valid


def _brute(grid: object, valid: np.ndarray, origin: object) -> object:
    """``core.georef.precision_report`` sobre los centros de las celdas con dato."""
    xx, yy = grid.centers()
    points = np.column_stack([xx[valid], yy[valid]])
    return georef.precision_report(points, origin)


class _Shift:
    """Una transformación de prueba: traslada (y, con ``broken``, da ∞ en un punto)."""

    def __init__(self, dx: float, dy: float, *, broken: bool = False) -> None:
        self.info = None
        self.offset = np.array([dx, dy, 0.0])
        self.broken = broken
        self.seen: list[np.ndarray] = []

    def apply(self, xyz: np.ndarray) -> np.ndarray:
        self.seen.append(np.array(xyz))
        moved = np.asarray(xyz, dtype=np.float64) + self.offset
        if self.broken:
            moved[0, 0] = math.inf
        return moved


class DataExtentTest(unittest.TestCase):
    def test_extent_of_the_cells_with_data(self) -> None:
        """RF-006-08, §8: la extensión de un MDT es la de sus celdas con dato: las filas y las
        columnas del borde sin ninguna no cuentan, un hueco interior no la cambia y, sin
        ninguna celda con dato, no hay extensión."""
        grid = gis.Grid(west=700_020.0, north=4_400_050.0, dx=1.0, dy=0.5, ncols=6, nrows=5)
        self.assertEqual(placement.data_extent(grid, _valid(5, 6, holes=((2, 3),))),
                         grid.extent)
        valid = np.zeros((5, 6), dtype=bool)
        valid[1:4, 2:5] = True
        valid[2, 3] = False
        self.assertEqual(placement.data_extent(grid, valid),
                         georef.Window(700_022.0, 4_400_048.0, 700_025.0, 4_400_049.5))
        self.assertIsNone(placement.data_extent(grid, np.zeros((5, 6), dtype=bool)))
        with self.assertRaises(ValueError):
            placement.data_extent(grid, np.ones((6, 5), dtype=bool))


class CellsPrecisionTest(unittest.TestCase):
    def test_same_report_as_precision_report_on_the_centres(self) -> None:
        """RF-002-26: el informe de los centros de las celdas con dato es el de
        ``core.georef.precision_report`` sobre esos centros, campo a campo: dentro de ±8 km,
        sin aviso; a 9 km al este (los 100 centros), «100 puntos» y 0,488 mm; cruzando el
        límite al norte y al oeste, solo los que pasan (sin contar los sin dato, también en
        una esquina que pasa en X y en Y a la vez); al sur, a 16,4 km, 0,977 mm. Una rejilla sin
        ninguna celda con dato, sin aviso."""
        cases = {
            "dentro": (gis.Grid(700_020.0, 4_400_050.0, 1.0, 1.0, 40, 40), ()),
            "a 9 km": (gis.Grid(709_000.0, 4_400_020.0, 1.0, 1.0, 10, 10), ()),
            "cruza al norte": (gis.Grid(699_995.0, 4_408_003.0, 1.0, 1.5, 4, 6),
                               ((0, 0), (1, 3), (5, 2))),
            "esquina": (gis.Grid(691_998.0, 4_408_002.0, 0.5, 0.5, 8, 8),
                        ((0, 0), (0, 7), (3, 3), (7, 0))),
            "a 16,4 km": (gis.Grid(700_100.0, 4_383_600.0, 2.0, 2.0, 5, 3), ((1, 1),)),
        }
        for label, (grid, holes) in cases.items():
            with self.subTest(caso=label):
                valid = _valid(grid.nrows, grid.ncols, holes=holes)
                got = placement.cells_precision(grid, valid, ORIGIN)
                self.assertEqual(got, _brute(grid, valid, ORIGIN))
        far = placement.cells_precision(cases["a 9 km"][0], _valid(10, 10), ORIGIN)
        self.assertEqual((far.points_outside, far.max_abs_local_m), (100, 9_009.5))
        self.assertIn("100 puntos están a más de 8", far.message)
        self.assertIn("0,488 mm", far.message)
        self.assertTrue(placement.cells_precision(cases["dentro"][0], _valid(40, 40),
                                                  ORIGIN).within_limit)
        south = placement.cells_precision(cases["a 16,4 km"][0], _valid(3, 5), ORIGIN)
        self.assertIn("0,977 mm", south.message)
        grid = cases["esquina"][0]
        empty = placement.cells_precision(grid, np.zeros(grid.shape, dtype=bool), ORIGIN)
        self.assertEqual(empty, _brute(grid, np.zeros(grid.shape, dtype=bool), ORIGIN))
        self.assertTrue(empty.within_limit)

    def test_every_split_of_far_rows_and_columns(self) -> None:
        """RF-002-26: con las celdas sin dato en cualquier sitio (todas las máscaras de una
        rejilla de 3 × 3 que cruza el límite en X y en Y), la cuenta y el máximo son los de
        ``precision_report``."""
        grid = gis.Grid(707_998.5, 4_408_001.5, 1.0, 1.0, 3, 3)  # centros a 7 999 y 8 001 m
        for bits in itertools.product((False, True), repeat=9):
            valid = np.array(bits, dtype=bool).reshape(3, 3)
            with self.subTest(máscara=bits):
                self.assertEqual(placement.cells_precision(grid, valid, ORIGIN),
                                 _brute(grid, valid, ORIGIN))


class WindowTest(unittest.TestCase):
    def test_extent_in_the_project_crs(self) -> None:
        """RF-006-05, §8: sin transformación, la extensión es la misma; con una (otro CRS), la
        caja de sus esquinas y de los puntos medios de sus lados transformados (en float64, con
        la Z a 0); si alguno no sale finito (fuera de la rejilla del IGN), no hay extensión."""
        extent = georef.Window(700_000.0, 4_400_000.0, 700_064.0, 4_400_048.0)
        self.assertIs(placement.extent_in(extent, None), extent)
        shift = _Shift(-110.0, -207.0)
        self.assertEqual(placement.extent_in(extent, shift),
                         georef.Window(699_890.0, 4_399_793.0, 699_954.0, 4_399_841.0))
        (sent,) = shift.seen
        self.assertEqual(sent.shape, (8, 3))
        self.assertEqual(sent.dtype, np.float64)
        self.assertTrue((sent[:, 2] == 0.0).all())
        self.assertIsNone(placement.extent_in(extent, _Shift(0.0, 0.0, broken=True)))

    def test_outside_the_window(self) -> None:
        """RF-006-11, §8: sale de la ventana el MDT que pasa de ella por algún lado (más de
        1 µm); el que cabe, o tiene un borde justo sobre el de la ventana, no."""
        inside = (georef.Window(700_000.0, 4_400_000.0, 700_010.0, 4_400_010.0),
                  WINDOW, georef.Window(699_989.9999999, 4_399_990.0, 700_040.0, 4_400_030.0000001))
        for extent in inside:
            with self.subTest(extensión=extent):
                self.assertFalse(placement.outside_window(extent, WINDOW))
        outside = (georef.Window(700_020.0, 4_400_010.0, 700_060.0, 4_400_050.0),
                   georef.Window(709_000.0, 4_400_010.0, 709_010.0, 4_400_020.0),
                   georef.Window(699_989.99, 4_399_995.0, 700_000.0, 4_400_000.0),
                   georef.Window(700_000.0, 4_399_989.99, 700_010.0, 4_400_000.0),
                   georef.Window(700_000.0, 4_400_000.0, 700_040.01, 4_400_010.0),
                   georef.Window(700_000.0, 4_400_000.0, 700_010.0, 4_400_030.01))
        for extent in outside:
            with self.subTest(extensión=extent):
                self.assertTrue(placement.outside_window(extent, WINDOW))


if __name__ == "__main__":
    unittest.main()
