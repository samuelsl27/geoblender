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
        self.assertAlmostEqual(checked.max_gradient_pct, 10.0, delta=1e-6)  # DIFF-018c: la cota es lineal en el arco: ya no sube a g·4/π
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
        self.assertAlmostEqual(max(item.values["gradient"] for item in over), 12.0, delta=1e-6)
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
        """RF-018-21: los bordes de la banda están a W/2 del eje, en planta, y a la cota de la rasante en cada abscisa."""
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


def spiral5() -> object:
    """La espiral de CE-018-05 (5 bancos sobre la corta circular, g = 8 %), con ``spiral_steps`` sobre los pies y las crestas absolutos: el eje esqueleto de la corta."""
    from tests.unit.design import test_pit_ramp_spiral as sp

    _tramos, feet, crests = sp.build_spiral()
    polylines = []
    for bench in range(pd.BENCHES):
        for kind, ring, z in (("foot", feet[bench], 125.0 + 10.0 * bench), ("crest", crests[bench], 135.0 + 10.0 * bench)):
            xy = pd.absolute(ring)
            polylines.append(pit_model.Polyline(kind, bench, np.column_stack([xy, np.full(len(xy), z)])))
    road = profile(min_radius_m=7.0)
    definition = ramp(road, "spiral", 8.0)
    steps = list(pit_ramp.spiral_steps(job(road, ramps=(definition,)), polylines, definition, pd.absolute(sp.NORTH[None, :])[0]))
    return steps[-1].result


def rectangle_spiral(width_m: float = 12.0) -> object:
    """Un pie rectangular de 60 × ``width_m`` m (una corta poligonal con esquinas de 90°) con un tramo de rampa que da la vuelta a sus dos esquinas cortas."""
    ring = np.array([[0.0, 0.0], [60.0, 0.0], [60.0, width_m], [0.0, width_m]])
    tramo = pit_ramp.build_tramo(ring, (30.0, 0.0), bench=0, z_foot_m=125.0, rise_m=10.0, gradient_pct=8.0, width_m=W)
    shift = np.array([*pd.absolute(np.zeros((1, 2)))[0], 0.0])
    tramo = dataclasses.replace(tramo, axis=tramo.axis + shift)
    path = pit_model.RampPath("rampa", 0, tramo.axis, np.full(len(tramo.axis), W / 2.0))
    return pit_ramp.Spiral(path, (tramo,), tramo.ramp_m, 0.0)


def turns_deg(axis: np.ndarray) -> np.ndarray:
    """Los giros (°) en los vértices interiores de una poligonal ``(n, 2+)``."""
    steps = np.diff(axis[:, :2], axis=0)
    heading = np.degrees(np.arctan2(steps[:, 0], steps[:, 1]))
    return (np.diff(heading) + 180.0) % 360.0 - 180.0


