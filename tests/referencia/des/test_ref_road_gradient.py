# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia de la rasante acotada de la pista (spec 017, T11; HU-017-1 y HU-017-4; RF-017-15, RF-017-16, RF-017-17 y RF-017-18; CE-017-03; plan
017 §5.4 A5 y §5.8 H-4): el perfil del terreno en escalón y la rasante que da, contra el **cálculo analítico**.

Verifica **de forma independiente** lo que hace ``design.road_gradient``: la rasante del escalón se calcula a mano de dos maneras (la analítica del perfil
continuo y la de las mismas estaciones, H-4) y con un oráculo de fuerza bruta O(n²); el desnivel imposible, la media y el modo «eje 3D» salen de las
cifras de ``tests.support.road_data`` (``step_*``, ``SHORT_*`` y ``axis_3d_irregular``, hechas a mano). **Ningún** valor esperado se calcula llamando al
código bajo prueba. Todo es sintético, en el dominio y sin Blender.

- **CE-017-03 · la rampa del escalón** (RF-017-15): un perfil del terreno en escalón (0 m hasta la abscisa 0 y 6 m después, en un eje de 200 m centrado en
  el escalón) con pd = 10 % da una rampa del 5 % (pd/2) entre las abscisas −60 y +60 m y una diferencia con el terreno de 180 m·m **en el perfil
  continuo**; con estaciones cada ``w`` m, a ≤ 10⁻⁹ m del cálculo en esas mismas estaciones (5,021 % y 178,5 m·m con ``w`` = 0,5 m: H-4), y la cifra continua
  con un error O(``w``): la diferencia es ``180 − 3·w`` exacta.
- **CE-017-03 · el desnivel imposible** (RF-017-16): los extremos a 0 y a 20 m en un eje de 100 m con pd = 10 % → «necesaria 200 m, el eje mide 100 m»; y por
  lo que las curvas acortan la ruta.
- **CE-017-03 · la media** (RF-017-17): con pm = 2 % la media de la rampa del escalón (6 m sobre 200 m, el 3 %) da el aviso con la media, el límite y los
  tramos de mayor pendiente (la confirmación expresa y el motivo registrado son de la operación, T21).
