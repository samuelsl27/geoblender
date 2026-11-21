# SPDX-License-Identifier: GPL-3.0-or-later
"""Bermas, plataformas y zonas comunicadas, y las dos superficies de una cantera (spec 017, T16; HU-017-3; RF-017-25 y 24; CE-017-07; RNF-017-05; plan 017 §5.4 A11):
``road_access.access`` dice de cada **tramo de berma** (una componente 4-conexa de la rejilla de cotas de berma de la 013 con al menos el área mínima) si queda comunicado, con su
cota real, su área y su lugar; de cada **plataforma** si queda comunicada y a qué cota (la menor de las celdas alcanzables de su huella); de cada zona **«requiere acceso»** si queda
comunicada y, de las que no, su lugar, la distancia y la diferencia de cota a lo alcanzable más próximo; y, donde la versión tenga una cantera con **dos superficies**, la cota mínima
alcanzable sobre la final con los mismos parámetros. **No cambia ninguna superficie ni restricción.**

Los valores esperados salen **a mano** y por **fuerza bruta** (los tramos con una búsqueda en anchura 4-conexa, la distancia con todas las parejas de celdas, lo alcanzable con la
inundación de ``road_data.oracle_reachable``), **no** de llamar al código bajo prueba. Todo es sintético, sin Blender y sobre rejillas de ≤ 200 × 200 celdas; el caso de referencia
entero (CE-017-07) es de ``tests/referencia/des/test_ref_road_access.py`` y la medida a escala, de ``milestone_road_access_berms``.
"""

from __future__ import annotations

import hashlib
import math
import time
import unittest
from collections import deque
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import road_data as rd
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
road_access = import_geoblender("design.road_access")
road_model = import_geoblender("design.road_model")
zones_module = import_geoblender("gis.masks.zones")

ROWS, COLS = 40, 60
GRID = gis.Grid(cfx.BASE[0], cfx.BASE[1] + float(ROWS), 1.0, 1.0, COLS, ROWS)
"""La rejilla de las pruebas: 60 × 40 celdas de 1 m (la esquina suroeste en ``BASE``), con las coordenadas locales de ``rd.local_centers``."""
TOL = 1e-9
"""La tolerancia de las cuentas a mano (RF-017-25: ≤ 10⁻⁹ m)."""
MIN_AREA_M2 = 20.0
"""El área mínima de un tramo de berma de los casos (m²; HIPÓTESIS de la prueba, D-17: no es valor por defecto)."""
WALK = rd.AccessData(10.0, 1.0, MIN_AREA_M2)
"""Los umbrales de los casos: hasta el 10 %, ancho de 1 m (el disco de radio 0,5 celdas es el de una sola celda: la apertura no cambia nada) y el área mínima de arriba."""
WALL = (30.0, 0.0, 34.0, 40.0)
"""La franja intocable que parte la rejilla en la parte de la entrada (x < 30 m) y la que queda del otro lado (x > 34 m)."""
ENTRY = (10.5, 20.5)
"""La entrada (local), en la parte del oeste."""


def flat_cells(box: tuple[float, float, float, float], grid: Any = GRID) -> np.ndarray:
    """Los índices de la rejilla en filas (``fila · columnas + columna``) de las celdas con el centro dentro de la caja local ``box``."""
    return np.flatnonzero(rd.in_box(box, grid).ravel())


def levels_of(*boxes: tuple[tuple[float, float, float, float], float], grid: Any = GRID) -> np.ndarray:
    """Una rejilla de cotas de berma (``nan`` fuera de las bermas) con la cota de cada caja local."""
    found = np.full(grid.shape, np.nan)
    for box, level in boxes:
        found[rd.in_box(box, grid)] = level
    return found


def east_down(grid: Any = GRID) -> np.ndarray:
    """Un plano que **baja** al este: ``z = 100 + 0,05 · (60 − x)`` (5 %): cada celda tiene su cota y la menor está en el este."""
    x, _y = rd.local_centers(grid)
    return 100.0 + 0.05 * (60.0 - x)


def digest(*arrays: np.ndarray) -> str:
    """El resumen de unos arrays (para comprobar que no cambian)."""
    return hashlib.sha256(b"".join(np.ascontiguousarray(array).tobytes() for array in arrays)).hexdigest()


