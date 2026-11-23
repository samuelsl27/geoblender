# SPDX-License-Identifier: GPL-3.0-or-later
"""La rampa en espiral de la corta (spec 018, T15; HU-018-3; RF-018-16, RF-018-25; CE-018-05; plan 018 §5.4 A8).

CE-018-05 con el oráculo a mano de ``tests/support/pit_ramp_hand.py`` (T14, adaptado a la lectura del DIFF-018b: ``s`` por banco y
enlace horizontal de ``W + B`` m que cuenta en el eje y no en la rampa): 125 m de rampa por banco a 8,000 % (a ≤ 10⁻⁹), la cota de cada
banco igual a su ancla, la pared de ``h`` a 0, el retranqueo ``W + (z_{k+1} − z(s))/tan α`` en las mismas 8 estaciones, el sentido horario
y el antihorario, el desempate del punto de inicio y el eje de 5 bancos (695 m, pendiente media 7,19 %) con el desfase real de la corta."""

from __future__ import annotations

import dataclasses
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
pit_offset = import_geoblender("design.pit_offset")
pit_model = import_geoblender("design.pit_model")
ramp_def = import_geoblender("design.pit_ramp_def")
model = import_geoblender("design.model")

W = float(hand.SECTION_M)
G_PCT = 8.0
CENTER = np.array(pd.CENTER)
NORTH = CENTER + np.array([0.0, pd.CIRCLE_RADIUS_M])
"""El vértice más al norte del fondo circular (el 180 de 720)."""
FACE_DEG = 60.0
NOMINAL_M = 10.0 / math.tan(math.radians(FACE_DEG))


def tramo(sense: str = "ccw", start: np.ndarray = NORTH, ring: np.ndarray | None = None, **changes: object) -> object:
    values: dict[str, object] = dict(bench=0, z_foot_m=125.0, rise_m=10.0, gradient_pct=G_PCT, width_m=W, transition_m=0.0, sense=sense)
    values.update(changes)
    return pit_ramp.build_tramo(pd.circle_ring() if ring is None else ring, start, **values)


def offset(ring: np.ndarray, step: str, extra: np.ndarray | None = None) -> np.ndarray:
    steps = pit_offset.offset_polyline_steps(ring, step=step, side=1, tol=pd.HYPOTHESES.arc_m, simplify_m=1e-6, profile=pd.EXPL,
                                             extra_m=extra)
    for progress in steps:
        if progress.result is not None:
            rings = progress.result.result.rings
            assert len(rings) == 1
            return np.asarray(rings[0])
    raise AssertionError("sin resultado")


def build_spiral(sense: str = "ccw", transition_m: float = 0.0) -> tuple[list[object], list[np.ndarray], list[np.ndarray]]:
    """El bucle de la corta con el término de la rampa: pie, rampa, cresta con el término, pie siguiente (en locales)."""
    foot, point = pd.circle_ring(), NORTH
    tramos, feet, crests = [], [], []
    for bench in range(pd.BENCHES):
        one = pit_ramp.build_tramo(foot, point, bench=bench, z_foot_m=125.0 + 10.0 * bench, rise_m=10.0, gradient_pct=G_PCT, width_m=W,
                                   transition_m=transition_m, sense=sense)
        crest = offset(foot, "face", pit_ramp.edge_extra_m(one, foot, FACE_DEG))
        tramos.append(one)
        feet.append(foot)
        crests.append(crest)
        foot, point = offset(crest, "berm"), one.end_xy
    return tramos, feet, crests


