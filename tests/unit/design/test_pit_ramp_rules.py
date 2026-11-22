# SPDX-License-Identifier: GPL-3.0-or-later
"""Las reglas de la 017, los diagnósticos y la banda de la rampa de la corta (spec 018, T17; HU-018-3; RF-018-18, 19, 20, 21; plan 018 §5.4 A8 y A9, §5.7 P-11).

Se prueban con el zig-zag de CE-018-06 (ejes rectos de geometría conocida, tramos de 100 m y plataformas con esquinas de 90°) y con un tramo
de espiral suave; el perfil de pista de referencia (R 20 m, Rmín 12 m) y variantes."""

from __future__ import annotations

import ast
import dataclasses
import math
import time
import unittest
from pathlib import Path

import numpy as np

from tests.support import pit_data as pd
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design import test_pit_bench_up as up
from tests.unit.design import test_pit_ramp_zigzag as zz

pit_ramp = import_geoblender("design.pit_ramp")
pit_model = import_geoblender("design.pit_model")
ramp_def = import_geoblender("design.pit_ramp_def")
road_axis = import_geoblender("design.road_axis")
road_gradient = import_geoblender("design.road_gradient")
provenance = import_geoblender("design.provenance")
messages = import_geoblender("design.messages")

W = zz.W


def profile(**changes: float) -> object:
    return rd.road_profile(dataclasses.replace(rd.PROFILE, **changes))


def ramp(road: object, kind: str = "zigzag", g_pct: float = 10.0) -> object:
    extra = (12.0, 40.0) if kind == "zigzag" else ()
    return ramp_def.PitRampDef("rampa", "Rampa 1", kind, "ccw", "banco 0", g_pct, road.code, 0.0, *extra)


def job(road: object, **changes: object) -> object:
    return up.job(road_profiles=(road,), **changes)


def zigzag(g_pct: float = 10.0) -> object:
    """El zig-zag de CE-018-06 en absolutas (la corta de la prueba está en locales: se traslada a la rejilla del proyecto)."""
    found = zz.zigzag()
    shift = np.array([*pd.absolute(np.zeros((1, 2)))[0], 0.0])
    if g_pct != 10.0:
        feet = zz.feet()
        found = pit_ramp.build_zigzag(feet, zz.SOUTH, z_first_m=125.0, rise_m=10.0, gradient_pct=g_pct, width_m=W, platform_m=zz.PLATFORM_M)
    path = pit_model.RampPath("rampa", 0, found.path.axis + shift, found.path.half_width_m)
    tramos = tuple(dataclasses.replace(item, axis=item.axis + shift) for item in found.tramos)
    return dataclasses.replace(found, path=path, tramos=tramos)


def spiral_tramo() -> object:
    ring = pd.circle_ring()
    tramo = pit_ramp.build_tramo(ring, ring[180], bench=0, z_foot_m=125.0, rise_m=10.0, gradient_pct=8.0, width_m=W)
    shift = np.array([*pd.absolute(np.zeros((1, 2)))[0], 0.0])
    tramo = dataclasses.replace(tramo, axis=tramo.axis + shift)
    path = pit_model.RampPath("rampa", 0, tramo.axis, np.full(len(tramo.axis), W / 2.0))
    return pit_ramp.Spiral(path, (tramo,), tramo.ramp_m, 0.0)


SMALL_TURNS = dict(curve_radius_m=8.0, min_radius_m=6.0)
"""R 8 m y Rmín 6 m: las dos esquinas de 90° de una plataforma, a 17,5 m una de otra, caben (2·8 = 16 m)."""
CLEAN = dict(SMALL_TURNS, max_gradient_pct=14.0)
"""Y pd = 14 %: la curva de la esquina donde empieza un tramo reparte 2T de eje sobre un arco más corto (la Z es la de la línea en su abscisa, como en la 017) y
sube la pendiente del arco hasta 10 %·4/π = 12,73 %."""


