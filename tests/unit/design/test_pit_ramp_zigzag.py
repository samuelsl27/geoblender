# SPDX-License-Identifier: GPL-3.0-or-later
"""La rampa en zig-zag de la corta (spec 018, T16; HU-018-3; RF-018-17, RF-018-25; CE-018-06; plan 018 §5.4 A9).

CE-018-06 con el oráculo a mano de ``tests/support/pit_ramp_hand.py`` (T14): sobre la corta rectangular de 200 m de largo, con g = 10 % y
h = 10 m, cada banco pide 100 m de tramo; las plataformas de retorno (horizontales, de ``max(min_platform, π·Rgiro)`` m de eje) hacen de
enlace y cuentan en el eje y no en la rampa; el número de retornos, la longitud del eje y el desnivel igualan el cálculo a mano a ≤ 10⁻⁹ m;
una plataforma que no cabe da la longitud necesaria y la disponible."""

from __future__ import annotations

import math
import unittest
from fractions import Fraction

import numpy as np

from tests.support import pit_data as pd
from tests.support import pit_ramp_hand as hand
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design import test_pit_bench_up as up

pit_ramp = import_geoblender("design.pit_ramp")
pit_model = import_geoblender("design.pit_model")
ramp_def = import_geoblender("design.pit_ramp_def")

W = float(hand.SECTION_M)
LINK = float(hand.link_length())
"""Lo que separa el eje de un banco del del siguiente: ``W + B`` = 17,5 m."""
G_PCT = 10.0
TURN_M = 12.0
MIN_PLATFORM_M = 40.0
PLATFORM_M = max(MIN_PLATFORM_M, math.pi * TURN_M)
"""La plataforma de eje de la prueba: ``max(40; 37,70)`` = 40 m (≥ 17,5, el paso lateral)."""
SOUTH = np.array([pd.CENTER[0], pd.CENTER[1] - pd.ZIGZAG_WIDTH_M / 2.0])
"""Un punto del lado sur del pie del banco 0."""
FACE_DEG = 60.0


def feet(count: int = pd.BENCHES) -> list[np.ndarray]:
    """Los pies de los bancos: rectángulos concéntricos, cada uno ``W + B`` más afuera que el anterior (el banco 0 es el de CE-018-06)."""
    return [pd.rect_ring(pd.ZIGZAG_LENGTH_M + 2.0 * LINK * k, pd.ZIGZAG_WIDTH_M + 2.0 * LINK * k) for k in range(count)]


def zigzag(count: int = pd.BENCHES, sense: str = "ccw", platform_m: float = PLATFORM_M, point: np.ndarray = SOUTH) -> object:
    return pit_ramp.build_zigzag(feet(count), point, z_first_m=125.0, rise_m=10.0, gradient_pct=G_PCT, width_m=W, platform_m=platform_m,
                                 sense=sense)