def stretches_by_hand(levels: np.ndarray, grid: Any, min_area_m2: float) -> list[dict[str, Any]]:
    """Los tramos de berma **a mano**: las componentes 4-conexas de las celdas con cota (una búsqueda en anchura con una cola, en el orden de su primera celda recorriendo la
    rejilla fila a fila desde el norte), las de al menos ``min_area_m2`` m²; de cada una, sus celdas, su cota (la media de las de sus celdas), su área y su lugar (la media de los
    centros de sus celdas, absoluta)."""
    rows, cols = levels.shape
    seen = np.zeros(levels.shape, dtype=bool)
    found: list[dict[str, Any]] = []
    for first_row in range(rows):
        for first_col in range(cols):
            if seen[first_row, first_col] or not math.isfinite(float(levels[first_row, first_col])):
                continue
            queue: deque[tuple[int, int]] = deque([(first_row, first_col)])
            seen[first_row, first_col] = True
            cells: list[tuple[int, int]] = []
            while queue:
                row, col = queue.popleft()
                cells.append((row, col))
                for near_row, near_col in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                    if 0 <= near_row < rows and 0 <= near_col < cols and not seen[near_row, near_col] and math.isfinite(float(levels[near_row, near_col])):
                        seen[near_row, near_col] = True
                        queue.append((near_row, near_col))
            area = len(cells) * grid.cell_area
            if area >= min_area_m2:
                found.append({"cells": cells, "level": math.fsum(float(levels[r, c]) for r, c in cells) / len(cells), "area": area,
                              "x": grid.west + (math.fsum(c for _r, c in cells) / len(cells) + 0.5) * grid.dx,
                              "y": grid.north - (math.fsum(r for r, _c in cells) / len(cells) + 0.5) * grid.dy})
    return found


def zone_by_hand(zone: np.ndarray, reachable: np.ndarray, surface: np.ndarray, grid: Any) -> dict[str, Any]:
    """Una zona «requiere acceso» **a mano**: si alguna de sus celdas es alcanzable; y si no, la de ellas más próxima a lo alcanzable (a igual distancia, la de menor índice) con su
    lugar, la distancia (m, entre centros) y la diferencia de cota (la cota de la celda alcanzable más próxima —a igual distancia, la menor— menos la de la celda de la zona)."""
    cells = sorted(int(c) for c in zone)
    if not cells:
        return {"connected": False}
    if any(bool(reachable.ravel()[c]) for c in cells):
        return {"connected": True}
    first_row, first_col = divmod(cells[0], grid.ncols)
    place = (grid.west + (first_col + 0.5) * grid.dx, grid.north - (first_row + 0.5) * grid.dy)
    best = rd.oracle_nearest_reachable(cells, reachable, surface)
    if best is None:
        return {"connected": False, "x": place[0], "y": place[1], "distance": None, "difference": None}
    row, col = divmod(best[1], grid.ncols)
    return {"connected": False, "x": grid.west + (col + 0.5) * grid.dx, "y": grid.north - (row + 0.5) * grid.dy, "distance": math.sqrt(best[0]) * grid.dx,
            "difference": best[2] - float(surface[row, col])}


def bank_levels() -> np.ndarray:
    """Las bermas del caso: A (100 celdas a 135 m, comunicada), B (150 a 125 m, del otro lado de la franja), C (9 celdas: no se lista), D (20 celdas = el área mínima exacta, 115 m,
    comunicada), E1 y E2 (25 celdas cada una a 120 m, **juntas solo por una esquina**: dos tramos con 4-conexión) y F (24 celdas, la mitad a 130 m y la mitad a 132 m: cota media 131 m)."""
    found = levels_of(((2.0, 5.0, 12.0, 15.0), 135.0), ((40.0, 5.0, 55.0, 15.0), 125.0), ((14.0, 30.0, 17.0, 33.0), 135.0), ((20.0, 25.0, 24.0, 30.0), 115.0),
                      ((40.0, 25.0, 45.0, 30.0), 120.0), ((45.0, 30.0, 50.0, 35.0), 120.0), ((2.0, 20.0, 8.0, 24.0), 130.0))
    found[rd.in_box((5.0, 20.0, 8.0, 24.0), GRID)] = 132.0
    return found


def case(*, berms: Any = None, platforms: Any = (), zones: Any = (), surface: np.ndarray | None = None, final: np.ndarray | None = None, wall: bool = True,
         entries: Any = (ENTRY,), access: Any = WALK) -> Any:
    """El ``AccessJob`` de los casos: el plano que baja al este, la franja intocable (si ``wall``) y lo que se dé."""
    untouchable = rd.in_box(WALL, GRID) if wall else None
    grids = (road_model.BermGrid("bancos", bank_levels()),) if berms is None else berms
    return rd.access_job(GRID, east_down() if surface is None else surface, entries, untouchable=untouchable, access=access, final=final, berms=grids, platforms=platforms, zones=zones)


