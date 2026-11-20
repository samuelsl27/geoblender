# SPDX-License-Identifier: GPL-3.0-or-later
"""La rasante acotada de la pista (spec 017, T11; HU-017-1 y HU-017-4; RF-017-15, RF-017-16, RF-017-17 y RF-017-18; CE-017-03; RNF-017-03;
plan 017 §5.4 A5, §5.3.1, §5.8 H-4 y §7.3): ``road_gradient.gradient_line`` (la media de la mayor minorante y la menor mayorante pd-Lipschitz del
terreno a lo largo del eje, limitada a la banda de los extremos), ``mean_gradient`` (la pendiente media Σ|Δcota| / S, D-7), el aviso de la media
(RF-017-17) y ``check_axis_3d`` (el modo «eje 3D»: la Z de la línea **es** la rasante, se comprueba y no se corrige, RF-017-18).

Los valores esperados salen de la definición **a mano** (un oráculo de fuerza bruta O(n²) de la minorante y la mayorante, la banda de los extremos, las
cuentas del escalón de CE-017-03 en las mismas estaciones) y de ``tests.support.road_data`` (``step_profile_m``, ``SHORT_AXIS``, ``axis_3d_irregular``,
hechas a mano), **no** de llamar al código bajo prueba. Todo es sintético, en el dominio y sin Blender; el caso de referencia, con su cálculo
analítico, en ``tests/referencia/des/test_ref_road_gradient``.
"""

from __future__ import annotations

import hashlib
import math
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import best_of

road_gradient = import_geoblender("design.road_gradient")
road_axis = import_geoblender("design.road_axis")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")

TOL = 1e-9
"""La tolerancia de RF-017-15: la pendiente de cada tramo ≤ pd (a ≤ 10⁻⁹) y la rasante a ≤ 10⁻⁹ m del cálculo."""
PD = rd.PROFILE.max_gradient_pct / 100.0
"""La pendiente de diseño del perfil de referencia, en tanto por uno (0,10)."""
PROFILE = rd.road_profile()


def digest(array: np.ndarray) -> str:
    """El *hash* del contenido de ``array`` (para comprobar que nadie lo cambia)."""
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def slopes(s: np.ndarray, z: np.ndarray) -> np.ndarray:
    """La pendiente (tanto por uno, con signo) de cada tramo entre estaciones."""
    return np.diff(z) / np.diff(s)


