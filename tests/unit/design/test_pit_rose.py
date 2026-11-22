# SPDX-License-Identifier: GPL-3.0-or-later
"""La roseta de taludes de la corta (spec 018, T04; HU-018-1; RF-018-07, RF-018-08; plan 018 §5.1, §5.2.2 y §5.2.3; ADR-0027;
RF-013-20, RF-009-24).

Lo puro: la validación de los rangos de una roseta (de 0 a 360° sin huecos ni solapes; α en (0; 90)°; B ≥ 0), el avance de cada rango
``n·h/tan α + B`` y su talud general ``atan(n·h / avance)`` con el cálculo a mano de 70 cifras (error ≤ 10⁻⁹ relativo), el rango de un
azimut y el código del nombre. La tabla del proyecto y la operación de proyecto ``des.edit_pit_roses`` (una versión, los rechazos y el
código inmutable) están en ``milestone_pit_rose_ramp_operation`` (paso «hito», como las de los perfiles de la 017).
"""

from __future__ import annotations

import math
import unittest
from decimal import Decimal, localcontext
from typing import Any

from tests.support import pit_data as pd
from tests.support.package import import_geoblender

messages = import_geoblender("design.messages")
pit_rose = import_geoblender("design.pit_rose")

NAME = "ROSETA_TAJO"
CODE = "roseta_tajo"


def ranges_of(data: Any = pd.ROSE_TWO_RANGES) -> list[Any]:
    return [pit_rose.RoseRange(item.from_deg, item.to_deg, item.face_deg, item.berm_m) for item in data]