class OracleTest(unittest.TestCase):
    """CE-018-06: tramos, retornos, eje y desnivel contra el cálculo a mano."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = zigzag()
        cls.total = hand.zigzag_totals(pd.BENCHES, Fraction(PLATFORM_M).limit_denominator(10 ** 6))

    def test_100_m_of_tramo_per_bench_at_10_percent(self) -> None:
        """CE-018-06, RF-018-17: cada banco pide 100 m de tramo recto a 10 % (a ≤ 10⁻⁹) y sube de su cota a la del siguiente."""
        self.assertEqual(len(self.found.tramos), pd.BENCHES)
        for bench, one in enumerate(self.found.tramos):
            with self.subTest(bench=bench):
                run = float(np.hypot(*(one.axis[-1, :2] - one.axis[0, :2])))
                self.assertAlmostEqual(run, float(self.total.tramo_m), delta=1e-9)
                self.assertAlmostEqual(one.ramp_m, 100.0, delta=1e-9)
                self.assertAlmostEqual(float(one.axis[-1, 2] - one.axis[0, 2]) / run, 0.10, delta=1e-9)
                self.assertEqual((one.axis[0, 2], one.axis[-1, 2]), (125.0 + 10.0 * bench, 135.0 + 10.0 * bench))

    def test_tramos_alternate_direction(self) -> None:
        """RF-018-17: el sentido se invierte en cada retorno (el banco 0, hacia el este; el 1, hacia el oeste…)."""
        signs = [math.copysign(1.0, float(one.axis[-1, 0] - one.axis[0, 0])) for one in self.found.tramos]
        self.assertEqual(signs, [1.0, -1.0, 1.0, -1.0, 1.0])
        for one in self.found.tramos:
            self.assertAlmostEqual(float(one.axis[-1, 1] - one.axis[0, 1]), 0.0, delta=1e-12)

    def test_returns_length_and_drop_match_the_hand_calculation(self) -> None:
        """CE-018-06: 4 retornos, eje ``5·100 + 4·P`` y desnivel 50 m a ≤ 10⁻⁹; las plataformas no cuentan en la rampa."""
        found = self.found
        self.assertEqual(found.returns, 4)
        self.assertAlmostEqual(found.ramp_m, 500.0, delta=1e-9)
        self.assertAlmostEqual(found.platforms_m, 4.0 * PLATFORM_M, delta=1e-9)
        self.assertAlmostEqual(found.axis_m, float(self.total.axis_m), delta=1e-6)
        self.assertAlmostEqual(found.axis_m, 500.0 + 4.0 * PLATFORM_M, delta=1e-9)
        self.assertAlmostEqual(found.rise_m, 50.0, delta=1e-9)
        self.assertAlmostEqual(found.path.length_m, found.axis_m, delta=1e-9)
        self.assertEqual(found.platform_m, PLATFORM_M)

    def test_platforms_are_horizontal_and_link_the_axes(self) -> None:
        """DIFF-018b / CE-018-06: la plataforma es horizontal a ``z_{k+1}``, mide ``P`` y une el fin del tramo ``k`` con el inicio del ``k + 1``."""
        for k, plat in enumerate(self.found.platforms):
            with self.subTest(retorno=k):
                np.testing.assert_array_equal(plat[:, 2], 135.0 + 10.0 * k)
                np.testing.assert_array_equal(plat[0], self.found.tramos[k].axis[-1])
                np.testing.assert_array_equal(plat[-1], self.found.tramos[k + 1].axis[0])
                self.assertAlmostEqual(float(np.hypot(*np.diff(plat[:, :2], axis=0).T).sum()), PLATFORM_M, delta=1e-9)
                self.assertAlmostEqual(float(np.hypot(*(plat[-1, :2] - plat[1, :2]))), LINK, delta=1e-9)

    def test_axis_is_the_foot_moved_half_the_section_outward(self) -> None:
        """El eje del tramo ``k`` va a ``W/2`` fuera del lado sur de su pie."""
        for bench, one in enumerate(self.found.tramos):
            with self.subTest(bench=bench):
                south = pd.CENTER[1] - pd.ZIGZAG_WIDTH_M / 2.0 - LINK * bench
                np.testing.assert_allclose(one.axis[:, 1], south - W / 2.0, atol=1e-9)

    def test_path_is_continuous_and_monotonic_in_z(self) -> None:
        axis = self.found.path.axis
        self.assertTrue(bool((np.diff(axis[:, 2]) >= 0.0).all()))
        self.assertEqual((axis[0, 2], axis[-1, 2]), (125.0, 175.0))
        np.testing.assert_allclose(self.found.path.half_width_m, W / 2.0)
        self.assertAlmostEqual(self.found.path.gradient_mean_pct, 50.0 / (500.0 + 4.0 * PLATFORM_M) * 100.0, delta=1e-9)


class SenseAndStartTest(unittest.TestCase):
    def test_clockwise_goes_the_other_way_from_the_other_end(self) -> None:
        """RF-018-25: en sentido horario el banco 0 sube hacia el oeste desde el extremo este del lado."""
        one = zigzag(sense="cw")
        self.assertLess(float(one.tramos[0].axis[-1, 0] - one.tramos[0].axis[0, 0]), 0.0)
        self.assertAlmostEqual(float(one.tramos[0].axis[0, 0]), pd.CENTER[0] + pd.ZIGZAG_LENGTH_M / 2.0, delta=1e-9)
        self.assertAlmostEqual(one.axis_m, 500.0 + 4.0 * PLATFORM_M, delta=1e-9)

    def test_the_longest_side_containing_the_start_point(self) -> None:
        """Un punto en el lado este (60 m) elige ese lado; en la esquina, el más largo de los dos (el sur, de 200 m)."""
        corner = np.array([pd.CENTER[0] + 100.0, pd.CENTER[1] - 30.0])
        one = zigzag(count=1, point=corner)
        self.assertAlmostEqual(float(one.tramos[0].axis[0, 1]), pd.CENTER[1] - 30.0 - W / 2.0, delta=1e-9)

    def test_a_short_side_cannot_hold_the_tramo(self) -> None:
        east = np.array([pd.CENTER[0] + 100.0, pd.CENTER[1]])
        with self.assertRaises(pit_ramp.ZigzagDoesNotFit) as caught:
            zigzag(count=1, point=east)
        self.assertAlmostEqual(caught.exception.needed_m, 100.0, delta=1e-9)
        self.assertAlmostEqual(caught.exception.available_m, pd.ZIGZAG_WIDTH_M, delta=1e-9)

    def test_deterministic(self) -> None:
        self.assertTrue(np.array_equal(zigzag().path.axis, zigzag().path.axis))


class DoesNotFitTest(unittest.TestCase):
    def test_platform_that_does_not_fit_gives_needed_and_available(self) -> None:
        """CE-018-06, RF-018-20: ``h/g + P`` > lado recto: 100 + 135,5 = 235,5 m necesarios en un lado de 200 m."""
        with self.assertRaises(pit_ramp.ZigzagDoesNotFit) as caught:
            zigzag(platform_m=2.0 * TURN_M + W + 100.0)
        self.assertAlmostEqual(caught.exception.needed_m, 100.0 + 2.0 * TURN_M + W + 100.0, delta=1e-9)
        self.assertAlmostEqual(caught.exception.available_m, 200.0, delta=1e-9)
        self.assertIn("necesita", str(caught.exception))
        self.assertIsInstance(caught.exception, pit_ramp.RampDoesNotFit)

    def test_oracle_fit_rule(self) -> None:
        """La regla del oráculo (``h/g + P ≤ lado``) y la del producto coinciden en el límite: cabe con P = 100 y no con 100,001."""
        self.assertTrue(hand.zigzag_fit(Fraction(200), Fraction(100))[2])
        zigzag(count=2, platform_m=100.0)
        with self.assertRaises(pit_ramp.ZigzagDoesNotFit):
            zigzag(count=2, platform_m=100.001)

    def test_platform_length_is_the_larger_of_minimum_and_half_turn(self) -> None:
        self.assertEqual(pit_ramp.platform_length_m(12.0, 40.0), 40.0)
        self.assertAlmostEqual(pit_ramp.platform_length_m(20.0, 40.0), 20.0 * math.pi, delta=1e-12)
        with self.assertRaises(ValueError):
            pit_ramp.platform_length_m(0.0, 40.0)

    def test_bad_values_are_program_errors(self) -> None:
        with self.assertRaises(ValueError):
            zigzag(sense="x")
        with self.assertRaises(ValueError):
            pit_ramp.build_zigzag([], SOUTH, z_first_m=0.0, rise_m=10.0, gradient_pct=10.0, width_m=W, platform_m=40.0)


class EdgeTermTest(unittest.TestCase):
    """RF-018-17: la cresta se retranquea ``W + (z_{k+1} − z(s))/tan α`` a lo largo del tramo (el oráculo de la T14)."""

    def test_term_follows_the_oracle_in_the_stations(self) -> None:
        one = zigzag(count=1).tramos[0]
        x0 = float(one.axis[0, 0])
        stations = [x0 + 12.5, x0 + 37.5, x0 + 62.5, x0 + 87.5]
        y = pd.CENTER[1] - pd.ZIGZAG_WIDTH_M / 2.0
        xs = [x0, *[x0 + 25.0 * i for i in range(1, 5)]]
        ring = np.array([[xs[0], y], [xs[1], y], [xs[2], y], [xs[3], y], [xs[4], y],
                         [pd.CENTER[0] + 100.0, pd.CENTER[1] + 30.0], [pd.CENTER[0] - 100.0, pd.CENTER[1] + 30.0]])
        extra = pit_ramp.zigzag_edge_extra_m(one, ring, FACE_DEG)
        self.assertEqual(extra[5:].tolist(), [0.0, 0.0])
        for i, s in enumerate(stations):
            face = Fraction(10) - Fraction(1, 10) * Fraction(s - x0).limit_denominator(1000)
            wanted = float(hand.setback(face)) - 10.0 / math.tan(math.radians(FACE_DEG))
            self.assertAlmostEqual(float(extra[i]), wanted, delta=1e-9)
            self.assertAlmostEqual(float(pit_ramp.crest_distance_m(one, s - x0, FACE_DEG)), float(hand.setback(face)), delta=1e-9)

    def test_a_single_long_edge_uses_its_midpoint(self) -> None:
        one = zigzag(count=1).tramos[0]
        y = pd.CENTER[1] - pd.ZIGZAG_WIDTH_M / 2.0
        x0 = float(one.axis[0, 0])
        ring = np.array([[x0, y], [x0 + 100.0, y], [x0 + 100.0, y + 60.0], [x0, y + 60.0]])
        extra = pit_ramp.zigzag_edge_extra_m(one, ring, FACE_DEG)
        self.assertAlmostEqual(float(extra[0]), W - 0.1 * 50.0 / math.tan(math.radians(FACE_DEG)), delta=1e-9)


class StepsTest(unittest.TestCase):
    def test_steps_build_the_same_zigzag_from_the_polylines(self) -> None:
        """A9: ``zigzag_steps`` sobre los pies absolutos da el mismo eje, el ``RampPath`` y los totales de CE-018-06."""
        polylines = []
        for bench, ring in enumerate(feet()):
            xy = pd.absolute(ring)
            for kind, z in (("foot", 125.0 + 10.0 * bench), ("crest", 135.0 + 10.0 * bench)):
                polylines.append(pit_model.Polyline(kind, bench, np.column_stack([xy, np.full(len(xy), z)])))
        road = rd.road_profile()
        ramp = ramp_def.PitRampDef("zz", "ZZ", "zigzag", "ccw", "banco 0", G_PCT, road.code, 0.0, TURN_M, MIN_PLATFORM_M)
        job = up.job(ramps=(ramp,), road_profiles=(road,))
        steps = list(pit_ramp.zigzag_steps(job, polylines, ramp, pd.absolute(SOUTH[None, :])[0]))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        found = steps[-1].result
        self.assertEqual((found.returns, len(found.tramos)), (4, 5))
        self.assertAlmostEqual(found.axis_m, 500.0 + 4.0 * PLATFORM_M, delta=1e-9)
        self.assertAlmostEqual(found.rise_m, 50.0, delta=1e-9)
        self.assertEqual((found.path.code, found.path.bench), ("zz", 0))
        local = zigzag().path.axis
        np.testing.assert_allclose(found.path.axis[:, :2] - pd.absolute(np.zeros((1, 2)))[0], local[:, :2], atol=1e-6)
        again = list(pit_ramp.zigzag_steps(job, polylines, ramp, pd.absolute(SOUTH[None, :])[0]))[-1].result
        self.assertTrue(np.array_equal(found.path.axis, again.path.axis))

    def test_spiral_type_is_a_program_error(self) -> None:
        road = rd.road_profile()
        ramp = ramp_def.PitRampDef("sp", "SP", "spiral", "ccw", "banco 0", 8.0, road.code, 0.0)
        job = up.job(ramps=(ramp,), road_profiles=(road,))
        with self.assertRaises(ValueError):
            list(pit_ramp.zigzag_steps(job, [], ramp, (0.0, 0.0)))


if __name__ == "__main__":
    unittest.main()
