# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de referencia de las envolventes y el escalonado (spec 013, T01; plan 013 §7.1;
CE-013-01 a CE-013-05, CE-013-07 y CE-013-09).

Comprueba ``tests.support.design_fixtures`` antes de que lo usen las pruebas del núcleo (que aún no
existe), sin el núcleo: las cifras de cada caso con cuentas hechas a mano.

- **Cono** (CE-013-01): una semilla en el centro de 201 × 201 celdas de 1 m; las distancias entre
  centros de celda con triángulos pitagóricos (3-4-5, 5-12-13, 8-15-17, 20-21-29, 60-80-100) y los
  100 m de eje y 100√2 m de diagonal; la ascendente y la descendente exactas; la distancia analítica
  de un punto.
- **Pared** (CE-013-01): una columna entera de semillas, alineada con la rejilla.
- **Perfiles** (CE-013-03; RF-013-20): ``EXPL_10_60_6`` (11,77 m y 40,3°), ``REST_5_35_6`` (13,14 m
  y 20,83°) y ``DESD_10_45_6`` (16,00 m y 32,0°) y las cotas de berma ``z₀ + n·h`` a mano.
- **Plano inclinado** (CE-013-03): una superficie con pendiente 0,25 exacta en binario.
- **Sectores** (CE-013-04, CE-013-05): el de 10,6° con ``REST_5_35_6`` (berma de 19,5765237 m,
  que el RF-013-25 y CE-013-04 citan como 19,576 m) y tres con taludes distintos.
- **Corta circular** (CE-013-09; inv. 07 §3.10): 1.308.944,006 m³ analíticos (como la 006, ADR-0014)
  con celdas de 1 y de 2 m.
- **Ladera y relleno ×40** (CE-013-07; errores 10, 17, 56 y 66): las semillas «en toda la ladera»
  con sus celdas fuera del dominio y el relleno de 716.000 m³ frente a 17.607 m³.
- **El proyecto del diseño**: el de las restricciones (V01 y V02, 160 × 160 celdas de 2 m, los
  límites, las cinco restricciones y los dos sectores) con las búsquedas de los dos sectores
  cerradas, la superficie de partida del sitio y las máscaras de V01 compiladas; creado una vez por
  proceso y copiado en menos de 1 s.

