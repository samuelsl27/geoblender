# SPDX-License-Identifier: GPL-3.0-or-later
"""La definición de rampa de la corta (spec 018, T04; HU-018-3; RF-018-15; plan 018 §5.1, §5.2.2 y §5.2.3; ADR-0027; RF-009-24).

Lo puro: la validación de los valores de una definición de rampa (``0 < g ≤ pd`` del perfil de pista de la 017; transición ≥ 0; en el
zig-zag, el radio de giro y la plataforma mínima > 0), los derivados (la longitud de eje que pide un banco, ``h / g``, y la sección del
perfil de pista) con su cálculo a mano de 70 cifras, y el código del nombre. La tabla del proyecto y la operación ``des.edit_pit_ramps``
están en ``milestone_pit_rose_ramp_operation`` (paso «hito»).

La pendiente es ``gradient_pct`` (no ``grade_pct``: el glosario §14 reserva «grade» a la ley; errata del plan y de la spec 018).
"""

from __future__ import annotations

import unittest
from decimal import Decimal, localcontext
from typing import Any

from tests.support import pit_data as pd
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_profiles import profile_of

messages = import_geoblender("design.messages")
pit_ramp_def = import_geoblender("design.pit_ramp_def")
road_profiles = import_geoblender("design.road_profiles")

NAME = "RAMPA_NORTE"
CODE = "rampa_norte"
PD = rd.PROFILE.max_gradient_pct
"""La pendiente máxima de diseño del perfil de pista de referencia (%)."""
ROAD = "PISTA_PRINCIPAL"


def values(**changes: object) -> dict[str, object]:
    """Una espiral válida: 8 % (CE-018-05), sentido horario, desde el fondo, con la pista de referencia y 10 m de transición."""
    base: dict[str, object] = {"type": "spiral", "sense": "cw", "start": "fondo", "gradient_pct": 8.0,
                               "road_profile": "pista_principal", "transition_m": 10.0}
    base.update(changes)
    return {key: value for key, value in base.items() if value is not None}


def zigzag(**changes: object) -> dict[str, object]:
    return values(**{"type": "zigzag", "gradient_pct": 10.0, "turn_radius_m": 15.0, "min_platform_m": 20.0, **changes})


def check(data: dict[str, object], limit: float = PD) -> Any:
    return pit_ramp_def.check_ramp(NAME, CODE, data, max_gradient_pct=limit, road_profile_name=ROAD)


class _Case(unittest.TestCase):
    def rejected(self, data: dict[str, object], limit: float = PD) -> Any:
        with self.assertRaises(messages.DesignError) as caught:
            check(data, limit)
        return caught.exception


class ValidRampTest(_Case):
    def test_the_spiral_of_ce_018_05_is_valid(self) -> None:
        """RF-018-15, CE-018-05: la espiral de g = 8 % del perfil de pista de referencia."""
        self.assertGreater(PD, pd.SPIRAL_GRADE_PCT)
        found = check(values())
        self.assertEqual((found.code, found.name, found.type, found.sense, found.start, found.gradient_pct, found.road_profile,
                          found.transition_m), (CODE, NAME, "spiral", "cw", "fondo", 8.0, "pista_principal", 10.0))
        self.assertIsNone(found.turn_radius_m)
        self.assertIsNone(found.min_platform_m)

    def test_the_zigzag_of_ce_018_06_is_valid(self) -> None:
        """RF-018-15, CE-018-06: el zig-zag de g = 10 % con radio de giro y plataforma mínima."""
        found = check(zigzag(), 10.0)
        self.assertEqual((found.type, found.gradient_pct, found.turn_radius_m, found.min_platform_m), ("zigzag", 10.0, 15.0, 20.0))

    def test_the_gradient_may_equal_the_maximum(self) -> None:
        """RF-018-15: ``g ≤ pd``, con la igualdad admitida."""
        self.assertEqual(check(values(gradient_pct=PD)).gradient_pct, PD)

    def test_the_text_values_are_trimmed(self) -> None:
        self.assertEqual(check(values(start="  fondo ")).start, "fondo")