class RadiusTest(unittest.TestCase):
    """RF-018-18: cada vértice, una curva con la regla de la 017 (se llama; no se repite)."""

    def test_corners_are_rounded_with_the_017_rule(self) -> None:
        road = profile(**CLEAN)
        found = zigzag()
        checked = pit_ramp.check_ramp(found, job(road), ramp(road))
        direct = road_axis.axis_of(found.path.axis[:, :2], 8.0, 6.0, 1.0)
        self.assertEqual(checked.axis.length_m, direct.length_m)
        self.assertEqual(checked.axis.curve_count, 8)
        self.assertEqual(checked.axis.min_radius_m, 8.0)
        self.assertEqual(checked.notices, ())
        self.assertLess(checked.length_m, found.path.length_m)

    def test_radius_that_fits_is_reduced_and_noticed(self) -> None:
        """Con R = 10 m no caben las tangentes en 17,5 m: baja a 8,75 m (≥ Rmín) y es un aviso con su banco y su lugar."""
        road = profile(curve_radius_m=10.0, min_radius_m=6.0)
        checked = pit_ramp.check_ramp(zigzag(), job(road), ramp(road))
        reduced = [item for item in checked.notices if item.code == "des.pit_ramp_radius_reduced"]
        self.assertEqual(len(reduced), 8)
        self.assertAlmostEqual(reduced[0].values["fitted"], 8.75, delta=1e-9)
        self.assertEqual(reduced[0].values["radius"], 10.0)
        self.assertEqual([item.values["bench"] for item in reduced[:2]], [1, 1])
        self.assertIn("banco 1", reduced[0].text("es"))

    def test_below_minimum_is_rejected_with_bench_and_place(self) -> None:
        """El perfil de referencia (R 20, Rmín 12): el radio que cabe, 8,75 m, es menor; se rechaza sin relajar nada (RF-018-20)."""
        road = profile()
        found = zigzag()
        before = found.path.axis.copy()
        with self.assertRaises(pit_ramp.DesignError) as caught:
            pit_ramp.check_ramp(found, job(road), ramp(road))
        error = caught.exception
        self.assertEqual(error.code, "des.pit_ramp_radius_below_min")
        self.assertAlmostEqual(error.values["value"], 8.75, delta=1e-3)
        self.assertEqual(error.values["limit"], 12.0)
        self.assertEqual(error.values["bench"], 1)
        self.assertIn("banco 1", error.text)
        self.assertTrue(np.array_equal(before, found.path.axis))

    def test_smooth_spiral_keeps_the_design_radius(self) -> None:
        road = profile()
        checked = pit_ramp.check_ramp(spiral_tramo(), job(road), ramp(road, "spiral", 8.0))
        self.assertEqual(checked.notices, ())
        self.assertGreaterEqual(checked.axis.min_radius_m, 20.0 - 1e-9)


class GradientTest(unittest.TestCase):
    """RF-018-19: el eje 3D con las reglas de la 017; cada incumplimiento, un aviso con banco, abscisa y lugar; sin corregir."""

    def test_clean_ramp_has_no_notices_and_the_z_of_the_construction(self) -> None:
        road = profile(**CLEAN)
        found = zigzag()
        checked = pit_ramp.check_ramp(found, job(road), ramp(road))
        self.assertEqual(checked.notices, ())
        self.assertAlmostEqual(checked.max_gradient_pct, 40.0 / math.pi, delta=0.05)
        self.assertEqual(float(checked.z[0]), 125.0)
        self.assertEqual(float(checked.z[-1]), 175.0)
        self.assertFalse(checked.mean_exceeded)
        self.assertIsNone(pit_ramp.confirm_mean(checked))

    def test_gradient_over_pd_is_a_notice_with_bench_station_and_place(self) -> None:
        road = profile(**SMALL_TURNS)
        found = zigzag(12.0)
        before = found.path.axis.copy()
        checked = pit_ramp.check_ramp(found, job(road), dataclasses.replace(ramp(road), gradient_pct=12.0))
        over = [item for item in checked.notices if item.code == "des.pit_ramp_gradient"]
        self.assertGreater(len(over), 0)
        first = over[0].values
        self.assertEqual(first["bench"], 0)
        self.assertAlmostEqual(first["gradient"], 12.0, delta=1e-6)
        self.assertEqual(first["limit"], 10.0)
        self.assertTrue(all(key in first for key in ("station", "x", "y")))
        self.assertEqual({item.values["bench"] for item in over}, {0, 1, 2, 3, 4})
        self.assertTrue(np.array_equal(before, found.path.axis))
        self.assertIn("banco 0", over[0].text("es"))

    def test_mean_over_pm_asks_for_the_confirmation_with_its_reason(self) -> None:
        road = profile(max_mean_gradient_pct=5.0, **CLEAN)
        checked = pit_ramp.check_ramp(zigzag(), job(road), ramp(road))
        self.assertTrue(checked.mean_exceeded)
        self.assertGreater(checked.mean_gradient_pct, 5.0)
        self.assertEqual([item.code for item in checked.notices], ["des.pit_ramp_mean_gradient"])
        with self.assertRaises(pit_ramp.DesignError) as caught:
            pit_ramp.confirm_mean(checked)
        self.assertEqual(caught.exception.code, "des.pit_ramp_mean_over")
        self.assertEqual(caught.exception.values["limit"], 5.0)
        mean = checked.mean_gradient_pct
        done = provenance.ramp_confirmation("rampa", mean, "Hay que cruzar el cauce", "Samuel", "2026-11-23T10:00:00Z")
        self.assertIs(pit_ramp.confirm_mean(checked, done), done)
        for other in (provenance.ramp_confirmation("otra", mean, "m", "S", "t"), provenance.ramp_confirmation("rampa", mean - 1.0, "m", "S", "t")):
            with self.subTest(other=other), self.assertRaises(pit_ramp.DesignError):
                pit_ramp.confirm_mean(checked, other)


