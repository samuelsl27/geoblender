# SPDX-License-Identifier: GPL-3.0-or-later
"""Mezcla del aspecto de varios elementos y regla de la leyenda por campo (spec 019, T04; RF-019-10,
RF-019-13; plan 019 §5.7 P-10; D-8)."""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

merge = import_geoblender("core.appearance.merge")
catalog = import_geoblender("core.appearance.catalog")
errors = import_geoblender("core.errors")


def _dtm(**changes: str):
    return catalog.defaults_for("DTM").with_values(changes)


class CommonTest(unittest.TestCase):
    def test_three_equal_items_give_the_value(self) -> None:
        result = merge.common([_dtm(color="#112233")] * 3)
        self.assertEqual(result, _dtm(color="#112233"))

    def test_one_different_field_is_various_values(self) -> None:
        result = merge.common([_dtm(), _dtm(), _dtm(transparency="40")])
        self.assertIsInstance(result, merge.Mixed)
        self.assertEqual(result.count, 3)
        self.assertEqual(result.kinds, ("DTM",))
        self.assertTrue(result.is_various("transparency"))
        self.assertFalse(result.is_various("color"))
        self.assertEqual(result.get("color"), catalog.defaults_for("DTM").get("color"))
        self.assertIsNone(result.get("transparency"))

    def test_different_kinds_only_common_fields(self) -> None:
        result = merge.common([_dtm(transparency="20"), catalog.defaults_for("POINTS"),
                               catalog.defaults_for("BREAKLINES")])
        self.assertIsInstance(result, merge.Mixed)
        self.assertEqual(result.count, 3)
        self.assertEqual(set(result.kinds), {"DTM", "POINTS", "BREAKLINES"})
        # transparency no es de POINTS: solo queda la visibilidad
        self.assertEqual(result.props, ("visible",))
        self.assertEqual(result.get("visible"), "1")

    def test_different_kinds_with_shared_transparency(self) -> None:
        result = merge.common([_dtm(transparency="20"), catalog.defaults_for("DESIGN")])
        self.assertEqual(result.props, ("transparency", "visible"))
        self.assertTrue(result.is_various("transparency"))
        self.assertFalse(result.is_various("visible"))

    def test_empty_selection_is_an_error(self) -> None:
        with self.assertRaises(errors.GeoblenderError):
            merge.common([])


class ColorRuleTest(unittest.TestCase):
    def test_without_legend_the_color_is_editable(self) -> None:
        rule = merge.color_rule([None, None])
        self.assertTrue(rule.editable)
        self.assertIsNone(rule.legend)

    def test_active_legend_rules_and_is_named(self) -> None:
        rule = merge.color_rule([None, "Cu %"])
        self.assertFalse(rule.editable)
        self.assertEqual(rule.legend, "Cu %")
        self.assertIn("Cu %", rule.text)

    def test_color_returns_when_the_legend_is_removed(self) -> None:
        stored = _dtm(color="#112233")
        self.assertTrue(merge.color_rule([None]).editable)
        self.assertEqual(merge.effective_color(stored, "Cu %"), None)
        self.assertEqual(merge.effective_color(stored, None), "#112233")

    def test_several_legends_are_all_named(self) -> None:
        rule = merge.color_rule(["Cu %", "Au g/t", "Cu %"])
        self.assertEqual(rule.legend, "Au g/t, Cu %")


if __name__ == "__main__":
    unittest.main()
