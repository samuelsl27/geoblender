# SPDX-License-Identifier: GPL-3.0-or-later
"""El eje de una pista con curvas circulares (spec 017, T10; HU-017-1 y HU-017-4; RF-017-13 y RF-017-14; CE-017-02; RNF-017-03; plan 017 §5.4 A4,
§5.3.1 y §7.3): ``road_axis.axis_of`` (la ruta, simplificada con Douglas–Peucker, o la línea dibujada, con una curva circular de radio ``R``
en cada vértice, su radio reducido al que cabe o el rechazo si es menor que ``Rmín``, y el muestreo cada ``w`` m).

Las cifras de cada caso salen de la geometría **a mano** (la tangente ``T = R·tan(Δ/2)``, el arco ``R·|Δ|``, la desviación ``R·(1/cos(Δ/2) − 1)``,
la regla de una pasada ``f = mín(tramo / necesario)``) y de ``tests.support.road_data`` (``corner_by_hand``, ``CORNER_LONG`` y ``CORNER_SHORT``,
hechas a mano), **no** de llamar al código bajo prueba. Todo es sintético, en el dominio y sin Blender; el caso de referencia con su cálculo
analítico completo, en ``tests/referencia/des/test_ref_road_axis``.
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

road_axis = import_geoblender("design.road_axis")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")

TOL = 1e-9
"""Metros: el error pedido por RF-017-13 frente al cálculo analítico de arcos y tangentes."""
RADIUS_M = rd.PROFILE.curve_radius_m
"""El radio de curva del perfil de referencia (20 m)."""
MIN_RADIUS_M = rd.PROFILE.min_radius_m
"""Su radio mínimo (12 m)."""
STEP_M = rd.PROFILE.station_step_m
"""Su paso de estación (1 m)."""
LOOSE_M = 0.01
"""Un radio mínimo que nada rechaza: las rutas de nodos muy juntos (zigzag, simplificaciones) no son las de un perfil real."""
LOCAL_LONG = np.asarray(rd.CORNER_LONG)
LOCAL_SHORT = np.asarray(rd.CORNER_SHORT)


def axis_of(points: Any, radius: float = RADIUS_M, minimum: float = MIN_RADIUS_M, step: float = STEP_M, **keywords: Any) -> Any:
    """``axis_of`` con los valores del perfil de referencia."""
    return road_axis.axis_of(points, radius, minimum, step, **keywords)


def mirrored(points: np.ndarray) -> np.ndarray:
    """``points`` reflejados en x (un giro a la izquierda pasa a ser a la derecha)."""
    return np.column_stack([-points[:, 0], points[:, 1]])


def point_segment_m(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """La distancia (m) de ``p`` al segmento ``ab``, en Python puro (independiente del módulo)."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    length2 = abx * abx + aby * aby
    t = 0.0 if length2 == 0.0 else max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / length2))
    return math.hypot(p[0] - (a[0] + t * abx), p[1] - (a[1] + t * aby))


def polyline_distance_m(p: np.ndarray, line: np.ndarray) -> float:
    """La distancia (m) de ``p`` a la poligonal ``line``."""
    return min(point_segment_m(p, line[k], line[k + 1]) for k in range(len(line) - 1))


def digest(array: np.ndarray) -> str:
    """El *hash* del contenido de ``array`` (para comprobar que nadie lo cambia)."""
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def zigzag(count: int, leg_m: float, turn_deg: float) -> np.ndarray:
    """Una poligonal de ``count`` vértices con tramos de ``leg_m`` m que giran ``±turn_deg`` alternando (un camino que serpentea)."""
    heading, points = 0.0, [(0.0, 0.0)]
    for k in range(1, count):
        points.append((points[-1][0] + leg_m * math.sin(heading), points[-1][1] + leg_m * math.cos(heading)))
        heading += math.radians(turn_deg if k % 2 else -turn_deg)
    return np.asarray(points)