class OracleTest(unittest.TestCase):
    """CE-018-05 sobre el fondo circular: el tramo del banco 0 contra el oráculo a mano."""

    def test_125_m_at_8_percent_exactly(self) -> None:
        """CE-018-05, RF-018-16: 125 m de rampa y 8,000 % a ≤ 10⁻⁹ en cada trozo; la cota del banco es su ancla y el fin, la del siguiente."""
        one = tramo()
        self.assertEqual(one.ramp_m, float(hand.run_length()))
        self.assertAlmostEqual(one.length_m, 125.0, delta=1e-12)
        run = np.hypot(*np.diff(one.axis[:, :2], axis=0).T)
        np.testing.assert_allclose(np.diff(one.axis[:, 2]) / run, 0.08, rtol=0, atol=1e-9)
        self.assertAlmostEqual(float(run.sum()), 125.0, delta=1e-9)
        self.assertEqual((one.axis[0, 2], one.axis[-1, 2]), (125.0, 135.0))
        self.assertEqual(float(hand.anchors()[0]), one.axis[0, 2])

    def test_axis_is_the_foot_moved_half_the_section(self) -> None:
        """RF-018-16: el eje va a ``W/2`` del pie (sobre el círculo de 50 m, a 55,75 m del centro, salvo la flecha de 720 lados)."""
        radii = np.hypot(*(tramo().axis[:, :2] - CENTER).T)
        self.assertLess(abs(float(radii.max()) - 55.75), 1e-3)
        self.assertGreater(float(radii.min()), 55.75 - 2e-3)

    def test_sweep_of_the_first_tramo(self) -> None:
        """DIFF-018b: ``s`` por banco; el tramo 0 barre el ángulo del oráculo (128,466°) desde el norte en sentido antihorario."""
        one = tramo()
        end = one.end_xy - CENTER
        angle = math.degrees(math.atan2(end[1], end[0]))
        start_angle = 90.0
        swept = (angle - start_angle) % 360.0
        self.assertAlmostEqual(swept, float(hand.first_tramo_sweep_deg()), delta=5e-3)

    def test_wall_and_setback_in_the_eight_stations(self) -> None:
        """DIFF-018-2: la pared de ``h`` a 0 y el retranqueo ``W + pared/tan 60°`` en las 8 estaciones del oráculo, a ≤ 10⁻⁹."""
        one = tramo()
        for st in hand.tramo_stations(0):
            s = float(st.s_rel_m)
            with self.subTest(s=s):
                self.assertAlmostEqual(float(pit_ramp.wall_height_m(one, s)), float(st.face_height_m), delta=1e-9)
                self.assertAlmostEqual(float(pit_ramp.crest_distance_m(one, s, FACE_DEG)), float(st.setback_m), delta=1e-9)
        self.assertEqual(float(pit_ramp.wall_height_m(one, 300.0)), 0.0)

    def test_edge_term_follows_the_oracle(self) -> None:
        """A2: el término de cada arista (``W − g·s/tan α`` en la rampa y 0 fuera) con la abscisa de su punto medio sobre el eje."""
        ring = pd.circle_ring()
        one = tramo(ring=ring)
        extra = pit_ramp.edge_extra_m(one, ring, FACE_DEG)
        edges = np.arange(pd.CIRCLE_VERTICES)
        order = (edges - 180) % pd.CIRCLE_VERTICES
        s_mid = (order + 0.5) * float(np.hypot(*(np.roll(pit_axis(ring), -1, axis=0) - pit_axis(ring)).T)[0])
        in_ramp = s_mid <= 125.0
        np.testing.assert_allclose(extra[in_ramp], W - 0.08 * s_mid[in_ramp] / math.tan(math.radians(FACE_DEG)), atol=1e-9)
        self.assertTrue(np.all(extra[~in_ramp & (s_mid > 125.0 + 1e-6)] == 0.0))
        self.assertAlmostEqual(float(extra[in_ramp][0]) + NOMINAL_M, W + 10.0 / math.tan(math.radians(FACE_DEG)), delta=0.1)


def pit_axis(ring: np.ndarray) -> np.ndarray:
    """El eje de un anillo circular de 720 lados desplazado ``W/2`` con el inglete (el que usa ``build_tramo``), a mano."""
    center = CENTER
    radial = ring - center
    unit = radial / np.hypot(*radial.T)[:, None]
    half = np.pi / pd.CIRCLE_VERTICES
    return ring + unit * (W / 2.0) / math.cos(half)


class SenseTest(unittest.TestCase):
    def test_clockwise_mirrors_counterclockwise(self) -> None:
        """RF-018-16: el sentido horario es el espejo del antihorario desde el norte (la corta circular es simétrica)."""
        ccw, cw = tramo("ccw"), tramo("cw")
        np.testing.assert_allclose(cw.axis[:, 0] - CENTER[0], -(ccw.axis[:, 0] - CENTER[0]), atol=1e-9)
        np.testing.assert_allclose(cw.axis[:, 1], ccw.axis[:, 1], atol=1e-9)
        np.testing.assert_allclose(cw.axis[:, 2], ccw.axis[:, 2], atol=1e-12)

    def test_edge_term_in_the_chosen_sense(self) -> None:
        """A2: el término sale por las aristas que recorre el tramo, en el sentido pedido (el primero tras el inicio lleva el mayor)."""
        ring = pd.circle_ring()
        ccw = pit_ramp.edge_extra_m(tramo("ccw"), ring, FACE_DEG)
        cw = pit_ramp.edge_extra_m(tramo("cw"), ring, FACE_DEG)
        self.assertEqual(int(np.argmax(ccw)), 180)
        self.assertEqual(int(np.argmax(cw)), 179)
        np.testing.assert_allclose(np.sort(ccw), np.sort(cw), atol=1e-9)

    def test_bad_sense_and_clockwise_ring_are_program_errors(self) -> None:
        with self.assertRaises(ValueError):
            tramo("left")
        with self.assertRaises(ValueError):
            tramo(ring=pd.circle_ring()[::-1])