class BermStretchTest(unittest.TestCase):
    def test_a_berm_stretch_is_a_4_connected_component_with_level_area_place_and_whether_it_is_reached(self) -> None:
        """RF-017-25: de cada tramo de berma (componente 4-conexa de las celdas con cota de berma, con al menos el área mínima) se dice si queda comunicado (alguna de sus celdas es
        alcanzable: lo de la inundación a mano desde la entrada), su cota real (la media de las de sus celdas), su área (m²) y su lugar (el centroide de sus celdas), a ≤ 10⁻⁹; los
        tramos van numerados de 1 en 1 en el orden de su primera celda desde el norte; y los **menores que el área mínima no se listan** (C) y el que tiene **exactamente** el área
        mínima, sí (D)."""
        job = case()
        found = road_access.access(job)
        expected = stretches_by_hand(bank_levels(), GRID, MIN_AREA_M2)
        reach = rd.oracle_reachable(~rd.in_box(WALL, GRID), [rd.cell_of(ENTRY, GRID)])
        np.testing.assert_array_equal(found.reachable, reach)
        self.assertEqual(len(expected), 6, "E2, D, E1, F, A y B: C (9 m²) no se lista")
        self.assertEqual([item["level"] for item in expected], [120.0, 115.0, 120.0, 131.0, 135.0, 125.0])
        self.assertEqual([item["area"] for item in expected], [25.0, 20.0, 25.0, 24.0, 100.0, 150.0])
        self.assertEqual([stretch.connected for stretch in found.berms], [False, True, False, True, True, False])
        self.assertEqual(len(found.berms), len(expected))
        for number, (stretch, hand) in enumerate(zip(found.berms, expected, strict=True), start=1):
            with self.subTest(number=number):
                self.assertEqual(stretch.number, number)
                self.assertAlmostEqual(stretch.level_m, hand["level"], delta=TOL)
                self.assertAlmostEqual(stretch.area_m2, hand["area"], delta=TOL)
                self.assertAlmostEqual(stretch.x, hand["x"], delta=TOL)
                self.assertAlmostEqual(stretch.y, hand["y"], delta=TOL)
                self.assertEqual(stretch.connected, any(bool(reach[r, c]) for r, c in hand["cells"]))
                self.assertEqual(stretch.source, "bancos")
        self.assertTrue(all(isinstance(stretch, road_model.BermReach) for stretch in found.berms))

    def test_two_blocks_that_touch_at_a_corner_are_two_stretches_not_one(self) -> None:
        """RF-017-25 (tramo = componente **4-conexa**): E1 y E2 (25 celdas cada una, juntas solo por una esquina) son dos tramos de 25 m², no uno de 50 m²; y con un área mínima de
        40 m² ninguno se lista."""
        two = [stretch for stretch in road_access.access(case()).berms if abs(stretch.level_m - 120.0) < TOL]
        self.assertEqual([stretch.area_m2 for stretch in two], [25.0, 25.0])
        big = rd.AccessData(WALK.walk_slope_pct, WALK.walk_width_m, 40.0)
        listed = road_access.access(case(access=big)).berms
        self.assertEqual([stretch.area_m2 for stretch in listed], [100.0, 150.0], "solo A y B pasan de 40 m²")
        none = road_access.access(case(access=rd.AccessData(WALK.walk_slope_pct, WALK.walk_width_m, 151.0))).berms
        self.assertEqual(none, ())

    def test_the_area_uses_the_cell_area_of_the_grid(self) -> None:
        """RF-017-25: el área de un tramo es su número de celdas por el área de celda (celdas de 2 m: 4 m²) y el área mínima se compara en m², no en celdas; el lugar y la distancia a lo
        alcanzable de una zona sin comunicar salen en metros (6 celdas de 2 m, 12 m), no en celdas."""
        grid = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 80.0, 2.0, 2.0, 30, 40)
        levels = np.full(grid.shape, np.nan)
        levels[rd.in_box((4.0, 10.0, 14.0, 20.0), grid)] = 135.0
        levels[rd.in_box((30.0, 10.0, 38.0, 20.0), grid)] = 125.0
        wall = rd.in_box((40.0, 0.0, 44.0, 80.0), grid)
        zone = road_model.AccessCells("zona", "Zona", np.flatnonzero(rd.in_box((50.0, 20.0, 58.0, 30.0), grid).ravel()))
        surface = np.full(grid.shape, 100.0)
        job = rd.access_job(grid, surface, [(5.0, 5.0)], untouchable=wall, access=rd.AccessData(10.0, 2.0, 100.0), berms=[road_model.BermGrid("bancos", levels)], zones=[zone])
        found = road_access.access(job)
        hand = stretches_by_hand(levels, grid, 100.0)
        self.assertEqual([item["area"] for item in hand], [100.0], "5 × 5 celdas de 4 m² = 100 m² se lista; 4 × 5 celdas = 80 m² no")
        self.assertEqual([(stretch.level_m, stretch.area_m2, stretch.connected) for stretch in found.berms], [(135.0, 100.0, True)])
        self.assertAlmostEqual(found.berms[0].x, hand[0]["x"], delta=TOL)
        self.assertAlmostEqual(found.berms[0].y, hand[0]["y"], delta=TOL)
        reach = rd.oracle_reachable(~wall, [rd.cell_of((5.0, 5.0), grid)])
        np.testing.assert_array_equal(found.reachable, reach)
        item, by_hand = found.zones[0], zone_by_hand(zone.cells, reach, surface, grid)
        self.assertFalse(item.connected)
        self.assertAlmostEqual(item.distance_m, 12.0, delta=TOL)
        self.assertAlmostEqual(item.distance_m, by_hand["distance"], delta=TOL)
        self.assertAlmostEqual(item.x, by_hand["x"], delta=TOL)
        self.assertAlmostEqual(item.y, by_hand["y"], delta=TOL)
        self.assertAlmostEqual(item.level_difference_m, 0.0, delta=TOL)

    def test_a_stretch_with_a_single_reachable_cell_is_reached(self) -> None:
        """RF-017-25 (comunicado si **alguna** de sus celdas es alcanzable): un tramo de 11 celdas en fila que cruza la franja intocable y solo tiene la del oeste alcanzable (x = 29,5 m)
        queda comunicado; y su cota es la de sus celdas."""
        levels = levels_of(((29.0, 37.0, 40.0, 38.0), 128.0))
        found = road_access.access(case(berms=(road_model.BermGrid("cruza", levels),), access=rd.AccessData(WALK.walk_slope_pct, WALK.walk_width_m, 5.0)))
        reach = rd.oracle_reachable(~rd.in_box(WALL, GRID), [rd.cell_of(ENTRY, GRID)])
        hand = stretches_by_hand(levels, GRID, 5.0)
        self.assertEqual(sum(bool(reach[r, c]) for r, c in hand[0]["cells"]), 1, "una sola celda alcanzable")
        self.assertEqual([(stretch.level_m, stretch.area_m2, stretch.connected) for stretch in found.berms], [(128.0, 11.0, True)])

    def test_several_berm_data_are_numbered_in_a_row_and_keep_their_source(self) -> None:
        """RF-017-25: con más de un dato de bermas (la accesibilidad admite varios), cada uno se lee por separado en el orden dado, los tramos se numeran seguidos y cada uno lleva el
        nombre de su dato (``source``); un dato sin ninguna celda de berma no aporta ninguno."""
        alpha = levels_of(((2.0, 5.0, 12.0, 15.0), 135.0), ((40.0, 5.0, 55.0, 15.0), 125.0))
        beta = levels_of(((2.0, 5.0, 12.0, 15.0), 136.0))
        empty = np.full(GRID.shape, np.nan)
        job = case(berms=(road_model.BermGrid("alfa", alpha), road_model.BermGrid("vacio", empty), road_model.BermGrid("beta", beta)))
        found = road_access.access(job)
        self.assertEqual([(s.number, s.source, s.level_m, s.connected) for s in found.berms], [(1, "alfa", 135.0, True), (2, "alfa", 125.0, False), (3, "beta", 136.0, True)])

    def test_without_berm_data_there_are_no_stretches(self) -> None:
        """RF-017-25: una accesibilidad sin datos de bermas lista ninguno (A10 sola, como antes de T16)."""
        found = road_access.access(case(berms=()))
        self.assertEqual((found.berms, found.platforms, found.zones), ((), (), ()))

    def test_berm_reach_carries_an_optional_source(self) -> None:
        """RF-017-25 (``BermReach.source``, T16: el nombre del dato de bermas de que sale el tramo): es opcional (``None``), se valida y la clase sigue igual si no se da."""
        plain = road_model.BermReach(1, 135.0, 100.0, True, 10.0, 20.0)
        self.assertIsNone(plain.source)
        self.assertEqual(road_model.BermReach(1, 135.0, 100.0, True, 10.0, 20.0, "bancos").source, "bancos")
        with self.assertRaises(TypeError):
            road_model.BermReach(1, 135.0, 100.0, True, 10.0, 20.0, 5)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            road_model.BermReach(1, 135.0, 100.0, True, 10.0, 20.0, "  ")