class GradientLineTest(unittest.TestCase):
    def test_where_the_terrain_does_not_pass_pd_the_line_is_the_terrain(self) -> None:
        """RF-017-15: donde el perfil del terreno no pasa de pd, la rasante es el terreno (movimiento 0): un terreno ondulado del 5 % de
        pendiente máxima, con la cota de inicio y la de fin las del terreno, da el terreno a ≤ 10⁻⁹ m."""
        s = rd.stations_by_hand(300.0, 1.0)
        terrain = 100.0 + 3.0 * np.sin(s / 60.0)  # pendiente máxima 3/60 = 5 %
        self.assertLessEqual(float(np.abs(slopes(s, terrain)).max()), 0.05 + 1e-3)
        line = road_gradient.gradient_line(s, terrain, PD, float(terrain[0]), float(terrain[-1]))
        np.testing.assert_allclose(line, terrain, rtol=0.0, atol=TOL)

    def test_a_terrain_exactly_at_pd_is_still_the_terrain(self) -> None:
        """RF-017-15: un terreno de pendiente exactamente pd (una rampa del 10 %) no se mueve: «no pasa de pd» incluye pd."""
        s = rd.stations_by_hand(120.0, 0.5)
        terrain = 40.0 + PD * s
        line = road_gradient.gradient_line(s, terrain, PD, float(terrain[0]), float(terrain[-1]))
        np.testing.assert_allclose(line, terrain, rtol=0.0, atol=TOL)

    def test_the_slope_of_every_stretch_is_at_most_pd_and_the_ends_are_fixed(self) -> None:
        """RF-017-15: con terrenos al azar (saltos de hasta 0,6 m por metro, muy por encima de pd) la pendiente de cada tramo es ≤ pd (a ≤ 10⁻⁹), las
        cotas de inicio y de fin quedan **exactamente** en los extremos, y la rasante es finita."""
        rng = np.random.default_rng(20261120)
        for case in range(25):
            count = int(rng.integers(5, 80))
            step = float(rng.choice([0.25, 0.5, 1.0, 2.0]))
            s = rd.stations_by_hand((count - 1) * step, step)
            terrain = 100.0 + np.cumsum(rng.uniform(-0.6, 0.6, len(s)) * step)
            z_start = float(terrain[0] + rng.uniform(-3.0, 3.0))
            reach = PD * float(s[-1])
            z_end = float(np.clip(terrain[-1] + rng.uniform(-3.0, 3.0), z_start - 0.9 * reach, z_start + 0.9 * reach))
            line = road_gradient.gradient_line(s, terrain, PD, z_start, z_end)
            self.assertLessEqual(float(np.abs(slopes(s, line)).max()), PD + TOL, msg=f"caso {case}")
            self.assertEqual(float(line[0]), z_start)
            self.assertEqual(float(line[-1]), z_end)
            self.assertTrue(bool(np.isfinite(line).all()))

    def test_the_line_is_the_mean_of_the_largest_minorant_and_the_smallest_majorant(self) -> None:
        """RF-017-15, D-9: la rasante es la media de la mayor minorante y de la menor mayorante pd-Lipschitz del perfil, limitada a la banda de los
        extremos: igual, a ≤ 10⁻⁹ m, al oráculo de fuerza bruta O(n²) en terrenos al azar (estaciones uniformes y con la última más corta)."""
        rng = np.random.default_rng(1120)
        for case in range(30):
            count = int(rng.integers(4, 130))
            step = float(rng.choice([0.5, 1.0, 1.5]))
            s = rd.stations_by_hand((count - 1) * step + float(rng.choice([0.0, 0.3 * step])), step)
            terrain = 100.0 + np.cumsum(rng.uniform(-0.45, 0.45, len(s)) * step) + 4.0 * np.sin(s / 17.0)
            pd = float(rng.choice([0.05, 0.10, 0.15]))
            z_start = float(terrain[0] + rng.uniform(-2.0, 2.0))
            reach = pd * float(s[-1])
            z_end = float(np.clip(terrain[-1] + rng.uniform(-2.0, 2.0), z_start - 0.95 * reach, z_start + 0.95 * reach))
            line = road_gradient.gradient_line(s, terrain, pd, z_start, z_end)
            np.testing.assert_allclose(line, rd.oracle_gradient_line(s, terrain, pd, z_start, z_end), rtol=0.0, atol=TOL, err_msg=f"caso {case}")

    def test_reversing_the_axis_reverses_the_line(self) -> None:
        """RF-017-15: la rasante no depende del sentido del eje: recorrerlo al revés (estaciones ``S − s`` al revés, el terreno invertido y las
        cotas de los extremos cambiadas) da la misma rasante invertida."""
        rng = np.random.default_rng(777)
        for case in range(15):
            count = int(rng.integers(5, 90))
            s = rd.stations_by_hand((count - 1) * 1.0 + float(rng.choice([0.0, 0.4])), 1.0)
            terrain = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, len(s)))
            z_start = float(terrain[0] + 1.0)
            reach = 0.9 * PD * float(s[-1])
            z_end = float(np.clip(terrain[-1] - 1.0, z_start - reach, z_start + reach))
            forward = road_gradient.gradient_line(s, terrain, PD, z_start, z_end)
            backward = road_gradient.gradient_line(s[-1] - s[::-1], terrain[::-1], PD, z_end, z_start)
            np.testing.assert_allclose(backward[::-1], forward, rtol=0.0, atol=TOL, err_msg=f"caso {case}")

    def test_stations_that_do_not_start_at_zero_use_the_distance_between_them(self) -> None:
        """RF-017-15: la rasante no depende de dónde empieza la abscisa: solo cuentan las distancias entre estaciones."""
        s = rd.stations_by_hand(90.0, 1.0)
        terrain = 100.0 + 6.0 * (s > 40.0)
        shifted = road_gradient.gradient_line(s + 1234.5, terrain, PD, 100.0, 106.0)
        base = road_gradient.gradient_line(s, terrain, PD, 100.0, 106.0)
        np.testing.assert_allclose(shifted, base, rtol=0.0, atol=TOL)

    def test_the_band_of_the_ends_limits_the_line_at_the_start(self) -> None:
        """RF-017-15, D-9: con un terreno llano a 20 m, la cota de inicio a 0 m y la de fin a 20 m en un eje de 300 m, la rasante no puede subir más de
        pd desde el inicio: ``mín(20, pd·s)`` (a mano), no el terreno."""
        s = rd.stations_by_hand(300.0, 1.0)
        line = road_gradient.gradient_line(s, np.full(len(s), 20.0), PD, 0.0, 20.0)
        np.testing.assert_allclose(line, np.minimum(20.0, PD * s), rtol=0.0, atol=TOL)

    def test_the_band_of_the_ends_limits_the_line_at_the_end(self) -> None:
        """RF-017-15, D-9: lo mismo al revés: terreno a 20 m, inicio a 20 m y fin a 0 m: la rasante baja pd por metro hasta el fin, ``mín(20,
        pd·(S − s))``."""
        s = rd.stations_by_hand(300.0, 1.0)
        line = road_gradient.gradient_line(s, np.full(len(s), 20.0), PD, 20.0, 0.0)
        np.testing.assert_allclose(line, np.minimum(20.0, PD * (300.0 - s)), rtol=0.0, atol=TOL)

    def test_a_start_level_off_the_terrain_is_joined_to_it_with_slope_pd(self) -> None:
        """RF-017-15: un terreno llano a 100 m con la cota de inicio a 100,5 m: la rasante baja con pendiente pd hasta el terreno (5 m) y sigue en él;
        a mano ``máx(100, 100,5 − pd·s)``."""
        s = rd.stations_by_hand(100.0, 0.5)
        line = road_gradient.gradient_line(s, np.full(len(s), 100.0), PD, 100.5, 100.0)
        np.testing.assert_allclose(line, np.maximum(100.0, 100.5 - PD * s), rtol=0.0, atol=TOL)

    def test_a_drop_that_exactly_fits_is_a_straight_ramp_and_is_accepted(self) -> None:
        """RF-017-16: un desnivel igual a pd por la longitud del eje cabe: la rasante es la recta de pendiente pd entre los extremos (con el terreno
        como sea), en los dos sentidos."""
        s = rd.stations_by_hand(100.0, 1.0)
        terrain = 3.0 * np.sin(s / 7.0)
        up = road_gradient.gradient_line(s, terrain, PD, 10.0, 20.0)
        np.testing.assert_allclose(up, 10.0 + PD * s, rtol=0.0, atol=TOL)
        down = road_gradient.gradient_line(s, terrain, PD, 20.0, 10.0)
        np.testing.assert_allclose(down, 20.0 - PD * s, rtol=0.0, atol=TOL)

    def test_a_drop_that_does_not_fit_is_rejected_naming_the_axis_the_needed_length_and_the_drop(self) -> None:
        """RF-017-16, CE-017-03: con los extremos a 0 y a 20 m en un eje de 100 m con pd = 10 % el rechazo dice «necesaria 200 m, el eje mide
        100 m» y el desnivel, en español y en inglés; no cambia las cotas ni la pendiente por su cuenta (ninguna rasante), no cambia sus entradas y
        el campo del rechazo es la pendiente máxima del perfil."""
        s = rd.stations_by_hand(rd.SHORT_NEEDED_M / 2.0, 1.0)
        terrain = np.zeros(len(s))
        before = (digest(s), digest(terrain))
        with self.assertRaises(road_gradient.DropTooSteep) as caught:
            road_gradient.gradient_line(s, terrain, PD, rd.SHORT_Z_START_M, rd.SHORT_Z_END_M)
        self.assertEqual((digest(s), digest(terrain)), before)
        rejection = caught.exception
        self.assertAlmostEqual(rejection.length_m, 100.0, delta=TOL)
        self.assertAlmostEqual(rejection.needed_m, rd.SHORT_NEEDED_M, delta=TOL)
        self.assertAlmostEqual(rejection.drop_m, 20.0, delta=TOL)
        error = rejection.error(layer="trazados", entity="Pista corta", profile=PROFILE)
        self.assertIsInstance(error, messages.DesignError)
        self.assertEqual(error.code, "des.road_drop_too_steep")
        self.assertEqual(error.field, "des.roadprofile.pista_principal.max_gradient_pct")
        self.assertEqual(error.value, 10.0)
        text = error.text_in("es")
        for expected in ("trazados", "Pista corta", "mide 100 m", "harían falta 200 m", "(20 m)", "10 %", "no se cambian las cotas ni la pendiente",
                         "no se crea nada"):
            self.assertIn(expected, text)
        self.assertIn("the axis is 100 m long and 200 m are needed", error.text_in("en"))
        self.assertNotIn("?", text)

    def test_the_rejection_is_the_same_going_down_and_tolerates_the_noise_of_the_last_digit(self) -> None:
        """RF-017-16: el desnivel se mide en valor absoluto (bajar 20 m en 100 m también se rechaza); un desnivel 10⁻¹¹ m por encima de pd·S es el
        ruido de la última cifra y se acepta, y uno 10⁻⁶ m por encima se rechaza."""
        s = rd.stations_by_hand(100.0, 1.0)
        flat = np.zeros(len(s))
        with self.assertRaises(road_gradient.DropTooSteep) as caught:
            road_gradient.gradient_line(s, flat, PD, 20.0, 0.0)
        self.assertAlmostEqual(caught.exception.drop_m, 20.0, delta=TOL)
        road_gradient.gradient_line(s, flat, PD, 0.0, 10.0 + 1e-11)
        with self.assertRaises(road_gradient.DropTooSteep):
            road_gradient.gradient_line(s, flat, PD, 0.0, 10.0 + 1e-6)

    def test_the_inputs_are_not_modified_and_the_line_is_a_read_only_float64_copy(self) -> None:
        """RF-017-15 y principio 7: las estaciones y el terreno no cambian (su *hash*, también si son de solo lectura); la rasante es un array float64
        nuevo y de solo lectura."""
        s, terrain = rd.stations_by_hand(80.0, 1.0), 100.0 + 5.0 * (rd.stations_by_hand(80.0, 1.0) > 30.0)
        s.flags.writeable = terrain.flags.writeable = False
        before = (digest(s), digest(terrain))
        line = road_gradient.gradient_line(s, terrain, PD, 100.0, 105.0)
        self.assertEqual((digest(s), digest(terrain)), before)
        self.assertEqual(line.dtype, np.float64)
        self.assertFalse(line.flags.writeable)
        self.assertFalse(np.shares_memory(line, terrain))
        self.assertEqual(line.shape, s.shape)

    def test_inputs_that_are_not_of_their_shape_are_programme_errors(self) -> None:
        """RF-017-15: unas estaciones que no crecen, un terreno de otra longitud o con celdas sin dato, una pendiente que no es positiva y finita, unas
        cotas que no son finitas o un solo punto son errores del programa (``ValueError``; ``TypeError`` si no es un número): la preparación de la
        pista rechazó antes, con su capa y su pista (RF-017-04)."""
        s, terrain = rd.stations_by_hand(10.0, 1.0), np.zeros(11)
        line = road_gradient.gradient_line
        for case, call in {
            "estaciones que no crecen": lambda: line(s[::-1], terrain, PD, 0.0, 0.0),
            "estación repetida": lambda: line(np.array([0.0, 1.0, 1.0, 2.0]), np.zeros(4), PD, 0.0, 0.0),
            "terreno más corto": lambda: line(s, terrain[:-1], PD, 0.0, 0.0),
            "terreno sin dato": lambda: line(s, np.where(s == 4.0, np.nan, 0.0), PD, 0.0, 0.0),
            "terreno infinito": lambda: line(s, np.where(s == 4.0, np.inf, 0.0), PD, 0.0, 0.0),
            "pendiente cero": lambda: line(s, terrain, 0.0, 0.0, 0.0),
            "pendiente negativa": lambda: line(s, terrain, -0.1, 0.0, 0.0),
            "pendiente infinita": lambda: line(s, terrain, math.inf, 0.0, 0.0),
            "cota de inicio sin dato": lambda: line(s, terrain, PD, math.nan, 0.0),
            "cota de fin infinita": lambda: line(s, terrain, PD, 0.0, math.inf),
            "una sola estación": lambda: line(np.array([0.0]), np.array([0.0]), PD, 0.0, 0.0),
            "estaciones en dos dimensiones": lambda: line(np.zeros((2, 2)), np.zeros((2, 2)), PD, 0.0, 0.0),
        }.items():
            with self.subTest(case=case), self.assertRaises(ValueError):
                call()
        for case, call in {
            "pendiente textual": lambda: line(s, terrain, "0,1", 0.0, 0.0),
            "pendiente lógica": lambda: line(s, terrain, True, 0.0, 0.0),
            "cota textual": lambda: line(s, terrain, PD, "0", 0.0),
        }.items():
            with self.subTest(case=case), self.assertRaises(TypeError):
                call()

    def test_two_stations_are_a_straight_ramp(self) -> None:
        """RF-017-15: el caso mínimo, dos estaciones (un eje de una sola longitud): la rasante son las dos cotas, con tal de que quepan."""
        line = road_gradient.gradient_line(np.array([0.0, 5.0]), np.array([1.0, 7.0]), PD, 2.0, 2.4)
        np.testing.assert_array_equal(line, [2.0, 2.4])

    def test_the_levels_are_exact_in_absolute_heights_and_the_work_is_float64(self) -> None:
        """Regla 4 de AGENTS.md (cotas de float64): con cotas del orden de 4.000 m la rasante sigue a ≤ 10⁻⁹ m del cálculo y la pendiente, ≤ pd."""
        s = rd.stations_by_hand(500.0, 1.0)
        terrain = 4_000.0 + 6.0 * (s > 250.0)
        line = road_gradient.gradient_line(s, terrain, PD, 4_000.0, 4_006.0)
        np.testing.assert_allclose(line, rd.oracle_gradient_line(s, terrain, PD, 4_000.0, 4_006.0), rtol=0.0, atol=TOL)
        self.assertLessEqual(float(np.abs(slopes(s, line)).max()), PD + TOL)

    def test_five_kilometres_with_w_1_m_in_a_fraction_of_the_budget(self) -> None:
        """RNF-017-03 (el plan midió 1,6 ms con el eje): la rasante de 5 km con estaciones cada metro (5.001) se calcula en menos de 0,2 s (con un
        bucle de Python por estación o la fuerza bruta serían segundos), y sigue siendo la del oráculo en un tramo de 300 estaciones."""
        s = rd.stations_by_hand(5_000.0, 1.0)
        rng = np.random.default_rng(5)
        terrain = 300.0 + np.cumsum(rng.uniform(-0.3, 0.3, len(s))) + 20.0 * np.sin(s / 300.0)
        line = road_gradient.gradient_line(s, terrain, PD, float(terrain[0]), float(terrain[-1]))
        self.assertLessEqual(float(np.abs(slopes(s, line)).max()), PD + TOL)
        seconds = best_of(lambda: road_gradient.gradient_line(s, terrain, PD, float(terrain[0]), float(terrain[-1])), 0.2)
        self.assertLessEqual(seconds, 0.2)
        part = slice(1000, 1300)
        local = road_gradient.gradient_line(s[part], terrain[part], PD, float(terrain[part][0]), float(terrain[part][-1]))
        np.testing.assert_allclose(local, rd.oracle_gradient_line(s[part], terrain[part], PD, float(terrain[part][0]), float(terrain[part][-1])), atol=TOL)


