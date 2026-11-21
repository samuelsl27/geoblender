# SPDX-License-Identifier: GPL-3.0-or-later
"""Calcular la pista por pasos: la orquestación por modos, las cifras de RF-017-23 y el ``RoadOutcome`` (spec 017, T20 (a); HU-017-1 y HU-017-2; RF-017-23, 17, 22, 12, 05 (b), 06, 14 y 16;
RF-015-03, RF-015-09, RF-015-13 y RF-015-29; RNF-017-04, 06 y 07; plan 017 §5.3.2, §5.4 A0, §5.7 P-4 y P-14 y §5.8 H-10).

``road_store.road_compute_steps(job, common, ...)`` es el cálculo que comparten «Calcular», el recálculo y la reproducción: encadena, por modo (P-14), la red 2D desde el destino y desde el origen y el
pasillo, la ruta 3D con su presupuesto (solo «trazar»), el eje con curvas, la rasante, la ventana de trabajo (A0), la sección y el grabado, **sin proyecto y sin escribir nada**, por pasos de ≤ 0,05 s con
su progreso y cancelable. Lo que se comprueba aquí es **la orquestación**: que da lo que dan las piezas de la T06 a la T13 compuestas a mano (``tests/referencia/des/test_ref_roads.compose``: el hito H1, que
contrasta cada pieza con el cálculo a mano en las mismas celdas), las veintitrés cifras con sus valores de a mano de CE-017-01, CE-017-02 y CE-017-03, los rechazos como ``DesignError`` de la persona
(RF-012, RF-014, RF-016, RF-015-09), los avisos que añade (la media por encima de pm, RF-017-05 (b), la magnitud) y que cerrar a mitad no deja nada ni toca ninguna entrada.

Todo en la rejilla de 2 m de la cantera sintética (200 × 200 celdas; ``rd.grid_of(2.0)``): un cálculo cuesta ≈ 0,1 s. La ``Calculation`` (``road_run``), las confirmaciones y el resumen son de la
T20b (parte (b) de ``test_road_operation``); la pista de E1 y la rampa a una cota, con la cantera y la malla de 4 m, van a ``milestone_road_operation``.
"""

from __future__ import annotations

import dataclasses
import time
import unittest
from collections.abc import Iterator
from typing import Any
from unittest import mock

import numpy as np

from tests.referencia.des import test_ref_roads as h1
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_no_route import strip_case

messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
platform = import_geoblender("design.platform")
provenance = import_geoblender("design.provenance")
report = import_geoblender("design.report")
road_engrave = import_geoblender("design.road_engrave")
road_gradient = import_geoblender("design.road_gradient")
road_model = import_geoblender("design.road_model")
road_net = import_geoblender("design.road_net")
road_store = import_geoblender("design.road_store")

TOL = 1e-9
GRID = rd.grid_of(2.0)
"""La rejilla de la cantera con celdas de 2 m (200 × 200): la malla de la ruta de 4 m son bloques de 2 × 2 celdas."""
COMMON = {**h1.PROJECT, params.WARNING_RATIO: 1.5}
"""Los parámetros del proyecto que lee el cálculo (``provenance.PLATFORM_COMMON_PARAMS``: valores de la prueba, no de un proyecto): los cuatro del borde de la ``test_ref_roads`` y el umbral de la magnitud."""
ENTITY = h1.ENTITY


