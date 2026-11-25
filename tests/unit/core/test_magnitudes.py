# SPDX-License-Identifier: GPL-3.0-or-later
"""Las magnitudes con su formato único (spec 019, T06; RF-019-17; UI-07)."""

from __future__ import annotations

import unittest

from geoblender.core import magnitudes
from geoblender.core.errors import GeoblenderError
from geoblender.core.i18n import THIN_SPACE, format_number


class FormatTest(unittest.TestCase):
    """RF-019-17: coma decimal, decimales y unidad fijos por magnitud."""

    def test_each_magnitude_with_unit_and_decimal_comma(self) -> None:
        cases = {
            "length": (12.3456, "12,35 m"),
            "area": (1234.5, f"1{THIN_SPACE}234,50 m²"),
            "volume": (1234567.891, f"1{THIN_SPACE}234{THIN_SPACE}567,9 m³"),
            "percent": (33.333, "33,3 %"),
            "angle": (45.04, "45,0 °"),
        }
        for name, (value, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(magnitudes.format(name, value, language="es"), expected)

    def test_coordinate_keeps_thousands_and_two_decimals(self) -> None:
        self.assertEqual(magnitudes.format("coordinate", 4435871.02, language="es"),
                         f"4{THIN_SPACE}435{THIN_SPACE}871,02 m")

    def test_english_uses_point(self) -> None:
        self.assertEqual(magnitudes.format("area", 1234.5, language="en"), "1,234.50 m²")

    def test_same_number_as_the_existing_formatter(self) -> None:
        for value in (0.0, -0.004, 1234.5678, 987654.321):
            self.assertEqual(magnitudes.format("length", value, language="es"),
                             format_number(value, 2) + " m")

    def test_position_is_three_coordinates_with_their_unit(self) -> None:
        """T25: la posición de la ficha, X, Y y Z absolutas con la unidad de la coordenada (sin float32)."""
        self.assertEqual(magnitudes.format_position(736512.344, 4435871.019, 180.0, language="es"),
                         f"X 736{THIN_SPACE}512,34 m  Y 4{THIN_SPACE}435{THIN_SPACE}871,02 m  Z 180,00 m")
        self.assertEqual(magnitudes.format_position(736512.344, 4400000.456, 0.0, language="en"),
                         "X 736,512.34 m  Y 4,400,000.46 m  Z 0.00 m")

    def test_no_negative_zero(self) -> None:
        self.assertEqual(magnitudes.format("percent", -0.01, language="es"), "0,0 %")

    def test_unknown_magnitude_is_an_error(self) -> None:
        with self.assertRaises(GeoblenderError):
            magnitudes.format("furlong", 1.0)


class ParseTest(unittest.TestCase):
    """Postel: tolerante con coma o punto y espacios."""

    def test_accepted_spellings(self) -> None:
        for text in ("1.234,5", "1234.5", "1 234,5", f"1{THIN_SPACE}234,5", "1234,5", " 1 234,5 m "):
            with self.subTest(text):
                self.assertEqual(magnitudes.parse("length", text), 1234.5)

    def test_unit_suffix_is_optional_and_checked(self) -> None:
        self.assertEqual(magnitudes.parse("percent", "33,3 %"), 33.3)
        self.assertEqual(magnitudes.parse("area", "10 m²"), 10.0)
        with self.assertRaises(GeoblenderError):
            magnitudes.parse("area", "10 m³")

    def test_negative_and_point_as_thousands(self) -> None:
        self.assertEqual(magnitudes.parse("coordinate", "-1.234.567,25"), -1234567.25)
        self.assertEqual(magnitudes.parse("volume", "1,234,567.5"), 1234567.5)

    def test_invalid_text(self) -> None:
        for text in ("", "abc", "1,2,3x", "--1"):
            with self.subTest(text), self.assertRaises(GeoblenderError):
                magnitudes.parse("length", text)

    def test_round_trip(self) -> None:
        for name in magnitudes.MAGNITUDES:
            for value in (0.0, 12.5, -3.5, 1234567.5):
                with self.subTest(name=name, value=value):
                    for language in ("es", "en"):
                        text = magnitudes.format(name, value, language=language)
                        self.assertEqual(magnitudes.parse(name, text), value)

    def test_coordinates_stay_float64(self) -> None:
        """Principio 6: 4 400 000,456 no se redondea a 0,5."""
        text = magnitudes.format("coordinate", 4400000.456, language="es")
        self.assertEqual(text, f"4{THIN_SPACE}400{THIN_SPACE}000,46 m")
        self.assertEqual(magnitudes.parse("coordinate", "4 400 000,456"), 4400000.456)
        self.assertIsInstance(magnitudes.parse("coordinate", "4400000.456"), float)


if __name__ == "__main__":
    unittest.main()
