# SPDX-License-Identifier: GPL-3.0-or-later
"""La tolerancia de la celda frente al redondeo de un UTM (spec 012, T39; RF-012-12; plan 012 D-1
y D-37; hallazgo F-2 de la verificación única).

RF-012-12 da una celda como dentro de una zona solo si una parte de su área (**más que el residuo
del redondeo**) cae en ella, y como dentro de un límite solo si toda su área cae dentro. Con
nortes de 4,4 Mm un ``float64`` redondea a 1 ulp = 9,3·10⁻¹⁰ m, una fracción 9·10⁻¹⁰ de una celda
de 1 m, mucho mayor que ε = 10⁻¹² (``gis.coverage.FRACTION_EPSILON``): una exclusión de 12 × 12 m
alineada con la rejilla pasaba de 144 celdas a 192 con 1 ulp hacia fuera (a 196 con 1 µm), y un
límite legal de 30 × 30 m alineado, de 900 a 784 con 1 ulp hacia dentro. La tolerancia de
pertenencia de ``gis.masks.zones`` crece ahora con la ulp de las coordenadas de la rejilla (hasta
1 µm), sin tocar la ε de la cubicación (011).

- **Alineadas, con ruido** (RF-012-12): una exclusión y un límite alineados con la rejilla, con
  ruido de 0, 1 ulp y 1 µm hacia dentro y hacia fuera, dan sus 144 y 900 celdas; con su resguardo
  (hacia fuera la exclusión, hacia dentro el límite) el mismo recuento que sin ruido; con celdas no
  cuadradas, igual; y por ``combine.prepare`` (el camino de la compilación).
- **Lo que invade de verdad entra** (RF-012-12): con 10 µm y con 1 mm, los anillos de la exclusión
  siguen entrando en su zona y el límite pierde las celdas que no caen enteras dentro.
- **La tolerancia** (D-37): ≥ la de antes, creciente con la ulp y nunca mayor que 1 µm por
  coordenada; ``FRACTION_EPSILON`` de la 011, intacta.
"""

from __future__ import annotations

import math
import unittest
from datetime import date

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.gis.masks.test_combine import resolved_for

gis = import_geoblender("gis")
coverage = import_geoblender("gis.coverage")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
zones = import_geoblender("gis.masks.zones")
reserves_coverage = import_geoblender("reserves.coverage")

G = model.GeometryKind
T = model.ConstraintType

ULP_M = float(np.spacing(fx.BASE[1] + 100.0))
"""1 ulp de un norte de 4,4 Mm (9,3·10⁻¹⁰ m): el residuo de un ``float64`` en un UTM."""
MICRON_M = 1e-6
NOISES = ((0.0, "sin ruido"), (ULP_M, "1 ulp"), (MICRON_M, "1 µm"))
EXCLUSION = (20.0, 20.0, 32.0, 32.0)    # 12 × 12 m, alineada con celdas de 1 m
LIMIT = (20.0, 20.0, 50.0, 50.0)        # 30 × 30 m


def shifted(value: float, meters: float) -> float:
    """``value`` desplazado ``meters`` (con signo) **sin pasar de ello**: un múltiplo entero del
    paso de ``float64`` de ``value``, así que la suma es exacta y el ruido es el pedido o, como
    mucho, un paso menos (un ``value + 1e-6`` redondearía a veces a más de 1 µm)."""
    step = float(np.spacing(value))
    return value + math.copysign(math.floor(abs(meters) / step) * step, meters)


def square(box: tuple[float, float, float, float], out: float) -> np.ndarray:
    """El anillo ABSOLUTO del rectángulo local ``box`` (m desde ``fx.BASE``), con cada lado
    desplazado ``out`` m **hacia fuera** (negativo, hacia dentro): ruido en las dos coordenadas."""
    left, bottom, right, top = box
    x0, y0 = fx.BASE
    west, east = shifted(x0 + left, -out), shifted(x0 + right, out)
    south, north = shifted(y0 + bottom, -out), shifted(y0 + top, out)
    return np.array([(west, south), (east, south), (east, north), (west, north), (west, south)],
                    dtype=np.float64)


