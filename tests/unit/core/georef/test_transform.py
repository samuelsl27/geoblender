# SPDX-License-Identifier: GPL-3.0-or-later
"""Conversión absoluta ↔ local y aviso de precisión (spec 002, T04; RF-002-25,
RF-002-26; ADR-0005).

Blender guarda en float32: con nortes UTM de 4,4 Mm la resolución es de 0,5 m. Por eso
las coordenadas absolutas se restan del GeoOrigin en float64 (``world_to_local``) antes
de pasar a float32, y ``world_to_local`` rechaza absolutas que ya llegan en float32 (la
clase de error de Silvestre N-03). La ida y vuelta de 10⁶ puntos con la cifra de error
está en ``tests/referencia/core/test_georef_reference.py``.
"""

import unittest

import numpy as np

from tests.support.package import import_geoblender

georef = import_geoblender("core.georef")
transform = import_geoblender("core.georef.transform")
ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)


class WorldToLocalTest(unittest.TestCase):
    def test_values(self) -> None:
        """RF-002-25: local = absoluta − (X0, Y0, Z0) en float64, con 3 o 2 columnas o un
        solo punto; la entrada no cambia."""
        origin = georef.GeoOrigin(700_000, 4_400_000, 100)
        world = np.array([[700_100.5, 4_400_200.25, 850.0], [699_000.0, 4_399_000.0, 0.0]])
        before = world.copy()
        local = georef.world_to_local(world, origin)
        self.assertEqual(local.dtype, np.float64)
        np.testing.assert_array_equal(
            local, [[100.5, 200.25, 750.0], [-1_000.0, -1_000.0, -100.0]]
        )
        np.testing.assert_array_equal(world, before)
        flat = georef.world_to_local(np.array([[700_100.5, 4_400_200.25]]), origin)
        np.testing.assert_array_equal(flat, [[100.5, 200.25]])
        single = georef.world_to_local(np.array([700_001.0, 4_400_002.0, 103.0]), origin)
        np.testing.assert_array_equal(single, [1.0, 2.0, 3.0])
        ints = georef.world_to_local(np.array([[700_001, 4_400_002, 103]]), origin)
        self.assertEqual(ints.dtype, np.float64)

    def test_float32_absolute_rejected(self) -> None:
        """RF-002-25: un array absoluto en float32 da ``TypeError`` (ya perdió hasta
        0,25 m en Y); también otros tipos que no son float64 ni enteros."""
        for dtype in (np.float32, np.float16, np.complex128, object):
            with self.subTest(dtype=dtype):
                with self.assertRaises(TypeError) as caught:
                    georef.world_to_local(np.zeros((2, 3), dtype=dtype), ORIGIN)
                self.assertIn("float64", str(caught.exception))

    def test_bad_shape(self) -> None:
        """RF-002-25: la última dimensión debe ser 2 (X, Y) o 3 (X, Y, Z)."""
        for shape in ((4, 4), (4, 1), (0,), ()):
            with self.subTest(shape=shape):
                with self.assertRaises(ValueError):
                    georef.world_to_local(np.zeros(shape), ORIGIN)


class LocalToWorldTest(unittest.TestCase):
    def test_values_and_dtype(self) -> None:
        """RF-002-25: absoluta = local + (X0, Y0, Z0), siempre en float64; admite
        locales en float32 (lo que devuelve Blender)."""
        origin = georef.GeoOrigin(700_000, 4_400_000, -180)
        local32 = np.array([[100.5, 200.25, 1_030.0]], dtype=np.float32)
        world = georef.local_to_world(local32, origin)
        self.assertEqual(world.dtype, np.float64)
        np.testing.assert_array_equal(world, [[700_100.5, 4_400_200.25, 850.0]])
        flat = georef.local_to_world(np.array([[1.0, 2.0]]), origin)
        np.testing.assert_array_equal(flat, [[700_001.0, 4_400_002.0]])

    def test_round_trip_small_sample(self) -> None:
        """RF-002-25: ida y vuelta por float32 de 10⁴ puntos a ±8 km (semilla fija):
        error ≤ 0,5 mm; y sin pasar por float32, exacta."""
        rng = np.random.default_rng(20261005)
        n = 10_000
        world = np.column_stack(
            [
                700_000 + rng.uniform(-8_000, 8_000, n),
                4_400_000 + rng.uniform(-8_000, 8_000, n),
                rng.uniform(0, 4_000, n),
            ]
        )
        local = georef.world_to_local(world, ORIGIN)
        np.testing.assert_array_equal(georef.local_to_world(local, ORIGIN), world)
        back = georef.local_to_world(local.astype(np.float32), ORIGIN)
        self.assertLessEqual(float(np.abs(back - world).max()), 0.0005)


