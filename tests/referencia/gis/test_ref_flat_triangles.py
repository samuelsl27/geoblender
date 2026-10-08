# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia de los triángulos planos de un TIN desde curvas (spec 006, T20;
RF-006-16; plan 006 §5.4 A12 y §7.2; inv. 08 §6.3; CE-006-03).

Tres curvas concéntricas de 850, 855 y 860 m (círculos de 36, 24 y 12 m de radio con 49
vértices cada uno: tramos de 4,6 m como mucho, sin densificar con los 5 m por defecto) y un
punto acotado de 863 m en el centro, con los parámetros por defecto (``gis/params.py``):

- **Sin corregir** (la triangulación de las curvas solas, como en inv. 08 §6.3): 47 de 243
  triángulos planos, el 19,3 %: todo el 49-gono de la cima (49 − 2 triángulos; entre dos
  anillos ningún triángulo tiene sus tres vértices en uno, porque su circunferencia
  circunscrita es la del anillo y contiene el otro).
- **Corregido**: por debajo de ``gis.tin.max_flat_pct`` (1 %).
- **Sin el punto acotado** (D-6): la cima queda plana (las mismas 47) y se informa como una
  región sin acotar con el área del 49-gono.
"""

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
params = import_geoblender("gis.params")
points = import_geoblender("gis.points")
cdt = import_geoblender("gis.cdt")
georef = import_geoblender("core.georef")

E0, N0 = 700_000.0, 4_400_000.0
ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)
CENTER = (E0 + 250.0, N0 + 180.0)
CONTOURS = ((36.0, 850.0, 0.0), (24.0, 855.0, 0.03), (12.0, 860.0, 0.06))  # radio, cota, giro
COUNT = 49
SPOT_HEIGHT = 863.0
BASELINE_PCT = 19.0  # inv. 08 §6.3: 47 de 243
BASELINE_TOLERANCE_PCT = 0.5


def _contours() -> list:
    lines = []
    for radius, level, offset in CONTOURS:
        angle = offset + 2.0 * math.pi * np.arange(COUNT + 1) / COUNT
        angle[-1] = angle[0]  # cerrada
        xyz = np.column_stack([CENTER[0] + radius * np.cos(angle),
                               CENTER[1] + radius * np.sin(angle), np.full(COUNT + 1, level)])
        xyz.flags.writeable = False
        lines.append(points.Breakline(f"C{level:g}", xyz))
    return lines


def _spot() -> object:
    xyz = np.array([[CENTER[0], CENTER[1], SPOT_HEIGHT]])
    xyz.flags.writeable = False
    return points.PointSet(xyz, ("cima",), ("",), (2,))


def _build(spots):
    return gis.tin_from_contours(_contours(), spot_heights=spots,
                                 triangulator=cdt.PureTriangulator(), origin=ORIGIN,
                                 name="referencia")


class FlatTrianglesReferenceTest(unittest.TestCase):
    """RF-006-16: curvas concéntricas de 850, 855 y 860 m con punto acotado de 863 m."""

    def test_flat_triangles_corrected(self) -> None:
        """Sin corregir ≈ 19 % (47 de 243, inv. 08 §6.3); corregido < 1 %
        (``gis.tin.max_flat_pct``); ninguna cima sin acotar."""
        tin, report = _build(_spot())
        self.assertEqual(report.flat_pct_before, 100.0 * 47 / 243)
        self.assertAlmostEqual(report.flat_pct_before, BASELINE_PCT,
                               delta=BASELINE_TOLERANCE_PCT)
        self.assertLess(report.flat_pct, params.default("gis.tin.max_flat_pct"))
        self.assertEqual(report.flat_pct, 100.0 * tin.flat_faces / len(tin.faces))
        self.assertEqual(report.unresolved_flat_regions, 0)
        self.assertIn(SPOT_HEIGHT, tin.vertices[:, 2].tolist())

    def test_summit_without_spot_height_is_reported(self) -> None:
        """Sin el punto acotado, la cima queda plana (47 de 243) y se informa: una región
        con el área del 49-gono de 12 m de radio, (49/2)·12²·sen(2π/49) m² (D-6)."""
        tin, report = _build(None)
        self.assertEqual(report.flat_pct, 100.0 * 47 / 243)
        self.assertEqual(report.points_added, 0)
        self.assertEqual(report.unresolved_flat_regions, 1)
        area = COUNT / 2.0 * 12.0**2 * math.sin(2.0 * math.pi / COUNT)
        self.assertAlmostEqual(report.unresolved_flat_area_m2, area, delta=1e-9 * area)
        self.assertEqual(tin.flat_faces, 47)


if __name__ == "__main__":
    unittest.main()