class CornerTest(unittest.TestCase):
    def test_a_right_angle_gets_its_tangent_its_arc_and_its_length(self) -> None:
        """RF-017-13, CE-017-02: dos tramos perpendiculares de 40 m con R = 20 m dan una tangente de 20 m, un arco de π·R/2 y un eje de
        71,416 m (20 + π·10 + 20), con el radio mínimo real de 20 m, una curva y la desviación del vértice al arco R·(√2 − 1)."""
        hand = rd.corner_by_hand(40.0, RADIUS_M)
        axis = axis_of(LOCAL_LONG)
        self.assertEqual(axis.curve_count, 1)
        self.assertEqual(len(axis.curves), 1)
        curve = axis.curves[0]
        self.assertAlmostEqual(curve.tangent_m, hand.tangent_m, delta=TOL)
        self.assertAlmostEqual(curve.length_m, hand.arc_m, delta=TOL)
        self.assertAlmostEqual(curve.radius_m, RADIUS_M, delta=TOL)
        self.assertAlmostEqual(axis.length_m, hand.length_m, delta=TOL)
        self.assertAlmostEqual(axis.length_m, 20.0 + math.pi * 10.0 + 20.0, delta=TOL)
        self.assertAlmostEqual(axis.min_radius_m, 20.0, delta=TOL)
        self.assertAlmostEqual(axis.curve_deviation_m, RADIUS_M * (math.sqrt(2.0) - 1.0), delta=TOL)
        self.assertEqual(axis.simplification_m, 0.0)
        self.assertAlmostEqual(axis.deviation_m, RADIUS_M * (math.sqrt(2.0) - 1.0), delta=TOL)
        self.assertFalse(curve.reduced)
        self.assertEqual(axis.notices("RDW-001"), ())

    def test_the_curve_is_a_circle_tangent_to_both_legs(self) -> None:
        """RF-017-13: el arco es un círculo de radio R tangente a sus dos tramos y continuo en tangente (sin vértices puntiagudos, B-PRONT4):
        todos los puntos del eje a la vista del arco están a R de su centro (80, 80); el eje empieza y acaba rectos y en sus tramos."""
        axis = axis_of(LOCAL_LONG, step=0.25)
        s, xy = axis.stations, axis.points
        start, stop = 20.0, 20.0 + math.pi * 10.0
        inside = (s > start + 1e-9) & (s < stop - 1e-9)
        self.assertTrue(inside.any())
        radii = np.hypot(xy[inside, 0] - 80.0, xy[inside, 1] - 80.0)
        np.testing.assert_allclose(radii, RADIUS_M, rtol=0.0, atol=TOL)
        before = xy[s <= start]
        np.testing.assert_allclose(before[:, 1], 60.0, rtol=0.0, atol=TOL)  # el primer tramo es y = 60
        after = xy[s >= stop]
        np.testing.assert_allclose(after[:, 0], 100.0, rtol=0.0, atol=TOL)  # el segundo, x = 100
        self.assertAlmostEqual(float(axis.curves[0].station_m), start, delta=TOL)

    def test_the_heading_has_no_jump_and_turns_exactly_the_deflection(self) -> None:
        """RF-017-13: el azimut del eje (desde el norte, en sentido horario) no salta en ninguna parte: entre dos muestras a 0,01 m cambia como
        mucho 0,01/R y el giro total es el cambio de dirección del vértice (un giro a la izquierda, −90°)."""
        axis = axis_of(LOCAL_LONG)
        s = np.arange(0.0, axis.length_m, 0.01)
        _, heading = axis.sample(s)
        steps = np.diff(heading)
        steps = (steps + math.pi) % (2.0 * math.pi) - math.pi
        self.assertLessEqual(float(np.abs(steps).max()), 0.01 / RADIUS_M * (1.0 + 1e-6))
        self.assertAlmostEqual(float(steps.sum()), -math.pi / 2.0, delta=1e-6)
        self.assertAlmostEqual(heading[0], math.pi / 2.0, delta=TOL)  # empieza al este
        self.assertAlmostEqual(float(axis.curves[0].deflection), -math.pi / 2.0, delta=TOL)

    def test_a_right_turn_is_the_mirror_image_of_a_left_turn(self) -> None:
        """RF-017-13: reflejar la ruta en x da el mismo eje reflejado, con el giro con el signo contrario (a la derecha: +, en sentido horario)."""
        left, right = axis_of(LOCAL_LONG), axis_of(mirrored(LOCAL_LONG))
        self.assertAlmostEqual(left.length_m, right.length_m, delta=TOL)
        np.testing.assert_allclose(right.points, mirrored(left.points), rtol=0.0, atol=TOL)
        self.assertGreater(right.curves[0].deflection, 0.0)
        self.assertLess(left.curves[0].deflection, 0.0)

    def test_a_straight_route_has_no_curve(self) -> None:
        """RF-017-13: sin cambio de dirección no hay curva: ni radio mínimo, ni desviación, y la longitud es la distancia. Un vértice
        alineado en medio tampoco es una curva."""
        line = np.asarray([[0.0, 0.0], [30.0, 40.0], [60.0, 80.0]])
        axis = axis_of(line)
        self.assertEqual(axis.curve_count, 0)
        self.assertIsNone(axis.min_radius_m)
        self.assertEqual(axis.deviation_m, 0.0)
        self.assertAlmostEqual(axis.length_m, 100.0, delta=TOL)
        self.assertEqual(axis.notices("RDW-001"), ())
        two = axis_of(line[[0, 2]])
        self.assertAlmostEqual(two.length_m, 100.0, delta=TOL)

    def test_the_radius_actually_used_is_the_minimum_real_radius(self) -> None:
        """RF-017-13: el radio mínimo real es el menor de los radios de las curvas y el número de curvas, el de vértices con giro."""
        points = zigzag(9, 60.0, 50.0)
        axis = axis_of(points)
        self.assertEqual(axis.curve_count, 7)
        self.assertEqual(min(curve.radius_m for curve in axis.curves), axis.min_radius_m)
        self.assertEqual([curve.vertex for curve in axis.curves], list(range(2, 9)))

    def test_every_axis_is_continuous_and_closes_on_its_last_vertex(self) -> None:
        """RF-017-13: en caminos que serpentean, con giros de todos los tamaños, el eje es continuo (entre dos muestras a 1 m no hay más de 1 m),
        acaba en su último vértice y su longitud es la de los tramos menos las tangentes más los arcos (la fórmula a mano)."""
        rng = np.random.default_rng(20261120)
        for case in range(12):
            count = int(rng.integers(3, 14))
            headings = np.cumsum(rng.uniform(-1.4, 1.4, count - 1))
            legs = rng.uniform(60.0, 120.0, count - 1)
            points = np.vstack([[0.0, 0.0], np.cumsum(np.column_stack([legs * np.sin(headings), legs * np.cos(headings)]), axis=0)])
            axis = axis_of(points, 20.0, 5.0, 1.0)
            by_hand = math.fsum(math.hypot(*(points[k + 1] - points[k])) for k in range(count - 1))
            by_hand += math.fsum(curve.length_m - 2.0 * curve.tangent_m for curve in axis.curves)
            self.assertAlmostEqual(axis.length_m, by_hand, delta=TOL, msg=f"caso {case}")
            jumps = np.hypot(*np.diff(axis.points, axis=0).T)
            self.assertLessEqual(float(jumps.max()), 1.0 + TOL, msg=f"caso {case}")
            np.testing.assert_array_equal(axis.points[-1], points[-1])
            np.testing.assert_array_equal(axis.points[0], points[0])