class PrecisionReportTest(unittest.TestCase):
    def test_estimated_error(self) -> None:
        """RF-002-26: error estimado de float32 para |local| = m: 2^(⌊log2 m⌋ − 24) m,
        0,244 mm a 8 km, 0,488 mm a 16 km y 0,977 mm a 20 km; 0 en el origen."""
        self.assertAlmostEqual(transform.float32_error_mm(8_000.0), 0.244140625)
        self.assertAlmostEqual(transform.float32_error_mm(16_000.0), 0.48828125)
        self.assertAlmostEqual(transform.float32_error_mm(20_000.0), 0.9765625)
        self.assertEqual(transform.float32_error_mm(0.0), 0.0)
        self.assertAlmostEqual(transform.float32_error_mm(-20_000.0), 0.9765625)

    def test_points_within_limit(self) -> None:
        """RF-002-26: puntos a menos de 8 000 m del GeoOrigin en X y en Y: sin aviso."""
        world = np.array([[707_999.0, 4_392_001.0, 4_000.0], [700_000.0, 4_400_000.0, 0.0]])
        report = georef.precision_report(world, ORIGIN)
        self.assertTrue(report.within_limit)
        self.assertEqual(report.points_outside, 0)
        self.assertEqual(report.corners_outside, ())
        self.assertLessEqual(report.max_error_mm, 0.25)
        self.assertEqual(report.message, "")

    def test_points_at_20_km(self) -> None:
        """RF-002-26: con puntos a 20 km se informa del número de puntos y de 0,977 mm."""
        world = np.array(
            [
                [720_000.0, 4_400_000.0, 0.0],
                [700_000.0, 4_380_000.0, 0.0],
                [700_500.0, 4_400_500.0, 0.0],
                [712_000.0, 4_400_000.0, 0.0],
            ]
        )
        report = georef.precision_report(world, ORIGIN)
        self.assertFalse(report.within_limit)
        self.assertEqual(report.points_outside, 3)
        self.assertEqual(report.max_abs_local_m, 20_000.0)
        self.assertAlmostEqual(report.max_error_mm, 0.9765625)
        self.assertIn("3 puntos", report.message)
        self.assertIn("0,977 mm", report.message)
        self.assertIn("8 000 m", report.message)  # espacio fino de miles

    def test_window_corners(self) -> None:
        """RF-002-26: una ventana de 20 × 20 km centrada en el origen tiene las cuatro
        esquinas a más de 8 km: se nombran, con el error estimado; una de 2 km, no."""
        big = georef.Window(690_000.0, 4_390_000.0, 710_000.0, 4_410_000.0)
        report = georef.precision_report(big, ORIGIN)
        self.assertFalse(report.within_limit)
        self.assertEqual(report.corners_outside, ("suroeste", "sureste", "noreste", "noroeste"))
        self.assertAlmostEqual(report.max_error_mm, 0.48828125)
        for corner in ("suroeste", "sureste", "noreste", "noroeste"):
            self.assertIn(corner, report.message)
        east = georef.Window(705_000.0, 4_399_000.0, 709_000.0, 4_401_000.0)
        self.assertEqual(
            georef.precision_report(east, ORIGIN).corners_outside, ("sureste", "noreste")
        )
        small = georef.Window(699_000.0, 4_399_000.0, 701_000.0, 4_401_000.0)
        self.assertTrue(georef.precision_report(small, ORIGIN).within_limit)

    def test_float32_points_rejected(self) -> None:
        """RF-002-25: el informe recibe absolutas en float64; en float32, ``TypeError``."""
        with self.assertRaises(TypeError):
            georef.precision_report(np.zeros((1, 3), dtype=np.float32), ORIGIN)


if __name__ == "__main__":
    unittest.main()
