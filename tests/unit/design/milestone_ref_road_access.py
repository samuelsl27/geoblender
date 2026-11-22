# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia de la accesibilidad de la cantera con bancos y del tajo con dos superficies, como prueba de **hito** (spec 017, T16, que lo dejó en el «verde» como
``tests/referencia/des/test_ref_road_access.py``; T48, que lo pasó al paso «hito» de ``tools/check.py --completo`` para que el «verde» vuelva a costar ≤ +3 s: RNF-017-09): CE-017-07 (T16; HU-017-3; RF-017-24 y 25; CE-017-07 y CE-017-05; plan 017
§5.4 A10 y A11; error 23): una entrada a 140 m, cuatro bermas a 135, 125, 115 y 105 m y una rampa grabada del 12,5 % que comunica las tres superiores, contra el **cálculo a mano**.

Verifica **de forma independiente** lo que hace ``design.road_access``: lo alcanzable sale de la pendiente local a mano, la apertura con el disco exacto y la inundación 4-conexa de
``tests.support.road_data`` (no de llamar al código bajo prueba) y lo demás, de las cifras de la cantera sintética (``road_data``: las cotas, las áreas y los lugares a mano). Todo es
sintético y sin Blender, sobre la rejilla de 1 m de la cantera (400 × 400).

- **CE-017-07 · las bermas** (RF-017-25): **tres bermas comunicadas y una no**, con su cota real (135, 125, 115 y 105 m), su área (8.000 m²) y su lugar (el centroide); un tramo con menos del
  área mínima (280 m² frente a 300) no se lista.
- **CE-017-07 · la cota mínima** (RF-017-24): la cota mínima alcanzable es 115 m y la máxima, 140 m (el terreno de la entrada).
- **CE-017-07 · la plataforma y las zonas** (RF-017-25): la plataforma de la berma de 125 m queda comunicada a 125 m; la zona «requiere acceso» de la berma de 135 m, comunicada; la de la berma
  de 105 m, **no**, con su lugar, a 16 m de lo alcanzable más próximo (la berma de 115 m) y 10 m más baja.
- **CE-017-05 · las dos superficies** (RF-017-24, error 23): en el tajo, con la explotación hasta 125 m y la final con el fondo relleno hasta 140 m, la cota mínima alcanzable es 125 m sobre la
  explotación y 140 m sobre la final.
