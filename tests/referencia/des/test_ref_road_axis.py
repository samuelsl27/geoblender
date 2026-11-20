# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia del eje de la pista con curvas (spec 017, T10; HU-017-1 y HU-017-4; RF-017-13 y RF-017-14; CE-017-02; plan 017 §5.4 A4 y §7.3):
la curva circular de radio ``R`` en un vértice, el radio que cabe y el rechazo, contra el **cálculo analítico** de arcos y tangentes.

Verifica **de forma independiente** lo que hace ``design.road_axis``: cada cifra y cada posición del eje salen de la geometría a mano (la
tangente ``T = R·tan(Δ/2)``, el arco ``R·Δ``, la longitud ``2·tramo − 2·T + arco``, la posición en el tramo recto, en el círculo de centro
conocido y en el tramo recto de salida) y de las cifras de ``tests.support.road_data`` (``CORNER_LONG``, ``CORNER_SHORT`` y ``corner_by_hand``, hechas a
mano); **ningún** valor esperado se calcula llamando al código bajo prueba. Tolerancia: ≤ 10⁻⁹ m del cálculo analítico (RF-017-13). Todo es sintético,
en el dominio y sin Blender.

- **CE-017-02 · la curva** (RF-017-13): dos tramos rectos perpendiculares de 40 m con R = 20 m dan una tangente de 20 m, un arco de 31,416 m (π·R/2)
  y un eje de 71,416 m (20 + π·10 + 20) a ≤ 10⁻⁹ m del arco analítico en cada una de sus estaciones, con el radio mínimo real de 20 m; con cualquier
  otro ángulo (60°: T = R·tan 30°) y a la derecha lo mismo.
- **CE-017-02 · el radio que cabe** (RF-017-14): con tramos de 15 m y Rmín = 12 m el radio se reduce a 15 m (el mayor que cabe: la tangente es el
  tramo entero) con el aviso del vértice; con Rmín = 16 m el rechazo nombra el vértice, los tramos y el radio que cabría (15 m).
