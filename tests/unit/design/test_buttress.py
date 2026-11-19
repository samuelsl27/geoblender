# SPDX-License-Identifier: GPL-3.0-or-later
"""El contrafuerte: la semilla en la coronación, el escalonado en relleno y la composición sin corte (spec 016, T26; HU-016-3;
RF-016-01, RF-016-17, RF-016-18; RNF-016-02, RNF-016-03; plan 016 §5.4 A0 y A10, §5.7 P-8, §5.8 H-6 y H-10; D-7, D-21, D-24).

:func:`design.buttress.buttress_steps` (y :func:`compute_buttress`, de una vez) recorre un :class:`ButtressJob` (todo lo leído
—rejilla, perfil de banco, partida, zona de coronación, relleno admitido, valores resueltos—; nada del proyecto) y da el
:class:`ButtressOutcome`: la semilla es la cota de coronación en las celdas de la zona con la partida por debajo, la envolvente
descendente (la euclídea exacta o el *chamfer* 5×5, hasta el alcance si se fija) con el talud general del perfil por su factor
de malla, el escalonado en relleno de RF-013-23 anclado a ``z₀ + n·h``, el recorte final de RF-013-27 y la composición
``máx(partida, recorte)`` donde las máscaras de la 012 admiten el relleno, **sin cortar ninguna celda** y sin recortar el pie a
la zona dibujada. Se prueba con:

- **la fórmula cerrada** de RF-013-23 (:func:`tests.support.buttress_data.strip_closed_form`): una franja de lado a lado es un
  problema de una dimensión que se resuelve a mano (el escalonado en racionales y el recorte final en una dimensión), con las
  dos métricas, y da la superficie, el volumen, el área y la altura máxima;
- **una implementación independiente** (:func:`tests.support.design_oracles.hand_buttress`: la envolvente por fuerza bruta o el
  *Dijkstra* del *chamfer*, el escalonado en racionales, el recorte y las cifras en bucles de Python con ``fsum``) en un llano
  con una zona cuadrada (el tronco de pirámide) y en un relieve con celdas sin dato, una celda por encima de la coronación y
  relleno no admitido, con las dos métricas, el factor de malla 0,93 y el alcance;
- **las propiedades**: ninguna celda baja, lo que no sube es la partida bit a bit (también lo no admitido y lo sin dato), las
  bermas están en ``z₀ + n·h``, el pie sale de la zona dibujada y el espesor (salida − partida) es ≥ 0 y cuadra con ``derive``;
- **los rechazos de RF-016-18**: una coronación que no es del ancla (con la cota del ancla más próxima), por debajo de la
  partida en toda la zona (sin semilla) y los valores sin valor por defecto (la coronación: D-21);
- **la zona de solo restauración** (D-24, H-10; RF-012-13): con las máscaras de verdad, el pie entra en ella, donde el corte no
  está admitido pero el relleno sí, y se detiene donde el relleno está prohibido;
- **la ventana de trabajo** (A0): leer solo la de :func:`buttress_window` da el mismo resultado, bit a bit, que la rejilla entera;
- **los pasos** (RNF-016-03): por pasos de ``budget_s`` como mucho, cancelables y sin modificar ninguna entrada.
"""

from __future__ import annotations

import copy
import dataclasses
import math
import time
import unittest
from contextlib import closing
from typing import Any
from unittest import mock

import numpy as np

from tests.support import buttress_data as bdata
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.unit.gis.masks.test_combine import GRID as MASK_GRID
from tests.unit.gis.masks.test_combine import make as make_constraint
from tests.unit.gis.masks.test_combine import resolved_for

access = import_geoblender("gis.masks.access")
buttress = import_geoblender("design.buttress")
combine = import_geoblender("gis.masks.combine")
compose = import_geoblender("design.compose")
constraints = import_geoblender("core.constraints.model")
design_model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
thickness = import_geoblender("design.thickness")

DesignError = messages.DesignError
FILL = design_model.BenchSense.FILL
T = constraints.ConstraintType
CROWN = "des.buttress.btr_001.crown_m"
"""La clave de la cota de coronación del contrafuerte de las pruebas."""
STEP = 2.0
RELATIVE = 1e-9


class Close(unittest.TestCase):
    def close(self, found: float, wanted: float, *, rel: float = RELATIVE, what: str = "") -> None:
        """``found`` es ``wanted`` a ≤ ``rel`` relativo (con un suelo de 1 para los ceros)."""
        self.assertLessEqual(abs(found - wanted), rel * max(abs(wanted), 1.0), f"{what}: {found} frente a {wanted}")

    def same(self, found: np.ndarray, wanted: np.ndarray, *, what: str = "") -> None:
        """Las dos rejillas, bit a bit (los NaN, en los mismos sitios)."""
        self.assertEqual(found.shape, wanted.shape, what)
        self.assertTrue(np.array_equal(found, wanted, equal_nan=True), f"{what}: no son idénticas")

    def near(self, found: np.ndarray, wanted: np.ndarray, *, what: str = "", tol: float = 1e-9) -> None:
        """Las dos rejillas a ≤ ``tol`` m, con los NaN en los mismos sitios."""
        self.assertEqual(found.shape, wanted.shape, what)
        self.assertTrue(np.array_equal(np.isnan(found), np.isnan(wanted)), f"{what}: los NaN no coinciden")
        mask = ~np.isnan(wanted)
        worst = float(np.abs(found[mask] - wanted[mask]).max()) if mask.any() else 0.0
        self.assertLessEqual(worst, tol, f"{what}: la mayor diferencia es {worst}")

    def agrees_with(self, outcome: Any, hand: Any, scene: bdata.Scene) -> None:
        """El resultado es el del cálculo independiente: las semillas, el recorte, la superficie y las tres cifras (≤ 10⁻⁹)."""
        self.assertEqual(outcome.window, (slice(0, scene.start.shape[0]), slice(0, scene.start.shape[1])))
        self.same(outcome.seeds, hand.seeds, what="las semillas")
        self.near(outcome.stepped, hand.stepped, what="el escalonado recortado")
        self.near(outcome.surface, hand.surface, what="la superficie")
        self.assertEqual(int(outcome.footprint.sum()), hand.cells)
        self.close(outcome.volume_m3, hand.volume_m3, what="el volumen")
        self.close(outcome.area_m2, hand.area_m2, what="el área")
        self.close(outcome.height_max_m, hand.height_max_m, what="la altura máxima")


