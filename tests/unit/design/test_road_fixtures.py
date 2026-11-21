# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera de pruebas de las pistas y rampas (spec 017, T01; plan 017 §7.1, §7.3 y §7.4; RF-017-02, 04, 08
a 18, 20, 24 y 25; CE-017-01 a 09; E1 a E5).

Recorre ``tests.support.road_data`` antes de que la usen las pruebas de la 017 (que aún no existen), con
cuentas a mano: el perfil de referencia y sus derivados (calzada 10,5 m, sección 11,5 m, semianchura 5,75 m); los
16 rumbos (y que ofrecen la ruta a ≤ 2,8 % de la recta y las pendientes de CE-017-04); el plano del 4 % con y sin
la pendiente transversal del 20 % (y el corte y el relleno de su calzada); el escalón y su rasante analítica; las
esquinas de CE-017-02; la ladera del 38 % a 22,5° y la franja de un nodo con y sin intocable; el barranco de 14 m; el
tajo con su corredor, la superficie final restaurada y el relleno posterior; la cantera con bancos y una rampa (con
su comunicación comprobada por un oráculo propio, no por el algoritmo de la tarea T15); las capas y el proyecto; los
datos de escala que no pesan (la rejilla de 2,81 M celdas, solo bajo demanda); que el proyecto se construye en ≤ 2 s
de CPU y se lee de vuelta; y que los nombres de ``main`` en los que se apoya el plan 017 (§5) siguen ahí.