def last(work: Iterator[Any]) -> Any:
    """Lo que **devuelve** unos pasos (``yield from``)."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


def run(job: Any, **kwargs: Any) -> tuple[list[Any], Any, float]:
    """Los pasos que da ``road_compute_steps``, el ``RoadOutcome`` y lo más que tardó una llamada del hilo (s)."""
    work = road_store.road_compute_steps(job, kwargs.pop("common", COMMON), **kwargs)
    steps: list[Any] = []
    slowest = 0.0
    while True:
        started = time.perf_counter()
        try:
            steps.append(next(work))
        except StopIteration as done:
            slowest = max(slowest, time.perf_counter() - started)
            return steps, done.value, slowest
        slowest = max(slowest, time.perf_counter() - started)


def values_of(outcome: Any) -> dict[str, float]:
    """Las cifras de un resultado por su clave."""
    return {figure.key: figure.value for figure in outcome.figures}


def check_figures(test: unittest.TestCase, outcome: Any, road: Any) -> None:
    """Las cifras de ``outcome`` son las de la composición a mano ``road`` (las que existen), ≤ 10⁻⁹ relativo."""
    found = values_of(outcome)
    expected = {key: value for key, value in road.figures().items() if value is not None}
    test.assertEqual(set(found), set(expected))
    for key, value in expected.items():
        test.assertAlmostEqual(found[key], value, delta=TOL * max(1.0, abs(value)), msg=key)


def ramp_job(cross_pct: float = rd.RAMP_CROSS_PCT, shoulder_m: float = 1.5, **changes: Any) -> Any:
    """La pista «trazar» de 200 m de CE-017-01 (pd = 8 %) sobre el plano del 4 % con ``cross_pct`` % transversal y el arcén ``shoulder_m``: el trabajo de ``h1.ramp`` en la rejilla de 2 m."""
    origin, destination = (tuple(float(v) for v in rd.absolute([point], GRID)[0]) for point in (rd.RAMP_ORIGIN, rd.RAMP_DESTINATION))
    return rd.route_job(GRID, rd.ramp_terrain(GRID, cross_pct=cross_pct), origin, destination, route=rd.ROUTE, profile=dataclasses.replace(h1.PD8, shoulder_m=shoulder_m), **changes)


def axis_job(points: Any, *, terrain: np.ndarray | None = None, profile: rd.ProfileData = h1.SHORT, **changes: Any) -> Any:
    """Una pista «sobre un eje» en la rejilla de 2 m: la línea ``points`` (locales) sobre el plano del 4 % o el ``terrain`` que se dé."""
    return rd.axis_job(GRID, rd.ramp_terrain(GRID) if terrain is None else terrain, rd.absolute(points, GRID), profile=profile, **changes)


def line_of_ramp() -> Any:
    """La línea recta de la rampa de CE-017-01 (de (100, 200) a (300, 200) locales), que es el eje de las pistas «sobre un eje» de abajo."""
    return (rd.RAMP_ORIGIN, rd.RAMP_DESTINATION)


def digest_of(job: Any) -> str:
    """El hash de los arrays de entrada de un trabajo (principio 7: no se modifican)."""
    arrays = [job.start, job.cut_allowed, job.fill_allowed, job.untouchable]
    if job.avoid_weight is not None:
        arrays.append(job.avoid_weight)
    if job.geometry.line is not None:
        arrays.append(job.geometry.line)
    return h1.digest(*arrays)


class TraceTest(unittest.TestCase):
    """«Trazar»: de la ruta al grabado, A1 a A9 (P-14)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = ramp_job()
        cls.before = digest_of(cls.job)
        cls.road = h1.compose(cls.job)
        cls.steps, cls.outcome, _ = run(cls.job)
        cls.fine, cls.fine_outcome, _ = run(cls.job, budget_s=1e-9)

    def test_a_it_is_what_the_pieces_do_by_hand_and_the_inputs_are_not_modified(self) -> None:
        """RF-017-23, RF-017-09 a 11, 13, 15, 20, 21, RF-015-29, principio 7: el resultado es el de las piezas compuestas a mano (la ruta, el eje, la rasante, la sección y el grabado de la ``h1.compose``): la
        ventana de trabajo, la superficie, la huella, el eje, la rasante en sus estaciones y el terreno bajo ellas, bit a bit; y ni la superficie de partida ni las máscaras cambian."""
        outcome, road = self.outcome, self.road
        self.assertIsInstance(outcome, road_model.RoadOutcome)
        self.assertEqual((outcome.name, outcome.code, outcome.mode), (ENTITY, "RDW-001", road_model.RoadMode.TRACE))
        self.assertEqual(outcome.window, road.window)
        np.testing.assert_array_equal(outcome.surface, road.found.surface)
        np.testing.assert_array_equal(outcome.footprint, road.found.footprint)
        np.testing.assert_array_equal(outcome.axis.points, road.axis.points)
        np.testing.assert_array_equal(outcome.axis.stations, road.axis.stations)
        np.testing.assert_array_equal(outcome.levels, road.z)
        np.testing.assert_array_equal(outcome.terrain, road.terrain)
        self.assertEqual(digest_of(self.job), self.before)
        shape = tuple(part.stop - part.start for part in outcome.window)
        self.assertEqual((outcome.surface.shape, outcome.footprint.shape), (shape, shape))
        self.assertLess(shape[0] * shape[1], GRID.nrows * GRID.ncols)  # una ventana de trabajo, no la rejilla entera

    def test_b_the_figures_are_the_hand_figures_of_the_composition_with_their_unit_kind_and_scope(self) -> None:
        """RF-017-23, RF-008-30: las cifras son CALCULADO, con unidad, y de su pista (su ámbito: la entidad ``RDW-001``): las veintitrés de la composición a mano —las del eje y la rasante y las del grabado
        (corte y relleno de la sección y del borde por separado y el neto, la pared, las alturas máximas)—, menos las que no existen (una recta no tiene radio mínimo), en el orden de ``ROAD_FIGURES``."""
        found = values_of(self.outcome)
        check_figures(self, self.outcome, self.road)
        self.assertEqual([figure.key for figure in self.outcome.figures], [figure.key for figure in provenance.ROAD_FIGURES if figure.key in found])
        for figure in self.outcome.figures:
            self.assertEqual(str(figure.kind), "CALCULADO", figure.key)
            self.assertEqual(figure.scope[provenance.ENTITY_SCOPE_KEY], "RDW-001")
        self.assertEqual(found["des.road_curves"], 0)
        self.assertNotIn("des.road_radius_min_m", found)
        self.assertAlmostEqual(found["des.road_net_m3"], found["des.road_cut_m3"] + found["des.road_edge_cut_m3"] - found["des.road_fill_m3"] - found["des.road_edge_fill_m3"], delta=1e-6)

    def test_c_ce_017_01_the_straight_ramp_is_200_m_at_4_percent_with_the_hand_widths(self) -> None:
        """RF-017-23, CE-017-01: sobre el plano del 4 % sin pendiente transversal y con pd = 8 %, la pista de 200 m mide 200,000 m, baja de la cota 104 a la 112 (desnivel 8,000 m), su pendiente media y
        su máxima son del 4,000 % (la rasante es el terreno: **movimiento 0 m**: ni corte ni relleno ni borde), la calzada es f·A = 10,5 m y la sección, con el caballón de 1 m, 11,5 m."""
        found = values_of(last(road_store.road_compute_steps(ramp_job(0.0, 0.0), COMMON)))
        self.assertAlmostEqual(found["des.road_length_m"], rd.RAMP_LENGTH_M, delta=TOL)
        self.assertAlmostEqual(found["des.road_z_start_m"], 104.0, delta=TOL)
        self.assertAlmostEqual(found["des.road_z_end_m"], 112.0, delta=TOL)
        self.assertAlmostEqual(found["des.road_drop_m"], rd.RAMP_DROP_M, delta=TOL)
        self.assertAlmostEqual(found["des.road_gradient_mean_pct"], 4.0, delta=TOL * 100.0)
        self.assertAlmostEqual(found["des.road_gradient_max_pct"], 4.0, delta=TOL * 100.0)
        self.assertEqual((found["des.road_width_m"], found["des.road_section_m"]), (10.5, 11.5))
        for key in ("des.road_cut_m3", "des.road_fill_m3", "des.road_edge_cut_m3", "des.road_edge_fill_m3", "des.road_net_m3"):
            self.assertAlmostEqual(found[key], 0.0, delta=1e-6, msg=key)
        self.assertGreaterEqual(found["des.road_gradient_max_station_m"], 0.0)
        self.assertLess(found["des.road_gradient_max_station_m"], found["des.road_length_m"])

    def test_g_the_ramp_to_a_level_ends_in_its_zone_at_the_requested_level(self) -> None:
        """RF-017-02, RF-017-10, D-4, E4: con un destino por cota (110 m en una zona de 20 × 20 m y tolerancia 0,5 m) la ruta termina en un nodo de la zona, la rasante acaba en la cota pedida
        (``des.road_z_end_m`` = 110 m: la cota de fin es la pedida), el eje acaba en el centro del nodo de llegada y el resultado dice el destino alcanzado y que cabe en la tolerancia."""
        ring = rd.absolute([(240.0, 190.0), (260.0, 190.0), (260.0, 210.0), (240.0, 210.0)], GRID)
        origin = tuple(float(v) for v in rd.absolute([rd.RAMP_ORIGIN], GRID)[0])
        job = rd.route_job(GRID, rd.ramp_terrain(GRID), origin, road_model.LevelDestination(110.0, 0.5, ((ring,),)), route=rd.ROUTE, profile=h1.PD8)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        arrival = outcome.route.arrival
        self.assertEqual(values_of(outcome)["des.road_z_end_m"], 110.0)
        self.assertEqual((arrival.requested_m, arrival.within_tolerance), (110.0, True))
        west, south = rd.origin_of(GRID)
        self.assertTrue(240.0 <= arrival.x - west <= 260.0 and 190.0 <= arrival.y - south <= 210.0)
        np.testing.assert_array_equal(outcome.axis.points[-1], (arrival.x, arrival.y))

    def test_d_the_progress_is_by_phases_in_order_and_the_budget_does_not_change_the_result(self) -> None:
        """RF-017-30, RF-015-29, RF-015-02 (progreso y cancelación; D-23): con un presupuesto mínimo (cada unidad, un paso) los pasos son ``Progress`` de las fases de la red 2D, la ruta 3D, la sección y el
        grabado en ese orden, con ``done`` ≤ ``total``, un mensaje en español con el nombre de la pista y ningún ``result`` en ellos (lo que se devuelve es el valor de ``StopIteration``, como
        ``platform_compute_steps``); el del presupuesto por defecto da menos pasos y **el mismo resultado bit a bit** (la superficie, la huella, el eje, la rasante y las cifras)."""
        steps = self.fine
        self.assertLess(len(self.steps), len(steps))
        phases = [step.phase for step in steps]
        order = list(dict.fromkeys(phases))
        self.assertEqual(order, [road_store.COMPUTE_PHASE, "road_net", "road_route", "road_section", "road_engrave"])
        self.assertEqual([phases.index(phase) for phase in order], sorted(phases.index(phase) for phase in order))
        self.assertTrue(all(0 <= step.done <= step.total for step in steps))
        self.assertIn(f"«{ENTITY}»", steps[0].message)
        self.assertTrue(all(step.result is None for step in steps))
        self.assertIn(road_store.COMPUTE_PHASE, {step.phase for step in self.steps})
        again, outcome = self.fine_outcome, self.outcome
        self.assertEqual(again.surface.tobytes(), outcome.surface.tobytes())
        self.assertEqual(again.footprint.tobytes(), outcome.footprint.tobytes())
        self.assertEqual((again.axis.points.tobytes(), again.levels.tobytes()), (outcome.axis.points.tobytes(), outcome.levels.tobytes()))
        self.assertEqual(again.figures, outcome.figures)

    def test_e_the_outcome_says_the_corridor_the_search_and_names_itself(self) -> None:
        """RF-017-10, RF-017-12, H-10, RF-015-02: el resultado lleva **la holgura del pasillo** y los nodos que tiene (la ruta cambia con ella), la malla, los estados expandidos y el presupuesto (los de la
        búsqueda) y la cota inferior de la red 2D; ``message`` lo dice en español (la pista, su código, el eje y el corte y el relleno de la sección y del borde juntos); ``compose`` da la superficie entera con
        la ventana cambiada y el resto igual a la de partida, sin modificarla."""
        outcome, job = self.outcome, self.job
        route = outcome.route
        self.assertEqual((route.margin_m, route.mesh_m, route.budget), (job.route.margin_m, job.route.mesh_m, job.route.search_budget))
        corridor = rd.route_corridor(job)[1]  # el pasillo como lo arma la composición a mano (``h1.compose``), con la holgura de la ruta
        self.assertEqual((route.corridor_nodes, route.lower_bound_m), (corridor.nodes, corridor.lower_bound_m))
        self.assertGreater(route.expanded, 0)
        self.assertLessEqual(route.expanded, route.budget)
        self.assertGreaterEqual(route.nodes, 2)
        self.assertLessEqual(route.lower_bound_m, outcome.axis.length_m * 1.03 + route.mesh_m)  # la cota inferior es de la malla: no pasa de la longitud del eje más lo que cabe de malla
        self.assertGreaterEqual(route.lower_bound_m, outcome.axis.length_m - 2.0 * route.mesh_m)
        self.assertIn(f"«{ENTITY}»", outcome.message)
        self.assertIn("RDW-001", outcome.message)
        whole = outcome.compose(job.start)
        self.assertEqual(whole.shape, job.start.shape)
        np.testing.assert_array_equal(whole[outcome.window], outcome.surface)
        outside = np.ones(job.start.shape, dtype=bool)
        outside[outcome.window] = False
        np.testing.assert_array_equal(whole[outside], job.start[outside])
        self.assertEqual(digest_of(job), self.before)
        self.assertIsNot(whole, job.start)

    def test_f_the_engraved_data_the_summary_needs_are_in_the_outcome(self) -> None:
        """RF-017-22, RF-015-13: el resultado lleva el grabado entero (``engraved``: las celdas que las máscaras no dejan cortar ni rellenar, lo que el borde no mueve, los grupos de la calzada que no
        queda en su rasante y la pared) para que el resumen (T20b) los nombre con su restricción, y sus avisos propios (la pared del borde, lo que llega al borde de la rejilla, el salto creado)."""
        found = self.outcome.engraved
        self.assertIsInstance(found, road_engrave.Engraved)
        self.assertEqual(found.footprint_cells, int(self.outcome.footprint.sum()))
        self.assertEqual(self.outcome.off_level, found.off_level)
        self.assertEqual(self.outcome.off_level, ())
        codes = {notice.code for notice in self.outcome.notices}
        self.assertTrue({"des.magnitude_no_reference"} <= codes)
        self.assertTrue({notice.code for notice in found.notices} <= codes)


