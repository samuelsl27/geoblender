# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia de la diferencia entre la cota de las bocas y la del MDT (spec 005,
T10; RF-005-18; DH-W05; plan 005 §5.4, §5.6.6 y §7; D-19).

**MDT plano inclinado**, en EPSG:25830 (EPSG:5782 de cotas): una rejilla de 50 × 25 celdas de
4 m (oeste 700 000, norte 4 400 100; centros de E 700 002 a 700 198 y de N 4 400 098 a
4 400 002) con la cota de cada centro en

    z = 760 + 0,12·x − 0,05·y (m), con x = E − 700 000 e y = N − 4 400 000,

y una celda sin dato (fila 10, columna 20, contadas desde la esquina noroeste). La bilineal
reproduce un plano: la cota del MDT en una boca es la del plano en su posición, que se
calcula a mano. Se muestrea con ``drillholes.surface.raster_sampler`` (la bilineal de
``gis.raster.sample``, la de la 006; D-19), y la diferencia es dz = Z de la boca − z del MDT,
con error ≤ 1 mm (RF-005-18). Con la tolerancia de la spec (§11: 2 m), DH-W05 si |dz| > 2 m:

==== ============ ============== ======= ===================================== ======== ===========
Boca E (m)        N (m)          Z (m)   z del MDT, a mano (m)                 dz (m)   DH-W05
==== ============ ============== ======= ===================================== ======== ===========
P-1  700 037,30   4 400 052,90   762,000 760 + 4,476 − 2,645 = 761,831         +0,169   no
P-2  700 121,85   4 400 013,65   778,000 760 + 14,622 − 0,6825 = 773,9395     +4,0605  sí
P-3  700 150,00   4 400 090,00   770,000 760 + 18 − 4,5 = 773,5 (un centro)    −3,5     sí
P-4  700 010,10   4 400 097,90   757,000 760 + 1,212 − 4,895 = 756,317         +0,683   no
P-5  700 199,00   4 400 050,00   780,000 más allá del último centro (700 198)  —        sin evaluar
P-6  699 950,00   4 400 050,00   750,000 fuera del MDT                         —        sin evaluar
P-7  700 083,00   4 400 056,00   767,000 un vecino sin dato (fila 10, col. 20) —        sin evaluar
P-8  700 060,00   4 400 030,00   763,701 760 + 7,2 − 1,5 = 765,7               −1,999   no
==== ============ ============== ======= ===================================== ======== ===========

**Boca fuera del MDT** (P-5, P-6 y P-7; spec §8): DH-W05 no se evalúa, su diferencia queda
vacía (NaN) y el informe lo dice con una nota por boca. **Sin MDT**, ninguna boca se evalúa y
el informe lo dice con una nota general.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import dh_sets
from tests.support.package import import_geoblender

validate = import_geoblender("drillholes.validate")
surface = import_geoblender("drillholes.surface")
ports = import_geoblender("drillholes.ports")
model = import_geoblender("drillholes.model")
grid = import_geoblender("gis.grid")
raster = import_geoblender("gis.raster")

DZ_TOLERANCE_M = 0.001  # RF-005-18: ≤ 1 mm frente al cálculo manual
E0, N0 = 700_000.0, 4_400_000.0
GRID = grid.Grid(west=700_000.0, north=4_400_100.0, dx=4.0, dy=4.0, ncols=50, nrows=25)
NO_DATA_CELL = (10, 20)  # (fila, columna)

# (boca, E, N, Z, dz a mano o None si no se evalúa, DH-W05)
COLLARS = (
    ("P-1", 700_037.30, 4_400_052.90, 762.000, 0.169, False),
    ("P-2", 700_121.85, 4_400_013.65, 778.000, 4.0605, True),
    ("P-3", 700_150.00, 4_400_090.00, 770.000, -3.5, True),
    ("P-4", 700_010.10, 4_400_097.90, 757.000, 0.683, False),
    ("P-5", 700_199.00, 4_400_050.00, 780.000, None, False),
    ("P-6", 699_950.00, 4_400_050.00, 750.000, None, False),
    ("P-7", 700_083.00, 4_400_056.00, 767.000, None, False),
    ("P-8", 700_060.00, 4_400_030.00, 763.701, -1.999, False),
)


def _plane() -> object:
    """El MDT plano inclinado del módulo, con su celda sin dato."""
    east = GRID.west + GRID.dx * (np.arange(GRID.ncols) + 0.5)
    north = GRID.north - GRID.dy * (np.arange(GRID.nrows) + 0.5)
    values = 760.0 + 0.12 * (east[None, :] - E0) - 0.05 * (north[:, None] - N0)
    values[NO_DATA_CELL] = np.nan
    return raster.Raster(GRID, values, dh_sets.H25830, dh_sets.V5782)