class MeanGradientTest(unittest.TestCase):
    def test_the_mean_is_the_sum_of_the_level_changes_over_the_length(self) -> None:
        """RF-017-17, D-7: la pendiente media es Σ|Δcota| / S (en tanto por uno): una subida de 6 m y una bajada de 2 m en 200 m son 8 / 200 = 0,04, no
        el desnivel entre los extremos (4 m)."""
        s = np.array([0.0, 50.0, 100.0, 150.0, 200.0])
        z = np.array([10.0, 13.0, 16.0, 14.0, 14.0])
        self.assertAlmostEqual(road_gradient.mean_gradient(s, z), (3.0 + 3.0 + 2.0 + 0.0) / 200.0, delta=1e-15)
        self.assertAlmostEqual(road_gradient.mean_gradient(s, z), 0.04, delta=1e-15)
        self.assertAlmostEqual(road_gradient.mean_gradient(s, z[::-1]), 0.04, delta=1e-15)  # recorrida al revés: la misma suma

    def test_a_ramp_of_slope_p_has_mean_p_and_a_flat_line_has_zero(self) -> None:
        """RF-017-17: una rampa uniforme tiene su pendiente como media; una rasante horizontal, 0; la media no depende de la abscisa de origen."""
        s = rd.stations_by_hand(200.0, 0.5)
        self.assertAlmostEqual(road_gradient.mean_gradient(s, 50.0 + 0.07 * s), 0.07, delta=1e-12)
        self.assertEqual(road_gradient.mean_gradient(s, np.full(len(s), 50.0)), 0.0)
        self.assertAlmostEqual(road_gradient.mean_gradient(s + 777.0, 50.0 + 0.07 * s), 0.07, delta=1e-12)

    def test_inputs_of_the_wrong_shape_are_programme_errors(self) -> None:
        """RF-017-17: unas estaciones y unas cotas de distinta longitud, o estaciones que no crecen, son errores del programa."""
        with self.assertRaises(ValueError):
            road_gradient.mean_gradient(np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0]))
        with self.assertRaises(ValueError):
            road_gradient.mean_gradient(np.array([0.0, 2.0, 1.0]), np.array([0.0, 1.0, 2.0]))
        with self.assertRaises(ValueError):
            road_gradient.mean_gradient(np.array([0.0]), np.array([1.0]))


