# SPDX-License-Identifier: GPL-3.0-or-later
"""El bucle de la rampa dentro de ``ascend`` (spec 018, T21c; HU-018-3; RF-018-16 a 21, RF-018-25; CE-018-05 y 06; plan 018 §5.4 A8 y A9).

CE-018-05 y 06 por ``pit_bench.ascend`` con las rampas de la corta (``job.ramps``, ``job.road_profiles`` y ``job.ramp_starts`` ya resueltos): 125 m de rampa por banco a 8,000 %
en la espiral (695 m de eje con los enlaces) y 100 m por banco en el zig-zag, con las aristas del pie partidas en los extremos del tramo y la cresta retranqueada con el término."""

from __future__ import annotations

import dataclasses
import math
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support import pit_ramp_hand as hand
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design import test_pit_bench_up as up

pit_bench = import_geoblender("design.pit_bench")
pit_model = import_geoblender("design.pit_model")
pit_ramp = import_geoblender("design.pit_ramp")
ramp_def = import_geoblender("design.pit_ramp_def")
messages = import_geoblender("design.messages")

W = float(hand.SECTION_M)
FACE_DEG = 60.0
ARC_PARAMS = up.params(arc_tol_m=pd.HYPOTHESES.arc_m, simplify_m=1e-6)
"""La tolerancia de arco de la corta con rampa (5 cm, la de la prueba de la T15: con 1 mm el desfase con la cara que salta ``W`` en cada rampa cuesta 36 s)."""


def road(**changes: float) -> object:
    return rd.road_profile(dataclasses.replace(rd.PROFILE, **changes))


def spiral_job(start: object = None, **changes: object) -> object:
    profile = road(min_radius_m=7.0)
    ramp = ramp_def.PitRampDef("rampa", "Rampa 1", "spiral", "ccw", "banco 0", 8.0, profile.code, 0.0)
    return up.job(ramps=(ramp,), road_profiles=(profile,), ramp_starts=(start or pit_model.RampStart("rampa", bench=0),), params=ARC_PARAMS, **changes)


def zigzag_job(**changes: object) -> object:
    profile = road(min_radius_m=8.0)
    ramp = ramp_def.PitRampDef("rampa", "Rampa 1", "zigzag", "ccw", "banco 0", 10.0, profile.code, 0.0, 12.0, 40.0)
    sources = (pit_model.PitSource("fondo", pd.absolute(pd.rect_ring(pd.ZIGZAG_LENGTH_M, pd.ZIGZAG_WIDTH_M)), pd.FLOOR_Z_M),)
    return up.job(ramps=(ramp,), road_profiles=(profile,), ramp_starts=(pit_model.RampStart("rampa", bench=0),), sources=sources, params=ARC_PARAMS, **changes)


def line_of(found: object, kind: str, bench: int) -> np.ndarray:
    return next(item for item in found.polylines if item.kind == kind and item.bench == bench).vertices[:, :2]


