# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del azimut de cuadrícula y de la convergencia en las bocas (spec 005,
T04; RF-005-27; plan 005 §5.4 y §5.6.12, hito H1.1).

**Azimut de cuadrícula calculado a mano** (``drillholes.conventions``: boca →
``collar_convergence`` → ``convert_surveys``; γ de cada boca dada por un ``CrsService`` falso
que cumple el puerto de la 006). A = A_m + δ − γ (magnético) o A = A_m − γ (geográfico),
llevado a [0°, 360°); tolerancia 10⁻⁶° (RF-005-27):

==== =========== ======== ========= ===================================================
Caso A_m (°)     δ (°)    γ (°)     A (°), a mano
==== =========== ======== ========= ===================================================
M-1  123,456     +2,5     +1,4937   123,456 + 2,5 − 1,4937 = 124,4623
M-2  359,9       +2,5     −0,8      359,9 + 2,5 + 0,8 = 363,2 → 363,2 − 360 = 3,2
M-3  0,2         −1,1     +0,6      0,2 − 1,1 − 0,6 = −1,5 → −1,5 + 360 = 358,5
M-4  270         −1,1     −1,9294   270 − 1,1 + 1,9294 = 270,8294
T-1  200         —        −1,93     200 + 1,93 = 201,93
T-2  1           —        +1,0000001  1 − 1,0000001 = −0,0000001 → 359,9999999
T-3  360         —        +0,25     360 − 0,25 = 359,75
==== =========== ======== ========= ===================================================

Cada estación guarda además A_m, su referencia, δ (solo magnético) y γ, exactos.

**Convergencia de cuadrícula frente a Snyder, con el servicio real de la 006**
(``adapters.registry.crs_service()``, pyproj de ``.deps/site``): γ en grados, horaria del
norte geográfico al de cuadrícula y positiva al este del meridiano central (el contrato de
``gis.ports.CrsService.grid_convergence``), frente a la serie de la convergencia de la
transversa de Mercator del elipsoide escrita con las variables de Snyder (1987), *Map
Projections — A Working Manual*, USGS PP 1395, cap. 8 (la referencia del plan 005 §5.4):
A = (λ − λ₀)·cos φ, T = tan² φ y C = e′²·cos² φ,

    γ = A·tan φ·[1 + A²·(1 + 3C + 2C²)/3 + A⁴·(2 − T)/15]  (radianes),

con los parámetros de cada CRS del catálogo de la 002 (GRS 1980 en ETRS89 e Internacional
1924 en ED50) y las geográficas de cada punto con la transversa de Mercator propia de
``core.georef`` (sin pyproj). Tolerancia 0,001° (plan 005 §5.4). En el borde del huso
(0° E y 6° O a 40° N) γ = ±1,9294°; en el meridiano central, 0; en las bocas de
``tests/data/dh/csv_basico``, ≈ +1,49° (la que el servicio falso redondea a 1,50°).
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support.dh_fakes import FakeCrsService
from tests.support.package import import_geoblender
from tests.support.repo import ROOT

conventions = import_geoblender("drillholes.conventions")
model = import_geoblender("drillholes.model")
georef = import_geoblender("core.georef")
registry = import_geoblender("adapters.registry")
csv_tables = import_geoblender("interop.csv_tables")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
H25831 = CATALOG.horizontal(25831)
H23030 = CATALOG.horizontal(23030)
V5782 = CATALOG.vertical(5782)
BASICO = ROOT / "tests" / "data" / "dh" / "csv_basico"

ANGLE_TOLERANCE_DEG = 1e-6  # RF-005-27
SNYDER_TOLERANCE_DEG = 0.001  # plan 005 §5.4

# (caso, A_m, γ, A a mano) por referencia y declinación; los de la tabla del módulo.
HAND_CASES = (
    ("magnetic", 2.5, (("M-1", 123.456, 1.4937, 124.4623), ("M-2", 359.9, -0.8, 3.2))),
    ("magnetic", -1.1, (("M-3", 0.2, 0.6, 358.5), ("M-4", 270.0, -1.9294, 270.8294))),
    ("true", None, (("T-1", 200.0, -1.93, 201.93), ("T-2", 1.0, 1.0000001, 359.9999999),
                    ("T-3", 360.0, 0.25, 359.75))),
)

# (CRS, lon, lat) de los puntos de la comparación con Snyder.
SNYDER_POINTS = (
    (H25830, 0.0, 40.0),  # borde este del huso 30
    (H25830, -6.0, 40.0),  # borde oeste
    (H25830, -3.0, 40.0),  # meridiano central
    (H25830, -0.75, 43.6),
    (H25830, -5.25, 36.1),
    (H25831, 1.2, 41.4),
    (H23030, -1.5, 41.0),  # ED50: elipsoide Internacional 1924
    (H23030, -5.9, 37.3),
)


def _snyder_convergence(lon: float, lat: float, tm) -> float:
    """γ en grados por la serie del módulo (variables de Snyder, 1987, cap. 8)."""
    f = 1.0 / tm.inv_f
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)
    phi = math.radians(lat)
    a = math.radians(lon - tm.lon0) * math.cos(phi)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    series = 1.0 + a * a * (1.0 + 3.0 * c + 2.0 * c * c) / 3.0 + a**4 * (2.0 - t) / 15.0
    return math.degrees(a * math.tan(phi) * series)