class RejectionTest(_Case):
    def test_a_gradient_over_the_maximum_is_rejected(self) -> None:
        """RF-018-15: ``g > pd`` se rechaza nombrando la rampa, el perfil de pista, la clave, g y pd."""
        error = self.rejected(values(gradient_pct=PD + 0.5))
        self.assertEqual((error.code, error.field, error.values["value"], error.values["limit"]),
                         ("des.pit_ramp_gradient_over", "des.pitramp.rampa_norte.gradient_pct", PD + 0.5, PD))
        self.assertIn(NAME, error.text)
        self.assertIn(ROAD, error.text)

    def test_a_gradient_over_the_maximum_of_a_stricter_profile_is_rejected(self) -> None:
        self.assertEqual(self.rejected(values(gradient_pct=8.0), 7.5).code, "des.pit_ramp_gradient_over")

    def test_a_gradient_out_of_range_is_rejected(self) -> None:
        """RF-018-15, RF-018-04: g ≤ 0 o > 100 fuera de su rango."""
        for gradient in (0.0, -3.0, 150.0):
            with self.subTest(gradient=gradient):
                self.assertEqual(self.rejected(values(gradient_pct=gradient), 200.0).code, "des.pit_ramp_value_range")

    def test_a_negative_transition_is_rejected(self) -> None:
        error = self.rejected(values(transition_m=-1.0))
        self.assertEqual((error.code, error.field), ("des.pit_ramp_value_range", "des.pitramp.rampa_norte.transition_m"))

    def test_a_zero_transition_is_valid(self) -> None:
        self.assertEqual(check(values(transition_m=0.0)).transition_m, 0.0)

    def test_the_type_and_the_sense_are_in_their_lists(self) -> None:
        for field, bad in (("type", "helix"), ("sense", "left")):
            with self.subTest(field=field):
                error = self.rejected(values(**{field: bad}))
                self.assertEqual((error.code, error.values["value"]), ("des.pit_ramp_value_range", bad))

    def test_a_missing_value_is_rejected(self) -> None:
        for field in ("type", "sense", "start", "gradient_pct", "road_profile", "transition_m"):
            with self.subTest(field=field):
                error = self.rejected(values(**{field: None}))
                self.assertEqual((error.code, error.field), ("des.pit_ramp_value_missing", f"des.pitramp.rampa_norte.{field}"))

    def test_a_blank_start_is_a_missing_value(self) -> None:
        self.assertEqual(self.rejected(values(start="   ")).code, "des.pit_ramp_value_missing")

    def test_the_zigzag_needs_its_turn_radius_and_platform(self) -> None:
        """RF-018-15 (HIPÓTESIS, D-19): sin valor por defecto; ``> 0``."""
        for field in ("turn_radius_m", "min_platform_m"):
            with self.subTest(field=field):
                self.assertEqual(self.rejected(zigzag(**{field: None}), 10.0).code, "des.pit_ramp_value_missing")
            with self.subTest(field=field, value=0.0):
                self.assertEqual(self.rejected(zigzag(**{field: 0.0}), 10.0).code, "des.pit_ramp_value_range")

    def test_the_spiral_does_not_need_them_but_checks_them_if_given(self) -> None:
        self.assertEqual(check(values(turn_radius_m=12.0)).turn_radius_m, 12.0)
        self.assertEqual(self.rejected(values(turn_radius_m=-1.0)).code, "des.pit_ramp_value_range")

    def test_unknown_values_are_a_program_error(self) -> None:
        with self.assertRaises(ValueError):
            check(values(pendiente=8.0))

    def test_a_wrong_type_is_a_program_error(self) -> None:
        with self.assertRaises(TypeError):
            check(values(gradient_pct="ocho"))
        with self.assertRaises(TypeError):
            check(values(start=5))

    def test_the_limit_must_be_positive(self) -> None:
        for limit in (0.0, -1.0, float("nan")):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                check(values(), limit)


class DerivedTest(unittest.TestCase):
    def test_the_length_needed_by_a_bench_is_h_over_g(self) -> None:
        """RF-018-15, CE-018-05 y 06: subir un banco de 10 m pide 125 m de eje con el 8 % y 100 m con el 10 % (cálculo a mano de
        70 cifras, error ≤ 10⁻⁹)."""
        with localcontext() as context:
            context.prec = 70
            cases = [(10.0, 8.0, Decimal(125)), (10.0, 10.0, Decimal(100)), (15.0, 7.5, Decimal(200)), (7.0, 6.0, Decimal(7) * 100 / 6)]
        for height, gradient, expected in cases:
            with self.subTest(height=height, gradient=gradient):
                found = pit_ramp_def.required_length_m(height, gradient)
                with localcontext() as context:
                    context.prec = 70
                    self.assertLessEqual(abs(Decimal(found) - expected) / expected, Decimal("1e-9"))
        self.assertEqual(pit_ramp_def.required_length_m(10.0, pd.SPIRAL_GRADE_PCT), pd.ramp_run_by_hand(10.0, pd.SPIRAL_GRADE_PCT))
        self.assertEqual(pit_ramp_def.required_length_m(10.0, pd.ZIGZAG_GRADE_PCT), pd.ramp_run_by_hand(10.0, pd.ZIGZAG_GRADE_PCT))

    def test_the_derived_values_of_a_definition(self) -> None:
        """RF-018-15: la longitud por banco, la longitud de la transición y, del perfil de pista, la sección (11,5 m con el de
        referencia de la spec 017: calzada 10,5 + arcén 0 + caballón 1)."""
        found = check(values())
        profile = road_profiles.derived(profile_of())
        result = pit_ramp_def.derived(found, 10.0, profile)
        self.assertEqual(result.length_per_bench_m, 125.0)
        self.assertEqual(result.transition_m, 10.0)
        self.assertEqual(result.section_m, profile.section_m)
        self.assertIsNone(pit_ramp_def.derived(found, 10.0).section_m)

    def test_the_inputs_of_the_derived_are_checked(self) -> None:
        for args in ((0.0, 8.0), (-1.0, 8.0), (10.0, 0.0), (10.0, -2.0), (float("nan"), 8.0), (10.0, float("inf"))):
            with self.subTest(args=args), self.assertRaises(ValueError):
                pit_ramp_def.required_length_m(*args)
        with self.assertRaises(TypeError):
            pit_ramp_def.required_length_m("10", 8.0)  # type: ignore[arg-type]


class CodeTest(unittest.TestCase):
    def test_the_code_comes_from_the_name_and_is_not_reused(self) -> None:
        """RF-018-15: ``[a-z][a-z0-9_]*`` ASCII, ``ramp`` delante si no empieza por letra, ``_2`` si ya está."""
        self.assertEqual(pit_ramp_def.ramp_code("RAMPA NORTE", []), "rampa_norte")
        self.assertEqual(pit_ramp_def.ramp_code("8%", []), "ramp_8")
        self.assertEqual(pit_ramp_def.ramp_code("Rampa norte", ["rampa_norte"]), "rampa_norte_2")
        self.assertEqual(pit_ramp_def.ramp_code("", []), "ramp")


if __name__ == "__main__":
    unittest.main()