class StartTest(unittest.TestCase):
    def test_nearest_point_of_the_foot(self) -> None:
        """RF-018-25: el inicio es el punto del pie más cercano al pedido."""
        point, edge, fraction, distance = pit_ramp.nearest_on_ring(pd.circle_ring(), CENTER + np.array([100.0, 0.0]))
        self.assertAlmostEqual(distance, 50.0, delta=1e-3)
        self.assertAlmostEqual(float(point[1] - CENTER[1]), 0.0, delta=1e-9)

    def test_tie_goes_to_the_first_clockwise_from_north(self) -> None:
        """P-15: desde el centro todo el pie está a la misma distancia; manda el primero en sentido horario desde el norte (0,25°)."""
        point, _edge, _fraction, distance = pit_ramp.nearest_on_ring(pd.circle_ring(), CENTER)
        offset_xy = point - CENTER
        azimuth = math.degrees(math.atan2(offset_xy[0], offset_xy[1])) % 360.0
        self.assertAlmostEqual(azimuth, 0.25, delta=1e-6)
        self.assertAlmostEqual(distance, 50.0 * math.cos(math.pi / 720.0), delta=1e-9)


class TransitionTest(unittest.TestCase):
    def test_flat_tail_and_linear_crest(self) -> None:
        """G-2: con ``L_t = 10`` el tramo mide 135 m (125 de rampa y 10 planos a la cota siguiente) y la cresta vuelve linealmente a la base."""
        ring = pd.circle_ring()
        one = tramo(ring=ring, transition_m=10.0)
        self.assertEqual((one.ramp_m, one.length_m), (125.0, 135.0))
        self.assertAlmostEqual(float(np.hypot(*np.diff(one.axis[:, :2], axis=0).T).sum()), 135.0, delta=1e-9)
        tail = one.axis[:, 2][-5:]
        self.assertTrue(np.all(tail == 135.0))
        extra = pit_ramp.edge_extra_m(one, ring, FACE_DEG)
        self.assertGreater(float(extra.min()), -1e-12)
        entering = extra[(180 - 22):180]
        self.assertTrue(np.all(np.diff(entering) > 0.0))
        self.assertLess(float(entering[0]), 0.3)
        self.assertAlmostEqual(float(extra[180]), W - 0.08 * 0.5 * 0.4871 / math.tan(math.radians(FACE_DEG)), delta=2e-2)

    def test_negative_term_with_a_narrow_section(self) -> None:
        """RF-018-16: con ``W < h/tan α`` el término es negativo al final de la rampa (cresta más cerca que la base) y el desfase lo admite."""
        ring = pd.circle_ring()
        one = tramo(ring=ring, width_m=3.0)
        extra = pit_ramp.edge_extra_m(one, ring, FACE_DEG)
        self.assertLess(float(extra.min()), 0.0)
        crest = offset(ring, "face", extra)
        self.assertGreater(len(crest), 100)


class DoesNotFitTest(unittest.TestCase):
    def test_longer_than_the_perimeter_is_rejected(self) -> None:
        """G-3: solo se rechaza si el tramo mide más que el perímetro del eje (351 m) ; sin envolver."""
        with self.assertRaises(pit_ramp.RampDoesNotFit) as caught:
            tramo(gradient_pct=1.0)
        self.assertEqual((caught.exception.bench, caught.exception.needed_m), (0, 1000.0))
        self.assertAlmostEqual(caught.exception.available_m, 2.0 * math.pi * 55.75, delta=0.05)
        self.assertEqual(tramo(gradient_pct=3.0).ramp_m, Fraction(10, 3).__float__() * 100.0)