class SkeletonAxisTest(unittest.TestCase):
    """DIFF-018c (spec 0.5, opción i), RF-018-16, 17, 18, 19 y 20: el eje de la rampa es el esqueleto liso (el tramo, el enlace horizontal de W + B y el tramo siguiente), sin la
    muesca del pie donde empieza cada tramo; la regla de radio se comprueba sobre todos los giros del esqueleto y un perfil de pista con Rmín mayor que el radio que cabe entre los dos giros
    de un enlace se rechaza diciéndolo. Cifras medidas con el eje de CE-018-05 (R 20 m, enlace W + B = 17,5 m): antes, con el pie tal cual, 24 a 31 vértices de radio de 0,001 a 9 m,
    retrocesos de 0,7 y 2,2 m y deflexiones de −157° a −178°, y 12 avisos de pendiente de 10,2 a 20,8 %; ahora, giros de 86° a 113° de radio ≥ 7,2 m y pendiente ≤ 8,05 %."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = spiral5()
        cls.road = profile(min_radius_m=7.0)
        cls.checked = pit_ramp.check_ramp(cls.found, job(cls.road), ramp(cls.road, "spiral", 8.0))

    def test_the_notch_is_gone_from_every_tramo(self) -> None:
        """Sin retrocesos (giros de más de 120°) ni cuerdas de 4 m con arcos de 0,6 m: el eje denso que usan la banda y la comprobación 3D es liso salvo los dos giros de cada enlace."""
        self.assertEqual(len(self.found.tramos), 5)
        for one in self.found.tramos:
            with self.subTest(bench=one.bench):
                self.assertLess(float(np.abs(turns_deg(one.axis)).max()), 25.0)
        path = self.found.path.axis
        links = [i for i, turn in enumerate(np.abs(turns_deg(path))) if turn > 25.0]
        self.assertEqual(len(links), 8)  # 4 enlaces, 2 giros cada uno
        self.assertLess(float(np.abs(turns_deg(path)).max()), 120.0)

    def test_every_tramo_is_still_125_m_at_8_percent_and_the_links_17_5(self) -> None:
        """CE-018-05: 125 m de rampa por banco a 8,000 % (≤ 10⁻⁹), la cota de cada banco igual a su ancla y 4 enlaces de W + B (17,5 m ± 0,25) a la cota del banco que alcanzan."""
        for bench, one in enumerate(self.found.tramos):
            with self.subTest(bench=bench):
                run = np.hypot(*np.diff(one.axis[:, :2], axis=0).T)
                np.testing.assert_allclose(np.diff(one.axis[:, 2]) / run, 0.08, rtol=0, atol=1e-9)
                self.assertAlmostEqual(float(run.sum()), 125.0, delta=1e-9)
                self.assertEqual((one.axis[0, 2], one.axis[-1, 2]), (125.0 + 10.0 * bench, 135.0 + 10.0 * bench))
        self.assertAlmostEqual(self.found.ramp_m, 625.0, delta=1e-9)
        for bench in range(1, 5):
            gap = self.found.tramos[bench].axis[0] - self.found.tramos[bench - 1].axis[-1]
            self.assertEqual(float(gap[2]), 0.0)
            self.assertAlmostEqual(float(np.hypot(*gap[:2])), 17.5, delta=0.25)
        self.assertAlmostEqual(self.found.axis_m, 695.0, delta=1.0)

    def test_checked_axis_has_no_gradient_notices_and_turns_above_the_minimum(self) -> None:
        """RF-018-18 y 19: sin avisos de pendiente en los bancos 1 a 4 (pd = 10 %, g = 8 %), pendiente máxima ≤ 8,05 %, la Z repartida sin subir en la cuerda, todos los radios ≥ Rmín
        (7,27 m en el giro más cerrado) y la cota del primer punto y del último, las de los bancos."""
        gradients = [item for item in self.checked.notices if item.code == "des.pit_ramp_gradient"]
        self.assertEqual(gradients, [])
        self.assertLessEqual(self.checked.max_gradient_pct, 8.05)
        self.assertGreaterEqual(self.checked.axis.min_radius_m, self.road.min_radius_m)
        self.assertAlmostEqual(self.checked.axis.min_radius_m, 7.27, delta=0.05)
        self.assertEqual((float(self.checked.z[0]), float(self.checked.z[-1])), (125.0, 175.0))
        self.assertFalse(self.checked.mean_exceeded)
        self.assertEqual(set(np.unique(self.checked.benches)), {0, 1, 2, 3, 4})
        self.assertLess(self.checked.length_m, self.found.axis_m)

    def test_reference_profile_is_rejected_with_the_link_and_the_largest_minimum(self) -> None:
        """C: con R 20 / Rmín 12, el radio que cabe entre los dos giros de un enlace de 17,5 m es de 7,3 a 8,75 m: se rechaza con el banco, el lugar, el radio que cabe, Rmín y el enlace."""
        road = profile()
        for found, kind, g, low, high in ((self.found, "spiral", 8.0, 7.0, 8.0), (zigzag(), "zigzag", 10.0, 8.7, 8.8)):
            with self.subTest(kind=kind), self.assertRaises(pit_ramp.DesignError) as caught:
                pit_ramp.check_ramp(found, job(road), ramp(road, kind, g))
            error = caught.exception
            self.assertEqual(error.code, "des.pit_ramp_radius_below_min")
            self.assertTrue(low <= error.values["value"] <= high, error.values["value"])
            self.assertEqual(error.values["limit"], 12.0)
            self.assertGreaterEqual(error.values["bench"], 1)
            self.assertTrue(10.0 <= error.values["link"] <= 18.0, error.values["link"])
            self.assertRegex(error.values["place"], r"^\d+\.\d, \d+\.\d$")
            self.assertIn("banco", error.text)
            self.assertIn("como mucho", error.text)

    def test_zigzag_with_the_largest_minimum_passes_with_the_g_of_the_tramo(self) -> None:
        """C: con Rmín 8 (≤ 8,75 m, la mitad del enlace de 17,5 m) el zig-zag pasa; con la cota lineal en el arco su pendiente máxima es g (10 %) y con pd = 10 % no hay avisos."""
        road = profile(min_radius_m=8.0)
        checked = pit_ramp.check_ramp(zigzag(), job(road), ramp(road))
        self.assertAlmostEqual(checked.axis.min_radius_m, 8.75, delta=1e-6)
        self.assertEqual([item.code for item in checked.notices if item.code == "des.pit_ramp_gradient"], [])
        self.assertAlmostEqual(checked.max_gradient_pct, 10.0, delta=1e-6)

    def test_a_closed_corner_of_a_polygonal_foot_is_checked(self) -> None:
        """RF-018-20: la esquina de 90° del pie de una corta poligonal (un rectángulo de 60 × 12 m: el lado corto del eje mide 23,5 m) se comprueba con Rmín: 11,75 m caben, y con Rmín 12 se rechaza."""
        found = rectangle_spiral()
        road = profile(min_radius_m=11.0)
        checked = pit_ramp.check_ramp(found, job(road), ramp(road, "spiral", 8.0))
        self.assertAlmostEqual(checked.axis.min_radius_m, 11.75, delta=0.05)
        road = profile()
        with self.assertRaises(pit_ramp.DesignError) as caught:
            pit_ramp.check_ramp(found, job(road), ramp(road, "spiral", 8.0))
        self.assertEqual(caught.exception.code, "des.pit_ramp_radius_below_min")
        self.assertAlmostEqual(caught.exception.values["value"], 11.75, delta=0.05)
        self.assertEqual(caught.exception.values["bench"], 0)

    def test_notch_is_found_by_its_two_hairpins_and_a_single_corner_is_kept(self) -> None:
        """Una muesca son dos retrocesos o más en los primeros 6·W m; uno solo (una esquina cerrada real) no se toca."""
        notch = np.array([[0.0, 0.0], [4.0, -2.0], [8.0, -3.0], [8.5, -3.1], [6.0, -1.5], [6.4, -1.6]]
                         + [[6.4 + 3.0 * i, -1.6 - 1.0 * i] for i in range(1, 40)])
        keep = pit_ramp._skeleton_keep(notch, W)
        self.assertIsNotNone(keep)
        self.assertEqual(int(keep[0]), 0)
        self.assertLess(len(keep), len(notch) - 4)
        one_corner = np.array([[0.0, 0.0], [20.0, 0.0], [0.0, 3.0]] + [[-3.0 * i, 3.0] for i in range(1, 30)])
        self.assertIsNone(pit_ramp._skeleton_keep(one_corner, W))

    def test_axis_in_a_tenth_of_a_second_and_bit_for_bit(self) -> None:
        """RNF-018-02: el eje esqueleto de la espiral de 5 bancos en ≤ 0,1 s (con su simplificación) y el mismo resultado bit a bit."""
        definition, work = ramp(self.road, "spiral", 8.0), job(self.road)
        best = math.inf
        for _ in range(5):
            start = time.perf_counter()
            first = pit_ramp.check_ramp(self.found, work, definition)
            best = min(best, time.perf_counter() - start)
        self.assertLessEqual(best, 0.1)
        again = pit_ramp.check_ramp(self.found, work, definition)
        self.assertTrue(np.array_equal(first.line, again.line))
        self.assertTrue(np.array_equal(first.z, again.z))


if __name__ == "__main__":
    unittest.main()