Ningún dato de cliente: todo es sintético. Las cuentas son las de la docstring de cada constante, hechas aquí otra
vez de otra manera (fórmulas cerradas, bucles de Python por celda o fuerza bruta), no con el código que genera los
datos.
"""

from __future__ import annotations

import ast
import math
import time
import tomllib
import unittest

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

gis = import_geoblender("gis")
gis_store = import_geoblender("gis.store")

COPY_BUDGET_S = 1.0
"""Una copia del proyecto por clase, en menos de 1 s de CPU."""
STEPS = (1.0, 2.0)
"""Los dos pasos de rejilla de los casos: 1 m (cuentas a mano) y 2 m (con proyecto)."""


def box_cells(box: tuple[float, float, float, float], grid: object = rd.GRID) -> int:
    """Las celdas de ``grid`` con el centro dentro de la caja local, contadas con dos bucles de Python."""
    columns, rows = grid.ncols, grid.nrows  # type: ignore[attr-defined]
    left, bottom, right, top = box
    step_x, step_y = grid.dx, grid.dy  # type: ignore[attr-defined]
    found = 0
    for column in range(columns):
        x = (column + 0.5) * step_x
        if not left < x < right:
            continue
        for row in range(rows):
            y = rows * step_y - (row + 0.5) * step_y
            if bottom < y < top:
                found += 1
    return found


class FrameTest(unittest.TestCase):
    """Las coordenadas locales y las rejillas de los casos."""

    def test_local_centers(self) -> None:
        """Con celdas de 1 m, el centro de la celda de la esquina noroeste es (0,5; 399,5) y con las de 2 m,
        (1; 399); la rejilla de escala, que parte de otra esquina, tiene sus propias coordenadas locales."""
        x, y = rd.local_centers(rd.GRID)
        self.assertEqual((float(x[0, 0]), float(y[0, 0]), float(x[-1, -1]), float(y[-1, -1])),
                         (0.5, 399.5, 399.5, 0.5))
        x2, y2 = rd.local_centers(rd.grid_of(2.0))
        self.assertEqual((x2.shape, float(x2[0, 0]), float(y2[0, 0])), ((200, 200), 1.0, 399.0))
        scale = rd.scale_grid()
        xs, ys = rd.local_centers(scale)
        self.assertEqual((float(xs[0, 0]), float(ys[0, 0])), (0.5, 1698.5))
        self.assertNotEqual(rd.origin_of(scale), rd.BASE)
        self.assertEqual(rd.origin_of(rd.GRID), rd.BASE)

    def test_the_frame_is_the_quarry_one(self) -> None:
        """Las rejillas son las de la cantera de la 014 y las coordenadas locales, las de la 015 y la 016."""
        self.assertIs(rd.GRID, qfx.GRID)
        self.assertEqual(rd.grid_of(2.0), qfx.grid_of(2.0))
        x, y = rd.local_centers(rd.GRID)
        np.testing.assert_array_equal(x, qfx.local_centers(qfx.GRID)[0])
        np.testing.assert_array_equal(y, sdata.local_centers(qfx.GRID)[1])

    def test_absolute_and_bearings(self) -> None:
        """Lo local pasa a absoluto en float64 sumando la esquina de la rejilla; el azimut es el del norte en
        sentido horario."""
        found = rd.absolute([(0.0, 0.0), (10.0, 20.0)])
        self.assertEqual(found.dtype, np.float64)
        np.testing.assert_array_equal(found, np.array([cfx.BASE, (cfx.BASE[0] + 10.0, cfx.BASE[1] + 20.0)]))
        scale = rd.scale_grid()
        np.testing.assert_array_equal(rd.absolute([(1.0, 2.0)], scale),
                                      [[scale.west + 1.0, rd.origin_of(scale)[1] + 2.0]])
        east = rd.bearing_point((10.0, 20.0), 90.0, 5.0)
        north = rd.bearing_point((10.0, 20.0), 0.0, 5.0)
        self.assertAlmostEqual(east[0], 15.0, delta=1e-12)
        self.assertAlmostEqual(east[1], 20.0, delta=1e-12)
        self.assertAlmostEqual(north[0], 10.0, delta=1e-12)
        self.assertAlmostEqual(north[1], 25.0, delta=1e-12)

    def test_in_box_counts(self) -> None:
        """Una caja de 40 × 40 m tiene 1.600 celdas de 1 m y 400 de 2 m (centros estrictamente dentro)."""
        box = (100.0, 150.0, 140.0, 190.0)
        self.assertEqual(int(rd.in_box(box).sum()), 1_600)
        self.assertEqual(int(rd.in_box(box, rd.grid_of(2.0)).sum()), 400)
        self.assertEqual(box_cells(box, rd.grid_of(2.0)), 400)
        np.testing.assert_array_equal(rd.in_box(box), qfx.in_box(box))

    def test_a_new_array_every_time(self) -> None:
        """Cada función que da un array da uno nuevo (nadie comparte el de otro)."""
        first = rd.ramp_terrain()
        first[...] = 0.0
        self.assertNotEqual(float(rd.ramp_terrain()[0, 0]), 0.0)


class ProfileTest(unittest.TestCase):
    """El perfil de pista de referencia (``spec.md`` §11, solo para pruebas) y los parámetros de la ruta."""

    def test_the_reference_values(self) -> None:
        """Vehículo de 3,5 m, factor 3, arcén 0 m, caballón 1 m, pd 10 %, R 20 m, Rmín 12 m, desmonte a 60° y
        terraplén a 35°; la métrica exacta y el factor de malla 1,0 (ADOPTADOS «sin confirmar»)."""
        found = rd.PROFILE
        self.assertEqual((found.vehicle_width_m, found.lane_factor, found.shoulder_m, found.berm_m),
                         (3.5, 3.0, 0.0, 1.0))
        self.assertEqual((found.max_gradient_pct, found.curve_radius_m, found.min_radius_m), (10.0, 20.0, 12.0))
        self.assertEqual((found.cut_angle_deg, found.fill_angle_deg), (60.0, 35.0))
        self.assertEqual((found.mesh_factor, found.metric), (1.0, "exact"))
        self.assertEqual(found.station_step_m, 1.0)
        self.assertEqual(found.reach_m, 60.0)

    def test_the_derived_values(self) -> None:
        """Calzada 3,5 · 3 = 10,5 m; sección 10,5 + 0 + 1 = 11,5 m; semianchura 5,75 m; con pd = 10 %, salvar
        30 m pide 300 m; el radio mínimo (12 m) cabe entre la semianchura y el radio (20 m)."""
        found = rd.PROFILE
        self.assertAlmostEqual(found.carriageway_m, 10.5, delta=1e-12)
        self.assertAlmostEqual(found.section_m, 11.5, delta=1e-12)
        self.assertAlmostEqual(found.half_section_m, 5.75, delta=1e-12)
        self.assertAlmostEqual(rd.needed_length_m(30.0, found.max_gradient_pct), 300.0, delta=1e-9)
        self.assertGreaterEqual(found.min_radius_m, found.half_section_m)
        self.assertLessEqual(found.min_radius_m, found.curve_radius_m)

    def test_variants_change_only_what_they_say(self) -> None:
        """``profile_with`` cambia los campos pedidos y deja el resto; el original no se toca."""
        other = rd.profile_with(max_gradient_pct=8.0, min_radius_m=16.0)
        self.assertEqual((other.max_gradient_pct, other.min_radius_m), (8.0, 16.0))
        self.assertEqual(other.curve_radius_m, rd.PROFILE.curve_radius_m)
        self.assertEqual(rd.PROFILE.max_gradient_pct, 10.0)
        with self.assertRaises(TypeError):
            rd.profile_with(no_such_field=1.0)

    def test_the_route_parameters(self) -> None:
        """Malla de 4 m, paso de cota de 0,28 m (el 7 % de un paso recto), altura máxima de 14 m y λ = 2 1/m son
        de la referencia; los cuatro sin valor en ella (giro, holgura, simplificación y llegada) son HIPÓTESIS
        sencillas de la prueba (T01-a: un paso de giro, un nodo de simplificación, un paso de cota de llegada y
        la holgura de 60 m de RNF-017-02); el presupuesto, el de P-3."""
        found = rd.ROUTE
        self.assertEqual((found.mesh_m, found.max_cut_fill_m, found.lambda_per_m), (4.0, 14.0, 2.0))
        self.assertAlmostEqual(found.level_step_m, 0.07 * found.mesh_m, delta=1e-12)
        self.assertEqual(rd.ROUTE_HYPOTHESES, ("turn_m", "margin_m", "simplify_m", "arrival_tol_m"))
        self.assertEqual((found.turn_m, found.simplify_m, found.arrival_tol_m, found.margin_m),
                         (found.mesh_m, found.mesh_m, found.level_step_m, 60.0))
        self.assertEqual(found.search_budget, 5_000_000)
        for step in STEPS:
            self.assertEqual(found.mesh_m % step, 0.0)  # un múltiplo entero del paso del proyecto (D-10)
        self.assertEqual(rd.route_with(mesh_m=8.0).mesh_m, 8.0)

    def test_the_access_parameters(self) -> None:
        """Hasta el 16 % y 300 m² son de la referencia; el ancho mínimo (4 m) es una HIPÓTESIS de la prueba."""
        self.assertEqual((rd.ACCESS.walk_slope_pct, rd.ACCESS.min_berm_area_m2), (16.0, 300.0))
        self.assertEqual(rd.ACCESS.walk_width_m, 4.0)


class HeadingsTest(unittest.TestCase):
    """Los 16 rumbos (D-8, D-23, RF-017-11) y lo que la spec dice de ellos, sin el código de la ruta."""

    def test_sixteen_steps_clockwise_from_north(self) -> None:
        """Los 16 pasos ``(dx, dy)`` van en sentido horario desde el norte, con los azimuts de la lista."""
        steps = rd.ORACLE_HEADINGS
        self.assertEqual(len(steps), 16)
        self.assertEqual(len(set(steps)), 16)
        self.assertEqual(steps[0], (0, 1))
        azimuths = [math.degrees(math.atan2(dx, dy)) % 360.0 for dx, dy in steps]
        self.assertEqual(azimuths, sorted(azimuths))
        expected = [0.0, 26.565051177078, 45.0, 63.434948822922, 90.0, 116.565051177078, 135.0,
                    153.434948822922, 180.0, 206.565051177078, 225.0, 243.434948822922, 270.0,
                    296.565051177078, 315.0, 333.434948822922]
        for found, wanted in zip(azimuths, expected, strict=True):
            self.assertAlmostEqual(found, wanted, delta=1e-9)
        self.assertEqual(rd.heading_azimuth_deg((1, 2)), azimuths[1])

    def test_the_route_is_within_2_8_percent_of_the_straight_line(self) -> None:
        """El hueco mayor entre dos rumbos contiguos es de 26,565° (entre el este y (2, 1)): una ruta que usa los
        dos rumbos más próximos a un rumbo cualquiera mide a lo sumo 1/cos(hueco/2) de la recta, un 2,75 % (D-22:
        2,8 %); con 8 rumbos el hueco sería de 45° y el desvío, del 8,2 %."""
        azimuths = [rd.heading_azimuth_deg(step) for step in rd.ORACLE_HEADINGS]
        gaps = [(azimuths[(index + 1) % 16] - azimuths[index]) % 360.0 for index in range(16)]
        self.assertAlmostEqual(max(gaps), 26.565051177078, delta=1e-9)
        self.assertEqual(sorted({round(gap, 6) for gap in gaps}), [18.434949, 26.565051])
        detour = 100.0 * (1.0 / math.cos(math.radians(max(gaps) / 2.0)) - 1.0)
        self.assertGreater(detour, 2.7)
        self.assertLess(detour, rd.DETOUR_BOUND_PCT)
        eight = 100.0 * (1.0 / math.cos(math.radians(45.0 / 2.0)) - 1.0)
        self.assertGreater(eight, 8.0)

    def test_the_38_percent_hillside_needs_16_headings(self) -> None:
        """CE-017-04: con la curva de nivel a 22,5° de un eje de la rejilla, la menor pendiente de paso de los 16
        rumbos es del 2,7 % y la de 8 rumbos, del 14,5 % (sin ruta con pd = 10 %)."""
        sixteen = [rd.hillside_heading_slope_pct(dx, dy) for dx, dy in rd.ORACLE_HEADINGS]
        eight = [rd.hillside_heading_slope_pct(dx, dy) for dx, dy in rd.ORACLE_HEADINGS
                 if abs(dx) <= 1 and abs(dy) <= 1]
        self.assertEqual(len(eight), 8)
        self.assertAlmostEqual(min(sixteen), 100.0 * 0.38 * math.sin(math.atan(0.5) - math.radians(22.5)),
                               delta=1e-12)
        self.assertEqual(round(min(sixteen), 1), 2.7)
        self.assertEqual(round(min(eight), 1), 14.5)
        self.assertLess(min(sixteen), rd.PROFILE.max_gradient_pct)
        self.assertGreater(min(eight), rd.PROFILE.max_gradient_pct)
        self.assertIn(sixteen.index(min(sixteen)), (3, 11))  # (2, 1) o su opuesto: el rumbo de la ruta de CE-017-04


class RampTest(unittest.TestCase):
    """El plano del 4 % cuyo sentido de máxima pendiente es un eje de la rejilla, con y sin una pendiente
    transversal del 20 % (CE-017-01)."""

    def test_the_plane_by_hand(self) -> None:
        """z = 100 + 0,04·x en los centros de las celdas (1 y 2 m): 4 % hacia el este, nada hacia el norte."""
        for step in STEPS:
            grid = rd.grid_of(step)
            found = rd.ramp_terrain(grid)
            x, _y = rd.local_centers(grid)
            np.testing.assert_allclose(found, 100.0 + 0.04 * x, rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(np.diff(found, axis=1) / step, 0.04, rtol=0.0, atol=1e-12)
            self.assertEqual(float(np.abs(np.diff(found, axis=0)).max()), 0.0)

    def test_origin_and_destination(self) -> None:
        """De (100, 200) a (300, 200): 200,000 m en un rumbo de la rejilla (el este), desnivel de 8,000 m y el 4,000 %
        de media y de máxima; con pd = 8 % la rasante es el terreno."""
        (x0, y0), (x1, y1) = rd.RAMP_ORIGIN, rd.RAMP_DESTINATION
        self.assertEqual(math.hypot(x1 - x0, y1 - y0), rd.RAMP_LENGTH_M)
        self.assertEqual(rd.RAMP_LENGTH_M, 200.0)
        z0 = rd.RAMP_Z0_M + rd.RAMP_SLOPE_PCT / 100.0 * x0
        z1 = rd.RAMP_Z0_M + rd.RAMP_SLOPE_PCT / 100.0 * x1
        self.assertAlmostEqual(z1 - z0, rd.RAMP_DROP_M, delta=1e-12)
        self.assertAlmostEqual(rd.RAMP_DROP_M, 8.0, delta=1e-12)
        self.assertAlmostEqual(100.0 * (z1 - z0) / (x1 - x0), 4.0, delta=1e-12)
        self.assertLess(rd.RAMP_SLOPE_PCT, rd.profile_with(max_gradient_pct=8.0).max_gradient_pct)
        self.assertEqual(rd.heading_azimuth_deg((1, 0)), 90.0)  # el este es uno de los 16 rumbos

    def test_the_cross_slope(self) -> None:
        """Con el 20 % transversal, z = 100 + 0,04·x + 0,2·(y − 200): el eje (y = 200) sigue en 100 + 0,04·x, el
        terreno baja 0,2 m por metro hacia el sur y el 4 % del este no cambia."""
        for step in STEPS:
            grid = rd.grid_of(step)
            found = rd.ramp_terrain(grid, cross_pct=20.0)
            x, y = rd.local_centers(grid)
            np.testing.assert_allclose(found, 100.0 + 0.04 * x + 0.2 * (y - 200.0), rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(np.diff(found, axis=1) / step, 0.04, rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(-np.diff(found, axis=0) / step, 0.2, rtol=0.0, atol=1e-12)
            axis_rows = np.flatnonzero(np.abs(y[:, 0] - 200.0) == step / 2.0)
            self.assertEqual(len(axis_rows), 2)
            np.testing.assert_allclose((found[axis_rows[0]] + found[axis_rows[1]]) / 2.0,
                                       100.0 + 0.04 * x[0], rtol=0.0, atol=1e-12)

    def test_the_carriageway_by_hand(self) -> None:
        """La calzada de 10,5 m (|y − 200| ≤ 5,25) sobre el 20 % transversal, con la rasante en el terreno del eje:
        el corte (norte) y el relleno (sur) iguales, 500 m³ con celdas de 1 m (5 filas por lado: Σ0,2·(k+½) = 2,5
        m³ por columna, 200 columnas) y 720 m³ con las de 2 m (3 filas por lado), a ≤ 10⁻⁹ relativo; sin
        pendiente transversal no se mueve nada."""
        for step, rows, columns, volume in ((1.0, 5, 200, 500.0), (2.0, 3, 100, 720.0)):
            found = rd.ramp_calzada_by_hand(step)
            self.assertEqual((found.rows_per_side, found.columns), (rows, columns))
            self.assertAlmostEqual(found.cut_m3, volume, delta=volume * 1e-12)
            self.assertAlmostEqual(found.fill_m3, volume, delta=volume * 1e-12)
            grid = rd.grid_of(step)
            x, y = rd.local_centers(grid)
            half = rd.PROFILE.carriageway_m / 2.0
            window = (np.abs(y - 200.0) <= half) & (x > 100.0) & (x < 300.0)
            self.assertEqual(int(window.sum()), 2 * rows * columns)
            for cross in (20.0, 0.0):
                terrain = rd.ramp_terrain(grid, cross_pct=cross)
                grade = 100.0 + 0.04 * x
                diff = np.where(window, terrain - grade, 0.0)
                cut = float(np.maximum(diff, 0.0).sum()) * step * step
                fill = float(np.maximum(-diff, 0.0).sum()) * step * step
                want = volume if cross else 0.0
                self.assertAlmostEqual(cut, want, delta=max(want, 1.0) * 1e-9)
                self.assertAlmostEqual(fill, want, delta=max(want, 1.0) * 1e-9)

    def test_the_points_are_cell_boundaries_of_the_axis(self) -> None:
        """El eje y = 200 es un borde de celda en 1 y en 2 m: la calzada es simétrica (la cuenta de arriba)."""
        self.assertEqual(rd.RAMP_AXIS_Y_M, 200.0)
        for step in STEPS:
            self.assertEqual(rd.RAMP_AXIS_Y_M % step, 0.0)


class StepProfileTest(unittest.TestCase):
    """El perfil del terreno en escalón (CE-017-03) y los ejes de sus casos."""

    def test_the_step_terrain(self) -> None:
        """0 m hasta la abscisa 0 (x = 200) y 6 m después, en un eje de 200 m centrado en el escalón."""
        for step in STEPS:
            grid = rd.grid_of(step)
            found = rd.step_terrain(grid)
            x, _y = rd.local_centers(grid)
            np.testing.assert_array_equal(found, np.where(x < 200.0, 0.0, 6.0))
            self.assertEqual(sorted(np.unique(found).tolist()), [0.0, 6.0])
            self.assertEqual(float(np.abs(np.diff(found, axis=0)).max()), 0.0)
        (x0, y0), (x1, y1) = rd.STEP_AXIS
        self.assertEqual((math.hypot(x1 - x0, y1 - y0), (x0 + x1) / 2.0), (200.0, rd.STEP_X_M))
        profile = rd.step_profile_m(np.array([-100.0, -0.5, 0.5, 100.0]))
        np.testing.assert_array_equal(profile, [0.0, 0.0, 6.0, 6.0])

    def test_the_analytic_grade(self) -> None:
        """Con pd = 10 % la rasante es la rampa del 5 % (pd/2) entre las abscisas −60 y +60 m, 0 m antes y 6 m
        después, y la diferencia con el terreno suma 180 m·m: ∫|g − t| = 18/pd."""
        grade = rd.step_grade_by_hand
        np.testing.assert_allclose(grade(np.array([-100.0, -60.0, 0.0, 60.0, 100.0]), 10.0),
                                   [0.0, 0.0, 3.0, 6.0, 6.0], rtol=0.0, atol=1e-12)
        self.assertAlmostEqual(float(grade(np.array([60.0]), 10.0)[0] - grade(np.array([-60.0]), 10.0)[0])
                               / 120.0 * 100.0, rd.STEP_RAMP_PCT, delta=1e-12)
        self.assertEqual((rd.STEP_RAMP_PCT, rd.STEP_RAMP_FROM_M, rd.STEP_RAMP_TO_M), (5.0, -60.0, 60.0))
        s = np.linspace(-100.0, 100.0, 400_001)
        difference = float(np.trapezoid(np.abs(grade(s, 10.0) - rd.step_profile_m(s)), s))
        self.assertAlmostEqual(difference, 180.0, delta=0.01)
        self.assertAlmostEqual(rd.step_diff_by_hand(10.0), 180.0, delta=1e-9)
        self.assertEqual(rd.STEP_DIFF_MM, 180.0)
        for grade_pct in (5.0, 8.0):
            self.assertAlmostEqual(rd.step_diff_by_hand(grade_pct), 18.0 / (grade_pct / 100.0), delta=1e-9)

    def test_the_mean_grade(self) -> None:
        """La rampa del escalón sube 6 m en 200 m: el 3 % de media, que con pm = 2 % pide aviso."""
        self.assertAlmostEqual(100.0 * (rd.STEP_HIGH_M - rd.STEP_LOW_M) / 200.0, rd.STEP_MEAN_PCT, delta=1e-12)
        self.assertEqual(rd.STEP_MEAN_PCT, 3.0)
        self.assertGreater(rd.STEP_MEAN_PCT, rd.profile_with(max_mean_gradient_pct=2.0).max_mean_gradient_pct)

    def test_the_axis_that_is_too_short(self) -> None:
        """Con los extremos a 0 y a 20 m en un eje de 100 m con pd = 10 %: «necesaria 200 m, el eje mide 100 m»."""
        (x0, y0), (x1, y1) = rd.SHORT_AXIS
        self.assertEqual(math.hypot(x1 - x0, y1 - y0), 100.0)
        self.assertEqual((rd.SHORT_Z_START_M, rd.SHORT_Z_END_M), (0.0, 20.0))
        self.assertAlmostEqual(rd.needed_length_m(rd.SHORT_Z_END_M - rd.SHORT_Z_START_M, 10.0), 200.0, delta=1e-9)
        self.assertEqual(rd.SHORT_NEEDED_M, 200.0)

    def test_the_irregular_3d_axis(self) -> None:
        """Un eje 3D de diez tramos de 20 m con pendientes de 5, 5, 10, 15, −2, 8, 12, 0, 5 y 10 %: con pd = 10 % se
        pasan el 4.º (15 %) y el 7.º (12 %), los de 10 % exactos no; la media Σ|Δz|/S = 14,4/200 = 7,2 %."""
        line = rd.axis_3d_irregular()
        self.assertEqual((line.shape, line.dtype), ((11, 3), np.float64))
        legs = np.hypot(*np.diff(line[:, :2], axis=0).T)
        np.testing.assert_allclose(legs, 20.0, rtol=0.0, atol=1e-9)
        slopes = 100.0 * np.diff(line[:, 2]) / legs
        np.testing.assert_allclose(slopes, [5.0, 5.0, 10.0, 15.0, -2.0, 8.0, 12.0, 0.0, 5.0, 10.0], atol=1e-9)
        self.assertEqual(tuple(slopes.round(6)), rd.AXIS_3D_SLOPES_PCT)
        self.assertEqual([index for index, value in enumerate(slopes) if abs(value) > 10.0 + 1e-9], [3, 6])
        mean = 100.0 * float(np.abs(np.diff(line[:, 2])).sum()) / float(legs.sum())
        self.assertAlmostEqual(mean, rd.AXIS_3D_MEAN_PCT, delta=1e-9)
        self.assertEqual(rd.AXIS_3D_MEAN_PCT, 7.2)
        self.assertEqual(float(line[0, 2]), rd.AXIS_3D_START_Z_M)
        local = line[:, :2] - np.array(rd.origin_of(rd.GRID))
        self.assertEqual((float(local[0, 0]), float(local[0, 1]), float(local[-1, 0])), (100.0, 250.0, 300.0))

    def test_the_smooth_3d_axis(self) -> None:
        """El otro eje 3D sigue el plano del 4 % (cada tramo, el 4 % exacto): sin avisos con pd = 10 %."""
        line = rd.axis_3d_smooth()
        legs = np.hypot(*np.diff(line[:, :2], axis=0).T)
        np.testing.assert_allclose(100.0 * np.diff(line[:, 2]) / legs, 4.0, atol=1e-9)
        x = line[:, 0] - rd.BASE[0]
        np.testing.assert_allclose(line[:, 2], rd.RAMP_Z0_M + 0.04 * x, rtol=0.0, atol=1e-9)


class CornerTest(unittest.TestCase):
    """Las esquinas de CE-017-02: dos tramos rectos perpendiculares."""

    def test_the_long_corner(self) -> None:
        """Dos tramos de 40 m a 90° con R = 20 m: tangente 20 m, arco de π·20/2 = 31,416 m y 20 + 31,416 + 20 =
        71,416 m (la longitud analítica de §7.3 del plan)."""
        path = np.asarray(rd.CORNER_LONG, dtype=np.float64)
        legs = np.hypot(*np.diff(path, axis=0).T)
        np.testing.assert_array_equal(legs, [40.0, 40.0])
        first, second = np.diff(path, axis=0)
        turn = math.degrees(math.atan2(first[0] * second[1] - first[1] * second[0], first @ second))
        self.assertAlmostEqual(abs(turn), 90.0, delta=1e-12)
        found = rd.corner_by_hand(40.0, 20.0)
        self.assertAlmostEqual(found.tangent_m, 20.0 * math.tan(math.radians(45.0)), delta=1e-12)
        self.assertAlmostEqual(found.arc_m, math.pi * 20.0 / 2.0, delta=1e-12)
        self.assertAlmostEqual(found.length_m, 20.0 + math.pi * 10.0 + 20.0, delta=1e-12)
        self.assertAlmostEqual(found.length_m, 71.41592653589793, delta=1e-12)
        self.assertEqual(found.fitted_radius_m, 20.0)

    def test_the_short_corner(self) -> None:
        """Con tramos de 15 m el radio que cabe es de 15 m (T = R ≤ 15): con Rmín = 12 m se reduce a 15 m con
        aviso y con Rmín = 16 m se rechaza diciendo que cabría 15 m."""
        path = np.asarray(rd.CORNER_SHORT, dtype=np.float64)
        np.testing.assert_array_equal(np.hypot(*np.diff(path, axis=0).T), [15.0, 15.0])
        found = rd.corner_by_hand(15.0, 20.0)
        self.assertEqual(found.fitted_radius_m, 15.0)
        self.assertAlmostEqual(found.tangent_m, 15.0, delta=1e-12)
        self.assertAlmostEqual(found.arc_m, math.pi * 15.0 / 2.0, delta=1e-12)
        self.assertAlmostEqual(found.length_m, math.pi * 15.0 / 2.0, delta=1e-12)
        self.assertLessEqual(rd.PROFILE.min_radius_m, found.fitted_radius_m)
        self.assertGreater(rd.profile_with(min_radius_m=16.0).min_radius_m, found.fitted_radius_m)

    def test_the_corners_are_apart_and_inside(self) -> None:
        """Las dos esquinas y el eje corto caben en la ventana sin tocarse."""
        boxes = []
        for path in (rd.CORNER_LONG, rd.CORNER_SHORT, rd.SHORT_AXIS):
            array = np.asarray(path)
            boxes.append((array[:, 0].min(), array[:, 1].min(), array[:, 0].max(), array[:, 1].max()))
        for index, a in enumerate(boxes):
            self.assertTrue(0.0 < a[0] and 0.0 < a[1] and a[2] < 400.0 and a[3] < 400.0)
            for b in boxes[index + 1:]:
                self.assertTrue(a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


class HillsideTest(unittest.TestCase):
    """La ladera del 38 % con la curva de nivel a 22,5° de un eje de la rejilla (CE-017-04)."""

    def test_the_plane(self) -> None:
        """Pendiente 0,38 con la curva de nivel a 22,5° del eje x: el plano tiene |∇z| = 0,38, no cambia a lo largo
        de la curva de nivel y su máxima pendiente es perpendicular a ella."""
        theta = math.radians(22.5)
        for step in STEPS:
            grid = rd.grid_of(step)
            found = rd.hillside_terrain(grid)
            slope_x = np.diff(found, axis=1) / step
            slope_y = -np.diff(found, axis=0) / step
            np.testing.assert_allclose(slope_x, -0.38 * math.sin(theta), rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(slope_y, 0.38 * math.cos(theta), rtol=0.0, atol=1e-12)
            self.assertAlmostEqual(math.hypot(float(slope_x[0, 0]), float(slope_y[0, 0])), 0.38, delta=1e-12)
            self.assertAlmostEqual(float(slope_x[0, 0]) * math.cos(theta) + float(slope_y[0, 0]) * math.sin(theta),
                                   0.0, delta=1e-12)
        found = rd.hillside_terrain()
        pivot = (found[199, 199] + found[199, 200] + found[200, 199] + found[200, 200]) / 4.0
        self.assertAlmostEqual(float(pivot), rd.HILL_Z0_M, delta=1e-12)

    def test_the_pivot_and_the_route(self) -> None:
        """z = 100 m en (200, 200) (el pivote); de (100, 100) a (180, 140), diez pasos de (8, 4) m con el rumbo
        (2, 1): 89,443 m con 2,409 m de desnivel, el 2,69 % de pendiente, por debajo de pd."""
        (x0, y0), (x1, y1) = rd.HILL_ORIGIN, rd.HILL_DESTINATION
        self.assertEqual((x1 - x0, y1 - y0), (10 * 8.0, 10 * 4.0))
        self.assertEqual(rd.HILL_STEPS, 10)
        distance = math.hypot(x1 - x0, y1 - y0)
        self.assertAlmostEqual(distance, 89.44271909999159, delta=1e-12)
        theta = math.radians(22.5)

        def z(x: float, y: float) -> float:
            return 100.0 + 0.38 * (-(x - 200.0) * math.sin(theta) + (y - 200.0) * math.cos(theta))

        drop = z(x1, y1) - z(x0, y0)
        self.assertAlmostEqual(drop, 2.4094, delta=1e-4)
        self.assertAlmostEqual(100.0 * drop / distance, rd.hillside_heading_slope_pct(2, 1), delta=1e-9)
        self.assertLess(100.0 * drop / distance, rd.PROFILE.max_gradient_pct)
        found = rd.hillside_terrain(rd.GRID)
        self.assertAlmostEqual(float(found[199, 199]), z(199.5, 200.5), delta=1e-12)  # fila 199: y = 200,5


class StripTest(unittest.TestCase):
    """La franja de un nodo de la malla de la ruta con un perímetro que solo la deja pasar (CE-017-04)."""

    def test_the_terrain(self) -> None:
        """El 30 % hacia el este: 100 m en el origen (102, 198) y 130 m en el destino (202, 198), a 100 m: el
        desnivel de 30 m con pd = 10 % pide 300 m."""
        for step in STEPS:
            grid = rd.grid_of(step)
            found = rd.strip_terrain(grid)
            x, _y = rd.local_centers(grid)
            np.testing.assert_allclose(found, 100.0 + 0.30 * (x - 102.0), rtol=0.0, atol=1e-12)
        (x0, y0), (x1, y1) = rd.STRIP_ORIGIN, rd.STRIP_DESTINATION
        self.assertEqual((math.hypot(x1 - x0, y1 - y0), rd.STRIP_Z_ORIGIN_M), (100.0, 100.0))
        self.assertAlmostEqual(0.30 * (x1 - x0), 30.0, delta=1e-12)
        self.assertAlmostEqual(rd.needed_length_m(30.0, 10.0), rd.STRIP_NEEDED_M, delta=1e-9)
        self.assertEqual(rd.STRIP_NEEDED_M, 300.0)
        self.assertEqual(rd.STRIP_REACH_M, 10.0)  # la cota mayor que alcanza: la del origen + 10 m

    def test_the_strip_is_one_node_of_the_mesh(self) -> None:
        """La franja es una fila de 26 bloques de 4 × 4 m alineados con la malla de la ruta (desde el oeste y el
        norte): 416 m², 104 m de largo y 4 m de ancho; con 100 m entre el centro de su primer nodo y el del último."""
        for step in STEPS:
            grid = rd.grid_of(step)
            mask = rd.strip_allowed(grid)
            self.assertAlmostEqual(float(mask.sum()) * step * step, 416.0, delta=1e-9)
            k = round(4.0 / step)
            blocks = mask.reshape(grid.nrows // k, k, grid.ncols // k, k).sum(axis=(1, 3))
            self.assertEqual(sorted(np.unique(blocks).tolist()), [0, k * k])
            rows, columns = np.nonzero(blocks)
            self.assertEqual((len(rows), len(set(rows.tolist()))), (26, 1))
            self.assertEqual((int(columns.min()), int(columns.max())), (25, 50))
            centres = (columns + 0.5) * 4.0
            self.assertEqual((float(centres[0]), float(centres[-1]), float(centres[-1] - centres[0])),
                             (102.0, 202.0, 100.0))
            self.assertEqual(float(rd.in_box((100.0, 196.0, 204.0, 200.0), grid).sum()), float(mask.sum()))
        for point in (rd.STRIP_ORIGIN, rd.STRIP_DESTINATION):
            self.assertTrue(100.0 < point[0] < 204.0 and 196.0 < point[1] < 200.0)

    def test_the_untouchable_closes_the_only_way(self) -> None:
        """El intocable (148 a 152 m en x, más ancho que la franja) quita un solo nodo, el de la abscisa media: la
        franja queda en dos trozos de 12 y de 13 nodos."""
        self.assertEqual(rd.STRIP_UNTOUCHABLE_NAME, "Intocable de la franja")
        for step in STEPS:
            grid = rd.grid_of(step)
            closed = rd.strip_allowed(grid, untouchable=True)
            open_ = rd.strip_allowed(grid)
            self.assertAlmostEqual(float((open_ & ~closed).sum()) * step * step, 16.0, delta=1e-9)
            self.assertEqual(int(rd.strip_forbidden(grid).sum()),
                             int(rd.in_box(rd.STRIP_UNTOUCHABLE_BOX, grid).sum()))
            k = round(4.0 / step)
            blocks = closed.reshape(grid.nrows // k, k, grid.ncols // k, k).sum(axis=(1, 3))
            row = int(np.flatnonzero(blocks.any(axis=1))[0])
            present = (blocks[row] > 0).astype(int)
            changes = np.flatnonzero(np.diff(np.concatenate(([0], present, [0]))))
            self.assertEqual((changes[1] - changes[0], changes[3] - changes[2]), (12, 13))
            self.assertEqual(int(present.sum()), 25)
            self.assertFalse(bool(closed[rd.in_box((148.0, 194.0, 152.0, 202.0), grid)].any()))


class RavineTest(unittest.TestCase):
    """El barranco de 14 m a medio camino de la ruta, perpendicular a ella (plan §7.3)."""

    def test_the_depth_and_the_flanks(self) -> None:
        """Sobre el plano del 4 %, un barranco en V de 14 m de fondo y 30 m de semiancho (flancos del 46,7 %) en
        x = 200, que no cambia con y; fuera de ±30 m, el plano."""
        self.assertEqual((rd.RAVINE_DEPTH_M, rd.RAVINE_X_M, rd.RAVINE_HALF_WIDTH_M), (14.0, 200.0, 30.0))
        self.assertAlmostEqual(float(rd.ravine_depth_m(np.array([200.0]))[0]), 14.0, delta=1e-12)
        np.testing.assert_array_equal(rd.ravine_depth_m(np.array([169.9, 230.1, 0.0, 400.0])), 0.0)
        for step in STEPS:
            grid = rd.grid_of(step)
            found = rd.ravine_terrain(grid)
            x, _y = rd.local_centers(grid)
            depth = (100.0 + 0.04 * x) - found
            np.testing.assert_allclose(depth, 14.0 * np.maximum(0.0, 1.0 - np.abs(x - 200.0) / 30.0),
                                       rtol=0.0, atol=1e-12)
            self.assertEqual(float(np.abs(np.diff(found, axis=0)).max()), 0.0)
            columns = np.nonzero(np.abs(x[0] - 185.0) <= step)[0]
            slope = (found[0, columns[1]] - found[0, columns[0]]) / step
            self.assertAlmostEqual(float(slope), 0.04 - 14.0 / 30.0, delta=1e-12)
            columns = np.nonzero(np.abs(x[0] - 215.0) <= step)[0]
            slope = (found[0, columns[1]] - found[0, columns[0]]) / step
            self.assertAlmostEqual(float(slope), 0.04 + 14.0 / 30.0, delta=1e-12)

    def test_halfway_and_perpendicular(self) -> None:
        """El barranco está en el punto medio de la ruta (de (40, 200) a (360, 200): 320 m en el este) y su eje es
        norte-sur: perpendicular a ella."""
        (x0, y0), (x1, y1) = rd.RAVINE_ORIGIN, rd.RAVINE_DESTINATION
        self.assertEqual((math.hypot(x1 - x0, y1 - y0), (x0 + x1) / 2.0), (320.0, rd.RAVINE_X_M))
        self.assertEqual(y0, y1)

    def test_the_scale_route(self) -> None:
        """A escala (plan §7.3), una ruta de 1.500 m en la rejilla de 1.654 × 1.699 celdas con el barranco a medio
        camino, solo bajo demanda: aquí, lo que no pesa (los puntos y el eje), no la rejilla de 2,81 M celdas."""
        grid = rd.scale_grid()
        spec = rd.scale_ravine_spec()
        (x0, y0), (x1, y1) = spec.origin, spec.destination
        self.assertEqual((grid.ncols, grid.nrows), (1654, 1699))
        self.assertEqual(math.hypot(x1 - x0, y1 - y0), 1_500.0)
        self.assertEqual((x0 + x1) / 2.0, spec.axis_x)
        self.assertTrue(0.0 < x0 < x1 < grid.ncols * grid.dx and 0.0 < y0 < grid.nrows * grid.dy)
        window = gis.Grid(grid.west, grid.north, 1.0, 1.0, 20, 4)
        found = rd.ravine_terrain(window, axis_x=10.0, half_width_m=5.0, depth_m=4.0)
        for column in (9, 10):  # los dos centros a 0,5 m del eje: 4·(1 − 0,5/5) = 3,6 m de fondo
            self.assertAlmostEqual(float(found[0, column]), 100.0 + 0.04 * (column + 0.5) - 3.6, delta=1e-12)


class PitTest(unittest.TestCase):
    """El tajo de CE-017-05: la superficie de explotación hasta 125 m, la final restaurada con el fondo relleno
    hasta 140 m y un «solo relleno» posterior."""

    def setUp(self) -> None:
        self.grid = rd.GRID
        self.x, self.y = rd.local_centers(self.grid)
        self.expl = rd.pit_exploitation(self.grid)

    def test_the_exploitation_surface(self) -> None:
        """Terreno llano a 141 m; fondo de 80 × 80 m (6.400 celdas) a 125 m; paredes 1:1 desde el borde del fondo
        (125 + distancia al fondo, tope 141); y un corredor de 20 m de ancho que sube un 8 % desde el este del fondo
        (x = 140) y sale al terreno a los 200 m (x = 340, 125 + 0,08·200 = 141 m)."""
        z = self.expl
        self.assertEqual((rd.PIT_GROUND_M, rd.PIT_FLOOR_M), (141.0, 125.0))
        self.assertEqual(float(z[0, 0]), 141.0)
        self.assertEqual(float(z.max()), 141.0)
        self.assertEqual(float(z.min()), 125.0)
        self.assertEqual(int(np.count_nonzero(z == 125.0)), 6_400)
        np.testing.assert_array_equal(z == 125.0, rd.in_box(rd.PIT_FLOOR_BOX, self.grid))
        wall = {(59.5, 160.5): 125.5, (50.5, 160.5): 134.5, (44.5, 160.5): 140.5, (43.5, 160.5): 141.0}
        for (px, py), wanted in wall.items():
            column, row = int(px - 0.5), int(400 - py - 0.5)
            self.assertEqual(float(z[row, column]), wanted, (px, py))
        self.assertEqual(float(z[239, 100]), 125.0)  # el centro del fondo, (100,5; 160,5)

    def test_the_corridor(self) -> None:
        """La rasante del corredor, 125 + 0,08·(x − 140), en las celdas de 150 < y < 170 y 140 < x < 340: 125,04 m
        en la primera columna, 140,96 en la última y el 8 % exacto entre columnas; 20 filas; a los lados, el terreno."""
        corridor = rd.in_box((140.0, 150.0, 340.0, 170.0), self.grid)
        self.assertEqual(int(corridor.sum()), 20 * 200)
        rows = np.flatnonzero(corridor.any(axis=1))
        self.assertEqual(len(rows), 20)
        strip = self.expl[rows[0]]
        columns = np.flatnonzero(corridor[rows[0]])
        np.testing.assert_allclose(strip[columns], 125.0 + 0.08 * (self.x[rows[0], columns] - 140.0),
                                   rtol=0.0, atol=1e-12)
        self.assertAlmostEqual(float(strip[columns[0]]), 125.04, delta=1e-12)
        self.assertAlmostEqual(float(strip[columns[-1]]), 140.96, delta=1e-12)
        np.testing.assert_allclose(np.diff(strip[columns]) / 1.0, 0.08, rtol=0.0, atol=1e-12)
        self.assertEqual(rd.PIT_CORRIDOR_PCT, 8.0)
        self.assertAlmostEqual(rd.PIT_FLOOR_M + 0.08 * (340.0 - 140.0), rd.PIT_GROUND_M, delta=1e-12)
        self.assertEqual(float(self.expl[int(400 - 149.5 - 0.5), 250]), 141.0)  # el lado sur del corredor
        self.assertEqual(float(self.expl[int(400 - 170.5 - 0.5), 250]), 141.0)  # el lado norte

    def test_the_final_surface(self) -> None:
        """La final restaurada tiene el fondo relleno hasta 140 m: ``max(explotación, 140)``; el relleno suma, a mano
        con bucles de Python por celda en la rejilla de 2 m, lo mismo que da el cálculo con arrays; del corredor
        solo queda lo que pasa de 140 m (la rasante supera 140 m desde x = 327,5: 12 columnas de 20 celdas)."""
        final = rd.pit_final(self.grid)
        self.assertEqual(float(final.min()), 140.0)
        np.testing.assert_array_equal(final, np.maximum(self.expl, 140.0))
        corridor = rd.in_box((140.0, 150.0, 340.0, 170.0), self.grid)
        remains = corridor & (final == self.expl)
        self.assertEqual(int((remains & (self.x > 327.6)).sum()), 12 * 20)
        coarse = rd.grid_of(2.0)
        cx, cy = rd.local_centers(coarse)
        filled = 0.0
        for row in range(coarse.nrows):
            for column in range(coarse.ncols):
                px, py = float(cx[row, column]), float(cy[row, column])
                dx = max(60.0 - px, px - 140.0, 0.0)
                dy = max(120.0 - py, py - 200.0, 0.0)
                z = min(125.0 + max(dx, dy), 141.0)
                if 140.0 < px < 340.0 and 150.0 < py < 170.0:
                    z = min(z, 125.0 + 0.08 * (px - 140.0))
                filled += max(140.0 - z, 0.0) * 4.0
        found = float((rd.pit_final(coarse) - rd.pit_exploitation(coarse)).sum()) * 4.0
        self.assertAlmostEqual(found, filled, delta=filled * 1e-12)
        self.assertEqual(rd.PIT_RESTORED_M, 140.0)

    def test_the_fill_afterwards(self) -> None:
        """El «solo relleno» posterior sube a 130 m la zona (80, 140, 120, 180) del fondo: 1.600 celdas, 5 m de
        diferencia máxima y 8.000 m³; el resto de la explotación no cambia."""
        after = rd.pit_after_fill(self.grid)
        box = rd.in_box(rd.PIT_FILL_BOX, self.grid)
        self.assertEqual(int(box.sum()), 1_600)
        self.assertEqual(rd.PIT_FILL_LEVEL_M, 130.0)
        np.testing.assert_array_equal(after[box], 130.0)
        np.testing.assert_array_equal(after[~box], self.expl[~box])
        diff = after - self.expl
        self.assertEqual((float(diff.max()), int(np.count_nonzero(diff)), float(diff.sum())), (5.0, 1_600, 8_000.0))
        self.assertTrue(bool(np.all(self.expl[box] == 125.0)))
        self.assertTrue(80.0 < rd.PIT_DESTINATION[0] < 120.0 and 140.0 < rd.PIT_DESTINATION[1] < 180.0)

    def test_the_accessibility_by_hand(self) -> None:
        """Con un oráculo propio (celdas del ≤ 16 % de pendiente local con una apertura de un paso que hace de ancho
        mínimo, de la entrada hacia fuera): sobre la explotación se llega al fondo, a 125 m, por el corredor; sobre
        la final, con el fondo a 140 m, solo hasta 140 m."""
        coarse = rd.grid_of(2.0)
        entry = rd.cell_of(rd.PIT_ENTRY, coarse)
        for erosion in (0, 1):
            found = {}
            for name, surface in (("expl", rd.pit_exploitation(coarse)), ("final", rd.pit_final(coarse))):
                transitable = rd.oracle_slope_pct(surface, 2.0) <= 16.0
                transitable = rd.opening(transitable, erosion)
                reach = rd.oracle_reachable(transitable, [entry])
                found[name] = (float(surface[reach].min()), float(surface[reach].max()))
            self.assertEqual(found["expl"], (125.0, 141.0), erosion)
            self.assertEqual(found["final"], (140.0, 141.0), erosion)
        self.assertEqual((rd.PIT_Z_MIN_EXPLOITATION_M, rd.PIT_Z_MIN_FINAL_M), (125.0, 140.0))


class BankTest(unittest.TestCase):
    """La cantera con bancos y una rampa (CE-017-07, E4): una entrada a 140 m, cuatro bermas a 135, 125, 115 y 105 m,
    una rampa grabada que comunica las tres superiores, una plataforma y zonas «requiere acceso»."""

    def setUp(self) -> None:
        self.coarse = rd.grid_of(2.0)
        self.surface = rd.bank_surface(self.coarse)

    def test_the_benches(self) -> None:
        """Perfil en y: 140 m al sur, caras de 5 m (en 6 m de ancho) y de 10 m (en 10 m) y bermas de 20 m a 135, 125,
        115 y 105 m, y una pared al norte de 35 m en 36 m; sin cambio en x fuera de las rampas."""
        grid = rd.GRID
        z = rd.bank_surface(grid)
        x, y = rd.local_centers(grid)
        column = int(np.argmin(np.abs(x[0] - 300.5)))
        for py, wanted in ((20.5, 140.0), (56.5, 135.0), (86.5, 125.0), (116.5, 115.0), (146.5, 105.0),
                           (43.5, 140.0 - 5.0 * 3.5 / 6.0), (71.5, 135.0 - 5.5), (101.5, 125.0 - 5.5),
                           (131.5, 115.0 - 5.5), (300.5, 140.0), (174.0 + 0.5, 105.0 + 35.0 * 18.5 / 36.0)):
            row = int(np.argmin(np.abs(y[:, 0] - py)))
            self.assertAlmostEqual(float(z[row, column]), wanted, delta=1e-12, msg=str(py))
        free = x[0] > 150.0  # las rampas acaban en x = 140: más al este, el perfil no depende de x
        np.testing.assert_array_equal(z[:, free], np.repeat(z[:, free][:, :1], int(free.sum()), axis=1))
        slopes = [(5.0, 6.0), (10.0, 10.0), (10.0, 10.0), (10.0, 10.0), (35.0, 36.0)]
        for rise, run in slopes:
            self.assertGreaterEqual(100.0 * rise / run, 83.0)
        self.assertEqual(rd.BANK_ENTRANCE_M, 140.0)
        self.assertEqual(rd.BANK_LEVELS, (135.0, 125.0, 115.0, 105.0))

    def test_the_berms(self) -> None:
        """Cuatro bermas de 400 × 20 m = 8.000 m² (≥ 300 m²), planas, a 135, 125, 115 y 105 m, sin solaparse, en 1 y en
        2 m."""
        for step in STEPS:
            grid = rd.grid_of(step)
            berms = rd.bank_berms(grid)
            self.assertEqual(sorted(np.unique(berms[~np.isnan(berms)]).tolist()), [105.0, 115.0, 125.0, 135.0])
            for level in rd.BANK_LEVELS:
                area = float(np.count_nonzero(berms == level)) * step * step
                self.assertEqual(area, rd.BANK_BERM_AREA_M2)
            self.assertEqual(rd.BANK_BERM_AREA_M2, 400.0 * 20.0)
            self.assertGreater(rd.BANK_BERM_AREA_M2, rd.ACCESS.min_berm_area_m2)
            self.assertEqual(int(np.count_nonzero(~np.isnan(berms))), int(4 * 8_000 / (step * step)))
        for low, high in rd.BANK_BERM_RANGES:
            self.assertEqual(high - low, 20.0)
            self.assertEqual(low % 2.0, 0.0)  # los bordes caen en bordes de celda también en 2 m

    def test_the_ramps(self) -> None:
        """Tres rampas del 12,5 % (12,5 m por cada 100 m): de 140 a 135 m (40 m), de 125 a 135 m (80 m, hacia el
        oeste) y de 125 a 115 m (80 m): cruzan las caras 1, 2 y 3 y no la 4; en sus extremos, a ras de la berma."""
        self.assertEqual(len(rd.BANK_RAMPS), 3)
        for ramp in rd.BANK_RAMPS:
            self.assertAlmostEqual(100.0 * abs(ramp.z_end_m - ramp.z_start_m) / (ramp.x_end_m - ramp.x_start_m),
                                   12.5, delta=1e-12)
        spans = [(r.z_start_m, r.z_end_m, r.x_end_m - r.x_start_m) for r in rd.BANK_RAMPS]
        self.assertEqual(spans, [(140.0, 135.0, 40.0), (125.0, 135.0, 80.0), (125.0, 115.0, 80.0)])
        z = self.surface
        x, y = rd.local_centers(self.coarse)
        for ramp in rd.BANK_RAMPS:
            box = rd.in_box((ramp.x_start_m, ramp.y_start_m, ramp.x_end_m, ramp.y_end_m), self.coarse)
            self.assertGreater(int(box.sum()), 0)
            expected = ramp.z_start_m + (ramp.z_end_m - ramp.z_start_m) * (x - ramp.x_start_m) / (
                ramp.x_end_m - ramp.x_start_m)
            np.testing.assert_allclose(z[box], expected[box], rtol=0.0, atol=1e-12)
            at_start = box & (x == ramp.x_start_m + 1.0)
            at_end = box & (x == ramp.x_end_m - 1.0)
            self.assertLess(abs(float(z[at_start][0]) - ramp.z_start_m), 0.125 * 2.0)
            self.assertLess(abs(float(z[at_end][0]) - ramp.z_end_m), 0.125 * 2.0)
        # cada rampa cubre, sobre la cara que cruza, bermas de 8 m a un lado y a otro (sus caras: 40-46, 66-76 y 96-106)
        for ramp, face in zip(rd.BANK_RAMPS, ((40.0, 46.0), (66.0, 76.0), (96.0, 106.0)), strict=True):
            self.assertLessEqual(ramp.y_start_m, face[0] - 8.0)
            self.assertGreaterEqual(ramp.y_end_m, face[1] + 8.0)
        for first, second in zip(rd.BANK_RAMPS, rd.BANK_RAMPS[1:], strict=False):
            self.assertLess(first.y_end_m, second.y_start_m)

    def test_the_local_slopes(self) -> None:
        """La pendiente local (la mayor tangente a las ocho vecinas, a mano): 12,5 % en el interior de las rampas,
        0 % en las bermas libres y al menos el 83 % en las caras que no cruza una rampa."""
        slope = rd.oracle_slope_pct(self.surface, 2.0)
        x, y = rd.local_centers(self.coarse)
        for ramp in rd.BANK_RAMPS:
            inside = rd.in_box((ramp.x_start_m + 4.0, ramp.y_start_m + 4.0, ramp.x_end_m - 4.0,
                                ramp.y_end_m - 4.0), self.coarse)
            self.assertGreater(int(inside.sum()), 100)
            np.testing.assert_allclose(slope[inside], 12.5, rtol=0.0, atol=1e-9)
        free_berm = rd.in_box((150.0, 110.0, 350.0, 122.0), self.coarse)
        np.testing.assert_array_equal(slope[free_berm], 0.0)
        face_4 = rd.in_box((150.0, 128.0, 350.0, 134.0), self.coarse)
        self.assertGreaterEqual(float(slope[face_4].min()), 99.0)
        far_wall = rd.in_box((150.0, 160.0, 350.0, 188.0), self.coarse)
        self.assertGreaterEqual(float(slope[far_wall].min()), 97.0)

    def test_what_is_communicated(self) -> None:
        """Desde la entrada se llega, por celdas del ≤ 16 % (con y sin una apertura de un paso de ancho), a las bermas de
        135, 125 y 115 m y no a la de 105 m: cota mínima alcanzable 115 m y máxima 140 m; la plataforma de la berma de
        125 m se alcanza (a 125 m), la zona «requiere acceso» de la berma de 105 m no y la de la de 135 m sí."""
        entry = rd.cell_of(rd.BANK_ENTRY, self.coarse)
        berms = rd.bank_berms(self.coarse)
        platform = rd.bank_platform_mask(self.coarse)
        for erosion in (0, 1):
            transitable = rd.opening(rd.oracle_slope_pct(self.surface, 2.0) <= 16.0, erosion)
            reach = rd.oracle_reachable(transitable, [entry])
            communicated = [level for level in rd.BANK_LEVELS if bool((reach & (berms == level)).any())]
            self.assertEqual(communicated, [135.0, 125.0, 115.0], erosion)
            self.assertEqual((float(self.surface[reach].min()), float(self.surface[reach].max())),
                             (rd.BANK_Z_MIN_M, rd.BANK_Z_MAX_M), erosion)
            self.assertEqual(float(self.surface[reach & platform].min()), rd.BANK_PLATFORM_Z_M, erosion)
            self.assertEqual(int((reach & platform).sum()), int(platform.sum()), erosion)
            without = rd.bank_zone_mask("Zona sin acceso", self.coarse)
            with_access = rd.bank_zone_mask("Zona con acceso", self.coarse)
            self.assertFalse(bool((reach & without).any()))
            self.assertTrue(bool(np.all(reach[with_access])), erosion)
            self.assertFalse(bool(reach[rd.in_box((0.0, 200.0, 400.0, 400.0), self.coarse)].any()))  # el llano del norte
        self.assertEqual((rd.BANK_COMMUNICATED, rd.BANK_NOT_COMMUNICATED), ((135.0, 125.0, 115.0), (105.0,)))
        self.assertEqual((rd.BANK_Z_MIN_M, rd.BANK_Z_MAX_M), (115.0, 140.0))

    def test_the_platform_and_the_zones(self) -> None:
        """La plataforma (10, 80, 50, 92) = 480 m² en la berma de 125 m, al oeste de las rampas; la zona sin acceso (160,
        140, 220, 152) = 720 m² en la de 105 m y la con acceso (160, 52, 200, 62) = 400 m² en la de 135 m, al este de
        ellas; el hueco entre la zona sin acceso y la berma de 115 m es de 14 m (sin contar el ancho mínimo)."""
        self.assertEqual(float(rd.bank_platform_mask(self.coarse).sum()) * 4.0, 480.0)
        self.assertEqual(float(rd.bank_zone_mask("Zona sin acceso", self.coarse).sum()) * 4.0, 720.0)
        self.assertEqual(float(rd.bank_zone_mask("Zona con acceso", self.coarse).sum()) * 4.0, 400.0)
        self.assertEqual(rd.BANK_PLATFORM_BOX, (10.0, 80.0, 50.0, 92.0))
        berms = rd.bank_berms(self.coarse)
        for mask, level in ((rd.bank_platform_mask(self.coarse), 125.0),
                            (rd.bank_zone_mask("Zona sin acceso", self.coarse), 105.0),
                            (rd.bank_zone_mask("Zona con acceso", self.coarse), 135.0)):
            self.assertTrue(bool(np.all(berms[mask] == level)))
        for ramp in rd.BANK_RAMPS:
            self.assertLess(rd.BANK_PLATFORM_BOX[2], ramp.x_start_m)
            for name in ("Zona sin acceso", "Zona con acceso"):
                self.assertGreater(rd.BANK_ZONE_BOXES[name][0], ramp.x_end_m)
        gap = rd.BANK_ZONE_BOXES["Zona sin acceso"][1] - rd.BANK_BERM_RANGES[2][1]
        self.assertEqual(gap, 14.0)
        self.assertEqual(rd.BANK_ZONE_LEVEL_GAP_M, 10.0)  # 115 − 105
        constraints = rd.bank_zone_constraints()
        self.assertEqual([c.code for c in constraints], ["zona_sin_acceso", "zona_con_acceso"])
        self.assertTrue(all(c.ctype.value == "requires_access" for c in constraints))

    def test_the_entry_is_on_the_ground(self) -> None:
        """La entrada (10, 20) está en el terreno llano a 140 m, al sur de la primera cara."""
        x, y = rd.BANK_ENTRY
        self.assertEqual(float(self.surface[rd.cell_of(rd.BANK_ENTRY, self.coarse)]), 140.0)
        self.assertTrue(x < 20.0 and y < 32.0)


class LayersTest(unittest.TestCase):
    """Las capas del proyecto (plan §5.2.1) y las líneas con Z."""

    def test_the_layers(self) -> None:
        """Cinco capas de entidades (puntos, ejes, zonas, plataformas y entradas), de puntos, de líneas y de polígonos."""
        found = {layer.name: layer for layer in rd.layers()}
        self.assertEqual(tuple(found), rd.LAYERS)
        self.assertEqual(len(rd.LAYERS), 5)
        self.assertEqual({found[name].kind for name in rd.LAYERS},
                         {"point", "line", "polygon"})
        points = found[rd.POINTS_LAYER]
        self.assertEqual(points.names[0:2], ("Origen rampa", "Destino rampa"))
        self.assertEqual(len(set(points.names)), len(points.names))
        axes = found[rd.AXES_LAYER]
        self.assertEqual(axes.names[0:3], ("Eje de 200 m", "Esquina de 40 m", "Esquina de 15 m"))
        self.assertIn("Eje de dos partes", axes.names)
        parts = axes.entities[axes.names.index("Eje de dos partes")]
        self.assertEqual(len(parts), 2)
        self.assertEqual(found[rd.ZONES_LAYER].fields["cota"], (125.0, 115.0))
        platforms = found[rd.PLATFORMS_LAYER]
        self.assertEqual(platforms.names, ("P1", "Relleno sobre la calzada", "Plataforma de la berma 125"))
        self.assertEqual(platforms.fields["ancho"], (30.0, 20.0, 12.0))
        self.assertEqual(platforms.fields["cota_inicial"], (112.0, 111.0, 125.0))
        self.assertEqual(found[rd.ENTRIES_LAYER].names[0], "Entrada de la cantera de bancos")

    def test_the_points_are_where_the_cases_say(self) -> None:
        """Cada origen y destino de los casos es el de su constante y cae dentro de su terreno (salvo el punto fuera
        de la rejilla, a propósito); el destino en P1 cae en su huella y el eje del ramal sale de su eje."""
        points = next(layer for layer in rd.layers() if layer.name == rd.POINTS_LAYER)
        local = {name: tuple(entity[0][0][0] - np.asarray(rd.BASE))
                 for name, entity in zip(points.names, points.entities, strict=True)}
        self.assertEqual(local["Origen rampa"], rd.RAMP_ORIGIN)
        self.assertEqual(local["Destino rampa"], rd.RAMP_DESTINATION)
        self.assertEqual(local["Origen ladera"], rd.HILL_ORIGIN)
        self.assertEqual(local["Destino ladera"], rd.HILL_DESTINATION)
        self.assertEqual(local["Origen franja"], rd.STRIP_ORIGIN)
        self.assertEqual(local["Destino franja"], rd.STRIP_DESTINATION)
        self.assertEqual(local["Origen barranco"], rd.RAVINE_ORIGIN)
        self.assertEqual(local["Destino barranco"], rd.RAVINE_DESTINATION)
        self.assertEqual(local["Origen tajo"], rd.PIT_ORIGIN)
        self.assertEqual(local["Destino tajo"], rd.PIT_DESTINATION)
        self.assertEqual(local["Destino del ramal"], rd.BRANCH_DESTINATION)
        self.assertLess(local["Punto fuera de la rejilla"][0], 0.0)
        footprint = rd.platform_footprint_box("P1")
        self.assertEqual(footprint, (300.0, 185.0, 340.0, 215.0))
        px, py = local["Punto en P1"]
        self.assertTrue(footprint[0] < px < footprint[2] and footprint[1] < py < footprint[3])
        self.assertEqual(rd.platform_footprint_box("Relleno sobre la calzada"), (230.0, 190.0, 250.0, 210.0))
        self.assertEqual(rd.platform_footprint_box("Plataforma de la berma 125"), rd.BANK_PLATFORM_BOX)
        self.assertEqual(rd.BRANCH_ORIGIN_ABSCISSA_M, 100.0)
        self.assertEqual(rd.RAMP_ORIGIN[0] + rd.BRANCH_ORIGIN_ABSCISSA_M, 200.0)  # (200, 200) del eje de la pista
        self.assertEqual(rd.BRANCH_DESTINATION, (200.0, 260.0))

    def test_the_chain_is_trivially_feasible(self) -> None:
        """La cadena P1 → pista → ramal sobre el plano del 4 %: la pista sube 8,2 m en 205 m (un 4 %) hasta P1 y el ramal
        va a cota constante: ningún paso pasa de pd (la ruta de verdad la prueban T08 y T19)."""
        z = lambda x: rd.RAMP_Z0_M + 0.04 * x  # noqa: E731
        road = (z(305.0) - z(100.0)) / (305.0 - 100.0)
        self.assertAlmostEqual(100.0 * road, 4.0, delta=1e-12)
        self.assertEqual(z(200.0), z(rd.BRANCH_DESTINATION[0]))
        self.assertLess(112.0 - z(300.0), 0.01)  # P1 (112 m) a ras del terreno en su borde oeste

    def test_the_defective_axes(self) -> None:
        """Los ejes con defecto de RF-017-04, en el margen norte de la ventana: se corta a sí mismo, de longitud cero,
        de dos partes y con un vértice repetido; ninguno lleva Z (la capa de entidades guarda solo X e Y)."""
        axes = next(layer for layer in rd.layers() if layer.name == rd.AXES_LAYER)
        by_name = dict(zip(axes.names, axes.entities, strict=True))
        crossing = by_name["Eje que se corta"][0][0]
        self.assertEqual(crossing.shape, (4, 2))
        zero = by_name["Eje de longitud cero"][0][0]
        np.testing.assert_array_equal(zero[0], zero[1])
        repeated = by_name["Eje con vértice repetido"][0][0]
        np.testing.assert_array_equal(repeated[1], repeated[2])
        for entity in axes.entities:
            for part in entity:
                self.assertEqual(part[0].shape[1], 2)

    def test_the_3d_lines(self) -> None:
        """Dos líneas con Z (la irregular y la lisa) para la tabla de líneas de rotura."""
        lines = rd.breaklines()
        self.assertEqual(len(lines), 2)
        np.testing.assert_array_equal(lines[0], rd.axis_3d_irregular())
        np.testing.assert_array_equal(lines[1], rd.axis_3d_smooth())
        self.assertTrue(rd.BREAKLINES_LAYER.startswith("gis_brk_"))

    def test_a_new_array_every_time(self) -> None:
        rd.layers()[0].entities[0][0][0][...] = 0.0
        self.assertNotEqual(float(rd.layers()[0].entities[0][0][0][0, 0]), 0.0)
        rd.axis_3d_irregular()[...] = 0.0
        self.assertNotEqual(float(rd.axis_3d_irregular()[0, 2]), 0.0)


class OraclesTest(unittest.TestCase):
    """Los oráculos propios de las pruebas (pendiente local, alcance y erosión), con casos hechos a mano."""

    def test_the_local_slope(self) -> None:
        """Un plano del 10 % al este tiene el 10 % de pendiente local en el interior y en los bordes (solo cuenta lo que
        hay); un escalón de 3 m en 1 m da el 300 % a los dos lados y la diagonal (3 m en 1,414 m) no la supera."""
        plane = np.tile(0.1 * np.arange(6)[None, :], (4, 1))
        np.testing.assert_allclose(rd.oracle_slope_pct(plane, 1.0), 10.0, atol=1e-12)
        step = np.zeros((4, 6))
        step[:, 3:] = 3.0
        found = rd.oracle_slope_pct(step, 1.0)
        np.testing.assert_allclose(found[:, 2:4], 300.0, atol=1e-12)
        np.testing.assert_array_equal(found[:, 0], 0.0)

    def test_reachability(self) -> None:
        """Las celdas 4-conexas con la semilla: dos mitades separadas por una columna cerrada no se comunican; la
        diagonal no cuenta; una semilla cerrada no alcanza nada."""
        mask = np.ones((5, 7), dtype=bool)
        mask[:, 3] = False
        left = rd.oracle_reachable(mask, [(2, 0)])
        self.assertEqual(int(left.sum()), 15)
        self.assertFalse(bool(left[:, 4:].any()))
        diagonal = np.array([[True, False], [False, True]])
        self.assertEqual(int(rd.oracle_reachable(diagonal, [(0, 0)]).sum()), 1)
        self.assertEqual(int(rd.oracle_reachable(mask, [(2, 3)]).sum()), 0)

    def test_opening(self) -> None:
        """La apertura (erosión y dilatación con la cruz) quita lo más fino que la cruz (una línea de una celda) y deja
        lo grueso, con la forma de la cruz (de un bloque de 3 × 3, la cruz de 5 celdas: la
        erosión deja el centro y la dilatación lo ensancha a la cruz); con 0 pasos, la máscara."""
        mask = np.zeros((9, 9), dtype=bool)
        mask[1:4, 1:4] = True      # un bloque de 3 × 3
        mask[6, 1:8] = True        # una línea de una celda
        np.testing.assert_array_equal(rd.opening(mask, 0), mask)
        found = rd.opening(mask, 1)
        cross = np.zeros((9, 9), dtype=bool)
        cross[2, 1:4] = True
        cross[1:4, 2] = True
        np.testing.assert_array_equal(found, cross)
        self.assertEqual(int(found.sum()), 5)

    def test_erosion(self) -> None:
        """Erosionar 1 paso quita las celdas con una vecina 4-conexa cerrada (y las del borde de la rejilla)."""
        mask = np.ones((5, 5), dtype=bool)
        np.testing.assert_array_equal(rd.erode(mask, 0), mask)
        once = rd.erode(mask, 1)
        self.assertEqual(int(once.sum()), 9)
        self.assertTrue(bool(once[1:4, 1:4].all()))


class ScaleDataTest(unittest.TestCase):
    """Los datos de escala de RNF-017-01 a 10 (plan §7.3): solo lo que no pesa; la rejilla de 2,81 M celdas con su
    terreno es **bajo demanda** (lo usa T34) y no se construye en ``check.py``."""

    def test_the_sizes(self) -> None:
        """La rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M). Con la malla de la ruta de 4 m caben 413 × 424 bloques
        completos (175.112 nodos) y sobran 2 columnas y 3 filas: el plan dice «413 × 425 = 175.525» (una redondeo de
        la rejilla a 1.652 × 1.700) y la tarea T06 decide qué hace con los bloques parciales del borde."""
        grid = rd.scale_grid()
        self.assertEqual((grid.ncols, grid.nrows, grid.ncols * grid.nrows), (1654, 1699, 2_810_146))
        self.assertEqual((grid.ncols // 4, grid.nrows // 4, (grid.ncols // 4) * (grid.nrows // 4)),
                         (413, 424, 175_112))
        self.assertEqual((grid.ncols % 4, grid.nrows % 4), (2, 3))

    def test_the_long_axes(self) -> None:
        """Un eje de 2.035 m con 61 curvas (63 vértices) y otro de 5 km con 163 vértices (161 curvas), de tramos que
        giran ±20°: la tangente de R = 20 m (3,5 m) cabe en cada tramo; absolutos y float64. El de 2 km cabe en la rejilla
        de escala (en diagonal); el de 5 km no (la rejilla mide 1,65 km): solo es para el eje y la rasante (RNF-017-03)."""
        short = rd.scale_axis_2km()
        long = rd.scale_axis_5km()
        self.assertEqual((short.shape, long.shape), ((63, 2), (163, 2)))
        self.assertEqual((short.dtype, long.dtype), (np.float64, np.float64))
        for axis, curves, length in ((short, 61, 2_035.0), (long, 161, 5_013.0)):
            legs = np.hypot(*np.diff(axis, axis=0).T)
            self.assertEqual(len(legs), curves + 1)
            self.assertAlmostEqual(float(legs.sum()), length, delta=1e-6)
            headings = np.arctan2(np.diff(axis[:, 0]), np.diff(axis[:, 1]))
            turns = np.abs(np.diff(headings))
            np.testing.assert_allclose(turns, math.radians(20.0), rtol=0.0, atol=1e-9)
            self.assertLessEqual(20.0 * math.tan(math.radians(10.0)), float(legs.min()) / 2.0)
        grid = rd.scale_grid()
        local = short - np.array(rd.origin_of(grid))
        self.assertTrue(bool((local[:, 0] > 0).all() and (local[:, 0] < grid.ncols).all()))
        self.assertTrue(bool((local[:, 1] > 0).all() and (local[:, 1] < grid.nrows).all()))

    def test_the_preview_lines(self) -> None:
        """Veinte pistas de 5.000 vértices para la vista previa de RNF-017-08."""
        lines = rd.scale_preview_lines()
        self.assertEqual((lines.shape, lines.dtype), ((20, 5_000, 3), np.float64))
        self.assertEqual((rd.SCALE_ROADS, rd.SCALE_ROAD_VERTICES), (20, 5_000))
        self.assertTrue(bool(np.all(np.isfinite(lines))))

    def test_the_berms_platforms_and_zones(self) -> None:
        """250 tramos de berma, 5 plataformas y 20 zonas «requiere acceso» como cajas locales dentro de la rejilla y sin
        solaparse (rasterizarlas pesa y es de la tarea T34)."""
        berms = rd.scale_berm_boxes()
        platforms = rd.scale_platform_boxes()
        zones = rd.scale_zone_boxes()
        self.assertEqual((len(berms), len(platforms), len(zones)), (250, 5, 20))
        grid = rd.scale_grid()
        every = np.array([*berms, *platforms, *zones])
        self.assertTrue(bool((every[:, 0] >= 0).all() and (every[:, 2] <= grid.ncols).all()))
        self.assertTrue(bool((every[:, 1] >= 0).all() and (every[:, 3] <= grid.nrows).all()))
        for first, a in enumerate(berms):
            for b in berms[first + 1:first + 30]:
                self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
        for box in (*platforms, *zones):
            inside = [b for b in berms if b[0] <= box[0] and box[2] <= b[2] and b[1] <= box[1] and box[3] <= b[3]]
            self.assertEqual(len(inside), 1, box)
        self.assertGreater(min((b[2] - b[0]) * (b[3] - b[1]) for b in berms), rd.ACCESS.min_berm_area_m2)


class RoadProjectTest(rd.RoadProjectCase):
    """El proyecto de la cantera de la 015 con las superficies y las capas de las pistas, en la rejilla gruesa de 2 m."""

    def test_built_once_within_budget(self) -> None:
        """La plantilla se crea una vez por proceso y paso en ≤ 2 s de CPU (lo que añade a la cantera de la 015) y
        cada clase la copia en menos de 1 s."""
        template = rd.project_template(qfx.COARSE_STEP_M)
        self.assertIs(template, rd.project_template(qfx.COARSE_STEP_M))
        self.assertLessEqual(template["build_s"], rd.BUILD_BUDGET_S)
        started = time.process_time()
        with rd.open_road_project(step_m=qfx.COARSE_STEP_M) as (_project, _clock):
            elapsed = time.process_time() - started
        self.assertLess(elapsed, COPY_BUDGET_S)

    def test_the_015_project_is_still_there(self) -> None:
        """Lo de la cantera y de la 015 sigue igual: V01 y V02, la rejilla gruesa, las capas de la 014 y de plataformas y
        el terreno de partida."""
        self.assertEqual((self.v1.code, self.v2.code), ("V01", "V02"))
        self.assertEqual(self.grid, qfx.grid_of(qfx.COARSE_STEP_M))
        for layer in (*qfx.layers(), *efx.platform_layers()):
            found = self.read_layer(layer.name)
            self.assertTrue(qfx.same_entities(found.parts, layer.entities), layer.name)
        raster = gis_store.load_raster(self.project, qfx.START_DATASET)
        np.testing.assert_array_equal(raster.values, qfx.terrain(self.grid))

    def test_rasters_read_back(self) -> None:
        """Cada terreno, escrito como rejilla del proyecto, vuelve igual bit a bit a lo que dan las funciones del
        módulo en la rejilla gruesa."""
        self.assertEqual(tuple(rd.RASTERS), ("rampa", "rampa_lateral", "escalon", "ladera38", "franja", "barranco",
                                             "banco", "tajo", "tajo_final", "tajo_relleno"))
        for label, make in rd.RASTERS.items():
            name = rd.dataset_of(label)
            self.assertIsNotNone(self.record(name), name)
            raster = gis_store.load_raster(self.project, name)
            self.assertEqual(raster.grid, self.grid, name)
            self.assertEqual((raster.crs.epsg, raster.vertical.epsg), (25830, 5782))
            np.testing.assert_array_equal(raster.values, make(self.grid), name)

    def test_layers_read_back(self) -> None:
        """Las capas están en el proyecto como capas de entidades: su geometría bit a bit, sus ``fid`` (1, 2…), sus
        nombres y sus campos; las líneas son de X e Y (sin Z, trampa de ``docs/trampas.md`` §6)."""
        for layer in rd.layers():
            self.assertIsNotNone(self.record(layer.name), layer.name)
            found = self.read_layer(layer.name)
            self.assertEqual(found.kind, layer.kind, layer.name)
            self.assertEqual(found.fids, tuple(range(1, len(layer.entities) + 1)))
            self.assertTrue(qfx.same_entities(found.parts, layer.entities), layer.name)
            self.assertEqual(tuple(found.values["nombre"]), layer.names)
            for field, values in layer.fields.items():
                self.assertEqual(tuple(found.values[field]), values, (layer.name, field))
        axes = self.read_layer(rd.AXES_LAYER)
        self.assertEqual(axes.parts[0][0][0].shape[1], 2)

    def test_the_3d_lines_keep_their_z(self) -> None:
        """La tabla de líneas de rotura guarda la Z de las dos líneas (la única capa que la guarda) bit a bit."""
        self.assertIsNotNone(self.record(rd.BREAKLINES_LAYER))
        found = gis_store.load_lines(self.project, rd.BREAKLINES_LAYER)
        self.assertEqual(len(found), 2)
        for line, wanted in zip(found, rd.breaklines(), strict=True):
            np.testing.assert_array_equal(line.xyz, wanted)

    def test_the_zones_as_constraints_are_not_in_the_project(self) -> None:
        """Las zonas «requiere acceso» son datos de las pruebas, no están en el proyecto (las restricciones son las
        de la cantera de la 014)."""
        codes = {item.code for item in qfx.constraints()}
        self.assertFalse(codes & {"zona_sin_acceso", "zona_con_acceso"})


class PlanNamesTest(unittest.TestCase):
    """Los nombres de ``main`` en los que se apoya el plan 017 (§5; T01) existen con la forma que dice, salvo lo que
    se anota: ``bl/ui/constraint_panels.py`` dice «Not checked (R-40)» en la línea 1611 y no en la 1602 (que es su
    docstring)."""

    def test_domain_names(self) -> None:
        names = {
            "design.entities": ("EntityKind", "EntityType", "_TYPES", "register_entity_type", "chain_tails",
                                "registry", "detect_supports", "strongest", "retired_supports",
                                "declared_zone_of_runs"),
            "design.entity_store": ("entity_surfaces", "check_parameter_change", "bring_entities",
                                    "layers_sync_steps", "platform_compute_steps"),
            "design.entity_layer": (),
            "design.params": ("EntityParams", "entity_family", "entity_params", "check_entity_param"),
            "design.provenance": ("OPERATION_TYPES_BY_NAME", "ENTITY_OP_NAMES", "ENTITY_LAYER", "BERM_TABLE",
                                  "_BERMS_ROLE"),
            "design.store": ("DesignWriter", "RECOMPUTED", "recompute_run", "masks_steps"),
            "design.steps": ("Calculation", "platform_run"),
            "design.reproduce": (), "design.preview": (), "design.export": (),
            "design.quarry": ("axis_abscissa", "axis_abscissa_units", "corridor_window"),
            "design.edges": ("seed_envelope_steps", "created_steps"),
            "design.envelopes": ("reach_steps",),
            "design.platform": ("work_window", "_edge_units"),
            "design.supported_edge": ("outside_notice", "order_notice", "clipped_notice", "no_data_notice"),
            "design.morphology": ("opening",),
            "design.grids": ("label_components", "label_components_steps", "nearest_value_steps"),
            "design.report": ("max_tangents", "padded_rows"),
            "reserves.compliance": ("Counts", "Verdict", "Checker", "counts_of"),
            "reserves.compliance_store": ("select_bases", "verify_inputs", "verify_settings", "begin_verify",
                                          "check_sources", "freeze_findings"),
            "gis.masks.combine": ("ClassBit", "Masks"),
            "core.gpkg.wkb": ("encode_geometry", "decode_geometry", "EWKB_Z"),
        }
        for module, found in names.items():
            loaded = import_geoblender(module)
            for name in found:
                self.assertTrue(hasattr(loaded, name), f"{module}.{name}")

    def test_members_the_plan_relies_on(self) -> None:
        """``Counts.ACCESS``, ``Verdict.UNCHECKED``, ``ClassBit.ACCESS``, ``Masks.access``, el papel ``berms`` y las
        operaciones de las entidades de la 015 y la 016 (que ``road`` y ``access`` ampliarán en la T03)."""
        compliance = import_geoblender("reserves.compliance")
        combine = import_geoblender("gis.masks.combine")
        provenance = import_geoblender("design.provenance")
        self.assertTrue(hasattr(compliance.Counts, "ACCESS"))
        self.assertTrue(hasattr(compliance.Verdict, "UNCHECKED"))
        self.assertTrue(hasattr(combine.ClassBit, "ACCESS"))
        self.assertTrue(hasattr(combine.Masks, "access"))
        self.assertEqual(provenance._BERMS_ROLE, "berms")
        self.assertEqual(provenance.ENTITY_OP_NAMES,
                         ("des.platform", "des.stockpile_detect", "des.stockpile_removal", "des.buttress",
                          "des.body", "des.road", "des.road_access"))
        self.assertEqual(provenance.ENTITY_LAYER, "des.entity_layer")

    def test_blender_names(self) -> None:
        """``bl/ops/des.py``, ``bl/scene/des_views.LOADERS``, ``bl/props/core.OBJECT_KINDS``, ``bl/scene/views.BRANCHES``
        y los ficheros de ``bl/draw`` y ``bl/scene`` (que ``bl`` no deja importar aquí) se declaran en el código."""
        for module, found in (("ops/des.py", ("OPERATION_DEFS", "RECOMPUTE", "SUPPORTED_RECOMPUTE",
                                              "PARAMETER_PREFIXES", "_layers_after_recompute", "register")),
                              ("scene/des_views.py", ("LOADERS",)), ("props/core.py", ("OBJECT_KINDS",)),
                              ("scene/views.py", ("BRANCHES",))):
            source = (EXTENSION_DIR / "bl" / module).read_text(encoding="utf-8")
            declared = set()
            for node in ast.parse(source).body:
                target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
                if isinstance(target, ast.Name):
                    declared.add(target.id)
                if isinstance(node, ast.FunctionDef):
                    declared.add(node.name)
            for name in found:
                self.assertIn(name, declared, f"bl/{module} no declara {name}")
        for module in ("draw/entity.py", "scene/entity_views.py", "ui/des_panels.py", "ui/constraint_panels.py"):
            self.assertTrue((EXTENSION_DIR / "bl" / module).is_file(), module)
        text = (EXTENSION_DIR / "bl" / "ui" / "constraint_panels.py").read_text(encoding="utf-8")
        self.assertIn('tr("Not checked (R-40)")', text)

    def test_reserves_already_import_design(self) -> None:
        """``reserves.compliance_store`` ya importa ``design`` (la base de los acopios: lo que la T18 necesita para
        leer la accesibilidad por su papel sin saltarse la arquitectura); el algoritmo, ``compliance.py``, no."""
        def imports_design(name: str) -> bool:
            source = (EXTENSION_DIR / "reserves" / name).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "design":
                    return True
            return False

        self.assertTrue(imports_design("compliance_store.py"))
        self.assertFalse(imports_design("compliance.py"))

    def test_the_catalog_entries(self) -> None:
        """Las tres órdenes provisionales de «Pistas y entidades» son entradas sueltas de R-40; ``entries.toml`` tiene
        ``R-40`` y no ``017``."""
        menu = tomllib.loads((EXTENSION_DIR / "core" / "catalog" / "data" / "menus" / "07_design.toml")
                             .read_text(encoding="utf-8"))
        groups = {group["label"]["en"]: group for group in menu["menu"][0]["group"]}
        group = groups["Haul roads and entities"]
        loose = {item["key"]: item for item in group["item"] if "key" in item}
        for key in ("geoblender.des_draw_haul_road", "geoblender.des_route_haul_road",
                    "geoblender.des_burn_roads"):
            self.assertIn(key, loose, key)
            self.assertEqual(loose[key]["entry"], "R-40", key)
            self.assertNotIn("item", loose[key], key)
        entries = tomllib.loads((EXTENSION_DIR / "core" / "catalog" / "data" / "entries.toml")
                                .read_text(encoding="utf-8"))
        self.assertIn("R-40", entries)
        self.assertNotIn("017", entries)

    def test_the_design_fixtures_it_builds_on(self) -> None:
        """Lo que la cantera usa: los perfiles de la 013 y el ancla de 125 m."""
        self.assertEqual(qfx.EXPLOITATION_PROFILE.name, dfx.EXPL_10_60_6.name)
        self.assertEqual(qfx.FLOORS[0].level_m, 125.0)


if __name__ == "__main__":
    unittest.main()
