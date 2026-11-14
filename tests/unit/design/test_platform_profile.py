# SPDX-License-Identifier: GPL-3.0-or-later
"""La contrapendiente, las cifras y los avisos de la plataforma (spec 015, T09; RF-015-23, RF-015-24,
RF-015-14 y RF-015-13; plan 015 §5.4, A4 y A5; B7, D-8 y D-16).

Las cuentas están hechas a mano y se comparan a ≤ 10⁻⁹ (D-9):

- **La franja de CE-015-02** (``entity_fixtures.strip_case``: eje de 200 m, 40 m de ancho, 1 % desde
  230 m) en «en corte y relleno» (el tramo bajo la rasante se rellena: sin dientes) deja el perfil
  sobre la rasante, ``230 + 0,01 (k + 0,5)`` por tramo de 1 m, que **baja hacia las abscisas
  pequeñas**: ninguna contrapendiente. Con **el intocable** (la banda de la abscisa 40 a 50 m, que cruza
  toda la huella y no se corta: 6 m por encima de la rasante) el perfil, recorrido en el sentido en
  que baja la rasante (de la abscisa 200 a la 0), sube sobre el mínimo aguas arriba (``230,505`` en
  el tramo 50) ``5,495 + 0,01 (k + 0,5)`` m en los tramos 40 a 49: la peor, 5,99 m en la abscisa 49,5.
- **Un tramo bajo la rasante en «en corte»** (una rejilla propia de 30 × 100 celdas de 1 m, eje de
  80 m de oeste a este, 10 m de ancho, 100 m al ± 1 %, el terreno 6 m por encima y, entre las
  abscisas 30 y 50 m, 5 m por debajo): la plataforma no rellena y deja un foso; el perfil sube al
  salir de él, **en el sentido en que baja la rasante**: con − 1 % (baja hacia el este) los tramos 50
  a 79 sobre ``94,505`` (la peor, 4,99 m en la abscisa 50,5) y con + 1 % (baja hacia el oeste) los
  tramos 0 a 29 sobre ``95,305`` (la peor, 4,99 m en la abscisa 29,5). Con 0 %, la contrapendiente
  es máximo menos mínimo del perfil (D-16): 5 m.
- **El orden de una cantera de la 014** (``quarry_fixtures.terrain``: la explotación 10 m y la final
  25 m por debajo; ``final ≤ explotación ≤ terreno``): una plataforma «en corte y relleno» a 215 m
  sobre la final sube hasta 13,59375 m por encima de la explotación; una «en corte» a 190 m sobre la
  explotación queda hasta 8,59375 m por debajo de la final.
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

platform = import_geoblender("design.platform")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
preview = import_geoblender("design.preview")
quarry = import_geoblender("design.quarry")
design_report = import_geoblender("design.report")
gis = import_geoblender("gis")
i18n = import_geoblender("core.i18n")
params_core = import_geoblender("core.params")

placeholders = i18n.placeholders
THIN = i18n.THIN_SPACE

DesignError = messages.DesignError
TOL = 1e-9
"""La tolerancia de las cuentas a mano (D-9)."""
PROJECT = {params.TOLERANCE_FACE: 1.0, params.VERIFY_MIN_THICKNESS: 0.05,
           params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0, params.WARNING_RATIO: 2.0}
"""Los parámetros del proyecto que leen el borde y el resumen (valores de la prueba)."""


# --- Lo que construyen las pruebas -------------------------------------------------------------


def request(name: str = "P1") -> Any:
    return model.PlatformRequest(
        name=name, feature=name, start="Terreno",
        fields=model.PlatformFields(layer=efx.AXES_LAYER, start_level_field="cota_inicial",
                                    gradient_field="pendiente", width_field="ancho"))


def absolute(x: float, y: float) -> tuple[float, float]:
    """El punto local (m desde ``BASE``) en coordenadas absolutas."""
    point = cfx.absolute([(x, y)])[0]
    return float(point[0]), float(point[1])


def rounded(x: float, y: float) -> tuple[float, float]:
    """El punto local absoluto, al cm: como lo lleva un aviso."""
    point = absolute(x, y)
    return round(point[0], 2), round(point[1], 2)


def strip_job(case: Any, mode: str = "cut_fill", *, cut_allowed: np.ndarray | None = None,
              **values: object) -> Any:
    """El trabajo de la franja de ``case`` en el ``mode``."""
    parameters: dict[str, object] = {
        "width_m": case.width_m, "start_level_m": case.grade_start_m, "gradient_pct": case.slope_pct,
        "reach_m": 12.5, "edge_angle_deg": 40.0, "mode": mode, **values}
    return platform.PlatformJob(
        request(), "PLT-001", case.grid, case.terrain, platform.PlatformGeometry("line", ((case.axis,),)),
        parameters, case.cut_allowed if cut_allowed is None else cut_allowed, case.fill_allowed)


SMALL_ROWS, SMALL_COLS = 30, 100
SMALL_AXIS = ((10.0, 15.0), (90.0, 15.0))
"""El eje de las pruebas pequeñas (local): 80 m de oeste a este, con ``σ = x − 10``."""
HOLLOW = (30.0, 50.0)
"""El tramo bajo la rasante, de la abscisa 30 a la 50 m."""


def tilted_grid(nrows: int, ncols: int) -> Any:
    """Una rejilla de 1 m con su esquina suroeste en ``BASE`` (absoluta, float64)."""
    return gis.Grid(cfx.BASE[0], cfx.BASE[1] + nrows, 1.0, 1.0, ncols, nrows)


def small_job(gradient_pct: float, *, depth: float = 5.0, above: float = 6.0, mode: str = "cut",
              cut_allowed: np.ndarray | None = None, **values: object) -> Any:
    """La plataforma de 80 m de eje a 100 m con la pendiente dada: el terreno queda ``above`` m por
    encima de la rasante salvo entre las abscisas 30 y 50 m, donde queda ``depth`` m por debajo."""
    grid = tilted_grid(SMALL_ROWS, SMALL_COLS)
    sigma = np.broadcast_to((np.arange(SMALL_COLS) + 0.5 - 10.0)[None, :], grid.shape)
    level = 100.0 + sigma * (gradient_pct / 100.0)
    hollow = (sigma >= HOLLOW[0]) & (sigma < HOLLOW[1])
    terrain = np.where(hollow, level - depth, level + above)
    parameters: dict[str, object] = {
        "width_m": 10.0, "start_level_m": 100.0, "gradient_pct": gradient_pct, "reach_m": 12.5,
        "edge_angle_deg": 40.0, "mode": mode, **values}
    allowed = np.ones(grid.shape, dtype=bool)
    return platform.PlatformJob(
        request(), "PLT-001", grid, terrain, platform.PlatformGeometry(
            "line", ((cfx.absolute(SMALL_AXIS),),)), parameters,
        allowed.copy() if cut_allowed is None else cut_allowed, allowed.copy())


def small_oracle(gradient_pct: float, *, depth: float = 5.0) -> list[float]:
    """La cota de cada tramo de ``small_job`` en «en corte», a mano: la rasante, o ``depth`` m menos
    en el tramo bajo ella."""
    found = []
    for k in range(80):
        level = 100.0 + (k + 0.5) * gradient_pct / 100.0
        found.append(level - depth if HOLLOW[0] <= k < HOLLOW[1] else level)
    return found


def rise_oracle(levels: list[float], gradient_pct: float) -> list[float]:
    """La contrapendiente de cada tramo, por fuerza bruta: lo que sube sobre el mínimo de los tramos
    aguas arriba (recorrido en el sentido en que baja la rasante) o, con 0 %, sobre el mínimo de todo
    el perfil."""
    if gradient_pct == 0.0:
        low = min(levels)
        return [level - low for level in levels]
    order = list(range(len(levels)))
    if gradient_pct > 0.0:
        order.reverse()  # baja hacia las abscisas pequeñas
    found = [0.0] * len(levels)
    for position, k in enumerate(order):
        before = [levels[j] for j in order[:position]]
        found[k] = max(levels[k] - min(before), 0.0) if before else 0.0
    return found


def calculate(job: Any, project: Any = None) -> tuple[Any, Any, Any]:
    """La huella, la plataforma aplicada y su borde."""
    footprint = platform.platform_footprint(job)
    applied = platform.apply_platform(job, footprint)
    edge = platform.platform_edge(job, footprint, applied, PROJECT if project is None else project)
    return footprint, applied, edge


def outcome_of(job: Any, *, confirm: bool = False, **kwargs: Any) -> Any:
    """Todo el cálculo de ``job`` hasta su resultado."""
    footprint, applied, edge = calculate(job)
    return platform.platform_outcome(job, footprint, applied, edge, PROJECT,
                                     confirm_counterslope=confirm, **kwargs)


def codes(outcome: Any) -> list[str]:
    return [item.code for item in outcome.notices]


# --- Lo público --------------------------------------------------------------------------------


class PublicNamesTest(unittest.TestCase):
    """RF-015-23, RF-015-24, RF-015-14: lo que entrega esta tarea es público y está documentado."""

    def test_the_module_publishes_the_profile_the_figures_and_the_order(self) -> None:
        """``design.platform`` exporta el perfil, el resultado, el orden de la cantera y sus datos,
        cada nombre con su documentación."""
        names = ("HeldGroup", "LongProfile", "OrderBreach", "PlatformOutcome", "QuarryOrder",
                 "order_check", "platform_outcome", "platform_profile")
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, platform.__all__)
                self.assertTrue(getattr(platform, name).__doc__.strip())

    def test_the_new_messages_are_in_the_catalog_with_both_languages(self) -> None:
        """RF-015-23, RF-015-24: los dos mensajes que faltaban (lo que las máscaras no dejan rellenar
        y el rechazo de crear sin confirmar) están, con su texto en español y en inglés y con
        los mismos marcadores."""
        for code, severity in (("des.platform_below_masks", "warning"),
                               ("des.platform_counter_unconfirmed", "error")):
            with self.subTest(code=code):
                message = messages.MESSAGES[code]
                self.assertEqual(message.severity, severity)
                self.assertTrue(message.msgid and message.es)
                self.assertEqual(placeholders(message.msgid), placeholders(message.es))


# --- El perfil de la franja: sin contrapendiente ------------------------------------------------


class PlainStripProfileTest(unittest.TestCase):
    """RF-015-23: la franja de CE-015-02 en «en corte y relleno» queda sobre su rasante, que baja
    hacia las abscisas pequeñas (1 %): ninguna contrapendiente."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case()
        cls.outcome = outcome_of(strip_job(cls.case, "cut_fill"))
        cls.profile = cls.outcome.profile

    def test_one_section_per_cell_of_abscissa(self) -> None:
        """RF-015-23: 200 tramos de una celda de abscisa (``⌊σ/h⌋`` con σ de 0,5 a 199,5 m), su
        abscisa es el centro del tramo y la cota, la rasante ``230 + 0,01 (k + 0,5)`` a ≤ 10⁻⁹."""
        profile = self.profile
        np.testing.assert_array_equal(profile.section, np.arange(200))
        np.testing.assert_allclose(profile.chainage_m, np.arange(200) + 0.5, rtol=0, atol=TOL)
        np.testing.assert_allclose(profile.level_m, 230.0 + 0.01 * (np.arange(200) + 0.5),
                                   rtol=0, atol=TOL)
        self.assertEqual((profile.step_m, profile.gradient_pct), (1.0, 1.0))

    def test_the_place_of_a_section_is_its_highest_cell_the_northernmost_on_a_tie(self) -> None:
        """RF-015-23: las 40 celdas de un tramo tienen la misma cota: el lugar es el centro de la
        primera, la más al norte (``y = 219,5``), en su columna (``x = 100,5 + k``), absoluto."""
        profile = self.profile
        base_x, base_y = absolute(0.0, 0.0)
        np.testing.assert_allclose(profile.x, base_x + 100.5 + np.arange(200), rtol=0, atol=TOL)
        np.testing.assert_allclose(profile.y, np.full(200, base_y + 219.5), rtol=0, atol=TOL)

    def test_no_section_rises_so_nothing_is_warned_and_it_can_be_created(self) -> None:
        """RF-015-23: la rasante baja hacia la abscisa 0: ninguna contrapendiente, ningún aviso de
        ella y se puede crear sin confirmar."""
        self.assertEqual(float(self.profile.rise_m.max()), 0.0)
        self.assertFalse(self.profile.flagged.any())
        self.assertIsNone(self.profile.worst)
        self.assertFalse(self.outcome.counter_slope)
        self.assertFalse(self.outcome.needs_confirmation)
        self.assertIsNone(self.outcome.ensure_creatable())
        self.assertFalse([item for item in codes(self.outcome) if "counter" in item])
        self.assertEqual(self.profile.tolerance_m, 0.1)  # D-8, el valor por defecto

    def test_the_profile_is_read_on_the_surface_with_the_edge(self) -> None:
        """RF-015-23: el perfil es el de la superficie resultante (huella y borde): una superficie
        con la huella subida 1 m en unos tramos da otro perfil."""
        job = strip_job(self.case, "cut_fill")
        footprint, applied, edge = calculate(job)
        raised = edge.surface.copy()
        raised[footprint.cells & (np.abs(footprint.sigma - 100.5) < 0.1)] += 1.0
        found = platform.platform_profile(job, footprint, raised)
        self.assertAlmostEqual(float(found.level_m[100]), 231.005 + 1.0, delta=TOL)
        self.assertEqual(float(found.level_m[99]), float(self.profile.level_m[99]))


