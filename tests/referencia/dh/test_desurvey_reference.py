# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de las trazas de los sondeos (spec 005, T06; RF-005-20; CE-005-02;
plan 005 §5.4 y §7).

Convenio (plan 005 §5.4): dirección unitaria t = (sin I·sin A, sin I·cos A, −cos I) (E, N,
Z arriba), con I = 90° + θ, A el azimut de cuadrícula y θ la inclinación interna (desde la
horizontal, negativa hacia abajo). Las bocas, en coordenadas absolutas (EPSG:25830), y la
solución, relativa a la boca.

**Recto, −60° / 45°, por los tres métodos.** Estaciones cada 50 m de 0 a 500 m, todas con
45° / −60° (I = 30°): t = (sin 30°·sin 45°, sin 30°·cos 45°, −cos 30°) y p(s) = boca + s·t;
a 500 m, (+176,776695; +176,776695; −433,012702) m. Mínima curvatura, tangente y tangente
equilibrada dan la misma recta: tolerancia 10⁻⁶ m en cada estación (tarea T06).

**Arco de circunferencia en un plano inclinado** (3°/30 m, R = 30/(3·π/180) =
572,957795 m). Dirección inicial t₀ = 30° / −55°; el centro está en la dirección
u = cos 60°·h + sin 60°·r, con h = (cos I₀·sin A₀, cos I₀·cos A₀, sin I₀) (hacia arriba, en
el plano vertical de t₀) y r = (cos A₀, −sin A₀, 0) (a la derecha): el arco gira y levanta a
la vez (ni el azimut ni la inclinación son constantes). Solución analítica, con σ = s/R:

    p(s) = boca + R·[sin σ·t₀ + (1 − cos σ)·u],   t(s) = cos σ·t₀ + sin σ·u.

Estaciones cada 30 m de 0 a 480 m y la última a 500 m, con su azimut y su inclinación
sacados de t(s):

====== ============ ============ ============ ========== ==========
s (m)  ΔE (m)       ΔN (m)       ΔZ (m)       A (°)      θ (°)
====== ============ ============ ============ ========== ==========
0      0            0            0            30,000000  −55,000000
30     9,349433     14,833655    −24,338143   34,361760  −53,419475
240    114,129204   111,880782   −176,691595  57,024849  −39,174574
480    303,114905   196,658273   −294,419611  73,082349  −19,572205
500    321,288736   201,993691   −300,838691  74,190023  −17,869394
====== ============ ============ ============ ========== ==========

La mínima curvatura reproduce el arco exactamente (Sawaryn y Thorogood, 2005, SPE Drilling &
Completion 20(1)): tolerancia 1 mm en cada estación hasta 500 m (RF-005-20, CE-005-02); el
14/10/2026 dio 4,7·10⁻¹⁰ m, el redondeo de las coordenadas absolutas. La tangente y la
tangente equilibrada no son exactas en un arco: su error a 500 m pasa de 1 cm (12,5 m y
0,108 m ese día; la prueba lo comprueba para saber que el caso distingue los métodos).

**Tres estaciones calculadas a mano** (mínima curvatura, con la fórmula clásica del ángulo
de *dogleg*, cos β = cos(I₂ − I₁) − sin I₁·sin I₂·(1 − cos(A₂ − A₁)), distinta de la que usa
el código; RF = (2/β)·tan(β/2); ΔE = ΔMD/2·(sin I₁·sin A₁ + sin I₂·sin A₂)·RF;
ΔN = ΔMD/2·(sin I₁·cos A₁ + sin I₂·cos A₂)·RF; ΔZ = −ΔMD/2·(cos I₁ + cos I₂)·RF):

====== =========== ============ ============== ============ ============ ============
MD (m) A / θ (°)   β (°)        RF             E (m)        N (m)        Z (m)
====== =========== ============ ============== ============ ============ ============
0      40 / −60    —            —              0            0            0
30     43 / −58    2,526800454  1,000162106286 10,243628    11,560583    −25,715270
75     47 / −55    3,723443962  1,000352084240 27,819869    29,088326    −63,240481
====== =========== ============ ============== ============ ============ ============