class FitTest(unittest.TestCase):
    def test_short_legs_lower_the_radius_to_the_largest_that_fits_and_say_so(self) -> None:
        """RF-017-14, CE-017-02: con tramos de 15 m y Rmín = 12 m el radio baja a 15 m (el mayor que cabe: la tangente es el tramo entero) y
        el aviso dice el vértice (el segundo de la ruta), el radio de diseño, el que cabe y su lugar; la pista se puede crear."""
        hand = rd.corner_by_hand(15.0, RADIUS_M)
        axis = axis_of(LOCAL_SHORT)
        curve = axis.curves[0]
        self.assertTrue(curve.reduced)
        self.assertAlmostEqual(curve.radius_m, hand.fitted_radius_m, delta=TOL)
        self.assertAlmostEqual(curve.tangent_m, hand.tangent_m, delta=TOL)
        self.assertAlmostEqual(axis.length_m, hand.length_m, delta=TOL)
        self.assertAlmostEqual(axis.min_radius_m, 15.0, delta=TOL)
        (notice,) = axis.notices("RDW-001")
        self.assertIsInstance(notice, preview.Notice)
        self.assertEqual(notice.code, "des.road_radius_reduced")
        self.assertEqual(notice.severity, "warning")
        self.assertEqual(notice.values["entity"], "RDW-001")
        self.assertEqual(notice.values["vertex"], 2)
        self.assertAlmostEqual(notice.values["radius"], 20.0, delta=TOL)
        self.assertAlmostEqual(notice.values["fitted"], 15.0, delta=TOL)
        self.assertAlmostEqual(notice.values["x"], 75.0, delta=TOL)
        self.assertAlmostEqual(notice.values["y"], 140.0, delta=TOL)
        text, english = notice.text("es"), notice.text("en")
        self.assertIn("RDW-001", text)
        self.assertIn("vértice 2", text)
        self.assertIn("20", text)
        self.assertIn("15", text)
        self.assertIn("vertex 2", english)

    def test_a_radius_below_the_minimum_rejects_naming_the_vertex_the_legs_and_the_radius_that_would_fit(self) -> None:
        """RF-017-14, CE-017-02: con Rmín = 16 m y tramos de 15 m el rechazo nombra el vértice, los tramos (15 m y 15 m) y el radio que
        cabría (15 m), qué hacer y el perfil; **no baja de Rmín por su cuenta** (nada se calcula)."""
        with self.assertRaises(road_axis.RadiusBelowMinimum) as caught:
            axis_of(LOCAL_SHORT, minimum=16.0)
        rejection = caught.exception
        self.assertEqual(len(rejection.offenders), 1)
        worst = rejection.curve
        self.assertEqual(worst.vertex, 2)
        self.assertAlmostEqual(worst.radius_m, 15.0, delta=TOL)
        self.assertAlmostEqual(worst.before_m, 15.0, delta=TOL)
        self.assertAlmostEqual(worst.after_m, 15.0, delta=TOL)
        self.assertEqual(rejection.minimum_m, 16.0)
        profile = rd.road_profile(rd.profile_with(min_radius_m=16.0, name="PISTA_ESTRECHA"))
        error = rejection.error(layer="trazados", entity="Pista norte", profile=profile)
        self.assertIsInstance(error, messages.DesignError)
        self.assertEqual(error.code, "des.road_radius_below_min")
        for language in ("es", "en"):
            text = error.text_in(language)
            for expected in ("trazados", "Pista norte", "PISTA_ESTRECHA", "15", "16", "75", "140"):
                self.assertIn(expected, text, msg=language)
        self.assertIn("vértice 2", error.text_in("es"))
        self.assertIn("mueva el vértice", error.text_in("es"))
        self.assertIn("vertex 2", error.text_in("en"))
        self.assertEqual(error.field, "des.roadprofile.pista_principal.min_radius_m")
        self.assertEqual(error.values["fitted"], 15.0)
        self.assertEqual(error.values["length_before"], 15.0)
        self.assertEqual(error.values["length_after"], 15.0)

    def test_the_radius_equal_to_the_minimum_is_not_rejected_and_one_below_it_is(self) -> None:
        """RF-017-14: el radio que cabe igual a Rmín (12 m con tramos de 12 m) se acepta, con aviso; con tramos de 11,9 m solo cabrían 11,9 m y
        se rechaza: la frontera es Rmín, sin bajar de él."""
        exact = axis_of(((0.0, 0.0), (12.0, 0.0), (12.0, 12.0)))
        self.assertAlmostEqual(exact.min_radius_m, 12.0, delta=TOL)
        self.assertTrue(exact.curves[0].reduced)
        with self.assertRaises(road_axis.RadiusBelowMinimum) as caught:
            axis_of(((0.0, 0.0), (11.9, 0.0), (11.9, 11.9)))
        self.assertAlmostEqual(caught.exception.curve.radius_m, 11.9, delta=TOL)

    def test_two_contiguous_curves_share_the_leg_that_separates_them(self) -> None:
        """RF-017-14: si las tangentes de dos curvas contiguas no caben en el tramo que las separa (T + T = 40 m en un tramo de 30 m) los dos
        radios bajan al mismo factor de una pasada, 30/40 (R = 15 m): sus tangentes suman el tramo entero y entre los arcos no queda recta."""
        points = np.asarray([[0.0, 0.0], [40.0, 0.0], [40.0, 30.0], [80.0, 30.0]])
        axis = axis_of(points)
        self.assertEqual([curve.vertex for curve in axis.curves], [2, 3])
        for curve in axis.curves:
            self.assertTrue(curve.reduced)
            self.assertAlmostEqual(curve.radius_m, 15.0, delta=TOL)
            self.assertAlmostEqual(curve.tangent_m, 15.0, delta=TOL)
        first, second = axis.curves
        self.assertAlmostEqual(second.station_m - (first.station_m + first.length_m), 0.0, delta=TOL)  # sin recta entre los dos arcos
        self.assertAlmostEqual(axis.length_m, 25.0 + 0.0 + 25.0 + 2.0 * (math.pi / 2.0 * 15.0), delta=TOL)  # recta, nada, recta y dos arcos
        self.assertEqual(len(axis.notices("RDW-001")), 2)

    def test_the_rule_of_one_pass_and_that_every_tangent_fits(self) -> None:
        """RF-017-14: en caminos al azar el radio de cada curva es el de diseño por el menor ``f = tramo / necesario`` de sus dos tramos (una
        pasada, calculada a mano con las tangentes de diseño) y, con esos radios, las tangentes de cada tramo caben en él."""
        rng = np.random.default_rng(1120)
        reduced_seen = 0
        for case in range(20):
            count = int(rng.integers(4, 10))
            headings = np.cumsum(rng.uniform(-1.5, 1.5, count - 1))
            legs = rng.uniform(8.0, 40.0, count - 1)
            points = np.vstack([[0.0, 0.0], np.cumsum(np.column_stack([legs * np.sin(headings), legs * np.cos(headings)]), axis=0)])
            axis = road_axis.axis_of(points, 20.0, 1e-6, 1.0)
            ell = [math.hypot(*(points[k + 1] - points[k])) for k in range(count - 1)]
            azimuth = [math.atan2(*(points[k + 1] - points[k])) for k in range(count - 1)]
            nominal = [0.0]
            for k in range(1, count - 1):
                turn = abs((azimuth[k] - azimuth[k - 1] + math.pi) % (2.0 * math.pi) - math.pi)
                nominal.append(20.0 * math.tan(turn / 2.0))
            nominal.append(0.0)

            def factor(j: int) -> float:
                needed = nominal[j] + nominal[j + 1]
                return min(1.0, ell[j] / needed) if needed > 0.0 else 1.0

            expected = {k + 1: 20.0 * min(factor(k), factor(k + 1)) for k in range(count - 2)}
            self.assertEqual({curve.vertex - 1: curve.radius_m for curve in axis.curves}.keys() - expected.keys(), set())
            for curve in axis.curves:
                self.assertAlmostEqual(curve.radius_m, expected[curve.vertex - 1], delta=1e-9, msg=f"caso {case}")
                reduced_seen += curve.reduced
            tangents = {curve.vertex - 1: curve.tangent_m for curve in axis.curves}
            for j in range(count - 1):
                used = tangents.get(j, 0.0) + tangents.get(j + 1, 0.0)
                self.assertLessEqual(used, ell[j] + 1e-9, msg=f"caso {case}, tramo {j}")
        self.assertGreater(reduced_seen, 10)  # el caso está bien elegido: reduce muchas curvas

    def test_the_end_legs_can_be_used_whole(self) -> None:
        """RF-017-14: la tangente de la primera (o la última) curva puede ser el tramo entero (la curva empieza en el origen): con tramos de
        15 m y R = 15 m el eje es un cuarto de círculo del origen al destino, sin tramos rectos."""
        axis = axis_of(LOCAL_SHORT)
        self.assertAlmostEqual(axis.curves[0].station_m, 0.0, delta=TOL)
        np.testing.assert_array_equal(axis.points[0], LOCAL_SHORT[0])  # el primer punto es el origen, aunque empiece en un arco
        np.testing.assert_array_equal(axis.points[-1], LOCAL_SHORT[2])
        xy, _ = axis.sample(np.asarray([0.0, axis.length_m]))
        np.testing.assert_array_equal(xy, [LOCAL_SHORT[0], LOCAL_SHORT[2]])

    def test_the_noise_of_the_last_digit_is_not_a_reduction(self) -> None:
        """RF-017-14: unas tangentes que caben en el tramo salvo por el ruido de la última cifra (el tramo, 2·10⁻¹⁴ m más corto de lo que piden) no son un
        aviso: el radio de diseño se queda y entre los dos arcos no hay recta, ni negativa."""
        points = np.asarray([[0.0, 0.0], [40.0, 0.0], [40.0, 40.0 - 2e-14], [80.0, 40.0 - 2e-14]])
        axis = axis_of(points)
        self.assertEqual(axis.notices("RDW-001"), ())
        self.assertEqual([curve.radius_m for curve in axis.curves], [RADIUS_M, RADIUS_M])
        first, second = axis.curves
        self.assertGreaterEqual(second.station_m - (first.station_m + first.length_m), 0.0)
        self.assertLessEqual(second.station_m - (first.station_m + first.length_m), 1e-12)

    def test_a_reversal_cannot_be_rounded(self) -> None:
        """RF-017-14: un giro casi de 180° pide una tangente enorme: el radio que cabe es casi cero, por debajo de cualquier Rmín, y se rechaza."""
        with self.assertRaises(road_axis.RadiusBelowMinimum):
            axis_of(((0.0, 0.0), (30.0, 0.0), (0.0, 0.01)))

    def test_every_offender_is_listed_and_the_worst_is_named(self) -> None:
        """RF-017-14: con varios vértices por debajo de Rmín, el rechazo los lleva todos y nombra el de menor radio."""
        points = np.asarray([[0.0, 0.0], [40.0, 0.0], [40.0, 13.0], [80.0, 13.0], [80.0, 80.0]])
        with self.assertRaises(road_axis.RadiusBelowMinimum) as caught:
            axis_of(points, minimum=18.0)
        offenders = caught.exception.offenders
        self.assertGreaterEqual(len(offenders), 2)
        self.assertEqual(caught.exception.curve.radius_m, min(curve.radius_m for curve in offenders))

    def test_the_worst_offender_is_not_always_the_first(self) -> None:
        """RF-017-14: con Rmín = 12 m y dos pares de curvas pegadas (a 20 m y a 10 m una de otra: radios de 10 m y de 5 m), el rechazo lleva las cuatro
        en el orden del eje y nombra la de menor radio (el vértice 5, de 5 m), no la primera."""
        points = np.asarray([[0.0, 0.0], [40.0, 0.0], [40.0, 20.0], [80.0, 20.0], [150.0, 20.0], [150.0, 30.0], [190.0, 30.0]])
        with self.assertRaises(road_axis.RadiusBelowMinimum) as caught:
            axis_of(points)
        offenders = caught.exception.offenders
        self.assertEqual([curve.vertex for curve in offenders], [2, 3, 5, 6])
        self.assertEqual([round(curve.radius_m, 9) for curve in offenders], [10.0, 10.0, 5.0, 5.0])
        self.assertEqual(caught.exception.curve.vertex, 5)
        self.assertEqual(caught.exception.curve.radius_m, offenders[2].radius_m)