def relative(found: float, expected: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 70
        return abs(Decimal(found) - expected) / abs(expected)


class _Case(unittest.TestCase):
    def rejected(self, ranges: Any) -> Any:
        with self.assertRaises(messages.DesignError) as caught:
            pit_rose.check_rose(NAME, CODE, ranges)
        return caught.exception


class ValidRoseTest(_Case):
    def test_the_rose_of_ce_018_02_is_valid(self) -> None:
        """RF-018-07: la roseta de CE-018-02 (0–180° con 60° y 6 m; 180–360° con 45° y 6 m) cubre de 0 a 360° sin huecos ni solapes."""
        found = pit_rose.check_rose(NAME, CODE, ranges_of())
        self.assertEqual([(item.from_deg, item.to_deg, item.face_deg, item.berm_m) for item in found],
                         [(0.0, 180.0, 60.0, 6.0), (180.0, 360.0, 45.0, 6.0)])

    def test_the_ranges_come_back_in_azimuth_order(self) -> None:
        """RF-018-07: la roseta se escribe en cualquier orden y se lee de 0 a 360°."""
        found = pit_rose.check_rose(NAME, CODE, list(reversed(ranges_of())))
        self.assertEqual([item.from_deg for item in found], [0.0, 180.0])

    def test_a_single_range_may_cover_the_circle(self) -> None:
        found = pit_rose.check_rose(NAME, CODE, [pit_rose.RoseRange(0.0, 360.0, 70.0, 5.0)])
        self.assertEqual(len(found), 1)

    def test_a_range_accepts_a_mapping_or_a_tuple(self) -> None:
        found = pit_rose.check_rose(NAME, CODE, [{"from_deg": 0, "to_deg": 90, "face_deg": 60, "berm_m": 6}, (90, 360, 45, 6)])
        self.assertEqual([item.to_deg for item in found], [90.0, 360.0])

    def test_the_index_of_a_range_is_r_and_its_position(self) -> None:
        """RF-018-07 (T04 confirma la forma de T03): ``des.rose.{r}.{i}.<valor>`` con ``{i}`` = ``r1``, ``r2``…"""
        self.assertEqual([pit_rose.range_index(i) for i in range(3)], ["r1", "r2", "r3"])


class RejectionTest(_Case):
    def test_a_gap_is_rejected_with_its_azimuths(self) -> None:
        """RF-018-07: un hueco entre 180° y 200° se rechaza nombrando la roseta y los azimuts."""
        error = self.rejected([pit_rose.RoseRange(0, 180, 60, 6), pit_rose.RoseRange(200, 360, 45, 6)])
        self.assertEqual(error.code, "des.pit_rose_gap")
        self.assertEqual((error.values["from_deg"], error.values["to_deg"]), (180.0, 200.0))
        self.assertIn(NAME, error.text)

    def test_a_gap_at_the_ends_is_rejected(self) -> None:
        self.assertEqual(self.rejected([pit_rose.RoseRange(10, 360, 60, 6)]).code, "des.pit_rose_gap")
        error = self.rejected([pit_rose.RoseRange(0, 350, 60, 6)])
        self.assertEqual((error.code, error.values["from_deg"], error.values["to_deg"]), ("des.pit_rose_gap", 350.0, 360.0))

    def test_an_overlap_is_rejected_with_its_azimuths(self) -> None:
        error = self.rejected([pit_rose.RoseRange(0, 190, 60, 6), pit_rose.RoseRange(180, 360, 45, 6)])
        self.assertEqual(error.code, "des.pit_rose_overlap")
        self.assertEqual((error.values["from_deg"], error.values["to_deg"]), (180.0, 190.0))

    def test_a_range_that_does_not_advance_is_rejected(self) -> None:
        """RF-018-07: ``desde`` < ``hasta`` en cada rango."""
        error = self.rejected([pit_rose.RoseRange(180, 180, 60, 6), pit_rose.RoseRange(0, 180, 60, 6)])
        self.assertEqual((error.code, error.field), ("des.pit_rose_value_range", "des.rose.roseta_tajo.r1.to_deg"))

    def test_the_face_angle_out_of_range_names_the_range(self) -> None:
        """RF-018-07, RF-018-04: α = 0°, 90° o 120° fuera de (0; 90)°, con la clave y el valor."""
        for alpha in (0.0, 90.0, 120.0, -5.0):
            with self.subTest(alpha=alpha):
                error = self.rejected([pit_rose.RoseRange(0, 180, 60, 6), pit_rose.RoseRange(180, 360, alpha, 6)])
                self.assertEqual((error.code, error.field, error.values["value"]),
                                 ("des.pit_rose_value_range", "des.rose.roseta_tajo.r2.face_deg", alpha))
                self.assertIn("(0; 90)", error.values["range"])

    def test_a_negative_berm_is_rejected(self) -> None:
        error = self.rejected([pit_rose.RoseRange(0, 360, 60, -0.5)])
        self.assertEqual((error.code, error.field, error.values["value"]),
                         ("des.pit_rose_value_range", "des.rose.roseta_tajo.r1.berm_m", -0.5))

    def test_a_missing_value_is_rejected(self) -> None:
        for bad in ({"from_deg": 0, "to_deg": 360, "face_deg": 60}, {"from_deg": 0, "to_deg": 360, "face_deg": None, "berm_m": 6}):
            with self.subTest(bad=bad):
                self.assertEqual(self.rejected([bad]).code, "des.pit_rose_value_missing")

    def test_no_ranges_is_rejected(self) -> None:
        self.assertEqual(self.rejected([]).code, "des.pit_rose_no_ranges")

    def test_non_finite_values_are_rejected(self) -> None:
        for value in (math.nan, math.inf):
            with self.subTest(value=value):
                self.assertEqual(self.rejected([pit_rose.RoseRange(0, 360, value, 6)]).code, "des.pit_rose_value_range")

    def test_a_range_of_the_wrong_shape_is_a_program_error(self) -> None:
        with self.assertRaises(ValueError):
            pit_rose.check_rose(NAME, CODE, [(0, 360, 60)])
        with self.assertRaises(TypeError):
            pit_rose.check_rose(NAME, CODE, [{"from_deg": "a", "to_deg": 360, "face_deg": 60, "berm_m": 6}])


class DerivedTest(unittest.TestCase):
    def test_the_advance_between_berms(self) -> None:
        """RF-018-07, RF-018-08, CE-018-02: h = 10 m, α = 60°, B = 6 m → 10/√3 + 6 = 11,7735 m; con 2 bancos por berma, 20/√3 + 6;
        con α = 45°, 16 m y 26 m (cálculo a mano de 70 cifras, error ≤ 10⁻⁹)."""
        with localcontext() as context:
            context.prec = 70
            root3 = Decimal(3).sqrt()
            cases = [(1, 60.0, Decimal(10) / root3 + 6), (2, 60.0, Decimal(20) / root3 + 6),
                     (1, 45.0, Decimal(16)), (2, 45.0, Decimal(26)), (3, 45.0, Decimal(36))]
        for n, alpha, expected in cases:
            with self.subTest(n=n, alpha=alpha):
                self.assertLessEqual(relative(pit_rose.advance_m(10.0, alpha, 6.0, n), expected), Decimal("1e-9"))

    def test_the_overall_slope(self) -> None:
        """RF-018-07: el talud general es atan(n·h / avance): 10 m con 16 m de avance → atan(0,625)."""
        found = pit_rose.overall_slope_deg(10.0, 45.0, 6.0)
        self.assertLessEqual(abs(found - math.degrees(math.atan(0.625))) / found, 1e-9)
        advance = 10.0 / math.tan(math.radians(60.0)) + 6.0
        self.assertAlmostEqual(pit_rose.overall_slope_deg(10.0, 60.0, 6.0), math.degrees(math.atan(10.0 / advance)), places=9)
        double = pit_rose.overall_slope_deg(10.0, 45.0, 6.0, 2)
        self.assertLessEqual(abs(double - math.degrees(math.atan(20.0 / 26.0))) / double, 1e-9)

    def test_without_a_rose_the_values_are_the_ones_of_the_profile(self) -> None:
        """RF-018-07: sin roseta, α y B son los del perfil: el avance es el del perfil (EXPL_10_60_6: 11,7735 m)."""
        found = pit_rose.profile_range(60.0, 6.0)
        self.assertEqual((found.from_deg, found.to_deg, found.face_deg, found.berm_m), (0.0, 360.0, 60.0, 6.0))
        self.assertAlmostEqual(pit_rose.derived([found], 10.0)[0].advance_m, 11.7735, places=4)

    def test_the_derived_values_of_every_range(self) -> None:
        found = pit_rose.derived(pit_rose.check_rose(NAME, CODE, ranges_of()), 10.0)
        self.assertEqual([(item.range.from_deg, item.range.to_deg) for item in found], [(0.0, 180.0), (180.0, 360.0)])
        self.assertAlmostEqual(found[0].advance_m, 11.7735026919, places=9)
        self.assertAlmostEqual(found[1].advance_m, 16.0, places=9)
        self.assertAlmostEqual(found[1].overall_slope_deg, math.degrees(math.atan(10.0 / 16.0)), places=9)

    def test_the_inputs_of_the_derived_are_checked(self) -> None:
        """RF-018-08: n entero ≥ 1, h > 0, α en (0; 90), B ≥ 0; otra cosa es un error del programa."""
        for args in ((10.0, 60.0, 6.0, 0), (10.0, 60.0, 6.0, 1.5), (10.0, 60.0, 6.0, True), (0.0, 60.0, 6.0, 1),
                     (10.0, 90.0, 6.0, 1), (10.0, 60.0, -1.0, 1)):
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                pit_rose.advance_m(*args)

    def test_the_hand_distance_of_the_fixture_agrees(self) -> None:
        """CE-018-02: la distancia de la cara h/tan α de ``pit_data`` (5,7735 m en 90°, 10 m en 270°) es el avance sin la berma."""
        rose = pit_rose.check_rose(NAME, CODE, ranges_of())
        for azimuth in (90.0, 270.0, 0.0, 359.9):
            found = pit_rose.range_at(rose, azimuth)
            self.assertAlmostEqual(pit_rose.advance_m(10.0, found.face_deg, 0.0), pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, azimuth), places=9)


