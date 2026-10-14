# SPDX-License-Identifier: GPL-3.0-or-later
"""Muestreo de una superficie en rejilla en puntos sueltos (spec 006, T52; plan 006 §5.3.2:
``gis.raster.sample``, el contrato para la 005, DH-W05: la cota de boca frente al MDT).

- **RF-006-11** (la bilineal y su regla de vecinos): ``sample(raster, xy)`` interpola entre
  los cuatro centros vecinos con la misma bilineal que ``resample_to_grid`` (es la misma
  función: los centros de una rejilla dan sus cotas bit a bit); un plano sale exacto, un
  punto en un centro toma su cota bit a bit y el punto al que le falta un vecino de peso no
  nulo (fuera de los centros, sin dato, ±∞, o una coordenada que no es finita) es NaN.
- ``method="nearest"``: la cota de la celda que contiene el punto (la extensión de la rejilla,
  con sus bordes); fuera o sin dato, NaN.
- Un método que no es de muestreo, unas coordenadas que no son (…, 2) o una superficie que no
  es un ``Raster`` son errores del programa (``ValueError``, ``TypeError``), con el valor
  recibido y lo que se admite. Las entradas no se modifican.

Coordenadas ABSOLUTAS (EPSG:25830) en float64, rejilla pequeña con celdas de 2 × 1 m.
"""

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
raster_mod = import_geoblender("gis.raster")
resample = import_geoblender("gis.resample")
georef = import_geoblender("core.georef")

NAN = math.nan
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
WEST, NORTH = 700_000.0, 4_400_003.0
GRID = gis.Grid(west=WEST, north=NORTH, dx=2.0, dy=1.0, ncols=4, nrows=3)
# Centros: X 700 001, 700 003, 700 005, 700 007; Y 4 400 002,5, 4 400 001,5, 4 400 000,5.


def _plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 800.0 + 0.5 * (x - WEST) - 0.25 * (y - 4_400_000.0)


def _raster(values: np.ndarray) -> object:
    array = np.array(values, dtype=np.float64)
    array.flags.writeable = False  # una entrada nunca se modifica
    return gis.Raster(GRID, array, CRS, VERTICAL)


def _plane_raster() -> object:
    return _raster(_plane(*GRID.centers()))


def _points(*xy: tuple[float, float]) -> np.ndarray:
    array = np.array(xy, dtype=np.float64)
    array.flags.writeable = False
    return array


ODD = np.array([[811.25, 812.5, 809.75, 810.0],
                [813.0, 815.5, NAN, 808.25],
                [np.inf, 812.75, 811.0, 809.5]])
"""Cotas sin forma: la celda (1, 2) sin dato y la (2, 0) con +∞ (sin dato también)."""


class BilinearTest(unittest.TestCase):
    def test_plane_is_exact_and_centres_keep_their_heights(self) -> None:
        """RF-006-11: un plano sale exacto (≤ 10⁻⁹ m) en cualquier punto entre los centros,
        y un punto en un centro toma su cota bit a bit; la forma del resultado es la de
        ``xy`` sin su última dimensión, en float64."""
        surface = _plane_raster()
        x, y = GRID.centers()
        centres = np.column_stack([x.ravel(), y.ravel()])
        got = raster_mod.sample(surface, centres)
        self.assertEqual((got.shape, got.dtype), ((12,), np.float64))
        self.assertTrue(np.array_equal(got.view(np.uint64),
                                       surface.values.ravel().view(np.uint64)))
        inner = _points((700_002.0, 4_400_002.0), (700_006.5, 4_400_000.75),
                        (700_001.0, 4_400_001.25), (700_004.125, 4_400_002.5),
                        (700_007.0, 4_400_000.5))
        expected = _plane(inner[:, 0], inner[:, 1])
        np.testing.assert_allclose(raster_mod.sample(surface, inner), expected, rtol=0,
                                   atol=1e-9)
        np.testing.assert_allclose(raster_mod.sample(surface, inner, method="bilinear"),
                                   expected, rtol=0, atol=1e-9)
        single = raster_mod.sample(surface, np.array([700_002.0, 4_400_002.0]))
        self.assertEqual(single.shape, ())
        self.assertAlmostEqual(float(single), 800.5, delta=1e-9)

    def test_known_values_between_four_centres(self) -> None:
        """RF-006-11: en el punto medio de cuatro centros, la media de sus cuatro cotas; a
        un cuarto de paso de un centro en X, ¾ de su cota y ¼ de la del vecino."""
        surface = _raster(ODD)
        got = raster_mod.sample(surface, _points((700_002.0, 4_400_002.0),
                                                 (700_001.5, 4_400_002.5)))
        np.testing.assert_allclose(got, [(811.25 + 812.5 + 813.0 + 815.5) / 4,
                                         0.75 * 811.25 + 0.25 * 812.5], rtol=0, atol=1e-9)

    def test_missing_neighbour_outside_or_not_finite_is_nan(self) -> None:
        """RF-006-11: NaN si al punto le falta un vecino de peso no nulo: sin dato (NaN o
        ±∞), fuera de la rejilla, dentro de ella pero fuera de los centros (el medio paso
        del borde) o con una coordenada que no es finita; un vecino sin dato de peso nulo
        no estorba (un punto sobre la línea de dos centros con dato, o en un centro)."""
        surface = _raster(ODD)
        nan_points = _points(
            (700_004.0, 4_400_002.0),   # su vecino (1, 2) no tiene dato
            (700_002.0, 4_400_001.0),   # su vecino (2, 0) es +∞
            (699_999.0, 4_400_002.0),   # al oeste de la rejilla
            (700_004.0, 4_400_003.5),   # al norte
            (700_000.5, 4_400_002.0),   # en la rejilla, al oeste del primer centro
            (700_004.0, 4_400_000.25),  # en la rejilla, al sur del último centro
            (NAN, 4_400_002.0),
            (700_004.0, np.inf),
            (-np.inf, NAN),
            (1e300, -1e300),
        )
        got = raster_mod.sample(surface, nan_points)
        self.assertTrue(np.isnan(got).all(), got)
        kept = raster_mod.sample(surface, _points((700_004.0, 4_400_002.5),
                                                  (700_003.0, 4_400_001.5),
                                                  (700_007.0, 4_400_001.5)))
        np.testing.assert_allclose(kept, [(812.5 + 809.75) / 2, 815.5, 808.25], rtol=0,
                                   atol=1e-9)

    def test_same_bilinear_as_the_project_grid(self) -> None:
        """RF-006-11: muestrear en los centros de una rejilla da, bit a bit, las cotas que
        ``resample_to_grid`` calcula con la bilineal en esa rejilla (la misma función, sin
        un segundo algoritmo), con NaN en las mismas celdas."""
        surface = _raster(ODD)
        target = gis.Grid(west=WEST, north=NORTH, dx=0.5, dy=0.5, ncols=16, nrows=6)
        grid, _report = gis.resample_to_grid(surface, target, method="bilinear")
        x, y = target.centers()
        got = raster_mod.sample(surface, np.stack([x, y], axis=-1))
        self.assertEqual(got.shape, target.shape)
        nan = np.isnan(grid.values)
        self.assertTrue(nan.any() and not nan.all())
        np.testing.assert_array_equal(np.isnan(got), nan)
        self.assertTrue(np.array_equal(got[~nan].view(np.uint64),
                                       grid.values[~nan].view(np.uint64)))