Tolerancia 10⁻⁶ m (los valores de la tabla, redondeados a la micra).
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

desurvey = import_geoblender("drillholes.desurvey")
model = import_geoblender("drillholes.model")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
V5782 = CATALOG.vertical(5782)

Method = desurvey.Method

STRAIGHT_TOLERANCE_M = 1e-6  # tarea T06
ARC_TOLERANCE_M = 1e-3  # RF-005-20, CE-005-02
HAND_TOLERANCE_M = 1e-6  # la tabla, a la micra
INEXACT_ERROR_M = 1e-2  # la tangente y la tangente equilibrada, en el arco

COLLAR = (700_100.5, 4_400_200.5, 812.25)

# El recto: 45° / −60°, estaciones cada 50 m hasta 500 m.
STRAIGHT_BOTTOM = (176.776695, 176.776695, -433.012702)

# El arco: 3°/30 m desde 30° / −55°, centro a 60° del lado alto hacia la derecha.
ARC_RADIUS_M = 30.0 / math.radians(3.0)
ARC_START = (30.0, -55.0)
ARC_TILT_DEG = 60.0
ARC_DEPTHS = (*range(0, 481, 30), 500)
ARC_TABLE = {  # s: (ΔE, ΔN, ΔZ, A, θ), los de la tabla del módulo
    0: (0.0, 0.0, 0.0, 30.0, -55.0),
    30: (9.349433, 14.833655, -24.338143, 34.361760, -53.419475),
    240: (114.129204, 111.880782, -176.691595, 57.024849, -39.174574),
    480: (303.114905, 196.658273, -294.419611, 73.082349, -19.572205),
    500: (321.288736, 201.993691, -300.838691, 74.190023, -17.869394),
}

# Las tres estaciones calculadas a mano: (MD, A, θ) y la posición relativa a la boca.
HAND_STATIONS = ((0.0, 40.0, -60.0), (30.0, 43.0, -58.0), (75.0, 47.0, -55.0))
HAND_POSITIONS = (
    (0.0, 0.0, 0.0),
    (10.243628, 11.560583, -25.715270),
    (27.819869, 29.088326, -63.240481),
)


def _dset(depth: float, stations) -> object:
    """Un sondeo «R-1» con su boca en :data:`COLLAR` y las estaciones (MD, A, θ) dadas."""
    collar = model.Collar("R-1", *COLLAR, depth)
    surveys = [model.SurveyStation("R-1", md, azimuth, inclination)
               for md, azimuth, inclination in stations]
    return model.DrillholeSet.from_records(crs=H25830, vertical=V5782, collars=[collar],
                                           surveys=surveys)


def _relative(traces) -> np.ndarray:
    return traces.xyz - np.array(COLLAR)


def _arc() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """El arco analítico: las profundidades, las posiciones relativas a la boca y (A, θ) en
    cada estación (las fórmulas del módulo)."""
    a0, i0 = math.radians(ARC_START[0]), math.radians(90.0 + ARC_START[1])
    t0 = np.array([math.sin(i0) * math.sin(a0), math.sin(i0) * math.cos(a0), -math.cos(i0)])
    high = np.array([math.cos(i0) * math.sin(a0), math.cos(i0) * math.cos(a0), math.sin(i0)])
    right = np.array([math.cos(a0), -math.sin(a0), 0.0])
    tilt = math.radians(ARC_TILT_DEG)
    u = math.cos(tilt) * high + math.sin(tilt) * right
    md = np.array(ARC_DEPTHS, dtype=np.float64)
    sigma = md / ARC_RADIUS_M
    position = ARC_RADIUS_M * (np.sin(sigma)[:, None] * t0
                               + (1.0 - np.cos(sigma))[:, None] * u)
    tangent = np.cos(sigma)[:, None] * t0 + np.sin(sigma)[:, None] * u
    azimuth = np.degrees(np.arctan2(tangent[:, 0], tangent[:, 1])) % 360.0
    inclination = np.degrees(np.arctan2(tangent[:, 2], np.hypot(tangent[:, 0], tangent[:, 1])))
    return md, position, np.column_stack([azimuth, inclination])