class PlatformTest(unittest.TestCase):
    def test_a_platform_is_reached_at_the_lowest_level_of_its_reachable_cells(self) -> None:
        """RF-017-25: de cada plataforma se dice si queda comunicada (alguna celda alcanzable en su huella) y a qué cota: **la menor de las celdas alcanzables** de su huella, no la
        menor de la huella (la de la que cruza la franja baja hacia el este: las celdas del otro lado, más bajas, no cuentan); una del otro lado no se comunica y su cota es ``None``; una
        sin celdas, tampoco."""
        surface = east_down()
        boxes = {"P1": (3.0, 2.0, 9.0, 4.0), "P2": (25.0, 10.0, 38.0, 12.0), "P3": (45.0, 20.0, 55.0, 25.0), "P4": (3.2, 2.2, 3.4, 2.4)}
        platforms = [road_model.AccessCells(code, f"Plataforma {code}", flat_cells(box)) for code, box in zip(("PLT-001", "PLT-002", "PLT-003", "PLT-004"), boxes.values(), strict=True)]
        self.assertEqual(platforms[3].cells.size, 0, "P4 no tiene ninguna celda")
        found = road_access.access(case(platforms=platforms, surface=surface))
        reach = rd.oracle_reachable(~rd.in_box(WALL, GRID), [rd.cell_of(ENTRY, GRID)])
        self.assertEqual([item.code for item in found.platforms], ["PLT-001", "PLT-002", "PLT-003", "PLT-004"])
        for item, platform in zip(found.platforms, platforms, strict=True):
            with self.subTest(code=item.code):
                cells = [divmod(int(index), COLS) for index in platform.cells]
                reached = [float(surface[r, c]) for r, c in cells if reach[r, c]]
                self.assertEqual(item.connected, bool(reached))
                if reached:
                    self.assertAlmostEqual(item.level_m, min(reached), delta=TOL)
                else:
                    self.assertIsNone(item.level_m)
        self.assertEqual([item.connected for item in found.platforms], [True, True, False, False])
        p2 = [float(surface[r, c]) for r, c in (divmod(int(index), COLS) for index in platforms[1].cells)]
        self.assertLess(min(p2), found.platforms[1].level_m, "la menor de la huella (en el este) no es la de lo alcanzable")
        self.assertAlmostEqual(found.platforms[1].level_m, 100.0 + 0.05 * (60.0 - 29.5), delta=TOL)