class NearestTest(unittest.TestCase):
    def test_cell_that_contains_the_point(self) -> None:
        """La cota de la celda que contiene el punto, también en el medio paso del borde
        (donde la bilineal no llega) y en los bordes exteriores; en un borde interior, la
        celda del este o la del sur; sin dato (NaN o ±∞) o fuera de la rejilla, NaN."""
        surface = _raster(ODD)
        points = _points(
            (700_000.5, 4_400_002.9),   # (0, 0)
            (700_000.0, 4_400_003.0),   # esquina noroeste: (0, 0)
            (700_008.0, 4_400_000.0),   # esquina sureste: (2, 3)
            (700_002.0, 4_400_002.0),   # bordes interiores: (1, 1)
            (700_007.9, 4_400_001.2),   # (1, 3)
            (700_005.0, 4_400_001.5),   # (1, 2) sin dato
            (700_001.0, 4_400_000.5),   # (2, 0) +∞
            (700_008.001, 4_400_001.0),  # al este
            (700_004.0, 4_399_999.999),  # al sur
            (NAN, 4_400_001.0),
        )
        got = raster_mod.sample(surface, points, method="nearest")
        expected = [811.25, 811.25, 809.5, 815.5, 808.25, NAN, NAN, NAN, NAN, NAN]
        np.testing.assert_array_equal(got, expected)


class ErrorsTest(unittest.TestCase):
    def test_unsupported_method_and_bad_arguments(self) -> None:
        """Un método que no es de muestreo es ``ValueError`` con el método recibido y los
        admitidos; unas coordenadas sin X e Y en su última dimensión, ``ValueError`` con su
        forma; una superficie que no es un ``Raster``, ``TypeError``."""
        surface = _plane_raster()
        xy = _points((700_002.0, 4_400_002.0))
        for method in ("cubic", "area_mean", "", None):
            with self.subTest(metodo=method), self.assertRaises(ValueError) as caught:
                raster_mod.sample(surface, xy, method=method)
            self.assertIn(repr(method), str(caught.exception))
            self.assertIn("«bilinear»", str(caught.exception))
            self.assertIn("«nearest»", str(caught.exception))
        for bad in (np.zeros((2, 3)), np.zeros(3), np.float64(700_000.0)):
            with self.subTest(forma=np.shape(bad)), self.assertRaises(ValueError) as caught:
                raster_mod.sample(surface, bad)
            self.assertIn(str(np.shape(bad)), str(caught.exception))
        with self.assertRaises(TypeError):
            raster_mod.sample(surface.values, xy)

    def test_inputs_are_not_modified(self) -> None:
        """Las coordenadas y las cotas de entrada no cambian (son de solo lectura: escribir
        en ellas lanzaría), y el resultado es un array nuevo."""
        surface = _raster(ODD)
        xy = _points((700_002.0, 4_400_002.0), (700_000.5, 4_400_002.0))
        before = (xy.copy(), surface.values.copy())
        for method in ("bilinear", "nearest"):
            with self.subTest(metodo=method):
                got = raster_mod.sample(surface, xy, method=method)
                got[...] = 0.0  # el resultado se puede escribir: no es una vista
                np.testing.assert_array_equal(xy, before[0])
                np.testing.assert_array_equal(surface.values, before[1])


if __name__ == "__main__":
    unittest.main()