# --- La contrapendiente que hace un intocable --------------------------------------------------


class UntouchableCounterSlopeTest(unittest.TestCase):
    """RF-015-23 (B7, D-8): la banda del intocable cruza toda la huella y no se corta: queda 6 m por
    encima de la rasante. El perfil sube sobre el mínimo aguas arriba en los tramos 40 a 49."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case(untouchable=True)
        cls.job = strip_job(cls.case, "cut_fill")
        cls.outcome = outcome_of(cls.job)
        cls.profile = cls.outcome.profile

    def test_the_sections_over_the_untouchable_are_the_ones_that_rise(self) -> None:
        """RF-015-23: ``5,495 + 0,01 (k + 0,5)`` m en los tramos 40 a 49 (6 m sobre la rasante menos
        lo que ésta baja hasta el tramo 50, ``230,505``) y 0 en los demás."""
        flagged = np.flatnonzero(self.profile.flagged)
        np.testing.assert_array_equal(flagged, np.arange(40, 50))
        expected = np.zeros(200)
        expected[40:50] = 5.495 + 0.01 * (np.arange(40, 50) + 0.5)
        np.testing.assert_allclose(self.profile.rise_m, expected, rtol=0, atol=TOL)
        self.assertEqual(self.profile.counter_sections, 10)

    def test_the_worst_is_5_99_m_at_the_abscissa_49_5(self) -> None:
        """RF-015-23: la peor sube 5,99 m (``236,495 − 230,505``) en el tramo 49, abscisa 49,5 m,
        con el lugar de su celda más alta (la más al norte de su columna)."""
        profile = self.profile
        self.assertEqual(profile.worst, 49)
        self.assertAlmostEqual(float(profile.rise_m[49]), 5.99, delta=TOL)
        self.assertAlmostEqual(float(profile.chainage_m[49]), 49.5, delta=TOL)
        self.assertAlmostEqual(float(profile.level_m[49]), 236.495, delta=TOL)
        x, y = absolute(149.5, 219.5)
        self.assertAlmostEqual(float(profile.x[49]), x, delta=TOL)
        self.assertAlmostEqual(float(profile.y[49]), y, delta=TOL)

    def test_the_notice_gives_the_chainage_the_amount_and_the_place(self) -> None:
        """RF-015-23: el aviso lleva la abscisa (m), la cuantía (m), el lugar, la tolerancia y la
        entidad, y su texto está en español y en inglés (con la coma decimal y el punto)."""
        notice = next(item for item in self.outcome.notices
                      if item.code == "des.platform_counter_slope")
        x, y = rounded(149.5, 219.5)
        self.assertEqual(dict(notice.values), {
            "entity": "P1", "amount": 5.99, "chainage": 49.5, "x": x, "y": y, "tolerance": 0.1})
        self.assertEqual(notice.severity, "warning")
        self.assertIn("5,990", notice.text("es"))
        self.assertIn("49,5", notice.text("es"))
        self.assertIn("5.990", notice.text("en"))

    def test_it_cannot_be_created_without_the_express_confirmation(self) -> None:
        """RF-015-23: sin la confirmación expresa, el resultado la pide (``needs_confirmation``) y
        ``ensure_creatable`` rechaza con ``des.platform_counter_unconfirmed``, que nombra la
        entidad, la cuantía y la tolerancia; con ella se puede crear, y el aviso sigue en la lista."""
        outcome = self.outcome
        self.assertTrue(outcome.counter_slope)
        self.assertTrue(outcome.needs_confirmation)
        self.assertFalse(outcome.confirmed)
        with self.assertRaises(DesignError) as caught:
            outcome.ensure_creatable()
        error = caught.exception
        self.assertEqual(error.code, "des.platform_counter_unconfirmed")
        self.assertEqual((error.values["entity"], error.values["tolerance"]), ("P1", 0.1))
        self.assertIn("P1", error.text)
        self.assertIn("5,99", error.text)
        self.assertIn("5.99", error.text_in("en"))
        for sure in (outcome_of(self.job, confirm=True), outcome.confirm()):
            with self.subTest(sure=sure):
                self.assertTrue(sure.confirmed)
                self.assertFalse(sure.needs_confirmation)
                self.assertIsNone(sure.ensure_creatable())
                self.assertIn("des.platform_counter_slope", codes(sure))

    def test_the_untouchable_is_one_group_that_the_notices_place(self) -> None:
        """RF-015-13, RF-015-24: las 400 celdas de la huella que el intocable no deja cortar son un
        grupo por encima de la rasante (6 m, su centro) y suma a lo que las máscaras no mueven, junto
        con las del borde, en un grupo con su lugar; ninguna es «no corta» (se corta en 6.000)."""
        outcome = self.outcome
        self.assertEqual(outcome.applied.cut_cells, 6000)
        self.assertFalse(outcome.no_cut)
        (group,) = outcome.applied.above
        self.assertEqual((group.cells, group.area_m2), (400, 400.0))
        self.assertAlmostEqual(group.max_m, 6.0, delta=TOL)
        self.assertGreater(outcome.held_cells, 400)
        self.assertEqual(outcome.held_cells, 400 + outcome.edge.held_cells)
        (held,) = outcome.held_groups
        self.assertEqual((held.cells, held.footprint_cells, held.edge_cells),
                         (outcome.held_cells, 400, outcome.edge.held_cells))
        self.assertEqual(held.area_m2, float(held.cells))
        base_x, base_y = absolute(0.0, 0.0)
        self.assertAlmostEqual(held.y, base_y + 200.0, delta=TOL)  # simétrica de norte a sur
        self.assertAlmostEqual(held.x, base_x + 145.0, delta=0.5)

    def test_the_notices_come_in_a_stable_order(self) -> None:
        """RF-015-13, RF-015-23, RF-015-24: la contrapendiente, lo que queda por encima (el resumen
        y sus grupos), los avisos del borde tal cual los da y la nota de que no hay revisión
        anterior con la que comparar la magnitud."""
        outcome = self.outcome
        edge_codes = [item.code for item in outcome.edge.notices]
        self.assertTrue(edge_codes)
        self.assertEqual(codes(outcome), [
            "des.platform_counter_slope", "des.platform_above", "des.platform_above_group",
            *edge_codes, "des.magnitude_no_reference"])
        self.assertEqual(codes(outcome_of(self.job)), codes(outcome))
        edge_block = list(outcome.notices[3:3 + len(edge_codes)])
        self.assertEqual(edge_block, list(outcome.edge.notices))

    def test_one_group_and_two_groups_read_in_the_singular_and_the_plural(self) -> None:
        """RF-015-24 (trampa de la 014: ``Notice.text`` escribe los números antes de elegir el
        singular): «en 1 grupo» con la banda, «en 2 grupos» con una segunda, en español y en
        inglés."""
        one = next(item for item in self.outcome.notices if item.code == "des.platform_above")
        self.assertIn("en 1 grupo,", one.text("es"))
        self.assertIn("in 1 group,", one.text("en"))
        second = efx.strip_case(untouchable=True)
        allowed = second.cut_allowed & ~qfx.in_box((250.0, 170.0, 260.0, 230.0))
        outcome = outcome_of(strip_job(second, "cut_fill", cut_allowed=allowed))
        two = next(item for item in outcome.notices if item.code == "des.platform_above")
        self.assertEqual((two.values["groups"], two.values["area"]), (2, 800.0))
        self.assertIn("en 2 grupos,", two.text("es"))
        self.assertIn("in 2 groups,", two.text("en"))
        groups = [item for item in outcome.notices if item.code == "des.platform_above_group"]
        self.assertEqual([item.values["group"] for item in groups], [1, 2])
        self.assertEqual(outcome.profile.counter_sections, 20)

    def test_no_input_is_modified(self) -> None:
        """RF-015-23: ni el trabajo, ni la huella, ni la aplicada, ni el borde cambian."""
        job = strip_job(self.case, "cut_fill")
        footprint, applied, edge = calculate(job)
        before = [array.copy() for array in (job.start, footprint.levels, footprint.sigma,
                                             applied.surface, edge.surface)]
        platform.platform_outcome(job, footprint, applied, edge, PROJECT)
        after = (job.start, footprint.levels, footprint.sigma, applied.surface, edge.surface)
        for was, now in zip(before, after, strict=True):
            np.testing.assert_array_equal(now, was)


# --- El sentido en que baja la rasante ---------------------------------------------------------


class SenseOfTheGradeTest(unittest.TestCase):
    """RF-015-23 (A4): la contrapendiente se mide **en el sentido en que baja la rasante**: con una
    pendiente negativa, hacia las abscisas grandes; con una positiva, hacia las pequeñas."""

    def test_a_platform_that_falls_towards_the_east_rises_after_the_hollow_at_k_50(self) -> None:
        """RF-015-23: con − 1 % el foso (abscisas 30 a 50) hace que los tramos 50 a 79 suban
        ``5,495 − 0,01 (k + 0,5)`` m sobre ``94,505``; la peor, 4,99 m en la abscisa 50,5."""
        outcome = outcome_of(small_job(-1.0))
        profile = outcome.profile
        np.testing.assert_array_equal(np.flatnonzero(profile.flagged), np.arange(50, 80))
        expected = np.zeros(80)
        expected[50:] = 5.495 - 0.01 * (np.arange(50, 80) + 0.5)
        np.testing.assert_allclose(profile.rise_m, expected, rtol=0, atol=TOL)
        self.assertEqual(profile.worst, 50)
        self.assertAlmostEqual(float(profile.rise_m[50]), 4.99, delta=TOL)
        self.assertAlmostEqual(float(profile.chainage_m[50]), 50.5, delta=TOL)
        x, y = absolute(60.5, 19.5)
        self.assertAlmostEqual(float(profile.x[50]), x, delta=TOL)
        self.assertAlmostEqual(float(profile.y[50]), y, delta=TOL)

    def test_a_platform_that_falls_towards_the_west_rises_before_the_hollow_at_k_29(self) -> None:
        """RF-015-23: con + 1 % baja hacia el oeste y suben los tramos 0 a 29, ``4,695 + 0,01 (k +
        0,5)`` m sobre ``95,305``; la peor, 4,99 m en la abscisa 29,5."""
        outcome = outcome_of(small_job(1.0))
        profile = outcome.profile
        np.testing.assert_array_equal(np.flatnonzero(profile.flagged), np.arange(0, 30))
        expected = np.zeros(80)
        expected[:30] = 4.695 + 0.01 * (np.arange(30) + 0.5)
        np.testing.assert_allclose(profile.rise_m, expected, rtol=0, atol=TOL)
        self.assertEqual(profile.worst, 29)
        self.assertAlmostEqual(float(profile.rise_m[29]), 4.99, delta=TOL)
        self.assertAlmostEqual(float(profile.chainage_m[29]), 29.5, delta=TOL)

    def test_the_brute_force_agrees_with_the_two_senses(self) -> None:
        """RF-015-23: la cota de cada tramo y su contrapendiente salen igual que con una fuerza
        bruta tramo a tramo (el mínimo de los tramos aguas arriba, con un bucle) con las dos
        pendientes, a ≤ 10⁻⁹ m."""
        for gradient in (-1.0, 1.0, -0.25, 3.0):
            with self.subTest(gradient=gradient):
                profile = outcome_of(small_job(gradient)).profile
                levels = small_oracle(gradient)
                np.testing.assert_allclose(profile.level_m, levels, rtol=0, atol=TOL)
                np.testing.assert_allclose(profile.rise_m, rise_oracle(levels, gradient),
                                           rtol=0, atol=TOL)

    def test_a_downhill_that_never_rises_gives_no_counter_slope(self) -> None:
        """RF-015-23: si la plataforma rellena el foso (``cut_fill``) la rasante baja sin dientes:
        ni un tramo marcado, con las dos pendientes."""
        for gradient in (-1.0, 1.0):
            with self.subTest(gradient=gradient):
                outcome = outcome_of(small_job(gradient, mode="cut_fill"))
                self.assertFalse(outcome.profile.flagged.any())
                self.assertFalse(outcome.needs_confirmation)

    def test_the_tolerance_is_the_one_of_the_entity_and_defaults_to_0_1(self) -> None:
        """RF-015-23, D-8: ``counter_tol_m`` del trabajo manda (0,5 y 4,9 m: los 4,99 m siguen
        avisando; 5,0 m, no); sin él es 0,1 m (D-8); fuera de rango, el rechazo de la entidad."""
        for tolerance, warned in ((None, True), (0.5, True), (4.9, True), (5.0, False)):
            with self.subTest(tolerance=tolerance):
                values = {} if tolerance is None else {"counter_tol_m": tolerance}
                outcome = outcome_of(small_job(-1.0, **values))
                self.assertEqual(outcome.counter_slope, warned)
                self.assertEqual(outcome.profile.tolerance_m, 0.1 if tolerance is None else tolerance)
        with self.assertRaises(DesignError) as caught:
            outcome_of(small_job(-1.0, counter_tol_m=-0.1))
        self.assertEqual(caught.exception.code, "des.entity_param_range")

    def test_a_rise_within_the_tolerance_does_not_warn(self) -> None:
        """RF-015-23: un foso de 0,05 m (≤ 0,1 m) no avisa; uno de 0,2 m, sí."""
        for depth, warned in ((0.05, False), (0.2, True)):
            with self.subTest(depth=depth):
                outcome = outcome_of(small_job(-1.0, depth=depth))
                self.assertEqual(outcome.counter_slope, warned)


# --- Pendiente 0 % -----------------------------------------------------------------------------


class FlatPlatformTest(unittest.TestCase):
    """RF-015-23 (D-16): con pendiente 0 % la plataforma se admite y su contrapendiente es el máximo
    menos el mínimo del perfil."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.outcome = outcome_of(small_job(0.0))
        cls.profile = cls.outcome.profile

    def test_the_counter_slope_is_the_highest_minus_the_lowest_section(self) -> None:
        """RF-015-23: 100 m fuera del foso y 95 m en él: contrapendiente de 5 m (los 60 tramos fuera
        del foso suben 5 m sobre el mínimo del perfil), sin sentido: la cota, a ≤ 10⁻⁹ m."""
        profile = self.profile
        self.assertTrue(profile.flat)
        levels = small_oracle(0.0)
        np.testing.assert_allclose(profile.level_m, levels, rtol=0, atol=TOL)
        np.testing.assert_allclose(profile.rise_m, rise_oracle(levels, 0.0), rtol=0, atol=TOL)
        self.assertAlmostEqual(profile.spread_m, 5.0, delta=TOL)
        self.assertEqual(profile.counter_sections, 60)

    def test_the_notice_gives_the_range_and_the_first_highest_section(self) -> None:
        """RF-015-23: ``des.platform_counter_flat`` con la cuantía 5, las cotas 95 y 100, la
        tolerancia y el lugar del primer tramo más alto (abscisa 0,5 m, su celda más al norte)."""
        notice = next(item for item in self.outcome.notices
                      if item.code == "des.platform_counter_flat")
        x, y = rounded(10.5, 19.5)
        self.assertEqual(dict(notice.values), {
            "entity": "P1", "amount": 5.0, "low": 95.0, "high": 100.0, "tolerance": 0.1,
            "chainage": 0.5, "x": x, "y": y})
        self.assertNotIn("des.platform_counter_slope", codes(self.outcome))
        self.assertIn("0 %", notice.text("es"))
        self.assertTrue(self.outcome.needs_confirmation)

    def test_a_difference_exactly_the_tolerance_does_not_warn(self) -> None:
        """RF-015-23: «más que la tolerancia»: un perfil que varía exactamente 0,25 m (exacto en
        binario: 100 y 99,75) con una tolerancia de 0,25 m no avisa; con una de 0,125 m, sí."""
        for tolerance, warned in ((0.25, False), (0.125, True)):
            with self.subTest(tolerance=tolerance):
                outcome = outcome_of(small_job(0.0, depth=0.25, counter_tol_m=tolerance))
                self.assertEqual(outcome.profile.spread_m, 0.25)
                self.assertEqual(outcome.counter_slope, warned)

    def test_a_flat_profile_within_the_tolerance_is_admitted_without_notice(self) -> None:
        """RF-015-23, D-16: con 0,05 m de diferencia (≤ 0,1 m) no hay aviso; con 0,2 m, sí; y con
        la misma cota en todo el perfil, ninguno."""
        for depth, warned in ((0.05, False), (0.2, True), (0.0, False)):
            with self.subTest(depth=depth):
                outcome = outcome_of(small_job(0.0, depth=depth, above=0.0 if depth == 0.0 else 6.0))
                self.assertEqual(outcome.counter_slope, warned)
                self.assertEqual("des.platform_counter_flat" in codes(outcome), warned)