def constraint(ring: np.ndarray, *, code: str = "r_zona",
               ctype: model.ConstraintType = T.EXCLUSION) -> model.Constraint:
    """Una restricción poligonal mínima con su anillo absoluto."""
    return model.Constraint(
        uid=code.ljust(32, "0"), code=code, name=code, ctype=ctype, kind=G.POLYGON,
        parts=((ring,),), priority=1, reason="Prueba", decided_by="IMGA",
        decided_on=date(2026, 11, 1), decision_uid=None, intention_uid=None, source_input=None,
        source_fid=None, layer="core_constraint_polygon", fid=1)


class NoiseHelperTest(unittest.TestCase):
    """Las ayudas de esta prueba ponen de verdad el ruido que dicen."""

    def test_the_noise_is_at_most_what_is_asked_and_not_less_than_one_step(self) -> None:
        box = EXCLUSION
        exact = square(box, 0.0)
        self.assertTrue(np.array_equal(exact, fx.rectangle(*box)))
        for meters, label in NOISES[1:]:
            ring = square(box, meters)
            delta = np.abs(ring - exact)[:4]
            self.assertTrue(np.all(delta > 0.0), label)
            self.assertTrue(np.all(delta <= meters), label)
            self.assertTrue(np.all(delta >= meters - 2 * ULP_M), label)
        inside = square(box, -MICRON_M)   # hacia dentro: el vértice suroeste sube y va al este
        self.assertTrue(np.all(inside[0] > exact[0]))
        self.assertTrue(np.all(inside[0] - exact[0] <= MICRON_M))
        self.assertTrue(np.all(inside[2] < exact[2]))