class ModesTest(unittest.TestCase):
    """«Sobre un eje» (A4 a A9) y «eje 3D» (la comprobación de A5 y A6 a A9; P-14): cada modo da sus cifras."""

    def test_a_on_axis_the_corner_of_ce_017_02_gives_the_analytic_length_and_one_curve(self) -> None:
        """RF-017-13, RF-017-23, CE-017-02, P-14: «sobre un eje» con las dos rectas de 40 m y R = 20 m da un eje de 40 + 31,416 + 40 − 2·20 = 71,4159 m con **una** curva de radio 20 m (las cifras salen del
        eje formado, sin ruta: ``route`` es ``None``), sin avisos del radio, y es la composición a mano; la línea dibujada no se modifica."""
        job = axis_job(rd.CORNER_LONG)
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        road = h1.compose(job)
        found = values_of(outcome)
        self.assertEqual(outcome.mode, road_model.RoadMode.ON_AXIS)
        self.assertAlmostEqual(found["des.road_length_m"], 40.0 + 40.0 - 2.0 * 20.0 + np.pi * 20.0 / 2.0, delta=TOL)
        self.assertEqual((found["des.road_curves"], found["des.road_radius_min_m"]), (1, 20.0))
        self.assertIsNone(outcome.route)
        self.assertEqual([notice.code for notice in outcome.notices if notice.code == "des.road_radius_reduced"], [])
        np.testing.assert_array_equal(outcome.surface, road.found.surface)
        check_figures(self, outcome, road)
        self.assertEqual(digest_of(job), before)

    def test_b_the_radius_that_does_not_fit_is_reduced_with_its_notice_in_the_outcome(self) -> None:
        """RF-017-14: con tramos de 15 m el radio baja a 15 m y el resultado lleva el aviso ``des.road_radius_reduced`` (el vértice, el radio pedido y el que cabe), **el primero** de sus avisos; la cadena sigue."""
        outcome = last(road_store.road_compute_steps(axis_job(rd.CORNER_SHORT), COMMON))
        self.assertEqual(outcome.notices[0].code, "des.road_radius_reduced")
        self.assertAlmostEqual(outcome.notices[0].values["fitted"], 15.0, delta=TOL)
        self.assertAlmostEqual(values_of(outcome)["des.road_radius_min_m"], 15.0, delta=TOL)

    def test_c_axis_3d_the_z_of_the_line_is_the_gradient_line_it_is_checked_and_never_corrected(self) -> None:
        """RF-017-18, RF-017-23, CE-017-03, P-14: en «eje 3D» la Z de la línea **es** la rasante (``gradient_line`` no se llama), se comprueba (un aviso por tramo entre estaciones que pasa de pd —12 % y
        15 % frente al 10 %— y el de la media, 7,2 % frente a pm = 5 %), **la línea no cambia** (hash antes y después) y se graba: las cifras son las de la composición a mano."""
        job = h1.axis_3d_job(GRID, rd.ramp_terrain(GRID), rd.axis_3d_irregular(), profile=rd.profile_with(reach_m=12.5, max_mean_gradient_pct=5.0))
        before = digest_of(job)
        with mock.patch.object(road_gradient, "gradient_line", side_effect=AssertionError("en «eje 3D» la Z es la rasante: no se recalcula")):
            outcome = last(road_store.road_compute_steps(job, COMMON))
        road = h1.compose(job)
        self.assertEqual(outcome.mode, road_model.RoadMode.AXIS_3D)
        np.testing.assert_array_equal(outcome.levels, road.z)
        np.testing.assert_allclose(outcome.levels, 104.0 + np.interp(outcome.axis.stations, 20.0 * np.arange(11), np.concatenate(([0.0], np.cumsum(rd.AXIS_3D_INCREMENTS_M)))), rtol=0.0, atol=TOL)
        codes = [notice.code for notice in outcome.notices]
        self.assertEqual(codes[:41], ["des.road_axis3d_gradient"] * 40 + ["des.road_mean_gradient"])
        self.assertTrue(outcome.mean_exceeded)
        self.assertEqual(digest_of(job), before)
        np.testing.assert_array_equal(job.geometry.line, rd.axis_3d_irregular())
        check_figures(self, outcome, road)

    def test_c2_a_3d_corner_below_the_minimum_radius_is_a_notice_and_never_a_rejection(self) -> None:
        """RF-017-18, RF-017-14: una línea 3D con una esquina de tramos de 15 m y Rmín = 16 m **no se rechaza** (es una entrada: el radio es un aviso, ``des.road_axis3d_radius``, con el radio que cabe, 15 m);
        con el mismo perfil, «sobre un eje» sí la rechaza. La línea no cambia."""
        planar = rd.absolute(rd.CORNER_SHORT, GRID)
        line = np.column_stack([planar, 140.0 + 0.04 * np.array([0.0, 15.0, 30.0])])
        profile = rd.profile_with(reach_m=12.5, min_radius_m=16.0)
        job = h1.axis_3d_job(GRID, rd.ramp_terrain(GRID), line, profile=profile)
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        radius = [notice for notice in outcome.notices if notice.code == "des.road_axis3d_radius"]
        self.assertEqual(len(radius), 1)
        self.assertAlmostEqual(radius[0].values["radius"], 15.0, delta=TOL)
        self.assertEqual(digest_of(job), before)
        with self.assertRaises(messages.DesignError) as caught:
            last(road_store.road_compute_steps(axis_job(rd.CORNER_SHORT, profile=profile), COMMON))
        self.assertEqual(caught.exception.code, "des.road_radius_below_min")

    def test_d_the_mean_gradient_over_pm_is_a_notice_with_its_steepest_stretches_and_a_flag(self) -> None:
        """RF-017-17, CE-017-03: la media de la rampa del escalón (3,000 %) con pm = 2 % da el aviso ``des.road_mean_gradient`` (la media, el límite y los cinco tramos más empinados con su abscisa y su
        lugar) y ``mean_exceeded``; con pm = 10 %, ni aviso ni bandera. La confirmación expresa con su motivo la pide y la registra la orden (T20b y T21), no este cálculo."""
        step = rd.step_terrain(GRID)
        strict = axis_job(rd.STEP_AXIS, terrain=step, profile=rd.profile_with(reach_m=12.5, max_mean_gradient_pct=2.0))
        outcome = last(road_store.road_compute_steps(strict, COMMON))
        mean = [notice for notice in outcome.notices if notice.code == "des.road_mean_gradient"]
        self.assertEqual(len(mean), 1)
        self.assertAlmostEqual(mean[0].values["mean"], rd.STEP_MEAN_PCT, delta=TOL * 100.0)
        self.assertEqual((mean[0].values["limit"], len(mean[0].values["stretches"])), (2.0, road_gradient.LISTED_STRETCHES))
        self.assertTrue(outcome.mean_exceeded)
        relaxed = last(road_store.road_compute_steps(axis_job(rd.STEP_AXIS, terrain=step), COMMON))
        self.assertEqual([notice.code for notice in relaxed.notices if notice.code == "des.road_mean_gradient"], [])
        self.assertFalse(relaxed.mean_exceeded)
        self.assertAlmostEqual(values_of(relaxed)["des.road_gradient_mean_pct"], rd.STEP_MEAN_PCT, delta=TOL * 100.0)

    def test_e_the_axis_in_the_half_cell_at_the_edge_of_the_grid_takes_the_terrain_of_its_own_cell(self) -> None:
        """RF-015-09, RF-017-15: a menos de media celda del borde de la rejilla la interpolación bilineal no tiene los cuatro vecinos; el terreno bajo el eje es el de **su propia celda** (como las cotas
        de inicio y de fin por defecto de la preparación) y no se rechaza ni se elige otra cota por la persona."""
        job = axis_job(((0.5, 100.0), (0.5, 160.0)), terrain=rd.ramp_terrain(GRID, cross_pct=5.0))
        outcome = last(road_store.road_compute_steps(job, COMMON))
        column = np.zeros(len(outcome.axis.stations), dtype=np.int64)
        row = np.floor((GRID.north - outcome.axis.points[:, 1]) / GRID.dy).astype(np.int64)
        np.testing.assert_array_equal(outcome.terrain, job.start[row, column])
        self.assertTrue(bool(np.isfinite(outcome.levels).all()))