class ZoneTest(unittest.TestCase):
    def test_a_zone_is_reached_or_listed_with_its_place_distance_and_level_difference(self) -> None:
        """RF-017-25: de cada zona «requiere acceso» se dice si queda comunicada (alguna de sus celdas es alcanzable) y, de las que no, su lugar (su celda más próxima a lo alcanzable,
        a igual distancia la de menor índice), la distancia (m, entre centros: exacta) y la diferencia de cota (la de la celda alcanzable más próxima menos la de su celda), a ≤ 10⁻⁹;
        una comunicada no lleva lugar, distancia ni diferencia."""
        surface = east_down()
        zones = [road_model.AccessCells("zona_a", "Zona A", flat_cells((3.0, 25.0, 8.0, 28.0))),
                 road_model.AccessCells("zona_b", "Zona B", flat_cells((40.0, 10.0, 50.0, 20.0))),
                 road_model.AccessCells("zona_c", "Zona C", flat_cells((26.0, 30.0, 40.0, 34.0))),
                 road_model.AccessCells("zona_d", "Zona D", flat_cells((45.0, 30.0, 52.0, 33.0)))]
        found = road_access.access(case(zones=zones, surface=surface))
        reach = rd.oracle_reachable(~rd.in_box(WALL, GRID), [rd.cell_of(ENTRY, GRID)])
        self.assertEqual([item.code for item in found.zones], ["zona_a", "zona_b", "zona_c", "zona_d"])
        self.assertEqual([item.connected for item in found.zones], [True, False, True, False])
        for item, zone in zip(found.zones, zones, strict=True):
            with self.subTest(code=item.code):
                hand = zone_by_hand(zone.cells, reach, surface, GRID)
                self.assertEqual(item.connected, hand["connected"])
                if hand["connected"]:
                    self.assertEqual((item.x, item.y, item.distance_m, item.level_difference_m), (None, None, None, None))
                else:
                    self.assertAlmostEqual(item.x, hand["x"], delta=TOL)
                    self.assertAlmostEqual(item.y, hand["y"], delta=TOL)
                    self.assertAlmostEqual(item.distance_m, hand["distance"], delta=TOL)
                    self.assertAlmostEqual(item.level_difference_m, hand["difference"], delta=TOL)
        b = found.zones[1]
        self.assertAlmostEqual(b.distance_m, 11.0, delta=TOL, msg="de x = 40,5 a la última celda alcanzable (x = 29,5)")
        self.assertAlmostEqual(b.level_difference_m, (100.0 + 0.05 * (60.0 - 29.5)) - (100.0 + 0.05 * (60.0 - 40.5)), delta=TOL)

    def test_at_equal_distance_the_lowest_reachable_level_is_taken(self) -> None:
        """RF-017-25: si dos celdas alcanzables están a la misma distancia de la zona, la diferencia de cota es con la de **menor cota** (3 m al oeste a 100 m y 3 m al este a 104 m,
        con la zona a 102 m: −2 m, no +2 m), como el más próximo de ``grids.nearest_value_steps``."""
        grid = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 3.0, 1.0, 1.0, 9, 3)
        surface = np.full(grid.shape, 102.0)
        surface[:, 1] = 100.0
        surface[:, 7] = 104.0
        untouchable = np.ones(grid.shape, dtype=bool)
        untouchable[:, 1] = False
        untouchable[:, 7] = False
        zone = road_model.AccessCells("zona", "Zona", np.array([1 * 9 + 4]))
        job = rd.access_job(grid, surface, [(1.5, 1.5), (7.5, 1.5)], untouchable=untouchable, access=rd.AccessData(1000.0, 1.0, 0.0), zones=[zone])
        found = road_access.access(job)
        self.assertEqual(int(found.reachable.sum()), 6, "las dos columnas")
        item = found.zones[0]
        self.assertFalse(item.connected)
        self.assertEqual((item.distance_m, item.level_difference_m), (3.0, -2.0))
        self.assertEqual((item.x, item.y), (grid.west + 4.5, grid.north - 1.5))

    def test_a_zone_with_nothing_reachable_or_without_cells_has_no_distance(self) -> None:
        """RF-017-25: si no se alcanza ninguna celda (la entrada cae en lo intocable), la zona no queda comunicada, su lugar es su primera celda y no tiene distancia ni diferencia
        (nada de dónde medir); una zona sin ninguna celda tampoco las tiene ni lugar."""
        zones = [road_model.AccessCells("zona_a", "Zona A", flat_cells((3.0, 25.0, 8.0, 28.0))), road_model.AccessCells("zona_v", "Vacía", np.array([], dtype=np.int64))]
        job = rd.access_job(GRID, east_down(), [ENTRY], untouchable=np.ones(GRID.shape, dtype=bool), access=WALK, zones=zones)
        found = road_access.access(job)
        self.assertFalse(found.reachable.any())
        self.assertIsNone(found.z_min_m)
        first = divmod(int(zones[0].cells.min()), COLS)
        self.assertEqual([(item.connected, item.distance_m, item.level_difference_m) for item in found.zones], [(False, None, None), (False, None, None)])
        self.assertAlmostEqual(found.zones[0].x, GRID.west + first[1] + 0.5, delta=TOL)
        self.assertAlmostEqual(found.zones[0].y, GRID.north - first[0] - 0.5, delta=TOL)
        self.assertEqual((found.zones[1].x, found.zones[1].y), (None, None))

    def test_the_zones_of_the_masks_runs_give_the_same_result_as_their_cells(self) -> None:
        """RF-017-25 (las zonas son los tramos de fila ``Runs`` de la compilación de las máscaras): la celdas de unos ``Runs`` (``np.flatnonzero(runs.mask(forma))``: el paso de la
        preparación, T17) dan el mismo resultado que las de la máscara de la que salen."""
        mask = rd.in_box((40.0, 10.0, 50.0, 20.0), GRID)
        runs = zones_module.Runs.from_mask(mask)
        from_runs = road_model.AccessCells("zona_b", "Zona B", np.flatnonzero(runs.mask(GRID.shape).ravel()))
        from_mask = road_model.AccessCells("zona_b", "Zona B", np.flatnonzero(mask.ravel()))
        np.testing.assert_array_equal(from_runs.cells, from_mask.cells)
        a = road_access.access(case(zones=[from_runs])).zones
        b = road_access.access(case(zones=[from_mask])).zones
        self.assertEqual(a, b)