- **Nada cambia** (RF-017-25): ninguna superficie ni restricción cambia (resumen de todo lo que se lee, antes y después).
"""

from __future__ import annotations

import hashlib
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender

road_access = import_geoblender("design.road_access")
road_model = import_geoblender("design.road_model")

TOL = 1e-9
"""RF-017-24 y 25: las cotas y las áreas, a ≤ 10⁻⁹ m (o m²) del cálculo a mano."""
SMALL_BERM_BOX = (300.0, 20.0, 320.0, 34.0)
"""Un tramo de berma de 20 × 14 m = 280 m², menor que el área mínima de la referencia (300 m²): no se lista (a 130 m, en el terreno de la entrada)."""
SMALL_BERM_LEVEL_M = 130.0


def flat_cells(mask: np.ndarray) -> np.ndarray:
    """Los índices de la rejilla en filas de las celdas de ``mask``."""
    return np.flatnonzero(mask.ravel())


def digest(*arrays: np.ndarray) -> str:
    """El resumen de unos arrays (para comprobar que no cambian)."""
    return hashlib.sha256(b"".join(np.ascontiguousarray(array).tobytes() for array in arrays)).hexdigest()


def reachable_by_hand(surface: np.ndarray, entry: tuple[float, float]) -> np.ndarray:
    """Lo alcanzable **a mano** con los umbrales de la referencia (16 % y 4 m): la pendiente local de ``road_data.oracle_slope_pct``, la apertura con el disco exacto de
    ``road_data.oracle_disc_opening`` y la inundación 4-conexa con una cola de ``road_data.oracle_reachable`` desde la entrada local ``entry``."""
    walkable = rd.oracle_slope_pct(surface, rd.STEP_M) <= rd.ACCESS.walk_slope_pct
    return rd.oracle_reachable(rd.oracle_disc_opening(walkable, rd.ACCESS.walk_width_m / 2.0, rd.STEP_M), [rd.cell_of(entry, rd.GRID)])


class BankTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.GRID
        cls.surface = rd.bank_surface(cls.grid)
        levels = rd.bank_berms(cls.grid)
        levels[rd.in_box(SMALL_BERM_BOX, cls.grid)] = SMALL_BERM_LEVEL_M
        cls.levels = levels
        cls.platform = road_model.AccessCells("PLT-001", "Plataforma de la berma 125", flat_cells(rd.bank_platform_mask(cls.grid)))
        cls.zones = tuple(road_model.AccessCells(code, name, flat_cells(rd.bank_zone_mask(name, cls.grid)))
                          for code, name in (("zona_sin_acceso", "Zona sin acceso"), ("zona_con_acceso", "Zona con acceso")))
        cls.job = rd.access_job(cls.grid, cls.surface, [rd.BANK_ENTRY], access=rd.ACCESS, berms=[road_model.BermGrid("bancos", levels)], platforms=[cls.platform], zones=cls.zones)
        cls.keep = digest(cls.job.surface, cls.job.untouchable, cls.job.berms[0].levels, cls.platform.cells, *(zone.cells for zone in cls.zones))
        cls.found = road_access.access(cls.job)
        cls.by_hand = reachable_by_hand(cls.surface, rd.BANK_ENTRY)

    def test_the_reachable_grid_is_the_flood_by_hand(self) -> None:
        """RF-017-24, CE-017-07: lo alcanzable es la inundación a mano (pendiente ≤ 16 %, ancho ≥ 4 m, desde la entrada) y sus cotas, 115 y 140 m (a ≤ 10⁻⁹): **la cota mínima
        alcanzable es 115 m**, no la de la berma de 105 m, que no se comunica."""
        np.testing.assert_array_equal(self.found.reachable, self.by_hand)
        self.assertAlmostEqual(self.found.z_min_m, rd.BANK_Z_MIN_M, delta=TOL)
        self.assertAlmostEqual(self.found.z_max_m, rd.BANK_Z_MAX_M, delta=TOL)
        self.assertAlmostEqual(self.found.z_min_m, float(self.surface[self.by_hand].min()), delta=TOL)
        self.assertAlmostEqual(self.found.area_m2, float(self.by_hand.sum()) * self.grid.cell_area, delta=TOL)
        self.assertIsNone(self.found.z_min_final_m, "una cantera de una superficie no da la cota sobre la final")

    def test_three_berms_are_reached_and_one_is_not_with_their_level_area_and_place(self) -> None:
        """RF-017-25, CE-017-07: **tres bermas comunicadas (135, 125 y 115 m) y una no (105 m)**, cada una con su cota real, su área (8.000 m²: 400 × 20 m) y su lugar (el centro de
        la berma: x = 200 m y la mitad de su rango de y), todo igual al cálculo a mano a ≤ 10⁻⁹; y el tramo de 280 m² (menor que el área mínima de 300 m²) **no se lista**."""
        found = self.found.berms
        self.assertEqual(len(found), 4, "las cuatro bermas; la de 280 m² no se lista")
        self.assertEqual([stretch.number for stretch in found], [1, 2, 3, 4])
        by_level = {round(stretch.level_m, 9): stretch for stretch in found}
        self.assertEqual(sorted(by_level), sorted(rd.BANK_LEVELS))
        self.assertNotIn(SMALL_BERM_LEVEL_M, by_level)
        for level, (low, high) in zip(rd.BANK_LEVELS, rd.BANK_BERM_RANGES, strict=True):
            with self.subTest(level=level):
                stretch = by_level[level]
                self.assertEqual(stretch.connected, level in rd.BANK_COMMUNICATED)
                self.assertAlmostEqual(stretch.area_m2, rd.BANK_BERM_AREA_M2, delta=TOL)
                where = rd.absolute([(200.0, (low + high) / 2.0)], self.grid)[0]
                self.assertAlmostEqual(stretch.x, float(where[0]), delta=TOL)
                self.assertAlmostEqual(stretch.y, float(where[1]), delta=TOL)
                self.assertEqual(stretch.source, "bancos")
        self.assertEqual(sum(stretch.connected for stretch in found), 3)
        self.assertEqual([stretch.level_m for stretch in found if not stretch.connected], list(rd.BANK_NOT_COMMUNICATED))
        listed_with_small = road_access.access(rd.access_job(self.grid, self.surface, [rd.BANK_ENTRY], access=rd.AccessData(16.0, 4.0, 200.0),
                                                              berms=[road_model.BermGrid("bancos", self.levels)])).berms
        self.assertEqual(len(listed_with_small), 5, "con un área mínima de 200 m² el tramo de 280 m² sí se lista")

    def test_the_platform_is_reached_at_its_level_and_the_zone_without_access_is_listed(self) -> None:
        """RF-017-25, CE-017-07: la plataforma de la berma de 125 m queda comunicada a 125 m; la zona «requiere acceso» de la berma de 135 m (al este de las rampas), comunicada; la
        de la berma de 105 m, **no**: se lista con su lugar (su celda más próxima a lo alcanzable, la de x = 160,5 m e y = 140,5 m), la distancia (16 m a la berma de 115 m) y la diferencia
        de cota (10 m: 115 − 105), todo a ≤ 10⁻⁹ del cálculo a mano."""
        platform = self.found.platforms[0]
        self.assertEqual((platform.code, platform.connected), ("PLT-001", True))
        self.assertAlmostEqual(platform.level_m, rd.BANK_PLATFORM_Z_M, delta=TOL)
        without, with_access = self.found.zones
        self.assertEqual((without.code, without.connected), ("zona_sin_acceso", False))
        self.assertEqual((with_access.code, with_access.connected), ("zona_con_acceso", True))
        self.assertEqual((with_access.x, with_access.y, with_access.distance_m, with_access.level_difference_m), (None, None, None, None))
        place = rd.absolute([(160.5, 140.5)], self.grid)[0]
        self.assertAlmostEqual(without.x, float(place[0]), delta=TOL)
        self.assertAlmostEqual(without.y, float(place[1]), delta=TOL)
        self.assertAlmostEqual(without.distance_m, 16.0, delta=TOL)
        self.assertAlmostEqual(without.level_difference_m, rd.BANK_ZONE_LEVEL_GAP_M, delta=TOL)
        best = rd.oracle_nearest_reachable(self.zones[0].cells, self.by_hand, self.surface)
        self.assertEqual((best[0], best[2]), (256, 115.0), "a 16 celdas de la berma de 115 m, por fuerza bruta")
        self.assertEqual(divmod(best[1], self.grid.ncols), rd.cell_of((160.5, 140.5), self.grid), "la celda de la zona más próxima a lo alcanzable es su esquina suroeste")

    def test_nothing_that_is_read_changes(self) -> None:
        """RF-017-25: ninguna superficie ni restricción cambia: el resumen de la superficie, de lo intocable, de las cotas de berma y de las celdas de la plataforma y de las zonas es el de
        antes de calcular, y todo lo que se lee es de solo lectura."""
        again = road_access.access(self.job)
        np.testing.assert_array_equal(again.reachable, self.found.reachable)
        self.assertEqual(digest(self.job.surface, self.job.untouchable, self.job.berms[0].levels, self.platform.cells, *(zone.cells for zone in self.zones)), self.keep)
        for array in (self.job.surface, self.job.untouchable, self.job.berms[0].levels, self.platform.cells, self.found.reachable):
            self.assertFalse(array.flags.writeable)


class PitTest(unittest.TestCase):
    def test_the_lowest_reachable_level_is_125_m_on_the_exploitation_and_140_m_on_the_final(self) -> None:
        """RF-017-24, CE-017-05, error 23: en el tajo (terreno a 141 m, fondo a 125 m con un corredor del 8 %), la cota mínima alcanzable sobre la superficie de explotación es 125 m
        (el fondo, por el corredor) y sobre la final restaurada (el fondo relleno hasta 140 m), **140 m** y no la de la explotación; con los mismos parámetros (16 % y 4 m) y la entrada
        del tajo, a ≤ 10⁻⁹ m, y lo alcanzable es la inundación a mano en cada una."""
        grid = rd.GRID
        exploitation, final = rd.pit_exploitation(grid), rd.pit_final(grid)
        job = rd.access_job(grid, exploitation, [rd.PIT_ENTRY], access=rd.ACCESS, final=final)
        keep = digest(job.surface, job.final, job.untouchable)
        found = road_access.access(job)
        self.assertAlmostEqual(found.z_min_m, rd.PIT_Z_MIN_EXPLOITATION_M, delta=TOL)
        self.assertAlmostEqual(found.z_min_final_m, rd.PIT_Z_MIN_FINAL_M, delta=TOL)
        np.testing.assert_array_equal(found.reachable, reachable_by_hand(exploitation, rd.PIT_ENTRY))
        by_hand_final = reachable_by_hand(final, rd.PIT_ENTRY)
        self.assertAlmostEqual(float(final[by_hand_final].min()), rd.PIT_Z_MIN_FINAL_M, delta=TOL)
        self.assertEqual(digest(job.surface, job.final, job.untouchable), keep)
        self.assertEqual((found.berms, found.platforms, found.zones), ((), (), ()))


if __name__ == "__main__":
    unittest.main()
