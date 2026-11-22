# SPDX-License-Identifier: GPL-3.0-or-later
"""El oráculo a mano de las rampas (spec 018, T14; RF-018-16, 17, 21; CE-018-05 y 06): se prueba a sí mismo contra las cifras de la spec."""

from __future__ import annotations

import unittest
from decimal import Decimal
from fractions import Fraction

from tests.support import pit_data as pd
from tests.support import pit_ramp_hand as hand

TOL = Decimal("1e-12")


class SpiralTest(unittest.TestCase):
    def test_125_m_per_bench_at_exactly_8_percent(self) -> None:
        """CE-018-05: 125 m de eje por banco; la pendiente es 8,000 % exacta (aritmética racional)."""
        self.assertEqual(hand.run_length(), Fraction(125))
        self.assertEqual(float(hand.run_length()), pd.ramp_run_by_hand(10.0, pd.SPIRAL_GRADE_PCT))
        for bench in range(hand.BENCHES):
            stations = hand.tramo_stations(bench)
            for a, b in zip(stations, stations[1:]):
                self.assertEqual((b.z_m - a.z_m) / (b.s_rel_m - a.s_rel_m), Fraction(8, 100))

    def test_each_tramo_goes_from_its_anchor_to_the_next(self) -> None:
        """CE-018-05: la cota de cada banco es su ancla; el fin del tramo ``k`` es la cota del ``k + 1``."""
        z = hand.anchors()
        self.assertEqual(z, tuple(Fraction(125 + 10 * k) for k in range(6)))
        for bench in range(hand.BENCHES):
            stations = hand.tramo_stations(bench)
            self.assertEqual((stations[0].z_m, stations[-1].z_m), (z[bench], z[bench + 1]))
            self.assertEqual(stations[-1].s_abs_m - stations[0].s_abs_m, 125)
        self.assertEqual(hand.tramo_stations(1)[0].z_m, hand.tramo_stations(0)[-1].z_m)

    def test_wall_height_goes_from_h_to_zero(self) -> None:
        """RF-018-16 (spec 0.3): la pared sobre la rampa mide entre h y 0 (no entre h y 2h: errata de plan H-3)."""
        stations = hand.tramo_stations(0)
        self.assertEqual((stations[0].face_height_m, stations[-1].face_height_m), (10, 0))
        heights = [s.face_height_m for s in stations]
        self.assertEqual(heights, sorted(heights, reverse=True))

    def test_setback_by_hand_in_eight_stations(self) -> None:
        """DIFF-018-2: ``W + (z_{k+1} − z(s))/tan α``: 17,2735… m al empezar, 11,5 m al acabar (W = 11,5 m, α = 60°)."""
        stations = hand.tramo_stations(0)
        self.assertEqual(len(stations), 8)
        root3 = Decimal(3).sqrt()
        for i, st in enumerate(stations):
            expected = Decimal("11.5") + Decimal(10) * (Decimal(7 - i) / Decimal(7)) / root3
            self.assertLess(abs(st.setback_m - expected), TOL)
        self.assertLess(abs(stations[0].setback_m - Decimal("17.2735026918962576")), TOL)
        self.assertEqual(stations[-1].setback_m, Decimal("11.5"))
        for st in stations[:-1]:
            tan = hand.face_gradient(st.face_height_m, st.setback_m)
            self.assertLess(abs(tan - Decimal(3).sqrt()), TOL)  # tan 60°: la cara no pasa de α
        self.assertIsNone(hand.face_gradient(Fraction(0), stations[-1].setback_m))

    def test_nominal_foot_radii_match_the_circle_of_ce_018_03(self) -> None:
        radii = hand.foot_radii()
        for found, (foot, _crest) in zip(radii, pd.circle_radii_by_hand()):
            self.assertLess(abs(float(found) - foot), 1e-9)

    def test_link_between_tramos_is_w_plus_berm(self) -> None:
        """DIFF-018b (propuesta): el enlace horizontal entre el fin del tramo ``k`` y el inicio del ``k + 1`` mide W + B = 17,5 m."""
        self.assertEqual(hand.link_length(), Fraction(35, 2))

    def test_totals(self) -> None:
        total = hand.spiral_totals()
        self.assertEqual((total.ramp_m, total.rise_m, total.ramp_gradient), (625, 50, Fraction(8, 100)))
        self.assertEqual((total.links, total.links_m, total.axis_m), (4, 70, 695))
        self.assertEqual(total.mean_gradient, Fraction(50, 695))

    def test_literal_reading_of_the_abscissas_breaks_the_plan_continuity(self) -> None:
        """El hallazgo G-4: con ``s_{k+1} = s_k + L_k`` sobre pies de radios distintos, el fin del tramo ``k`` y el inicio del
        ``k + 1`` caen en azimuts distintos (143,2° frente a 115,9° en el primer par)."""
        pairs = hand.literal_end_start_angles()
        self.assertAlmostEqual(pairs[0][0], 143.2394487827058, places=9)
        for end, start in pairs:
            self.assertGreater(end - start, 10.0)


class ZigzagTest(unittest.TestCase):
    def test_100_m_per_bench_at_10_percent(self) -> None:
        """CE-018-06: cada banco pide 100 m de tramo con g = 10 % y h = 10 m."""
        self.assertEqual(hand.run_length(gradient=hand.ZIGZAG_GRADIENT), 100)
        self.assertEqual(float(hand.run_length(gradient=hand.ZIGZAG_GRADIENT)), pd.ramp_run_by_hand(10.0, pd.ZIGZAG_GRADE_PCT))

    def test_totals_with_the_minimum_platform_and_the_turn_arc(self) -> None:
        """Cinco bancos: 4 retornos, desnivel 50 m, eje ``500 + 4·P``: 580 m con P = 20 (mínima de prueba) y 666 m con P = 2·Rgiro + W = 41,5."""
        short = hand.zigzag_totals(5, Fraction(20))
        self.assertEqual((short.returns, short.rise_m, short.ramp_m, short.platforms_m, short.axis_m), (4, 50, 500, 80, 580))
        reference = hand.zigzag_totals(5, Fraction(83, 2))
        self.assertEqual((reference.platforms_m, reference.axis_m), (166, 666))
        one = hand.zigzag_totals(1, Fraction(20))
        self.assertEqual((one.returns, one.axis_m, one.rise_m), (0, 100, 10))
        with self.assertRaises(ValueError):
            hand.zigzag_totals(0, Fraction(20))

    def test_platform_fit_on_a_straight_side(self) -> None:
        """RF-018-20 (propuesta): necesaria ``h/g + P``; cabe en los 200 m de CE-018-06 y no en 120 m (necesaria 141,5, disponible 120)."""
        self.assertEqual(hand.zigzag_fit(Fraction(200), Fraction(83, 2)), (Fraction(283, 2), 200, True))
        self.assertEqual(hand.zigzag_fit(Fraction(120), Fraction(83, 2)), (Fraction(283, 2), 120, False))

    def test_setback_along_a_zigzag_tramo(self) -> None:
        """RF-018-17: el mismo retranqueo que la espiral, tramo a tramo, con g = 10 %."""
        stations = hand.tramo_stations(0, gradient=hand.ZIGZAG_GRADIENT)
        self.assertEqual((stations[0].z_m, stations[-1].z_m, stations[-1].s_rel_m), (125, 135, 100))
        self.assertEqual(stations[-1].setback_m, Decimal("11.5"))


if __name__ == "__main__":
    unittest.main()