class RangeAtTest(_Case):
    def test_the_range_is_closed_on_the_left_and_open_on_the_right(self) -> None:
        """RF-018-07: ``[desde, hasta)``: 180° es del segundo rango y 360° vale 0°."""
        rose = pit_rose.check_rose(NAME, CODE, ranges_of())
        self.assertEqual(pit_rose.range_at(rose, 179.999).face_deg, 60.0)
        self.assertEqual(pit_rose.range_at(rose, 180.0).face_deg, 45.0)
        self.assertEqual(pit_rose.range_at(rose, 360.0).face_deg, 60.0)
        self.assertEqual(pit_rose.range_at(rose, -90.0).face_deg, 45.0)


class CodeTest(unittest.TestCase):
    def test_the_code_comes_from_the_name_and_is_not_reused(self) -> None:
        """RF-018-07: ``[a-z][a-z0-9_]*`` ASCII, ``rose`` delante si no empieza por letra, ``_2`` si ya está."""
        self.assertEqual(pit_rose.rose_code("ROSETA TAJO Ñ", []), "roseta_tajo_n")
        self.assertEqual(pit_rose.rose_code("10-60", []), "rose_10_60")
        self.assertEqual(pit_rose.rose_code("roseta tajo", ["roseta_tajo"]), "roseta_tajo_2")
        self.assertEqual(pit_rose.rose_code("", []), "rose")


if __name__ == "__main__":
    unittest.main()