class AlignedWithNoiseTest(unittest.TestCase):
    """RF-012-12: lo alineado con la rejilla sigue alineado con el ruido de un UTM."""

    def setUp(self) -> None:
        self.grid = fx.mask_grid(1.0)

    def zone_cells(self, out: float, outward: float = 0.0, grid=None) -> int:
        item = constraint(square(EXCLUSION, out))
        return zones.zone_runs(item, grid or self.grid, outward).cells

    def limit(self, out: float, inward: float = 0.0, grid=None):
        item = constraint(square(LIMIT, out), ctype=T.LEGAL_LIMIT)
        grid = grid or self.grid
        return zones.limit_runs(zones.edges_of(item, grid), grid, inward)

    def test_exclusion_takes_its_144_cells_with_noise_in_or_out(self) -> None:
        """Una exclusión de 12 × 12 m alineada: 144 celdas, no 192 (1 ulp) ni 196 (1 µm)."""
        for meters, label in NOISES:
            for sign in (1.0, -1.0):
                with self.subTest(noise=label, sign=sign):
                    self.assertEqual(self.zone_cells(sign * meters), 144)

    def test_limit_takes_its_900_whole_cells_with_noise_in_or_out(self) -> None:
        """Un límite de 30 × 30 m alineado: 900 celdas enteras dentro, no 784 (1 ulp hacia
        dentro: perdía el anillo de 116 celdas)."""
        for meters, label in NOISES:
            for sign in (1.0, -1.0):
                with self.subTest(noise=label, sign=sign):
                    found = self.limit(sign * meters)
                    self.assertEqual(found.inside.cells, 900)
                    self.assertEqual(found.band.cells, 0)

    def test_setback_ring_is_the_same_with_noise(self) -> None:
        """Con 2 m hacia fuera, la zona de la exclusión son 16 × 16 = 256 celdas (la de las
        celdas a 2 m justos no entra), también con ruido; y con 3 m hacia dentro, la banda del
        límite son 30² − 24² = 324 celdas y el núcleo 576."""
        for meters, label in NOISES:
            for sign in (1.0, -1.0):
                with self.subTest(noise=label, sign=sign):
                    self.assertEqual(self.zone_cells(sign * meters, 2.0), 256)
                    found = self.limit(sign * meters, 3.0)
                    self.assertEqual(found.band.cells, 324)
                    self.assertEqual(found.core.cells, 576)

    def test_a_literal_micron_added_to_the_coordinates(self) -> None:
        """Un «+ 1e-6» escrito a pelo (la suma se redondea a la ulp más cercana, de modo que a un
        norte de 4,4 Mm queda en 1,00026 µm) tampoco cambia las 144 y 900 celdas."""
        noise = 1e-6
        for sign in (1.0, -1.0):
            with self.subTest(sign=sign):
                grow = sign * noise
                exclusion = fx.absolute([(20 - grow, 20 - grow), (32 + grow, 20 - grow),
                                         (32 + grow, 32 + grow), (20 - grow, 32 + grow),
                                         (20 - grow, 20 - grow)])
                limit = fx.absolute([(20 - grow, 20 - grow), (50 + grow, 20 - grow),
                                     (50 + grow, 50 + grow), (20 - grow, 50 + grow),
                                     (20 - grow, 20 - grow)])
                self.assertGreater(abs(float(limit[0, 1]) - (fx.BASE[1] + 20)), 0.0)
                self.assertEqual(
                    zones.zone_runs(constraint(exclusion), self.grid, 0.0).cells, 144)
                item = constraint(limit, ctype=T.LEGAL_LIMIT)
                found = zones.limit_runs(zones.edges_of(item, self.grid), self.grid, 0.0)
                self.assertEqual(found.inside.cells, 900)

    def test_non_square_cells_too(self) -> None:
        """Con celdas de 2 × 0,5 m (la exclusión: 6 × 24 = 144 celdas; con 2 m de resguardo,
        8 × 32 = 256; el límite: 15 × 60 = 900) y las mismas cifras con ruido."""
        grid = gis.Grid(fx.BASE[0], fx.BASE[1] + 70.0, 2.0, 0.5, 70, 140)
        for meters, label in NOISES:
            for sign in (1.0, -1.0):
                with self.subTest(noise=label, sign=sign):
                    self.assertEqual(self.zone_cells(sign * meters, grid=grid), 144)
                    self.assertEqual(self.limit(sign * meters, grid=grid).inside.cells, 900)
                    self.assertEqual(self.zone_cells(sign * meters, 2.0, grid=grid), 8 * 32)

    def test_by_pieces_equals_at_once_with_noise(self) -> None:
        """Por trozos de filas y de segmentos sale lo mismo que de una vez."""
        item = constraint(square(EXCLUSION, ULP_M))
        once = zones.zone_runs(item, self.grid, 2.0)
        pieces = zones.zone_runs(item, self.grid, 2.0, segments_per_step=1, rows_per_step=3)
        self.assertEqual(pieces, once)
        self.assertEqual(once.cells, 256)

    def test_prepare_gives_the_aligned_figures(self) -> None:
        """Por la compilación (``combine.prepare``): el límite legal de 30 × 30 m con 1 ulp hacia
        dentro y una exclusión de 12 × 12 m con 1 ulp hacia fuera dentro de otro de 60 × 60 m."""
        grid = gis.Grid(fx.BASE[0], fx.BASE[1] + 60.0, 1.0, 1.0, 60, 60)
        for meters, label in NOISES[1:]:
            with self.subTest(noise=label):
                legal = constraint(square((0.0, 0.0, 30.0, 30.0), -meters), code="r_concesion",
                                   ctype=T.LEGAL_LIMIT)
                prepared = combine.prepare([legal], resolved_for([legal], inward=0.0), grid)
                self.assertEqual(prepared.limits.legal.inside.cells, 900)
                big = constraint(square((0.0, 0.0, 60.0, 60.0), 0.0), code="r_concesion",
                                 ctype=T.LEGAL_LIMIT)
                item = constraint(square(EXCLUSION, meters), code="r_exclusion")
                items = [big, item]
                prepared = combine.prepare(items, resolved_for(items, outward=0.0, inward=0.0),
                                           grid)
                self.assertEqual(prepared.zones["r_exclusion"].runs.cells, 144)


