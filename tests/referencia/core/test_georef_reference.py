# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la georreferencia (spec 002; constitución, principio 2;
ADR-0005, «Cómo se verifica»).

- GeoOrigin (T03, RF-002-24): el centro (700 234,7; 4 400 281,2) da exactamente
  (700 200; 4 400 300), y una ventana de 700 000,0 a 700 099,6 en X con paso 1 m da
  X0 = 700 100 (centro de la ventana ampliada). Resultado conocido por cálculo manual;
  tolerancia: ninguna (enteros exactos).
- Ida y vuelta (T04, RF-002-25; CE-002-03): 10⁶ puntos aleatorios (semilla fija) a
  ±8 km de (700 000; 4 400 000; 0), con Z de 0 a 4 000 m, absoluta float64 → local
  float32 (lo que guarda Blender) → absoluta float64. Tolerancia: 0,5 mm; esperado
  ≤ 0,244 mm, el redondeo teórico de float32 a 8 km (ADR-0005).
"""

import unittest

import numpy as np

from tests.support.package import import_geoblender

georef = import_geoblender("core.georef")

ROUND_TRIP_POINTS = 1_000_000
ROUND_TRIP_SEED = 20_261_005
TOLERANCE_M = 0.0005  # 0,5 mm (ADR-0005, punto 6)
EXPECTED_MAX_M = 0.000244140625  # 2⁻¹² m: semipaso de float32 entre 4 096 y 8 192 m


class GeoOriginReferenceTest(unittest.TestCase):
    def test_origin_of_reference_centre(self) -> None:
        """RF-002-24 (referencia, ADR-0005): centro (700 234,7; 4 400 281,2) →
        (700 200; 4 400 300; 0), exacto."""
        window = georef.Window(700_134.7, 4_400_181.2, 700_334.7, 4_400_381.2)
        self.assertEqual(window.centre, (700_234.7, 4_400_281.2))
        self.assertEqual(georef.choose_origin(window), georef.GeoOrigin(700_200, 4_400_300, 0))

    def test_origin_of_widened_window(self) -> None:
        """RF-002-24 (referencia, spec 002 §8): ventana tecleada de 700 000,0 a 700 099,6
        en X con paso 1 m → ventana 700 000–700 100 y X0 = 700 100, exacto."""
        typed = georef.Window(700_000.0, 4_400_000.0, 700_099.6, 4_400_100.0)
        aligned = georef.align_window(typed, 1.0)
        self.assertEqual(aligned, georef.Window(700_000.0, 4_400_000.0, 700_100.0, 4_400_100.0))
        self.assertEqual(georef.choose_origin(aligned).x0, 700_100)


class RoundTripReferenceTest(unittest.TestCase):
    def test_million_points_through_float32(self) -> None:
        """RF-002-25 (referencia; CE-002-03): 10⁶ puntos a ±8 km del origen (700 000;
        4 400 000; 0), Z de 0 a 4 000 m, pasando por float32: error máximo ≤ 0,5 mm
        (esperado ≤ 0,244 mm); la cifra va en el mensaje de la prueba."""
        rng = np.random.default_rng(ROUND_TRIP_SEED)
        n = ROUND_TRIP_POINTS
        world = np.column_stack(
            [
                700_000.0 + rng.uniform(-8_000.0, 8_000.0, n),
                4_400_000.0 + rng.uniform(-8_000.0, 8_000.0, n),
                rng.uniform(0.0, 4_000.0, n),
            ]
        )
        origin = georef.GeoOrigin(700_000, 4_400_000, 0)
        local32 = georef.world_to_local(world, origin).astype(np.float32)  # Blender
        back = georef.local_to_world(local32, origin)
        error = float(np.abs(back - world).max())
        figure = f"error máximo {error * 1000:.4f} mm en {n} puntos"
        self.assertLessEqual(error, TOLERANCE_M, figure)
        self.assertLessEqual(error, EXPECTED_MAX_M, figure)
        report = georef.precision_report(world, origin)
        self.assertTrue(report.within_limit, report.message)


if __name__ == "__main__":
    unittest.main()