# --- Una plataforma que no corta ---------------------------------------------------------------


class NoCutTest(unittest.TestCase):
    """RF-015-24: si no baja ninguna celda, el aviso «la plataforma no corta» con su área."""

    def test_a_platform_under_the_terrain_in_cut_mode_does_not_cut(self) -> None:
        """RF-015-24, RF-015-20: con el terreno 2 m por debajo de la rasante y el modo «en corte», no
        baja ninguna celda: el aviso con su área (800 m²), y las 800 celdas, por debajo, en un
        grupo; sin borde."""
        job = small_job(1.0, depth=2.0, above=-2.0)
        outcome = outcome_of(job)
        self.assertTrue(outcome.no_cut)
        self.assertEqual((outcome.applied.cut_cells, outcome.applied.cut_m3), (0, 0.0))
        notice = next(item for item in outcome.notices if item.code == "des.platform_no_cut")
        self.assertEqual(dict(notice.values), {"entity": "P1", "area": 800.0})
        (below,) = outcome.applied.below
        self.assertEqual((below.cells, below.area_m2), (800, 800.0))
        self.assertAlmostEqual(below.max_m, 2.0, delta=TOL)
        self.assertEqual(codes(outcome)[:4], ["des.platform_no_cut", "des.platform_below",
                                              "des.platform_below_group",
                                              "des.magnitude_no_reference"])
        self.assertEqual(outcome.edge.notices, ())
        self.assertAlmostEqual(outcome.off_level_area_m2, 800.0, delta=TOL)
        self.assertAlmostEqual(outcome.off_level_max_m, 2.0, delta=TOL)
        self.assertFalse(outcome.needs_confirmation)

    def test_a_platform_the_masks_do_not_let_cut_does_not_cut_either(self) -> None:
        """RF-015-24, RF-015-13: con el corte no admitido en ninguna parte tampoco baja ninguna celda:
        el aviso, y las 800 celdas por encima de la rasante (6 m), en un grupo, que las máscaras no
        dejan cortar."""
        nothing = np.zeros((SMALL_ROWS, SMALL_COLS), dtype=bool)
        outcome = outcome_of(small_job(-1.0, depth=-6.0, cut_allowed=nothing))
        self.assertTrue(outcome.no_cut)
        self.assertEqual(codes(outcome), ["des.platform_no_cut", "des.platform_above",
                                          "des.platform_above_group", "des.magnitude_no_reference"])
        (above,) = outcome.applied.above
        self.assertEqual((above.cells, above.area_m2), (800, 800.0))
        self.assertAlmostEqual(above.max_m, 6.0, delta=TOL)
        self.assertAlmostEqual(outcome.off_level_area_m2, 800.0, delta=TOL)

    def test_a_platform_that_cuts_is_not_reported_as_not_cutting(self) -> None:
        """RF-015-24: con corte en alguna celda, ningún aviso de «no corta»."""
        self.assertNotIn("des.platform_no_cut", codes(outcome_of(small_job(-1.0))))

    def test_the_text_of_the_notice_is_in_both_languages(self) -> None:
        """RF-015-24: el aviso se lee en español y en inglés con el área."""
        outcome = outcome_of(small_job(1.0, depth=2.0, above=-2.0))
        notice = next(item for item in outcome.notices if item.code == "des.platform_no_cut")
        self.assertIn("no corta", notice.text("es"))
        self.assertIn("800", notice.text("es"))
        self.assertIn("does not cut", notice.text("en"))