class WhatInvadesStillCountsTest(unittest.TestCase):
    """RF-012-12: lo que de verdad invade una celda, entra (lado seguro, D-1)."""

    def setUp(self) -> None:
        self.grid = fx.mask_grid(1.0)

    def test_millimetre_and_10_micron_outward_take_the_ring(self) -> None:
        """Con 1 mm (y con 10 µm) hacia fuera, entran las 48 celdas de los cuatro lados (las
        esquinas, de 10⁻⁶ m² o menos, no)."""
        grid = self.grid
        for meters in (1e-3, 1e-5):
            with self.subTest(meters=meters):
                item = constraint(square(EXCLUSION, meters))
                runs = zones.zone_runs(item, grid, 0.0)
                self.assertGreaterEqual(runs.cells, 192)
                self.assertLessEqual(runs.cells, 196)
                mask = runs.mask(grid.shape)
                south, north = 20, 32
                for column in (19, 32):          # las columnas de los lados oeste y este
                    for row_south in range(south, north):
                        self.assertTrue(mask[grid.nrows - 1 - row_south, column])
                for row_south in (19, 32):       # y las filas de los lados sur y norte
                    for column in range(south, north):
                        self.assertTrue(mask[grid.nrows - 1 - row_south, column])

    def test_millimetre_inward_loses_the_cells_that_are_not_whole(self) -> None:
        """Un límite 1 mm (y 10 µm) hacia dentro ya no tiene enteras las 116 del anillo: 784."""
        for meters in (1e-3, 1e-5):
            with self.subTest(meters=meters):
                item = constraint(square(LIMIT, -meters), ctype=T.LEGAL_LIMIT)
                found = zones.limit_runs(zones.edges_of(item, self.grid), self.grid, 0.0)
                self.assertEqual(found.inside.cells, 784)

    def test_setback_still_counts_a_millimetre_closer(self) -> None:
        """Una exclusión 1 mm más cerca de lo alineado mete las celdas a 2 m − 1 mm con 2 m de
        resguardo (más de las 256 de la alineada)."""
        item = constraint(square(EXCLUSION, 1e-3))
        self.assertGreater(zones.zone_runs(item, self.grid, 2.0).cells, 256)


class ToleranceTest(unittest.TestCase):
    """D-37: la tolerancia crece con la ulp de las coordenadas y no pasa de 1 µm."""

    def grid_at(self, west: float, north: float, step: float = 1.0):
        return gis.Grid(west, north, step, step, 10, 10)

    def test_utm_noise_is_the_micron_cap(self) -> None:
        grid = fx.mask_grid(1.0)
        self.assertEqual(zones.noise_m(grid), 1e-6)

    def test_never_above_one_micron_whatever_the_coordinates(self) -> None:
        for west, north in ((0.0, 100.0), (500.0, 6e4), (7e5, 4.4e6), (3e5, 1e7), (1e9, 1e9)):
            with self.subTest(west=west, north=north):
                self.assertLessEqual(zones.noise_m(self.grid_at(west, north)), 1e-6)

    def test_grows_with_the_ulp(self) -> None:
        small = zones.noise_m(self.grid_at(0.0, 100.0))
        middle = zones.noise_m(self.grid_at(500.0, 6e4))
        self.assertGreater(small, 0.0)
        self.assertLess(small, middle)
        self.assertLess(middle, 1e-6)

    def test_fraction_tolerance_is_never_below_the_cubication_epsilon(self) -> None:
        """ε de la celda ≥ ε de la 011 (10⁻¹²), y con celdas de 1 m en un UTM, 2 µm de área
        (un lado de 1 µm en cada eje)."""
        origin = self.grid_at(0.0, 1.0)
        self.assertGreaterEqual(zones.fraction_epsilon(origin), coverage.FRACTION_EPSILON)
        # t = 1 µm más una ulp (9,3·10⁻¹⁰ m) de guardarlo: 2,002 µm con celdas de 1 m.
        self.assertAlmostEqual(zones.fraction_epsilon(fx.mask_grid(1.0)), 2e-6, delta=5e-9)
        coarse = gis.Grid(7e5, 4.4e6, 10.0, 10.0, 10, 10)
        self.assertAlmostEqual(zones.fraction_epsilon(coarse), 2e-7, delta=5e-10)
        slim = gis.Grid(7e5, 4.4e6, 2.0, 0.5, 10, 10)
        self.assertAlmostEqual(zones.fraction_epsilon(slim), 2.5e-6, delta=5e-9)

    def test_distance_tolerance_is_never_below_tau(self) -> None:
        self.assertEqual(zones.distance_tau(self.grid_at(0.0, 1.0)), zones.TAU_M)
        utm = zones.distance_tau(fx.mask_grid(1.0))
        self.assertGreater(utm, zones.TAU_M)
        self.assertLessEqual(utm, 2e-6)

    def test_the_cubication_epsilon_is_untouched(self) -> None:
        """La ε de la 011 (``gis.coverage``, ``reserves.coverage``) sigue siendo 10⁻¹²."""
        self.assertEqual(coverage.FRACTION_EPSILON, 1e-12)
        self.assertEqual(reserves_coverage.FRACTION_EPSILON, 1e-12)


if __name__ == "__main__":
    unittest.main()
