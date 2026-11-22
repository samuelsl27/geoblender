# SPDX-License-Identifier: GPL-3.0-or-later
"""Los modos «sobre un eje» y «eje 3D» de la pista (spec 017, T23; HU-017-1 y HU-017-4; RF-017-02, RF-017-04, RF-017-13, RF-017-14, RF-017-17 y RF-017-18; CE-017-02 y CE-017-03; E3; plan 017
§5.2.1, §5.4 A4 y A5, §5.7 P-14 y §5.8; decisiones de la sesión principal T23-a y «el radio de la planta de un eje 3D denso», 21/11/2026), sin proyecto.

- **«Sobre un eje»** (:class:`OnAxisTest`): una línea en planta a la que se ajustan las curvas (con el radio del perfil) y se da la rasante, **sin modificarla**: CE-017-02 (la tangente de 20 m, el arco de
  31,416 m y el eje de 71,4159 m; el radio que baja a 15 m con su aviso; el rechazo con Rmín = 16 m) y la «opción A15» de la propiedad (E3: el aviso de la media, la confirmación y el motivo, N-15).
- **«Eje 3D»** (:class:`ThreeDModeTest`): la Z de la línea **es** la rasante y no se recalcula; se comprueba (la pendiente entre estaciones cada ``w`` m, la media y **el radio de su planta**) y se graba,
  **sin corregir la línea**. El contrato de esta tarea: (1) la Z de cada estación del eje es la de **la línea en su abscisa**, y no la proporcional de la T20 (:meth:`Axis.line_abscissa`, con las
  tangentes de cada curva repartidas entre sus dos puntos de tangencia); (2) el radio de la planta se mide **remuestreando la línea en las estaciones** (cada ``w`` m, las de la comprobación de la rasante) y
  es el del círculo por tres estaciones consecutivas (:func:`road_axis.plan_of_line`), un aviso por estación con R < Rmín con su abscisa y su lugar.
- **Leer la capa** (:class:`ReadLines3dTest` y :class:`ReadLayer3dTest`, T23-a): la Z de la línea se lee de una línea de rotura (``gis_brk_``) o de la capa propuesta (``des_rpl_``) tal como están guardadas (su ``geom`` con Z, con la
  planta —los campos que no admite una capa de entidades, como el ``BOOLEAN`` de ``hard``, no estorban—); una capa de entidades, sin Z, o una línea sin Z se rechaza con ``des.road_line_no_z``
  nombrando la capa, la pista, el campo y el valor, y los demás rechazos de RF-017-04 valen para la planta de la línea.
- **Reproducir** (:class:`FrozenGeometryTest`): :func:`road_store.frozen_geometry` rehace la línea de «eje 3D» de lo congelado, la misma que la preparación.

Los valores esperados salen de la **definición a mano** (la tangente ``T = R·tan(Δ/2)``, el arco ``R·Δ``, la abscisa de la poligonal, la fórmula del circunradio de tres puntos), no de llamar al código
bajo prueba. Todo en el dominio y sin proyecto; las pruebas con proyecto, en ``milestone_road_modes``.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import math
import sqlite3
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.referencia.des import test_ref_roads as h1
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_operation import COMMON, GRID, axis_job, digest_of, last

messages = import_geoblender("design.messages")
road_axis = import_geoblender("design.road_axis")
road_gradient = import_geoblender("design.road_gradient")
road_model = import_geoblender("design.road_model")
road_store = import_geoblender("design.road_store")
road_section = import_geoblender("design.road_section")
vector = import_geoblender("gis.vector")
wkb = import_geoblender("core.gpkg.wkb")

TOL = 1e-9
ENTITY = h1.ENTITY
PI = math.pi
ARC_M = 10.0 * PI
"""El arco de CE-017-02 (m): R·Δ = 20 · π/2."""
LONG_AXIS_M = 40.0 + 40.0 - 2.0 * 20.0 + ARC_M
"""La longitud del eje de la esquina de 40 m + 40 m con R = 20 m (CE-017-02): 71,4159 m."""
SPARSE = rd.profile_with(reach_m=12.5)
"""El perfil de referencia con el alcance de 12,5 m: el R de diseño de 20 m, el Rmín de 12 m y la estación de 1 m."""
SMOOTH = rd.profile_with(reach_m=12.5, curve_radius_m=40.0, min_radius_m=30.0)
"""El perfil de las líneas densas: R = 40 m y Rmín = 30 m (un arco de 25 m no cabe y uno de 35 m sí)."""


def hand_abscissa(station_m: np.ndarray) -> np.ndarray:
    """La abscisa de la poligonal (la línea de 40 m + 40 m) de cada abscisa del eje de CE-017-02 **a mano**: hasta la tangente (20 m) la misma; el arco (de 31,416 m de eje) reparte los 40 m
    que hay entre sus dos puntos de tangencia; y después, la misma distancia otra vez."""
    s = np.asarray(station_m, dtype=np.float64)
    return np.where(s <= 20.0, s, np.where(s <= 20.0 + ARC_M, 20.0 + (s - 20.0) * 40.0 / ARC_M, 60.0 + (s - 20.0 - ARC_M)))


def hand_corner_point(along_m: np.ndarray) -> np.ndarray:
    """El punto local ``(x, y)`` de la poligonal de la esquina de 40 m ((60, 60) → (100, 60) → (100, 100)) en la abscisa ``along_m`` (a mano)."""
    p = np.asarray(along_m, dtype=np.float64)
    return np.column_stack([np.where(p <= 40.0, 60.0 + p, 100.0), np.where(p <= 40.0, 60.0, 60.0 + (p - 40.0))])


def hand_circumradius(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """El radio del círculo que pasa por tres puntos, ``abc / (4·área)``, a mano (``inf`` si están en una recta)."""
    ab, bc, ca = (float(np.hypot(*(q - p))) for p, q in ((a, b), (b, c), (c, a)))
    area2 = abs(float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])))
    return math.inf if area2 <= 1e-12 else ab * bc * ca / (2.0 * area2)


def local(points: np.ndarray) -> np.ndarray:
    """Los puntos absolutos ``(k, 2)`` como locales de la rejilla de las pruebas."""
    return np.asarray(points, dtype=np.float64)[:, :2] - np.asarray(rd.origin_of(GRID))


def line_3d(local_xy: Any, levels: Any) -> np.ndarray:
    """Una línea 3D absoluta ``(k, 3)`` (float64) de los puntos locales ``local_xy`` y las cotas ``levels``."""
    return np.column_stack([rd.absolute(local_xy, GRID), np.asarray(levels, dtype=np.float64)])


def job_3d(line: np.ndarray, *, profile: Any = SPARSE) -> Any:
    """Una pista «eje 3D» sobre el plano del 4 % con ``line``."""
    return h1.axis_3d_job(GRID, rd.ramp_terrain(GRID), line, profile=profile)


def arc_line(radius_m: float, spacing_m: float, *, lead_m: float = 15.0) -> np.ndarray:
    """Una línea 3D **densa**: una recta de ``lead_m`` m hacia el este, un cuarto de círculo a la izquierda de ``radius_m`` con un vértice cada ``spacing_m`` m y otra recta de ``lead_m`` m hacia el
    norte, de (100, 100) local; la Z sube el 4 % por metro de línea. Los vértices del arco están en el círculo."""
    steps = round(PI / 2.0 * radius_m / spacing_m)
    lead = round(lead_m / spacing_m)
    angle = np.linspace(0.0, PI / 2.0, steps + 1)
    start = np.array([100.0 + lead_m, 100.0])
    centre = start + np.array([0.0, radius_m])
    arc = centre + radius_m * np.column_stack([np.sin(angle), -np.cos(angle)])
    first = np.column_stack([100.0 + np.arange(lead) * spacing_m, np.full(lead, 100.0)])
    last_ = arc[-1] + np.column_stack([np.zeros(lead), np.arange(1, lead + 1) * spacing_m])
    xy = np.vstack([first, arc, last_])
    along = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))))
    return line_3d(xy, 104.0 + 0.04 * along)


class AxisAbscissaTest(unittest.TestCase):
    """El eje de una línea con curvas y la abscisa de la línea que corresponde a cada estación (el contrato de la Z de «eje 3D»)."""

    def test_the_corner_of_ce_017_02_maps_the_arc_onto_the_two_tangents(self) -> None:
        """RF-017-13, RF-017-18, CE-017-02: en la esquina de 40 m + 40 m con R = 20 m (tangente de 20 m, arco de 31,416 m), la abscisa de la línea de cada estación es la **a mano**: la misma hasta la
        tangente, los 40 m de la línea repartidos por el arco y otra vez la misma distancia; el eje mide 71,4159 m y la poligonal, 80 m."""
        axis = road_axis.axis_of(rd.absolute(rd.CORNER_LONG, GRID), 20.0, 12.0, 1.0)
        self.assertAlmostEqual(axis.length_m, LONG_AXIS_M, delta=TOL)
        stations = np.concatenate([axis.stations, [20.0 + ARC_M / 2.0, 20.0 + ARC_M]])
        np.testing.assert_allclose(axis.line_abscissa(stations), hand_abscissa(stations), rtol=0.0, atol=TOL)
        self.assertEqual(float(axis.line_abscissa(np.array([0.0]))[0]), 0.0)
        self.assertAlmostEqual(float(axis.line_abscissa(np.array([axis.length_m]))[0]), 80.0, delta=TOL)
        self.assertAlmostEqual(float(axis.line_abscissa(np.array([20.0 + ARC_M / 2.0]))[0]), 40.0, delta=TOL)  # la mitad del arco es el vértice

    def test_a_straight_line_is_the_identity_and_an_abscissa_outside_the_axis_is_clamped(self) -> None:
        """RF-017-18: sin curvas la abscisa de la línea es la del eje; una abscisa fuera del eje queda en su extremo más próximo; un vector que no es de números finitos es un error del programa."""
        axis = road_axis.axis_of(rd.absolute(rd.STEP_AXIS, GRID), 20.0, 12.0, 0.5)
        np.testing.assert_array_equal(axis.line_abscissa(axis.stations), axis.stations)
        np.testing.assert_array_equal(axis.line_abscissa(np.array([-5.0, 500.0])), np.array([0.0, 200.0]))
        for bad in (np.array([[1.0]]), np.array([np.nan])):
            with self.assertRaises(ValueError):
                axis.line_abscissa(bad)

    def test_a_radius_reduced_to_fit_takes_the_whole_line(self) -> None:
        """RF-017-14, RF-017-18: con tramos de 15 m el radio baja a 15 m y la tangente (15 m) es todo el tramo: el arco de 23,562 m (π·15/2) es todo el eje y reparte los 30 m de la línea."""
        axis = road_axis.axis_of(rd.absolute(rd.CORNER_SHORT, GRID), 20.0, 12.0, 1.0)
        arc = PI * 15.0 / 2.0
        self.assertAlmostEqual(axis.length_m, arc, delta=TOL)
        stations = axis.stations
        np.testing.assert_allclose(axis.line_abscissa(stations), stations * 30.0 / arc, rtol=0.0, atol=TOL)

    def test_a_dense_line_gives_a_monotone_map_that_is_nearly_the_identity(self) -> None:
        """RF-017-18: una línea densa (un vértice cada 0,1 m en un arco de 25 m de radio) da una abscisa creciente que difiere de la del eje en lo que acortan las curvas (menos del 0,01 %)."""
        line = arc_line(25.0, 0.1)
        axis = road_axis.axis_of(line, 40.0, 30.0, 1.0, reject_below_minimum=False)
        along = axis.line_abscissa(axis.stations)
        self.assertTrue(bool((np.diff(along) > 0.0).all()))
        chord = float(np.hypot(*np.diff(line[:, :2], axis=0).T).sum())
        self.assertAlmostEqual(float(along[-1]), chord, delta=TOL * chord)
        self.assertLess(abs(chord - axis.length_m) / chord, 1e-4)


class PlanRadiiTest(unittest.TestCase):
    """El radio de la planta de una línea dibujada, remuestreada en las estaciones del eje (RF-017-18; decisión de la sesión principal, 21/11/2026)."""

    def test_a_discretized_arc_gives_back_its_radius(self) -> None:
        """RF-017-18: un cuarto de círculo de 25 m de radio con un vértice cada 0,1 m, remuestreado cada 1 m, da en cada estación interior del arco el radio del círculo por tres estaciones consecutivas: 25 m
        con el error del remuestreo (O(d²/w²) = 1 % con d = 0,1 y w = 1 m); en las rectas, infinito; y no hay radio en las estaciones de los extremos."""
        line = arc_line(25.0, 0.1)
        axis = road_axis.axis_of(line, 40.0, 30.0, 1.0, reject_below_minimum=False)
        plan = road_axis.plan_of_line(axis, line)
        self.assertEqual(plan.radii.shape, axis.stations.shape)
        self.assertTrue(bool(np.isnan(plan.radii[0])) and bool(np.isnan(plan.radii[-1])))
        lead, arc_m = 15.0, PI / 2.0 * 25.0
        on_arc = (plan.along_m >= lead + 1.5) & (plan.along_m <= lead + arc_m - 1.5)  # las tres estaciones del círculo, dentro del arco
        self.assertGreaterEqual(int(on_arc.sum()), 36)
        np.testing.assert_allclose(plan.radii[on_arc], 25.0, rtol=0.02, atol=0.0)
        straight = (plan.along_m >= 1.5) & (plan.along_m <= lead - 1.5)
        self.assertTrue(bool((plan.radii[straight] > 1e5).all()))  # las rectas: infinito (o la última cifra de la resta)
        np.testing.assert_allclose(np.hypot(*(local(plan.points[on_arc]) - np.array([115.0, 125.0])).T), 25.0, rtol=0.0, atol=0.01)

    def test_a_sharp_corner_is_the_circle_through_the_three_stations_around_it(self) -> None:
        """RF-017-18, CE-017-02: la esquina de 40 m + 40 m (sin curva en la línea) da, en las estaciones cuyo tramo la contiene, el radio del círculo por las tres estaciones **a mano** (los puntos de la
        poligonal en la abscisa de cada estación, ``hand_abscissa``): menores que el Rmín de 12 m cerca del vértice y sin radio en las rectas."""
        line = rd.absolute(rd.CORNER_LONG, GRID)
        axis = road_axis.axis_of(line, 20.0, 12.0, 1.0)
        plan = road_axis.plan_of_line(axis, line)
        points = hand_corner_point(hand_abscissa(axis.stations))
        expected = np.full(len(axis.stations), np.nan)
        for i in range(1, len(points) - 1):
            expected[i] = hand_circumradius(points[i - 1], points[i], points[i + 1])
        np.testing.assert_allclose(plan.radii[1:-1], expected[1:-1], rtol=1e-9, atol=0.0)
        np.testing.assert_allclose(local(plan.points), points, rtol=0.0, atol=3e-9)  # el último bit de una coordenada absoluta de 4,4 Mm
        np.testing.assert_allclose(plan.along_m, hand_abscissa(axis.stations), rtol=0.0, atol=TOL)
        low = np.flatnonzero(plan.radii < 12.0)
        self.assertEqual(len(low), 2, "las dos estaciones cuyas tres puntos rodean el vértice (35 y 36 m)")
        self.assertEqual([float(axis.stations[i]) for i in low], [35.0, 36.0])

    def test_the_z_of_a_line_is_the_line_at_the_abscissa_of_each_station(self) -> None:
        """RF-017-18: la Z de cada estación es la de la línea **en su abscisa** (``plan.levels``): con la Z lineal en la abscisa de la línea (0,05 m por metro) es ``100 + 0,05·p`` con ``p`` la abscisa a
        mano; sin Z (una línea ``(k, 2)``) no hay cotas."""
        line = line_3d(rd.CORNER_LONG, [100.0, 102.0, 104.0])
        axis = road_axis.axis_of(line, 20.0, 12.0, 1.0)
        plan = road_axis.plan_of_line(axis, line)
        np.testing.assert_allclose(plan.levels, 100.0 + 0.05 * hand_abscissa(axis.stations), rtol=0.0, atol=TOL)
        self.assertIsNone(road_axis.plan_of_line(axis, line[:, :2]).levels)

    def test_the_line_and_the_axis_must_be_the_same(self) -> None:
        """Una línea con otros vértices que el eje es un error del programa (``ValueError``), no un resultado."""
        axis = road_axis.axis_of(rd.absolute(rd.CORNER_LONG, GRID), 20.0, 12.0, 1.0)
        with self.assertRaises(ValueError):
            road_axis.plan_of_line(axis, rd.absolute(rd.STEP_AXIS, GRID))
        with self.assertRaises(ValueError):
            road_axis.plan_of_line(axis, line_3d(rd.CORNER_LONG, [100.0, 102.0, 104.0])[:2])
        with self.assertRaises(ValueError):  # los mismos vértices que cuenta, pero en otro sitio
            road_axis.plan_of_line(axis, line_3d(rd.CORNER_SHORT, [100.0, 102.0, 104.0]))


class OnAxisTest(unittest.TestCase):
    """«Sobre un eje» (RF-017-02, RF-017-13, RF-017-14, RF-017-17; CE-017-02; E3): las curvas del perfil y la rasante, sin modificar la línea."""

    def test_a_ce_017_02_the_corner_gives_the_analytic_arc_and_the_line_does_not_change(self) -> None:
        """RF-017-13, RF-017-02, CE-017-02: dos tramos rectos perpendiculares de 40 m con R = 20 m dan una tangente de 20 m, un arco de 31,416 m (π·R/2) y un eje de 71,4159 m con el radio mínimo real
        de 20 m, y el eje a ≤ 10⁻⁹ m del arco analítico (centro (80, 80), radio 20); **la línea no cambia** (su hash antes y después)."""
        job = axis_job(rd.CORNER_LONG, profile=SPARSE)
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        self.assertIs(outcome.mode, road_model.RoadMode.ON_AXIS)
        (curve,) = outcome.axis.curves
        self.assertAlmostEqual(curve.tangent_m, 20.0, delta=TOL)
        self.assertAlmostEqual(curve.length_m, ARC_M, delta=TOL)
        self.assertAlmostEqual(outcome.axis.length_m, LONG_AXIS_M, delta=TOL)
        self.assertEqual(outcome.axis.min_radius_m, 20.0)
        station = outcome.axis.stations
        arc = local(outcome.axis.points)[(station >= 20.0) & (station <= 20.0 + ARC_M)]
        np.testing.assert_allclose(np.hypot(*(arc - np.array([80.0, 80.0])).T), 20.0, rtol=0.0, atol=TOL)
        self.assertEqual(digest_of(job), before)
        self.assertIsNone(outcome.route)

    def test_b_ce_017_02_the_radius_that_does_not_fit_is_reduced_with_its_notice_or_rejected(self) -> None:
        """RF-017-14, CE-017-02: con tramos de 15 m y Rmín = 12 m el radio se reduce a 15 m (el mayor que cabe) con el aviso del vértice (el 2.º, con su lugar); con Rmín = 16 m **se rechaza**
        nombrando la capa, la pista, el vértice, los tramos (15 y 15 m) y el radio que cabría (15 m), sin bajar de Rmín por su cuenta; en los dos casos la línea no cambia."""
        job = axis_job(rd.CORNER_SHORT, profile=rd.profile_with(reach_m=12.5, min_radius_m=12.0))
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        reduced = [notice for notice in outcome.notices if notice.code == "des.road_radius_reduced"]
        self.assertEqual(len(reduced), 1)
        self.assertEqual((reduced[0].values["vertex"], reduced[0].values["radius"]), (2, 20.0))
        self.assertAlmostEqual(reduced[0].values["fitted"], 15.0, delta=TOL)
        self.assertAlmostEqual(outcome.axis.min_radius_m, 15.0, delta=TOL)
        strict = axis_job(rd.CORNER_SHORT, profile=rd.profile_with(reach_m=12.5, min_radius_m=16.0))
        with self.assertRaises(messages.DesignError) as caught:
            last(road_store.road_compute_steps(strict, COMMON))
        error = caught.exception
        self.assertEqual(error.code, "des.road_radius_below_min")
        for expected in (strict.request.layer, strict.request.name):
            self.assertIn(expected, error.obj)
        self.assertEqual((error.values["vertex"], error.values["length_before"], error.values["length_after"], error.values["fitted"], error.values["minimum"]), (2, 15.0, 15.0, 15.0, 16.0))  # a milésimas
        self.assertEqual(digest_of(job), before)
        self.assertEqual(digest_of(strict), digest_of(axis_job(rd.CORNER_SHORT, profile=rd.profile_with(reach_m=12.5, min_radius_m=16.0))))

    def test_c_e3_the_a15_axis_asks_for_the_confirmation_with_a_reason_that_stays_recorded(self) -> None:
        """RF-017-17, E3, D-6, N-15: un eje con pd = 15 % sobre un terreno del 10,5 % (la «opción A15» de la propiedad) y pm = 10 % da el aviso de la media (10,5 % frente al 10 %, con sus tramos), no se
        crea sin la confirmación (``des.road_mean_unconfirmed``) ni la confirmación sin un motivo (``des.road_mean_reason``), con ambos se crea y **el motivo queda registrado con quién y cuándo** (y no
        bloquea); la línea no cambia."""
        x, _y = rd.local_centers(GRID)
        terrain = rd.RAMP_Z0_M + 0.105 * x
        job = axis_job(rd.STEP_AXIS, terrain=terrain, profile=rd.profile_with(reach_m=12.5, max_gradient_pct=15.0, max_mean_gradient_pct=10.0))
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        mean = [notice for notice in outcome.notices if notice.code == "des.road_mean_gradient"]
        self.assertEqual(len(mean), 1)
        self.assertAlmostEqual(mean[0].values["mean"], 10.5, delta=TOL * 100.0)
        self.assertEqual((mean[0].values["limit"], len(mean[0].values["stretches"])), (10.0, road_gradient.LISTED_STRETCHES))
        self.assertTrue(outcome.mean_exceeded)
        with self.assertRaises(messages.DesignError) as unconfirmed:
            road_store.check_road_confirmed(outcome)
        self.assertEqual(unconfirmed.exception.code, "des.road_mean_unconfirmed")
        self.assertAlmostEqual(unconfirmed.exception.values["mean"], 10.5, delta=1e-2)
        with self.assertRaises(messages.DesignError) as reasonless:
            road_store.check_road_confirmed(outcome, mean=True, reason="  ")
        self.assertEqual(reasonless.exception.code, "des.road_mean_reason")
        reason = "Opción A15 de la propiedad (N-15)"
        road_store.check_road_confirmed(outcome, mean=True, reason=reason)
        project = SimpleNamespace(session=SimpleNamespace(user_host="IMGA\\ana@PC-01"), clock=SimpleNamespace(now=lambda: dt.datetime(2026, 11, 21, 9, 30, tzinfo=dt.UTC)))
        found = road_store.road_confirmation(project, outcome, mean=True, carriageway=False, reason=reason, decided_by=None)
        recorded = found.settings()["mean_gradient"]
        self.assertEqual((recorded["reason"], recorded["decided_by"], recorded["decided_on"]), (reason, "IMGA\\ana@PC-01", "2026-11-21T09:30:00.000Z"))
        self.assertAlmostEqual(recorded["mean_pct"], 10.5, delta=TOL * 100.0)
        self.assertEqual(recorded["limit_pct"], 10.0)
        self.assertEqual(digest_of(job), before)


class ThreeDModeTest(unittest.TestCase):
    """«Eje 3D» (RF-017-02, RF-017-17, RF-017-18; CE-017-03): la Z de la línea es la rasante; se comprueba y se graba sin corregirla."""

    def test_a_the_z_of_a_station_is_the_z_of_the_line_at_its_abscissa_not_the_proportional_one(self) -> None:
        """RF-017-18, RF-017-02: con una esquina el eje (con su curva) es más corto que la línea: la Z de cada estación es **la de la línea en su abscisa** (``100 + 0,05·p`` con ``p`` la de
        ``hand_abscissa``, a ≤ 10⁻⁹ m) y no la proporcional (que daría 101,12 m en el comienzo del arco, donde la línea lleva 101 m)."""
        job = job_3d(line_3d(rd.CORNER_LONG, [100.0, 102.0, 104.0]))
        outcome = last(road_store.road_compute_steps(job, COMMON))
        np.testing.assert_allclose(outcome.levels, 100.0 + 0.05 * hand_abscissa(outcome.axis.stations), rtol=0.0, atol=TOL)
        at_arc = int(np.flatnonzero(outcome.axis.stations == 20.0)[0])
        self.assertAlmostEqual(float(outcome.levels[at_arc]), 101.0, delta=TOL)

    def test_b_a_dense_arc_below_the_minimum_gives_one_notice_per_station_and_not_one_per_vertex(self) -> None:
        """RF-017-18: una línea densa (un vértice cada 0,1 m) con un cuarto de círculo de 25 m (menor que el Rmín de 30 m) avisa **una vez por estación** —cada 1 m del arco: unos 38, y no uno por vértice,
        que serían casi 400— con la abscisa y el lugar de cada una y el radio del círculo por tres estaciones (25 m a ≤ 2 % en casi todas); **la línea no cambia**."""
        line = arc_line(25.0, 0.1)
        job = job_3d(line, profile=SMOOTH)
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        radius = [notice for notice in outcome.notices if notice.code == "des.road_axis3d_radius"]
        self.assertTrue(34 <= len(radius) <= 42, len(radius))
        found = np.array([notice.values["radius"] for notice in radius])
        self.assertTrue(bool(((found > 24.0) & (found < 30.0)).all()))
        self.assertGreaterEqual(int((np.abs(found - 25.0) <= 0.5).sum()), int(0.9 * len(found)))  # las de transición (una estación en la recta) quedan entre 25 y 30 m
        self.assertTrue(all(notice.values["minimum"] == 30.0 for notice in radius))
        stations = [notice.values["station"] for notice in radius]
        self.assertEqual(stations, sorted(stations))
        self.assertTrue(all(0.0 < station < outcome.axis.length_m for station in stations))
        np.testing.assert_allclose(np.hypot(*(local(np.array([[n.values["x"], n.values["y"]] for n in radius])) - np.array([115.0, 125.0])).T), 25.0, rtol=0.0, atol=0.01)
        self.assertEqual(digest_of(job), before)

    def test_c_a_dense_arc_that_fits_gives_no_notice_at_all(self) -> None:
        """RF-017-18: la misma línea con un arco de 35 m (≥ Rmín = 30 m, menor que el R de diseño de 40 m) **no avisa de nada**: ni del radio de la planta ni de «el radio baja» (la línea es una
        entrada que no se redondea por la persona: el radio de diseño no es un aviso en este modo)."""
        outcome = last(road_store.road_compute_steps(job_3d(arc_line(35.0, 0.1), profile=SMOOTH), COMMON))
        self.assertEqual([notice.code for notice in outcome.notices if notice.code.startswith(("des.road_axis3d", "des.road_radius"))], [])

    def test_d_a_sharp_corner_is_flagged_even_if_its_legs_are_long(self) -> None:
        """RF-017-18, CE-017-02: la esquina de 40 m + 40 m **sin curva en la línea** (el radio de la planta es nulo en el vértice) avisa del radio por debajo de Rmín = 12 m en las dos estaciones que
        la rodean (35 y 36 m) con el radio del círculo por sus tres puntos **a mano**, aunque el eje la redondee con R = 20 m para grabar; la línea no cambia."""
        job = job_3d(line_3d(rd.CORNER_LONG, [100.0, 102.0, 104.0]))
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        radius = [notice for notice in outcome.notices if notice.code == "des.road_axis3d_radius"]
        self.assertEqual([notice.values["station"] for notice in radius], [35.0, 36.0])
        points = hand_corner_point(hand_abscissa(np.array([34.0, 35.0, 36.0, 37.0])))
        expected = [hand_circumradius(*points[0:3]), hand_circumradius(*points[1:4])]
        np.testing.assert_allclose([notice.values["radius"] for notice in radius], expected, rtol=1e-9, atol=0.0)
        np.testing.assert_allclose(local(np.array([[n.values["x"], n.values["y"]] for n in radius])), hand_corner_point(hand_abscissa(np.array([35.0, 36.0]))), rtol=0.0, atol=1e-9)
        self.assertEqual(outcome.axis.min_radius_m, 20.0)  # lo que se graba (el eje redondeado con R = 20 m) no es lo que se avisa
        self.assertEqual(digest_of(job), before)

    def test_e_the_irregular_z_gives_the_stretch_the_mean_and_nothing_for_the_radius_and_the_engraving_is_the_z(self) -> None:
        """RF-017-18, RF-017-17, CE-017-03: con la Z irregular de CE-017-03 (40 avisos de tramo con w = 1 m —los de 15 % y 12 %—, la media de 7,2 % frente a pm = 5 %) y una planta recta **no hay avisos
        del radio**; la Z es la rasante (``gradient_line`` no se llama) y **la calzada grabada la lleva** (la superficie en las celdas de la sección es la cota de cada una); la línea no cambia y la
        media pide la confirmación con un motivo, como en los demás modos."""
        job = job_3d(rd.axis_3d_irregular(), profile=rd.profile_with(reach_m=12.5, max_mean_gradient_pct=5.0))
        before = digest_of(job)
        outcome = last(road_store.road_compute_steps(job, COMMON))
        codes = [notice.code for notice in outcome.notices]
        self.assertEqual(codes[:41], ["des.road_axis3d_gradient"] * 40 + ["des.road_mean_gradient"])
        self.assertNotIn("des.road_axis3d_radius", codes)
        self.assertTrue(outcome.mean_exceeded)
        np.testing.assert_allclose(outcome.levels, 104.0 + np.interp(outcome.axis.stations, 20.0 * np.arange(11), np.concatenate(([0.0], np.cumsum(rd.AXIS_3D_INCREMENTS_M)))), rtol=0.0, atol=TOL)
        window = outcome.window
        section = road_section.section_cells(outcome.axis, 10.5, 0.0, 1.0, job.start, GRID, window)
        expected = section.levels(outcome.axis.stations, outcome.levels)
        engraved = outcome.surface[section.cells & ~np.isnan(expected)]
        np.testing.assert_allclose(engraved, expected[section.cells & ~np.isnan(expected)], rtol=0.0, atol=TOL)
        with self.assertRaises(messages.DesignError) as unconfirmed:
            road_store.check_road_confirmed(outcome)
        self.assertEqual(unconfirmed.exception.code, "des.road_mean_unconfirmed")
        road_store.check_road_confirmed(outcome, mean=True, reason="La línea es de R-35")
        self.assertEqual(digest_of(job), before)

    def test_f_the_gradient_stretches_come_before_the_mean_and_the_radius_after_it(self) -> None:
        """RF-017-18: el orden de los avisos es el de la comprobación: los tramos que pasan de pd (por abscisa), la media y los radios de la planta (por abscisa), y el aviso de cada uno lleva el nombre de la
        pista, la abscisa y el lugar."""
        profile = rd.profile_with(reach_m=12.5, max_gradient_pct=3.0, max_mean_gradient_pct=1.0)
        outcome = last(road_store.road_compute_steps(job_3d(line_3d(rd.CORNER_LONG, [100.0, 102.0, 104.0]), profile=profile), COMMON))
        codes = [notice.code for notice in outcome.notices if notice.code.startswith(("des.road_axis3d", "des.road_mean"))]
        self.assertEqual(codes[0], "des.road_axis3d_gradient")
        self.assertEqual(codes[-3:], ["des.road_mean_gradient", "des.road_axis3d_radius", "des.road_axis3d_radius"])
        self.assertLess(codes.index("des.road_mean_gradient"), codes.index("des.road_axis3d_radius"))
        for notice in outcome.notices:
            if notice.code.startswith("des.road_axis3d"):
                self.assertEqual(notice.values["entity"], ENTITY)
                self.assertTrue({"station", "x", "y"} <= set(notice.values))

    def test_g_a_line_that_goes_back_over_itself_has_no_axis_and_is_refused_with_its_text(self) -> None:
        """RF-017-04, RF-017-18 (T49; hallazgo T47-3): una línea que vuelve por el mismo camino (A → B → A: sus dos tramos son contiguos y no cuentan como un cruce) da un eje **sin longitud** (el radio del
        giro es nulo: en «eje 3D» no se rechaza por Rmín) y hasta la T49 el cálculo lanzaba un ``ValueError`` pelado («la Z de la línea es un vector con al menos dos números: forma (1,)»): ahora es un
        ``DesignError`` ``des.road_line_doubles_back`` con la capa, la pista, el campo, el valor y el lugar del giro (x = 100 m, y = 60 m locales), en los dos idiomas y sin marcadores sin llenar, y no se
        crea nada. En «sobre un eje» la misma línea sigue dando ``des.road_radius_below_min`` (sin cambio)."""
        turn = rd.absolute(((100.0, 60.0),), GRID)[0]
        back = line_3d(((60.0, 60.0), (100.0, 60.0), (60.0, 60.0)), [100.0, 102.0, 104.0])
        job = job_3d(back)
        before = digest_of(job)
        with self.assertRaises(messages.DesignError) as caught:
            last(road_store.road_compute_steps(job, COMMON))
        error = caught.exception
        self.assertEqual(error.code, "des.road_line_doubles_back")
        self.assertEqual(error.values["layer"], job.request.layer)
        self.assertEqual(error.values["entity"], ENTITY)
        self.assertTrue(error.field.endswith("feature"), error.field)
        self.assertEqual((error.values["x"], error.values["y"]), (round(float(turn[0]), 2), round(float(turn[1]), 2)))
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertIn(ENTITY, text)
        self.assertIn("no se crea nada", error.text)
        self.assertEqual(digest_of(job), before)
        with self.assertRaises(messages.DesignError) as on_axis:
            last(road_store.road_compute_steps(axis_job(((60.0, 60.0), (100.0, 60.0), (60.0, 60.0))), COMMON))
        self.assertEqual(on_axis.exception.code, "des.road_radius_below_min")


def gpkg(rows: list[tuple[bytes, str]], *, table: str = "gis_brk_prueba") -> sqlite3.Connection:
    """Una base con la tabla de líneas de rotura ``table`` tal como la deja el proyecto (``fid``, ``geom``, ``line_id``, ``hard`` y ``code``) y las filas ``(geom, line_id)``."""
    conn = sqlite3.connect(":memory:")
    conn.execute(f'CREATE TABLE "{table}" (fid INTEGER PRIMARY KEY NOT NULL, geom LINESTRING, line_id TEXT NOT NULL DEFAULT \'\', hard BOOLEAN NOT NULL, code TEXT NOT NULL DEFAULT \'\')')
    conn.executemany(f'INSERT INTO "{table}" (geom, line_id, hard, code) VALUES (?, ?, 1, \'\')', rows)
    return conn


def blob(coords: np.ndarray, *, z: bool = True) -> bytes:
    """El blob GeoPackage de un ``LINESTRING`` (con Z o sin ella)."""
    return wkb.encode_geometry("LINESTRING", np.asarray(coords, dtype=np.float64), 25830, z)


def request_3d(feature: str | None, *, layer: str = "gis_brk_prueba", name_field: str | None = "line_id") -> Any:
    """Una pista «eje 3D» de la capa ``layer`` que elige la línea ``feature`` (su ``fid`` o su nombre)."""
    return road_model.RoadRequest(ENTITY, road_model.LayerFields(layer, name_field), "axis_3d", "pista_principal", "gis_dtm_prueba", feature=feature)


class ReadLines3dTest(unittest.TestCase):
    """Leer la línea con Z de una capa del proyecto (T23-a; RF-017-02, RF-017-04, RF-017-18)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.irregular, cls.smooth = rd.axis_3d_irregular(), rd.axis_3d_smooth()
        cls.flat = rd.absolute(rd.STEP_AXIS, GRID)
        cls.conn = gpkg([(blob(cls.irregular), "S1"), (blob(cls.smooth), "S2"), (blob(cls.flat, z=False), "Plana")])
        cls.addClassCleanup(cls.conn.close)
        cls.lines = road_store.read_lines_3d(cls.conn, "gis_brk_prueba")

    def refused(self, request: Any, expected: str, lines: Any = None) -> Any:
        """La línea que pide ``request`` se rechaza con ``expected`` nombrando la capa, la pista, el campo y el valor, con el texto sin marcadores en los dos idiomas."""
        with self.assertRaises(messages.DesignError) as caught:
            road_store.line_3d(self.lines if lines is None else lines, request, "RDW-001")
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertIn(request.layer, error.obj)
        self.assertIn(request.name, error.obj)
        self.assertTrue(error.field.endswith("feature"))
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
        return error

    def test_a_the_layer_is_read_as_stored_with_its_plan_names_and_z(self) -> None:
        """RF-017-02, RF-017-18, T23-a: la tabla de líneas de rotura se lee **tal como está guardada** (bit a bit: X, Y y Z absolutas en float64) con los números de sus filas, los campos de texto como
        nombres y la planta de cada línea; el ``BOOLEAN`` de ``hard`` no estorba (una capa de entidades no lo admite: se lee como el entero que es en el proyecto)."""
        layer = self.lines.layer
        self.assertEqual((layer.kind, layer.fids), ("line", (1, 2, 3)))
        self.assertEqual([(column.field, column.sql_type) for column in layer.columns], [("line_id", "TEXT"), ("hard", "INTEGER"), ("code", "TEXT")])
        self.assertEqual(layer.values["line_id"], ("S1", "S2", "Plana"))
        self.assertEqual(layer.values["hard"], (1, 1, 1))
        np.testing.assert_array_equal(self.lines.xyz[0], self.irregular)
        np.testing.assert_array_equal(self.lines.xyz[1], self.smooth)
        self.assertEqual(self.lines.xyz[2].shape, (2, 2))  # sin Z: dos columnas
        np.testing.assert_array_equal(layer.parts[0][0][0], self.irregular[:, :2])

    def test_b_a_line_is_chosen_by_its_fid_or_by_its_name_and_comes_with_its_z(self) -> None:
        """RF-017-02: «eje 3D» elige la línea por su ``fid`` (``"2"``) o por su nombre (``"S1"``, del campo que eligió la persona) y da sus vértices ``(k, 3)`` y el ``fid``; sin el campo, el de la
        capa de líneas de rotura (``line_id``)."""
        for feature, fid, expected in (("S1", 1, self.irregular), ("2", 2, self.smooth), ("1", 1, self.irregular)):
            line, found = road_store.line_3d(self.lines, request_3d(feature), "RDW-001")
            self.assertEqual(found, fid)
            np.testing.assert_array_equal(line, expected)
        line, found = road_store.line_3d(self.lines, request_3d("S2", name_field=None), "RDW-001")
        self.assertEqual(found, 2)
        np.testing.assert_array_equal(line, self.smooth)

    def test_c_a_line_without_z_is_rejected_naming_the_layer_the_haul_road_the_field_and_the_value(self) -> None:
        """RF-017-04, RF-017-18, T23-a: una línea sin Z (la capa guarda solo X e Y) o con una Z que no es un número se rechaza con ``des.road_line_no_z`` nombrando la capa, la pista, el campo (la
        geometría de su capa) y el valor, **sin elegir una cota por la persona**."""
        error = self.refused(request_3d("Plana"), "des.road_line_no_z")
        self.assertEqual(error.value, "Plana")
        broken = self.irregular.copy()
        broken[4, 2] = np.nan
        bad = road_store.Lines3D(self.lines.layer, (broken, self.smooth, self.flat))
        self.assertEqual(self.refused(request_3d("S1"), "des.road_line_no_z", bad).value, "S1")

    def test_d_the_other_rejections_of_the_plan_of_the_line_hold(self) -> None:
        """RF-017-04: la planta de la línea se comprueba como en «sobre un eje»: la que se corta a sí misma, la de longitud cero, la de un vértice repetido y la de varias partes; una línea que la capa
        no tiene, ``des.entity_feature_unknown``, y sin elegir ninguna, ``des.entity_param_missing``."""
        z = [100.0, 101.0, 102.0, 103.0]
        crossing = np.column_stack([rd.absolute(((200.0, 330.0), (260.0, 390.0), (260.0, 330.0), (200.0, 390.0)), GRID), z])
        repeated = np.column_stack([rd.absolute(((60.0, 360.0), (100.0, 360.0), (100.0, 360.0), (140.0, 360.0)), GRID), z])
        same = np.column_stack([rd.absolute(((50.0, 380.0), (50.0, 380.0)), GRID), [100.0, 101.0]])
        parts = [line_3d(((60.0, 340.0), (100.0, 340.0)), [100.0, 101.0]), line_3d(((120.0, 340.0), (160.0, 340.0)), [100.0, 101.0])]
        multi = wkb.encode_geometry("MULTILINESTRING", parts, 25830, True)
        conn = gpkg([(blob(crossing), "Cruce"), (blob(repeated), "Repetida"), (blob(same), "Nula"), (multi, "Varias")])
        self.addCleanup(conn.close)
        lines = road_store.read_lines_3d(conn, "gis_brk_prueba")
        for feature, code in (("Cruce", "des.road_line_self_intersects"), ("Repetida", "des.road_line_repeated_vertex"), ("Nula", "des.road_line_no_length"),
                              ("Varias", "des.road_line_multipart"), ("Nunca", "des.entity_feature_unknown")):
            self.refused(request_3d(feature), code, lines)
        with self.assertRaises(messages.DesignError) as missing:
            road_store.line_3d(lines, request_3d(None), "RDW-001")
        self.assertEqual(missing.exception.code, "des.entity_param_missing")

    def test_d2_a_line_whose_vertices_are_the_same_point_to_the_tolerance_of_the_axis_has_no_length(self) -> None:
        """RF-017-04, RF-017-18 (T49; hallazgo T47-3): una línea de dos vértices a 10⁻⁷ m, o de tres con todos sus tramos por debajo de 10⁻⁶ m (la tolerancia con que el eje toma un punto por el anterior:
        ``road_axis._REPEAT_M``, la misma constante), no tiene longitud: se rechaza con ``des.road_line_no_length`` —en «eje 3D» y en «sobre un eje», que leen la planta igual—, nombrando la capa, la pista, el
        campo y el valor; hasta la T49 pasaba (solo se rechazaba la igualdad exacta) y el eje lanzaba un ``ValueError`` pelado («necesita al menos dos puntos distintos»). Con un tramo de 2·10⁻⁶ m o de
        verdad entre los vértices, se lee."""
        tol = road_axis._REPEAT_M  # noqa: SLF001  (la misma constante, no una copia)
        base = rd.absolute(((50.0, 380.0),), GRID)[0]
        lines = {"Casi nula": [(0.0, 0.0), (0.1 * tol, 0.0)], "Casi nula 3": [(0.0, 0.0), (0.2 * tol, 0.0), (0.5 * tol, 0.1 * tol)], "Apenas más": [(0.0, 0.0), (2.0 * tol, 0.0)],
                 "Una": [(0.0, 0.0), (1.0, 0.0)]}
        conn = gpkg([(blob(np.column_stack([base + np.array(points), [100.0 + k for k in range(len(points))]])), name) for name, points in lines.items()])
        self.addCleanup(conn.close)
        found = road_store.read_lines_3d(conn, "gis_brk_prueba")
        for feature in ("Casi nula", "Casi nula 3"):
            with self.subTest(feature=feature):
                error = self.refused(request_3d(feature), "des.road_line_no_length", found)
                self.assertEqual(error.value, feature)
                with self.assertRaises(messages.DesignError) as plan:  # la misma planta de «sobre un eje»
                    road_store._read_line(found.layer, list(lines).index(feature), feature, request_3d(feature), "RDW-001")  # noqa: SLF001
                self.assertEqual(plan.exception.code, "des.road_line_no_length")
        for feature in ("Apenas más", "Una"):
            with self.subTest(feature=feature):
                line, _fid = road_store.line_3d(found, request_3d(feature), "RDW-001")
                self.assertEqual(len(line), 2)

    def test_e_the_line_is_read_without_modifying_the_stored_data(self) -> None:
        """Principio 7: leer no cambia la base (ni una fila) y la línea que se da es de solo lectura: quien la usa no puede tocarla."""
        before = self.conn.execute('SELECT fid, geom, line_id FROM "gis_brk_prueba" ORDER BY fid').fetchall()
        line, _fid = road_store.line_3d(self.lines, request_3d("S1"), "RDW-001")
        self.assertEqual(self.conn.execute('SELECT fid, geom, line_id FROM "gis_brk_prueba" ORDER BY fid').fetchall(), before)
        self.assertFalse(line.flags.writeable)