- **CE-017-02 · la línea dibujada** («sobre un eje», RF-017-13): da lo mismo que la ruta y la línea no cambia (su *hash* antes y después).
"""

from __future__ import annotations

import hashlib
import math
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender

road_axis = import_geoblender("design.road_axis")
messages = import_geoblender("design.messages")

TOL = 1e-9
"""Metros: RF-017-13 pide el eje a ≤ 10⁻⁹ m del cálculo analítico de arcos y tangentes."""
LONG = np.asarray(rd.CORNER_LONG)
"""(60, 60) → (100, 60) → (100, 100): dos tramos de 40 m, un giro de 90° a la izquierda."""
SHORT = np.asarray(rd.CORNER_SHORT)
"""(60, 140) → (75, 140) → (75, 155): dos tramos de 15 m."""


def by_hand_left_corner(origin: tuple[float, float], leg: float, radius: float, s: np.ndarray) -> np.ndarray:
    """El eje analítico de dos tramos perpendiculares de ``leg`` m —primero al este, luego al norte— con un arco de radio ``radius`` m (con
    ``radius ≤ leg`` la tangente es ``T = R·tan 45° = R``), en las abscisas ``s`` (m): el tramo recto de entrada (``s ≤ leg − R``), el arco, de centro
    ``(x₀ + leg − R, y₀ + R)``, de ángulo ``φ = (s − (leg − R))/R``, y el tramo recto de salida; **sin usar el código bajo prueba**."""
    x0, y0 = origin
    start = leg - radius
    arc_end = start + math.pi * radius / 2.0
    out = np.empty((len(s), 2))
    first = s <= start
    arc = (s > start) & (s < arc_end)
    last = s >= arc_end
    out[first] = np.column_stack([x0 + s[first], np.full(first.sum(), y0)])
    phi = (s[arc] - start) / radius
    out[arc] = np.column_stack([x0 + start + radius * np.sin(phi), y0 + radius - radius * np.cos(phi)])
    out[last] = np.column_stack([np.full(last.sum(), x0 + leg), y0 + radius + (s[last] - arc_end)])
    return out


def digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


class CurveTest(unittest.TestCase):
    def test_two_perpendicular_legs_of_40_m_with_r_20_m(self) -> None:
        """CE-017-02, RF-017-13: tangente de 20 m, arco de π·R/2 = 31,416 m, eje de 71,416 m y radio mínimo real de 20 m, y **el eje a ≤ 10⁻⁹ m del
        arco analítico** en cada estación (cada 0,5 m) y en 2.000 abscisas cualesquiera."""
        axis = road_axis.axis_of(LONG, 20.0, 12.0, 0.5)
        self.assertEqual(axis.curve_count, 1)
        curve = axis.curves[0]
        self.assertAlmostEqual(curve.tangent_m, 20.0 * math.tan(math.radians(45.0)), delta=TOL)
        self.assertAlmostEqual(curve.tangent_m, 20.0, delta=TOL)
        self.assertAlmostEqual(curve.length_m, math.pi * 20.0 / 2.0, delta=TOL)
        self.assertAlmostEqual(curve.length_m, 31.415926535897932, delta=TOL)
        self.assertAlmostEqual(axis.length_m, 20.0 + math.pi * 20.0 / 2.0 + 20.0, delta=TOL)
        self.assertAlmostEqual(axis.length_m, 71.41592653589793, delta=TOL)
        self.assertAlmostEqual(axis.min_radius_m, 20.0, delta=TOL)
        self.assertAlmostEqual(axis.curve_deviation_m, 20.0 * (1.0 / math.cos(math.radians(45.0)) - 1.0), delta=TOL)
        expected = by_hand_left_corner((60.0, 60.0), 40.0, 20.0, axis.stations)
        np.testing.assert_allclose(axis.points, expected, rtol=0.0, atol=TOL)
        rng = np.random.default_rng(1120)
        s = np.sort(rng.uniform(0.0, axis.length_m, 2000))
        xy, heading = axis.sample(s)
        np.testing.assert_allclose(xy, by_hand_left_corner((60.0, 60.0), 40.0, 20.0, s), rtol=0.0, atol=TOL)
        arc = (s > 20.0) & (s < 20.0 + 10.0 * math.pi)
        np.testing.assert_allclose(np.hypot(xy[arc, 0] - 80.0, xy[arc, 1] - 80.0), 20.0, rtol=0.0, atol=TOL)
        # el azimut (desde el norte, horario): este (90°) en el tramo de entrada, norte (0°) en el de salida y, en el arco, el del círculo
        np.testing.assert_allclose(heading[s < 20.0], math.pi / 2.0, rtol=0.0, atol=TOL)
        np.testing.assert_allclose(heading[s > 20.0 + 10.0 * math.pi], 0.0, rtol=0.0, atol=TOL)
        np.testing.assert_allclose(heading[arc], math.pi / 2.0 - (s[arc] - 20.0) / 20.0, rtol=0.0, atol=TOL)

    def test_the_same_curve_in_absolute_coordinates(self) -> None:
        """RF-017-13 y regla 4 de AGENTS.md: con las coordenadas absolutas de la cantera (un norte de 4,4 Mm, donde un ulp es de 0,93 nm) el eje
        sigue a ≤ 10⁻⁹ m + 2 ulp del arco analítico: el cálculo es en el marco local del primer vértice y solo el último redondeo es absoluto."""
        shift = np.asarray(rd.absolute([(0.0, 0.0)])[0])
        axis = road_axis.axis_of(LONG + shift, 20.0, 12.0, 0.5)
        tolerance = TOL + 2.0 * float(np.spacing(np.abs(axis.points).max()))
        np.testing.assert_allclose(axis.points, by_hand_left_corner((60.0, 60.0), 40.0, 20.0, axis.stations) + shift, rtol=0.0, atol=tolerance)
        self.assertAlmostEqual(axis.length_m, 71.41592653589793, delta=TOL)

    def test_a_right_turn_and_any_other_angle(self) -> None:
        """RF-017-13: a la derecha es la imagen en el espejo; con un giro de 60° (tramos de 50 m, R = 20 m) la tangente es R·tan 30°, el arco R·π/3
        y el eje 100 − 2·T + arco; la desviación del vértice al arco, R·(1/cos 30° − 1); los avisos no aparecen (cabe)."""
        mirrored = np.column_stack([-LONG[:, 0], LONG[:, 1]])
        right = road_axis.axis_of(mirrored, 20.0, 12.0, 0.5)
        expected = by_hand_left_corner((60.0, 60.0), 40.0, 20.0, right.stations)
        np.testing.assert_allclose(right.points, np.column_stack([-expected[:, 0], expected[:, 1]]), rtol=0.0, atol=TOL)
        self.assertGreater(right.curves[0].deflection, 0.0)  # horario
        turn = math.radians(60.0)
        points = np.asarray([[0.0, 0.0], [50.0, 0.0], [50.0 + 50.0 * math.cos(turn), 50.0 * math.sin(turn)]])
        axis = road_axis.axis_of(points, 20.0, 12.0, 1.0)
        tangent = 20.0 * math.tan(turn / 2.0)
        curve = axis.curves[0]
        self.assertAlmostEqual(curve.tangent_m, tangent, delta=TOL)
        self.assertAlmostEqual(curve.tangent_m, 11.547005383792515, delta=TOL)
        self.assertAlmostEqual(curve.length_m, 20.0 * turn, delta=TOL)
        self.assertAlmostEqual(axis.length_m, 100.0 - 2.0 * tangent + 20.0 * turn, delta=TOL)
        self.assertAlmostEqual(axis.curve_deviation_m, 20.0 * (1.0 / math.cos(turn / 2.0) - 1.0), delta=TOL)
        self.assertAlmostEqual(axis.curve_deviation_m, 3.0940107675850305, delta=TOL)
        self.assertAlmostEqual(curve.deflection, -turn, delta=TOL)  # a la izquierda
        self.assertEqual(axis.notices("RDW-001"), ())
        mid = axis.sample(np.asarray([50.0 - tangent + 0.5 * curve.length_m]))[0][0]
        centre = np.asarray([50.0 - tangent, 20.0])  # el centro del arco: a R del punto de tangencia, a la izquierda
        self.assertAlmostEqual(float(np.hypot(*(mid - centre))), 20.0, delta=TOL)


class FitTest(unittest.TestCase):
    def test_legs_of_15_m_and_rmin_12_m_reduce_the_radius_to_15_m(self) -> None:
        """CE-017-02, RF-017-14: con tramos de 15 m y Rmín = 12 m el radio baja a 15 m —el mayor que cabe: T = R = 15 m es el tramo entero— con el
        aviso del vértice; el eje es el cuarto de círculo de 15 m de radio del origen al destino (π·15/2 = 23,562 m), a ≤ 10⁻⁹ m del analítico."""
        hand = rd.corner_by_hand(15.0, 20.0)
        axis = road_axis.axis_of(SHORT, 20.0, 12.0, 0.25)
        self.assertEqual(axis.curve_count, 1)
        curve = axis.curves[0]
        self.assertAlmostEqual(curve.radius_m, 15.0, delta=TOL)
        self.assertAlmostEqual(curve.radius_m, hand.fitted_radius_m, delta=TOL)
        self.assertAlmostEqual(curve.tangent_m, 15.0, delta=TOL)
        self.assertAlmostEqual(axis.length_m, math.pi * 15.0 / 2.0, delta=TOL)
        self.assertAlmostEqual(axis.length_m, hand.length_m, delta=TOL)
        self.assertAlmostEqual(axis.min_radius_m, 15.0, delta=TOL)
        np.testing.assert_allclose(axis.points, by_hand_left_corner((60.0, 140.0), 15.0, 15.0, axis.stations), rtol=0.0, atol=TOL)
        (notice,) = axis.notices("RDW-001")
        self.assertEqual(notice.code, "des.road_radius_reduced")
        self.assertEqual((notice.values["vertex"], notice.values["x"], notice.values["y"]), (2, 75.0, 140.0))
        self.assertAlmostEqual(notice.values["radius"], 20.0, delta=TOL)
        self.assertAlmostEqual(notice.values["fitted"], 15.0, delta=TOL)

    def test_rmin_16_m_rejects_naming_the_vertex_the_legs_and_the_radius_that_would_fit(self) -> None:
        """CE-017-02, RF-017-14: con Rmín = 16 m el rechazo nombra el vértice (el segundo), los tramos (15 m y 15 m) y el radio que cabría (15 m) y qué
        hacer, y **no baja de Rmín por su cuenta**: ningún eje."""
        with self.assertRaises(road_axis.RadiusBelowMinimum) as caught:
            road_axis.axis_of(SHORT, 20.0, 16.0, 1.0)
        profile = rd.road_profile(rd.profile_with(min_radius_m=16.0))
        error = caught.exception.error(layer="trazados", entity="Pista A", profile=profile)
        self.assertIsInstance(error, messages.DesignError)
        self.assertEqual(error.code, "des.road_radius_below_min")
        text = error.text_in("es")
        for expected in ("vértice 2", "15 m y 15 m", "radio de 15 m", "(16 m)", "mueva el vértice", "simplifique", "otro perfil", "no se crea nada"):
            self.assertIn(expected, text)
        self.assertEqual(error.text_in("en").count("15 m"), 3)
        self.assertEqual(caught.exception.curve.vertex, 2)
        self.assertAlmostEqual(caught.exception.curve.radius_m, 15.0, delta=TOL)


class DrawnLineTest(unittest.TestCase):
    def test_a_drawn_line_gives_the_same_curve_and_does_not_change(self) -> None:
        """CE-017-02, RF-017-13: la línea dibujada («sobre un eje») da lo mismo que la ruta con esos vértices (la misma longitud, curva y puntos) y la
        línea no cambia: su *hash* es el de antes, con 2 o 3 coordenadas por vértice."""
        for line in (np.array(LONG), np.column_stack([LONG, [100.0, 101.0, 102.0]])):
            before = digest(line)
            drawn = road_axis.axis_of(line, 20.0, 12.0, 0.5)
            self.assertEqual(digest(line), before)
            route = road_axis.axis_of(LONG, 20.0, 12.0, 0.5)
            self.assertEqual(drawn.length_m, route.length_m)
            np.testing.assert_array_equal(drawn.points, route.points)
            np.testing.assert_allclose(drawn.points, by_hand_left_corner((60.0, 60.0), 40.0, 20.0, drawn.stations), rtol=0.0, atol=TOL)

    def test_the_five_kilometre_route_of_the_plan_is_a_valid_axis(self) -> None:
        """RNF-017-03 (el plan §7.3: 163 vértices, 161 curvas y 5.013 m): un camino de 163 vértices con tramos de 31,3 m y giros de ±40° da 161
        curvas, una estación cada metro y la longitud de la fórmula a mano 162·31,3 − 161·(2·T − R·Δ) con T = R·tan 20° y Δ = 40°."""
        heading, points = 0.0, [(0.0, 0.0)]
        for k in range(1, 163):
            points.append((points[-1][0] + 31.3 * math.sin(heading), points[-1][1] + 31.3 * math.cos(heading)))
            heading += math.radians(40.0 if k % 2 else -40.0)
        axis = road_axis.axis_of(np.asarray(points), 20.0, 12.0, 1.0)
        tangent, arc = 20.0 * math.tan(math.radians(20.0)), 20.0 * math.radians(40.0)
        self.assertEqual(axis.curve_count, 161)
        self.assertAlmostEqual(axis.length_m, 162 * 31.3 - 161 * (2.0 * tangent - arc), delta=1e-8)
        self.assertAlmostEqual(axis.length_m, 4_974.5, delta=1.0)
        self.assertEqual(len(axis.stations), int(math.floor(axis.length_m)) + 2)
        self.assertEqual(axis.min_radius_m, 20.0)
        self.assertEqual(axis.notices("RDW-001"), ())


if __name__ == "__main__":
    unittest.main()