class RejectionsTest(unittest.TestCase):
    """Lo que el cálculo rechaza, como ``DesignError`` de la persona y sin dejar nada (RF-017-04: nombrando la capa, la pista, el campo y el valor)."""

    def assert_error(self, job: Any, code: str, **kwargs: Any) -> Any:
        """``road_compute_steps`` de ``job`` se rechaza con ``code`` nombrando la capa y la pista, sin resultado, y el trabajo no cambia."""
        before = digest_of(job)
        with self.assertRaises(messages.DesignError) as caught:
            last(road_store.road_compute_steps(job, COMMON, **kwargs))
        error = caught.exception
        self.assertEqual(error.code, code)
        self.assertIn(job.request.layer, error.obj)
        self.assertIn(job.request.name, error.obj)
        self.assertTrue(error.field and error.text)
        self.assertEqual(digest_of(job), before)
        return error

    def test_a_no_route_is_rejected_with_its_three_causes_and_nothing_is_relaxed(self) -> None:
        """RF-017-12, CE-017-04: la franja que no puede subir 30 m con pd = 10 % se rechaza con ``des.road_no_route_corridor`` (la red 2D alcanza el origen y el pasillo no tiene ruta 3D: la cota alcanzada y
        la pendiente mínima, 30 %), con el intocable que cierra el único paso con ``des.road_no_route_network`` y con un presupuesto de 10 estados con ``des.road_budget``, **que no es «no hay ruta»**
        (los estados explorados y qué hacer); ningún límite se relaja por su cuenta."""
        job, _mesh, _corridor = strip_case()
        error = self.assert_error(job, "des.road_no_route_corridor")
        self.assertAlmostEqual(error.values["gradient"], 30.0, delta=0.01)
        closed, _mesh, _corridor = strip_case(closed=True)
        self.assert_error(closed, "des.road_no_route_network")
        poor, _mesh, _corridor = strip_case(search_budget=10)
        error = self.assert_error(poor, "des.road_budget")
        self.assertEqual((error.values["budget"], error.values["field"]), (10, params.entity_key(poor.code, "search_budget")))
        self.assertIn("presupuesto", error.text)

    def test_b_the_radius_below_the_minimum_is_rejected_naming_the_vertex_and_the_profile(self) -> None:
        """RF-017-14, RF-017-04: con Rmín = 16 m el radio que cabe (15 m) no llega: ``des.road_radius_below_min`` nombra la capa, la pista, el perfil, el vértice, los tramos y el radio que cabría."""
        job = axis_job(rd.CORNER_SHORT, profile=rd.profile_with(reach_m=12.5, min_radius_m=16.0))
        error = self.assert_error(job, "des.road_radius_below_min")
        self.assertEqual((error.values["vertex"], error.values["length_before"], error.values["minimum"]), (2, 15.0, 16.0))

    def test_c_the_drop_too_steep_is_rejected_saying_the_axis_and_the_needed_length(self) -> None:
        """RF-017-16, RF-017-04, CE-017-03: con los extremos a 0 y a 20 m en un eje de 100 m y pd = 10 %, ``des.road_drop_too_steep`` dice que el eje mide 100 m y hacen falta 200 m, sin cambiar las
        cotas ni la pendiente por su cuenta."""
        job = dataclasses.replace(axis_job(rd.SHORT_AXIS, terrain=rd.step_terrain(GRID)), start_level_m=rd.SHORT_Z_START_M, end_level_m=rd.SHORT_Z_END_M)
        error = self.assert_error(job, "des.road_drop_too_steep")
        self.assertEqual((error.values["length"], error.values["needed"], error.values["drop"]), (100.0, rd.SHORT_NEEDED_M, 20.0))
        self.assertEqual((job.start_level_m, job.end_level_m), (rd.SHORT_Z_START_M, rd.SHORT_Z_END_M))

    def test_d_a_section_over_cells_without_data_is_rejected_with_its_area_and_its_first_cell(self) -> None:
        """RF-015-09, RF-017-04: una celda de la sección sin dato en la superficie de partida (a 3 m del eje, dentro de la calzada) se rechaza con ``des.entity_nodata`` —la pista, la superficie, el área y la
        primera celda— antes de grabar nada (el cálculo no se oculta con un valor); con el nombre del dato que dé quien calcula, dice ese."""
        surface = rd.ramp_terrain(GRID).copy()
        hole = rd.in_box((150.0, 202.0, 154.0, 206.0), GRID)
        surface[hole] = np.nan
        job = axis_job(line_of_ramp(), terrain=surface)
        error = self.assert_error(job, "des.entity_nodata")
        self.assertEqual((error.values["area"], error.values["surface"]), (float(hole.sum()) * GRID.cell_area, job.request.start))
        rows, columns = np.nonzero(hole)
        self.assertEqual((error.values["x"], error.values["y"]), (GRID.west + (columns[0] + 0.5) * GRID.dx, GRID.north - (rows[0] + 0.5) * GRID.dy))
        self.assertEqual(self.assert_error(job, "des.entity_nodata", surface="des_dtm_partida").values["surface"], "des_dtm_partida")