# --- Las cifras --------------------------------------------------------------------------------


class FiguresTest(unittest.TestCase):
    """RF-015-24: el área, las longitudes, las cotas de los extremos, el corte y el relleno de la
    huella y del borde por separado y lo que no queda en la rasante, con su unidad y su ámbito, y sin
    NaN ni infinitos."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case()
        cls.cut = outcome_of(strip_job(cls.case, "cut"))
        cls.both = outcome_of(strip_job(cls.case, "cut_fill"))

    @staticmethod
    def value(outcome: Any, key: str) -> float | None:
        found = [item.value for item in outcome.figures if item.key == key]
        return found[0] if found else None

    def test_the_footprint_figures_are_the_hand_calculation(self) -> None:
        """RF-015-24, CE-015-02: 8.000 m² de área, eje de 200 m, huella medida de 199 m, cotas 230 y
        232 m en los extremos del eje, 38.400 m³ de corte (6 m en 6.400 celdas) y 0 m³ de relleno
        en «en corte»; en «en corte y relleno», 8.000 m³ de relleno más."""
        cut, both = self.cut, self.both
        expected = {"des.plat_area_m2": 8000.0, "des.plat_axis_m": 200.0,
                    "des.plat_footprint_m": 199.0, "des.plat_start_level_m": 230.0,
                    "des.plat_end_level_m": 232.0, "des.plat_cut_m3": 38_400.0,
                    "des.plat_fill_m3": 0.0}
        for key, wanted in expected.items():
            with self.subTest(key=key):
                found = self.value(cut, key)
                if wanted:
                    self.assertAlmostEqual(found / wanted, 1.0, delta=TOL)
                else:
                    self.assertEqual(found, 0.0)
        self.assertAlmostEqual(self.value(both, "des.plat_fill_m3") / 8000.0, 1.0, delta=TOL)
        self.assertAlmostEqual(self.value(both, "des.plat_cut_m3") / 38_400.0, 1.0, delta=TOL)

    def test_the_edge_figures_are_those_of_the_edge_apart_from_the_footprint(self) -> None:
        """RF-015-24, RF-015-22: el corte y el relleno del borde son los de ``Edge`` y no se suman a
        los de la huella; la altura máxima de su pared, la de ``Edge``."""
        for outcome in (self.cut, self.both):
            edge = outcome.edge
            self.assertEqual(self.value(outcome, "des.edge_cut_m3"), edge.cut_m3)
            self.assertEqual(self.value(outcome, "des.edge_fill_m3"), edge.fill_m3)
            self.assertEqual(self.value(outcome, "des.edge_wall_max_m"), edge.wall_max_m)
            self.assertEqual(self.value(outcome, "des.plat_cut_m3"), outcome.applied.cut_m3)
            self.assertGreater(edge.cut_m3, 0.0)
            self.assertAlmostEqual(outcome.total_cut_m3, outcome.applied.cut_m3 + edge.cut_m3,
                                   delta=1e-6)
            self.assertAlmostEqual(outcome.total_fill_m3, outcome.applied.fill_m3 + edge.fill_m3,
                                   delta=1e-6)

    def test_what_stays_off_the_grade_is_area_and_the_largest_gap(self) -> None:
        """RF-015-24: en «en corte», el tramo bajo la rasante (1.600 celdas, 1.600 m²) queda 5 m por
        debajo; en «en corte y relleno» no queda ninguna: 0 m² y sin diferencia máxima (la cifra no
        existe)."""
        self.assertAlmostEqual(self.value(self.cut, "des.plat_below_m2") / 1600.0, 1.0, delta=TOL)
        self.assertAlmostEqual(self.value(self.cut, "des.plat_below_max_m") / 5.0, 1.0, delta=TOL)
        self.assertEqual(self.value(self.both, "des.plat_below_m2"), 0.0)
        self.assertIsNone(self.value(self.both, "des.plat_below_max_m"))
        self.assertEqual(len(self.cut.figures), 12)
        self.assertEqual(len(self.both.figures), 11)

    def test_the_off_grade_figure_adds_what_the_masks_keep_above(self) -> None:
        """RF-015-24: con el intocable, a lo de por debajo (1.600 celdas, 5 m) se suma lo de por
        encima que no se corta (400 celdas, 6 m): 2.000 m² y 6 m (la figura cuenta todo lo que no
        queda en la rasante)."""
        outcome = outcome_of(strip_job(efx.strip_case(untouchable=True), "cut"))
        self.assertAlmostEqual(self.value(outcome, "des.plat_below_m2") / 2000.0, 1.0, delta=TOL)
        self.assertAlmostEqual(self.value(outcome, "des.plat_below_max_m") / 6.0, 1.0, delta=TOL)
        self.assertEqual(outcome.off_level_area_m2, 2000.0)

    def test_every_figure_has_its_unit_its_scope_and_a_finite_value(self) -> None:
        """RF-015-24: las cifras son CALCULADO, con la unidad que declara su definición, el ámbito
        de la entidad (el nombre y el código) y un valor finito, en el orden de la declaración."""
        declared = {item.key: item for item in provenance.PLATFORM_FIGURES}
        scope = provenance.entity_figure_scope("P1", "PLT-001")
        for outcome in (self.cut, self.both):
            keys = [item.key for item in outcome.figures]
            self.assertEqual(keys, [key for key in declared if key in keys])
            for figure in outcome.figures:
                with self.subTest(key=figure.key):
                    self.assertEqual(figure.unit, declared[figure.key].unit)
                    self.assertEqual(dict(figure.scope), scope)
                    self.assertEqual(figure.kind, params_core.ParamKind.CALCULADO)
                    self.assertTrue(math.isfinite(figure.value))

    def test_without_an_edge_there_is_no_wall_figure(self) -> None:
        """RF-015-24: sin ninguna semilla (el corte no admitido) no hay borde: 0 m³ y sin la cifra de
        la altura de la pared (no existe)."""
        nothing = np.zeros((SMALL_ROWS, SMALL_COLS), dtype=bool)
        outcome = outcome_of(small_job(-1.0, cut_allowed=nothing))
        self.assertEqual(self.value(outcome, "des.edge_cut_m3"), 0.0)
        self.assertIsNone(self.value(outcome, "des.edge_wall_max_m"))
        self.assertTrue(all(math.isfinite(item.value) for item in outcome.figures))

    def test_the_figures_of_a_negative_level_are_admitted(self) -> None:
        """RF-015-24: las cotas de la rasante pueden ser negativas (un nivel bajo el nivel del mar)."""
        grid = tilted_grid(SMALL_ROWS, SMALL_COLS)
        job = small_job(-1.0)
        shifted = platform.PlatformJob(
            job.request, job.code, grid, job.start - 130.0, job.geometry,
            {**job.values, "start_level_m": -30.0}, job.cut_allowed, job.fill_allowed)
        outcome = outcome_of(shifted)
        self.assertAlmostEqual(self.value(outcome, "des.plat_start_level_m"), -30.0, delta=TOL)
        self.assertAlmostEqual(self.value(outcome, "des.plat_end_level_m"), -30.8, delta=TOL)


# --- Los grupos de lo que no queda en la rasante ------------------------------------------------


class OffLevelNoticesTest(unittest.TestCase):
    """RF-015-24, RF-015-13: cada grupo de lo que no queda en la rasante, con su área, su diferencia
    máxima y su lugar; y cuando son las máscaras las que no dejan rellenar, su propio aviso."""

    def test_the_hollow_of_cut_mode_is_also_a_counter_slope_by_hand(self) -> None:
        """RF-015-23, B7: el foso que «en corte» no rellena (las abscisas 80 a 120, 5 m por debajo) hace
        que la rasante, que baja hacia el oeste (+ 1 %), suba al salir de él: ``4,195 + 0,01 (k + 0,5)``
        m sobre ``225,805`` en los tramos 0 a 79; la peor, 4,99 m en la abscisa 79,5."""
        profile = outcome_of(strip_job(efx.strip_case(), "cut")).profile
        np.testing.assert_array_equal(np.flatnonzero(profile.flagged), np.arange(0, 80))
        np.testing.assert_allclose(profile.rise_m[:80], 4.195 + 0.01 * (np.arange(80) + 0.5),
                                   rtol=0, atol=TOL)
        self.assertEqual(profile.worst, 79)
        self.assertAlmostEqual(float(profile.rise_m[79]), 4.99, delta=TOL)
        self.assertAlmostEqual(float(profile.chainage_m[79]), 79.5, delta=TOL)

    def test_the_hollow_of_cut_mode_is_one_group_with_its_centre(self) -> None:
        """RF-015-24: el tramo bajo la rasante de la franja en «en corte» es un grupo de 1.600 celdas,
        5 m y centro (200, 200) local, con el aviso ``des.platform_below`` y la nota de su grupo."""
        outcome = outcome_of(strip_job(efx.strip_case(), "cut"))
        self.assertEqual(codes(outcome)[:3], ["des.platform_counter_slope", "des.platform_below",
                                              "des.platform_below_group"])
        summary = outcome.notices[1]
        group = outcome.notices[2]
        self.assertEqual(dict(summary.values), {"entity": "P1", "area": 1600.0, "maximum": 5.0,
                                                "groups": 1})
        x, y = rounded(200.0, 200.0)
        self.assertEqual(dict(group.values), {"group": 1, "cells": 1600, "area": 1600.0,
                                              "maximum": 5.0, "x": x, "y": y})
        self.assertIn("en 1 grupo", summary.text("es"))
        self.assertIn(f"1{THIN}600 celdas", group.text("es"))

    def test_what_the_masks_do_not_let_fill_has_its_own_notice(self) -> None:
        """RF-015-13: en «en corte y relleno» con el relleno no admitido en el foso, las 1.600 celdas
        quedan por debajo porque las máscaras no dejan rellenar: ``des.platform_below_masks``, no el
        aviso del modo «en corte»."""
        case = efx.strip_case()
        nothing = np.zeros(case.grid.shape, dtype=bool)
        job = platform.PlatformJob(
            request(), "PLT-001", case.grid, case.terrain,
            platform.PlatformGeometry("line", ((case.axis,),)),
            {"width_m": case.width_m, "start_level_m": case.grade_start_m,
             "gradient_pct": case.slope_pct, "reach_m": 12.5, "edge_angle_deg": 40.0,
             "mode": "cut_fill"}, case.cut_allowed, nothing)
        outcome = outcome_of(job)
        self.assertEqual(outcome.applied.below[0].cause, platform.OffLevelCause.FILL_DENIED)
        self.assertIn("des.platform_below_masks", codes(outcome))
        self.assertNotIn("des.platform_below", codes(outcome))
        notice = next(item for item in outcome.notices if item.code == "des.platform_below_masks")
        self.assertEqual((notice.values["area"], notice.values["groups"]), (1600.0, 1))
        self.assertIn("máscaras", notice.text("es"))
        self.assertIn("masks", notice.text("en"))


# --- El orden de las dos superficies de una cantera ---------------------------------------------


class QuarryOrderTest(unittest.TestCase):
    """RF-015-14: una entidad aplicada a una de las dos superficies de una cantera de la 014 y que
    no cumple ``final ≤ explotación ≤ terreno`` frente a la otra (1 mm) avisa con el área y el lugar
    de lo que no lo cumple, y no impide crearla."""

    GRID = qfx.GRID
    TERRAIN = qfx.terrain()
    EXPLOITATION = TERRAIN - 10.0
    FINAL = TERRAIN - 25.0

    @classmethod
    def setUpClass(cls) -> None:
        quarry.check_order("Cantera", cls.FINAL, cls.EXPLOITATION, cls.TERRAIN, cls.GRID)

    def assertPlace(self, found: tuple[float, float], wanted: tuple[float, float]) -> None:
        """Dos lugares absolutos iguales a ≤ 10⁻⁹ m."""
        self.assertAlmostEqual(found[0], wanted[0], delta=TOL)
        self.assertAlmostEqual(found[1], wanted[1], delta=TOL)

    @classmethod
    def job(cls, start: np.ndarray, level: float, mode: str) -> Any:
        allowed = np.ones(cls.GRID.shape, dtype=bool)
        return platform.PlatformJob(
            request(), "PLT-001", cls.GRID, start, platform.PlatformGeometry(
                "polygon", ((cfx.rectangle(100.0, 100.0, 140.0, 140.0),),)),
            {"start_level_m": level, "gradient_pct": 0.0, "reach_m": 0.5, "edge_angle_deg": 40.0,
             "mode": mode}, allowed, allowed.copy())

    @classmethod
    def order(cls, side: Any) -> Any:
        final = side == "final"
        return platform.QuarryOrder(
            quarry="Cantera", side=side, surface="Final" if final else "Explotación",
            other_name="Explotación" if final else "Final",
            other=cls.EXPLOITATION if final else cls.FINAL)

    @classmethod
    def brute(cls, side: str, level: float) -> tuple[int, float, tuple[float, float]]:
        """Las celdas de la caja de (100, 100) a (140, 140) que incumplen, su mayor exceso y la
        primera (de norte a sur y de oeste a este), una a una y a mano."""
        count, largest, first = 0, 0.0, None
        for j in range(39, -1, -1):
            for i in range(40):
                x, y = 100.5 + i, 100.5 + j
                terrain = 180.0 + 0.25 * y + 0.0625 * x
                excess = level - (terrain - 10.0) if side == "final" else (terrain - 25.0) - level
                if excess > 0.001:
                    count += 1
                    largest = max(largest, excess)
                    first = first or (x, y)
        assert first is not None
        return count, largest, first

    def test_raising_the_final_above_the_exploitation_is_reported(self) -> None:
        """RF-015-14: una plataforma «en corte y relleno» a 215 m sobre la final sube 1.600 celdas
        por encima de la explotación (``215 − (terreno − 10)``), hasta 13,59375 m, la primera en la
        esquina noroeste (100,5; 139,5)."""
        job = self.job(self.FINAL, 215.0, "cut_fill")
        outcome = outcome_of(job, quarry=self.order("final"))
        breach = outcome.order
        self.assertEqual((breach.cells, breach.area_m2), (1600, 1600.0))
        self.assertAlmostEqual(breach.max_m, 13.59375, delta=TOL)
        self.assertPlace((breach.x, breach.y), absolute(100.5, 139.5))
        self.assertEqual(self.brute("final", 215.0)[:2], (1600, 13.59375))
        notice = next(item for item in outcome.notices if item.code == "des.entity_quarry_order")
        x, y = rounded(100.5, 139.5)
        self.assertEqual(dict(notice.values), {
            "entity": "P1", "surface": "Final", "quarry": "Cantera", "other": "Explotación",
            "cells": 1600, "area": 1600.0, "above": 13.594, "x": x, "y": y})
        self.assertIn("final ≤ explotación ≤ terreno", notice.text("es"))
        self.assertIn(f"1{THIN}600 celdas", notice.text("es"))

    def test_a_partial_breach_counts_only_the_cells_that_fail(self) -> None:
        """RF-015-14: a 213 m, solo incumplen las celdas con ``terreno < 222,999``: las que cuenta
        la fuerza bruta de a una; el máximo y la primera celda, también."""
        outcome = outcome_of(self.job(self.FINAL, 213.0, "cut_fill"), quarry=self.order("final"))
        cells, largest, first = self.brute("final", 213.0)
        self.assertTrue(0 < cells < 1600)
        self.assertEqual(outcome.order.cells, cells)
        self.assertEqual(outcome.order.area_m2, float(cells))
        self.assertAlmostEqual(outcome.order.max_m, largest, delta=TOL)
        self.assertPlace((outcome.order.x, outcome.order.y), absolute(*first))

    def test_lowering_the_exploitation_under_the_final_is_reported(self) -> None:
        """RF-015-14: una plataforma «en corte» a 190 m sobre la explotación la baja por debajo de la
        final donde ésta pasa de 190,001: hasta 8,59375 m, la primera en (100,5; 139,5)."""
        outcome = outcome_of(self.job(self.EXPLOITATION, 190.0, "cut"),
                             quarry=self.order("exploitation"))
        cells, largest, first = self.brute("exploitation", 190.0)
        self.assertEqual(outcome.order.cells, cells)
        self.assertAlmostEqual(outcome.order.max_m, 8.59375, delta=TOL)
        self.assertAlmostEqual(outcome.order.max_m, largest, delta=TOL)
        self.assertPlace((outcome.order.x, outcome.order.y), absolute(*first))
        self.assertEqual(outcome.order.side, model.Surface.EXPLOITATION)

    def test_an_entity_that_keeps_the_order_is_not_reported(self) -> None:
        """RF-015-14: una plataforma «en corte» sobre la final solo la baja: se cumple (``final ≤
        explotación``) y ni el dato ni el aviso aparecen."""
        outcome = outcome_of(self.job(self.FINAL, 190.0, "cut"), quarry=self.order("final"))
        self.assertIsNone(outcome.order)
        self.assertNotIn("des.entity_quarry_order", codes(outcome))

    def test_without_the_other_surface_nothing_is_checked(self) -> None:
        """RF-015-14: sin la otra superficie (una entidad que no parte de una cantera), ni dato ni
        aviso."""
        outcome = outcome_of(self.job(self.FINAL, 215.0, "cut_fill"))
        self.assertIsNone(outcome.order)
        self.assertNotIn("des.entity_quarry_order", codes(outcome))

    def test_the_breach_warns_but_does_not_prevent_creating_it(self) -> None:
        """RF-015-14: el aviso no pide confirmación ni impide crear (a diferencia de la
        contrapendiente)."""
        outcome = outcome_of(self.job(self.FINAL, 215.0, "cut_fill"), quarry=self.order("final"))
        self.assertIsNotNone(outcome.order)
        self.assertFalse(outcome.needs_confirmation)
        self.assertIsNone(outcome.ensure_creatable())

    def test_the_order_check_alone_uses_the_tolerance_of_1_mm(self) -> None:
        """RF-015-14, RF-014-14: con la función suelta, 0,5 mm por encima de la explotación cumple y
        2 mm, no (100 celdas); con otra tolerancia, la suya; con una ventana, solo mira la ventana;
        una celda sin dato no incumple."""
        result = self.FINAL.copy()
        patch = (slice(100, 110), slice(100, 110))
        result[patch] = self.EXPLOITATION[patch] + 0.0005
        self.assertIsNone(platform.order_check(result, self.EXPLOITATION, "final", self.GRID))
        result[patch] = self.EXPLOITATION[patch] + 0.002
        found = platform.order_check(result, self.EXPLOITATION, "final", self.GRID)
        self.assertEqual((found.cells, found.area_m2), (100, 100.0))
        self.assertAlmostEqual(found.max_m, 0.002, delta=TOL)
        self.assertPlace((found.x, found.y), (self.GRID.west + 100.5, self.GRID.north - 100.5))
        self.assertIsNone(platform.order_check(result, self.EXPLOITATION, "final", self.GRID,
                                               tolerance_m=0.003))
        window = (slice(95, 105), slice(95, 105))
        part = platform.order_check(result[window], self.EXPLOITATION, "final", self.GRID, window)
        self.assertEqual(part.cells, 25)
        result[patch] = np.nan
        self.assertIsNone(platform.order_check(result, self.EXPLOITATION, "final", self.GRID))

    def test_the_inputs_of_the_check_are_validated(self) -> None:
        """Una superficie de otra forma que la rejilla, o un lado que no es de la cantera, son errores
        del programa."""
        with self.assertRaises(ValueError):
            platform.order_check(self.FINAL, self.EXPLOITATION[:10], "final", self.GRID)
        with self.assertRaises(ValueError):
            platform.order_check(self.FINAL, self.EXPLOITATION, "sur", self.GRID)
        with self.assertRaises(ValueError):
            platform.order_check(self.FINAL[:10], self.EXPLOITATION, "final", self.GRID)


# --- La magnitud y las entradas -----------------------------------------------------------------


class MagnitudeAndInputsTest(unittest.TestCase):
    """RF-015-13: el aviso de magnitud con el desmonte de la huella y del borde juntos; las entradas
    que no casan son errores del programa."""

    def test_the_magnitude_compares_the_cut_of_the_footprint_and_the_edge(self) -> None:
        """RF-015-13: con 1.000 m³ de desmonte en la revisión anterior, el de la plataforma (huella y
        borde) la pasa más de 2 veces: ``des.magnitude_cut`` con el desmonte redondeado; con 10⁶ m³,
        no; y sin revisión anterior, la nota de que no hay referencia."""
        job = small_job(-1.0)
        footprint, applied, edge = calculate(job)
        total = applied.cut_m3 + edge.cut_m3
        before = design_report.Previous("Plataforma P1", "R01", 1000.0, 0.0)
        outcome = platform.platform_outcome(job, footprint, applied, edge, PROJECT, previous=before,
                                            operation="Plataforma P1")
        notice = next(item for item in outcome.notices if item.code == "des.magnitude_cut")
        self.assertEqual(notice.values["current"], round(total))
        self.assertEqual(notice.values["previous"], 1000)
        far = design_report.Previous("Plataforma P1", "R01", 1.0e6, 0.0)
        quiet = platform.platform_outcome(job, footprint, applied, edge, PROJECT, previous=far)
        self.assertFalse([item for item in quiet.notices if item.code.startswith("des.magnitude")])
        none = platform.platform_outcome(job, footprint, applied, edge, PROJECT,
                                         operation="Plataforma P1")
        self.assertEqual([item.code for item in none.notices
                          if item.code.startswith("des.magnitude")],
                         ["des.magnitude_no_reference"])

    def test_the_magnitude_ratio_of_the_project_is_required_and_checked(self) -> None:
        """Un proyecto sin ``des.warning.magnitude_ratio``, o con uno que no pasa de 1, es un error del
        programa (``ValueError``, como los demás parámetros del proyecto)."""
        job = small_job(-1.0)
        footprint, applied, edge = calculate(job)
        missing = {key: value for key, value in PROJECT.items() if key != params.WARNING_RATIO}
        with self.assertRaises(ValueError):
            platform.platform_outcome(job, footprint, applied, edge, missing)
        for ratio in (0.5, 1.0, math.nan):
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                platform.platform_outcome(job, footprint, applied, edge,
                                          {**PROJECT, params.WARNING_RATIO: ratio})

    def test_pieces_of_other_windows_are_programme_errors(self) -> None:
        """Una aplicada o un borde de otra ventana que la huella, y una huella de otro trabajo, son
        errores del programa."""
        job = small_job(-1.0)
        footprint, applied, edge = calculate(job)
        shifted = dataclasses.replace(applied, window=(slice(0, 5), slice(0, 5)))
        with self.assertRaises(ValueError):
            platform.platform_outcome(job, footprint, shifted, edge, PROJECT)
        other = dataclasses.replace(edge, window=(slice(0, 5), slice(0, 5)))
        with self.assertRaises(ValueError):
            platform.platform_outcome(job, footprint, applied, other, PROJECT)
        with self.assertRaises(ValueError):
            platform.platform_profile(job, footprint, np.zeros((3, 3)))

    def test_the_cells_must_be_square_for_the_profile(self) -> None:
        """ADR-0014: la abscisa por tramos de una celda supone celdas cuadradas: otra cosa es un error
        del programa."""
        job = small_job(-1.0)
        footprint = platform.platform_footprint(job)
        applied = platform.apply_platform(job, footprint)
        flat_grid = gis.Grid(job.grid.west, job.grid.north, 1.0, 2.0, job.grid.ncols, job.grid.nrows)
        bad = platform.PlatformJob(job.request, job.code, flat_grid, job.start, job.geometry,
                                   job.values, job.cut_allowed, job.fill_allowed)
        with self.assertRaises(ValueError):
            platform.platform_profile(bad, footprint, applied.surface)


if __name__ == "__main__":
    unittest.main()