class DoesNotFitTest(unittest.TestCase):
    """RF-018-20: los tres rechazos (perímetro o lado, zona sin rampa, intocable), con banco, longitudes, lugar y sugerencia; sin cambiar nada."""

    def test_perimeter_and_straight_side_become_the_rejection(self) -> None:
        road = profile()
        definition = ramp(road, "spiral", 8.0)
        with self.assertRaises(pit_ramp.RampDoesNotFit) as caught:
            pit_ramp.build_tramo(pd.circle_ring(10.0, 90), (210.0, 200.0), bench=3, z_foot_m=125.0, rise_m=10.0, gradient_pct=8.0, width_m=W)
        error = pit_ramp.no_fit_error(caught.exception, definition)
        self.assertEqual(error.code, "des.pit_no_ramp_fit")
        self.assertEqual((error.values["bench"], error.values["needed"]), (3, 125.0))
        self.assertLess(error.values["available"], 125.0)
        self.assertEqual(error.values["reason"], "el perímetro del eje del banco")
        self.assertRegex(error.values["place"], r"^\d+\.\d, \d+\.\d$")
        self.assertIn("otro punto de inicio", error.text)
        with self.assertRaises(pit_ramp.ZigzagDoesNotFit) as caught:
            pit_ramp.build_zigzag(zz.feet(), zz.SOUTH, z_first_m=125.0, rise_m=10.0, gradient_pct=2.0, width_m=W, platform_m=zz.PLATFORM_M)
        error = pit_ramp.no_fit_error(caught.exception, definition)
        self.assertEqual(error.values["reason"], "el lado recto del pie")
        self.assertGreater(error.values["needed"], error.values["available"])

    def test_steps_give_the_place_in_absolute_coordinates(self) -> None:
        road = profile()
        polylines = []
        for bench in range(2):
            xy = pd.absolute(zz.feet(2)[bench])
            polylines.append(pit_model.Polyline("foot", bench, np.column_stack([xy, np.full(len(xy), 125.0 + 10.0 * bench)])))
        definition = ramp_def.PitRampDef("zz", "ZZ", "zigzag", "ccw", "banco 0", 2.0, road.code, 0.0, 12.0, 40.0)
        with self.assertRaises(pit_ramp.RampDoesNotFit) as caught:
            list(pit_ramp.zigzag_steps(job(road, ramps=(definition,)), polylines, definition, pd.absolute(zz.SOUTH[None, :])[0]))
        x, y = caught.exception.place
        self.assertGreater(x, 1000.0)
        self.assertGreater(y, 1000.0)

    def _zone_job(self, **changes: object) -> tuple[object, object, object]:
        road = profile(**SMALL_TURNS)
        return zigzag(), road, job(road, **changes)

    def test_no_ramp_zone_on_the_axis(self) -> None:
        found = zigzag()
        point = found.tramos[2].axis[0] + np.array([0.0, 0.0, 0.0])
        x, y = float(point[0] + 30.0), float(point[1])
        square = np.array([[x - 2, y - 2], [x + 2, y - 2], [x + 2, y + 2], [x - 2, y + 2]])
        road = profile(**SMALL_TURNS)
        before = found.path.axis.copy()
        with self.assertRaises(pit_ramp.DesignError) as caught:
            pit_ramp.check_ramp(found, job(road, noramp=((square,),)), ramp(road))
        error = caught.exception
        self.assertEqual((error.code, error.values["bench"], error.values["reason"]), ("des.pit_no_ramp_fit", 2, "zona sin rampa"))
        self.assertAlmostEqual(error.values["needed"], 140.0, delta=40.0)
        self.assertLess(error.values["available"], error.values["needed"])
        px, py = (float(item) for item in error.values["place"].split(","))
        self.assertLessEqual(abs(px - x), 3.0)
        self.assertLessEqual(abs(py - y), 3.0)
        self.assertTrue(np.array_equal(before, found.path.axis))

    def test_untouchable_on_the_axis(self) -> None:
        found = zigzag()
        grid = pd.GRID
        point = found.tramos[1].axis[:2].mean(axis=0)
        mask = np.zeros(grid.shape, bool)
        mask[int((grid.north - point[1]) // grid.dy), int((point[0] - grid.west) // grid.dx)] = True
        road = profile(**SMALL_TURNS)
        owned = mask.copy()
        with self.assertRaises(pit_ramp.DesignError) as caught:
            pit_ramp.check_ramp(found, job(road, untouchable=mask), ramp(road))
        self.assertEqual((caught.exception.values["bench"], caught.exception.values["reason"]), (1, "intocable"))
        self.assertTrue(np.array_equal(mask, owned))

    def test_zone_off_the_axis_does_not_reject(self) -> None:
        road = profile(**CLEAN)
        far = np.array([[10.0, 10.0], [14.0, 10.0], [14.0, 14.0], [10.0, 14.0]]) + np.asarray(pd.origin_of(pd.GRID))
        checked = pit_ramp.check_ramp(zigzag(), job(road, noramp=((far,),)), ramp(road))
        self.assertEqual(checked.notices, ())


class BandTest(unittest.TestCase):
    """RF-018-21: la banda (eje y bordes con su Z por estaciones), y nada de «eje 3D» de la 017 por su cuenta (D-3); P2: la línea con Z comprobable con la 017."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.road = profile()
        cls.checked = pit_ramp.check_ramp(spiral_tramo(), job(cls.road), ramp(cls.road, "spiral", 8.0))

    def test_edges_are_w_over_two_from_the_axis_at_the_axis_level(self) -> None:
        band = self.checked.band
        left, axis, right = band.breaklines
        self.assertEqual(len(left), len(self.checked.axis.stations))
        np.testing.assert_allclose(np.hypot(*(left[:, :2] - axis[:, :2]).T), W / 2.0, atol=1e-9)
        np.testing.assert_allclose(np.hypot(*(right[:, :2] - axis[:, :2]).T), W / 2.0, atol=1e-9)
        np.testing.assert_allclose(left[:, 2], axis[:, 2], atol=0.0)
        np.testing.assert_allclose(right[:, 2], axis[:, 2], atol=0.0)
        np.testing.assert_allclose((left[:, :2] + right[:, :2]) / 2.0, axis[:, :2], atol=1e-9)
        # el borde izquierdo queda a la izquierda de la marcha
        heading = np.column_stack([np.sin(self.checked.axis.azimuth), np.cos(self.checked.axis.azimuth)])
        offset = left[:, :2] - axis[:, :2]
        np.testing.assert_allclose(heading[:, 0] * offset[:, 1] - heading[:, 1] * offset[:, 0], W / 2.0, atol=1e-9)

    def test_line_is_checkable_with_the_017(self) -> None:
        """P2: el eje con su Z, como línea, pasa por ``axis_of`` y ``check_axis_3d`` de la 017 sin avisos."""
        line = self.checked.line
        axis = road_axis.axis_of(line, self.road.curve_radius_m, self.road.min_radius_m, self.road.station_step_m, reject_below_minimum=False)
        z = np.interp(axis.line_abscissa(axis.stations), np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(axis.vertices, axis=0).T)))),
                      line[axis.kept, 2])
        self.assertEqual(road_gradient.check_axis_3d(axis, z, self.road, "Rampa 1", line), ())

    def test_path_keeps_the_half_width_and_levels(self) -> None:
        path = self.checked.path
        np.testing.assert_allclose(path.half_width_m, W / 2.0)
        self.assertEqual((float(path.axis[0, 2]), float(path.axis[-1, 2])), (125.0, 135.0))

    def test_no_road_is_applied_on_top(self) -> None:
        """D-3: el módulo no importa el grabado, la sección ni el almacén de la pista."""
        source = Path(pit_ramp.__file__).read_text(encoding="utf-8")
        names = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertFalse(names & {"road_engrave", "road_section", "road_store", "road_route", "road_net"})
        self.assertIn("road_axis", names)
        self.assertIn("road_gradient", names)


class SpeedAndDeterminismTest(unittest.TestCase):
    def test_axis_of_a_ramp_in_a_tenth_of_a_second_and_bit_for_bit(self) -> None:
        """RNF-018-02 (por analogía con la 017): el eje de una rampa en ≤ 0,1 s; el mismo resultado bit a bit."""
        road = profile()
        found, definition, work = spiral_tramo(), ramp(road, "spiral", 8.0), job(road)
        best = math.inf
        for _ in range(5):
            start = time.perf_counter()
            first = pit_ramp.check_ramp(found, work, definition)
            best = min(best, time.perf_counter() - start)
        self.assertLessEqual(best, 0.1)
        again = pit_ramp.check_ramp(found, work, definition)
        self.assertTrue(np.array_equal(first.line, again.line))
        self.assertTrue(np.array_equal(first.band.left, again.band.left))


if __name__ == "__main__":
    unittest.main()