def _dset() -> object:
    collars = [model.Collar(name, e, n, z, 50.0) for name, e, n, z, _dz, _w05 in COLLARS]
    stations = [model.SurveyStation(name, 0.0, 0.0, -90.0, source="declared_vertical")
                for name, *_rest in COLLARS]
    return model.DrillholeSet.from_records(crs=dh_sets.H25830, vertical=dh_sets.V5782,
                                           collars=collars, surveys=stations)


class DemDifferenceReferenceTest(unittest.TestCase):
    def test_inclined_plane(self) -> None:
        """RF-005-18: la diferencia de cada boca con el MDT plano inclinado, por la bilineal
        de la 006, a ≤ 1 mm del cálculo manual de la tabla del módulo; DH-W05 en las que pasan
        de la tolerancia (P-2 y P-3), con su campo, su valor y su mensaje en español."""
        report = validate.validate(_dset(), dh_sets.params(),
                                   surface=surface.raster_sampler(_plane()))
        dz = report.collar_dem_dz
        self.assertEqual((dz.dtype, dz.shape), (np.float64, (len(COLLARS),)))
        worst = 0.0
        for k, (name, _e, _n, _z, hand, _w05) in enumerate(COLLARS):
            with self.subTest(boca=name):
                if hand is None:
                    self.assertTrue(math.isnan(dz[k]))
                    continue
                error = abs(float(dz[k]) - hand)
                worst = max(worst, error)
                self.assertLessEqual(error, DZ_TOLERANCE_M)
        self.assertLess(worst, 1e-6)  # la bilineal reproduce el plano: solo el redondeo
        warned = [(i.code, i.hole_name, i.table, i.field, i.value) for i in report.issues]
        self.assertEqual(warned, [("DH-W05", name, "dh_collar", "z", None)
                                  for name, *_rest, w05 in COLLARS if w05])
        p2 = report.issues[0]
        self.assertEqual((p2.level, p2.scope, p2.row_ref), ("warning", None, 1))
        args = dict(p2.message_args)
        self.assertEqual(args["z"], 778.0)
        self.assertAlmostEqual(args["dem"], 773.9395, delta=0.001)  # al milímetro
        self.assertAlmostEqual(args["dz"], 4.0605, delta=0.001)
        self.assertEqual(args["tolerance"], 2.0)
        text = p2.message()
        self.assertIn("MDT", text)
        self.assertIn("778 m", text)
        self.assertIn("2 m", text)

    def test_collars_outside_the_dem(self) -> None:
        """RF-005-18 (spec §8): una boca fuera del MDT (más allá de los centros de la
        rejilla, fuera de su extensión o con un vecino sin dato) no se evalúa: sin DH-W05,
        con la diferencia vacía, y el informe lo dice con una nota de esa boca."""
        report = validate.validate(_dset(), dh_sets.params(),
                                   surface=surface.raster_sampler(_plane()))
        outside = [name for name, *_rest, hand, _w05 in COLLARS if hand is None]
        self.assertEqual([(n.code, n.hole_name) for n in report.notes],
                         [("DH-W05", name) for name in outside])
        self.assertEqual([n.hole for n in report.notes], [4, 5, 6])
        for note in report.notes:
            self.assertIn("MDT", note.message())
            self.assertNotIn("{", note.message())
        self.assertNotIn("P-5", {i.hole_name for i in report.issues})

    def test_without_dem(self) -> None:
        """RF-005-18 (spec §8): sin MDT, DH-W05 no se evalúa en ninguna boca (ni P-2 ni
        P-3), no hay diferencias y el informe lo dice con una nota general."""
        report = validate.validate(_dset(), dh_sets.params())
        self.assertEqual(report.issues, ())
        self.assertIsNone(report.collar_dem_dz)
        self.assertEqual([(n.code, n.hole, n.hole_name) for n in report.notes],
                         [("DH-W05", -1, None)])
        self.assertIn("MDT", report.notes[0].message())

    def test_sampler_is_the_bilinear_of_the_006(self) -> None:
        """RF-005-18, D-19: ``raster_sampler`` cumple el puerto ``SurfaceSampler`` con el CRS
        y la referencia vertical del ráster, y su cota es la bilineal de ``gis.raster.sample``
        bit a bit (en un centro, la del centro)."""
        plane = _plane()
        sampler = surface.raster_sampler(plane)
        self.assertIsInstance(sampler, ports.SurfaceSampler)
        self.assertIs(sampler.crs, plane.crs)
        self.assertIs(sampler.vertical, plane.vertical)
        xy = np.array([[e, n] for _name, e, n, *_rest in COLLARS])
        found = sampler.sample(xy)
        np.testing.assert_array_equal(found, raster.sample(plane, xy, method="bilinear"))
        self.assertEqual(found[2], plane.values[2, 37])
        with self.assertRaises(TypeError):
            surface.raster_sampler(plane.values)


if __name__ == "__main__":
    unittest.main()
