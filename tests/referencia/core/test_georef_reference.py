# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la georreferencia (spec 002; constitución, principio 2;
ADR-0005, «Cómo se verifica»).

- GeoOrigin (T03, RF-002-24): el centro (700 234,7; 4 400 281,2) da exactamente
  (700 200; 4 400 300), y una ventana de 700 000,0 a 700 099,6 en X con paso 1 m da
  X0 = 700 100 (centro de la ventana ampliada). Resultado conocido por cálculo manual;
  tolerancia: ninguna (enteros exactos).
"""

import unittest

from tests.support.package import import_geoblender

georef = import_geoblender("core.georef")


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


if __name__ == "__main__":
    unittest.main()
