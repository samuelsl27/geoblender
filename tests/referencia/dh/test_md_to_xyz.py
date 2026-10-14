# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la posición de cualquier profundidad de un sondeo y de su polilínea
densificada (spec 005, T07; RF-005-21; plan 005 §5.4 y §7).

Convenio (plan 005 §5.4): dirección unitaria t = (sin I·sin A, sin I·cos A, −cos I) (E, N,
Z arriba), con I = 90° + θ. La boca, en coordenadas absolutas (EPSG:25830), y la solución,
relativa a la boca. Entre dos estaciones a ΔMD, con s la distancia desde la primera y
f = s/ΔMD: mínima curvatura, el arco de circunferencia entre ellas,
p = p₁ + s/2·(t₁ + t(f))·RF(f·β) con t(f) = slerp(t₁, t₂, f); tangente, p₁ + s·t₁; tangente
equilibrada, t₁ hasta ΔMD/2 y t₂ después.

**Recto, −60° / 45°** (estaciones cada 50 m de 0 a 500 m, I = 30°): p(s) = boca + s·t con
t = (sin 30°·sin 45°, sin 30°·cos 45°, −cos 30°), por los tres métodos. Tolerancia 10⁻⁶ m:

======== ============ ============ =============
s (m)    ΔE (m)       ΔN (m)       ΔZ (m)
======== ============ ============ =============
12,5     4,419417     4,419417     −10,825318
123,456  43,648287    43,648287    −106,916032
499,999  176,776342   176,776342   −433,011836
======== ============ ============ =============

**Arco en un plano inclinado** (el de ``test_desurvey_reference``: 3°/30 m,
R = 572,957795 m, desde 30° / −55°, el centro a 60° del lado alto hacia la derecha;
estaciones cada 30 m hasta 480 m y la última a 500 m). Con σ = s/R,
p(s) = boca + R·[sin σ·t₀ + (1 − cos σ)·u]. Profundidades entre estaciones, por mínima
curvatura, con error ≤ 1 mm (RF-005-21); en las estaciones, la posición de la traza, exacta
(la misma curva):

======== ============ ============ =============
s (m)    ΔE (m)       ΔN (m)       ΔZ (m)
======== ============ ============ =============
7,5      2,197718     3,721538     −6,129387
100      36,844410    48,739726    −79,003605
333,3    180,265416   149,000002   −230,856496
499      320,373326   201,734011   −300,531134
======== ============ ============ =============

**Dos estaciones a mano**: 0 m con 40° / −60° (t₁ = (0,3213938048; 0,3830222216;
−0,8660254038)) y 60 m con 50° / −50° (t₂ = (0,4924038765; 0,4131759112; −0,7660444431)),
fondo a 60 m; β = 11,499898°. Tangente equilibrada: s·t₁ hasta su punto medio (30 m) y
30·t₁ + (s − 30)·t₂ después; tangente: s·t₁; mínima curvatura: el arco de radio 60/β,
R·[sin σ·t₁ + (1 − cos σ)·w] con w = (t₂ − cos β·t₁)/sin β (otra fórmula que la del código).
Tolerancia 10⁻⁶ m (la tabla, a la micra):

====== ================================ ================================
s (m)  tangente equilibrada (ΔE, ΔN, ΔZ) mínima curvatura (ΔE, ΔN, ΔZ)
====== ================================ ================================
15     4,820907; 5,745333; −12,990381    5,153800; 5,814342; −12,829052
30     9,641814; 11,490667; −25,980762   10,964458; 11,756885; −25,314052
45     17,027872; 17,688305; −37,471429  17,417346; 17,812671; −37,423572
====== ================================ ================================

**Polilínea densificada del arco**, cada ≤ 2 m, con los límites de unos tramos (12,34;
87,6; 250,05 y 499,5 m): contiene las estaciones y los límites, ningún segmento pasa de 2 m
(salvo el redondeo de float64: 10⁻⁹ m en profundidad y 10⁻⁶ m en el espacio), no tiene más
vértices que los necesarios y cada vértice está sobre el arco a ≤ 1 mm.
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

POSITION_TOLERANCE_M = 1e-3  # RF-005-21
EXACT_TOLERANCE_M = 1e-6  # el recto y la tabla a mano, a la micra
STEP_M = 2.0  # dh.desurvey.trace_step_m por defecto (plan §5.2.4)
MD_ROUNDING_M = 1e-9
XYZ_ROUNDING_M = 1e-6

COLLAR = (700_100.5, 4_400_200.5, 812.25)

STRAIGHT = {  # s: (ΔE, ΔN, ΔZ), los de la tabla del módulo
    12.5: (4.419417, 4.419417, -10.825318),
    123.456: (43.648287, 43.648287, -106.916032),
    499.999: (176.776342, 176.776342, -433.011836),
}
STRAIGHT_DEPTHS = (0.0, 12.5, 37.5, 50.0, 123.456, 250.0, 333.3, 499.999, 500.0)