class CancelTest(unittest.TestCase):
    """Cerrar a mitad no deja nada (RF-015-29; RNF-017-06): el cálculo no escribe en ninguna parte y cierra lo que tiene abierto."""

    def tracked(self, module: Any, name: str, closed: list[str]) -> Any:
        """``module.name`` con el aviso de que se cerró el generador que da."""
        real = getattr(module, name)

        def wrapper(*args: Any, **kwargs: Any) -> Iterator[Any]:
            try:
                yield from real(*args, **kwargs)
            finally:
                closed.append(name)

        return mock.patch.object(module, name, wrapper)

    def test_a_closing_in_the_2d_network_leaves_nothing_and_closes_the_search_it_had_open(self) -> None:
        """RF-015-29, RF-017-30, principio 7: con un presupuesto mínimo cada unidad es un paso; cerrar en la red 2D cierra su generador, no cambia ninguna entrada (hash) y el resultado no existe."""
        job = ramp_job()
        before = digest_of(job)
        closed: list[str] = []
        with self.tracked(road_net, "network_steps", closed):
            work = road_store.road_compute_steps(job, COMMON, budget_s=1e-9)
            seen = [next(work) for _ in range(3)]
            work.close()
        self.assertIn("road_net", {step.phase for step in seen})
        self.assertEqual(closed, ["network_steps"])
        self.assertEqual(digest_of(job), before)
        with self.assertRaises(StopIteration):
            next(work)

    def test_b_closing_in_the_engraving_closes_it_too_and_changes_no_input(self) -> None:
        """RF-015-29, RNF-017-06, principio 7: cerrar ya dentro del grabado (la última fase) cierra el generador del grabado y deja intactas la superficie de partida y las máscaras."""
        job = axis_job(line_of_ramp(), terrain=rd.ramp_terrain(GRID, cross_pct=rd.RAMP_CROSS_PCT))
        before = digest_of(job)
        closed: list[str] = []
        with self.tracked(road_engrave, "engrave_steps", closed):
            work = road_store.road_compute_steps(job, COMMON, budget_s=1e-9)
            for step in work:
                if step.phase == "road_engrave":
                    break
            work.close()
        self.assertEqual(closed, ["engrave_steps"])
        self.assertEqual(digest_of(job), before)

    def test_c_every_call_of_the_thread_takes_at_most_0_2_seconds_in_the_three_modes(self) -> None:
        """RNF-017-06, RF-017-30: ninguna llamada del hilo (un ``next`` de los pasos) pasa de 0,2 s en «trazar», «sobre un eje» y «eje 3D» con el presupuesto de 0,05 s (la mejor de dos corridas, por la
        carga ajena); la medida a escala, en Blender, es de la T34."""
        jobs = {
            "trace": ramp_job(),
            "on_axis": axis_job(rd.CORNER_LONG),
            "axis_3d": h1.axis_3d_job(GRID, rd.ramp_terrain(GRID), rd.axis_3d_irregular()),
        }
        for mode, job in jobs.items():
            with self.subTest(mode=mode):
                slowest = min(run(job)[2] for _ in range(2))
                self.assertLessEqual(slowest, 0.2)