class ReadLayer3dTest(unittest.TestCase):
    """Qué capas del proyecto dan la Z de la línea (T23-a): las líneas de rotura y la capa propuesta, no una capa de entidades."""

    def setUp(self) -> None:
        self.conn = gpkg([(blob(rd.axis_3d_irregular()), "S1")], table="des_rpl_propuesta")
        self.addCleanup(self.conn.close)
        self.project = SimpleNamespace(read=lambda: contextlib.nullcontext(self.conn))

    def read(self, layer: str, found: Any = "present") -> Any:
        """``read_layer_3d`` de la capa ``layer`` con un proyecto que tiene (o no, ``found`` ``None``) su dato registrado con la tabla de la conexión."""
        record = SimpleNamespace(locator="des_rpl_propuesta") if found == "present" else found
        with mock.patch.object(road_store.dataset_registry, "get", return_value=record):
            return road_store.read_layer_3d(self.project, request_3d("S1", layer=layer), "RDW-001")

    def test_the_proposed_layer_and_the_breaklines_give_their_z(self) -> None:
        """RF-017-18, T23-a, P-8: la capa propuesta de «Proponer el trazado…» (``des_rpl_``) y una línea de rotura (``gis_brk_``) se leen de la tabla de su dato, con su Z."""
        for layer in ("des_rpl_propuesta", "gis_brk_pistas"):
            found = self.read(layer)
            np.testing.assert_array_equal(found.xyz[0], rd.axis_3d_irregular())

    def test_an_entities_layer_has_no_z_and_another_layer_or_a_missing_dataset_is_not_a_source(self) -> None:
        """RF-017-04, T23-a: una capa de **entidades** (``gis_fea_``) se rechaza con ``des.road_line_no_z`` (sin tocar el proyecto); un dato que no existe, ``gis.dataset_unknown``; una capa de otra
        familia (puntos, curvas de nivel…), un error del programa."""
        with self.assertRaises(messages.DesignError) as caught:
            self.read("gis_fea_pistas_ejes", found=None)
        self.assertEqual((caught.exception.code, caught.exception.value), ("des.road_line_no_z", "S1"))
        with self.assertRaises(Exception) as missing:
            self.read("gis_brk_no_existe", found=None)
        self.assertEqual(missing.exception.code, "gis.dataset_unknown")
        with self.assertRaises(ValueError):
            self.read("gis_pts_puntos")