class SimplifyTest(unittest.TestCase):
    def wiggly(self, count: int = 60, amplitude: float = 1.0) -> np.ndarray:
        """Una ruta casi recta de ``count`` nodos con un zigzag de ±``amplitude`` m (los nodos de una malla de 4 m)."""
        x = 4.0 * np.arange(count)
        return np.column_stack([x, amplitude * np.where(np.arange(count) % 2 == 0, 1.0, -1.0) * (0 < np.arange(count)) * (np.arange(count) < count - 1)])

    def test_douglas_peucker_keeps_the_ends_and_every_node_within_the_tolerance(self) -> None:
        """RF-017-13: la ruta se simplifica con Douglas–Peucker a ``simplify_m``: los extremos se conservan y todo nodo quitado queda a
        no más de la tolerancia de la poligonal que queda (comprobado con una distancia punto–segmento aparte)."""
        route = self.wiggly()
        simple = axis_of(route, simplify_m=1.5, minimum=LOOSE_M)
        self.assertEqual(len(simple.vertices), 2)
        np.testing.assert_array_equal(simple.vertices[0], route[0])
        np.testing.assert_array_equal(simple.vertices[-1], route[-1])
        for node in route:
            self.assertLessEqual(polyline_distance_m(node, simple.vertices), 1.5 + 1e-12)
        self.assertLessEqual(simple.simplification_m, 1.5)
        self.assertAlmostEqual(simple.simplification_m, 1.0, delta=TOL)  # lo más que se quitó: los nodos a ±1 m

    def test_a_node_beyond_the_end_of_the_chord_is_measured_to_the_chord_not_to_its_line(self) -> None:
        """RF-017-13: Douglas–Peucker mide cada nodo a la **poligonal** que queda (el segmento, no su recta): en una horquilla, el nodo (10, 0) está a
        1,96 m de la recta de (0, 0) a (−5, 1) y a 10 m de ella; con 3 m de tolerancia se conserva (todo nodo quitado queda a ≤ 3 m)."""
        route = np.asarray([[0.0, 0.0], [10.0, 0.0], [-5.0, 1.0]])
        axis = axis_of(route, simplify_m=3.0, minimum=LOOSE_M)
        self.assertEqual(len(axis.vertices), 3)
        for node in route:
            self.assertLessEqual(polyline_distance_m(node, axis.vertices), 3.0)
        longer = np.vstack([route, [[-40.0, 3.0], [-90.0, 3.0]]])
        axis = axis_of(longer, simplify_m=3.0, minimum=LOOSE_M)
        for node in longer:
            self.assertLessEqual(polyline_distance_m(node, axis.vertices), 3.0 + 1e-12)

    def test_a_tolerance_below_the_wiggle_keeps_every_vertex_and_zero_simplifies_nothing(self) -> None:
        """RF-017-13: con una tolerancia menor que el zigzag se conservan los nodos que lo forman; con 0 no se quita ninguno (la línea
        dibujada no se simplifica)."""
        route = self.wiggly(count=12)
        fine = axis_of(route, simplify_m=0.5, minimum=LOOSE_M)
        self.assertEqual(len(fine.vertices), len(route))
        np.testing.assert_array_equal(fine.vertices, route)
        none = axis_of(route, minimum=LOOSE_M)
        self.assertEqual(len(none.vertices), len(route))
        self.assertEqual(none.simplification_m, 0.0)

    def test_the_simplified_polyline_is_a_subsequence_of_the_nodes_and_its_vertices_are_numbered_as_the_route(self) -> None:
        """RF-017-14: los vértices que quedan son nodos de la ruta, en su orden, y el número que dicen los avisos es el del nodo en la ruta
        (el primero es el 1)."""
        t = np.linspace(0.0, 1.0, 41)
        route = np.column_stack([100.0 * np.sin(2.0 * np.pi * t) + 3.0 * t, 100.0 * t * 2.0])
        axis = axis_of(route, simplify_m=2.0, minimum=LOOSE_M)
        self.assertGreater(len(axis.vertices), 3)
        self.assertLess(len(axis.vertices), len(route))
        np.testing.assert_array_equal(axis.vertices, route[axis.kept])
        self.assertTrue(bool((np.diff(axis.kept) > 0).all()))
        self.assertEqual(int(axis.kept[0]), 0)
        self.assertEqual(int(axis.kept[-1]), len(route) - 1)
        for curve in axis.curves:
            np.testing.assert_array_equal([curve.x, curve.y], route[curve.vertex - 1])

    def test_the_exact_origin_and_destination_replace_the_end_nodes(self) -> None:
        """RF-017-13: el origen y el destino exactos (el punto de la capa, no el nodo) son los extremos del eje, bit a bit, y lo que se
        movieron los nodos extremos entra en la desviación de la simplificación."""
        route = np.asarray([[102.0, 202.0], [112.0, 202.0], [112.0, 242.0], [150.0, 242.0]])
        origin, destination = (100.5, 200.25), (152.0, 244.0)
        axis = axis_of(route, origin=origin, destination=destination, minimum=LOOSE_M)
        np.testing.assert_array_equal(axis.vertices[0], origin)
        np.testing.assert_array_equal(axis.vertices[-1], destination)
        np.testing.assert_array_equal(axis.points[0], origin)
        np.testing.assert_array_equal(axis.points[-1], destination)
        np.testing.assert_array_equal(route[0], [102.0, 202.0])  # la ruta que se pasó no cambia
        self.assertAlmostEqual(axis.simplification_m, max(math.hypot(1.5, 1.75), math.hypot(2.0, 2.0)), delta=TOL)
        self.assertGreaterEqual(axis.deviation_m, axis.curve_deviation_m)

    def test_the_deviation_never_underestimates_the_distance_from_the_route_to_the_axis(self) -> None:
        """RF-017-13: la desviación máxima es una cota de la distancia de cada nodo de la ruta al eje (muestreado a 0,05 m), exacta (la de
        los arcos) cuando no se simplifica."""
        t = np.linspace(0.0, 1.0, 120)
        route = np.column_stack([300.0 * t, 40.0 * np.sin(6.0 * np.pi * t) + 8.0 * np.cos(31.0 * t)])
        axis = axis_of(route, simplify_m=3.0, minimum=LOOSE_M)
        dense = axis.sample(np.arange(0.0, axis.length_m, 0.05))[0]
        farthest = 0.0
        for node in route:
            farthest = max(farthest, float(np.hypot(dense[:, 0] - node[0], dense[:, 1] - node[1]).min()))
        self.assertLessEqual(farthest, axis.deviation_m + 0.05)
        self.assertLessEqual(axis.simplification_m, 3.0 + 1e-12)
        exact = axis_of(route, minimum=LOOSE_M)
        self.assertEqual(exact.simplification_m, 0.0)
        self.assertEqual(exact.deviation_m, exact.curve_deviation_m)

    def test_repeated_points_are_dropped_and_the_last_one_keeps_its_place(self) -> None:
        """RF-017-13: un punto que repite al anterior no es un tramo (no tiene dirección): se quita; si es el último, el destino exacto se
        queda y se quita el anterior."""
        points = np.asarray([[0.0, 0.0], [40.0, 0.0], [40.0, 0.0], [40.0, 40.0], [40.0, 40.0]])
        axis = axis_of(points)
        self.assertEqual(len(axis.vertices), 3)
        self.assertAlmostEqual(axis.length_m, rd.corner_by_hand(40.0, RADIUS_M).length_m, delta=TOL)
        np.testing.assert_array_equal(axis.points[-1], [40.0, 40.0])
        near = np.asarray([[0.0, 0.0], [40.0, 0.0], [40.0, 40.0], [40.0, 40.0 + 5e-7]])  # el último repite al anterior a 0,5 µm
        axis = axis_of(near)
        self.assertEqual(len(axis.vertices), 3)
        np.testing.assert_array_equal(axis.points[-1], [40.0, 40.0 + 5e-7])  # el destino exacto es el que se queda
        np.testing.assert_array_equal(axis.vertices[-1], near[-1])
        self.assertEqual(int(axis.kept[-1]), 3)

    def test_simplifying_a_long_route_is_fast(self) -> None:
        """RNF-017-03: simplificar los 1.250 nodos de una ruta de 5 km (malla de 4 m) a 4 m y formar su eje tarda menos de 0,2 s."""
        t = np.arange(1250) * 4.0
        route = np.column_stack([t, 120.0 * np.sin(t / 380.0) + 0.6 * np.sin(t / 7.0)])
        axis = axis_of(route, simplify_m=4.0)
        self.assertLess(len(axis.vertices), 200)
        seconds = best_of(lambda: axis_of(route, simplify_m=4.0), 0.2)
        self.assertLessEqual(seconds, 0.2)


