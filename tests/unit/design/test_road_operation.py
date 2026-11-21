# SPDX-License-Identifier: GPL-3.0-or-later
"""Calcular la pista por pasos: la orquestación por modos, las cifras de RF-017-23 y el ``RoadOutcome`` (spec 017, T20 (a)), y la ``Calculation``, las dos confirmaciones y el resumen (T20b; HU-017-1 y
HU-017-2; RF-017-23, 17, 22, 12, 05 (b), 06, 14 y 16; RF-015-03, RF-015-09, RF-015-13 y RF-015-29; RNF-017-04, 06 y 07; plan 017 §5.3.2, §5.4 A0, §5.7 P-4 y P-14 y §5.8 H-10).

``road_store.road_compute_steps(job, common, ...)`` es el cálculo que comparten «Calcular», el recálculo y la reproducción: encadena, por modo (P-14), la red 2D desde el destino y desde el origen y el
pasillo, la ruta 3D con su presupuesto (solo «trazar»), el eje con curvas, la rasante, la ventana de trabajo (A0), la sección y el grabado, **sin proyecto y sin escribir nada**, por pasos de ≤ 0,05 s con
su progreso y cancelable. Lo que se comprueba aquí es **la orquestación**: que da lo que dan las piezas de la T06 a la T13 compuestas a mano (``tests/referencia/des/test_ref_roads.compose``: el hito H1, que
contrasta cada pieza con el cálculo a mano en las mismas celdas), las veintitrés cifras con sus valores de a mano de CE-017-01, CE-017-02 y CE-017-03, los rechazos como ``DesignError`` de la persona
(RF-012, RF-014, RF-016, RF-015-09), los avisos que añade (la media por encima de pm, RF-017-05 (b), la magnitud) y que cerrar a mitad no deja nada ni toca ninguna entrada.

Todo en la rejilla de 2 m de la cantera sintética (200 × 200 celdas; ``rd.grid_of(2.0)``): un cálculo cuesta ≈ 0,1 s. La pista de E1 y la rampa a una cota, con la cantera y la malla de 4 m, van a
``milestone_road_operation``.

**La parte (b)** (T20b), **sin proyecto** (el «verde»): la huella que la rejilla recorta (``des.road_footprint_clipped``; RF-015-13), las dos confirmaciones —la pendiente media por encima de pm con su
motivo, RF-017-17, y la calzada que no queda en su rasante, RF-017-22— con lo que se registra de quién y cuándo, la restricción o la entidad que impide mover la calzada, y el resumen con las cifras, la
holgura del pasillo (H-10) y los avisos en su orden. La ``Calculation`` (``steps.road_run``) con el proyecto —Calcular no escribe, cerrar a mitad no deja nada, la causa de un «sin ruta», las confirmaciones
sobre la ``Calculation``— es de ``milestone_road_calculate``.

**La parte de la T21** (crear), **sin proyecto**: lo que guarda «Crear» —el eje por estaciones (``des_rdx_``), la fila de la huella (``des_epr_``), el informe (``des_prp_``) y el hash de la geometría— como
funciones puras del resultado (lo repite la reproducción, T22), lo que anota la operación (las entradas de los otros diseños que difieren y lo confirmado) y que **no se declara nada** (RF-017-01, D-15).
«Crear» con el proyecto es de ``milestone_road_create``.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import datetime as dt
import json
import math
import pathlib
import sqlite3
import time
import unittest
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.referencia.des import test_ref_roads as h1
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_no_route import strip_case

access = import_geoblender("gis.masks.access")
entity_store = import_geoblender("design.entity_store")
masks_zones = import_geoblender("gis.masks.zones")
messages = import_geoblender("design.messages")
operations = import_geoblender("core.provenance.operations")
params = import_geoblender("design.params")
platform = import_geoblender("design.platform")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
report = import_geoblender("design.report")
road_engrave = import_geoblender("design.road_engrave")
road_axis = import_geoblender("design.road_axis")
road_gradient = import_geoblender("design.road_gradient")
road_model = import_geoblender("design.road_model")
road_net = import_geoblender("design.road_net")
road_profiles = import_geoblender("design.road_profiles")
road_section = import_geoblender("design.road_section")
road_store = import_geoblender("design.road_store")
store = import_geoblender("design.store")

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


# --- T20b: la huella que la rejilla recorta, las confirmaciones y el resumen (sin proyecto) -------------------------------------


def clipped_of(outcome: Any) -> list[Any]:
    """Los avisos de la huella que la rejilla recorta de un resultado."""
    return [notice for notice in outcome.notices if notice.code == "des.road_footprint_clipped"]


class ClippedFootprintTest(unittest.TestCase):
    """RF-015-13 (último inciso: «la huella que la rejilla recorta»), RF-017-20, RF-017-23: la sección de una pista junto al borde de la rejilla sale de ella; lo de fuera no se calcula y se avisa, con
    su área y su lugar, como la plataforma, el contrafuerte y el cuerpo apoyado."""

    def test_a_a_road_along_the_north_edge_loses_the_rows_of_its_left_side_outside_the_grid(self) -> None:
        """RF-015-13, RF-017-20: el eje de 200 m a 1 m del borde norte (y = 399 m; la rejilla acaba en 400 m) y el terreno sin dato al norte: el caballón va a la derecha (al sur) y el lado izquierdo, el
        del borde, es la calzada sola (5,25 m: arcén 0). Las filas de fuera son las de los centros a 401 y 403 m (a 2 y 4 m del eje; la de 405 m está a 6 m), por los 100 centros de columna entre 100
        y 300 m: 200 celdas, 800 m², la primera —de norte a sur y de oeste a este— en (101, 403). El aviso va **el primero** (no hay avisos del eje) y la sección que queda es la de dentro."""
        job = axis_job(((100.0, 399.0), (300.0, 399.0)))
        outcome = last(road_store.road_compute_steps(job, COMMON))
        found = clipped_of(outcome)
        self.assertEqual(len(found), 1)
        self.assertEqual(outcome.notices[0].code, "des.road_footprint_clipped")
        values = found[0].values
        columns = np.arange(101.0, 300.0, 2.0)  # los centros de celda de x entre 100 y 300 m (los extremos de la calzada son planos)
        rows = np.arange(401.0, 410.0, 2.0)  # los centros de las filas de fuera de la rejilla (al norte de y = 400 m)
        inside = np.abs(rows - 399.0) <= 10.5 / 2.0  # el lado del borde es la calzada sola: sin arcén
        cells = columns.size * int(inside.sum())
        self.assertEqual((columns.size, int(inside.sum()), cells), (100, 2, 200))
        self.assertEqual((values["entity"], values["cells"], values["area"]), (ENTITY, cells, float(cells) * GRID.cell_area))
        self.assertEqual((values["x"], values["y"]), tuple(float(value) for value in rd.absolute([(columns[0], rows[inside].max())], GRID)[0]))
        self.assertEqual(found[0].severity, "warning")
        self.assertTrue(bool(outcome.footprint.any()), "lo de dentro se calcula")

    def test_a2_the_notice_goes_before_those_of_the_engraving_and_the_magnitude(self) -> None:
        """RF-015-13: en el orden del resultado el aviso de lo que la rejilla recorta va tras los del eje y **antes** de los del grabado (el salto creado y sus tramos) y de la magnitud, como el de la huella
        de la plataforma va antes de los de su borde; con el escalón del terreno la pista los tiene todos."""
        job = axis_job(((100.0, 399.0), (300.0, 399.0)), terrain=rd.step_terrain(GRID))
        outcome = last(road_store.road_compute_steps(job, COMMON))
        codes = [notice.code for notice in outcome.notices]
        self.assertTrue(outcome.engraved.notices and codes.count("des.road_footprint_clipped") == 1)
        self.assertEqual(codes.index("des.road_footprint_clipped"), 0)
        self.assertLess(codes.index("des.road_footprint_clipped"), min(codes.index(notice.code) for notice in outcome.engraved.notices))
        self.assertLess(codes.index("des.edge_surface_step"), codes.index("des.magnitude_no_reference"))

    def test_b_a_road_along_the_east_edge_loses_its_berm_side_columns(self) -> None:
        """RF-015-13, RF-017-20, D-12: el eje de 200 m a 1 m del borde este (x = 399 m) hacia el norte: con el terreno sin dato fuera, el caballón (1 m) va a la derecha, al este, y el lado de fuera mide
        5,25 + 1 = 6,25 m: las columnas de 401, 403 y 405 m (a 2, 4 y 6 m) por las 100 filas de 101 a 299 m: 300 celdas, 1.200 m², la primera en (401, 299)."""
        job = axis_job(((399.0, 100.0), (399.0, 300.0)))
        outcome = last(road_store.road_compute_steps(job, COMMON))
        (notice,) = clipped_of(outcome)
        columns = np.arange(401.0, 410.0, 2.0)
        within = columns[np.abs(columns - 399.0) <= 10.5 / 2.0 + 1.0]
        cells = within.size * np.arange(101.0, 300.0, 2.0).size
        self.assertEqual(cells, 300)
        self.assertEqual((notice.values["cells"], notice.values["area"]), (cells, 1200.0))
        self.assertEqual((notice.values["x"], notice.values["y"]), tuple(float(value) for value in rd.absolute([(within.min(), 299.0)], GRID)[0]))

    def test_b2_in_a_corner_the_strips_give_what_the_whole_extended_grid_gives(self) -> None:
        """RF-015-13: una pista que acaba en la esquina nordeste de la rejilla sale por el norte y por el este: la cuenta por franjas (cuántas celdas y la primera, de norte a sur y de oeste a este)
        es la de medir la sección entera sobre una rejilla ampliada (diez celdas por lado, el terreno sin dato fuera) y quedarse con lo que cae fuera de la rejilla; las dos franjas tienen celdas."""
        job = axis_job(((330.0, 340.0), (399.0, 399.0)))
        profile = job.profile
        axis = road_axis.axis_of(job.geometry.line, profile.curve_radius_m, profile.min_radius_m, profile.station_step_m)
        carriageway = road_profiles.derived(profile).carriageway_m
        pad = 10
        wide = type(GRID)(west=GRID.west - pad * GRID.dx, north=GRID.north + pad * GRID.dy, dx=GRID.dx, dy=GRID.dy, ncols=GRID.ncols + 2 * pad, nrows=GRID.nrows + 2 * pad)
        whole = road_section.section_cells(axis, carriageway, profile.shoulder_m, profile.berm_m, np.pad(job.start, pad, constant_values=np.nan), wide)
        rows, columns = np.nonzero(whole.cells)
        rows, columns = rows + whole.window[0].start, columns + whole.window[1].start
        out = ~((rows >= pad) & (rows < pad + GRID.nrows) & (columns >= pad) & (columns < pad + GRID.ncols))
        north, east = int((out & (rows < pad)).sum()), int((out & (columns >= pad + GRID.ncols)).sum())
        self.assertTrue(north > 0 and east > 0, "sale por el norte y por el este")
        first = min(zip(rows[out].tolist(), columns[out].tolist(), strict=True))
        found = last(road_section.clipped_steps(axis, carriageway, profile.shoulder_m, profile.berm_m, job.start, GRID))
        self.assertEqual(found[0], int(out.sum()))
        self.assertEqual((found[1], found[2]), (float(wide.west + (first[1] + 0.5) * wide.dx), float(wide.north - (first[0] + 0.5) * wide.dy)))

    def test_c_a_section_that_stays_inside_the_grid_or_a_road_in_the_middle_has_no_notice(self) -> None:
        """RF-015-13: una pista a 10 m del borde (la sección llega a 6,25 m) y la rampa de en medio no recortan nada: ningún aviso."""
        near = last(road_store.road_compute_steps(axis_job(((100.0, 390.0), (300.0, 390.0))), COMMON))
        self.assertEqual(clipped_of(near), [])
        self.assertEqual(clipped_of(last(road_store.road_compute_steps(ramp_job(), COMMON))), [])

    def test_d_the_budget_does_not_change_it_the_steps_are_short_and_the_text_has_both_languages(self) -> None:
        """RNF-017-06, RF-015-02: con el presupuesto mínimo el aviso es el mismo y ninguna llamada del hilo pasa de 0,2 s; el texto, en español y en inglés (con su singular), no deja ningún marcador."""
        job = axis_job(((100.0, 399.0), (300.0, 399.0)))
        _steps, fine, slowest = run(job, budget_s=1e-9)
        whole = last(road_store.road_compute_steps(job, COMMON))
        self.assertEqual([(n.code, dict(n.values)) for n in clipped_of(fine)], [(n.code, dict(n.values)) for n in clipped_of(whole)])
        self.assertLessEqual(slowest, 0.2)
        (notice,) = clipped_of(whole)
        for language, words in (("es", ("«Pista de prueba»", "recorta su huella", "800 m²", "200 celdas")), ("en", ("«Pista de prueba»", "cuts its footprint", "800 m²", "200 cells"))):
            text = notice.text(language)
            self.assertNotIn("{", text)
            for word in words:
                self.assertIn(word, text)
        one = preview.Notice("des.road_footprint_clipped", {**notice.values, "cells": 1, "area": 4.0})
        self.assertIn("(1 celda)", one.text("es"))
        self.assertIn("(1 cell)", one.text("en"))


A15_PROFILE = rd.profile_with(reach_m=12.5, max_gradient_pct=12.0)
"""pd = 12 % con la pm = 10 % del perfil de referencia: la media de 10,5 % de la «opción A15» de la propiedad (N-15; D-6) la pasa."""


def a15_job() -> Any:
    """La pista «sobre un eje» de 200 m sobre un plano del 10,5 % (la «opción A15»): su media pasa de pm sin pasar de pd."""
    x, _y = rd.local_centers(GRID)
    return axis_job(line_of_ramp(), terrain=rd.RAMP_Z0_M + 0.105 * x, profile=A15_PROFILE)


def restricted_job(**changes: Any) -> Any:
    """La rampa con el 20 % transversal donde no se admite el corte en la caja de ``h1.MASK_BOX``: la calzada del norte no queda en su rasante."""
    return AvoidAndMagnitudeTest.cross_job(cut_allowed=~rd.in_box(h1.MASK_BOX, GRID), **changes)


def masks_of(code: str | None = None, ctype: str = "no_cut", box: tuple[float, float, float, float] = h1.MASK_BOX) -> Any:
    """Las máscaras de la versión con una sola zona ``code`` de tipo ``ctype`` (o ninguna) en la caja ``box``, como las lee un ``MaskSet``."""
    zones = {} if code is None else {code: masks_zones.Runs.from_mask(rd.in_box(box, GRID))}
    types = {} if code is None else {code: ctype}
    return access.MaskSet(GRID, "v-mano", "op-mano", access.MaskState.CURRENT, (), np.zeros(GRID.shape, dtype=np.uint16), zones=zones, ctypes=types)


class ConfirmationsTest(unittest.TestCase):
    """RF-017-17, RF-017-22, D-6: la pista no se crea sin la confirmación expresa de la pendiente media por encima de pm (con un motivo, que queda registrado con quién y cuándo y no la bloquea) ni de la
    calzada que no queda en su rasante (como la contrapendiente de RF-015-23)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.a15 = last(road_store.road_compute_steps(a15_job(), COMMON))
        cls.carriageway = last(road_store.road_compute_steps(restricted_job(), COMMON))
        cls.clean = last(road_store.road_compute_steps(ramp_job(), COMMON))

    def refused(self, outcome: Any, expected: str, **given: Any) -> Any:
        """``check_road_confirmed`` se rechaza con ``expected`` como ``DesignError`` con su texto sin marcadores en los dos idiomas."""
        with self.assertRaises(messages.DesignError) as caught:
            road_store.check_road_confirmed(outcome, **given)
        error = caught.exception
        self.assertEqual(error.code, expected)
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)
        return error

    def test_a_the_option_a15_mean_over_pm_is_not_created_without_the_confirmation_and_a_reason(self) -> None:
        """RF-017-17, D-6, N-15: la media de 10,5 % frente al 10 % del perfil pide la confirmación: sin ella, ``des.road_mean_unconfirmed`` con la media y el límite; con ella y sin motivo (ausente, vacío o en
        blanco), ``des.road_mean_reason``; con las dos, se crea (no se bloquea). El aviso de antes de crear es el de la media, con la bandera del resultado."""
        outcome = self.a15
        self.assertAlmostEqual(values_of(outcome)["des.road_gradient_mean_pct"], 10.5, delta=1e-6)
        self.assertTrue(outcome.mean_exceeded)
        error = self.refused(outcome, "des.road_mean_unconfirmed")
        self.assertAlmostEqual(float(error.values["mean"]), 10.5, delta=0.01)
        self.assertEqual((error.values["limit"], error.values["entity"]), (10.0, ENTITY))
        for reason in (None, "", "   "):
            with self.subTest(reason=reason):
                self.assertEqual(self.refused(outcome, "des.road_mean_reason", mean=True, reason=reason).values["limit"], 10.0)
        self.assertIsNone(road_store.check_road_confirmed(outcome, mean=True, reason="Opción A15 de la propiedad (N-15)"))
        self.assertTrue(any(notice.code == "des.road_mean_gradient" for notice in outcome.notices))

    def test_b_the_carriageway_off_its_level_is_not_created_without_the_confirmation(self) -> None:
        """RF-017-22: con la calzada del norte sin corte, ``des.road_carriageway_unconfirmed`` dice el área de lo que no queda en su rasante (la suma de sus grupos) y la diferencia máxima; con la
        confirmación, se crea; confirmar la media (que no pasa de pm) no la sustituye."""
        outcome = self.carriageway
        self.assertTrue(outcome.engraved.needs_confirmation and not outcome.mean_exceeded)
        error = self.refused(outcome, "des.road_carriageway_unconfirmed")
        groups = outcome.off_level
        self.assertEqual(error.values["area"], sum(group.area_m2 for group in groups))
        self.assertEqual(error.values["difference"], round(max(group.max_m for group in groups), 3))
        self.assertEqual(self.refused(outcome, "des.road_carriageway_unconfirmed", mean=True, reason="No es la media").values["entity"], ENTITY)
        self.assertIsNone(road_store.check_road_confirmed(outcome, carriageway=True))

    def test_c_a_clean_road_has_nothing_to_confirm(self) -> None:
        """RF-017-17, RF-017-22: sin media por encima de pm ni calzada fuera de su rasante no se pide nada, y confirmar de más no estorba."""
        self.assertFalse(self.clean.mean_exceeded or self.clean.engraved.needs_confirmation)
        self.assertIsNone(road_store.check_road_confirmed(self.clean))
        self.assertIsNone(road_store.check_road_confirmed(self.clean, mean=True, carriageway=True))

    def test_d_the_confirmation_is_recorded_with_who_and_when_in_the_settings(self) -> None:
        """RF-017-17, RF-017-22: lo confirmado queda en los ajustes de la operación con quién (el que da, o quien tiene abierto el proyecto) y cuándo (UTC), la media y el límite, el motivo y el área y la
        diferencia de la calzada, y se lee de vuelta tal cual; sin nada que confirmar, nada que registrar."""
        project = SimpleNamespace(session=SimpleNamespace(user_host="IMGA\\ana@PC-01"), clock=SimpleNamespace(now=lambda: dt.datetime(2026, 11, 21, 9, 30, tzinfo=dt.UTC)))
        found = road_store.road_confirmation(project, self.a15, mean=True, carriageway=True, reason="Opción A15 de la propiedad (N-15)", decided_by="Ana")
        self.assertEqual((found.decided_by, found.decided_on), ("Ana", "2026-11-21T09:30:00.000Z"))
        self.assertEqual((found.reason, found.mean_limit_pct, found.carriageway_m2), ("Opción A15 de la propiedad (N-15)", 10.0, None))
        self.assertAlmostEqual(found.mean_pct, 10.5, delta=0.01)
        settings = found.settings()
        who = {"decided_by": "Ana", "decided_on": "2026-11-21T09:30:00.000Z"}
        self.assertEqual(list(settings), ["mean_gradient"])
        self.assertEqual({key: value for key, value in settings["mean_gradient"].items() if key != "mean_pct"},
                         {"limit_pct": 10.0, "reason": "Opción A15 de la propiedad (N-15)", **who})
        self.assertEqual(road_store.confirmed_of({road_store.CONFIRMED: settings}), found)
        both = road_store.road_confirmation(project, self.carriageway, mean=True, carriageway=True, reason=None, decided_by=None)
        groups = self.carriageway.off_level
        self.assertEqual((both.decided_by, both.mean_pct, both.carriageway_m2), ("IMGA\\ana@PC-01", None, sum(group.area_m2 for group in groups)))
        self.assertEqual(both.settings()["carriageway"], {"area_m2": both.carriageway_m2, "difference_m": round(max(group.max_m for group in groups), 3),
                                                          "decided_by": "IMGA\\ana@PC-01", "decided_on": "2026-11-21T09:30:00.000Z"})
        self.assertEqual(road_store.confirmed_of({road_store.CONFIRMED: both.settings()}), both)
        self.assertIsNone(road_store.road_confirmation(project, self.clean, mean=True, carriageway=True, reason="x", decided_by="Ana"))
        self.assertIsNone(road_store.confirmed_of({}))
        with self.assertRaises(ValueError):
            road_store.confirmed_of({road_store.CONFIRMED: {"mean_gradient": {"mean_pct": 10.5}}})  # sin quién ni cuándo


