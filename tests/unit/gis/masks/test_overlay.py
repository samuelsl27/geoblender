# SPDX-License-Identifier: GPL-3.0-or-later
"""El informe de los límites (spec 012, T09; RF-012-05, RF-012-15; plan 012 A4, D-12 y D-14).

- **RF-012-05 (D-12)**: las áreas del límite legal, del perímetro, de su intersección y de la
  franja perímetro ∖ límite legal, en m² y ha, con cada parte de la franja (área y centro
  absoluto) como aviso; dos concesiones contiguas dan lo mismo que una (se unen antes).
- **RF-012-15 (D-14)**: sin perímetro, el límite legal hace de perímetro (sin franja), con su
  aviso; lo que queda fuera de la rejilla, con el nombre y el área, en el informe.
"""

import unittest

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.gis.masks.test_combine import GRID, make, resolved_for

model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
overlay = import_geoblender("gis.masks.overlay")

T = model.ConstraintType
EXACT = 1e-9
ORIGIN = (GRID.west, GRID.extent.ymin)


class LimitsReportTest(unittest.TestCase):
    """RF-012-05: el informe a mano del caso de ``test_combine``."""

    def check_close(self, value, expected):
        self.assertLessEqual(abs(value - expected), EXACT * max(abs(expected), 1.0))

    def test_areas_and_strip_parts(self) -> None:
        legal = [(fx.rectangle(0, 0, 30, 30),)]
        for name, legal_rings in (("una", legal),
                                  ("dos contiguas", [(fx.rectangle(0, 0, 15, 30),),
                                                     (fx.rectangle(15, 0, 30, 30),)])):
            with self.subTest(legal=name):
                report = overlay.limits_report(legal_rings, [(fx.rectangle(2, 2, 36, 28),)],
                                               origin=ORIGIN)
                self.check_close(report.legal_m2, 900.0)
                self.check_close(report.perimeter_m2, 34 * 26.0)
                self.check_close(report.intersection_m2, 28 * 26.0)
                self.check_close(report.strip_m2, 6 * 26.0)
                self.check_close(report.legal_ha, 0.09)
                self.check_close(report.strip_ha, 0.0156)
                self.assertFalse(report.perimeter_from_legal)
                self.assertEqual(len(report.strip_parts), 1)
                part = report.strip_parts[0]
                self.check_close(part.area_m2, 156.0)
                self.check_close(part.centroid[0], fx.BASE[0] + 33.0)
                self.check_close(part.centroid[1], fx.BASE[1] + 15.0)
                notices = report.notices()
                self.assertEqual([n.code for n in notices], ["core.constraint_strip_part"])
                text = notices[0].text("es")
                self.assertIn("156 m²", text)
                self.assertIn("0,0156 ha", text)
                self.assertNotIn("{", notices[0].text("en"))

    def test_two_strip_parts_largest_first(self) -> None:
        """Un perímetro de dos polígonos contiguos: dos partes de la franja, la mayor antes."""
        report = overlay.limits_report(
            [(fx.rectangle(0, 0, 30, 30),)],
            [(fx.rectangle(2, 2, 36, 28),), (fx.rectangle(-4, 10, 2, 20),)], origin=ORIGIN)
        self.check_close(report.perimeter_m2, 34 * 26.0 + 60.0)
        self.check_close(report.strip_m2, 156.0 + 40.0)
        self.assertEqual(len(report.strip_parts), 2)
        for part, (area, x, y) in zip(report.strip_parts, ((156.0, 33.0, 15.0),
                                                           (40.0, -2.0, 15.0)), strict=True):
            self.check_close(part.area_m2, area)
            self.check_close(part.centroid[0], fx.BASE[0] + x)
            self.check_close(part.centroid[1], fx.BASE[1] + y)
        self.assertEqual(len(report.notices()), 2)

    def test_without_perimeter(self) -> None:
        report = overlay.limits_report([(fx.rectangle(0, 0, 30, 30),)], None, origin=ORIGIN)
        self.assertTrue(report.perimeter_from_legal)
        self.check_close(report.perimeter_m2, 900.0)
        self.check_close(report.intersection_m2, 900.0)
        self.assertEqual((report.strip_m2, report.strip_parts), (0.0, ()))
        self.assertEqual([n.code for n in report.notices()], [])

    def test_report_of_prepared(self) -> None:
        """Desde lo preparado para combinar: los límites activos y lo que queda fuera."""
        items = [make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 35), fid=1),
                 make("r_perimetro", T.ACTION_PERIMETER, (2, 2, 36, 28), fid=2),
                 make("r_cantera", T.EXCLUSION, (-3, 10, 2, 12), fid=3, name="Cantera vieja")]
        prepared = combine.prepare(items, resolved_for(items), GRID)
        report = overlay.report_of(prepared, GRID)
        self.check_close(report.legal_m2, 30 * 35.0)
        self.check_close(report.strip_m2, 6 * 26.0)
        self.assertEqual({(o.code, o.name, o.area_m2) for o in report.outside},
                         {("r_concesion", "Concesion", 150.0),
                          ("r_cantera", "Cantera vieja", 6.0)})
        codes = [n.code for n in report.notices()]
        self.assertEqual(codes.count("core.constraint_zone_outside_grid"), 2)
        self.assertEqual(codes.count("core.constraint_strip_part"), 1)


if __name__ == "__main__":
    unittest.main()