def outcome_of(scene: bdata.Scene, crown: float, **options: Any) -> Any:
    return buttress.compute_buttress(bdata.job_of(scene, crown, **options))


# --- La fórmula cerrada (RF-013-23) ----------------------------------------------------------------------------------------


class StripClosedFormTest(Close):
    """RF-016-17, RF-013-23: una franja de coronación de lado a lado sobre un llano es un problema de una dimensión, que sale de
    la fórmula del escalonado en relleno y del recorte final sin el oráculo ni el código."""

    def check(self, metric: str, crown: float, level: float, source: Any = bdata.SMALL) -> None:
        scene = bdata.strip_scene(level=level, source=source)
        rows, cols = scene.start.shape
        formula = bdata.strip_closed_form(rows, 28, 31, level=level, crown=crown, found=scene.profile, step=STEP,
                                          metric=metric)
        outcome = outcome_of(scene, crown, metric=metric)
        for column in range(cols):
            with self.subTest(column=column):
                self.near(outcome.stepped[:, column], np.array(formula.stepped), what="el recorte")
                self.near(outcome.surface[:, column], np.array(formula.surface), what="la superficie")
        self.close(outcome.volume_m3, formula.volume * cols, what="el volumen")
        self.close(outcome.area_m2, formula.area * cols, what="el área")
        self.close(outcome.height_max_m, formula.height_max, what="la altura máxima")

    def test_the_stepped_fill_of_a_strip_is_the_closed_form_with_the_exact_metric(self) -> None:
        """La coronación a 120 m (el ancla de 100 m y dos bancos de 10 m) sobre un llano de 102 m: el contrafuerte tiene
        varias bermas y su superficie, su volumen, su área y su altura máxima son la fórmula cerrada a ≤ 10⁻⁹."""
        self.check("exact", 120.0, 102.0)

    def test_and_with_the_chamfer_metric(self) -> None:
        """El *chamfer* mide un paso de eje con su escala (0,98644: ADR-0014) y la envolvente baja más despacio."""
        self.check("chamfer5", 120.0, 102.0)

    def test_the_height_is_the_crown_over_the_plane_and_the_foot_is_outside_the_zone(self) -> None:
        """La altura máxima es la coronación menos el llano (las filas del medio de la zona no las baja el recorte) y hay
        contrafuerte fuera de la zona dibujada: el pie no se recorta a ella (error 19)."""
        scene = bdata.strip_scene(level=102.0)
        outcome = outcome_of(scene, 120.0)
        self.close(outcome.height_max_m, 18.0, what="120 − 102")
        self.assertTrue((outcome.footprint & ~scene.zone).any())
        outside = np.flatnonzero(outcome.footprint[:, 0] & ~scene.zone[:, 0])
        self.assertGreaterEqual(outside.size, 8)

    def test_the_numbers_of_the_stairs_by_hand(self) -> None:
        """RF-013-23 con números que se hacen a mano: ``h = 10``, cara a 45°, berma 10 (avance 20 m, talud general 0,5) y celdas
        de 2 m: ``E_k = 120 − k`` (``k`` filas de la zona) y, con ``u = (E − 100)/10``, el escalonado es ``110 + máx(2·(E − 110) −
        10, 0)`` (``k`` ≤ 10) y ``100 + máx(2·(E − 100) − 10, 0)`` (``k`` de 11 a 20): 118, 116, 114, 112, 110, 110… y 108, 106,
        104, 102, 100…; el contrafuerte llega hasta la fila ``k = 13`` sobre un llano de 102 m."""
        scene = bdata.strip_scene(level=102.0)
        formula = bdata.strip_closed_form(60, 28, 31, level=102.0, crown=120.0, found=scene.profile, step=STEP)
        general = scene.profile.general_tan
        self.close(general, 0.5, what="el talud general")
        stairs = formula.stairs
        wanted = {1: 118.0, 2: 116.0, 3: 114.0, 4: 112.0, 5: 110.0, 6: 110.0, 10: 110.0, 11: 108.0, 12: 106.0, 13: 104.0,
                  14: 102.0, 15: 100.0, 20: 100.0}
        for k, level in wanted.items():
            with self.subTest(k=k):
                self.assertLessEqual(abs(stairs[31 + k] - level), 1e-9)
                self.assertLessEqual(abs(stairs[28 - k] - level), 1e-9)
        outcome = outcome_of(scene, 120.0)
        rows = np.flatnonzero(outcome.footprint[:, 0])
        self.assertEqual((int(rows.min()), int(rows.max())), (28 - 13, 31 + 13))


# --- Una implementación independiente (A10) --------------------------------------------------------------------------------