class FinalSurfaceTest(unittest.TestCase):
    @staticmethod
    def rising() -> np.ndarray:
        """El plano que sube al este: ``z = 100 + 0,05 · x``; su cota mínima alcanzable (en x = 0,5 m) es 100,025 m."""
        x, _y = rd.local_centers(GRID)
        return 100.0 + 0.05 * x

    def test_the_lowest_reachable_level_is_given_over_the_final_surface_too(self) -> None:
        """RF-017-24 (error 23): en una cantera con dos superficies, la cota mínima alcanzable sobre la **final** con los mismos parámetros, junto a la de la explotación: sobre el plano
        que sube al este (100,025 m) y la final con el fondo relleno a 110 m, 100,025 y 110 m, a ≤ 10⁻⁹; el resto de lo alcanzable (cotas máxima, área, rejilla) es el de la explotación."""
        surface = self.rising()
        final = np.maximum(surface, 110.0)
        found = road_access.access(case(surface=surface, final=final, wall=False, berms=()))
        self.assertAlmostEqual(found.z_min_m, 100.025, delta=TOL)
        self.assertAlmostEqual(found.z_min_final_m, 110.0, delta=TOL)
        alone = road_access.access(case(surface=surface, wall=False, berms=()))
        self.assertIsNone(alone.z_min_final_m, "sin cantera de dos superficies, no hay cota sobre la final")
        np.testing.assert_array_equal(found.reachable, alone.reachable)
        self.assertEqual((found.z_min_m, found.z_max_m, found.area_m2), (alone.z_min_m, alone.z_max_m, alone.area_m2))

    def test_the_final_surface_uses_the_same_parameters_and_the_same_untouchable_areas(self) -> None:
        """RF-017-24: sobre la final rigen la misma pendiente máxima, el mismo ancho mínimo y la misma máscara de lo intocable: con la franja, la parte del este no se alcanza y la cota
        mínima sobre la final es la de la parte del oeste (110 m); sin la franja se alcanza el este, más bajo (108,725 m); y con la entrada cercada por un escarpe (pendiente de 10.000 %)
        sobre la final, no se alcanza nada y la cota es ``None``, mientras la de la explotación sigue dándose."""
        x, _y = rd.local_centers(GRID)
        final = np.where(x < 34.0, 110.0, 110.0 - 0.05 * (x - 34.0))
        walled = road_access.access(case(surface=self.rising(), final=final, wall=True, berms=()))
        self.assertAlmostEqual(walled.z_min_final_m, 110.0, delta=TOL)
        open_final = road_access.access(case(surface=self.rising(), final=final, wall=False, berms=()))
        self.assertAlmostEqual(open_final.z_min_final_m, 110.0 - 0.05 * (59.5 - 34.0), delta=TOL)
        fenced = final.copy()
        row, col = rd.cell_of(ENTRY, GRID)
        fenced[row - 1:row + 2, col - 1:col + 2] += 100.0
        fenced[row, col] = 110.0
        cliff = road_access.access(case(surface=self.rising(), final=fenced, wall=False, berms=()))
        self.assertIsNone(cliff.z_min_final_m)
        self.assertAlmostEqual(cliff.z_min_m, 100.025, delta=TOL)