class DrawnLineTest(unittest.TestCase):
    def test_a_drawn_line_gives_the_same_axis_and_is_not_modified(self) -> None:
        """RF-017-13, CE-017-02: la línea dibujada («sobre un eje») da el mismo eje que la ruta con esos vértices y **no cambia** (su
        *hash* es el mismo antes y después, también si es de solo lectura y si lleva Z)."""
        line = np.column_stack([LOCAL_LONG, np.asarray([100.0, 100.5, 101.0])])
        line.flags.writeable = False
        before = digest(line)
        axis = axis_of(line)
        self.assertEqual(digest(line), before)
        self.assertFalse(line.flags.writeable)
        same = axis_of(LOCAL_LONG)
        self.assertEqual(axis.length_m, same.length_m)
        np.testing.assert_array_equal(axis.points, same.points)
        self.assertEqual(axis.curve_count, same.curve_count)
        writable = np.array(LOCAL_SHORT)
        before = digest(writable)
        axis_of(writable)
        self.assertEqual(digest(writable), before)

    def test_the_axis_does_not_alias_its_input(self) -> None:
        """RF-017-13: el eje guarda copias de solo lectura: cambiar la línea después no cambia el eje."""
        line = np.array(LOCAL_LONG)
        axis = axis_of(line)
        copy = np.array(axis.vertices)
        line[1] += 5.0
        np.testing.assert_array_equal(axis.vertices, copy)
        self.assertFalse(axis.vertices.flags.writeable)
        self.assertFalse(axis.points.flags.writeable)
        self.assertFalse(axis.stations.flags.writeable)