class FrozenGeometryTest(unittest.TestCase):
    """Reproducir «eje 3D» de lo congelado (RF-017-02, RF-017-18, RF-015-02): la misma línea que la preparación, sin proyecto."""

    def test_the_frozen_line_is_the_one_the_preparation_reads(self) -> None:
        """RF-017-18, RF-015-02: ``frozen_geometry`` de «eje 3D» da la línea con su Z (bit a bit) y el ``fid`` de la geometría; sin la línea congelada es un error del programa."""
        irregular = rd.axis_3d_irregular()
        conn = gpkg([(blob(rd.axis_3d_smooth()), "S2"), (blob(irregular), "S1")])
        self.addCleanup(conn.close)
        lines = road_store.read_lines_3d(conn, "gis_brk_prueba")
        asked = request_3d("S1")
        geometry, fid = road_store.frozen_geometry(asked, "RDW-001", GRID, lines.layer, lines=lines)
        self.assertEqual(fid, 2)
        np.testing.assert_array_equal(geometry.line, irregular)
        self.assertIsNone(geometry.origin)
        with self.assertRaises(ValueError):
            road_store.frozen_geometry(asked, "RDW-001", GRID, lines.layer)

    def test_the_hash_of_the_geometry_carries_the_z(self) -> None:
        """RF-017-01: el hash de la geometría de origen de una pista «eje 3D» cuenta la Z: la misma planta con otra Z es otra geometría."""
        line = rd.axis_3d_irregular()
        other = line.copy()
        other[:, 2] += 1.0
        found = road_store.road_geometry_sha256(road_model.RoadGeometry(line=line))
        self.assertNotEqual(found, road_store.road_geometry_sha256(road_model.RoadGeometry(line=other)))
        self.assertEqual(found, road_store.road_geometry_sha256(road_model.RoadGeometry(line=line.copy())))


if __name__ == "__main__":
    unittest.main()