class UntouchedTest(unittest.TestCase):
    def test_no_surface_or_restriction_changes_and_the_results_are_read_only(self) -> None:
        """RF-017-25, principio 7: ninguna superficie ni restricción cambia (el resumen de la superficie, de la final, de lo intocable, de las cotas de berma y de las celdas de las
        plataformas y las zonas, antes y después de calcular entero y de cerrar a mitad); una pasada después da el mismo resultado y lo que entrega no comparte memoria con la entrada."""
        surface = east_down()
        platforms = [road_model.AccessCells("PLT-001", "P1", flat_cells((3.0, 2.0, 9.0, 4.0)))]
        zones = [road_model.AccessCells("zona_b", "Zona B", flat_cells((40.0, 10.0, 50.0, 20.0)))]
        job = case(surface=surface, final=surface + 1.0, platforms=platforms, zones=zones)
        arrays = (job.surface, job.final, job.untouchable, job.berms[0].levels, job.platforms[0].cells, job.zones[0].cells)
        keep = digest(*arrays)
        before = road_access.access(job)
        steps = road_access.access_steps(job, budget_s=0.0)
        for _ in range(4):
            next(steps)
        steps.close()
        self.assertEqual(digest(*arrays), keep)
        again = road_access.access(job)
        self.assertEqual((again.berms, again.platforms, again.zones, again.z_min_final_m), (before.berms, before.platforms, before.zones, before.z_min_final_m))
        self.assertEqual(digest(*arrays), keep)
        for array in arrays:
            self.assertFalse(array.flags.writeable)
        self.assertFalse(np.shares_memory(before.reachable, job.surface))
        self.assertEqual((before.figures, before.notices), ((), ()), "las cifras y los avisos los compone la operación (T17)")


