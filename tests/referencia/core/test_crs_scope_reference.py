# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del ámbito del CRS y del huso extendido (spec 002, D-12 y T51;
RF-002-03; constitución, principio 2; plan 002 §5.4).

``core.georef.tm`` (Krüger, Karney 2011, orden 6) con los parámetros del WKT1 del
catálogo, contra la salida de otro programa sobre los mismos datos:

- **Ámbito proyectado del catálogo** (``bounds``, calculado al generar el catálogo con
  ``cs2cs`` de PROJ 9.8.1 desde el contorno de ``bbox_lonlat``, 64 puntos por lado): la
  proyección directa del mismo contorno da cada uno de los 13 límites con menos de 1 m de
  diferencia (la envolvente del catálogo está redondeada hacia fuera a metros enteros), y
  la inversa de la directa vuelve a cada punto con menos de 10⁻⁹°.
- **Puntos de la spec** (§8: Vinaròs, el huso extendido al este, Mahón y Castellón de la
  Plana), con ``proj`` de PROJ 9.8.1 (el de QGIS 4.2.0) el 06/10/2026: inversa
  ``proj -I -f %.12f +proj=utm +zone=30 +ellps=GRS80`` (también ``+ellps=intl`` para
  ED50) y factor de escala ``proj -V`` (8 decimales). Tolerancias: 10⁻⁹° y 10⁻⁸ en k
  (0,01 ppm, el redondeo de ``proj -V``).