class StraightHoleTest(unittest.TestCase):
    def test_three_methods(self) -> None:
        """RF-005-20, CE-005-02: un recto de 500 m a −60° / 45° da la recta analítica por
        mínima curvatura, tangente y tangente equilibrada, a ≤ 10⁻⁶ m en cada estación, y
        cada traza dice su método."""
        stations = [(float(md), 45.0, -60.0) for md in range(0, 501, 50)]
        dset = _dset(500.0, stations)
        i = math.radians(30.0)
        direction = np.array([math.sin(i) * math.sin(math.radians(45.0)),
                              math.sin(i) * math.cos(math.radians(45.0)), -math.cos(i)])
        expected = np.arange(0.0, 501.0, 50.0)[:, None] * direction
        np.testing.assert_allclose(expected[-1], STRAIGHT_BOTTOM, rtol=0, atol=5e-7)
        for method in Method:
            with self.subTest(method=method):
                traces = desurvey.desurvey(dset, method)
                self.assertIs(traces.method, method)
                np.testing.assert_array_equal(traces.md, np.arange(0.0, 501.0, 50.0))
                error = np.abs(_relative(traces) - expected).max()
                self.assertLessEqual(error, STRAIGHT_TOLERANCE_M)
                np.testing.assert_allclose(traces.tangent, np.tile(direction, (11, 1)),
                                           rtol=0, atol=1e-15)
                self.assertEqual(traces.warnings, ())


class InclinedArcTest(unittest.TestCase):
    def test_table_matches_formula(self) -> None:
        """RF-005-20: la tabla del módulo es la de las fórmulas analíticas del arco."""
        md, position, angles = _arc()
        for depth, (east, north, up, azimuth, inclination) in ARC_TABLE.items():
            k = ARC_DEPTHS.index(depth)
            np.testing.assert_allclose(position[k], (east, north, up), rtol=0, atol=5e-7)
            np.testing.assert_allclose(angles[k], (azimuth, inclination), rtol=0, atol=5e-7)
        self.assertEqual(md[-1], 500.0)
        self.assertAlmostEqual(ARC_RADIUS_M, 572.957795, places=6)

    def test_minimum_curvature_reproduces_the_arc(self) -> None:
        """RF-005-20, CE-005-02: por mínima curvatura, el arco en un plano inclinado
        (3°/30 m) se reproduce con error ≤ 1 mm en cada estación hasta 500 m; la tangente y
        la tangente equilibrada se alejan más de 1 cm a 500 m."""
        md, position, angles = _arc()
        stations = [(float(d), float(a), float(t))
                    for d, (a, t) in zip(md, angles, strict=True)]
        dset = _dset(500.0, stations)
        traces = desurvey.desurvey(dset)
        self.assertIs(traces.method, Method.MINIMUM_CURVATURE)
        np.testing.assert_array_equal(traces.md, md)
        error = np.linalg.norm(_relative(traces) - position, axis=1)
        self.assertLessEqual(error.max(), ARC_TOLERANCE_M)
        for method in (Method.TANGENT, Method.BALANCED_TANGENT):
            with self.subTest(method=method):
                other = desurvey.desurvey(dset, method)
                bottom = np.linalg.norm(_relative(other)[-1] - position[-1])
                self.assertGreater(bottom, INEXACT_ERROR_M)


class HandCalculatedTest(unittest.TestCase):
    def test_three_stations_by_hand(self) -> None:
        """RF-005-20: tres estaciones (0, 30 y 75 m) por mínima curvatura dan las posiciones
        de la tabla del módulo, calculadas a mano con la fórmula clásica, a ≤ 10⁻⁶ m."""
        traces = desurvey.desurvey(_dset(75.0, HAND_STATIONS))
        np.testing.assert_array_equal(traces.md, [0.0, 30.0, 75.0])
        error = np.abs(_relative(traces) - np.array(HAND_POSITIONS)).max()
        self.assertLessEqual(error, HAND_TOLERANCE_M)
        self.assertEqual(traces.xyz[0].tolist(), list(COLLAR))


if __name__ == "__main__":
    unittest.main()