class CarriagewayNoticesTest(unittest.TestCase):
    """RF-017-22, RF-015-13: la restricción o la entidad que impide mover la calzada, con el área, la diferencia máxima y el lugar; lo que no se mueve junto a ella."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.outcome = last(road_store.road_compute_steps(restricted_job(), COMMON))

    def notices(self, masks: Any, **given: Any) -> tuple[Any, ...]:
        return road_store.carriageway_notices(self.outcome, masks, names=given.get("names", {}), declared=given.get("declared", {}))

    def test_a_a_normal_restriction_is_named_with_its_code(self) -> None:
        """RF-017-22: la zona «sin corte» de las máscaras que cubre la calzada del norte la nombra, con su nombre y su código, con el área, la diferencia máxima y el lugar de su grupo."""
        (notice,) = self.notices(masks_of("sin_corte"), names={"sin_corte": "Sin corte"})
        (group,) = self.outcome.off_level
        self.assertEqual(notice.code, "des.road_carriageway_masks")
        self.assertEqual((notice.values["blocker"], notice.values["area"]), ("Sin corte (sin_corte)", group.area_m2))
        self.assertEqual((notice.values["difference"], notice.values["x"], notice.values["y"]), (round(group.max_m, 3), round(group.x, 2), round(group.y, 2)))
        self.assertIn("Sin corte (sin_corte)", notice.text("es"))
        self.assertEqual(self.notices(masks_of("sin_corte"))[0].values["blocker"], "sin_corte", "sin nombre, su código")

    def test_b_the_entity_that_declares_the_restriction_is_named_by_its_name(self) -> None:
        """RF-017-22, RF-015-10: si la zona la declara una entidad (``dec__btr_001``), el aviso es el de la entidad, con **su nombre** y no el código interno."""
        (notice,) = self.notices(masks_of("dec__btr_001"), declared={"dec__btr_001": "Contrafuerte C1"})
        self.assertEqual((notice.code, notice.values["blocker"]), ("des.road_carriageway_entity", "Contrafuerte C1"))
        self.assertIn("«Contrafuerte C1»", notice.text("es"))
        (fallback,) = self.notices(masks_of("dec__btr_001"))
        self.assertEqual(fallback.values["blocker"], "BTR-001")

    def test_c_what_no_zone_explains_says_the_masks_of_the_version_in_both_languages(self) -> None:
        """RF-017-22: si ninguna zona lo explica (un límite, su banda…) o la zona no prohíbe lo que se le pide (aquí el corte; la de «sin relleno» no lo impide), el aviso lo dice con las máscaras de la
        versión, en el idioma de quien lee."""
        for masks in (masks_of(), masks_of("sin_relleno", "no_fill")):
            with self.subTest(zones=sorted(masks.zones)):
                (notice,) = self.notices(masks)
                self.assertEqual(notice.code, "des.road_carriageway_masks")
                self.assertIn("un límite de las máscaras de la versión", notice.text("es"))
                self.assertIn("a limit of the masks of the version", notice.text("en"))
                self.assertNotIn("{", notice.text("es") + notice.text("en"))

    def test_d_the_zone_that_covers_most_of_the_group_is_the_one_named(self) -> None:
        """RF-017-22: con dos zonas que impiden el corte, se nombra la que cubre más celdas del grupo."""
        big, small = rd.in_box(h1.MASK_BOX, GRID), rd.in_box((180.0, 200.0, 190.0, 205.25), GRID)
        masks = access.MaskSet(GRID, "v-mano", "op-mano", access.MaskState.CURRENT, (), np.zeros(GRID.shape, dtype=np.uint16),
                               zones={"a_pequena": masks_zones.Runs.from_mask(small), "b_grande": masks_zones.Runs.from_mask(big)}, ctypes={"a_pequena": "no_cut", "b_grande": "no_cut"})
        (notice,) = self.notices(masks)
        self.assertEqual(notice.values["blocker"], "b_grande")

    def test_e_a_carriageway_over_the_maximum_height_says_that_height(self) -> None:
        """RF-017-22, RF-017-21: con la altura máxima de desmonte y terraplén de 0,5 m menor que la pendiente transversal, los grupos de la calzada que pasa de ella dicen esa altura
        (``des.road_carriageway_height``) y no una restricción."""
        origin, destination = (tuple(float(v) for v in rd.absolute([point], GRID)[0]) for point in (rd.RAMP_ORIGIN, rd.RAMP_DESTINATION))
        job = rd.route_job(GRID, rd.ramp_terrain(GRID, cross_pct=rd.RAMP_CROSS_PCT), origin, destination, route=rd.route_with(max_cut_fill_m=0.5),
                           profile=dataclasses.replace(h1.PD8, shoulder_m=1.5))
        outcome = last(road_store.road_compute_steps(job, COMMON))
        found = road_store.carriageway_notices(outcome, masks_of(), names={}, declared={})
        self.assertGreaterEqual(len(found), 1)
        self.assertEqual({notice.code for notice in found}, {"des.road_carriageway_height"})
        self.assertEqual({notice.values["height"] for notice in found}, {0.5})
        self.assertEqual(len(found), len(outcome.off_level))

    def test_f_what_does_not_move_is_named_with_the_restriction_as_in_the_platform(self) -> None:
        """RF-015-13: lo que la pista no mueve (las celdas de su sección que no se cortan o no se rellenan y las de su borde) lo dice ``preview.held_notices`` con la restricción: aquí la zona «sin corte» y
        el área de esas celdas; sin celdas, nada."""
        masks = masks_of("sin_corte")
        found = road_store.road_held_notices(self.outcome, masks, names={"sin_corte": "Sin corte"}, declared={})
        engraved = self.outcome.engraved
        held = engraved.cut_denied | engraved.fill_denied | engraved.held
        self.assertTrue(bool(held.any()))
        (notice,) = found
        self.assertEqual(notice.code, "des.entity_held_constraint")
        self.assertEqual((notice.values["entity"], notice.values["constraint"], notice.values["area"]), (ENTITY, "Sin corte (sin_corte)", float(held.sum()) * GRID.cell_area))
        clean = last(road_store.road_compute_steps(ramp_job(shoulder_m=0.0, cross_pct=0.0), COMMON))
        self.assertEqual(road_store.road_held_notices(clean, masks, names={}, declared={}), ())


class SummaryTest(unittest.TestCase):
    """RF-017-23, RF-015-03, RF-017-12, RF-017-17, RF-017-22, H-10: el resumen de «Calcular» lleva las cifras, la holgura del pasillo, los avisos en su orden, lo que pide confirmar y lo que quedará
    obsoleto."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = ramp_job()
        cls.outcome = last(road_store.road_compute_steps(cls.job, COMMON))
        cls.a15_job = a15_job()
        cls.a15 = last(road_store.road_compute_steps(cls.a15_job, COMMON))

    def test_a_the_summary_has_the_figures_the_headline_numbers_and_the_slack_of_the_corridor(self) -> None:
        """RF-017-23, H-10: el resumen de la rampa de CE-017-01 dice la pista y su código, la versión, el modo y el perfil, las cifras tal cual, la longitud (200 m), las cotas (104 y 112 m), la pendiente
        media y máxima (4 %, con su abscisa y su lugar), ningún radio (sin curvas), el corte y el relleno de la sección y del borde juntos y el neto, y **la holgura del pasillo** con su nota, la
        primera (la ruta cambia con ella)."""
        summary = road_store.summary_of(self.outcome, version="V01", profile=self.job.profile)
        found = values_of(self.outcome)
        self.assertIsInstance(summary, preview.RoadSummary)
        self.assertEqual((summary.name, summary.code, summary.version, summary.mode, summary.profile), (ENTITY, "RDW-001", "V01", "trace", self.job.profile.code))
        self.assertEqual(summary.figures, self.outcome.figures)
        self.assertAlmostEqual(summary.length_m, 200.0, delta=TOL * 200.0)
        self.assertAlmostEqual(summary.start_level_m, 104.0, delta=TOL * 104.0)
        self.assertAlmostEqual(summary.end_level_m, 112.0, delta=TOL * 112.0)
        self.assertAlmostEqual(summary.gradient_mean_pct, 4.0, delta=1e-9)
        self.assertAlmostEqual(summary.gradient_max_pct, found["des.road_gradient_max_pct"], delta=1e-12)
        self.assertEqual(summary.gradient_max_station_m, found["des.road_gradient_max_station_m"])
        point = self.outcome.axis.points[int(np.argmax(np.abs(np.diff(self.outcome.levels)) / np.diff(self.outcome.axis.stations)))]
        self.assertEqual((summary.gradient_max_x, summary.gradient_max_y), (float(point[0]), float(point[1])))
        self.assertEqual((summary.radius_min_m, summary.curves), (None, 0))
        cut = found["des.road_cut_m3"] + found["des.road_edge_cut_m3"]
        fill = found["des.road_fill_m3"] + found["des.road_edge_fill_m3"]
        self.assertEqual((summary.cut_m3, summary.fill_m3, summary.net_m3), (cut, fill, cut - fill))
        route = self.outcome.route
        self.assertEqual(summary.margin_m, route.margin_m)
        note = summary.notices[0]
        self.assertEqual((note.code, note.severity), ("des.road_route_margin", "note"))
        self.assertEqual(dict(note.values), {"entity": ENTITY, "mesh": route.mesh_m, "margin": route.margin_m, "expanded": route.expanded, "budget": route.budget})
        self.assertIn("holgura del pasillo de 60,0 m", note.text("es"))
        self.assertIn("slack of 60.0 m", note.text("en"))
        self.assertEqual(summary.obsolete, ())
        self.assertFalse(summary.needs_mean_confirmation or summary.needs_carriageway_confirmation)

    def test_a2_the_volumes_of_the_summary_add_the_section_and_the_edge(self) -> None:
        """RF-017-23: con un escarpe de 20 m a lo largo del eje (100 m al oeste de x = 200 m y 120 m al este) la sección corta y rellena 10 m a cada lado y **el borde** mueve terreno también (corte 4.152 m³ y
        terraplén 13.724 m³): el resumen suma las dos partes —el corte, el relleno y el neto son los totales de las cifras (sección más borde)—, no los de la sección sola."""
        x, _y = rd.local_centers(GRID)
        job = axis_job(((200.0, 100.0), (200.0, 300.0)), terrain=np.where(x < 200.0, 100.0, 120.0))
        outcome = last(road_store.road_compute_steps(job, COMMON))
        found = values_of(outcome)
        self.assertTrue(found["des.road_edge_cut_m3"] > 1000.0 and found["des.road_edge_fill_m3"] > 1000.0)
        summary = road_store.summary_of(outcome, version="V01", profile=job.profile)
        self.assertEqual(summary.cut_m3, found["des.road_cut_m3"] + found["des.road_edge_cut_m3"])
        self.assertEqual(summary.fill_m3, found["des.road_fill_m3"] + found["des.road_edge_fill_m3"])
        self.assertGreater(summary.cut_m3, found["des.road_cut_m3"])
        self.assertGreater(summary.fill_m3, found["des.road_fill_m3"])
        self.assertEqual(summary.net_m3, summary.cut_m3 - summary.fill_m3)
        self.assertAlmostEqual(summary.net_m3, found["des.road_net_m3"], delta=1e-9 * abs(summary.cut_m3))

    def test_b_the_notices_go_in_order_the_axis_the_footprint_the_carriageway_what_is_held_and_what_goes_stale(self) -> None:
        """RF-017-22, RF-015-13, RF-015-03: los avisos del cálculo, los de la calzada fuera de su rasante (los que piden confirmar), lo que no se mueve por una restricción y, al final, lo que quedará
        obsoleto con su causa (la nota de la holgura, la primera, es de «trazar»: ``test_a``)."""
        outcome = last(road_store.road_compute_steps(restricted_job(), COMMON))
        masks, names = masks_of("sin_corte"), {"sin_corte": "Sin corte"}
        carriageway = road_store.carriageway_notices(outcome, masks, names=names, declared={})
        held = road_store.road_held_notices(outcome, masks, names=names, declared={})
        stale = (preview.Obsolete(preview.ObsoleteKind.DEPENDENT, "Cubicación del relleno", "des.entity_layer", "uid-1"),)
        summary = road_store.summary_of(outcome, version="V01", profile=restricted_job().profile, carriageway=carriageway, held=held, obsolete=stale)
        codes = [notice.code for notice in summary.notices]
        calculated = [notice.code for notice in outcome.notices]  # «sobre un eje»: sin ruta, así que sin la nota de la holgura
        first = codes.index("des.road_carriageway_masks")
        self.assertEqual(codes[:first], calculated, "los del cálculo, antes de los de la calzada")
        self.assertEqual(codes[first:first + len(carriageway) + len(held)], [notice.code for notice in (*carriageway, *held)])
        self.assertEqual(codes[-1], "des.entity_obsolete_dependents")
        self.assertEqual(len(codes), first + len(carriageway) + len(held) + 1)
        self.assertTrue(summary.needs_carriageway_confirmation)
        self.assertEqual(summary.carriageway_area_m2, sum(group.area_m2 for group in outcome.off_level))
        self.assertEqual(summary.obsolete, stale)
        for language in ("es", "en"):
            self.assertTrue(all("{" not in line for line in summary.lines(language)))
        self.assertEqual(summary.warnings("es"), tuple(notice.text("es") for notice in summary.notices if notice.severity == "warning"))

    def test_c_the_mean_over_pm_says_it_with_its_limit_and_asks_for_the_confirmation(self) -> None:
        """RF-017-17, D-6: la pista de 10,5 % de media con pm = 10 % lo dice —la media, el límite y los tramos— y pide la confirmación; en «sobre un eje» no hay ruta, así que ni holgura ni su nota."""
        summary = road_store.summary_of(self.a15, version="V01", profile=self.a15_job.profile)
        self.assertTrue(summary.needs_mean_confirmation)
        self.assertEqual(summary.mean_limit_pct, 10.0)
        self.assertAlmostEqual(summary.gradient_mean_pct, 10.5, delta=1e-6)
        self.assertIsNone(summary.margin_m)
        self.assertNotIn("des.road_route_margin", [notice.code for notice in summary.notices])
        self.assertIn("des.road_mean_gradient", [notice.code for notice in summary.notices])
        self.assertFalse(summary.needs_carriageway_confirmation)

    def test_e_the_notices_of_the_start_come_first(self) -> None:
        """RF-017-05 (a): los avisos de la partida que arma la preparación («no llega al fondo» sobre la final restaurada) van **los primeros** del resumen, antes de la holgura del pasillo, y no impiden crearla."""
        start = (preview.Notice("des.road_start_is_final", {"entity": ENTITY, "surface": "des_fin_cantera", "z_final": 136.5, "z_pit": 125.0}),)
        summary = road_store.summary_of(self.outcome, version="V01", profile=self.job.profile, start_notices=start)
        self.assertEqual([notice.code for notice in summary.notices[:2]], ["des.road_start_is_final", "des.road_route_margin"])
        self.assertIn("136,5", summary.lines("es")[0])

    def test_d_a_result_without_engraving_is_a_program_error(self) -> None:
        """Un resultado sin el grabado (el de ``road_compute_steps`` siempre lo lleva) no tiene resumen: ``ValueError``."""
        with self.assertRaises(ValueError):
            road_store.summary_of(dataclasses.replace(self.outcome, engraved=None), version="V01", profile=self.job.profile)