class OtherDesignsTest(unittest.TestCase):
    """RF-017-05 (b): un relleno que la pista no tiene en cuenta, con la huella (sección y borde) que sale del cálculo."""

    BOX = (150.0, 198.0, 160.0, 202.0)
    """La caja (local) donde otro diseño sube la superficie: de 5 × 2 celdas de 2 m (40 m²), a lo largo del eje (y = 200 m) y dentro de la calzada (±5,25 m)."""
    RAISE_M = 0.5
    """Un múltiplo de 2⁻¹ (y las cotas, entre 64 y 128 m): la suma es exacta y la diferencia es 0,5 m en **todas** las celdas, así que la «mayor» es la primera (la más al noroeste)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = axis_job(line_of_ramp())
        cls.mask = rd.in_box(cls.BOX, GRID)

    def reader(self, calls: list[tuple[str, Any]]) -> Any:
        """El lector de las superficies de otros diseños en una ventana: «Relleno» sube la partida en la caja (0,5 m) y «Igual» la sube 0,04 m, menos que el espesor mínimo (0,05 m): no difiere."""
        job, mask, raise_m = self.job, self.mask, self.RAISE_M

        def read(name: str, window: Any) -> np.ndarray:
            calls.append((name, window))
            return job.start[window] + (raise_m if name == "Relleno" else 0.04) * mask[window]

        return read

    def test_a_the_design_that_differs_by_more_than_the_minimum_thickness_gives_the_notice_with_area_difference_and_place(self) -> None:
        """RF-017-05 (b), RF-015-06: de dos diseños de la versión que no parten de la partida, el que difiere en más del espesor mínimo (0,05 m) en la huella de la pista da ``des.road_other_design_differs``
        con el área (40 m²), la diferencia máxima (0,5 m) y el lugar (la primera celda de la caja), el otro no, y el resultado dice cuál (``other_designs``: lo que la T21 registra como entrada, con su hash).
        Los lee **en la ventana de trabajo** y no enteros."""
        calls: list[tuple[str, Any]] = []
        outcome = last(road_store.road_compute_steps(self.job, COMMON, others=("Relleno", "Igual"), read_other=self.reader(calls)))
        notices = [notice for notice in outcome.notices if notice.code == "des.road_other_design_differs"]
        self.assertEqual(len(notices), 1)
        values = notices[0].values
        self.assertEqual((values["other"], values["entity"]), ("Relleno", ENTITY))
        self.assertEqual(values["area"], float(self.mask.sum()) * GRID.cell_area)
        self.assertEqual(values["area"], 40.0)
        self.assertAlmostEqual(values["difference"], self.RAISE_M, delta=TOL)
        rows, columns = np.nonzero(self.mask)
        self.assertEqual((values["x"], values["y"]), (GRID.west + (columns[0] + 0.5) * GRID.dx, GRID.north - (rows[0] + 0.5) * GRID.dy))
        self.assertEqual(outcome.other_designs, ("Relleno",))
        self.assertEqual(calls, [("Relleno", outcome.window), ("Igual", outcome.window)])
        for found in calls:
            self.assertLess((found[1][0].stop - found[1][0].start) * (found[1][1].stop - found[1][1].start), GRID.nrows * GRID.ncols)

    def test_b_with_no_design_that_differs_nothing_is_noticed_nor_recorded(self) -> None:
        """RF-017-05 (b): si ningún otro diseño difiere (o no hay ninguno), ni aviso ni nada que registrar (``other_designs`` vacío) y el lector no se llama sin nombres; con nombres y sin lector es un error
        del programa."""
        calls: list[tuple[str, Any]] = []
        quiet = last(road_store.road_compute_steps(self.job, COMMON, others=("Igual",), read_other=self.reader(calls)))
        self.assertEqual((quiet.other_designs, [n for n in quiet.notices if n.code == "des.road_other_design_differs"]), ((), []))
        calls.clear()
        last(road_store.road_compute_steps(self.job, COMMON, read_other=self.reader(calls)))
        self.assertEqual(calls, [])
        with self.assertRaises(ValueError):
            last(road_store.road_compute_steps(self.job, COMMON, others=("Relleno",)))

    def test_c_the_difference_in_the_reach_of_the_edge_counts_as_part_of_the_footprint(self) -> None:
        """RF-017-05 (b): «la huella de la pista (sección y borde)» es la sección y lo que su borde alcanza: un relleno junto a la calzada (a más de 8 m del eje, fuera de la sección y dentro del alcance
        de 12,5 m) que la pista no tiene en cuenta da el aviso, con su área y su lugar."""
        near = rd.in_box((150.0, 208.0, 160.0, 212.0), GRID)
        job = self.job

        def read(name: str, window: Any) -> np.ndarray:
            return job.start[window] + 0.5 * near[window]

        outcome = last(road_store.road_compute_steps(job, COMMON, others=("Junto",), read_other=read))
        notices = [notice for notice in outcome.notices if notice.code == "des.road_other_design_differs"]
        self.assertEqual([notice.values["other"] for notice in notices], ["Junto"])
        self.assertEqual(notices[0].values["area"], float(near.sum()) * GRID.cell_area)
        self.assertFalse(bool((outcome.footprint & near[outcome.window]).any()))  # fuera de la sección
        self.assertEqual(outcome.other_designs, ("Junto",))

    def test_d_the_difference_outside_the_footprint_and_its_edge_does_not_count(self) -> None:
        """RF-017-05 (b): una diferencia fuera de la huella de la pista y de su borde (a 100 m del eje) no es un relleno que la pista deje de tener en cuenta: sin aviso."""
        far = rd.in_box((150.0, 300.0, 160.0, 304.0), GRID)
        job = self.job

        def read(name: str, window: Any) -> np.ndarray:
            return job.start[window] + 1.0 * far[window]

        outcome = last(road_store.road_compute_steps(job, COMMON, others=("Lejos",), read_other=read))
        self.assertEqual((outcome.other_designs, [n for n in outcome.notices if n.code == "des.road_other_design_differs"]), ((), []))


class AvoidAndMagnitudeTest(unittest.TestCase):
    """RF-017-06 (la afección de «preferible no afectar»), RF-015-13 (la magnitud) y RF-017-22 (la calzada fuera de su rasante) llegan al resultado."""

    @staticmethod
    def cross_job(**changes: Any) -> Any:
        """La rampa de 200 m con el 20 % transversal y el arcén de 1,5 m como pista «sobre un eje» (mueve corte y relleno en la sección y en el borde)."""
        return axis_job(line_of_ramp(), terrain=rd.ramp_terrain(GRID, cross_pct=rd.RAMP_CROSS_PCT), profile=dataclasses.replace(h1.SHORT, shoulder_m=1.5), **changes)

    def test_a_the_avoid_figures_weight_the_moved_volume_and_the_notice_is_in_the_outcome(self) -> None:
        """RF-017-06, RF-017-23: con un peso 3 en toda la rejilla, la afección es el área de lo que cambia, el volumen movido (corte + relleno de la sección y del borde) y ese volumen por 3, con su aviso
        ``des.road_avoid_affected``; sin zona de «preferible no afectar», ni cifra ni aviso."""
        weighted = last(road_store.road_compute_steps(self.cross_job(avoid_weight=np.full(GRID.shape, 3.0)), COMMON))
        found = values_of(weighted)
        moved = found["des.road_cut_m3"] + found["des.road_edge_cut_m3"] + found["des.road_fill_m3"] + found["des.road_edge_fill_m3"]
        self.assertGreater(found["des.road_avoid_m2"], 0.0)
        self.assertAlmostEqual(found["des.road_avoid_m3"], moved, delta=1e-6 * moved)
        self.assertAlmostEqual(found["des.road_avoid_weighted_m3"], 3.0 * found["des.road_avoid_m3"], delta=1e-6 * moved)
        self.assertIn("des.road_avoid_affected", [notice.code for notice in weighted.notices])
        plain = last(road_store.road_compute_steps(self.cross_job(), COMMON))
        self.assertEqual([values_of(plain)[key] for key in ("des.road_avoid_m2", "des.road_avoid_m3", "des.road_avoid_weighted_m3")], [0.0, 0.0, 0.0])
        self.assertNotIn("des.road_avoid_affected", [notice.code for notice in plain.notices])

    def test_b_the_magnitude_is_compared_with_the_previous_revision_and_the_threshold_of_the_project(self) -> None:
        """RF-015-13, RF-013-30: sin revisión anterior, la nota ``des.magnitude_no_reference`` con el nombre de la operación; con una que movió 1 m³ y el umbral 1,5, el desmonte y el terraplén de la pista
        (sección y borde juntos) pasan de 1,5 veces: ``des.magnitude_cut`` y ``des.magnitude_fill``."""
        job = self.cross_job()
        base = last(road_store.road_compute_steps(job, COMMON, operation="Pista de prueba"))
        self.assertEqual([n.code for n in base.notices if n.code.startswith("des.magnitude")], ["des.magnitude_no_reference"])
        previous = report.Previous("Pista de prueba", "V01.r1", 1.0, 1.0)
        compared = last(road_store.road_compute_steps(job, COMMON, previous=previous))
        self.assertEqual([n.code for n in compared.notices if n.code.startswith("des.magnitude")], ["des.magnitude_cut", "des.magnitude_fill"])
        found = values_of(compared)
        self.assertEqual(compared.notices[-1].values["current"], round(found["des.road_fill_m3"] + found["des.road_edge_fill_m3"]))

    def test_c_the_other_surface_of_a_quarry_reaches_the_engraving_and_warns_of_the_order(self) -> None:
        """RF-015-14, RF-015-13: si la pista parte de una de las dos superficies de una cantera de la 014 (``quarry``), el orden ``final ≤ explotación ≤ terreno`` se comprueba en su ventana: con la
        superficie final por encima de la de explotación que cambia la pista, ``des.entity_quarry_order`` con el área y el lugar; sin ``quarry``, ningún aviso."""
        job = self.cross_job()
        above = platform.QuarryOrder("Cantera 1", "exploitation", "des_exp_cantera_1", "des_fin_cantera_1", job.start + 10.0)
        checked = last(road_store.road_compute_steps(job, COMMON, quarry=above))
        notices = [notice for notice in checked.notices if notice.code == "des.entity_quarry_order"]
        self.assertEqual(len(notices), 1)
        self.assertEqual((notices[0].values["quarry"], notices[0].values["other"]), ("Cantera 1", "des_fin_cantera_1"))
        shape = tuple(part.stop - part.start for part in checked.window)
        self.assertEqual(notices[0].values["area"], shape[0] * shape[1] * GRID.cell_area)  # toda la ventana de trabajo
        plain = last(road_store.road_compute_steps(job, COMMON))
        self.assertNotIn("des.entity_quarry_order", [notice.code for notice in plain.notices])

    def test_d_the_restricted_road_exposes_the_groups_that_do_not_reach_their_level(self) -> None:
        """RF-017-22, RF-017-06: con un intocable al que llega la calzada, el resultado dice que hay calzada fuera de su rasante (``off_level``, con la causa y la diferencia máxima) para que la T20b pida
        la confirmación; el cálculo **no la pide ni la impide**: el resultado existe."""
        outcome = last(road_store.road_compute_steps(self.cross_job(untouchable=rd.in_box(h1.UNTOUCHABLE_BOX, GRID)), COMMON))
        self.assertTrue(outcome.engraved.needs_confirmation)
        self.assertGreaterEqual(len(outcome.off_level), 1)
        self.assertGreater(outcome.off_level[0].area_m2, 0.0)
        self.assertGreater(outcome.off_level[0].max_m, 0.0)


if __name__ == "__main__":
    unittest.main()