class ChainTest(unittest.TestCase):
    """CE-018-05: los 5 bancos con el desfase real de la corta, el término de la rampa y el enlace horizontal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tramos, cls.feet, cls.crests = build_spiral()

    def test_every_tramo_is_125_m_at_8_percent_from_its_anchor(self) -> None:
        for bench, one in enumerate(self.tramos):
            with self.subTest(bench=bench):
                run = np.hypot(*np.diff(one.axis[:, :2], axis=0).T)
                np.testing.assert_allclose(np.diff(one.axis[:, 2]) / run, 0.08, rtol=0, atol=1e-9)
                self.assertAlmostEqual(float(run.sum()), 125.0, delta=1e-9)
                self.assertEqual((one.axis[0, 2], one.axis[-1, 2]), (125.0 + 10.0 * bench, 135.0 + 10.0 * bench))

    def test_links_are_w_plus_berm(self) -> None:
        """DIFF-018b: el enlace entre el fin del tramo ``k`` y el inicio del ``k + 1`` mide ``W + B`` = 17,5 m (la tolerancia de arco del
        desfase real a 5 cm acumula ≤ 0,25 m) y es horizontal."""
        for bench in range(1, pd.BENCHES):
            with self.subTest(bench=bench):
                gap = self.tramos[bench].axis[0] - self.tramos[bench - 1].axis[-1]
                self.assertEqual(float(gap[2]), 0.0)
                self.assertAlmostEqual(float(np.hypot(*gap[:2])), float(hand.link_length()), delta=0.25)

    def test_axis_of_five_benches(self) -> None:
        """CE-018-05: eje de 695 m (625 de rampa y 4 enlaces) y pendiente media 7,19 % ≤ pm, con la tolerancia del desfase."""
        axis = np.vstack([one.axis for one in self.tramos])
        length = float(np.hypot(*np.diff(axis[:, :2], axis=0).T).sum())
        total = hand.spiral_totals()
        self.assertAlmostEqual(length, float(total.axis_m), delta=1.0)
        self.assertAlmostEqual(float(axis[-1, 2] - axis[0, 2]) / length * 100.0, float(total.mean_gradient) * 100.0, delta=0.01)
        self.assertAlmostEqual(float(total.mean_gradient) * 100.0, 7.194, delta=1e-3)

    def test_steps_build_the_same_axis_from_the_polylines(self) -> None:
        """A8: ``spiral_steps`` sobre los pies y las crestas absolutos da el mismo eje, el ``RampPath`` y los totales."""
        polylines = []
        for bench in range(pd.BENCHES):
            for kind, ring, z in (("foot", self.feet[bench], 125.0 + 10.0 * bench), ("crest", self.crests[bench], 135.0 + 10.0 * bench)):
                xy = pd.absolute(ring)
                polylines.append(pit_model.Polyline(kind, bench, np.column_stack([xy, np.full(len(xy), z)])))
        road = rd.road_profile()
        ramp = ramp_def.PitRampDef("espiral", "Espiral", "spiral", "ccw", "banco 0", G_PCT, road.code, 0.0)
        job = up.job(ramps=(ramp,), road_profiles=(road,))
        steps = list(pit_ramp.spiral_steps(job, polylines, ramp, pd.absolute(NORTH[None, :])[0]))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        found = steps[-1].result
        self.assertEqual(len(found.tramos), pd.BENCHES)
        self.assertAlmostEqual(found.ramp_m, 625.0, delta=1e-9)
        self.assertAlmostEqual(found.links_m, float(hand.spiral_totals().links_m), delta=1.0)
        self.assertAlmostEqual(found.axis_m, float(hand.spiral_totals().axis_m), delta=1.0)
        self.assertEqual((found.path.code, found.path.bench), ("espiral", 0))
        np.testing.assert_allclose(found.path.half_width_m, W / 2.0)
        self.assertAlmostEqual(found.path.gradient_mean_pct, 7.194, delta=0.01)
        local = np.vstack([pit_ramp._coarse_end(one.axis, 1.5 * W) for one in self.tramos])  # DIFF-018c: el eje esqueleto acaba cada tramo en una recta
        np.testing.assert_allclose(found.path.axis[:, :2] - pd.absolute(np.zeros((1, 2)))[0], local[:, :2], atol=1e-6)
        again = list(pit_ramp.spiral_steps(job, polylines, ramp, pd.absolute(NORTH[None, :])[0]))[-1].result
        self.assertTrue(np.array_equal(found.path.axis, again.path.axis))

    def test_other_type_is_a_program_error(self) -> None:
        road = rd.road_profile()
        ramp = ramp_def.PitRampDef("zz", "ZZ", "zigzag", "ccw", "banco 0", 10.0, road.code, 0.0, 12.0, 20.0)
        job = up.job(ramps=(ramp,), road_profiles=(road,))
        with self.assertRaises(ValueError):
            list(pit_ramp.spiral_steps(job, [], ramp, (0.0, 0.0)))


if __name__ == "__main__":
    unittest.main()