def straight_axis(length_m: float, step_m: float = 1.0) -> Any:
    """Un eje recto de ``length_m`` m hacia el este desde (100, 200) local (las absolutas de la cantera), con estaciones cada ``step_m`` m."""
    return road_axis.axis_of(rd.absolute([(100.0, 200.0), (100.0 + length_m, 200.0)]), 20.0, 12.0, step_m)


class MeanNoticeTest(unittest.TestCase):
    def ramp(self, mean_pct: float, *, length_m: float = 200.0, step_m: float = 1.0) -> tuple[Any, np.ndarray]:
        """Un eje recto con una rasante uniforme de ``mean_pct`` %."""
        axis = straight_axis(length_m, step_m)
        return axis, 100.0 + mean_pct / 100.0 * axis.stations

    def test_a_mean_above_the_profile_limit_gives_the_notice_with_the_mean_the_limit_and_the_steepest_stretches(self) -> None:
        """RF-017-17: con pm = 10 % y una rasante de media 10,5 % (la «opción A15» de la propiedad) el aviso da la media, el límite y los tramos de
        mayor pendiente con su abscisa y su lugar, y dice que no se crea sin la confirmación expresa y un motivo."""
        axis, z = self.ramp(10.5)
        notice = road_gradient.mean_gradient_notice(axis, z, PROFILE, "Pista A15")
        self.assertIsInstance(notice, preview.Notice)
        self.assertEqual(notice.code, "des.road_mean_gradient")
        self.assertEqual(notice.severity, "warning")
        self.assertEqual(notice.values["entity"], "Pista A15")
        self.assertAlmostEqual(notice.values["mean"], 10.5, delta=1e-9)
        self.assertEqual(notice.values["limit"], 10.0)
        stretches = notice.values["stretches"]
        self.assertGreaterEqual(len(stretches), 1)
        text, english = notice.text("es"), notice.text("en")
        for expected in ("«Pista A15»", "10,50 %", "10,00 %", "abscisa 0,0 m", "confirmación expresa", "motivo"):
            self.assertIn(expected, text)
        for expected in ("10.50 %", "10.00 %", "s = 0.0 m", "express confirmation"):
            self.assertIn(expected, english)
        self.assertNotIn("?", text)
        self.assertNotIn("{", english)

    def test_a_mean_at_the_limit_or_below_gives_no_notice(self) -> None:
        """RF-017-17: una media igual a pm (a 10⁻⁹) o menor no avisa; una décima de punto por encima, sí."""
        for mean_pct, expected in ((10.0, False), (9.99, False), (7.2, False), (10.0 + 1e-8, False), (10.01, True), (15.0, True)):
            axis, z = self.ramp(mean_pct)
            with self.subTest(mean=mean_pct):
                notice = road_gradient.mean_gradient_notice(axis, z, PROFILE, "RDW-001")
                self.assertEqual(notice is not None, expected)

    def test_the_decimals_tell_a_mean_just_above_the_limit_from_the_limit(self) -> None:
        """RF-017-17: una media del 10,04 % frente a un límite del 10 % no se lee «10,0 % … 10,0 %»: el aviso la escribe con dos decimales
        (``preview._CODE_DECIMALS``, como los de la 016)."""
        axis, z = self.ramp(10.04)
        text = road_gradient.mean_gradient_notice(axis, z, PROFILE, "RDW-001").text("es")
        self.assertIn("10,04 %", text)
        self.assertIn("10,00 %", text)

    def test_the_listed_stretches_are_the_steepest_in_order_and_ties_go_by_abscissa(self) -> None:
        """RF-017-17: los tramos que enseña el aviso son los de mayor pendiente, de mayor a menor y, a igual pendiente, por abscisa; son cinco (los
        de la persona que lee, no una cifra minera): una rasante con tramos del 12, 15, 9, 15 y 11 % los da 15 % (abscisa 20 m), 15 % (60 m), 12, 11 y 9 %."""
        s = np.arange(0.0, 101.0, 20.0)  # estaciones 0, 20, …, 100: cinco tramos de 20 m
        rises = np.array([0.12, 0.15, 0.09, 0.15, 0.11]) * 20.0
        z = 100.0 + np.concatenate([[0.0], np.cumsum(rises)])
        axis = road_axis.axis_of(rd.absolute([(100.0, 200.0), (200.0, 200.0)]), 20.0, 12.0, 20.0)
        found = road_gradient.steepest_stretches(axis, z)
        self.assertEqual([stretch.station_m for stretch in found], [20.0, 60.0, 0.0, 80.0, 40.0])
        for stretch, expected in zip(found, (15.0, 15.0, 12.0, 11.0, 9.0)):
            self.assertAlmostEqual(stretch.gradient_pct, expected, delta=1e-9)
            self.assertAlmostEqual(stretch.length_m, 20.0, delta=TOL)
        first = found[0]
        np.testing.assert_array_equal([first.x, first.y], axis.points[1])  # el lugar es el del comienzo del tramo (en absolutas)

    def test_at_most_listed_stretches_are_given_and_none_when_the_line_is_flat(self) -> None:
        """RF-017-17: con ``listed`` se limita cuántos (por defecto, cinco); una rasante horizontal no tiene tramos empinados que decir."""
        axis, z = self.ramp(12.0, length_m=100.0)
        self.assertEqual(len(road_gradient.steepest_stretches(axis, z)), 5)
        self.assertEqual(len(road_gradient.steepest_stretches(axis, z, listed=2)), 2)
        self.assertEqual(len(road_gradient.steepest_stretches(axis, z, listed=500)), 100)
        self.assertEqual(road_gradient.steepest_stretches(axis, np.full(len(axis.stations), 100.0)), ())

    def test_a_line_of_another_length_than_the_axis_is_a_programme_error(self) -> None:
        """RF-017-17: la rasante tiene una cota por estación del eje."""
        axis, z = self.ramp(10.5)
        with self.assertRaises(ValueError):
            road_gradient.mean_gradient_notice(axis, z[:-1], PROFILE, "RDW-001")
        with self.assertRaises(ValueError):
            road_gradient.steepest_stretches(axis, z[:-1])