class StepsTest(unittest.TestCase):
    @staticmethod
    def big() -> Any:
        rng = np.random.default_rng(16)
        grid = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 200.0, 1.0, 1.0, 200, 200)
        x, y = rd.local_centers(grid)
        surface = 100.0 + 2.0 * np.sin(x / 15.0) + 2.0 * np.cos(y / 11.0) + rng.normal(0.0, 0.02, grid.shape)
        boxes = [(10.0 + 30.0 * i, 10.0 + 30.0 * j, 30.0 + 30.0 * i, 20.0 + 30.0 * j) for i in range(6) for j in range(6)]
        levels = np.full(grid.shape, np.nan)
        for index, box in enumerate(boxes):
            levels[rd.in_box(box, grid)] = 100.0 + index
        platforms = [road_model.AccessCells(f"PLT-{n:03d}", f"P{n}", np.flatnonzero(rd.in_box(boxes[n], grid).ravel())) for n in (0, 7, 14, 21)]
        zones = [road_model.AccessCells(f"z{n}", f"Z{n}", np.flatnonzero(rd.in_box(boxes[n], grid).ravel())) for n in (3, 10, 17, 24)]
        job = rd.access_job(grid, surface, [(5.5, 5.5)], untouchable=rd.in_box((90.0, 0.0, 95.0, 200.0), grid), access=rd.AccessData(30.0, 5.0, 100.0), final=surface + 0.5,
                            berms=[road_model.BermGrid("bancos", levels)], platforms=platforms, zones=zones)
        return grid, job

    def test_the_steps_end_in_the_same_lists_as_one_go_and_each_call_is_short(self) -> None:
        """RF-017-25, RNF-017-05: por pasos, las bermas, las plataformas, las zonas y la cota sobre la final son las mismas que de una vez, hay varios pasos, cada llamada del paso
        tarda ≤ 0,2 s (también la de la búsqueda del más próximo y la de las componentes de las bermas) y todos llevan su fase."""
        grid, job = self.big()
        whole = road_access.access(job)
        steps = road_access.access_steps(job, budget_s=0.0)
        longest, count, last = 0.0, 0, None
        while True:
            before = time.perf_counter()
            try:
                step = next(steps)
            except StopIteration:
                break
            longest = max(longest, time.perf_counter() - before)
            count += 1
            last = step
            self.assertEqual(step.phase, "road_access")
        self.assertGreater(count, 10)
        self.assertLessEqual(longest, 0.2)
        found = last.result
        self.assertEqual((found.berms, found.platforms, found.zones, found.z_min_final_m), (whole.berms, whole.platforms, whole.zones, whole.z_min_final_m))
        np.testing.assert_array_equal(found.reachable, whole.reachable)
        self.assertEqual(len(whole.berms), 36)
        self.assertTrue(any(item.connected for item in whole.berms) and not all(item.connected for item in whole.berms), "un caso con unos tramos comunicados y otros no")
        self.assertEqual(len(whole.platforms), 4)
        self.assertEqual(len(whole.zones), 4)
        self.assertIsNotNone(whole.z_min_final_m)
        self.assertEqual(grid.shape, whole.reachable.shape)

    def test_the_lists_are_the_ones_by_hand(self) -> None:
        """RF-017-25: en el caso grande (36 tramos, 4 plataformas y 4 zonas, con una franja intocable que parte la rejilla y la entrada al oeste), cada lista es la del cálculo a mano: los tramos con su cota, su área, su lugar y si están comunicados
        (inundación a mano), las plataformas con la menor cota de sus celdas alcanzables y las zonas no comunicadas con su distancia y diferencia de cota."""
        grid, job = self.big()
        found = road_access.access(job)
        expected = stretches_by_hand(job.berms[0].levels, grid, 100.0)
        reach = found.reachable
        self.assertEqual(len(found.berms), len(expected))
        for stretch, hand in zip(found.berms, expected, strict=True):
            self.assertAlmostEqual(stretch.level_m, hand["level"], delta=TOL)
            self.assertAlmostEqual(stretch.area_m2, hand["area"], delta=TOL)
            self.assertAlmostEqual(stretch.x, hand["x"], delta=TOL)
            self.assertAlmostEqual(stretch.y, hand["y"], delta=TOL)
            self.assertEqual(stretch.connected, any(bool(reach[r, c]) for r, c in hand["cells"]))
        for item, platform in zip(found.platforms, job.platforms, strict=True):
            levels = [float(job.surface[divmod(int(i), grid.ncols)]) for i in platform.cells if reach.ravel()[int(i)]]
            self.assertEqual(item.connected, bool(levels))
            self.assertEqual(item.level_m, min(levels) if levels else None)
        for item, zone in zip(found.zones, job.zones, strict=True):
            hand = zone_by_hand(zone.cells, reach, job.surface, grid)
            self.assertEqual(item.connected, hand["connected"])
            if not hand["connected"]:
                self.assertAlmostEqual(item.distance_m, hand["distance"], delta=TOL)
                self.assertAlmostEqual(item.level_difference_m, hand["difference"], delta=TOL)
                self.assertAlmostEqual(item.x, hand["x"], delta=TOL)
                self.assertAlmostEqual(item.y, hand["y"], delta=TOL)
        self.assertTrue(any(not item.connected for item in found.zones), "al menos una zona sin comunicar, para medir la distancia")


if __name__ == "__main__":
    unittest.main()
