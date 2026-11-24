# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo puro de «Cambiar parámetro…» de los valores de la corta (spec 018, T41; hallazgo F-1; RF-018-04, RF-018-07, RF-018-15): las claves y las reglas con los valores ya leídos. Con un proyecto,
en ``milestone_pit_parameter_check`` (paso «hito»)."""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

messages = import_geoblender("design.messages")
pit_param_check = import_geoblender("design.pit_param_check")

RANGES = {"r1": {"from_deg": 0.0, "to_deg": 180.0, "face_deg": 60.0, "berm_m": 6.0}, "r2": {"from_deg": 180.0, "to_deg": 360.0, "face_deg": 45.0, "berm_m": 6.0}}


class KeysTest(unittest.TestCase):
    def test_the_keys_of_each_family_are_read_and_the_others_are_not(self) -> None:
        """RF-018-07, RF-018-15, RF-018-06: las tres familias se reconocen; una entidad, un perfil de pista o un texto cualquiera, no."""
        self.assertEqual(pit_param_check.parse_rose_key("des.rose.roseta_1.r2.to_deg")[:2], ("roseta_1", "r2"))
        self.assertEqual(pit_param_check.parse_ramp_key("des.pitramp.rampa_1.gradient_pct")[0], "rampa_1")
        self.assertEqual(pit_param_check.parse_sector_key("des.pit.pit_001.profile.perimeter__")[::2], ("PIT-001", "perimeter__"))
        for key in ("des.pit.pit_001.profile", "des.rose.roseta_1.to_deg", "des.pitramp.rampa_1.otro", "des.roadprofile.p.max_gradient_pct", None, 5):
            with self.subTest(key=key):
                self.assertIsNone(pit_param_check.parse_rose_key(key) or pit_param_check.parse_ramp_key(key) or pit_param_check.parse_sector_key(key))


class RuleTest(unittest.TestCase):
    def test_the_rose_rules_are_the_ones_of_creating_it(self) -> None:
        for param, bad, expected in (("to_deg", 200.0, "des.pit_rose_overlap"), ("to_deg", 170.0, "des.pit_rose_gap"), ("face_deg", 90.0, "des.pit_rose_value_range")):
            with self.subTest(param=param, value=bad), self.assertRaises(messages.DesignError) as caught:
                pit_param_check.check_rose_edit("Roseta", "roseta", "r1", param, bad, RANGES)
            self.assertEqual(caught.exception.code, expected)
        pit_param_check.check_rose_edit("Roseta", "roseta", "r1", "face_deg", 55.0, RANGES)
        pit_param_check.check_rose_edit("Roseta", "roseta", "r1", "to_deg", None, RANGES)

    def test_a_rose_with_values_missing_only_checks_the_value(self) -> None:
        half = {"r1": {"from_deg": 0.0, "to_deg": 90.0, "face_deg": None, "berm_m": None}}
        pit_param_check.check_rose_edit("Roseta", "roseta", "r1", "face_deg", 55.0, half)

    def test_the_gradient_of_a_ramp_does_not_pass_the_maximum_of_its_road_profile(self) -> None:
        current = {"gradient_pct": 8.0, "road_profile": "pista"}
        with self.assertRaises(messages.DesignError) as caught:
            pit_param_check.check_ramp_edit("Rampa", "rampa", "gradient_pct", 12.5, current, lambda code: ("Pista", 10.0))
        self.assertEqual((caught.exception.code, caught.exception.values["limit"]), ("des.pit_ramp_gradient_over", 10.0))
        pit_param_check.check_ramp_edit("Rampa", "rampa", "gradient_pct", 10.0, current, lambda code: ("Pista", 10.0))
        pit_param_check.check_ramp_edit("Rampa", "rampa", "transition_m", 4.0, {**current, "gradient_pct": 12.5}, lambda code: ("Pista", 10.0))  # otro valor: no lo cruza
        with self.assertRaises(messages.DesignError):
            pit_param_check.check_ramp_edit("Rampa", "rampa", "road_profile", "estrecha", {"gradient_pct": 8.0, "road_profile": "pista"}, lambda code: ("Estrecha", 6.0))


if __name__ == "__main__":
    unittest.main()
