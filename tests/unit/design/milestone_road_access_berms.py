# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_access_berms» (spec 017, T16; RF-017-24 y 25; RNF-017-05 y 06; plan 017 §5.4 A11 y §7.3): lo que pasa de 1 s y no entra en el «verde»
(``tools/check.py``, RNF-017-09). El «verde» deja en ``test_road_access_berms`` lo que cubre cada RF (en mallas de ≤ 200 × 200 celdas); esto lo ejecuta el paso «hito» de
``tools/check.py --completo`` (la publicación lo pide siempre).

- **A10 y A11 sobre 2,81 M celdas** (RNF-017-05, RNF-017-06; plan §7.3, rejilla de 1.654 × 1.699 celdas de 1 m, pendiente transitable del 12 % y ancho mínimo de 10 m): 250 tramos de
  berma de 640 m², 5 plataformas y 20 zonas «requiere acceso», con una franja intocable de 12 m que parte la rejilla (la entrada al oeste: 110 tramos y 3 plataformas comunicados, y la mitad
  de las zonas, no) y, aparte, con la superficie final de una cantera de dos superficies: la accesibilidad entera tarda ≤ 5 s (RNF-017-05; el plan midió 0,17 s para A10 y 0,34 s con dos
  superficies, **sin** la distancia exacta de las zonas sin comunicar, que añade ≈ 0,65 s) y cada llamada del paso, ≤ 0,2 s (RNF-017-06); las listas son las de la fórmula a mano
  (la franja decide qué se alcanza: las bermas de las columnas ≤ 10 y la distancia de cada zona sin comunicar a su borde oeste, x = 699,5 m).
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import least_of

road_access = import_geoblender("design.road_access")
road_model = import_geoblender("design.road_model")

STEP_LIMIT_S = 0.2
"""Lo que puede tardar cada llamada del paso (RNF-017-06)."""
TOTAL_LIMIT_S = 5.0
"""Lo que puede tardar la accesibilidad entera sobre 2,81 M celdas (RNF-017-05, en disco local)."""
WALK_SLOPE_PCT, WALK_WIDTH_M, MIN_BERM_AREA_M2 = 12.0, 10.0, 300.0
"""La pendiente transitable, el ancho mínimo (HIPÓTESIS de la prueba: ninguno es valor por defecto) y el área mínima de berma de la referencia de IMGA (300 m²)."""
WALL_X0_M, WALL_X1_M = 700.0, 712.0
"""La franja intocable (x local, m): lo alcanzable desde la entrada del oeste acaba en la celda de x = 699,5 m."""
LAST_REACHABLE_X_M = 699.5
EAST_COLUMN = 10
"""Las bermas de las columnas ≤ 10 (x ≤ 100 + 60 · 10 = 700 m) quedan del lado de la entrada."""


class ScaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.scale_grid()
        x, y = rd.local_centers(cls.grid)
        cls.terrain = 150.0 + 4.0 * np.sin(x / 150.0) + 3.0 * np.cos(y / 120.0)
        cls.wall = rd.in_box((WALL_X0_M, 0.0, WALL_X1_M, float(cls.grid.nrows)), cls.grid)
        cls.boxes = rd.scale_berm_boxes()
        levels = np.full(cls.grid.shape, np.nan)
        for index, box in enumerate(cls.boxes):
            levels[rd.in_box(box, cls.grid)] = 100.0 + index
        cls.levels = levels

        def cells(box: tuple[float, float, float, float]) -> np.ndarray:
            return np.flatnonzero(rd.in_box(box, cls.grid).ravel())

        cls.platforms = [road_model.AccessCells(f"PLT-{n:03d}", f"P{n}", cells(box)) for n, box in enumerate(rd.scale_platform_boxes(), start=1)]
        cls.zones = [road_model.AccessCells(f"z{n}", f"Z{n}", cells(box)) for n, box in enumerate(rd.scale_zone_boxes(), start=1)]

    def job(self, final: bool) -> Any:
        return rd.access_job(self.grid, self.terrain, [(10.5, 10.5)], untouchable=self.wall, access=rd.AccessData(WALK_SLOPE_PCT, WALK_WIDTH_M, MIN_BERM_AREA_M2),
                             final=self.terrain + 0.5 if final else None, berms=[road_model.BermGrid("bancos", self.levels)], platforms=self.platforms, zones=self.zones)

    @staticmethod
    def timed(job: Any) -> tuple[Any, float, float, int]:
        """La accesibilidad por pasos: el resultado, la llamada más larga al generador (s), el total (s) y cuántas llamadas fueron."""
        steps = road_access.access_steps(job)
        longest, count, total, last = 0.0, 0, 0.0, None
        while True:
            before = time.perf_counter()
            try:
                last = next(steps)
            except StopIteration:
                break
            spent = time.perf_counter() - before
            longest, count, total = max(longest, spent), count + 1, total + spent
        return last.result, longest, total, count

    def check(self, job: Any) -> Any:
        """Recorre la accesibilidad por pasos y comprueba el plazo total y el de cada llamada (la mejor de dos pasadas para la más larga: la prueba es de plazo)."""
        found, longest, total, count = self.timed(job)
        self.assertGreater(count, 10, "cede el hilo por unidades")
        self.assertLessEqual(total, TOTAL_LIMIT_S, f"la accesibilidad tardó {total:.2f} s sobre {self.grid.nrows * self.grid.ncols:,} celdas")
        if longest > STEP_LIMIT_S:
            longest = least_of(lambda: self.timed(job)[1], STEP_LIMIT_S, attempts=2, max_attempts=2)
        self.assertLessEqual(longest, STEP_LIMIT_S, f"una llamada de {longest:.3f} s (el total de la pasada, {total:.2f} s)")
        return found

    def test_250_berm_stretches_5_platforms_and_20_zones_in_at_most_5_s_and_calls_of_at_most_0_2_s(self) -> None:
        """RNF-017-05, RNF-017-06, RF-017-25: sobre 2,81 M celdas, con 250 tramos de berma (de 640 m²), 5 plataformas y 20 zonas, la accesibilidad entera tarda ≤ 5 s y cada llamada
        del paso, ≤ 0,2 s; con la superficie final de una cantera de dos superficies, lo mismo. Las listas son las de la fórmula a mano: los tramos de las columnas ≤ 10 comunicados, con su
        cota (100 + el número de la caja), su área (640 m²) y su lugar (el centro de su caja); las plataformas de las columnas ≤ 10, comunicadas a su cota (la menor de la huella);
        las zonas sin comunicar, con su lugar (la celda más al norte de su borde oeste), su distancia a x = 699,5 m y su diferencia de cota."""
        for final in (False, True):
            with self.subTest(final=final):
                job = self.job(final)
                found = self.check(job)
                self.assertEqual(found.z_min_final_m is None, not final)
                if final:
                    self.assertEqual(found.z_min_final_m, float(self.terrain[found.reachable].min()) + 0.5)
                self.assertEqual(len(found.berms), 250)
                # los tramos salen en el orden de su primera celda desde el norte: se comparan por su cota, que es la de su caja
                by_level = {round(stretch.level_m, 6): stretch for stretch in found.berms}
                self.assertEqual(sorted(by_level), [100.0 + index for index in range(250)])
                for index, box in enumerate(self.boxes):
                    stretch = by_level[100.0 + index]
                    column = index % 25
                    self.assertEqual(stretch.connected, column <= EAST_COLUMN, f"la caja {index}")
                    self.assertAlmostEqual(stretch.area_m2, 640.0, delta=1e-9)
                    where = rd.absolute([((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)], self.grid)[0]
                    self.assertAlmostEqual(stretch.x, float(where[0]), delta=1e-9)
                    self.assertAlmostEqual(stretch.y, float(where[1]), delta=1e-9)
                self.assertEqual(sum(stretch.connected for stretch in found.berms), 110)
                self.assertEqual([item.connected for item in found.platforms], [(index % 25) <= EAST_COLUMN for index in (0, 60, 120, 180, 240)])
                for item, platform in zip(found.platforms, self.platforms, strict=True):
                    if item.connected:
                        self.assertEqual(item.level_m, float(self.terrain.ravel()[platform.cells].min()))
                    else:
                        self.assertIsNone(item.level_m)
                self.check_zones(found)

    def check_zones(self, found: Any) -> None:
        """Las zonas: las de las columnas ≤ 10 comunicadas; las demás, con su lugar (su celda más al norte del borde oeste), la distancia a x = 699,5 m (en su misma fila) y la
        diferencia de cota (la de ese punto menos la de su celda), a ≤ 10⁻⁹."""
        origin_x, origin_y = rd.origin_of(self.grid)
        for k, item in enumerate(found.zones):
            index = 10 + 12 * k
            row, column = divmod(index, 25)
            self.assertEqual(item.connected, column <= EAST_COLUMN, f"la zona {k}")
            if item.connected:
                continue
            local_x, local_y = 64.5 + 60.0 * column, 73.5 + 150.0 * row
            self.assertAlmostEqual(item.x - origin_x, local_x, delta=1e-9)
            self.assertAlmostEqual(item.y - origin_y, local_y, delta=1e-9)
            self.assertAlmostEqual(item.distance_m, local_x - LAST_REACHABLE_X_M, delta=1e-9)
            expected = 4.0 * (np.sin(LAST_REACHABLE_X_M / 150.0) - np.sin(local_x / 150.0))
            self.assertAlmostEqual(item.level_difference_m, float(expected), delta=1e-9)
        self.assertEqual(sum(item.connected for item in found.zones), 10)


if __name__ == "__main__":
    unittest.main()