class SamplingTest(unittest.TestCase):
    def test_stations_every_w_and_one_at_the_end(self) -> None:
        """RF-017-13 (la base de RF-017-15): el eje se muestrea cada ``w`` m y con una estación en su extremo: 0, 1, …, 71 y 71,416 m."""
        axis = axis_of(LOCAL_LONG)
        s = axis.stations
        self.assertEqual(s[0], 0.0)
        self.assertEqual(s[-1], axis.length_m)
        np.testing.assert_allclose(s[:-1], np.arange(72.0), rtol=0.0, atol=0.0)
        self.assertEqual(len(s), 73)
        self.assertEqual(axis.points.shape, (73, 2))
        self.assertEqual(axis.azimuth.shape, (73,))
        np.testing.assert_array_equal(axis.points[0], LOCAL_LONG[0])
        np.testing.assert_array_equal(axis.points[-1], LOCAL_LONG[2])

    def test_no_duplicate_station_when_the_length_is_a_multiple_of_the_step(self) -> None:
        """RF-017-13: un eje de 100 m con w = 0,5 m tiene 201 estaciones, la última en 100 m exacta, sin repetirla."""
        axis = axis_of(((0.0, 0.0), (60.0, 80.0)), step=0.5)
        self.assertEqual(len(axis.stations), 201)
        self.assertEqual(axis.stations[-1], axis.length_m)
        self.assertTrue(bool((np.diff(axis.stations) > 0.0).all()))
        self.assertAlmostEqual(axis.length_m, 100.0, delta=TOL)

    def test_stations_for_is_what_the_axis_uses(self) -> None:
        """RF-017-13: ``stations_for`` da las mismas estaciones que el eje; con una longitud que no es múltiplo, la última es la longitud."""
        np.testing.assert_array_equal(road_axis.stations_for(71.4159, 1.0), np.append(np.arange(72.0), 71.4159))
        np.testing.assert_array_equal(road_axis.stations_for(10.0, 2.5), [0.0, 2.5, 5.0, 7.5, 10.0])
        self.assertEqual(road_axis.stations_for(3.0, 10.0).tolist(), [0.0, 3.0])

    def test_sample_clips_to_the_axis_and_keeps_the_ends_exact(self) -> None:
        """RF-017-13: ``sample`` evalúa el eje en cualquier abscisa: fuera del eje da sus extremos y, en 0 y en la longitud, los puntos
        exactos."""
        axis = axis_of(LOCAL_LONG)
        xy, _ = axis.sample(np.asarray([-5.0, 0.0, axis.length_m, axis.length_m + 9.0]))
        np.testing.assert_array_equal(xy, [LOCAL_LONG[0], LOCAL_LONG[0], LOCAL_LONG[2], LOCAL_LONG[2]])
        with self.assertRaises(ValueError):
            axis.sample(np.asarray([[0.0, 1.0]]))
        with self.assertRaises(ValueError):
            axis.sample(np.asarray([0.0, math.nan]))

    def test_a_dense_sample_of_500000_stations_is_vectorized(self) -> None:
        """RNF-017-03: el muestreo es con ``searchsorted``, sin bucle por estación: 500.000 estaciones (5 km cada 0,01 m) tardan menos de 0,5 s
        (con un bucle de Python por estación serían segundos)."""
        axis = axis_of(zigzag(163, 31.0, 40.0), step=0.01)
        self.assertGreater(len(axis.stations), 400_000)
        stations = axis.stations
        seconds = best_of(lambda: axis.sample(stations), 0.5)
        self.assertLessEqual(seconds, 0.5)

    def test_five_kilometres_with_163_vertices_in_a_fraction_of_the_budget(self) -> None:
        """RNF-017-03: el eje de 5 km con 163 vértices y w = 1 m (5.014 estaciones) se forma en menos de 2 s (el plan midió 1,6 ms con la
        rasante); son 161 curvas, con la longitud de los tramos menos las tangentes más los arcos."""
        route = zigzag(163, 31.0, 40.0)
        axis = axis_of(route)
        self.assertEqual(axis.curve_count, 161)
        self.assertGreater(axis.length_m, 4_900.0)
        self.assertGreaterEqual(len(axis.stations), 4_900)
        by_hand = 162 * 31.0 + math.fsum(curve.length_m - 2.0 * curve.tangent_m for curve in axis.curves)
        self.assertAlmostEqual(axis.length_m, by_hand, delta=1e-8)
        seconds = best_of(lambda: axis_of(route), 2.0)
        self.assertLessEqual(seconds, 2.0)

    def test_the_points_of_the_axis_are_exact_in_absolute_coordinates(self) -> None:
        """RF-017-13 y regla 4 de AGENTS.md: con coordenadas absolutas (un norte de 4,4 Mm) el eje se forma en el marco local de su primer
        vértice: lo que cambia respecto de las locales es solo el redondeo de la suma (media ulp del norte, 0,5 nm)."""
        shift = np.asarray(rd.absolute([(0.0, 0.0)])[0])
        absolute = axis_of(LOCAL_LONG + shift)
        local = axis_of(LOCAL_LONG)
        tolerance = TOL + 2.0 * float(np.spacing(np.abs(absolute.points).max()))
        np.testing.assert_allclose(absolute.points - shift, local.points, rtol=0.0, atol=tolerance)
        self.assertAlmostEqual(absolute.length_m, local.length_m, delta=TOL)
        self.assertEqual(absolute.points.dtype, np.float64)