class SpiralTest(unittest.TestCase):
    """CE-018-05 por ``ascend``: 125 m de rampa por banco a 8,000 %, 695 m de eje."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = pit_bench.ascend(spiral_job())
        cls.checked = cls.found.ramps[0]

    def test_five_benches_and_one_checked_ramp(self) -> None:
        self.assertEqual(self.found.count, 5)
        self.assertEqual(len(self.found.ramps), 1)
        self.assertEqual(self.checked.code, "rampa")
        self.assertTrue(self.found.reliable)

    def test_levels_and_gradient(self) -> None:
        """CE-018-05: la cota de cada banco, su ancla, y la pendiente del eje, la de la rampa."""
        self.assertEqual(set(np.unique(self.checked.benches)), {0, 1, 2, 3, 4})
        self.assertEqual((float(self.checked.z[0]), float(self.checked.z[-1])), (125.0, 175.0))
        self.assertLessEqual(self.checked.max_gradient_pct, 8.05)

    def test_125_m_of_ramp_per_bench(self) -> None:
        """CE-018-05: la construcción da 5 tramos de 125 m a 8,000 % (a ≤ 10⁻⁹) y un eje de unos 695 m."""
        total = hand.spiral_totals()
        axis = self.checked.path.axis
        self.assertAlmostEqual(axis[-1, 2] - axis[0, 2], 50.0, delta=1e-9)
        self.assertAlmostEqual(self.checked.length_m, float(total.axis_m), delta=40.0)
        self.assertFalse(self.checked.mean_exceeded)

    def test_feet_are_split_at_the_ends_of_the_tramo(self) -> None:
        """T21c: el pie de cada banco con rampa lleva vértices nuevos en el inicio y el fin del tramo."""
        feet = [item for item in self.found.polylines if item.kind == "foot"]
        self.assertEqual(len(feet), 5)
        self.assertTrue(all(len(item.vertices) > 2 for item in feet))
        self.assertGreater(len(feet[0].vertices), 720)

    def test_crest_follows_the_oracle_in_the_ramp(self) -> None:
        """RF-018-16: la cresta del banco 0 está a ``W + (z_{k+1} − z(s))/tan α`` del pie: de ``W + h/tan α`` al empezar a ``W`` al acabar."""
        foot = line_of(self.found, "foot", 0)
        crest = line_of(self.found, "crest", 0)
        near = np.array([float(np.hypot(*(foot - point).T).min()) for point in crest])
        full = W + 10.0 / math.tan(math.radians(FACE_DEG))
        self.assertAlmostEqual(float(near.max()), full, delta=0.3)
        self.assertTrue(bool(((near > W - 0.1) & (near < W + 0.5)).any()))
        self.assertTrue(bool(((near > 0.5 * (W + full) - 0.5) & (near < 0.5 * (W + full) + 0.5)).any()))

    def test_deterministic_bit_by_bit(self) -> None:
        again = pit_bench.ascend(spiral_job())
        for first, second in zip(self.found.polylines, again.polylines, strict=True):
            self.assertTrue(np.array_equal(first.vertices, second.vertices))
        self.assertTrue(np.array_equal(self.checked.path.axis, again.ramps[0].path.axis))

    def test_without_ramps_nothing_changes(self) -> None:
        plain = pit_bench.ascend(up.job())
        self.assertEqual(plain.ramps, ())
        self.assertEqual(len(plain.polylines[0].vertices), 720)


class StartTest(unittest.TestCase):
    def test_start_on_bench_two_starts_there(self) -> None:
        """RF-018-15: ``banco 2`` sitúa el inicio sobre la polilínea de ese banco: la rampa sube desde el banco 2."""
        found = pit_bench.ascend(spiral_job(pit_model.RampStart("rampa", bench=2)))
        self.assertEqual(set(np.unique(found.ramps[0].benches)), {2, 3, 4})
        self.assertEqual(float(found.ramps[0].z[0]), 145.0)

    def test_start_on_a_point_of_a_layer(self) -> None:
        north = pd.absolute((pd.CENTER + np.array([0.0, pd.CIRCLE_RADIUS_M]))[None, :])[0]
        found = pit_bench.ascend(spiral_job(pit_model.RampStart("rampa", point=(float(north[0]), float(north[1])), layer="gis_pts", name="p")))
        self.assertAlmostEqual(float(found.ramps[0].path.axis[0, 1]), float(north[1]) + W / 2.0, delta=0.5)

    def test_bench_not_reached_is_rejected(self) -> None:
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(spiral_job(pit_model.RampStart("rampa", bench=9)))
        self.assertEqual(caught.exception.code, "des.pit_start_invalid")


class ZigzagTest(unittest.TestCase):
    """CE-018-06 por ``ascend``: 100 m de tramo con g = 10 % en el primer banco. Con más de un banco, el pie real (con el escalón de la cresta retranqueada) no tiene un lado recto
    paralelo donde volver: hoy se rechaza con el banco y los metros (RF-018-20), a la espera de DIFF-018d (T21c2)."""

    def test_one_bench_has_a_tramo_of_100_m_at_10_percent(self) -> None:
        found = pit_bench.ascend(zigzag_job(start=pd.flat_terrain(pd.GRID, 135.0)))
        self.assertEqual(found.count, 1)
        checked = found.ramps[0]
        self.assertAlmostEqual(float(checked.path.axis[-1, 2] - checked.path.axis[0, 2]), 10.0, delta=1e-9)
        self.assertAlmostEqual(checked.length_m, 100.0, delta=1e-6)
        self.assertLessEqual(checked.max_gradient_pct, 10.0 + 1e-6)
        foot = line_of(found, "foot", 0)
        self.assertGreater(len(foot), 6)  # el lado del tramo, partido en su inicio, su fin y trozos de ≤ 5 m para que la cresta siga la pared

    def test_return_tramo_without_a_parallel_side_is_rejected_with_the_bench(self) -> None:
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(zigzag_job())
        self.assertEqual(caught.exception.code, "des.pit_no_ramp_fit")
        self.assertEqual(caught.exception.values["bench"], 1)


class DescendTest(unittest.TestCase):
    def test_descent_with_a_ramp_is_not_calculated_yet(self) -> None:
        with self.assertRaises(ValueError):
            pit_bench.descend(dataclasses.replace(spiral_job(), request=up.request(mode="down")))


if __name__ == "__main__":
    unittest.main()
