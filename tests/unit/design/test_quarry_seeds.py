# SPDX-License-Identifier: GPL-3.0-or-later
"""Las semillas «coronación y zonas a sostener» de la cantera (spec 014, T07; HU-014-1; RF-014-02,
RF-014-03; plan 014 A2, A3, §5.3.1).

- ``design.quarry.crown_ring``: la coronación ``C = dilate_square(R, k) ∧ ¬R ∧ isfinite(z)``, el
  anillo exterior de ``k`` celdas del recinto ``R`` con dato de terreno.
- ``design.quarry.hold_zones``: ``H``, la unión de las zonas de las restricciones intocables y sin
  corte de las máscaras (ya con su resguardo, ADR-0028).
- ``design.quarry.crown_seeds``: las semillas ``s = z`` en ``C ∪ H`` y en ninguna otra celda.
- ``design.quarry.outside_crown``: las semillas del usuario fuera de ``C ∪ H`` por grupos
  4-conexos, cada uno con sus celdas, su área en m² y el centro absoluto (float64) de sus celdas
  (error 10: sembrar «en toda la ladera» sube los fondos).

Sobre la cantera sintética de ``tests.support.quarry_fixtures`` (T01), con las cuentas a mano: el
recinto es el rectángulo de (45, 60) a (355, 340) menos la torre y «sin corte»; su anillo exterior
de 3 celdas, el de (42, 57) a (358, 343) menos el recinto exterior, 316 · 286 − 310 · 280 = 3.576
celdas; ``H``, la torre (224) y «sin corte» (1.600).
"""

from __future__ import annotations

import dataclasses
import unittest
from types import MappingProxyType
from typing import Any

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
seeds_mod = import_geoblender("design.seeds")
grids = import_geoblender("design.grids")
messages = import_geoblender("design.messages")
combine = import_geoblender("gis.masks.combine")
zones = import_geoblender("gis.masks.zones")

RING = 3
OUTER_RING_CELLS = 316 * 286 - 310 * 280
"""El anillo exterior de 3 celdas del recinto de la cantera, a mano: 3.576 celdas."""
HOLD_CELLS = qfx.TOWER_ZONE_CELLS + qfx.NO_CUT_CELLS
"""Las zonas a sostener de la cantera: la torre con su resguardo y «sin corte» (1.824 celdas)."""
CROWN_AND_HOLD_CELLS = OUTER_RING_CELLS + HOLD_CELLS
"""``C ∪ H`` en la cantera: los anillos de los agujeros (la torre y «sin corte») caen en ``H``."""
OUTSIDE_CELLS = qfx.SIZE * qfx.SIZE - 316 * 286
"""Lo de fuera del recinto dilatado: 160.000 − 90.376 = 69.624 celdas, centradas en (200, 200)."""
CUT_BIT = np.uint16(int(combine.ClassBit.CUT_ALLOWED))


def area_centre() -> tuple[float, float]:
    """El centro (absoluto) de las celdas del recinto, a mano: el rectángulo de (45, 60) a (355,
    340), centro (200, 200), menos «sin corte» (centro (80, 300), 1.600 celdas) y la torre (un
    disco simétrico alrededor de la esquina (300, 120), 224 celdas)."""
    cells = 310 * 280 - qfx.NO_CUT_CELLS - qfx.TOWER_ZONE_CELLS
    x = (310 * 280 * 200.0 - qfx.NO_CUT_CELLS * 80.0 - qfx.TOWER_ZONE_CELLS * 300.0) / cells
    y = (310 * 280 * 200.0 - qfx.NO_CUT_CELLS * 300.0 - qfx.TOWER_ZONE_CELLS * 120.0) / cells
    return qfx.BASE[0] + x, qfx.BASE[1] + y