Ningún dato de cliente: todo es sintético.
"""

from __future__ import annotations

import math
import re
import time
import unittest
from collections.abc import Callable
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as fx
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
access = import_geoblender("gis.masks.access")
combine = import_geoblender("gis.masks.combine")
gis_store = import_geoblender("gis.store")

BUILD_BUDGET_S = 1.0
"""«Los datos se construyen en < 1 s por prueba» (tarea T01)."""
HAND = 1e-12
"""Cuentas a mano en float64."""
PIT_M3_006 = 1_308_944.006
"""El volumen analítico de la corta circular de la 006 (ADR-0014; inv. 07 §3.10), al dm³."""


def _fast(test: unittest.TestCase, build: Callable[[], Any]) -> Any:
    """``build()``, comprobando que tarda menos de :data:`BUILD_BUDGET_S`."""
    started = time.perf_counter()
    found = build()
    test.assertLess(time.perf_counter() - started, BUILD_BUDGET_S)
    return found


def _ring_area(ring: np.ndarray) -> float:
    return cfx.ring_area(ring)


class ConeTest(unittest.TestCase):
    """CE-013-01: el cono de una semilla en 201 × 201."""

    def setUp(self) -> None:
        self.case = _fast(self, fx.cone_case)

    def test_grid_and_seed(self) -> None:
        """201 × 201 celdas de 1 m desde la esquina de los casos; la semilla, en la celda del
        centro, con su cota; su punto, el centro de esa celda (x = oeste + 100,5; y = norte −
        100,5)."""
        grid = self.case.grid
        self.assertEqual((grid.nrows, grid.ncols, grid.dx, grid.dy), (201, 201, 1.0, 1.0))
        self.assertEqual((grid.west, grid.north), (cfx.BASE[0], cfx.BASE[1] + 201.0))
        self.assertEqual((self.case.seed_row, self.case.seed_col), (100, 100))
        self.assertEqual(self.case.seed_point, (cfx.BASE[0] + 100.5, cfx.BASE[1] + 100.5))
        seeds = self.case.seeds()
        self.assertEqual(seeds.shape, (201, 201))
        self.assertEqual(int(np.isfinite(seeds).sum()), 1)
        self.assertEqual(seeds[100, 100], self.case.seed_z)
        self.assertTrue(np.isposinf(seeds[np.isinf(seeds)]).all())

    def test_every_call_gives_a_new_array(self) -> None:
        """Cada llamada da arrays nuevos: cambiar uno no cambia los siguientes."""
        seeds = self.case.seeds()
        seeds[0, 0] = 5.0
        distances = self.case.distances()
        distances[0, 0] = -1.0
        self.assertTrue(np.isposinf(self.case.seeds()[0, 0]))
        self.assertAlmostEqual(self.case.distances()[0, 0], 100.0 * math.sqrt(2.0), delta=HAND)

    def test_distances_by_hand(self) -> None:
        """La distancia entre centros de celda, a mano, en los cuatro cuadrantes."""
        distances = self.case.distances()
        self.assertEqual(distances[100, 100], 0.0)
        for drow, dcol, expected in fx.CONE_HAND:
            for sign_row in (1, -1):
                for sign_col in (1, -1):
                    cell = (100 + sign_row * drow, 100 + sign_col * dcol)
                    self.assertAlmostEqual(distances[cell], expected, delta=HAND, msg=str(cell))
        self.assertAlmostEqual(distances[0, 0], 100.0 * math.sqrt(2.0), delta=HAND)
        self.assertAlmostEqual(distances[0, 100], 100.0, delta=HAND)

    def test_up_and_down(self) -> None:
        """E_up = f + t·d y E_down = f − t·d, con la tangente de 35° y la cota de la semilla."""
        tangent = math.tan(math.radians(35.0))
        self.assertAlmostEqual(self.case.slope_tan, tangent, delta=HAND)
        up, down = self.case.up(), self.case.down()
        self.assertEqual(up[100, 100], self.case.seed_z)
        self.assertEqual(down[100, 100], self.case.seed_z)
        self.assertAlmostEqual(up[100, 200], self.case.seed_z + tangent * 100.0, delta=HAND)
        self.assertAlmostEqual(down[100, 0], self.case.seed_z - tangent * 100.0, delta=HAND)
        self.assertAlmostEqual(up[0, 0], self.case.seed_z + tangent * 100.0 * math.sqrt(2.0),
                               delta=HAND)
        self.assertTrue(np.allclose(up - self.case.seed_z, self.case.seed_z - down, atol=HAND))

    def test_analytic_distance_of_a_point(self) -> None:
        """La distancia analítica del punto de la semilla da las de entre centros (≤ 10⁻⁹ m) y la
        de un punto desplazado dentro de su celda difiere menos de media celda."""
        grid = self.case.grid
        x, y = self.case.seed_point
        centred = fx.analytic_distance(grid, x, y)
        self.assertLessEqual(float(np.abs(centred - self.case.distances()).max()), 1e-9)
        shifted = fx.analytic_distance(grid, x + 0.25, y - 0.125)
        self.assertLess(float(np.abs(shifted - self.case.distances()).max()),
                        math.hypot(0.25, 0.125) + HAND)
        self.assertLess(math.hypot(0.25, 0.125), 0.5 * grid.dx)


class WallTest(unittest.TestCase):
    """CE-013-01: una pared plana alineada con la rejilla."""

    def test_wall_column(self) -> None:
        """Una columna entera de semillas a la misma cota; E_up = f + t·h·|c − columna| y la
        descendente su espejo, a mano, con pasos de 1 y de 2 m."""
        for step in (1.0, 2.0):
            case = _fast(self, lambda step=step: fx.wall_case(step))
            self.assertEqual((case.grid.dx, case.grid.dy), (step, step))
            seeds = case.seeds()
            self.assertTrue(np.array_equal(np.isfinite(seeds)[:, case.column],
                                           np.ones(case.grid.nrows, dtype=bool)))
            self.assertEqual(int(np.isfinite(seeds).sum()), case.grid.nrows)
            self.assertTrue((seeds[np.isfinite(seeds)] == case.wall_z).all())
            up, down = case.up(), case.down()
            for column in (0, case.column, case.grid.ncols - 1):
                expected = case.slope_tan * step * abs(column - case.column)
                self.assertAlmostEqual(up[7, column], case.wall_z + expected, delta=HAND)
                self.assertAlmostEqual(down[7, column], case.wall_z - expected, delta=HAND)
            self.assertAlmostEqual(up[0, case.column + 5],
                                   case.wall_z + case.slope_tan * step * 5, delta=HAND)


class ScatterTest(unittest.TestCase):
    """Semillas dispersas deterministas (CE-013-02)."""

    def test_scattered_seeds(self) -> None:
        """La misma semilla da lo mismo; el número de semillas, el pedido; las cotas, múltiplos de
        0,25 m (exactos en binario) dentro del rango; sin semillas repetidas; un recuento
        imposible se rechaza."""
        first = fx.scattered_seeds((40, 30), 25, seed=3)
        again = fx.scattered_seeds((40, 30), 25, seed=3)
        other = fx.scattered_seeds((40, 30), 25, seed=4)
        self.assertEqual(first.shape, (40, 30))
        self.assertTrue(np.array_equal(first, again))
        self.assertFalse(np.array_equal(first, other))
        heights = first[np.isfinite(first)]
        self.assertEqual(heights.size, 25)
        self.assertTrue(((heights >= 100.0) & (heights <= 130.0)).all())
        self.assertTrue(np.array_equal(heights * 4.0, np.round(heights * 4.0)))
        self.assertTrue(np.isposinf(first[~np.isfinite(first)]).all())
        with self.assertRaises(ValueError):
            fx.scattered_seeds((3, 3), 10, seed=1)


class ProfilesTest(unittest.TestCase):
    """Los perfiles de banco y sus derivados a mano (RF-013-20)."""

    def test_derived_values(self) -> None:
        """EXPL_10_60_6: 10/√3 + 6 = 11,77 m y 40,3°; REST_5_35_6: 5/tan 35° + 6 = 13,14 m y
        20,83°; DESD_10_45_6: 16 m y 32,0° (≤ 10⁻⁹ relativo frente a la fórmula)."""
        by_hand = {
            "EXPL_10_60_6": (10.0 / math.sqrt(3.0) + 6.0,
                             math.degrees(math.atan(10.0 / (10.0 / math.sqrt(3.0) + 6.0)))),
            "REST_5_35_6": (5.0 / math.tan(math.radians(35.0)) + 6.0,
                            math.degrees(math.atan(5.0 / (5.0 / math.tan(math.radians(35.0))
                                                          + 6.0)))),
            "DESD_10_45_6": (16.0, math.degrees(math.atan(10.0 / 16.0))),
        }
        self.assertEqual(set(fx.PROFILES), set(by_hand))
        for name, (advance, general) in by_hand.items():
            profile = fx.PROFILES[name]
            self.assertEqual(profile.name, name)
            self.assertLessEqual(abs(profile.advance_m - advance) / advance, 1e-12)
            self.assertLessEqual(abs(profile.general_deg - general) / general, 1e-12)
            self.assertAlmostEqual(profile.general_tan, profile.height_m / advance, delta=1e-15)
        self.assertEqual([round(fx.PROFILES[n].advance_m, 2) for n in by_hand],
                         [11.77, 13.14, 16.00])
        self.assertEqual([round(fx.PROFILES[n].general_deg, 2) for n in by_hand],
                         [40.34, 20.83, 32.01])
        self.assertEqual([round(fx.PROFILES[n].general_deg, 1) for n in by_hand],
                         [40.3, 20.8, 32.0])

    def test_names_and_codes(self) -> None:
        """Nombres con altura, cara y berma; código ASCII en minúsculas del nombre (D-17); factor
        de malla 1,0; ancla de 125 m."""
        for name, profile in fx.PROFILES.items():
            _, height, face, berm = name.split("_")
            self.assertEqual((profile.height_m, profile.face_deg, profile.berm_m),
                             (float(height), float(face), float(berm)))
            self.assertEqual(profile.code, name.lower())
            self.assertRegex(profile.code, re.compile(r"^[a-z][a-z0-9_]*$"))
            self.assertEqual((profile.mesh_factor, profile.anchor_m), (1.0, 125.0))
        self.assertIs(fx.EXPL_10_60_6, fx.PROFILES["EXPL_10_60_6"])
        self.assertIs(fx.REST_5_35_6, fx.PROFILES["REST_5_35_6"])

    def test_hand_levels(self) -> None:
        """Las cotas z₀ + n·h dentro de un rango, a mano (el ancla incluida si cae dentro)."""
        self.assertEqual(fx.hand_levels(fx.EXPL_10_60_6, 140.125, 179.875),
                         (145.0, 155.0, 165.0, 175.0))
        self.assertEqual(fx.hand_levels(fx.REST_5_35_6, 140.125, 179.875),
                         (145.0, 150.0, 155.0, 160.0, 165.0, 170.0, 175.0))
        self.assertEqual(fx.hand_levels(fx.EXPL_10_60_6, 125.0, 145.0), (125.0, 135.0, 145.0))
        self.assertEqual(fx.hand_levels(fx.EXPL_10_60_6, 100.0, 126.0), (105.0, 115.0, 125.0))


class PlaneTest(unittest.TestCase):
    """CE-013-03: el plano inclinado."""

    def test_surface(self) -> None:
        """160 × 40 celdas de 1 m; cota 140 + 0,25·(columna + 0,5): exacta en binario, de 140,125
        a 179,875 m, igual en todas las filas."""
        case = _fast(self, fx.plane_case)
        self.assertEqual((case.grid.nrows, case.grid.ncols, case.grid.dx), (40, 160, 1.0))
        surface = case.surface()
        self.assertEqual(surface.shape, (40, 160))
        self.assertEqual((float(surface.min()), float(surface.max())), (140.125, 179.875))
        self.assertEqual(surface[3, 7], 140.0 + 0.25 * 7.5)
        self.assertTrue((surface == surface[0]).all())
        self.assertEqual(case.slope_tan, 0.25)
        surface[0, 0] = 0.0
        self.assertEqual(case.surface()[0, 0], 140.125)


class SectorsTest(unittest.TestCase):
    """CE-013-04 y CE-013-05: los sectores con talud impuesto."""

    def test_imposed_berm_by_hand(self) -> None:
        """B_s = máx(B, h/tan β − h/tan α) con REST_5_35_6 y β = 10,6°: 5/tan 10,6° − 5/tan 35° =
        19,5765237 m (el «19,576 m» del RF-013-25 truncado al mm); el sector sin talud, los 6 m."""
        by_hand = 5.0 / math.tan(math.radians(10.6)) - 5.0 / math.tan(math.radians(35.0))
        self.assertLessEqual(abs(fx.IMPOSED_BERM_M - by_hand) / by_hand, 1e-12)
        self.assertEqual(math.floor(fx.IMPOSED_BERM_M * 1000.0) / 1000.0, 19.576)
        self.assertEqual(fx.IMPOSED_DEG, 10.6)
        case = _fast(self, fx.imposed_sector_case)
        self.assertEqual(case.codes, ("frente_tendido", "frente_normal"))
        self.assertEqual(case.imposed_deg, (10.6, None))
        self.assertEqual(case.profile, fx.REST_5_35_6)
        self.assertAlmostEqual(case.berm_m("frente_tendido"), fx.IMPOSED_BERM_M, delta=HAND)
        self.assertEqual(case.berm_m("frente_normal"), 6.0)
        with self.assertRaises(KeyError):
            case.berm_m("no_existe")
        self.assertGreater(fx.IMPOSED_BERM_M, fx.REST_5_35_6.berm_m)

    def test_two_sectors(self) -> None:
        """120 × 100 celdas de 1 m en dos mitades de 60 columnas: las etiquetas, los anillos
        absolutos (área = celdas × área de celda) y la cresta (la fila norte, a la cota de
        cresta)."""
        case = fx.imposed_sector_case()
        self.assertEqual((case.grid.nrows, case.grid.ncols), (100, 120))
        labels = case.labels()
        self.assertEqual(labels.dtype, np.int16)
        self.assertEqual([int((labels == i).sum()) for i in (0, 1, 2)], [0, 6000, 6000])
        self.assertTrue((labels[:, :60] == 1).all() and (labels[:, 60:] == 2).all())
        rings = case.rings()
        self.assertEqual(tuple(rings), case.codes)
        for index, code in enumerate(case.codes, start=1):
            ring = rings[code]
            self.assertTrue(np.array_equal(ring[0], ring[-1]))
            self.assertAlmostEqual(_ring_area(ring), (labels == index).sum() * case.grid.cell_area,
                                   delta=HAND)
        left = rings["frente_tendido"]
        self.assertEqual((float(left[:, 0].min()), float(left[:, 0].max())),
                         (case.grid.west, case.grid.west + 60.0))
        self.assertEqual((float(left[:, 1].min()), float(left[:, 1].max())),
                         (case.grid.north - 100.0, case.grid.north))
        seeds = case.seeds()
        self.assertEqual(int(np.isfinite(seeds).sum()), 120)
        self.assertTrue((seeds[0] == case.crest_z).all())

    def test_three_sectors(self) -> None:
        """CE-013-05: tres sectores de 50 columnas con taludes distintos (10,6°, 18° y el del
        perfil), 150 × 100 celdas; bermas a mano: 19,5765 m, 5/tan 18° − 5/tan 35° = 8,2477 m y
        6 m."""
        case = _fast(self, fx.three_sectors_case)
        self.assertEqual((case.grid.nrows, case.grid.ncols), (100, 150))
        self.assertEqual(case.imposed_deg, (10.6, 18.0, None))
        labels = case.labels()
        self.assertEqual([int((labels == i).sum()) for i in (0, 1, 2, 3)], [0, 5000, 5000, 5000])
        second = 5.0 / math.tan(math.radians(18.0)) - 5.0 / math.tan(math.radians(35.0))
        berms = [case.berm_m(code) for code in case.codes]
        self.assertAlmostEqual(berms[0], fx.IMPOSED_BERM_M, delta=HAND)
        self.assertAlmostEqual(berms[1], second, delta=HAND)
        self.assertEqual(berms[2], 6.0)
        self.assertAlmostEqual(second, 8.2477, delta=5e-5)
        self.assertEqual(len(case.rings()), 3)


class PitTest(unittest.TestCase):
    """CE-013-09: la corta circular de inv. 07 §3.10 (R = 50 m, seis bancos de 10 m, cara de 70°,
    berma de 8 m, terreno llano a 60 m)."""

    def test_analytic_volume(self) -> None:
        """La suma de los seis troncos de cono da 1.308.944,0056 m³ (la 006: 1.308.944,006 al dm³)
        y el radio de la boca, 111,84 m, cabe en la rejilla (120 m de medio lado)."""
        case = fx.pit_case(1.0)
        face = 10.0 / math.tan(math.radians(70.0))
        total = 0.0
        for index in range(6):
            lower = 50.0 + index * (face + 8.0)
            upper = lower + face
            total += math.pi * 10.0 / 3.0 * (lower * lower + lower * upper + upper * upper)
        self.assertAlmostEqual(case.analytic_m3, total, delta=1e-6)
        self.assertAlmostEqual(case.analytic_m3, PIT_M3_006, delta=5e-4)
        self.assertAlmostEqual(case.top_radius_m, 50.0 + 5.0 * (face + 8.0) + face, delta=1e-9)
        self.assertLess(case.top_radius_m, 120.0)
        self.assertEqual((case.depth_m, case.terrain_z, case.floor_z), (60.0, 60.0, 0.0))
        self.assertEqual(case.profile.height_m, 10.0)
        self.assertEqual((case.profile.face_deg, case.profile.berm_m, case.profile.anchor_m),
                         (70.0, 8.0, 0.0))

    def test_cells_seeds_and_sampled_surface(self) -> None:
        """Con celdas de 1 y de 2 m: 240 m de lado con el eje en un nodo; el terreno llano a
        60 m; la semilla, el disco del fondo a cota 0 (su área, a ≤ 1 % de π·50²); y la corta
        muestreada en los centros de celda cubica lo analítico a ≤ 0,01 % (006: ≤ 0,0039 %)."""
        for step in (1.0, 2.0):
            case = _fast(self, lambda step=step: fx.pit_case(step))
            cells = int(240.0 / step)
            self.assertEqual((case.grid.nrows, case.grid.ncols), (cells, cells))
            self.assertEqual((case.grid.dx, case.grid.dy), (step, step))
            self.assertEqual(case.axis, (case.grid.west + 120.0, case.grid.north - 120.0))
            terrain = case.terrain()
            self.assertTrue((terrain == 60.0).all())
            seeds = case.seeds()
            finite = np.isfinite(seeds)
            self.assertTrue((seeds[finite] == 0.0).all())
            disc = finite.sum() * case.grid.cell_area
            self.assertLessEqual(abs(disc - math.pi * 50.0 ** 2) / (math.pi * 50.0 ** 2), 0.01)
            surface = case.surface()
            self.assertEqual((float(surface.min()), float(surface.max())), (0.0, 60.0))
            cut = float(np.sum(terrain - surface)) * case.grid.cell_area
            self.assertLessEqual(abs(cut - case.analytic_m3) / case.analytic_m3, 1e-4)
            self.assertAlmostEqual(case.cut_m3, cut, delta=1e-6)
            plateaus = [int(np.isclose(surface, level, atol=1e-9).sum()) for level in
                        (10.0, 20.0, 30.0, 40.0, 50.0)]
            self.assertTrue(all(count > 100 for count in plateaus), plateaus)

    def test_bad_step_is_refused(self) -> None:
        """Un paso que no deja el eje en un nodo (o no divide el lado) se rechaza."""
        for step in (0.0, -1.0, 7.0, 0.7):
            with self.assertRaises(ValueError, msg=str(step)):
                fx.pit_case(step)


class HillsideTest(unittest.TestCase):
    """CE-013-07: las semillas «en toda la ladera» y el relleno ×40."""

    def test_seeds_on_the_whole_hillside(self) -> None:
        """100 × 100 celdas de 2 m; la ladera sube al norte (tan = 0,5); semillas en las 60 filas
        del norte sobre el terreno (6.000 celdas, 24.000 m²); el dominio, las 80 × 80 interiores
        (6.400 celdas); 4.000 semillas dentro y 2.000 fuera; las semillas tocan el borde de la
        rejilla."""
        case = _fast(self, fx.hillside_case)
        self.assertEqual((case.grid.nrows, case.grid.ncols, case.grid.dx), (100, 100, 2.0))
        terrain = case.terrain()
        self.assertTrue((terrain[:-1] > terrain[1:]).all())  # sube hacia el norte (fila 0)
        self.assertAlmostEqual(float(terrain[0, 0] - terrain[1, 0]), 0.5 * 2.0, delta=HAND)
        seeds = case.seeds()
        finite = np.isfinite(seeds)
        self.assertEqual(int(finite.sum()), 6000)
        self.assertEqual(int(finite[:60].sum()), 6000)
        self.assertTrue(np.array_equal(seeds[finite], terrain[finite]))
        self.assertEqual(finite.sum() * case.grid.cell_area, 24_000.0)
        domain = case.domain()
        self.assertEqual(domain.dtype, bool)
        self.assertEqual(int(domain.sum()), 6400)
        self.assertEqual(int((finite & domain).sum()), 4000)
        self.assertEqual(int((finite & ~domain).sum()), 2000)
        self.assertEqual((case.seed_cells, case.inside_domain, case.outside_domain),
                         (6000, 4000, 2000))
        edge = np.zeros_like(finite)
        edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
        self.assertTrue((finite & edge).any())

    def test_fill_growth(self) -> None:
        """716.000 m³ frente a los 17.607 m³ de la revisión anterior: ×40,66, por encima del
        umbral de aviso (2,0) y de 40."""
        self.assertEqual((fx.FILL_PREVIOUS_M3, fx.FILL_CURRENT_M3), (17_607.0, 716_000.0))
        ratio = fx.FILL_CURRENT_M3 / fx.FILL_PREVIOUS_M3
        self.assertAlmostEqual(fx.FILL_RATIO, ratio, delta=HAND)
        self.assertGreater(ratio, 40.0)
        self.assertLess(ratio, 41.0)


class DesignProjectTest(fx.DesignProjectCase):
    """El proyecto del diseño: el de las restricciones con lo que necesita la 013."""

    def test_versions_and_grid(self) -> None:
        """V01 y V02 de la 012, en la rejilla del sitio (160 × 160 celdas de 2 m, ≤ 200 × 200),
        con las cinco restricciones y los dos sectores."""
        self.assertEqual((self.v1.code, self.v2.code), ("V01", "V02"))
        self.assertLessEqual(max(cfx.SITE_GRID.shape), 200)
        self.assertEqual(cfx.SITE_GRID.shape, (160, 160))
        codes = sorted(item.code for item in self.stored_constraints())
        self.assertEqual(codes, ["balsa", "concesion", "cuneta", "perimetro", "torre"])
        states = access.sector_states(self.project, self.v1.uid)
        self.assertEqual([state.code for state in states], ["sector_1", "sector_2"])

    def test_searches_are_closed_and_masks_compiled(self) -> None:
        """Las búsquedas de los dos sectores están cerradas (ninguno pendiente) y las máscaras
        de V01 compiladas y al día; las de V02, sin compilar."""
        for state in access.sector_states(self.project, self.v1.uid):
            self.assertIsNotNone(state.search, state.code)
        found, pending = access.mask_state(self.project, self.v1.uid)
        self.assertIs(found, access.MaskState.CURRENT)
        self.assertEqual(pending, ())
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.MISSING)

    def test_masks_by_hand(self) -> None:
        """Las máscaras de V01 en la rejilla del sitio: dominio por defecto = perímetro ∩ límite
        (27.600 m² = 6.900 celdas de 4 m²) − la zona de la torre con 8 m (60 celdas) = 6.840; la
        franja de solo relleno, 6.800 m² = 1.700 celdas (CE-012-03); cortar y rellenar, dentro del
        dominio."""
        masks = self.masks()
        self.assertEqual(masks.grid, cfx.SITE_GRID)
        domain = masks.default_domain()
        self.assertEqual(domain.shape, cfx.SITE_GRID.shape)
        self.assertEqual(int(domain.sum()), 27_600 // 4 - cfx.TOWER_ZONE_CELLS)
        self.assertEqual(masks.zone("torre").cells, cfx.TOWER_ZONE_CELLS)
        self.assertEqual(int(masks.fill_strip().sum()), 6_800 // 4)
        self.assertTrue((masks.cut_allowed() <= domain).all())
        self.assertTrue((masks.fill_allowed() <= (domain | masks.fill_strip())).all())
        self.assertEqual(int((masks.classes & np.uint16(int(combine.ClassBit.FILL_STRIP))
                              ).astype(bool).sum()), 6_800 // 4)

    def test_start_surface_is_a_project_grid(self) -> None:
        """La superficie de partida del sitio (el llano a 650 m) es una rejilla del proyecto:
        ``gis.store.load_raster`` la lee igual que ``site_start`` (CRS y datum vertical
        incluidos)."""
        raster = gis_store.load_raster(self.project, fx.START_DATASET)
        expected = cfx.site_start()
        self.assertEqual(raster.grid, cfx.SITE_GRID)
        self.assertTrue(np.array_equal(raster.values, expected.values))
        self.assertEqual((raster.crs, raster.vertical), (expected.crs, expected.vertical))

    def test_write_surfaces_adds_project_grids(self) -> None:
        """``write_surfaces`` escribe más superficies como rejillas del proyecto."""
        ramp = cfx.site_start().values + np.linspace(0.0, 1.0, 160)[None, :]
        self.write_surfaces(("rampa", gis.Raster(cfx.SITE_GRID, ramp, cfx.CRS, cfx.VERTICAL)))
        raster = gis_store.load_raster(self.project, "gis_dtm_rampa")
        self.assertTrue(np.array_equal(raster.values, ramp))

    def test_copies_are_cheap_and_independent(self) -> None:
        """El proyecto se crea una vez por proceso y una copia propia tarda menos de 1 s; lo que
        se escribe en ella no está en la plantilla ni en otra copia."""
        template = fx.project_template()
        self.assertIs(template, fx.project_template())
        started = time.perf_counter()
        with fx.open_design_project() as (project, _clock):
            elapsed = time.perf_counter() - started
            with project.write_transaction() as conn:
                conn.execute("CREATE TABLE copia_privada (fid INTEGER)")
        self.assertLess(elapsed, BUILD_BUDGET_S)
        with fx.open_design_project() as (other, _clock):
            with other.read() as conn:
                found = conn.execute("SELECT name FROM sqlite_master "
                                     "WHERE name = 'copia_privada'").fetchall()
        self.assertEqual(found, [])
        self.assertEqual(self.query("SELECT name FROM sqlite_master "
                                    "WHERE name = 'copia_privada'"), [])


if __name__ == "__main__":
    unittest.main()