class Axis3dTest(unittest.TestCase):
    def line_and_axis(self, **changes: Any) -> tuple[np.ndarray, Any, np.ndarray]:
        """La línea con Z irregular de CE-017-03 (11 vértices cada 20 m, ``road_data.axis_3d_irregular``), su eje con estaciones cada 20 m (los
        vértices; sin curvas) y su Z en esas estaciones."""
        line = rd.axis_3d_irregular()
        step = changes.pop("step", 20.0)
        axis = road_axis.axis_of(line, 20.0, 12.0, step, reject_below_minimum=False)
        z = np.interp(axis.stations, 20.0 * np.arange(len(line)), line[:, 2])
        return line, axis, z

    def test_each_stretch_over_pd_is_a_notice_with_its_abscissa_and_place_and_the_line_does_not_change(self) -> None:
        """RF-017-18, CE-017-03: la línea con Z irregular (tramos del 5, 5, 10, 15, −2, 8, 12, 0, 5 y 10 %) con pd = 10 % da un aviso por tramo
        que pasa de pd —el 4.º (15 %, abscisa 60 m) y el 7.º (12 %, abscisa 120 m); los de 10 % exactos, no— con su lugar, y **la línea no
        cambia** (su *hash*, con su Z)."""
        line, axis, z = self.line_and_axis()
        before = digest(line)
        notices = road_gradient.check_axis_3d(axis, z, PROFILE, "RDW-3D")
        self.assertEqual(digest(line), before)
        gradient = [notice for notice in notices if notice.code == "des.road_axis3d_gradient"]
        self.assertEqual([notice.values["station"] for notice in gradient], [60.0, 120.0])
        for notice, expected in zip(gradient, (15.0, 12.0)):
            self.assertEqual(notice.severity, "warning")
            self.assertEqual(notice.values["entity"], "RDW-3D")
            self.assertAlmostEqual(notice.values["gradient"], expected, delta=1e-9)
            self.assertEqual(notice.values["limit"], 10.0)
        np.testing.assert_allclose([gradient[0].values["x"], gradient[0].values["y"]], line[3, :2], rtol=0.0, atol=1e-6)
        np.testing.assert_allclose([gradient[1].values["x"], gradient[1].values["y"]], line[6, :2], rtol=0.0, atol=1e-6)
        self.assertEqual(len(notices), 2)  # la media (7,2 %) no pasa de pm = 10 % y la planta es recta: nada más
        text = gradient[0].text("es")
        for expected in ("«RDW-3D»", "abscisa 60,0 m", "15,00 %", "10,00 %", "modo «eje 3D»", "la línea no se corrige"):
            self.assertIn(expected, text)
        self.assertIn("3D axis", gradient[0].text("en"))

    def test_a_stretch_is_the_interval_between_stations_every_w(self) -> None:
        """RF-017-18: la comprobación es **entre estaciones cada w m** (RF-017-18), no por vértice de la línea: con w = 1 m cada metro del tramo
        del 15 % (20 m) y del 12 % (20 m) es un aviso, cada uno con su abscisa."""
        line, axis, z = self.line_and_axis(step=1.0)
        notices = road_gradient.check_axis_3d(axis, z, PROFILE, "RDW-3D")
        self.assertEqual([notice.values["station"] for notice in notices], [float(s) for s in (*range(60, 80), *range(120, 140))])
        self.assertTrue(all(notice.code == "des.road_axis3d_gradient" for notice in notices))

    def test_the_mean_above_pm_is_a_notice_with_the_steepest_stretches(self) -> None:
        """RF-017-18: con pm = 5 % la media de la línea (7,2 %) también avisa —el aviso de RF-017-17 (``des.road_mean_gradient``), con su media, su
        límite y sus tramos más empinados (15, 12, 10, 10 y 8 %)—, después de los avisos por tramo."""
        _line, axis, z = self.line_and_axis()
        profile = rd.road_profile(rd.profile_with(max_mean_gradient_pct=5.0))
        notices = road_gradient.check_axis_3d(axis, z, profile, "RDW-3D")
        self.assertEqual([notice.code for notice in notices], ["des.road_axis3d_gradient", "des.road_axis3d_gradient", "des.road_mean_gradient"])
        mean = notices[-1]
        self.assertAlmostEqual(mean.values["mean"], rd.AXIS_3D_MEAN_PCT, delta=1e-9)
        self.assertEqual(mean.values["limit"], 5.0)
        self.assertEqual([item.values["station"] for item in mean.values["stretches"]], [60.0, 120.0, 40.0, 180.0, 100.0])
        self.assertEqual([round(item.values["gradient"], 9) for item in mean.values["stretches"]], [15.0, 12.0, 10.0, 10.0, 8.0])

    def test_a_smooth_line_inside_the_limits_gives_no_notice(self) -> None:
        """RF-017-18: la línea con Z que sigue el plano del 4 % (≤ pd, media ≤ pm, planta recta) no da ningún aviso."""
        line = rd.axis_3d_smooth()
        axis = road_axis.axis_of(line, 20.0, 12.0, 5.0, reject_below_minimum=False)
        z = np.interp(axis.stations, 20.0 * np.arange(len(line)), line[:, 2])
        self.assertEqual(road_gradient.check_axis_3d(axis, z, PROFILE, "RDW-3D"), ())

    def test_a_radius_below_the_minimum_is_a_notice_and_not_a_rejection(self) -> None:
        """RF-017-18, decisión de la sesión principal tras la T10: una curva cuyo radio solo podría ser de 15 m con Rmín = 16 m es un aviso con su
        abscisa y su lugar (el vértice) y **la línea no cambia**; ``axis_of`` con la comprobación de «trazar» y «sobre un eje» la rechazaría."""
        line = np.column_stack([rd.absolute(rd.CORNER_SHORT), [100.0, 100.0, 100.0]])
        before = digest(line)
        with self.assertRaises(road_axis.RadiusBelowMinimum):
            road_axis.axis_of(line, 20.0, 16.0, 1.0)
        axis = road_axis.axis_of(line, 20.0, 16.0, 1.0, reject_below_minimum=False)
        profile = rd.road_profile(rd.profile_with(min_radius_m=16.0))
        notices = road_gradient.check_axis_3d(axis, np.full(len(axis.stations), 100.0), profile, "RDW-3D")
        self.assertEqual(digest(line), before)
        (notice,) = notices
        self.assertEqual(notice.code, "des.road_axis3d_radius")
        self.assertEqual(notice.severity, "warning")
        self.assertEqual(notice.values["entity"], "RDW-3D")
        self.assertAlmostEqual(notice.values["radius"], 15.0, delta=TOL)
        self.assertEqual(notice.values["minimum"], 16.0)
        self.assertAlmostEqual(notice.values["station"], 0.0, delta=TOL)  # la curva empieza en el origen: el primer tramo es de 15 m
        np.testing.assert_allclose([notice.values["x"], notice.values["y"]], line[1, :2], rtol=0.0, atol=1e-6)
        text = notice.text("es")
        for expected in ("«RDW-3D»", "abscisa 0,0 m", "15,00 m", "16,00 m", "la línea no se corrige"):
            self.assertIn(expected, text)

    def test_only_the_curves_below_rmin_are_noticed_in_the_order_of_the_axis(self) -> None:
        """RF-017-18: de las curvas de la planta (radios de 10, 10, 5 y 5 m en los vértices 2, 3, 5 y 6) con Rmín = 7 m solo avisan las dos de 5 m, en el
        orden del eje y cada una con su abscisa y su lugar (el vértice); las de 10 m, que cumplen, no."""
        points = rd.absolute([(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (80.0, 20.0), (150.0, 20.0), (150.0, 30.0), (190.0, 30.0)])
        axis = road_axis.axis_of(points, 20.0, 7.0, 1.0, reject_below_minimum=False)
        profile = rd.road_profile(rd.profile_with(min_radius_m=7.0))
        notices = road_gradient.check_axis_3d(axis, np.full(len(axis.stations), 100.0), profile, "RDW-3D")
        self.assertEqual([notice.code for notice in notices], ["des.road_axis3d_radius"] * 2)
        narrow = [curve for curve in axis.curves if curve.vertex in (5, 6)]
        self.assertEqual([round(notice.values["radius"], 9) for notice in notices], [5.0, 5.0])
        self.assertEqual([notice.values["minimum"] for notice in notices], [7.0, 7.0])
        self.assertEqual([notice.values["station"] for notice in notices], [curve.station_m for curve in narrow])
        self.assertLess(narrow[0].station_m, narrow[1].station_m)
        np.testing.assert_allclose([[notice.values["x"], notice.values["y"]] for notice in notices], points[[4, 5]], rtol=0.0, atol=1e-6)

    def test_the_three_kinds_together_in_a_steep_line_with_a_tight_corner(self) -> None:
        """RF-017-18, CE-017-03: una línea con una esquina de tramos de 15 m (R = 15 m < Rmín = 16 m) que sube 5 m en sus 23,6 m (el 21 %) da el
        aviso por tramo, el de la media y el del radio, en ese orden (los tramos por abscisa, la media y los radios), con la línea sin cambiar."""
        line = np.column_stack([rd.absolute(rd.CORNER_SHORT), [100.0, 102.0, 105.0]])
        before = digest(line)
        axis = road_axis.axis_of(line, 20.0, 16.0, 4.0, reject_below_minimum=False)
        z = 100.0 + 5.0 * axis.stations / axis.length_m
        profile = rd.road_profile(rd.profile_with(min_radius_m=16.0))
        notices = road_gradient.check_axis_3d(axis, z, profile, "RDW-3D")
        self.assertEqual(digest(line), before)
        codes = [notice.code for notice in notices]
        self.assertEqual(codes[-1], "des.road_axis3d_radius")
        self.assertEqual(codes[-2], "des.road_mean_gradient")
        self.assertTrue(all(code == "des.road_axis3d_gradient" for code in codes[:-2]))
        self.assertGreaterEqual(len(codes), 4)
        stations = [notice.values["station"] for notice in notices[:-2]]
        self.assertEqual(stations, sorted(stations))
        for notice in notices:
            for language in ("es", "en"):
                self.assertNotIn("?", notice.text(language))
                self.assertNotIn("{", notice.text(language))

    def test_the_axis_must_have_a_level_per_station(self) -> None:
        """RF-017-18: la Z que se comprueba es una por estación del eje."""
        _line, axis, z = self.line_and_axis()
        with self.assertRaises(ValueError):
            road_gradient.check_axis_3d(axis, z[:-1], PROFILE, "RDW-3D")

    def test_the_check_of_five_kilometres_is_fast(self) -> None:
        """RNF-017-03: comprobar la Z de un eje de 5 km con estaciones cada metro (hasta miles de avisos) tarda menos de 0,2 s."""
        heading, points = 0.0, [(0.0, 0.0)]
        for k in range(1, 163):
            points.append((points[-1][0] + 31.0 * math.sin(heading), points[-1][1] + 31.0 * math.cos(heading)))
            heading += math.radians(40.0 if k % 2 else -40.0)
        axis = road_axis.axis_of(np.asarray(points), 20.0, 12.0, 1.0, reject_below_minimum=False)
        z = 100.0 + 0.12 * axis.stations
        notices = road_gradient.check_axis_3d(axis, z, PROFILE, "RDW-3D")
        self.assertGreater(len(notices), 4_000)  # todos los metros pasan del 10 %, más la media
        seconds = best_of(lambda: road_gradient.check_axis_3d(axis, z, PROFILE, "RDW-3D"), 0.2)
        self.assertLessEqual(seconds, 0.2)


class MessagesTest(unittest.TestCase):
    def test_a_stretch_of_the_list_is_written_with_its_abscissa_its_place_and_its_gradient(self) -> None:
        """RF-017-17: cada tramo de la lista del aviso de la media es una nota del catálogo (``des.road_stretch``: abscisa, lugar y pendiente), en
        el idioma pedido, sin cifras escritas en el texto y con la pendiente a la centésima."""
        message = messages.MESSAGES["des.road_stretch"]
        self.assertEqual(message.severity, "note")
        item = preview.Named("des.road_stretch", {"station": 99.5, "x": 725100.0, "y": 4400200.0, "gradient": 10.0})
        thin = preview.THIN_SPACE
        self.assertEqual(item.text("es"), f"«abscisa 99,5 m (x = 725{thin}100,0 m, y = 4{thin}400{thin}200,0 m): 10,00 %»")
        self.assertEqual(item.text("en"), "«s = 99.5 m (x = 725,100.0 m, y = 4,400,200.0 m): 10.00 %»")


class ModuleTest(unittest.TestCase):
    def test_the_module_is_lazy_and_pure(self) -> None:
        """RNF-001-03: ni ``design.model`` ni el arranque cargan el módulo (lo fija ``test_lazy_registration``), no importa ``bpy`` ni librerías
        externas salvo numpy, y no dice «grade» (en minería es la ley: glosario §14; la pendiente de la rasante es ``gradient``)."""
        import ast
        import inspect
        import re

        source = inspect.getsource(road_gradient)
        tree = ast.parse(source)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertEqual(imported - {"__future__", "math", "numbers", "dataclasses", "collections", "typing", "numpy"}, set())
        self.assertIsNone(re.search(r"(?<!up)(?<!down)grade", source, re.IGNORECASE))

    def test_the_public_names_of_the_task(self) -> None:
        """RF-017-15 a RF-017-18: los nombres de la tarea (con ``gradient``, decisión de la sesión principal tras la T02)."""
        for name in ("gradient_line", "mean_gradient", "mean_gradient_notice", "steepest_stretches", "check_axis_3d", "DropTooSteep", "Stretch"):
            self.assertIn(name, road_gradient.__all__)
            self.assertTrue(hasattr(road_gradient, name))


if __name__ == "__main__":
    unittest.main()