"""

import math
import unittest

from tests.support.package import import_geoblender

crs = import_geoblender("core.georef.crs")
tm = import_geoblender("core.georef.tm")

EDGE_POINTS = 64  # los de tools/gen_crs_catalog.py (EDGE_POINTS)
BOUNDS_TOLERANCE_M = 1.0
ANGLE_TOLERANCE_DEG = 1e-9
SCALE_TOLERANCE = 1e-8

# (x, y) en EPSG:25830 → (lon, lat) de PROJ 9.8.1 (proj -I, GRS 1980, huso 30).
PROJ_INVERSE_25830 = (
    ((794_000.0, 4_482_000.0), (0.466092222171, 40.436698234070)),  # Vinaròs
    ((795_000.0, 4_483_000.0), (0.478325101548, 40.445336839459)),
    ((795_000.0, 4_482_000.0), (0.477861084016, 40.436344356521)),
    ((794_000.0, 4_483_000.0), (0.466554677181, 40.445690828793)),
    ((1_008_000.0, 4_500_000.0), (2.993087168030, 40.495117987944)),  # huso extendido
    ((1_008_000.0, 4_501_000.0), (2.993887465248, 40.504077654552)),
    ((1_009_000.0, 4_500_000.0), (3.004823148498, 40.494506565985)),  # fuera
    ((1_009_000.0, 4_501_000.0), (3.005624989900, 40.503466040226)),
    ((1_121_000.0, 4_440_000.0), (4.259191292825, 39.882363143821)),  # Mahón
    ((751_000.0, 4_429_000.0), (-0.060848018870, 39.973915183243)),  # Castellón
    ((752_000.0, 4_430_000.0), (-0.048765488119, 39.982615658639)),
)
# (x, y) en EPSG:23030 → (lon, lat) de PROJ 9.8.1 (proj -I, Internacional 1924).
PROJ_INVERSE_23030 = (
    ((795_000.0, 4_483_000.0), (0.478131714271, 40.444643995157)),
    ((150_000.0, 4_100_000.0), (-6.931600814605, 36.980446103325)),
)
# (lon, lat) en EPSG:25830 → k de PROJ 9.8.1 (proj -V, «Parallel scale»).
PROJ_SCALE_25830 = (
    ((0.47832510155, 40.445336839), 1.00067137),  # Vinaròs: +671 ppm
    ((2.993887465248, 40.504077654552), 1.00277806),  # +2 778 ppm
    ((3.004823148498, 40.494506565985), 1.00279060),
    ((4.259191292825, 39.882363143821), 1.00435104),
    ((-0.060848018870, 39.973915183243), 1.00037566),
    ((-3.0, 40.0), 0.9996),
)


def _contour(bbox: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    """El contorno (lon, lat) de ``bbox`` (oeste, sur, este, norte) que proyectó
    ``tools/gen_crs_catalog.py`` (``densify``): 64 puntos por lado, con las esquinas."""
    west, south, east, north = bbox
    points: list[tuple[float, float]] = []
    for index in range(EDGE_POINTS):
        t = index / EDGE_POINTS
        points.append((west + t * (east - west), south))
        points.append((east, south + t * (north - south)))
        points.append((east - t * (east - west), north))
        points.append((west, north - t * (north - south)))
    return points


class CatalogBoundsReferenceTest(unittest.TestCase):
    def test_projected_contour_gives_catalog_bounds(self) -> None:
        """RF-002-03 (referencia, D-12): para los 13 CRS horizontales del catálogo, la
        proyección directa del contorno de ``bbox_lonlat`` con los parámetros de su WKT1
        da su ``bounds`` (``cs2cs`` de PROJ 9.8.1) con menos de 1 m, y la inversa de la
        directa vuelve a cada punto con menos de 10⁻⁹°."""
        horizontals = crs.load_catalog().horizontals()
        self.assertEqual(len(horizontals), 13)
        for ref in horizontals:
            with self.subTest(epsg=ref.epsg):
                projected = []
                for lon, lat in _contour(ref.bbox_lonlat):
                    x, y = tm.tm_forward(lon, lat, ref.projection)
                    back = tm.tm_inverse(x, y, ref.projection)
                    self.assertLess(abs(back[0] - lon), ANGLE_TOLERANCE_DEG)
                    self.assertLess(abs(back[1] - lat), ANGLE_TOLERANCE_DEG)
                    projected.append((x, y))
                xs, ys = zip(*projected, strict=True)
                ours = (min(xs), min(ys), max(xs), max(ys))
                for name, value, expected in zip(
                    ("xmin", "ymin", "xmax", "ymax"), ours, ref.bounds, strict=True
                ):
                    self.assertLess(abs(value - expected), BOUNDS_TOLERANCE_M, (name, value))


class ProjPointsReferenceTest(unittest.TestCase):
    def _check_inverse(self, epsg: int, cases: tuple) -> None:
        projection = crs.load_catalog().horizontal(epsg).projection
        for (x, y), (lon, lat) in cases:
            with self.subTest(epsg=epsg, x=x, y=y):
                found = tm.tm_inverse(x, y, projection)
                self.assertLess(abs(found[0] - lon), ANGLE_TOLERANCE_DEG, found)
                self.assertLess(abs(found[1] - lat), ANGLE_TOLERANCE_DEG, found)

    def test_inverse_matches_proj(self) -> None:
        """RF-002-03 (referencia, spec §8): las esquinas de las ventanas de la spec en
        EPSG:25830 (Vinaròs, el huso extendido al este, más allá, Mahón y Castellón de la
        Plana) y dos puntos en EPSG:23030 (ED50, elipsoide Internacional) dan las
        geográficas de PROJ 9.8.1 con menos de 10⁻⁹°: Vinaròs llega a 0,4783° E (0,48° al
        este del huso 30), la ventana de 1 007 000 a 1 008 000 a 2,9939° E (dentro del huso
        extendido), la de 1 008 000 a 1 009 000 a 3,0056° E (fuera) y Mahón a 4,26° E."""
        self._check_inverse(25830, PROJ_INVERSE_25830)
        self._check_inverse(23030, PROJ_INVERSE_23030)

    def test_scale_matches_proj(self) -> None:
        """RF-002-03 (referencia, D-12): el factor de escala de esos puntos es el de PROJ
        9.8.1 con 10⁻⁸ (+671 ppm en Vinaròs, +2 778 ppm a 2,99° E del huso 30, 0,9996 en
        el meridiano central)."""
        projection = crs.load_catalog().horizontal(25830).projection
        for (lon, lat), expected in PROJ_SCALE_25830:
            with self.subTest(lon=lon, lat=lat):
                found = tm.tm_scale(lon, lat, projection)
                self.assertTrue(math.isfinite(found))
                self.assertLess(abs(found - expected), SCALE_TOLERANCE, found)


if __name__ == "__main__":
    unittest.main()
