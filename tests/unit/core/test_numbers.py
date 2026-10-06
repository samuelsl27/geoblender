# SPDX-License-Identifier: GPL-3.0-or-later
"""Números tecleados en un diálogo (spec 002, T25; RF-002-01, RF-002-03; ADR-0005 §4).

Las coordenadas absolutas que teclea el usuario llegan como texto (``StringProperty``: un
``FloatProperty`` las guardaría en float32) y se convierten a float64 aceptando coma o
punto decimal y espacios (también el fino) como separador de miles. Lo que no es un
número se rechaza con el objeto, el campo y el valor.
"""

import unittest

from tests.support.package import import_geoblender

numbers = import_geoblender("core.numbers")
errors = import_geoblender("core.errors")


class ParseDecimalTest(unittest.TestCase):
    def parse(self, text: object) -> float:
        return numbers.parse_decimal(text, obj="Ventana de trabajo", field="xmin")

    def test_comma_or_point(self) -> None:
        """RF-002-01: coma o punto decimal, con o sin espacios de miles (normales,
        finos o sin ruptura), signo y espacios alrededor; el resultado es float64 exacto
        al texto (700 000,4 → 700000.4)."""
        cases = {
            "700000,4": 700000.4,
            "700000.4": 700000.4,
            "700 000,4": 700000.4,
            "4 400 500,9": 4400500.9,
            "4 400 500.9": 4400500.9,
            "4 400 500": 4400500.0,
            "  -180 ": -180.0,
            "+12,5": 12.5,
            ",5": 0.5,
            "7.": 7.0,
            "4400000.456": 4400000.456,
        }
        for text, expected in cases.items():
            with self.subTest(texto=text):
                value = self.parse(text)
                self.assertIs(type(value), float)
                self.assertEqual(value, expected)

    def test_rejected_with_field(self) -> None:
        """RF-002-03: vacío, texto, dos separadores decimales, coma y punto a la vez,
        infinito o NaN se rechazan con el objeto, el campo y el valor tecleado."""
        for text in ("", "   ", "abc", "700.000,4", "1,2,3", "1.2.3", "inf", "nan", "1e3",
                     "--5", None, 5):
            with self.subTest(texto=text):
                with self.assertRaises(errors.ValidationError) as caught:
                    self.parse(text)
                self.assertEqual(caught.exception.field, "xmin")
                self.assertIn("Ventana de trabajo", str(caught.exception))
                self.assertIn("xmin", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