ARC_RADIUS_M = 30.0 / math.radians(3.0)
ARC_START = (30.0, -55.0)
ARC_TILT_DEG = 60.0
ARC_STATIONS = (*(float(s) for s in range(0, 481, 30)), 500.0)
ARC_TABLE = {
    7.5: (2.197718, 3.721538, -6.129387),
    100.0: (36.844410, 48.739726, -79.003605),
    333.3: (180.265416, 149.000002, -230.856496),
    499.0: (320.373326, 201.734011, -300.531134),
}
ARC_DEPTHS = (0.0, 0.25, 7.5, 15.0, 29.999, 45.0, 100.0, 222.2, 333.3, 479.5, 490.0, 499.0,
              500.0)
ARC_LIMITS = (12.34, 87.6, 250.05, 499.5)

HAND_STATIONS = ((0.0, 40.0, -60.0), (60.0, 50.0, -50.0))
HAND_BALANCED = {
    15.0: (4.820907, 5.745333, -12.990381),
    30.0: (9.641814, 11.490667, -25.980762),
    45.0: (17.027872, 17.688305, -37.471429),
}
HAND_CURVATURE = {
    15.0: (5.153800, 5.814342, -12.829052),
    30.0: (10.964458, 11.756885, -25.314052),
    45.0: (17.417346, 17.812671, -37.423572),
}


def _t(azimuth: float, inclination: float) -> np.ndarray:
    i, a = math.radians(90.0 + inclination), math.radians(azimuth)
    return np.array([math.sin(i) * math.sin(a), math.sin(i) * math.cos(a), -math.cos(i)])


def _dset(depth: float, stations) -> object:
    """Un sondeo «R-1» con su boca en :data:`COLLAR` y las estaciones (MD, A, θ) dadas."""
    collar = model.Collar("R-1", *COLLAR, depth)
    surveys = [model.SurveyStation("R-1", md, azimuth, inclination)
               for md, azimuth, inclination in stations]
    return model.DrillholeSet.from_records(crs=H25830, vertical=V5782, collars=[collar],
                                           surveys=surveys)


def _at(traces, depths) -> np.ndarray:
    """Las posiciones de ``depths`` en el sondeo 0, relativas a la boca."""
    md = np.asarray(depths, dtype=np.float64)
    hole = np.zeros(md.size, dtype=np.int64)
    return desurvey.md_to_xyz(traces, hole, md) - np.array(COLLAR)


class _Arc:
    """El arco analítico del módulo: posición relativa a la boca y (A, θ) a la profundidad
    ``s``."""

    def __init__(self) -> None:
        a0, i0 = math.radians(ARC_START[0]), math.radians(90.0 + ARC_START[1])
        self.t0 = np.array([math.sin(i0) * math.sin(a0), math.sin(i0) * math.cos(a0),
                            -math.cos(i0)])
        high = np.array([math.cos(i0) * math.sin(a0), math.cos(i0) * math.cos(a0),
                         math.sin(i0)])
        right = np.array([math.cos(a0), -math.sin(a0), 0.0])
        tilt = math.radians(ARC_TILT_DEG)
        self.u = math.cos(tilt) * high + math.sin(tilt) * right

    def position(self, s) -> np.ndarray:
        sigma = np.asarray(s, dtype=np.float64) / ARC_RADIUS_M
        return ARC_RADIUS_M * (np.sin(sigma)[:, None] * self.t0
                               + (1.0 - np.cos(sigma))[:, None] * self.u)

    def stations(self) -> list[tuple[float, float, float]]:
        sigma = np.array(ARC_STATIONS) / ARC_RADIUS_M
        tangent = np.cos(sigma)[:, None] * self.t0 + np.sin(sigma)[:, None] * self.u
        azimuth = np.degrees(np.arctan2(tangent[:, 0], tangent[:, 1])) % 360.0
        inclination = np.degrees(np.arctan2(tangent[:, 2],
                                            np.hypot(tangent[:, 0], tangent[:, 1])))
        return [(md, float(a), float(t)) for md, a, t
                in zip(ARC_STATIONS, azimuth, inclination, strict=True)]


class StraightHoleTest(unittest.TestCase):
    def test_intermediate_depths_three_methods(self) -> None:
        """RF-005-21: en un recto de 500 m a −60° / 45°, cualquier profundidad (entre
        estaciones, en ellas, en la boca y en el fondo) está en la recta analítica a
        ≤ 10⁻⁶ m por los tres métodos, y coincide con la tabla del módulo."""
        dset = _dset(500.0, [(float(md), 45.0, -60.0) for md in range(0, 501, 50)])
        expected = np.array(STRAIGHT_DEPTHS)[:, None] * _t(45.0, -60.0)
        for depth, row in STRAIGHT.items():
            k = STRAIGHT_DEPTHS.index(depth)
            np.testing.assert_allclose(expected[k], row, rtol=0, atol=5e-7)
        for method in Method:
            with self.subTest(method=method):
                found = _at(desurvey.desurvey(dset, method), STRAIGHT_DEPTHS)
                self.assertLessEqual(np.abs(found - expected).max(), EXACT_TOLERANCE_M)