class PreviousTest(unittest.TestCase):
    """RF-013-30, RF-015-13, D-25: con qué se compara el desmonte y el terraplén de una pista (la magnitud): lo de la misma entidad en la revisión congelada más reciente."""

    @staticmethod
    def database() -> sqlite3.Connection:
        """Las operaciones y las cifras que lee ``road_previous``, a mano: ``RDW-001`` (100 + 50 de desmonte y 20 + 10 de relleno), ``RDW-002`` (le falta una cifra), una fallida, y, **más recientes** y con todas
        las cifras, una plataforma y una pista fallida de igual código (que no cuentan)."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE gb_operation (fid INTEGER PRIMARY KEY, uid TEXT, revision_uid TEXT, op_type TEXT, status TEXT, settings TEXT)")
        conn.execute("CREATE TABLE gb_figure (operation_uid TEXT, key TEXT, value REAL)")
        for fid, uid, op_type, status, settings in ((1, "op-a", "des.road", "done", {"code": "RDW-001", "name": "Pista A"}), (2, "op-b", "des.road", "done", {"code": "RDW-002"}),
                                                    (3, "op-c", "des.road", "failed", {"code": "RDW-003"}), (4, "op-d", "des.platform", "done", {"code": "RDW-001", "name": "Otra"}),
                                                    (5, "op-e", "des.road", "failed", {"code": "RDW-001", "name": "Fallida"})):
            conn.execute("INSERT INTO gb_operation VALUES (?, ?, 'rev-1', ?, ?, ?)", (fid, uid, op_type, status, json.dumps(settings)))
        keys = {"des.road_cut_m3": 100.0, "des.road_edge_cut_m3": 50.0, "des.road_fill_m3": 20.0, "des.road_edge_fill_m3": 10.0}
        conn.executemany("INSERT INTO gb_figure VALUES (?, ?, ?)", [("op-a", key, value) for key, value in keys.items()])
        conn.executemany("INSERT INTO gb_figure VALUES (?, ?, ?)", [("op-b", key, value) for key, value in list(keys.items())[:3]])
        conn.executemany("INSERT INTO gb_figure VALUES (?, ?, ?)", [("op-d", key, 999.0) for key in keys] + [("op-e", key, 777.0) for key in keys])  # lo de la plataforma y lo de la fallida, que no cuentan
        return conn

    def test_a_the_previous_is_the_sum_of_the_section_and_the_edge_of_the_same_entity_by_its_code(self) -> None:
        """RF-013-30, D-25: de la entidad ``RDW-001`` en la revisión congelada ``V01.r3``: el desmonte (100 + 50) y el relleno (20 + 10) de la sección y del borde sumados, con el nombre de su operación; sin
        las de otro tipo ni las fallidas; una cifra que falta, una entidad que no está o ninguna revisión congelada, ``None``."""
        version = SimpleNamespace(uid="version-1", code="V01")
        conn = self.database()
        with mock.patch.object(road_store.versions_read, "last_frozen", return_value=SimpleNamespace(uid="rev-1", number=3)):
            self.assertEqual(road_store.road_previous(conn, version, "RDW-001"), report.Previous("Pista A", "V01.r3", 150.0, 30.0))
            self.assertIsNone(road_store.road_previous(conn, version, "RDW-002"), "le falta una cifra")
            self.assertIsNone(road_store.road_previous(conn, version, "RDW-003"), "la fallida no cuenta")
            self.assertIsNone(road_store.road_previous(conn, version, "RDW-009"))
        with mock.patch.object(road_store.versions_read, "last_frozen", return_value=None):
            self.assertIsNone(road_store.road_previous(conn, version, "RDW-001"), "sin ninguna revisión congelada")


class ObsoleteTest(unittest.TestCase):
    """RF-015-03, RF-015-16: lo que quedará obsoleto al crear la pista."""

    @staticmethod
    def project() -> Any:
        """Un «proyecto» con el grafo de las operaciones a mano: la pista vieja ``op-road`` escribió ``ds-1``; ``op-vol`` (una cubicación) lo lee y escribe ``ds-2``, que lee ``op-plan``; ``op-old`` lo leía
        pero ya está sustituida y ``op-other`` es de otra versión."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE gb_revision (uid TEXT, version_uid TEXT)")
        conn.execute("CREATE TABLE gb_operation (fid INTEGER PRIMARY KEY, uid TEXT, revision_uid TEXT, op_type TEXT, settings TEXT, status TEXT, superseded_by TEXT)")
        conn.execute("CREATE TABLE gb_operation_io (fid INTEGER PRIMARY KEY, operation_uid TEXT, direction TEXT, item_kind TEXT, item_uid TEXT)")
        conn.executemany("INSERT INTO gb_revision VALUES (?, ?)", [("rev-1", "v-1"), ("rev-2", "v-2")])
        for fid, uid, revision, op_type, name, replaced in ((1, "op-road", "rev-1", "des.road", "Pista vieja", None), (2, "op-vol", "rev-1", "des.volume", "Cubicación", None),
                                                            (3, "op-plan", "rev-1", "des.plan", "Plano", None), (4, "op-old", "rev-1", "des.volume", "Vieja", "op-vol"),
                                                            (5, "op-other", "rev-2", "des.volume", "De otra versión", None)):
            conn.execute("INSERT INTO gb_operation VALUES (?, ?, ?, ?, ?, 'done', ?)", (fid, uid, revision, op_type, json.dumps({"name": name}), replaced))
        for number, (uid, direction, item) in enumerate((("op-road", "out", "ds-1"), ("op-vol", "in", "ds-1"), ("op-vol", "out", "ds-2"), ("op-plan", "in", "ds-2"), ("op-old", "in", "ds-1"),
                                                         ("op-other", "in", "ds-1")), start=1):
            conn.execute("INSERT INTO gb_operation_io VALUES (?, ?, ?, 'dataset', ?)", (number, uid, direction, item))
        return SimpleNamespace(read=lambda: contextlib.nullcontext(conn))

    def test_a_a_new_road_makes_nothing_stale_and_a_replacing_one_makes_stale_what_depended_on_what_it_wrote(self) -> None:
        """RF-015-03, RF-015-16: una pista nueva no deja nada obsoleto; la que sustituye una operación (``supersedes``) deja obsoleto, **en cascada y por orden de registro**, lo vigente de su versión que
        dependía de lo que escribió (la cubicación y, por lo que ésta escribió, el plano), no lo sustituido ni lo de otra versión."""
        prepared = SimpleNamespace(version=SimpleNamespace(uid="v-1"))
        self.assertEqual(road_store.road_obsolete(self.project(), prepared), ())
        kind = preview.ObsoleteKind.DEPENDENT
        self.assertEqual(road_store.road_obsolete(self.project(), prepared, supersedes="op-road"),
                         (preview.Obsolete(kind, "Cubicación", "des.volume", "op-vol"), preview.Obsolete(kind, "Plano", "des.plan", "op-plan")))