class NoticesTest(unittest.TestCase):
    def test_only_the_reduced_curves_make_a_notice_in_the_order_of_the_route(self) -> None:
        """RF-017-14: un aviso por curva reducida, en el orden del eje, con el vértice, el radio y su lugar; las que mantienen su radio de
        diseño no avisan."""
        points = np.asarray([[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [115.0, 100.0], [115.0, 160.0]])
        axis = axis_of(points, minimum=5.0)
        self.assertEqual(axis.curve_count, 3)
        notices = axis.notices("RDW-007")
        reduced = [curve for curve in axis.curves if curve.reduced]
        self.assertEqual(len(notices), len(reduced))
        self.assertGreaterEqual(len(notices), 1)
        self.assertLess(len(notices), axis.curve_count)
        for notice, curve in zip(notices, reduced, strict=True):
            self.assertEqual(notice.values["vertex"], curve.vertex)
            self.assertEqual(notice.values["x"], curve.x)
            self.assertEqual(notice.values["y"], curve.y)
            self.assertEqual(notice.values["fitted"], curve.radius_m)
            self.assertEqual(notice.values["radius"], RADIUS_M)
            self.assertIn("RDW-007", notice.text("es"))
        self.assertEqual([curve.radius_m for curve in axis.curves][0], RADIUS_M)
        self.assertAlmostEqual(axis.min_radius_m, 7.5, delta=TOL)  # el menor de 20, 7,5 y 7,5 m: 20·15/40


class ValidationTest(unittest.TestCase):
    def test_wrong_inputs_are_errors_of_the_program(self) -> None:
        """Las entradas que no son de su forma son ``TypeError`` o ``ValueError`` (la preparación de la pista las rechazó antes con su capa,
        su pista, su campo y su valor, RF-017-04)."""
        with self.assertRaises(ValueError):
            axis_of(((0.0, 0.0),))  # un solo punto
        with self.assertRaises(ValueError):
            axis_of(((0.0, 0.0), (0.0, 0.0)))  # sin longitud
        with self.assertRaises(ValueError):
            axis_of(((0.0, 0.0), (math.nan, 1.0)))
        with self.assertRaises(ValueError):
            axis_of(np.zeros((3, 1)))
        with self.assertRaises(ValueError):
            axis_of(LOCAL_LONG, 10.0, 12.0)  # Rmín mayor que R
        for bad in (0.0, -1.0, math.inf, math.nan):
            with self.assertRaises(ValueError, msg=str(bad)):
                axis_of(LOCAL_LONG, radius=bad)
            with self.assertRaises(ValueError, msg=str(bad)):
                axis_of(LOCAL_LONG, step=bad)
        with self.assertRaises(TypeError):
            axis_of(LOCAL_LONG, radius="20")
        with self.assertRaises(TypeError):
            axis_of(LOCAL_LONG, step=True)
        with self.assertRaises(ValueError):
            axis_of(LOCAL_LONG, simplify_m=-1.0)
        with self.assertRaises(ValueError):
            axis_of(LOCAL_LONG, origin=(1.0, 2.0, 3.0))

    def test_the_module_is_lazy_and_pure(self) -> None:
        """RNF-001-03: ni ``design.model`` ni el arranque cargan el módulo (lo fija ``test_lazy_registration``) y no importa ``bpy``."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(road_axis))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertEqual(imported - {"__future__", "math", "numbers", "dataclasses", "collections", "typing", "numpy"}, set())


if __name__ == "__main__":
    unittest.main()
