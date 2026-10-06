# SPDX-License-Identifier: GPL-3.0-or-later
"""Proyección transversa de Mercator de Krüger (spec 002, D-12 y T51; RF-002-03; plan 002
§5.4, «Ámbito del CRS y huso extendido»).

``core.georef.tm`` solo decide si una ventana cae en el ámbito de su CRS o en su huso
extendido y calcula la deformación de escala que se avisa: directa, inversa y factor de
escala (Karney, 2011, orden 6). Aquí, sus propiedades y una fórmula independiente del
factor de escala (Snyder, 1987); la referencia contra PROJ está en
``tests/referencia/core/test_crs_scope_reference.py``.
"""

import math
import unittest

from tests.support.package import import_geoblender

tm = import_geoblender("core.georef.tm")

GRS80 = (6_378_137.0, 298.257222101)
UTM30 = tm.TransverseMercator(*GRS80, lon0=-3.0, k0=0.9996, fe=500_000.0, fn=0.0)
INTERNATIONAL = tm.TransverseMercator(6_378_388.0, 297.0, -3.0, 0.9996, 500_000.0, 0.0)


def _snyder_scale(lon: float, lat: float, proj: object) -> float:
    """Factor de escala de la transversa de Mercator por la serie de Snyder (1987,
    «Map Projections — A Working Manual», USGS PP 1395, ec. 8-11), independiente de las
    series de Krüger."""
    f = 1 / proj.inv_f
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi = math.radians(lat)
    big_t = math.tan(phi) ** 2
    big_c = ep2 * math.cos(phi) ** 2
    big_a = math.radians(lon - proj.lon0) * math.cos(phi)
    return proj.k0 * (
        1
        + (1 + big_c) * big_a**2 / 2
        + (5 - 4 * big_t + 42 * big_c + 13 * big_c**2 - 28 * ep2) * big_a**4 / 24
        + (61 - 148 * big_t + 16 * big_t**2) * big_a**6 / 720
    )


class TransverseMercatorTest(unittest.TestCase):
    def test_origin_and_central_meridian(self) -> None:
        """RF-002-03: en el meridiano central y el ecuador, (falso este; falso norte); en
        el meridiano central, el factor de escala es k0 (0,9996) a cualquier latitud y la
        X es el falso este."""
        x, y = tm.tm_forward(-3.0, 0.0, UTM30)
        self.assertAlmostEqual(x, 500_000.0, delta=1e-9)
        self.assertAlmostEqual(y, 0.0, delta=1e-9)
        for lat in (0.0, 35.26, 40.0, 60.0, 80.49):
            with self.subTest(latitud=lat):
                x, _y = tm.tm_forward(-3.0, lat, UTM30)
                self.assertAlmostEqual(x, 500_000.0, delta=1e-6)
                self.assertAlmostEqual(tm.tm_scale(-3.0, lat, UTM30), 0.9996, delta=1e-12)

    def test_symmetric_about_central_meridian(self) -> None:
        """RF-002-03: dos puntos a la misma distancia al este y al oeste del meridiano
        central tienen la misma Y, X simétricas respecto al falso este y la misma escala."""
        for delta, lat in ((0.5, 39.0), (3.0, 40.4), (6.0, 43.8)):
            with self.subTest(grados=delta, latitud=lat):
                xe, ye = tm.tm_forward(-3.0 + delta, lat, UTM30)
                xw, yw = tm.tm_forward(-3.0 - delta, lat, UTM30)
                self.assertAlmostEqual(xe - 500_000.0, 500_000.0 - xw, delta=1e-6)
                self.assertAlmostEqual(ye, yw, delta=1e-6)
                self.assertAlmostEqual(
                    tm.tm_scale(-3.0 + delta, lat, UTM30),
                    tm.tm_scale(-3.0 - delta, lat, UTM30),
                    delta=1e-15,
                )

    def test_inverse_of_forward(self) -> None:
        """RF-002-03: la inversa de la directa vuelve al punto con menos de 10⁻⁹° en todo
        el huso extendido (±6°) y en las latitudes de los CRS del catálogo, con los
        elipsoides GRS 1980 e Internacional 1924; y la directa de la inversa, con menos de
        1 µm."""
        for proj in (UTM30, INTERNATIONAL):
            for delta in (-6.0, -4.5, -3.0, -1.0, 0.0, 0.7, 3.0, 4.2, 6.0):
                for lat in (0.0, 24.6, 35.26, 40.45, 62.41, 80.49, 84.0):
                    lon = proj.lon0 + delta
                    with self.subTest(a=proj.a, lon=lon, lat=lat):
                        x, y = tm.tm_forward(lon, lat, proj)
                        lon2, lat2 = tm.tm_inverse(x, y, proj)
                        self.assertLess(abs(lon2 - lon), 1e-9)
                        self.assertLess(abs(lat2 - lat), 1e-9)
                        x2, y2 = tm.tm_forward(lon2, lat2, proj)
                        self.assertLess(max(abs(x2 - x), abs(y2 - y)), 1e-6)

    def test_scale_matches_snyder(self) -> None:
        """RF-002-03: el factor de escala coincide con la serie de Snyder (independiente de
        las series de Krüger) con menos de 0,05 ppm hasta 6° del meridiano central, y crece
        con la distancia a él (0,9996 en el meridiano, +671 ppm en Vinaròs, 3,48° al
        este)."""
        for delta in (0.0, 1.0, 2.0, 3.0, 3.4783, 4.5, 6.0):
            for lat in (35.26, 40.45, 43.8, 60.0):
                with self.subTest(grados=delta, latitud=lat):
                    lon = -3.0 + delta
                    ppm = (tm.tm_scale(lon, lat, UTM30) - _snyder_scale(lon, lat, UTM30)) * 1e6
                    self.assertLess(abs(ppm), 0.05)
        scales = [tm.tm_scale(-3.0 + delta, 40.45, UTM30) for delta in (0, 1, 2, 3, 4, 5, 6)]
        self.assertEqual(scales, sorted(scales))
        self.assertAlmostEqual((tm.tm_scale(0.4783, 40.4453, UTM30) - 1) * 1e6, 671, delta=1)

    def test_invalid(self) -> None:
        """RF-002-03: parámetros que no son de una transversa de Mercator (semieje nulo,
        aplanamiento ≤ 1, k0 nulo o un valor no finito) son un error; y un punto a más de
        un cuarto de vuelta del meridiano central (X e Y intercambiadas de verdad, o un
        número absurdo) no tiene inversa: :class:`ValueError`, que quien llama trata como
        fuera del ámbito."""
        for values in (
            (0.0, 298.0, -3.0, 0.9996, 500_000.0, 0.0),
            (6_378_137.0, 1.0, -3.0, 0.9996, 500_000.0, 0.0),
            (6_378_137.0, 298.0, -3.0, 0.0, 500_000.0, 0.0),
            (6_378_137.0, 298.0, math.nan, 0.9996, 500_000.0, 0.0),
        ):
            with self.subTest(valores=values), self.assertRaises(ValueError):
                tm.TransverseMercator(*values)
        for x, y in ((1e12, 4_400_000.0), (math.inf, 0.0), (500_000.0, math.nan)):
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                tm.tm_inverse(x, y, UTM30)


if __name__ == "__main__":
    unittest.main()