class CrownSeedsTest(qfx.QuarryProjectCase):
    """Las semillas de la cantera con las máscaras de V01 (sin escribir nada en el proyecto)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.loaded = cls.masks(cls)  # type: ignore[arg-type]
        cls.start = qfx.terrain()
        cls.area = quarry.excavation_area(cls.loaded, cls.start)

    def test_hold_zones_are_the_untouchables_and_no_cut(self) -> None:
        """RF-014-02, A2: ``H`` es la torre con sus 8 m y «sin corte»; ni el límite, ni el
        perímetro, ni la banda hacia dentro."""
        hold = quarry.hold_zones(self.loaded)
        self.assertEqual(hold.dtype, np.bool_)
        self.assertEqual(int(hold.sum()), HOLD_CELLS)
        expected = (self.loaded.zone("torre").mask(qfx.GRID.shape)
                    | self.loaded.zone("sin_corte").mask(qfx.GRID.shape))
        np.testing.assert_array_equal(hold, expected)

    def test_crown_ring_is_the_outer_ring_of_the_area(self) -> None:
        """RF-014-02, A2: la coronación es el anillo de 3 celdas fuera del recinto, también
        alrededor de sus agujeros (que caen en ``H``)."""
        ring = quarry.crown_ring(self.area, self.start, RING)
        self.assertFalse((ring & self.area).any())
        outer = qfx.in_box((42.0, 57.0, 358.0, 343.0)) & ~qfx.in_box((45.0, 60.0, 355.0, 340.0))
        np.testing.assert_array_equal(ring & ~quarry.hold_zones(self.loaded), outer)
        self.assertEqual(int(outer.sum()), OUTER_RING_CELLS)

    def test_no_seed_outside_crown_and_hold(self) -> None:
        """RF-014-02: las semillas son el terreno en ``C ∪ H`` y en ninguna otra celda (``+inf``);
        las entradas no cambian."""
        start = self.start.copy()
        area = self.area.copy()
        found = quarry.crown_seeds(self.area, self.start, self.loaded, RING)
        self.assertIsInstance(found, seeds_mod.SeedSet)
        np.testing.assert_array_equal(self.start, start)
        np.testing.assert_array_equal(self.area, area)
        allowed = quarry.crown_ring(self.area, self.start, RING) | quarry.hold_zones(self.loaded)
        seeded = np.isfinite(found.grid)
        self.assertFalse((seeded & ~allowed).any())
        np.testing.assert_array_equal(seeded, allowed)
        np.testing.assert_array_equal(found.grid[seeded], self.start[seeded])
        self.assertTrue(np.all(found.grid[~seeded] == np.inf))
        self.assertEqual(found.cells, CROWN_AND_HOLD_CELLS)
        self.assertEqual(found.area_m2, CROWN_AND_HOLD_CELLS * qfx.GRID.cell_area)
        self.assertEqual(found.nodata_cells, 0)
        self.assertTrue(found.geometry.same_geometry(qfx.GRID))
        # El dominio de trabajo por defecto es el recinto: todas las semillas quedan fuera.
        np.testing.assert_array_equal(found.domain.mask, self.area)
        self.assertEqual(found.outside_domain, CROWN_AND_HOLD_CELLS)
        self.assertEqual(quarry.outside_crown(found, self.area, self.start, self.loaded, RING),
                         ())

    def test_seeds_all_over_the_slope_are_grouped(self) -> None:
        """RF-014-03, A3 (error 10): sembrar en toda la ladera deja fuera de ``C ∪ H`` dos grupos,
        lo de fuera del recinto dilatado (el primero de norte a sur) y el recinto, con sus celdas,
        su área y su centro absoluto a ≤ 10⁻⁹ m del cálculo a mano."""
        groups = quarry.outside_crown(self.start, self.area, self.start, self.loaded, RING)
        self.assertEqual(len(groups), 2)
        first, second = groups
        self.assertIsInstance(first, quarry.SeedGroup)
        self.assertEqual((first.group, second.group), (1, 2))
        self.assertEqual(first.cells, OUTSIDE_CELLS)
        self.assertEqual(second.cells, qfx.CUT_ALLOWED_CELLS)
        self.assertEqual(first.area_m2, OUTSIDE_CELLS * qfx.GRID.cell_area)
        self.assertEqual(second.area_m2, qfx.CUT_ALLOWED_CELLS * qfx.GRID.cell_area)
        self.assertEqual(first.cells + second.cells, qfx.SIZE * qfx.SIZE - CROWN_AND_HOLD_CELLS)
        self.assertIsInstance(first.x, float)
        self.assertAlmostEqual(first.x, qfx.BASE[0] + 200.0, delta=1e-9)
        self.assertAlmostEqual(first.y, qfx.BASE[1] + 200.0, delta=1e-9)
        x, y = area_centre()
        self.assertAlmostEqual(second.x, x, delta=1e-9)
        self.assertAlmostEqual(second.y, y, delta=1e-9)

    def test_a_seed_set_from_the_013_is_accepted(self) -> None:
        """RF-014-03: unas semillas de la 013 (un ``SeedSet``) se miran por sus celdas con cota."""
        user = quarry.crown_seeds(self.area, self.start, self.loaded, RING)
        values = user.grid.copy()
        values[200, 200] = 250.0  # una celda dentro del recinto
        values[200, 201] = 250.0
        loose = dataclasses.replace(user, grid=values)
        groups = quarry.outside_crown(loose, self.area, self.start, self.loaded, RING)
        self.assertEqual([(g.group, g.cells) for g in groups], [(1, 2)])
        x, y = qfx.GRID.centers(slice(200, 201))
        self.assertAlmostEqual(groups[0].x, (x[0, 200] + x[0, 201]) / 2, delta=1e-9)
        self.assertEqual(groups[0].y, float(y[0, 200]))

    def test_the_ring_width_is_checked(self) -> None:
        """RF-014-02: el anillo de coronación es un entero en [1; 50] celdas (``check_quarry_param``)."""
        for wrong in (0, 51):
            with self.assertRaises(messages.DesignError) as caught:
                quarry.crown_seeds(self.area, self.start, self.loaded, wrong)
            self.assertEqual(caught.exception.code, "des.quarry_param_range")
        with self.assertRaises(TypeError):
            quarry.crown_ring(self.area, self.start, 2.5)


class HandRingTest(unittest.TestCase):
    """El anillo de 3 celdas a mano en un recinto pequeño de la rejilla de la cantera."""

    def setUp(self) -> None:
        shape = qfx.GRID.shape
        self.area = np.zeros(shape, dtype=bool)
        self.area[10:20, 30:40] = True  # 10 × 10
        self.start = qfx.terrain()

    def test_ring_of_three_cells(self) -> None:
        """A2: el anillo de un cuadrado de 10 × 10 es el de 16 × 16 menos el cuadrado (156
        celdas); una celda sin terreno no es de la coronación."""
        ring = quarry.crown_ring(self.area, self.start, 3)
        expected = np.zeros_like(self.area)
        expected[7:23, 27:43] = True
        expected[10:20, 30:40] = False
        np.testing.assert_array_equal(ring, expected)
        self.assertEqual(int(ring.sum()), 156)
        start = self.start.copy()
        start[7, 27] = np.nan
        ring = quarry.crown_ring(self.area, start, 3)
        self.assertEqual(int(ring.sum()), 155)
        self.assertFalse(ring[7, 27])

    def test_hold_zone_with_no_terrain_is_counted(self) -> None:
        """A2: con unas máscaras de mano (un intocable de 2 × 2 lejos del recinto, una zona sin
        corte con una celda sin terreno y una exclusión, que no es a sostener), las semillas son
        el anillo y las zonas a sostener con terreno; la celda sin terreno se cuenta."""
        shape = qfx.GRID.shape
        tower = np.zeros(shape, dtype=bool)
        tower[100:102, 100:102] = True
        no_cut = np.zeros(shape, dtype=bool)
        no_cut[200:203, 200:203] = True
        other = np.zeros(shape, dtype=bool)
        other[300:310, 300:310] = True
        masks = Masks(shape, {"t": (tower, "untouchable"), "n": (no_cut, "no_cut"),
                              "e": (other, "exclusion")})
        start = self.start.copy()
        start[201, 201] = np.nan
        found = quarry.crown_seeds(self.area, start, masks, 3)
        self.assertEqual(found.cells, 156 + 4 + 8)
        self.assertEqual(found.nodata_cells, 1)
        self.assertTrue(np.isinf(found.grid[305, 305]))
        self.assertEqual(found.grid[100, 100], start[100, 100])


class Masks:
    """Unas máscaras de mano con lo que leen las semillas: ``grid``, ``zone(code)`` y ``ctypes``."""

    def __init__(self, shape: tuple[int, int], found: dict[str, tuple[np.ndarray, str]]) -> None:
        self.grid = qfx.GRID
        self.zones = {code: zones.Runs.from_mask(mask) for code, (mask, _) in found.items()}
        self.ctypes = MappingProxyType({code: ctype for code, (_, ctype) in found.items()})
        self.classes = np.zeros(shape, dtype=np.uint16)

    def zone(self, code: str) -> Any:
        return self.zones[code]


if __name__ == "__main__":
    unittest.main()