class OracleTest(Close):
    """RF-016-17: el tronco de pirámide sobre un llano y un relieve con casos raros, con el cálculo independiente."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plane = bdata.plane_scene()
        cls.relief = bdata.relief_scene(3)

    def test_a_square_zone_on_a_plane_is_the_independent_calculation(self) -> None:
        """RF-016-17: el tronco de pirámide escalonado, con las dos métricas."""
        for metric in ("exact", "chamfer5"):
            with self.subTest(metric=metric):
                hand = bdata.hand_of(self.plane, 120.0, metric=metric)
                self.agrees_with(outcome_of(self.plane, 120.0, metric=metric), hand, self.plane)

    def test_a_relief_with_no_data_cells_a_high_cell_and_no_fill_is_the_independent_calculation(self) -> None:
        """RF-016-17, RF-012-13: celdas sin dato (dentro y fuera de la zona), una celda de la zona por encima de la
        coronación, una cresta, el relleno no admitido, el factor de malla 0,93 y las dos métricas."""
        for metric in ("exact", "chamfer5"):
            with self.subTest(metric=metric):
                hand = bdata.hand_of(self.relief, 115.0, metric=metric)
                self.agrees_with(outcome_of(self.relief, 115.0, metric=metric), hand, self.relief)

    def test_the_reach_stops_the_envelope(self) -> None:
        """RF-016-17: con el alcance, la envolvente solo llega a esa distancia de la zona (RF-013-14): el resultado es el del
        cálculo independiente con el alcance y ninguna celda a más de él sube."""
        for metric in ("exact", "chamfer5"):
            with self.subTest(metric=metric):
                hand = bdata.hand_of(self.plane, 120.0, metric=metric, reach=14.0)
                outcome = outcome_of(self.plane, 120.0, metric=metric, reach=14.0)
                self.agrees_with(outcome, hand, self.plane)
                whole = outcome_of(self.plane, 120.0, metric=metric)
                self.assertLess(int(outcome.footprint.sum()), int(whole.footprint.sum()))
        rows, cols = np.nonzero(self.plane.zone)
        far = np.ones(self.plane.zone.shape, dtype=bool)
        for row, col in zip(rows.tolist(), cols.tolist(), strict=True):
            r, c = np.indices(self.plane.zone.shape)
            far &= np.hypot(r - row, c - col) * STEP > 14.0
        exact = outcome_of(self.plane, 120.0, reach=14.0)
        self.assertFalse((exact.footprint & far).any())

    def test_the_scenes_exercise_every_case(self) -> None:
        """Guardián: la escena del llano sube lo mismo en las cuatro caras y tiene bermas; la del relieve tiene semillas, un
        hueco, una celda de la zona que no siembra, celdas sin dato, relleno no admitido con partida bit a bit y contrafuerte
        fuera de la zona."""
        flat = outcome_of(self.plane, 120.0)
        self.assertGreater(int(flat.footprint.sum()), 300)
        self.assertTrue(np.array_equal(flat.footprint, flat.footprint.T))
        relief = outcome_of(self.relief, 115.0)
        zone = self.relief.zone
        self.assertEqual(int(relief.seeds.sum()), int(zone.sum()) - 2)  # un NaN y la celda a 118 m
        self.assertTrue(zone[18, 25] and not relief.seeds[18, 25])
        self.assertTrue(np.isnan(self.relief.start[15, 14]) and np.isnan(relief.surface[15, 14]))
        blocked = ~self.relief.allowed & (relief.stepped > self.relief.start)
        self.assertGreater(int(blocked.sum()), 20)
        self.same(relief.surface[blocked], self.relief.start[blocked], what="lo no admitido")
        self.assertTrue((relief.footprint & ~zone).any())


# --- Las propiedades -------------------------------------------------------------------------------------------------------


class PropertiesTest(Close):
    """RF-016-01, RF-016-17: lo que ha de cumplir cualquier contrafuerte."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = ((bdata.plane_scene(), 120.0), (bdata.relief_scene(5), 115.0), (bdata.relief_scene(6), 125.0))
        cls.outcomes = tuple(outcome_of(scene, crown) for scene, crown in cls.cases)

    def each(self) -> Any:
        for (scene, crown), outcome in zip(self.cases, self.outcomes, strict=True):
            with self.subTest(crown=crown, level=float(np.nanmin(scene.start))):
                yield scene, crown, outcome

    def test_no_cell_is_cut_and_nothing_changes_where_it_does_not_rise(self) -> None:
        """RF-016-17: la superficie no baja en ninguna celda (sin corte) y, donde no sube —también lo no admitido y lo sin
        dato—, es la de partida bit a bit."""
        for scene, _crown, outcome in self.each():
            with np.errstate(invalid="ignore"):
                self.assertFalse((outcome.surface < scene.start).any())
                stays = ~(outcome.surface > scene.start)
            self.same(outcome.surface[stays], scene.start[stays], what="lo que no sube")
            self.same(outcome.surface[~scene.allowed], scene.start[~scene.allowed], what="lo no admitido")

    def test_the_foot_is_not_cut_to_the_drawn_zone(self) -> None:
        """RF-016-17, error 19: el contrafuerte sube fuera de la zona dibujada, hasta donde llega la envolvente."""
        for scene, _crown, outcome in self.each():
            self.assertTrue((outcome.footprint & ~scene.zone).any())
            self.assertTrue((outcome.footprint & ~scene.zone & scene.allowed).any())

    def test_the_berms_are_at_the_anchor_levels(self) -> None:
        """RF-016-17, RF-013-24: a lo largo de las cuatro líneas que salen del centro de la zona hacia fuera, dos celdas seguidas a
        la misma cota (las bermas: una cara baja siempre, y dos celdas del recorte nunca coinciden por azar) están en una cota
        ``z₀ + n·h`` a ≤ 10⁻⁹ m; salen la coronación y los bancos que baja el llano, y la zona de la coronación es una."""
        found, crown = self.cases[0]
        stepped, zone = self.outcomes[0].stepped, found.zone
        rows, cols = np.flatnonzero(zone.any(axis=1)), np.flatnonzero(zone.any(axis=0))
        row, col = int(rows[0] + rows[-1]) // 2, int(cols[0] + cols[-1]) // 2
        lines = (stepped[row, col:], stepped[row, :col + 1][::-1], stepped[row:, col], stepped[:row + 1, col][::-1])
        profile = found.profile
        plateaus: set[float] = set()
        for line in lines:
            for first, second in zip(line[:-1].tolist(), line[1:].tolist(), strict=True):
                if abs(first - second) <= 1e-12:
                    index = (first - profile.anchor_m) / profile.height_m
                    self.assertLessEqual(abs(index - round(index)) * profile.height_m, 1e-9, f"{first} no es de un ancla")
                    plateaus.add(round(first, 6))
        self.assertTrue({crown, 110.0, 100.0} <= plateaus, f"las bermas son {sorted(plateaus)}")

    def test_the_thickness_is_not_negative_and_adds_up_to_the_surface(self) -> None:
        """RF-016-01: el espesor (salida − partida) no es negativo, vale 0 donde no sube y, con ``derive`` (``base = partida``,
        ``techo = base + espesor``), el techo es la superficie a ≤ 10⁻¹²; el volumen es su suma por el área de la celda."""
        for scene, _crown, outcome in self.each():
            with np.errstate(invalid="ignore"):
                self.assertFalse((outcome.thickness < 0.0).any())
            self.assertTrue(np.array_equal(np.isnan(outcome.thickness), np.isnan(scene.start)))
            base, top = thickness.derive(scene.start, outcome.thickness, "on_base")
            self.near(base, scene.start, what="la base", tol=0.0)
            self.near(top, outcome.surface, what="el techo", tol=1e-12)
            self.assertTrue(np.array_equal(outcome.footprint, np.nan_to_num(outcome.thickness) > 0.0))
            self.close(outcome.volume_m3, float(np.nansum(outcome.thickness)) * STEP * STEP, what="el volumen")
            self.assertEqual(outcome.area_m2, int(outcome.footprint.sum()) * STEP * STEP)

    def test_the_outcome_gives_the_pieces_the_next_tasks_need(self) -> None:
        """La zona, las semillas, el recorte sin máscara (que da el pie cortado, T28) y la cota de coronación: lo que dejan
        las máscaras es lo que el escalonado sin máscara tiene de más."""
        for scene, crown, outcome in self.each():
            self.same(outcome.zone, scene.zone, what="la zona")
            self.assertEqual(outcome.crown_m, crown)
            free = compose.compose(scene.start, outcome.stepped, np.ones(scene.zone.shape, dtype=bool), FILL)
            masked = compose.compose(scene.start, outcome.stepped, scene.allowed, FILL)
            self.same(masked, outcome.surface, what="la composición con la máscara")
            with np.errstate(invalid="ignore"):
                self.assertFalse((free < masked).any())