# --- Crear (T21): lo que guarda la pista, como funciones puras de su resultado --------------------------------------------------------------


class RoadRowsTest(unittest.TestCase):
    """RF-017-01, RF-017-03, RF-017-23, RF-015-01 y RF-015-02 (T21): lo que «Crear» escribe de una pista son funciones **puras** de su resultado (lo repite la reproducción desde lo congelado, T22): el eje
    por estaciones (``des_rdx_``), la fila de la huella (``des_epr_``), el informe (``des_prp_``) y el hash de la geometría de origen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = ramp_job()
        cls.outcome = last(road_store.road_compute_steps(cls.job, COMMON))
        cls.corner_job = axis_job(rd.CORNER_LONG)
        cls.corner = last(road_store.road_compute_steps(cls.corner_job, COMMON))
        cls.step = last(road_store.road_compute_steps(axis_job(rd.STEP_AXIS, terrain=rd.step_terrain(GRID)), COMMON))
        cls.downhill = last(road_store.road_compute_steps(axis_job((rd.RAMP_DESTINATION, rd.RAMP_ORIGIN)), COMMON))
        cls.a15 = last(road_store.road_compute_steps(a15_job(), COMMON))
        cls.restricted = last(road_store.road_compute_steps(restricted_job(), COMMON, previous=report.Previous(ENTITY, "V01.r1", 1.0, 1.0), operation=ENTITY))

    @staticmethod
    def by_quantity(rows: list[Any]) -> dict[str, list[tuple[Any, Any, Any]]]:
        """Las filas de un informe largo por su cantidad: ``quantity`` → lista de ``(valor, unidad, nota)``."""
        found: dict[str, list[tuple[Any, Any, Any]]] = {}
        for quantity, value, unit, note in rows:
            found.setdefault(quantity, []).append((value, unit, note))
        return found

    def test_a_the_axis_has_one_row_per_station_with_its_terrain_its_level_and_its_gradient(self) -> None:
        """RF-017-03, RF-017-23, RF-015-02: ``des_rdx_`` tiene **una fila por estación** del eje, en el orden de la abscisa, con su lugar absoluto, la cota del terreno de partida y la de la rasante
        (las del resultado, bit a bit) y la pendiente del tramo que empieza en ella en % (con signo; la última repite la del último tramo); en la rampa recta de CE-017-01 sube de 104 m a 4 % y no
        tiene curvas (radio vacío y curva 0). Es lo que lee una pista que parte de este eje (``RDW-001@s``)."""
        rows = road_store.road_axis_rows(self.outcome)
        axis = self.outcome.axis
        self.assertEqual(len(rows), len(axis.stations))
        self.assertEqual(len(rows[0]), len(store.columns_of(provenance.ROAD, provenance.ROAD_AXIS_TABLE)))
        table = np.array([row[:6] for row in rows], dtype=np.float64)
        np.testing.assert_array_equal(table[:, 0], axis.stations)
        np.testing.assert_array_equal(table[:, 1:3], axis.points)
        np.testing.assert_array_equal(table[:, 3], self.outcome.terrain)
        np.testing.assert_array_equal(table[:, 4], self.outcome.levels)
        np.testing.assert_allclose(table[:, 4], 104.0 + 0.04 * table[:, 0], rtol=0.0, atol=TOL)  # a mano: de 104 m a 4 %
        np.testing.assert_allclose(table[:, 5], 4.0, rtol=0.0, atol=TOL)
        self.assertEqual({(row[6], row[7]) for row in rows}, {(None, 0)})
        self.assertTrue(all(isinstance(row[7], int) for row in rows))
        down = road_store.road_axis_rows(self.downhill)  # la misma rampa en sentido contrario: baja a 4 % (pendiente negativa) y cada cota es la del terreno
        self.assertEqual({round(row[5], 9) for row in down}, {-4.0})
        np.testing.assert_allclose([row[4] for row in down], 112.0 - 0.04 * np.array([row[0] for row in down]), rtol=0.0, atol=TOL)
        stepped = road_store.road_axis_rows(self.step)  # donde la rasante no es el terreno (el escalón), cada fila guarda las dos cotas
        terrain, level = np.array([row[3] for row in stepped]), np.array([row[4] for row in stepped])
        np.testing.assert_array_equal(terrain, self.step.terrain)
        np.testing.assert_array_equal(level, self.step.levels)
        self.assertGreater(float(np.abs(terrain - level).max()), 1.0)

    def test_b_the_radius_and_the_number_of_the_curve_are_those_of_the_arc_the_station_is_in(self) -> None:
        """RF-017-23, RF-017-13: en la esquina de CE-017-02 (dos rectas de 40 m y R = 20 m) el arco empieza a 20 m (la tangente, R·tan 45°) y mide π·20/2 = 31,416 m: las estaciones de 20 a 51 m
        (cada 1 m) son de la curva 1, de radio 20 m, y las demás, rectas (radio vacío y curva 0)."""
        rows = road_store.road_axis_rows(self.corner)
        (curve,) = self.corner.axis.curves
        self.assertAlmostEqual(curve.station_m, 20.0, delta=TOL)
        inside = {index for index, row in enumerate(rows) if row[7] == 1}
        self.assertEqual(inside, set(range(20, 52)))
        for index, row in enumerate(rows):
            self.assertEqual((row[6], row[7]), (20.0, 1) if index in inside else (None, 0), index)

    def test_b2_a_station_exactly_at_the_end_of_an_arc_is_already_a_straight(self) -> None:
        """RF-017-23, RF-017-13: una estación es de un arco entre su comienzo (incluido) y su final (**excluido**): con R = 12/(π/2 − 1) = 21,0245 m el arco de la esquina de CE-017-02 acaba justo en la
        estación 52 m (40 + R·(π/2 − 1)) y empieza a 18,98 m: las estaciones de 19 a 51 son de la curva y la 52 ya es recta."""
        radius = 12.0 / (np.pi / 2.0 - 1.0)
        outcome = last(road_store.road_compute_steps(axis_job(rd.CORNER_LONG, profile=rd.profile_with(reach_m=12.5, curve_radius_m=radius)), COMMON))
        (curve,) = outcome.axis.curves
        self.assertAlmostEqual(curve.station_m + curve.length_m, 52.0, delta=1e-9)
        rows = road_store.road_axis_rows(outcome)
        inside = [index for index, row in enumerate(rows) if row[7] == 1]
        self.assertEqual((inside[0], inside[-1], len(inside)), (19, 51, 33))
        self.assertEqual((rows[52][6], rows[52][7], rows[18][7]), (None, 0, 0))

    def test_c_the_entity_row_has_the_attributes_the_footprint_in_runs_and_the_points_of_the_axis(self) -> None:
        """RF-015-01, RF-015-02, RF-017-23: ``des_epr_`` tiene **una** fila con los atributos de la entidad (su código, su nombre, el tipo ``road``, los datos de su partida y de su apoyo, la capa y
        el ``fid`` de su geometría, el hash de esa geometría, el modo y las celdas), su ventana de trabajo, **la huella de la sección en tramos de fila** (la máscara que dicen es la huella del resultado
        en la ventana, bit a bit, y no hay nada fuera) y los puntos del eje (absolutos, float64, exactos)."""
        (row,) = road_store.road_entity_rows(self.job, self.outcome, fid=5, start_surface="gis_dtm_prueba", support_surface="gis_dtm_apoyo")
        self.assertEqual(len(row), len(store.columns_of(provenance.ROAD, provenance.ENTITY_TABLE)))
        code, name, kind, start, support, layer, fid, sha, mode, cells, principal, bounds, footprint, axis = row
        self.assertEqual((code, name, kind, start, support, layer, fid, mode, principal), (self.job.code, ENTITY, "road", "gis_dtm_prueba", "gis_dtm_apoyo", self.job.request.layer, 5, "trace", 0))
        self.assertEqual(sha, road_store.road_geometry_sha256(self.job.geometry))
        window = self.outcome.window
        self.assertEqual(json.loads(bounds), [window[0].start, window[0].stop, window[1].start, window[1].stop])
        mask = entity_store.runs_mask(json.loads(footprint), GRID.shape)
        np.testing.assert_array_equal(mask[window], self.outcome.footprint)
        self.assertEqual((cells, int(mask.sum())), (int(self.outcome.footprint.sum()),) * 2)
        self.assertEqual(cells * GRID.cell_area, values_of(self.outcome)["des.road_area_m2"])
        self.assertEqual(json.loads(axis), self.outcome.axis.points.tolist())
        (without,) = road_store.road_entity_rows(self.job, self.outcome, fid=0, start_surface="gis_dtm_prueba", support_surface=None)
        self.assertIsNone(without[4])

    def test_d_the_geometry_hash_follows_every_bit_of_the_geometry_and_its_kind(self) -> None:
        """RF-017-01, RF-015-01: el hash de la geometría de origen (SHA-256) es el mismo para la misma geometría y cambia con el último bit de un vértice, con el orden de origen y destino, con una línea
        en lugar de dos puntos, con la cota y la zona de un destino por cota y con la Z de una línea (un cambio de geometría en QGIS deja obsoleta la pista; uno de un campo, no)."""
        geometry = self.job.geometry
        sha = road_store.road_geometry_sha256(geometry)
        self.assertRegex(sha, r"^[0-9a-f]{64}$")
        self.assertEqual(road_store.road_geometry_sha256(ramp_job().geometry), sha)
        x, y = geometry.origin
        line = np.array(self.corner_job.geometry.line)
        moved = np.array(line)
        moved[-1, 0] = np.nextafter(moved[-1, 0], np.inf)
        ring = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]])
        other_ring = ring + [0.0, 1.0]
        hashes = {
            "base": sha,
            "last bit": road_store.road_geometry_sha256(road_model.RoadGeometry(origin=(float(np.nextafter(x, np.inf)), y), destination=geometry.destination)),
            "destination last bit": road_store.road_geometry_sha256(road_model.RoadGeometry(origin=geometry.origin, destination=(float(np.nextafter(geometry.destination[0], np.inf)), geometry.destination[1]))),
            "swapped": road_store.road_geometry_sha256(road_model.RoadGeometry(origin=geometry.destination, destination=geometry.origin)),
            "line": road_store.road_geometry_sha256(road_model.RoadGeometry(line=line)),
            "line last bit": road_store.road_geometry_sha256(road_model.RoadGeometry(line=moved)),
            "level": road_store.road_geometry_sha256(road_model.RoadGeometry(origin=geometry.origin, destination=road_model.LevelDestination(120.0, 1.0, ((ring,),)))),
            "other level": road_store.road_geometry_sha256(road_model.RoadGeometry(origin=geometry.origin, destination=road_model.LevelDestination(121.0, 1.0, ((ring,),)))),
            "other tolerance": road_store.road_geometry_sha256(road_model.RoadGeometry(origin=geometry.origin, destination=road_model.LevelDestination(120.0, 2.0, ((ring,),)))),
            "other zone": road_store.road_geometry_sha256(road_model.RoadGeometry(origin=geometry.origin, destination=road_model.LevelDestination(120.0, 1.0, ((other_ring,),)))),
            "line with z": road_store.road_geometry_sha256(road_model.RoadGeometry(line=np.column_stack([line, np.arange(len(line), dtype=np.float64)]))),
        }
        self.assertEqual(len(set(hashes.values())), len(hashes), "cada geometría tiene el suyo")

    def test_e_the_report_has_the_counts_the_axis_the_engraving_and_every_notice_but_those_that_depend_on_what_the_operation_does_not_consume(self) -> None:
        """RF-017-23, RF-015-02, RF-015-13: ``des_prp_`` (formato largo: cantidad, valor, unidad y nota) lleva las celdas y el área de la huella, el eje (longitud, estaciones, paso, desviación y una fila por
        curva), la rasante (cotas y pendientes con el lugar de la máxima y si pasa de pm), la sección y el borde (corte y relleno, celdas, alturas máximas y la pared), **cada grupo de la calzada que no queda
        en su rasante con su causa, sus celdas, su área y su lugar**, la afección de «preferible no afectar», la ruta (solo «trazar») y, al final, cada aviso con su código y sus valores en JSON, **salvo la
        magnitud y el orden con la cantera**, que dependen de lo que la operación no consume (la revisión congelada anterior y la otra superficie de la cantera): el informe se reproduce sin el proyecto. Nada
        es NaN ni infinito."""
        outcome = self.restricted
        rows = road_store.road_report_rows(outcome)
        self.assertTrue(all(len(row) == 4 for row in rows))
        for quantity, value, _unit, _note in rows:
            self.assertTrue(value is None or math.isfinite(value), quantity)
        found = self.by_quantity(rows)
        engraved, axis = outcome.engraved, outcome.axis
        self.assertEqual(found["footprint_cells"], [(float(engraved.footprint_cells), "-", None)])
        self.assertEqual(found["area_m2"], [(engraved.area_m2, "m2", None)])
        self.assertEqual((found["axis_m"][0][0], found["axis_stations"][0][0], found["axis_step_m"][0][0]), (axis.length_m, float(len(axis.stations)), axis.step_m))
        self.assertEqual((found["section_cut_m3"][0][0], found["section_fill_m3"][0][0]), (engraved.section_cut_m3, engraved.section_fill_m3))
        self.assertEqual((found["edge_cut_m3"][0][0], found["edge_fill_m3"][0][0]), (engraved.edge_cut_m3, engraved.edge_fill_m3))
        self.assertEqual((found["z_start_m"][0][0], found["z_end_m"][0][0]), (float(outcome.levels[0]), float(outcome.levels[-1])))
        self.assertEqual(found["mean_exceeded"], [(0.0, "-", None)])
        self.assertNotIn("route_expanded", found, "«sobre un eje» no busca ruta")
        trace = self.by_quantity(road_store.road_report_rows(self.outcome))
        route = self.outcome.route
        self.assertEqual([trace[key][0][0] for key in ("route_mesh_m", "route_margin_m", "route_expanded", "route_seen", "route_budget", "route_turns", "route_nodes")],
                         [route.mesh_m, route.margin_m, float(route.expanded), float(route.seen), float(route.budget), float(route.turns), float(route.nodes)])
        groups = [json.loads(note) for _value, _unit, note in found["off_level_group"]]
        self.assertGreaterEqual(len(groups), 1)
        self.assertEqual([(g["group"], g["cause"], g["cells"], g["area_m2"], g["x"], g["y"]) for g in groups],
                         [(g.group, g.cause.value, g.cells, g.area_m2, g.x, g.y) for g in outcome.off_level])
        self.assertEqual([value for value, _unit, _note in found["off_level_group"]], [g.max_m for g in outcome.off_level])
        notices = [json.loads(note)["code"] for quantity, _value, _unit, note in rows if quantity in ("warning", "note")]
        outside = {"des.magnitude_cut", "des.magnitude_fill", "des.magnitude_no_reference", "des.entity_quarry_order"}
        self.assertTrue(outside & {notice.code for notice in outcome.notices}, "el resultado tiene avisos de la magnitud: no van al informe")
        self.assertEqual(notices, [notice.code for notice in outcome.notices if notice.code not in outside])
        self.assertEqual(road_store.road_report_rows(outcome), rows, "el mismo resultado da el mismo informe")

    def test_f_the_mean_over_pm_and_the_curves_are_in_the_report(self) -> None:
        """RF-017-17, RF-017-13, RF-017-23: la media por encima de pm (la «opción A15») queda en el informe (``mean_exceeded`` 1) con su aviso, y cada curva es una fila con su radio y, en la nota, el
        vértice, el radio de diseño, el cambio de dirección, la tangente, el largo, la abscisa y el lugar; una pista «sobre un eje» no lleva filas de la ruta."""
        found = self.by_quantity(road_store.road_report_rows(self.a15))
        self.assertEqual(found["mean_exceeded"], [(1.0, "-", None)])
        self.assertAlmostEqual(found["gradient_mean_pct"][0][0], 10.5, delta=1e-6)
        self.assertIn("warning", found)
        self.assertNotIn("route_expanded", found)
        corner = self.by_quantity(road_store.road_report_rows(self.corner))
        ((radius, unit, note),) = corner["curve"]
        (curve,) = self.corner.axis.curves
        self.assertEqual((radius, unit, corner["curves"][0][0]), (20.0, "m", 1.0))
        self.assertEqual(json.loads(note), {"vertex": curve.vertex, "design_radius_m": curve.design_radius_m, "deflection_rad": curve.deflection, "tangent_m": curve.tangent_m,
                                            "length_m": curve.length_m, "station_m": curve.station_m, "x": curve.x, "y": curve.y})

    def test_g_the_operation_adds_the_other_designs_that_differ_as_inputs_and_what_was_confirmed_to_its_settings(self) -> None:
        """RF-017-05 (b), RF-017-17, RF-017-22, CE-017-05: lo que anota la operación de la pista además de lo que preparó: los **otros diseños que difieren** (``RoadOutcome.other_designs``) como
        entradas con su papel y **el hash que tenían al prepararla** (``seen`` no cambia: lo midió la preparación), sin repetir una que ya lo era; y **lo confirmado** (quién, cuándo, el motivo) en sus
        ajustes. Sin nada que añadir, la misma ``OperationStart``; la preparada no se modifica."""
        used = (operations.Use("gis_fea_pistas_puntos", provenance.ENTITY_LAYER_ROLE), operations.Use("gis_dtm_prueba", provenance.SURFACE_ROLE))
        start = store.OperationStart(provenance.ROAD, ENTITY, "uid-v1", "V01", {"name": ENTITY, "code": "RDW-001", "fields": {"name_field": "nombre"}}, used, ("des.road.rdw_001.mode",), None,
                                     {"uid-layer": "hash-layer", "uid-start": "hash-start", "uid-otra": "hash-otra"})
        self.assertIs(road_store.road_operation_start(start, self.outcome, None), start)
        outcome = dataclasses.replace(self.outcome, other_designs=("des_exp_otra", "des_fin_otra"))
        found = road_store.road_operation_start(start, outcome, None)
        role = provenance.ROAD_OTHER_DESIGN_ROLE
        self.assertEqual(found.inputs, (*used, operations.Use("des_exp_otra", role), operations.Use("des_fin_otra", role)))
        self.assertEqual((found.settings, found.seen, found.params, found.supersedes), (start.settings, start.seen, start.params, start.supersedes))
        self.assertEqual(start.inputs, used)
        again = dataclasses.replace(start, inputs=(*used, operations.Use("des_exp_otra", role)))
        self.assertEqual(road_store.road_operation_start(again, outcome, None).inputs, (*used, operations.Use("des_exp_otra", role), operations.Use("des_fin_otra", role)))
        confirmed = road_store.RoadConfirmed("Ana", "2026-11-21T09:30:00.000Z", 10.5, 10.0, "Opción A15 de la propiedad (N-15)")
        with_confirmation = road_store.road_operation_start(start, self.outcome, confirmed)
        self.assertEqual(with_confirmation.settings, {**start.settings, road_store.CONFIRMED: confirmed.settings()})
        self.assertNotIn(road_store.CONFIRMED, start.settings)
        self.assertEqual(road_store.confirmed_of(with_confirmation.settings), confirmed)
        self.assertEqual(with_confirmation.inputs, used)

    def test_h_creating_without_the_confirmation_is_refused_before_touching_the_writer(self) -> None:
        """RF-017-17, RF-017-22, D-6: ``create_road_steps`` rechaza la pista con la media por encima de pm sin confirmar (``des.road_mean_unconfirmed``) y confirmada sin motivo
        (``des.road_mean_reason``) y la de la calzada fuera de su rasante sin confirmar (``des.road_carriageway_unconfirmed``) **antes de tocar nada**: ni el escritor ni el proyecto (cualquier
        acceso a ellos sería un error de la prueba)."""
        writer = mock.Mock(spec=[])
        project = mock.Mock(spec=[])
        prepared = SimpleNamespace(job=SimpleNamespace(request=SimpleNamespace(name=ENTITY)))
        for outcome, given, expected in ((self.a15, {}, "des.road_mean_unconfirmed"), (self.a15, {"mean": True, "reason": "  "}, "des.road_mean_reason"),
                                         (self.restricted, {}, "des.road_carriageway_unconfirmed")):
            with self.subTest(expected=expected), self.assertRaises(messages.DesignError) as caught:
                next(road_store.create_road_steps(project, writer, prepared, outcome, **given))
            self.assertEqual(caught.exception.code, expected)
        with self.assertRaises(TypeError):
            next(road_store.create_road_steps(project, writer, prepared, object()))

    def test_i_the_road_declares_nothing_and_leaves_no_trace_of_a_declaration(self) -> None:
        """RF-017-01, RF-015-10, RF-015-12, D-15: la pista **no declara restricción alguna** a los demás operadores: ``road_store`` no nombra ni el tipo de operación ``des.declare_constraints`` ni su
        escritor (``declared_steps``), y su ajuste de ``protect``/``guard_m`` no existe; y la pista es una entidad con su propio código que deja una superficie (``store._OWN_CODE_TYPES``): lo que
        apoya al recalcularse no cuenta la superficie de su operación anterior."""
        tree = ast.parse(pathlib.Path(road_store.__file__).read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse(names & {"DECLARE_CONSTRAINTS", "declared_steps", "declare_constraints", "after_entity_change", "declare_steps"}, names & {"DECLARE_CONSTRAINTS", "declared_steps"})
        self.assertNotIn("protect", {param.value for param in params.RoadParam})
        self.assertNotIn("guard_m", {param.value for param in params.RoadParam})
        self.assertIn(provenance.ROAD, store._OWN_CODE_TYPES)


if __name__ == "__main__":
    unittest.main()