- **CE-017-03 · el «eje 3D»** (RF-017-18): un eje 3D de Z irregular da el aviso por tramo, el de la media y el del radio, y la línea no cambia.
"""

from __future__ import annotations

import hashlib
import unittest

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender

road_gradient = import_geoblender("design.road_gradient")
road_axis = import_geoblender("design.road_axis")
gis_raster = import_geoblender("gis.raster")

TOL = 1e-9
"""Metros: RF-017-15 pide la rasante a ≤ 10⁻⁹ m del cálculo analítico."""
PD = rd.STEP_RAMP_PCT * 2.0 / 100.0
"""La pendiente de diseño del caso: 10 %, tanto por uno (la rampa del escalón es la mitad, pd/2 = 5 %)."""
PROFILE = rd.road_profile()
"""El perfil de referencia (pd 10 %, pm 10 %, Rmín 12 m)."""


def digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def step_axis(step_m: float) -> object:
    """El eje de 200 m del escalón (recto, de oeste a este) con estaciones cada ``step_m`` m; la abscisa 100 m es el escalón."""
    return road_axis.axis_of(rd.absolute(rd.STEP_AXIS), 20.0, 12.0, step_m)


def step_line(axis: object) -> np.ndarray:
    """La rasante del escalón en las estaciones de ``axis`` con el terreno continuo (0 m antes del escalón y 6 m desde él) y los extremos en sus
    cotas (0 y 6 m), con pd = 10 %."""
    return road_gradient.gradient_line(axis.stations, rd.step_profile_m(axis.stations - 100.0), PD, rd.STEP_LOW_M, rd.STEP_HIGH_M)


class StepTest(unittest.TestCase):
    def test_the_step_gives_a_ramp_of_pd_over_2_in_the_same_stations(self) -> None:
        """CE-017-03, RF-017-15, H-4: con estaciones cada 0,5 m la rasante es, a ≤ 10⁻⁹ m, la del cálculo a mano **en esas mismas estaciones** (la media
        de la minorante y la mayorante discretas: ``máx(0, (6 + pd·s)/2)`` antes del escalón y ``(mín(6, pd·(s + w)) + 6)/2`` desde él) y es la de un
        oráculo de fuerza bruta O(n²); la pendiente es el 5 % (pd/2) en todo tramo de la rampa salvo el del escalón (pd), y 0 fuera de ella."""
        axis = step_axis(0.5)
        self.assertEqual(len(axis.stations), 401)
        s = axis.stations - 100.0
        line = step_line(axis)
        np.testing.assert_allclose(line, rd.step_line_in_stations_by_hand(s, 10.0, 0.5), rtol=0.0, atol=TOL)
        np.testing.assert_allclose(line, rd.oracle_gradient_line(axis.stations, rd.step_profile_m(s), PD, 0.0, 6.0), rtol=0.0, atol=TOL)
        slope = np.diff(line) / 0.5
        middle = 0.5 * (s[:-1] + s[1:])
        np.testing.assert_allclose(slope[(middle > -59.9) & (middle < -0.6)], 0.05, rtol=0.0, atol=TOL)
        np.testing.assert_allclose(slope[(middle > 0.1) & (middle < 59.4)], 0.05, rtol=0.0, atol=TOL)
        np.testing.assert_allclose(slope[(middle > -0.4) & (middle < -0.1)], PD, rtol=0.0, atol=TOL)  # el tramo del escalón sube pd
        self.assertLessEqual(float(np.abs(slope[(middle < -60.1) | (middle > 59.6)]).max()), TOL)  # fuera de la rampa, horizontal

    def test_5_021_percent_and_178_5_metre_metres_with_w_0_5_m(self) -> None:
        """CE-017-03, H-4: con estaciones cada 0,5 m, la pendiente media de la rampa (de la abscisa −60 m, donde la rasante deja el 0, a la 59,5 m, donde
        llega a 6 m) es el 5,021 % (6 / 119,5) y la diferencia con el terreno suma 178,5 m·m (Σ|z − t|·w)."""
        axis = step_axis(0.5)
        s = axis.stations - 100.0
        line = step_line(axis)
        low, high = float(s[line > 1e-6].min() - 0.5), float(s[line >= 6.0 - 1e-6].min())
        self.assertAlmostEqual(low, -60.0, delta=TOL)
        self.assertAlmostEqual(high, 59.5, delta=TOL)
        self.assertAlmostEqual(100.0 * 6.0 / (high - low), 5.021, delta=5e-4)
        difference = float(np.abs(line - rd.step_profile_m(s)).sum() * 0.5)
        self.assertAlmostEqual(difference, 178.5, delta=TOL)

    def test_the_continuous_figures_are_recovered_with_an_error_of_order_w(self) -> None:
        """CE-017-03, H-4: la rampa del 5 % de −60 a +60 m y los 180 m·m son del perfil **continuo**; con estaciones cada ``w`` m la diferencia con el
        terreno es exactamente ``180 − 3·w`` (a mano: Σ de dos progresiones aritméticas) y la rasante está a ≤ pd·w/2 de la analítica
        ``clip(3 + (pd/2)·s, 0, 6)``: el error es O(w) y baja con ``w`` (1, 0,5, 0,25 y 0,125 m)."""
        errors = []
        for step in (1.0, 0.5, 0.25, 0.125):
            with self.subTest(w=step):
                axis = step_axis(step)
                s = axis.stations - 100.0
                line = step_line(axis)
                difference = float(np.abs(line - rd.step_profile_m(s)).sum() * step)
                self.assertAlmostEqual(difference, rd.step_diff_by_hand(10.0) - 3.0 * step, delta=TOL)
                self.assertLessEqual(abs(difference - rd.STEP_DIFF_MM), 3.0 * step + TOL)
                np.testing.assert_allclose(line, rd.step_grade_by_hand(s, 10.0), rtol=0.0, atol=PD * step / 2.0 + TOL)
                np.testing.assert_allclose(line, rd.step_line_in_stations_by_hand(s, 10.0, step), rtol=0.0, atol=TOL)
                errors.append(abs(difference - rd.STEP_DIFF_MM))
        self.assertEqual(errors, sorted(errors, reverse=True))
        self.assertAlmostEqual(errors[0] / errors[-1], 8.0, delta=1e-6)  # 3·w: de 1 a 0,125 m, ocho veces menos

    def test_the_mirrored_step_is_the_mirrored_line(self) -> None:
        """RF-017-15: el terreno recorrido al revés (un escalón hacia abajo) da la misma rasante invertida, con las cotas de los extremos cambiadas: la
        simetría del problema (la minorante y la mayorante no distinguen el sentido)."""
        axis = step_axis(0.5)
        terrain = rd.step_profile_m(axis.stations - 100.0)
        forward = road_gradient.gradient_line(axis.stations, terrain, PD, 0.0, 6.0)
        backward = road_gradient.gradient_line(axis.stations, terrain[::-1], PD, 6.0, 0.0)
        np.testing.assert_allclose(backward, forward[::-1], rtol=0.0, atol=TOL)

    def test_the_step_in_the_grid_of_the_project_with_the_bilinear_terrain(self) -> None:
        """CE-017-03, RF-017-15: con el terreno de la **rejilla** de la cantera (de 1 m) muestreado con interpolación bilineal en las estaciones del eje
        (el escalón de la rejilla es una rampa de 1 m, de la abscisa −0,5 a +0,5 m), la rasante es la del oráculo de fuerza bruta a ≤ 10⁻⁹ m, queda a ≤ 0,1 m
        de la del perfil continuo (la rampa de 1 m desplaza las envolventes 0,5 m·pd) y su pendiente es ≤ pd."""
        raster = rd.raster_of(rd.step_terrain())
        axis = step_axis(0.5)
        terrain = gis_raster.sample(raster, axis.points)
        self.assertEqual(terrain.dtype, np.float64)
        self.assertTrue(bool(np.isfinite(terrain).all()))
        line = road_gradient.gradient_line(axis.stations, terrain, PD, float(terrain[0]), float(terrain[-1]))
        np.testing.assert_allclose(line, rd.oracle_gradient_line(axis.stations, terrain, PD, float(terrain[0]), float(terrain[-1])), rtol=0.0, atol=TOL)
        np.testing.assert_allclose(line, rd.step_grade_by_hand(axis.stations - 100.0, 10.0), rtol=0.0, atol=0.1)
        self.assertLessEqual(float(np.abs(np.diff(line) / 0.5).max()), PD + TOL)


class ImpossibleDropTest(unittest.TestCase):
    def test_a_drop_of_20_m_over_100_m_at_10_percent_needs_200_m(self) -> None:
        """CE-017-03, RF-017-16: con los extremos a 0 y a 20 m en un eje de 100 m con pd = 10 %, el rechazo dice «necesaria 200 m, el eje mide 100 m» y el
        desnivel (20 m), y no cambia las cotas ni la pendiente por su cuenta: no hay rasante."""
        axis = road_axis.axis_of(rd.absolute(rd.SHORT_AXIS), 20.0, 12.0, 1.0)
        self.assertAlmostEqual(axis.length_m, 100.0, delta=TOL)
        with self.assertRaises(road_gradient.DropTooSteep) as caught:
            road_gradient.gradient_line(axis.stations, np.zeros(len(axis.stations)), PD, rd.SHORT_Z_START_M, rd.SHORT_Z_END_M)
        rejection = caught.exception
        self.assertAlmostEqual(rejection.needed_m, rd.SHORT_NEEDED_M, delta=TOL)
        self.assertAlmostEqual(rejection.length_m, 100.0, delta=TOL)
        self.assertAlmostEqual(rejection.drop_m, 20.0, delta=TOL)
        text = rejection.error(layer="trazados", entity="Pista corta", profile=PROFILE).text_in("es")
        self.assertIn("el eje mide 100 m y harían falta 200 m", text)
        self.assertIn("(20 m)", text)

    def test_the_curves_that_shorten_the_route_count(self) -> None:
        """RF-017-16: el desnivel se compara con la longitud del **eje** —con sus curvas, que acortan la ruta—, no con la de la poligonal: dos tramos
        perpendiculares de 40 m (80 m) con R = 20 m dan un eje de 71,416 m; un desnivel de 7,0 m (necesarios 70 m) cabe y uno de 7,5 m (75 m) no."""
        axis = road_axis.axis_of(rd.absolute(rd.CORNER_LONG), 20.0, 12.0, 1.0)
        self.assertAlmostEqual(axis.length_m, 71.41592653589793, delta=TOL)
        terrain = np.full(len(axis.stations), 100.0)
        fits = road_gradient.gradient_line(axis.stations, terrain, PD, 100.0, 107.0)
        self.assertEqual((float(fits[0]), float(fits[-1])), (100.0, 107.0))
        with self.assertRaises(road_gradient.DropTooSteep) as caught:
            road_gradient.gradient_line(axis.stations, terrain, PD, 100.0, 107.5)
        self.assertAlmostEqual(caught.exception.needed_m, 75.0, delta=TOL)
        self.assertAlmostEqual(caught.exception.length_m, axis.length_m, delta=TOL)
        self.assertLess(caught.exception.length_m, 80.0)


class MeanTest(unittest.TestCase):
    def test_the_mean_of_the_ramp_of_the_step_is_3_percent_and_pm_2_percent_gives_the_notice(self) -> None:
        """CE-017-03, RF-017-17, D-7: la media de la rampa del escalón es Σ|Δcota| / S = 6 m / 200 m = el 3 % (la rasante es monótona: no cuenta nada más)
        y con pm = 2 % da el aviso con la media (3,00 %), el límite (2,00 %) y los tramos de mayor pendiente con su abscisa y su lugar: el escalón (el 10 %,
        abscisa 99,5 m) y después el 5 % de la rampa por abscisa. Con pm = 3 % no hay aviso."""
        axis = step_axis(0.5)
        line = step_line(axis)
        self.assertAlmostEqual(road_gradient.mean_gradient(axis.stations, line), rd.STEP_MEAN_PCT / 100.0, delta=1e-12)
        profile = rd.road_profile(rd.profile_with(max_mean_gradient_pct=2.0))
        notice = road_gradient.mean_gradient_notice(axis, line, profile, "Pista del escalón")
        self.assertEqual(notice.code, "des.road_mean_gradient")
        self.assertAlmostEqual(notice.values["mean"], 3.0, delta=1e-9)
        self.assertEqual(notice.values["limit"], 2.0)
        found = road_gradient.steepest_stretches(axis, line)
        self.assertEqual([stretch.station_m for stretch in found], [99.5, 40.0, 40.5, 41.0, 41.5])
        self.assertAlmostEqual(found[0].gradient_pct, 10.0, delta=1e-9)
        for stretch in found[1:]:
            self.assertAlmostEqual(stretch.gradient_pct, 5.0, delta=1e-9)
        self.assertEqual([item.values["station"] for item in notice.values["stretches"]], [99.5, 40.0, 40.5, 41.0, 41.5])
        np.testing.assert_allclose([found[0].x, found[0].y], axis.points[199], rtol=0.0, atol=TOL)
        text = notice.text("es")
        for expected in ("3,00 %", "2,00 %", "abscisa 99,5 m", "10,00 %", "confirmación expresa", "motivo"):
            self.assertIn(expected, text)
        self.assertIsNone(road_gradient.mean_gradient_notice(axis, line, rd.road_profile(rd.profile_with(max_mean_gradient_pct=3.0)), "Pista del escalón"))


class Axis3dTest(unittest.TestCase):
    def test_an_irregular_z_gives_the_notice_per_stretch_the_mean_and_the_radius_and_the_line_does_not_change(self) -> None:
        """CE-017-03, RF-017-18: un «eje 3D» de Z irregular (tramos del 5, 5, 10, 15, −2, 8, 12, 0, 5 y 10 %, media del 7,2 %) con pd = 10 % y pm = 5 % da
        el aviso por tramo (el 15 % en la abscisa 60 m y el 12 % en la 120 m), el de la media (7,2 % frente a 5 %) y, con su esquina estrecha, el del radio, y
        **la línea no cambia** (su *hash*, con la Z)."""
        line = rd.axis_3d_irregular()
        bend = np.column_stack([rd.absolute(rd.CORNER_SHORT), [100.0, 101.0, 102.0]])
        before = (digest(line), digest(bend))
        profile = rd.road_profile(rd.profile_with(max_mean_gradient_pct=5.0, min_radius_m=16.0))
        axis = road_axis.axis_of(line, 20.0, 16.0, 20.0, reject_below_minimum=False)
        z = np.interp(axis.stations, 20.0 * np.arange(len(line)), line[:, 2])
        np.testing.assert_allclose(z, line[:, 2], rtol=0.0, atol=1e-12)  # las estaciones de 20 m son los vértices: la Z que se comprueba es la de la línea
        notices = road_gradient.check_axis_3d(axis, z, profile, "RDW-3D")
        self.assertEqual([n.code for n in notices], ["des.road_axis3d_gradient", "des.road_axis3d_gradient", "des.road_mean_gradient"])
        self.assertEqual([(n.values["station"], round(n.values["gradient"], 9)) for n in notices[:2]], [(60.0, 15.0), (120.0, 12.0)])
        self.assertAlmostEqual(notices[2].values["mean"], rd.AXIS_3D_MEAN_PCT, delta=1e-9)
        corner = road_axis.axis_of(bend, 20.0, 16.0, 1.0, reject_below_minimum=False)
        radius = road_gradient.check_axis_3d(corner, np.full(len(corner.stations), 100.0), profile, "RDW-3D")
        self.assertEqual([n.code for n in radius], ["des.road_axis3d_radius"])
        self.assertAlmostEqual(radius[0].values["radius"], 15.0, delta=TOL)
        self.assertEqual((digest(line), digest(bend)), before)

    def test_a_line_that_follows_the_4_percent_plane_has_nothing_to_say(self) -> None:
        """RF-017-18: la línea con Z sobre el plano del 4 % (≤ pd y ≤ pm, planta recta) no da ningún aviso."""
        line = rd.axis_3d_smooth()
        axis = road_axis.axis_of(line, 20.0, 12.0, 20.0, reject_below_minimum=False)
        z = np.interp(axis.stations, 20.0 * np.arange(len(line)), line[:, 2])
        self.assertEqual(road_gradient.check_axis_3d(axis, z, PROFILE, "RDW-3D"), ())


if __name__ == "__main__":
    unittest.main()
