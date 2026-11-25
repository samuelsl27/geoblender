# SPDX-License-Identifier: GPL-3.0-or-later
"""Valores canónicos y validación del aspecto (spec 019, T02; RF-019-08, RF-019-22; plan 019 §5.2 y §5.3;
UI-34).

Color ``#RRGGBB``, transparencia entera de 0 a 100, ``0``/``1``, decimales con punto y texto. Un valor
fuera de rango se rechaza con objeto, campo y valor (principio 10).
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

model = import_geoblender("core.appearance.model")
catalog = import_geoblender("core.appearance.catalog")
errors = import_geoblender("core.errors")


class ValidateTest(unittest.TestCase):
    def test_canonical_values(self) -> None:
        v = model.validate
        self.assertEqual(v("DTM", "color", "#56b4e9"), "#56B4E9")
        self.assertEqual(v("DTM", "color", " #56B4E9 "), "#56B4E9")
        self.assertEqual(v("DTM", "transparency", "30"), "30")
        self.assertEqual(v("DTM", "transparency", 30), "30")
        self.assertEqual(v("DTM", "transparency", 30.0), "30")
        self.assertEqual(v("DTM", "visible", True), "1")
        self.assertEqual(v("DTM", "visible", "0"), "0")
        self.assertEqual(v("DTM", "wire", 1), "1")
        self.assertEqual(v("CONTOURS", "line_width", "2,5"), "2.5")
        self.assertEqual(v("CONTOURS", "line_width", 2.0), "2")
        self.assertEqual(v("POINTS", "point_size", "3.0"), "3")
        self.assertEqual(v("POINTS", "labels", "1"), "1")
        self.assertEqual(v("DTM", "label", "  Topografía inicial "), "Topografía inicial")

    def test_out_of_range_names_object_field_and_value(self) -> None:
        """RF-019-08: color y transparencia fuera de rango se rechazan con objeto, campo y valor."""
        cases = [("DTM", "transparency", "101"), ("DTM", "transparency", "-1"), ("DTM", "transparency", "12,5"),
                 ("DTM", "transparency", "abc"), ("DTM", "color", "#GGGGGG"), ("DTM", "color", "#FFF"),
                 ("DTM", "color", "rojo"), ("DTM", "visible", "2"), ("CONTOURS", "line_width", "0"),
                 ("CONTOURS", "line_width", "99"), ("CONTOURS", "line_width", "nan"),
                 ("POINTS", "point_size", "inf"), ("POINTS", "point_size", "-3"), ("DTM", "label", "   "),
                 ("DTM", "label", "a\nb"), ("DTM", "label", "x" * 200), ("DTM", "transparency", None),
                 ("DTM", "transparency", True)]
        for kind, prop, raw in cases:
            with self.assertRaises(errors.GeoblenderError, msg=f"{kind}.{prop}={raw!r}") as caught:
                model.validate(kind, prop, raw)
            error = caught.exception
            self.assertEqual(error.code, "core.appearance_invalid")
            self.assertTrue(error.obj and error.field, str(error))
            self.assertEqual(error.value, raw)
            self.assertIn(kind, error.obj)

    def test_a_property_the_kind_does_not_have(self) -> None:
        """UI-13: un tipo sin la propiedad no la acepta."""
        with self.assertRaises(errors.GeoblenderError) as caught:
            model.validate("DTM", "line_width", "2")
        self.assertEqual(caught.exception.code, "core.appearance_not_editable")
        with self.assertRaises(errors.GeoblenderError) as caught:
            model.validate("DTM", "bogus", "2")
        self.assertEqual(caught.exception.code, "core.appearance_not_editable")
        with self.assertRaises(errors.GeoblenderError):
            model.validate("NOPE", "color", "#000000")

    def test_message_is_spanish_and_has_no_internal_keys(self) -> None:
        """UI-08, UI-34: el texto va por el catálogo, en español."""
        with self.assertRaises(errors.GeoblenderError) as caught:
            model.validate("DTM", "transparency", "101")
        text = str(caught.exception)
        self.assertIn("101", text)
        self.assertIn("0 y 100", text)
        self.assertNotIn("transparency", text)


class AppearanceTest(unittest.TestCase):
    def test_appearance_is_immutable_and_hashable(self) -> None:
        look = model.Appearance("DTM", (("color", "#000000"), ("visible", "1")))
        self.assertEqual(look.get("color"), "#000000")
        self.assertEqual(look.props, ("color", "visible"))
        self.assertEqual(look.as_dict(), {"color": "#000000", "visible": "1"})
        self.assertEqual(hash(look), hash(model.Appearance("DTM", (("color", "#000000"), ("visible", "1")))))
        with self.assertRaises(KeyError):
            look.get("wire")
        self.assertIsNone(look.get("wire", None))

    def test_with_values_validates(self) -> None:
        look = catalog.defaults_for("DTM").with_values({"transparency": "40", "color": "#aabbcc"})
        self.assertEqual(look.get("transparency"), "40")
        self.assertEqual(look.get("color"), "#AABBCC")
        with self.assertRaises(errors.GeoblenderError):
            catalog.defaults_for("DTM").with_values({"transparency": "400"})


if __name__ == "__main__":
    unittest.main()