# --- RF-016-18: lo que se rechaza ------------------------------------------------------------------------------------------


class RefusalTest(Close):
    """RF-016-18, D-21, RF-015-08: la cota de coronación fuera del ancla o por debajo de la partida, y lo que no tiene valor
    por defecto; sin registrar nada ni elegir una cota por la persona."""

    def setUp(self) -> None:
        self.scene = bdata.plane_scene(level=101.5)

    def refused(self, crown: float | None, **options: Any) -> Any:
        with self.assertRaises(DesignError) as caught:
            buttress.buttress_steps(bdata.job_of(self.scene, crown, **options))
        return caught.exception

    def test_a_crown_off_the_anchor_is_refused_with_the_nearest_anchor(self) -> None:
        """RF-016-18, D-21: ``crown_m − z₀`` no es múltiplo de ``h`` ⇒ ``des.buttress_crown_off_anchor`` con la capa, el
        contrafuerte, la cota, el perfil y la cota del ancla más próxima; **al pedir los pasos**, antes de calcular."""
        error = self.refused(123.0)
        self.assertEqual(error.code, "des.buttress_crown_off_anchor")
        self.assertEqual(error.field, CROWN)
        self.assertEqual(error.value, 123.0)
        self.assertEqual(error.values["anchor"], 120.0)
        for text in ("«Zonas de coronación»", "«Contrafuerte de prueba»", "«SMALL_10_45_10»", "123", "120"):
            self.assertIn(text, error.text)

    def test_the_nearest_anchor_is_below_or_above_and_a_tie_goes_to_the_lower(self) -> None:
        """RF-016-18: la cota del ancla más próxima, por debajo o por encima; a igual distancia, la menor."""
        for crown, anchor in ((126.0, 130.0), (124.0, 120.0), (125.0, 120.0), (96.5, 100.0), (84.0, 80.0), (-3.0, 0.0)):
            with self.subTest(crown=crown):
                error = self.refused(crown)
                self.assertEqual(error.code, "des.buttress_crown_off_anchor")
                self.assertEqual(error.values["anchor"], anchor)

    def test_a_crown_on_the_anchor_is_accepted_also_with_float_noise(self) -> None:
        """RF-016-18: lo que dista del ancla ≤ 10⁻⁹ m (el redondeo de ``z₀ + n·h`` con un paso decimal) se acepta; una
        milésima, no."""
        scene = bdata.plane_scene(level=100.5, source=dfx.ProfileData("DECIMAL_2_45_2", "decimal_2_45_2", 2.4, 45.0, 2.4,
                                                                      100.1))
        crown = 100.1 + 4 * 2.4
        self.assertNotEqual(crown, 109.7)  # 109.69999999999999: lo que da la suma frente a lo que teclea una persona
        buttress.buttress_steps(bdata.job_of(scene, 109.7))
        buttress.buttress_steps(bdata.job_of(scene, crown))
        with self.assertRaises(DesignError) as caught:
            buttress.buttress_steps(bdata.job_of(scene, 109.701))
        self.assertEqual(caught.exception.code, "des.buttress_crown_off_anchor")

    def test_a_crown_below_the_start_in_the_whole_zone_is_refused_as_there_is_no_buttress(self) -> None:
        """RF-016-18: con la partida a la cota de coronación o por encima en toda la zona (o sin dato), no hay contrafuerte:
        ``des.buttress_crown_below_support``, nombrando la capa, el contrafuerte y la cota; al avanzar, sin crear nada."""
        for level in (120.0, 125.0, np.nan):
            with self.subTest(level=level):
                scene = bdata.plane_scene()
                scene.start[scene.zone] = level
                steps = buttress.buttress_steps(bdata.job_of(scene, 120.0))
                with self.assertRaises(DesignError) as caught:
                    next(steps)
                self.assertEqual(caught.exception.code, "des.buttress_crown_below_support")
                self.assertEqual(caught.exception.field, CROWN)
                self.assertEqual(caught.exception.value, 120.0)
                for text in ("«Zonas de coronación»", "«Contrafuerte de prueba»", "120"):
                    self.assertIn(text, caught.exception.text)

    def test_one_cell_of_the_zone_below_the_crown_is_enough(self) -> None:
        """RF-016-17: basta una celda de la zona por debajo de la coronación: siembra, aunque las demás no."""
        scene = bdata.plane_scene()
        scene.start[scene.zone] = 130.0
        scene.start[20, 20] = 119.0
        outcome = buttress.compute_buttress(bdata.job_of(scene, 120.0))
        self.assertEqual(int(outcome.seeds.sum()), 1)
        self.assertTrue(outcome.seeds[20, 20])

    def test_the_crown_has_no_default_and_is_checked(self) -> None:
        """RF-015-08, D-21: sin cota de coronación, ``des.entity_param_missing`` con el campo y el contrafuerte por su nombre;
        no finita, ``des.entity_param_range``: no se elige una cota por la persona."""
        error = self.refused(None)
        self.assertEqual(error.code, "des.entity_param_missing")
        self.assertEqual(error.field, CROWN)
        self.assertIn("«Contrafuerte de prueba»", error.text)
        self.assertIn("«Zonas de coronación»", error.text)
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(crown=value):
                self.assertEqual(self.refused(value).code, "des.entity_param_range")

    def test_the_reach_and_the_metric_are_checked_and_have_their_defaults(self) -> None:
        """RF-015-08, D-22 de la 015: un alcance que no es mayor que 0, ``des.entity_param_range``; una métrica que no es de la
        lista, ``des.entity_param_choice``; sin alcance no hay tope y sin métrica, la euclídea exacta."""
        for value in (0.0, -5.0, math.nan):
            with self.subTest(reach=value):
                self.assertEqual(self.refused(120.0, reach=value).code, "des.entity_param_range")
        self.assertEqual(self.refused(120.0, metric="chamfer3").code, "des.entity_param_choice")
        default = outcome_of(self.scene, 120.0)
        self.assertEqual((default.metric, default.reach_m), ("exact", None))
        self.same(default.surface, outcome_of(self.scene, 120.0, metric="exact").surface)

    def test_the_job_refuses_what_is_not_a_buttress(self) -> None:
        """Errores del programa (``ValueError`` o ``TypeError``): un código que no es el de un contrafuerte, un valor que no es
        de él, un perfil con otro código que el del valor, un array de otra forma o que no es booleano."""
        job = bdata.job_of(self.scene, 120.0)
        for changes in ({"code": "PLT-001"}, {"code": "BTR-1"}, {"values": {"width_m": 3.0}},
                        {"values": {"crown_m": 120.0, "profile": "otro"}}, {"start": np.zeros((5, 5))},
                        {"zone": np.zeros((5, 5), dtype=bool)}, {"fill_allowed": np.ones((5, 5), dtype=bool)}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                dataclasses.replace(job, **changes)
        with self.assertRaises(TypeError):
            dataclasses.replace(job, request="un contrafuerte")
        with self.assertRaises(TypeError):
            dataclasses.replace(job, profile=bdata.SMALL)
        same = dataclasses.replace(job, values={"crown_m": 120.0, "profile": self.scene.profile.code})
        buttress.compute_buttress(same)


# --- La zona de solo restauración (D-24, H-10) ----------------------------------------------------------------------------


class RestorationOnlyTest(Close):
    """RF-016-17, D-24, RF-012-13: la 012 admite el relleno en las zonas de solo restauración (no el corte): el pie del
    contrafuerte las atraviesa, y se detiene donde el relleno está prohibido. Con las máscaras de verdad."""

    @classmethod
    def setUpClass(cls) -> None:
        items = [
            make_constraint("r_concesion", T.LEGAL_LIMIT, (0, 0, 40, 30), fid=1),
            make_constraint("r_perimetro", T.ACTION_PERIMETER, (1, 1, 39, 29), fid=2),
            make_constraint("r_restauracion", T.RESTORATION_ONLY, (22, 8, 30, 20), fid=3),
            make_constraint("r_sin_relleno", T.NO_FILL, (30, 8, 38, 20), fid=4),
        ]
        prepared = combine.prepare(items, resolved_for(items, inward=0.0), MASK_GRID)
        found = combine.combine(prepared.zones, prepared.limits, MASK_GRID)
        cls.masks = access.MaskSet(MASK_GRID, "v-mano", "op-mano", access.MaskState.CURRENT, (), found.classes)
        rows, cols = MASK_GRID.shape
        y, x = np.mgrid[0:rows, 0:cols]
        cls.x = x + 0.5
        cls.y = rows - y - 0.5
        cls.profile = bdata.profile(dfx.ProfileData("TWO_2_45_2", "two_2_45_2", 2.0, 45.0, 2.0, 100.0))
        zone = (cls.x > 12) & (cls.x < 18) & (cls.y > 10) & (cls.y < 18)
        cls.scene = bdata.Scene(MASK_GRID, np.full((rows, cols), 100.5), zone, compose.admitted(cls.masks, FILL),
                                cls.profile)
        cls.outcome = outcome_of(cls.scene, 108.0)

    def zone_of(self, left: float, right: float) -> np.ndarray:
        return (self.x > left) & (self.x < right) & (self.y > 8) & (self.y < 20)

    def test_the_masks_allow_fill_but_not_cut_in_the_restoration_zone(self) -> None:
        """RF-012-13 (D-24): en la zona de solo restauración el relleno está admitido y el corte, no; en la de sin relleno,
        ninguno de los dos."""
        restoration = self.zone_of(22, 30)
        self.assertTrue(self.masks.fill_allowed()[restoration].all())
        self.assertFalse(self.masks.cut_allowed()[restoration].any())
        no_fill = self.zone_of(30, 38)
        self.assertFalse(compose.admitted(self.masks, FILL)[no_fill].any())

    def test_the_foot_enters_the_restoration_zone_and_stops_at_the_no_fill_one(self) -> None:
        """RF-016-17, D-24, error 19: el contrafuerte sube dentro de la zona de solo restauración (fuera de la zona dibujada de
        la coronación) y no toca ni un bit de la de sin relleno, aunque la envolvente llegue a ella."""
        restoration = self.zone_of(22, 30)
        no_fill = self.zone_of(30, 38)
        self.assertGreater(int((self.outcome.footprint & restoration).sum()), 10)
        self.assertTrue((self.outcome.stepped[no_fill] > self.scene.start[no_fill]).any())  # la envolvente llega
        self.same(self.outcome.surface[no_fill], self.scene.start[no_fill], what="lo que no admite relleno")
        self.assertTrue((self.outcome.footprint & ~self.scene.zone).any())

    def test_it_is_the_independent_calculation_with_the_real_masks(self) -> None:
        """RF-016-17: la superficie, el volumen y el área son los del cálculo independiente con el relleno que dicen las
        máscaras (``fill_allowed`` o la franja de solo relleno)."""
        hand = bdata.hand_of(self.scene, 108.0)
        self.agrees_with(self.outcome, hand, self.scene)

    def test_without_the_restoration_zone_the_foot_would_be_the_same_except_there(self) -> None:
        """D-24: si la zona de solo restauración no admitiera el relleno, el pie quedaría cortado en ella (error 19): la
        diferencia entre admitirlo y no es justo lo que sube dentro de ella (lo de T28: el pie cortado)."""
        restoration = self.zone_of(22, 30)
        blocked = dataclasses.replace(self.scene, allowed=self.scene.allowed & ~restoration)
        cut = outcome_of(blocked, 108.0)
        self.assertEqual(int((cut.footprint & restoration).sum()), 0)
        self.assertLess(cut.volume_m3, self.outcome.volume_m3)
        self.same(cut.surface[~restoration], self.outcome.surface[~restoration], what="fuera de la zona")


# --- La ventana de trabajo (A0) --------------------------------------------------------------------------------------------


class WindowTest(Close):
    """A0 (plan 016 §5.4): la ventana de la zona ampliada por lo que alcanza la envolvente y lo que aún nota el recorte final da el
    mismo resultado que la rejilla entera (a ≤ 10⁻¹² m: el orden de las sumas del *chamfer* no es el mismo)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.level = 109.3  # con la métrica exacta, sin el margen del recorte la ventana cambia 0,054 m
        cls.scene = bdata.plane_scene(100, 100, level=cls.level, box=(47, 53, 47, 53))
        cls.crown = 120.0
        cls.lowest = float(cls.scene.start.min())
        cls.whole = outcome_of(cls.scene, cls.crown)

    def window_for(self, reach: float, metric: str = "exact") -> Any:
        return buttress.buttress_window(self.scene.zone, self.scene.grid, reach, metric)

    def run_without_the_check(self, window: Any) -> Any:
        """El cálculo de una ventana **sin** la comprobación de que cubre lo que debe (para enseñar lo que cambiaría)."""
        job = bdata.job_of(self.scene, self.crown, region=window, lowest_m=self.lowest)
        last = None
        for last in buttress._buttress_progress(job, buttress._settings(job), 0.05):
            pass
        return last.result

    def test_the_trim_margin_is_what_the_final_trim_can_notice(self) -> None:
        """A0: el recorte final baja una celda por lo que hay más allá solo a menos de ``h / (0,98644 · tan α · malla − talud
        general · malla · razón)`` (la razón es 1 con la euclídea y 1/0,98644 con el *chamfer*: ADR-0014); con la cara más
        tendida que el talud general (sin berma) no tiene alcance."""
        small = self.scene.profile
        tan = math.tan(math.radians(45.0))
        general = 10.0 / (10.0 / tan + 10.0)
        self.close(buttress.trim_margin_m(small), 10.0 / (0.98644 * tan - general), what="exacta")
        self.close(buttress.trim_margin_m(small, "chamfer5"), 10.0 / (0.98644 * tan - general / 0.98644), what="chamfer")
        half = bdata.profile(bdata.SMALL, mesh_factor=0.5)
        self.close(buttress.trim_margin_m(half), 2.0 * buttress.trim_margin_m(small), what="el factor de malla")
        self.assertEqual(buttress.trim_margin_m(bdata.profile(bdata.SMALL, berm_m=0.0)), math.inf)

    def test_the_reach_is_the_distance_to_the_lowest_level_plus_the_trim_margin(self) -> None:
        """A0: el alcance es ``(coronación − cota más baja) / (talud general · malla)`` más el margen del recorte; con el alcance
        fijado, el menor de los dos; sin la cota más baja, el fijado; sin ninguno de los dos, un error del programa."""
        found = self.scene.profile
        margin = buttress.trim_margin_m(found)
        envelope = (120.0 - self.lowest) / found.general_tan
        self.close(buttress.buttress_reach_m(found, 120.0, self.lowest), envelope + margin, what="alcance")
        self.close(buttress.buttress_reach_m(found, 120.0, self.lowest, 10.0), 10.0, what="el fijado, si es menor")
        self.close(buttress.buttress_reach_m(found, 120.0, self.lowest, 1e6), envelope + margin, what="el otro, si es menor")
        self.close(buttress.buttress_reach_m(found, 120.0, None, 33.0), 33.0, what="sin la cota más baja")
        self.close(buttress.buttress_reach_m(found, 120.0, 130.0), margin, what="la partida por encima de la coronación")
        self.assertEqual(buttress.buttress_reach_m(bdata.profile(bdata.SMALL, berm_m=0.0), 120.0, 100.0), math.inf)
        with self.assertRaises(ValueError):
            buttress.buttress_reach_m(found, 120.0, None)
        half = bdata.profile(bdata.SMALL, mesh_factor=0.5)
        self.close(buttress.buttress_reach_m(half, 120.0, self.lowest),
                   (120.0 - self.lowest) / (half.general_tan * 0.5) + buttress.trim_margin_m(half), what="malla")

    def test_the_window_is_the_zone_box_plus_the_reach_and_two_cells(self) -> None:
        """A0: la caja de la zona (filas y columnas 47 a 52) más ``⌈alcance / paso⌉ + 2`` celdas por cada lado
        (``⌈alcance / (0,98644 · paso)⌉ + 2`` con el *chamfer*), recortada a la rejilla; con un alcance infinito, la rejilla
        entera; ninguna zona, ninguna ventana."""
        self.assertEqual(self.window_for(37.0), (slice(47 - 21, 53 + 21), slice(47 - 21, 53 + 21)))
        self.assertEqual(self.window_for(0.0), (slice(45, 55), slice(45, 55)))
        self.assertEqual(self.window_for(37.0, "chamfer5"), (slice(47 - 21, 53 + 21), slice(47 - 21, 53 + 21)))
        self.assertEqual(self.window_for(1000.0), (slice(0, 100), slice(0, 100)))
        self.assertEqual(self.window_for(math.inf), (slice(0, 100), slice(0, 100)))
        self.assertIsNone(buttress.buttress_window(np.zeros(self.scene.zone.shape, dtype=bool), self.scene.grid, 10.0))
        with self.assertRaises(ValueError):
            buttress.buttress_window(np.zeros((5, 5), dtype=bool), self.scene.grid, 10.0)

    def test_reading_only_the_window_gives_the_same_result(self) -> None:
        """A0: con la ventana del alcance de la envolvente más el margen del recorte (la cota más baja de la rejilla entera), el
        contrafuerte es el mismo que con la rejilla entera a ≤ 10⁻¹² m; ``compose`` lo vuelve a poner en ella."""
        for metric in ("exact", "chamfer5"):
            with self.subTest(metric=metric):
                reach = buttress.buttress_reach_m(self.scene.profile, self.crown, self.lowest, None, metric)
                window = self.window_for(reach, metric)
                self.assertNotEqual(window, (slice(0, 100), slice(0, 100)))
                found = outcome_of(self.scene, self.crown, metric=metric, region=window, lowest_m=self.lowest)
                whole = outcome_of(self.scene, self.crown, metric=metric)
                self.assertEqual(found.window, window)
                self.near(found.compose(self.scene.start), whole.surface, what="la superficie entera", tol=1e-12)
                self.near(found.thickness, whole.thickness[window], what="el espesor", tol=1e-12)
                self.assertEqual(found.seeds.sum(), whole.seeds.sum())
                self.close(found.volume_m3, whole.volume_m3, rel=1e-12, what="el volumen")
                self.close(found.area_m2, whole.area_m2, rel=1e-12, what="el área")
                self.close(found.height_max_m, whole.height_max_m, rel=1e-12, what="la altura máxima")

    def test_without_the_trim_margin_the_window_changes_the_result(self) -> None:
        """A0: con la ventana de solo la envolvente (sin lo que aún nota el recorte), el contrafuerte cambia en el borde de la
        ventana más de un milímetro con la métrica exacta: por eso la ventana lleva el margen y el trabajo comprueba que lo
        lleva."""
        window = self.window_for((self.crown - self.lowest) / self.scene.profile.general_tan)
        narrow = self.run_without_the_check(window)
        worst = float(np.abs(narrow.compose(self.scene.start) - self.whole.surface).max())
        self.assertGreater(worst, 1e-3)
        with self.assertRaises(ValueError):
            buttress.buttress_steps(bdata.job_of(self.scene, self.crown, region=window, lowest_m=self.lowest))

    def test_with_a_reach_the_window_does_not_need_the_lowest_level(self) -> None:
        """A0: con el alcance fijado basta él para la ventana (no hace falta la cota más baja ni el margen: más allá no hay
        escalonado) y el resultado es el de la rejilla entera con ese alcance."""
        for metric in ("exact", "chamfer5"):
            with self.subTest(metric=metric):
                window = self.window_for(16.0, metric)
                found = outcome_of(self.scene, self.crown, reach=16.0, metric=metric, region=window)
                whole = outcome_of(self.scene, self.crown, reach=16.0, metric=metric)
                self.near(found.compose(self.scene.start), whole.surface, what="la superficie entera", tol=1e-12)
                self.assertLess(window[0].stop - window[0].start, 100)
                self.assertGreater(float(whole.footprint.sum()), 100)

    def test_a_window_that_does_not_cover_the_reach_is_a_program_error(self) -> None:
        """A0: una ventana más pequeña que la que pide el alcance (o sin la cota más baja, si no hay alcance fijado) es un
        error del programa, no un contrafuerte recortado en silencio."""
        too_small = (slice(40, 60), slice(40, 60))
        with self.assertRaises(ValueError):
            buttress.buttress_steps(bdata.job_of(self.scene, self.crown, region=too_small, lowest_m=self.lowest))
        reach = buttress.buttress_reach_m(self.scene.profile, self.crown, self.lowest)
        window = self.window_for(reach)
        with self.assertRaises(ValueError):
            buttress.buttress_steps(bdata.job_of(self.scene, self.crown, region=window))
        edge = (slice(window[0].start + 1, window[0].stop), window[1])
        with self.assertRaises(ValueError):
            buttress.buttress_steps(bdata.job_of(self.scene, self.crown, region=edge, lowest_m=self.lowest))
        with self.assertRaises(ValueError):
            bdata.job_of(self.scene, self.crown, region=window, lowest_m=math.nan)
        buttress.buttress_steps(bdata.job_of(self.scene, self.crown, region=window, lowest_m=self.lowest))
        whole = (slice(0, 100), slice(0, 100))
        buttress.buttress_steps(bdata.job_of(self.scene, self.crown, region=whole, lowest_m=self.lowest))


# --- Los pasos y las cifras (RNF-016-03) -----------------------------------------------------------------------------------


class StepsTest(Close):
    """RNF-016-03: por pasos, cancelable, sin tocar la entrada y con sus cifras."""

    def test_the_steps_end_with_the_outcome_and_match_the_one_shot_call(self) -> None:
        """``buttress_steps`` da ``Progress``; solo el último lleva el resultado, y es el de ``compute_buttress``. Con un
        presupuesto de 0 s cada unidad es un paso: son varios."""
        scene = bdata.relief_scene(1)
        steps = list(buttress.buttress_steps(bdata.job_of(scene, 115.0), budget_s=0.0))
        self.assertGreater(len(steps), 5)
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        last = steps[-1].result
        self.assertIsInstance(last, buttress.ButtressOutcome)
        once = outcome_of(scene, 115.0)
        self.same(last.surface, once.surface, what="la superficie")
        self.assertEqual(last.volume_m3, once.volume_m3)
        phases = [step.phase for step in steps]
        self.assertEqual(phases[-1], "buttress")
        self.assertIn("envelope", phases)
        self.assertIn("trim", phases)

    def test_closing_half_way_leaves_nothing_and_no_input_changes(self) -> None:
        """Cerrar el generador a mitad no deja nada y ni la partida, ni la zona, ni lo admitido, ni los valores se modifican
        (tampoco al terminar)."""
        scene = bdata.relief_scene(2)
        job = bdata.job_of(scene, 115.0, metric="chamfer5")
        before = (job.start.copy(), job.zone.copy(), job.fill_allowed.copy(), copy.deepcopy(dict(job.values)))
        steps = buttress.buttress_steps(job, budget_s=0.0)
        next(steps)
        next(steps)
        steps.close()
        buttress.compute_buttress(job)
        after = (job.start, job.zone, job.fill_allowed, dict(job.values))
        for found, wanted in zip(after, before, strict=True):
            if isinstance(wanted, np.ndarray):
                self.same(found, wanted)
            else:
                self.assertEqual(found, wanted)

    def test_each_step_takes_at_most_two_tenths_of_a_second(self) -> None:
        """RNF-016-03: en una ventana de 160 × 160 celdas (10 ha a 2 m; el contrafuerte de 10 ha de plan §7.3), con las dos
        métricas, cada llamada del hilo de Blender (cada paso con el presupuesto de 50 ms) tarda ≤ 0,2 s."""
        scene = bdata.plane_scene(160, 160, level=101.5, box=(60, 100, 60, 100))
        for metric in ("exact", "chamfer5"):
            with self.subTest(metric=metric):
                steps = buttress.buttress_steps(bdata.job_of(scene, 130.0, metric=metric), budget_s=0.05)
                worst = 0.0
                with closing(steps):
                    while True:
                        began = time.perf_counter()
                        step = next(steps)
                        worst = max(worst, time.perf_counter() - began)
                        if step.result is not None:
                            break
                self.assertLessEqual(worst, 0.2)

    def test_the_outcome_gives_the_figures_of_the_buttress(self) -> None:
        """RF-016-17: ``figures`` son las ``des.btr_*`` de ``provenance.buttress_figures`` (CALCULADO, con el ámbito de la
        entidad): el volumen, el área y la altura máxima; sin el pie cortado (todavía: la T28), no hay ``des.btr_cutoff_*``."""
        outcome = outcome_of(bdata.plane_scene(), 120.0)
        found = {figure.key: figure.value for figure in outcome.figures}
        self.assertEqual(set(found), {"des.btr_volume_m3", "des.btr_area_m2", "des.btr_height_max_m"})
        self.assertEqual(found["des.btr_volume_m3"], outcome.volume_m3)
        self.assertEqual(found["des.btr_area_m2"], outcome.area_m2)
        self.assertEqual(found["des.btr_height_max_m"], outcome.height_max_m)
        cut = dataclasses.replace(outcome, cutoff_m2=40.0, cutoff_m3=12.5)
        shown = {figure.key: figure.value for figure in cut.figures}
        self.assertEqual((shown["des.btr_cutoff_m2"], shown["des.btr_cutoff_m3"]), (40.0, 12.5))
        scope = outcome.figures[0].scope
        self.assertEqual(scope["entity"], bdata.CODE)

    def test_the_figures_are_summed_by_bands_of_rows_with_the_same_result(self) -> None:
        """RNF-016-03: el espesor se suma por bandas de filas (una unidad cada una); con bandas de una fila, el volumen, el
        área y la altura máxima con su lugar son los de la suma de una pieza (el volumen, a ≤ 10⁻¹²) y los del cálculo a mano."""
        scene = bdata.relief_scene(4)
        whole = outcome_of(scene, 115.0)
        with mock.patch.object(buttress, "CELLS_PER_UNIT", 1):
            banded = outcome_of(scene, 115.0)
        self.same(banded.surface, whole.surface)
        self.close(banded.volume_m3, whole.volume_m3, rel=1e-12, what="el volumen por bandas")
        self.close(banded.volume_m3, bdata.hand_of(scene, 115.0).volume_m3, what="el volumen a mano")
        self.assertEqual((banded.area_m2, banded.height_max_m, banded.height_max_x, banded.height_max_y),
                         (whole.area_m2, whole.height_max_m, whole.height_max_x, whole.height_max_y))

    def test_the_height_has_its_place_and_the_message_its_numbers(self) -> None:
        """La altura máxima se da con el centro de la primera celda (de arriba abajo y de oeste a este) que la tiene,
        en coordenadas absolutas; el mensaje dice el volumen, el área y la altura."""
        scene = bdata.plane_scene()
        outcome = outcome_of(scene, 120.0)
        top = np.argwhere(np.isclose(outcome.thickness, outcome.height_max_m, rtol=0.0, atol=0.0))[0]
        grid = scene.grid
        self.assertEqual(outcome.height_max_x, grid.west + (top[1] + 0.5) * grid.dx)
        self.assertEqual(outcome.height_max_y, grid.north - (top[0] + 0.5) * grid.dy)
        self.assertIn("«Contrafuerte de prueba»", outcome.message)
        self.assertIn(str(round(outcome.volume_m3)), outcome.message)

    def test_a_buttress_that_the_masks_do_not_admit_anywhere_is_empty(self) -> None:
        """RF-016-17: con el relleno sin admitir en ninguna celda, hay semillas pero nada sube: 0 m³, 0 m² y 0 m de altura,
        sin lugar, y la superficie es la de partida bit a bit (el pie cortado y su aviso: T28)."""
        scene = bdata.plane_scene()
        scene.allowed[:] = False
        outcome = outcome_of(scene, 120.0)
        self.assertEqual((outcome.volume_m3, outcome.area_m2, outcome.height_max_m), (0.0, 0.0, 0.0))
        self.assertEqual((outcome.height_max_x, outcome.height_max_y), (None, None))
        self.same(outcome.surface, scene.start)
        self.assertEqual(int(outcome.seeds.sum()), int(scene.zone.sum()))

    def test_a_crown_that_the_surface_already_reaches_in_part_still_builds_where_it_is_below(self) -> None:
        """RF-016-17: una cresta de la partida por encima de la envolvente queda como está (no se corta) y el contrafuerte
        sigue por los lados donde la partida está por debajo."""
        scene = bdata.plane_scene(level=101.5)
        scene.start[:, 30:] = 130.0  # un muro de 130 m al este, más alto que la coronación
        outcome = outcome_of(scene, 120.0)
        self.same(outcome.surface[:, 30:], scene.start[:, 30:], what="el muro")
        self.assertTrue(outcome.footprint[:, :30].any())
        hand = bdata.hand_of(scene, 120.0)
        self.agrees_with(outcome, hand, scene)


if __name__ == "__main__":
    unittest.main()