def _declaration(azimuth_ref: str, declination: float | None):
    return model.SourceDeclaration(
        crs=H25830, vertical=V5782, azimuth_ref=azimuth_ref, declination_deg=declination,
        inclination_convention="negative_down", units={},
        value_rules=model.ValueRules(decimal_mark="."))


def _basico_collars() -> np.ndarray:
    rows = csv_tables.read_table(BASICO / "bocas.csv", encoding="utf-8", separator=";").rows
    return np.array([(float(x.replace(",", ".")), float(y.replace(",", ".")))
                     for _name, x, y, *_rest in rows])


class HandCalculatedAzimuthTest(unittest.TestCase):
    def test_grid_azimuth_by_hand(self) -> None:
        """RF-005-27: los siete casos de la tabla del módulo, de la boca a la estación, a
        ≤ 10⁻⁶° del cálculo a mano, en [0°, 360°), con A_m, la referencia, δ y γ guardados
        en cada estación."""
        for ref, declination, cases in HAND_CASES:
            collars = [model.Collar(name, 700_000.0 + 10.0 * i, 4_400_000.0, 800.0, 100.0)
                       for i, (name, *_rest) in enumerate(cases)]
            stations = [model.SurveyStation(name, 0.0, measured, -60.0)
                        for name, measured, _gamma, _expected in cases]
            gammas = {collar.x: gamma for collar, (_n, _m, gamma, _e) in
                      zip(collars, cases, strict=True)}
            service = FakeCrsService(lambda xy, table=gammas: np.array(
                [table[x] for x in xy[:, 0].tolist()]))
            dset = model.DrillholeSet.from_records(crs=H25830, vertical=V5782,
                                                   collars=collars, surveys=stations)
            xy = np.column_stack([dset.collars.x, dset.collars.y])
            gamma = conventions.collar_convergence(xy, service, H25830)
            converted = conventions.convert_surveys(dset.surveys,
                                                    _declaration(ref, declination), gamma)
            codes = converted.code_values("azimuth_ref")
            for row, (name, measured, case_gamma, expected) in enumerate(cases):
                with self.subTest(caso=name):
                    azimuth = float(converted.azimuth[row])
                    self.assertLessEqual(abs(azimuth - expected), ANGLE_TOLERANCE_DEG)
                    self.assertTrue(0.0 <= azimuth < 360.0)
                    self.assertEqual(float(converted.azimuth_measured[row]), measured)
                    self.assertEqual(codes[int(converted.azimuth_ref[row])], ref)
                    self.assertEqual(float(converted.convergence_deg[row]), case_gamma)
                    stored = float(converted.declination_deg[row])
                    if declination is None:
                        self.assertTrue(math.isnan(stored))
                    else:
                        self.assertEqual(stored, declination)


class SnyderConvergenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = registry.crs_service()

    def test_against_snyder(self) -> None:
        """RF-005-27 (H1.1): ``collar_convergence`` con el servicio real da la γ de la serie
        de Snyder a ≤ 0,001° en ETRS89 (husos 30 y 31) y en ED50, con el signo del contrato
        (positiva al este del meridiano central): ±1,9294° en los bordes del huso 30 a
        40° N, 0 en el meridiano central."""
        worst = 0.0
        for crs, lon, lat in SNYDER_POINTS:
            with self.subTest(epsg=crs.epsg, lon=lon, lat=lat):
                x, y = georef.tm_forward(lon, lat, crs.projection)
                gamma = conventions.collar_convergence(np.array([(x, y)]), self.service, crs)
                expected = _snyder_convergence(lon, lat, crs.projection)
                error = abs(float(gamma[0]) - expected)
                worst = max(worst, error)
                self.assertLessEqual(error, SNYDER_TOLERANCE_DEG)
                if lon != crs.projection.lon0:
                    self.assertEqual(lon > crs.projection.lon0, gamma[0] > 0.0)
        self.assertAlmostEqual(_snyder_convergence(0.0, 40.0, H25830.projection), 1.9294,
                               delta=5e-5)
        self.assertAlmostEqual(_snyder_convergence(-6.0, 40.0, H25830.projection), -1.9294,
                               delta=5e-5)
        self.assertLess(worst, SNYDER_TOLERANCE_DEG)

    def test_collars_of_csv_basico(self) -> None:
        """RF-005-27 (H1.1): en las seis bocas de ``csv_basico`` (EPSG:25830, a 200 km al
        este del meridiano central), γ ≈ +1,49° y la de Snyder a ≤ 0,001°."""
        xy = _basico_collars()
        self.assertEqual(xy.shape, (6, 2))
        gamma = conventions.collar_convergence(xy, self.service, H25830)
        for (x, y), value in zip(xy.tolist(), gamma.tolist(), strict=True):
            with self.subTest(x=x, y=y):
                lon, lat = georef.tm_inverse(x, y, H25830.projection)
                expected = _snyder_convergence(lon, lat, H25830.projection)
                self.assertLessEqual(abs(value - expected), SNYDER_TOLERANCE_DEG)
                self.assertAlmostEqual(value, 1.49, delta=0.01)


if __name__ == "__main__":
    unittest.main()