class InclinedArcTest(unittest.TestCase):
    def test_table_matches_formula(self) -> None:
        """RF-005-21: la tabla del módulo es la de la fórmula analítica del arco."""
        arc = _Arc()
        position = arc.position(list(ARC_TABLE))
        np.testing.assert_allclose(position, list(ARC_TABLE.values()), rtol=0, atol=5e-7)
        self.assertAlmostEqual(ARC_RADIUS_M, 572.957795, places=6)

    def test_minimum_curvature_between_stations(self) -> None:
        """RF-005-21: por mínima curvatura, cualquier profundidad del arco (entre estaciones
        y en ellas) está sobre el arco analítico a ≤ 1 mm, y en cada estación da
        exactamente el punto de la traza (la misma curva)."""
        arc = _Arc()
        traces = desurvey.desurvey(_dset(500.0, arc.stations()))
        np.testing.assert_array_equal(traces.md, ARC_STATIONS)
        error = np.linalg.norm(_at(traces, ARC_DEPTHS) - arc.position(ARC_DEPTHS), axis=1)
        self.assertLessEqual(error.max(), POSITION_TOLERANCE_M)
        hole = np.zeros(len(ARC_STATIONS), dtype=np.int64)
        np.testing.assert_array_equal(
            desurvey.md_to_xyz(traces, hole, np.array(ARC_STATIONS)), traces.xyz)


class HandCalculatedTest(unittest.TestCase):
    def test_balanced_tangent_at_its_midpoint(self) -> None:
        """RF-005-21: entre dos estaciones, la tangente equilibrada sigue t₁ hasta el punto
        medio (30 m) y t₂ después; la tangente, t₁; la mínima curvatura, el arco de radio
        ΔMD/β: las posiciones de la tabla del módulo a ≤ 10⁻⁶ m."""
        dset = _dset(60.0, HAND_STATIONS)
        depths = list(HAND_BALANCED)
        t1 = _t(40.0, -60.0)
        cases = {
            Method.BALANCED_TANGENT: np.array(list(HAND_BALANCED.values())),
            Method.TANGENT: np.array(depths)[:, None] * t1,
            Method.MINIMUM_CURVATURE: np.array(list(HAND_CURVATURE.values())),
        }
        np.testing.assert_allclose(cases[Method.BALANCED_TANGENT][1], 30.0 * t1, rtol=0,
                                   atol=5e-7)
        for method, expected in cases.items():
            with self.subTest(method=method):
                traces = desurvey.desurvey(dset, method)
                found = _at(traces, depths)
                self.assertLessEqual(np.abs(found - expected).max(), EXACT_TOLERANCE_M)
                bottom = desurvey.md_to_xyz(traces, np.array([0]), np.array([60.0]))
                np.testing.assert_array_equal(bottom, traces.xyz[-1:])


class ArcPolylineTest(unittest.TestCase):
    def test_densified_polyline(self) -> None:
        """RF-005-21: la polilínea del arco cada ≤ 2 m con los límites de unos tramos
        contiene las estaciones y los límites, ningún segmento pasa de 2 m, no tiene más
        vértices que los necesarios y cada vértice está sobre el arco a ≤ 1 mm."""
        arc = _Arc()
        traces = desurvey.desurvey(_dset(500.0, arc.stations()))
        extra = {0: np.array(ARC_LIMITS)}
        offsets, md = desurvey.polyline_md(traces, extra, STEP_M)
        offsets_xyz, xyz = desurvey.polylines(traces, extra, STEP_M)
        np.testing.assert_array_equal(offsets, [0, md.size])
        np.testing.assert_array_equal(offsets_xyz, offsets)
        self.assertEqual(xyz.shape, (md.size, 3))
        wanted = sorted({*ARC_STATIONS, *ARC_LIMITS})
        self.assertTrue(np.isin(wanted, md).all())
        self.assertEqual((md[0], md[-1]), (0.0, 500.0))
        self.assertTrue((np.diff(md) > 0.0).all())
        self.assertLessEqual(np.diff(md).max(), STEP_M + MD_ROUNDING_M)
        chords = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
        self.assertLessEqual(chords.max(), STEP_M + XYZ_ROUNDING_M)
        needed = sum(math.ceil((b - a) / STEP_M) for a, b in zip(wanted, wanted[1:])) + 1
        self.assertEqual(md.size, needed)
        stations = np.flatnonzero(np.isin(md, ARC_STATIONS))
        np.testing.assert_array_equal(xyz[stations], traces.xyz)
        error = np.linalg.norm(xyz - np.array(COLLAR) - arc.position(md), axis=1)
        self.assertLessEqual(error.max(), POSITION_TOLERANCE_M)


if __name__ == "__main__":
    unittest.main()
