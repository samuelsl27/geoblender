# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo alcanzable y las cotas de la accesibilidad (spec 017, T15; HU-017-3; RF-017-24 y 04; RNF-017-05 y 06; plan 017 §5.4 A10, D-17 y T15-a): ``road_access.access`` da la
pendiente local de cada celda (la mayor tangente a sus ocho vecinas), las celdas **transitables** (pendiente ≤ la máxima transitable, con dato y fuera de lo intocable), el
**ancho mínimo** como una apertura con un disco exacto de radio ``ancho / 2``, las componentes 4-conexas con un punto de entrada (**lo alcanzable**), las cotas mínima y máxima
alcanzables y el área alcanzable; rechaza una capa sin puntos de entrada o con uno sin dato nombrando la capa, el punto y su lugar; y **no cambia ninguna superficie ni restricción**.

Los valores esperados salen **a mano** y por **fuerza bruta** (la pendiente con un bucle por celda y vecina, la apertura con el ``y``/``o`` de la máscara desplazada del disco
—``tests.support.road_data.oracle_disc_opening``— y la inundación 4-conexa con una cola —``oracle_reachable``—), **no** de llamar al código bajo prueba. Todo es sintético y sin
Blender, sobre rejillas de ≤ 200 × 200 celdas; la medida a escala (2,81 M celdas, RNF-017-05 y 06) es de ``milestone_road_access``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import time
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import road_data as rd
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
report = import_geoblender("design.report")
road_access = import_geoblender("design.road_access")

ROWS, COLS = 40, 60
GRID = gis.Grid(cfx.BASE[0], cfx.BASE[1] + float(ROWS), 1.0, 1.0, COLS, ROWS)
"""La rejilla de las pruebas: 60 × 40 celdas de 1 m (la esquina suroeste en ``BASE``), con las coordenadas locales de ``rd.local_centers``."""
TOL = 1e-9
"""La tolerancia de las cuentas a mano (RF-017-24: ≤ 10⁻⁹ m)."""
FLAT = np.full((ROWS, COLS), 100.0)
"""Un terreno llano a 100 m."""


def ramp(percent: float, grid: Any = GRID) -> np.ndarray:
    """Un plano que sube al este con una pendiente de ``percent`` % (``z = pendiente · x`` local)."""
    x, _y = rd.local_centers(grid)
    return percent / 100.0 * x


def steps_of(surface: np.ndarray, *, walk_pct: float, width_m: float, entries: list[tuple[float, float]], untouchable: np.ndarray | None = None, grid: Any = GRID) -> Any:
    """El ``AccessJob`` de la prueba (sin bermas, plataformas ni zonas) con los umbrales dados."""
    return rd.access_job(grid, surface, entries, untouchable=untouchable, access=rd.AccessData(walk_pct, width_m, 0.0))


def brute_slope_pct(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """La pendiente local (%) **a mano**: por celda con dato, la mayor tangente a sus (hasta) ocho vecinas con dato (``|Δz| / distancia``, la diagonal a ``hypot``); ``nan`` si la celda
    no tiene dato o ninguna vecina lo tiene."""
    rows, columns = z.shape
    found = np.full(z.shape, np.nan)
    for i in range(rows):
        for j in range(columns):
            if not math.isfinite(float(z[i, j])):
                continue
            best: float | None = None
            for d_row in (-1, 0, 1):
                for d_col in (-1, 0, 1):
                    near_row, near_col = i + d_row, j + d_col
                    if (d_row, d_col) == (0, 0) or not (0 <= near_row < rows and 0 <= near_col < columns) or not math.isfinite(float(z[near_row, near_col])):
                        continue
                    tangent = abs(float(z[i, j]) - float(z[near_row, near_col])) / math.hypot(d_col * dx, d_row * dy)
                    best = tangent if best is None else max(best, tangent)
            if best is not None:
                found[i, j] = best * 100.0
    return found


def expected_reachable(z: np.ndarray, grid: Any, walk_pct: float, width_m: float, seeds: list[tuple[int, int]], untouchable: np.ndarray | None = None) -> np.ndarray:
    """Lo alcanzable **a mano**: las celdas con dato, de pendiente ≤ la transitable y no intocables, abiertas con el disco exacto del ancho mínimo y 4-conexas con alguna
    entrada que quede en ellas."""
    with np.errstate(invalid="ignore"):
        walkable = np.isfinite(z) & (brute_slope_pct(z, grid.dx, grid.dy) <= walk_pct)
    if untouchable is not None:
        walkable &= ~untouchable
    return rd.oracle_reachable(rd.oracle_disc_opening(walkable, width_m / 2.0, grid.dx), seeds)


def digest(*arrays: np.ndarray) -> str:
    """El resumen de unos arrays (para comprobar que no cambian)."""
    return hashlib.sha256(b"".join(np.ascontiguousarray(array).tobytes() for array in arrays)).hexdigest()


class PromotedTest(unittest.TestCase):
    def test_the_tangent_helpers_of_the_report_are_public_and_give_the_hand_values(self) -> None:
        """RF-017-24 (la pendiente local es la de ``report``, que la plataforma y la pista ya usan): ``max_tangents`` y ``padded_rows`` son públicas (se promueven sin alias
        privado, como hizo la T05 de la 015: ``_max_tangents`` y ``_padded``) y dan lo mismo que el cálculo a mano de una malla de 3 × 3."""
        self.assertTrue(hasattr(report, "max_tangents") and hasattr(report, "padded_rows"))
        self.assertFalse(hasattr(report, "_max_tangents") or hasattr(report, "_padded"), "sin alias privados")
        self.assertIn("max_tangents", report.__all__)
        self.assertIn("padded_rows", report.__all__)
        z = np.array([[0.0, 1.0, 2.0], [0.0, 0.0, 4.0], [0.0, 0.0, 0.0]])
        found = report.max_tangents(report.padded_rows(z, 0, 3), 1.0, 1.0)
        self.assertEqual(found.shape, (5, 5))
        self.assertTrue(np.isnan(found[0]).all() and np.isnan(found[-1]).all() and np.isnan(found[:, 0]).all() and np.isnan(found[:, -1]).all(), "la vuelta de NaN no tiene pendiente")
        self.assertEqual(float(found[2, 2]), 4.0, "el centro: la mayor de las ocho, 4 m en 1 m hacia el este")
        self.assertEqual(float(found[1, 1]), 1.0, "la esquina noroeste: 1 m hacia el este")
        self.assertEqual(float(found[1, 3]), 2.0, "la esquina noreste (2 m): su vecina del sur está a 4 m, 2 m de diferencia")
        banded = report.max_tangents(report.padded_rows(z, 1, 3), 1.0, 1.0)
        self.assertEqual(banded.shape, (4, 5))
        self.assertEqual(float(banded[1, 2]), 4.0, "una banda con sus filas vecinas da lo mismo que toda la malla")


class SlopeTest(unittest.TestCase):
    def test_the_local_slope_is_the_largest_tangent_to_the_eight_neighbours(self) -> None:
        """RF-017-24: la pendiente local (%) de cada celda es la mayor tangente a sus ocho vecinas con dato (la diagonal, a ``hypot``), con celdas no cuadradas, huecos sin dato y
        el borde de la rejilla (una vecina fuera no cuenta) igual a la fuerza bruta; una celda sin dato o sin ninguna vecina con dato no tiene pendiente (``nan``); y por bandas
        de cualquier número de filas, igual bit a bit que de una vez."""
        rng = np.random.default_rng(20261121)
        grid = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 75.0, 2.0, 3.0, 31, 25)
        z = 50.0 + 6.0 * np.sin(np.arange(31) / 4.0)[None, :] + 4.0 * np.cos(np.arange(25) / 3.0)[:, None] + rng.normal(0.0, 0.3, (25, 31))
        z[rng.random(z.shape) < 0.08] = np.nan
        z[10:13, 10:13] = np.nan
        z[11, 11] = 77.0
        expected = brute_slope_pct(z, 2.0, 3.0)
        self.assertTrue(np.isnan(expected[11, 11]), "la celda con dato rodeada de huecos no tiene pendiente")
        self.assertGreater(int(np.isnan(expected).sum()), 5)
        whole = road_access.local_slope_pct(z, grid)
        np.testing.assert_allclose(whole, expected, rtol=1e-12, atol=0.0, equal_nan=True)
        for rows in (1, 2, 7, 25, 100):
            with self.subTest(band_rows=rows):
                np.testing.assert_array_equal(road_access.local_slope_pct(z, grid, band_rows=rows), whole)

    def test_the_slope_of_a_plane_is_its_gradient(self) -> None:
        """RF-017-24: el plano del 12,5 % hacia el este da 12,5 % en todas las celdas (a ≤ 10⁻⁹ %: las diagonales dan menos) y el de 10 % al este y al norte da el de la diagonal
        (0,2 m en √2 m: 14,142 %), la mayor de las ocho."""
        z = ramp(12.5)
        np.testing.assert_allclose(road_access.local_slope_pct(z, GRID), 12.5, atol=TOL)
        x, y = rd.local_centers(GRID)
        tilted = 0.10 * x + 0.10 * y
        found = road_access.local_slope_pct(tilted, GRID)
        np.testing.assert_allclose(found[1:-1, 1:-1], 20.0 / math.sqrt(2.0), atol=TOL, err_msg="la diagonal: 0,2 m en √2 m = 14,142 %, mayor que la de los lados (10 %)")
        self.assertAlmostEqual(float(found[0, 0]), 10.0, delta=TOL, msg="en las esquinas noroeste y sureste solo está la diagonal sin desnivel: manda el 10 % de los lados")
        self.assertAlmostEqual(float(found[-1, -1]), 10.0, delta=TOL)

    def test_the_slope_rejects_a_surface_that_is_not_the_grid(self) -> None:
        """RF-017-24: una superficie que no es de la forma de la rejilla es un error del programa (``ValueError``)."""
        with self.assertRaises(ValueError):
            road_access.local_slope_pct(FLAT[:-1], GRID)
        with self.assertRaises(ValueError):
            road_access.local_slope_pct(FLAT, GRID, band_rows=0)


class ThresholdTest(unittest.TestCase):
    def test_a_slope_just_at_the_threshold_is_walkable_and_one_billionth_of_a_percent_more_is_not(self) -> None:
        """RF-017-24, D-17: «pendiente ≤ la transitable»: una rampa **justa** (7, 12,5, 16 y 30 %: ``0,07 · 100`` sale 7,000000000000001 en coma flotante y no la rechaza) se
        alcanza entera desde una entrada y una con 10⁻⁹ % **de más** no se alcanza (la entrada no está en una celda transitable)."""
        for percent in (3.0, 7.0, 12.5, 16.0, 30.0):
            for entry in ((30.5, 20.5), (0.5, 0.5), (59.5, 39.5)):
                with self.subTest(percent=percent, entry=entry):
                    exact = road_access.access(steps_of(ramp(percent), walk_pct=percent, width_m=1.0, entries=[entry]))
                    self.assertEqual(int(exact.reachable.sum()), ROWS * COLS, "justa: toda la rampa")
                    over = road_access.access(steps_of(ramp(percent + 1e-9), walk_pct=percent, width_m=1.0, entries=[entry]))
                    self.assertFalse(over.reachable.any(), "con 10⁻⁹ % de más no es transitable ninguna celda")
                    self.assertIsNone(over.z_min_m)
                    self.assertIsNone(over.z_max_m)
                    self.assertEqual(over.area_m2, 0.0)

    def test_the_threshold_is_the_largest_tangent_of_the_cell(self) -> None:
        """RF-017-24: una celda queda fuera si **alguna** de sus ocho vecinas pasa de la pendiente transitable: un escalón de 0,2 m en un llano deja fuera sus dos columnas de
        celdas (la que sube y la que baja) con el 15 %, y con el 20 % —que en coma flotante es 20,00000000000028 %— lo alcanza todo."""
        z = FLAT.copy()
        z[:, 30:] += 0.2
        held = road_access.access(steps_of(z, walk_pct=15.0, width_m=1.0, entries=[(5.5, 20.5)]))
        self.assertTrue(held.reachable[:, :29].all())
        self.assertFalse(held.reachable[:, 29:].any(), "el escalón y lo que hay más allá no se alcanzan")
        passed = road_access.access(steps_of(z, walk_pct=20.0, width_m=1.0, entries=[(5.5, 20.5)]))
        self.assertTrue(passed.reachable.all())


class WidthTest(unittest.TestCase):
    @staticmethod
    def rooms(corridor_rows: int) -> np.ndarray:
        """Dos salas de 15 × 15 celdas unidas por un pasillo de ``corridor_rows`` filas, como lo transitable (el resto, intocable)."""
        free = np.zeros((ROWS, COLS), dtype=bool)
        free[10:25, 4:19] = True
        free[10:25, 40:55] = True
        middle = 17
        free[middle - corridor_rows // 2:middle - corridor_rows // 2 + corridor_rows, 19:40] = True
        return free

    def test_the_opening_removes_a_passage_narrower_than_the_minimum_width(self) -> None:
        """RF-017-24, D-17: el ancho mínimo transitable es una apertura con un disco exacto de radio ``ancho / 2``: un pasillo de 3 filas no deja pasar un disco de 4 m de
        diámetro (5 celdas de lado a lado) y uno de 5 filas sí; igual a la fuerza bruta (el disco como ``y``/``o`` de la máscara desplazada) con anchos de 2, 3 y 4 m y pasillos de
        1 a 7 filas."""
        for width_m in (2.0, 3.0, 4.0):
            for rows in range(1, 8):
                with self.subTest(width_m=width_m, corridor_rows=rows):
                    free = self.rooms(rows)
                    found = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=width_m, entries=[(10.5, 22.5)], untouchable=~free))
                    expected = expected_reachable(FLAT, GRID, 10.0, width_m, [rd.cell_of((10.5, 22.5), GRID)], untouchable=~free)
                    np.testing.assert_array_equal(found.reachable, expected)
        narrow = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=4.0, entries=[(10.5, 22.5)], untouchable=~self.rooms(3)))
        wide = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=4.0, entries=[(10.5, 22.5)], untouchable=~self.rooms(5)))
        self.assertFalse(narrow.reachable[:, 40:].any(), "el pasillo de 3 filas no da paso a la otra sala")
        self.assertTrue(wide.reachable[17, 47], "el de 5 filas, sí")
        self.assertTrue(narrow.reachable[:, :19].any())

    def test_the_opening_does_not_widen_what_it_keeps(self) -> None:
        """RF-017-24: la apertura solo quita (``abrir(a) ≤ a``): con una entrada en un llano sin nada que prohíba, lo alcanzable es el llano entero, también junto al borde de la
        rejilla (una celda de fuera no cuenta: la rejilla es todo lo que hay), con el disco de 4 m."""
        found = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=4.0, entries=[(0.5, 0.5)]))
        self.assertTrue(found.reachable.all())


class ReachTest(unittest.TestCase):
    def test_reachable_is_the_flood_fill_of_the_opened_walkable_cells(self) -> None:
        """RF-017-24: sobre un terreno ondulado con huecos sin dato y una mancha de intocable, lo alcanzable es **igual** a la inundación 4-conexa por fuerza bruta (una cola, sin
        numpy) desde las entradas sobre la máscara abierta, con varias pendientes transitables y anchos mínimos; no es nada ni todo."""
        rng = np.random.default_rng(17)
        x, y = rd.local_centers(GRID)
        z = 100.0 + 3.0 * np.sin(x / 6.0) + 2.0 * np.cos(y / 4.0) + rng.normal(0.0, 0.05, GRID.shape)
        smooth = z.copy()
        z[rng.random(z.shape) < 0.01] = np.nan
        untouchable = rd.in_box((20.0, 10.0, 26.0, 30.0), GRID)
        entries = [(10.5, 20.5), (50.5, 12.5)]
        seeds = [rd.cell_of(point, GRID) for point in entries]
        for seed in seeds:
            z[seed] = smooth[seed]  # una entrada sin dato se rechaza (RF-017-04): aquí las dos tienen
        sizes = set()
        for walk in (50.0, 60.0, 70.0):
            for width in (1.0, 2.0, 3.0):
                with self.subTest(walk=walk, width=width):
                    found = road_access.access(steps_of(z, walk_pct=walk, width_m=width, entries=entries, untouchable=untouchable))
                    expected = expected_reachable(z, GRID, walk, width, seeds, untouchable)
                    np.testing.assert_array_equal(found.reachable, expected)
                    sizes.add(int(expected.sum()))
                    self.assertFalse((found.reachable & untouchable).any())
                    self.assertFalse((found.reachable & ~np.isfinite(z)).any())
        self.assertGreater(len(sizes), 2, "los casos dan resultados distintos")
        self.assertGreater(min(sizes), 0)
        self.assertLess(max(sizes), int(np.isfinite(z).sum()) - int(untouchable.sum()))

    def test_two_entries_in_two_components_give_the_union(self) -> None:
        """RF-017-24: un muro intocable parte el llano en dos componentes; cada entrada alcanza la suya y con las dos entradas lo alcanzable es la **unión**, sin una celda del muro."""
        wall = np.zeros(GRID.shape, dtype=bool)
        wall[:, 29:32] = True
        west = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5)], untouchable=wall)).reachable
        east = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[(50.5, 20.5)], untouchable=wall)).reachable
        both = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5), (50.5, 20.5)], untouchable=wall))
        self.assertEqual(int(west.sum()), 29 * ROWS)
        self.assertEqual(int(east.sum()), (COLS - 32) * ROWS)
        np.testing.assert_array_equal(both.reachable, west | east)
        self.assertEqual(both.area_m2, (29 + COLS - 32) * ROWS * 1.0)
        self.assertFalse((both.reachable & wall).any())

    def test_a_cell_without_data_is_not_crossed_and_an_entry_on_a_cell_that_is_not_walkable_reaches_nothing(self) -> None:
        """RF-017-24: una columna sin dato parte lo alcanzable; una entrada en una celda no transitable (el intocable, o el escalón de pendiente) no alcanza nada: sin cotas y
        con área 0 (no se rechaza: el rechazo de RF-017-04 es de la entrada **sin dato**)."""
        z = FLAT.copy()
        z[:, 30] = np.nan
        found = road_access.access(steps_of(z, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5)]))
        self.assertTrue(found.reachable[:, :30].all())
        self.assertFalse(found.reachable[:, 30:].any())
        blocked = np.zeros(GRID.shape, dtype=bool)
        blocked[rd.cell_of((10.5, 20.5), GRID)] = True
        nothing = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5)], untouchable=blocked))
        self.assertFalse(nothing.reachable.any())
        self.assertEqual((nothing.z_min_m, nothing.z_max_m, nothing.area_m2), (None, None, 0.0))

    def test_the_untouchable_mask_is_what_cannot_be_crossed(self) -> None:
        """RF-017-24, T15-a: lo que no se atraviesa es **la máscara que lleva el trabajo** (los intocables y las exclusiones de la 012, que arma la preparación); las demás clases
        de la 012 no están en ella y la accesibilidad las atraviesa: con una banda de ellas en el camino, lo alcanzable es el llano entero."""
        band = np.zeros(GRID.shape, dtype=bool)
        band[:, 29:32] = True
        crossed = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5)]))
        self.assertTrue(crossed.reachable[:, 40:].all(), "sin máscara se atraviesa")
        held = road_access.access(steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5)], untouchable=band))
        self.assertFalse(held.reachable[:, 29:].any(), "una banda intocable no se atraviesa")


class FiguresTest(unittest.TestCase):
    def test_the_levels_and_the_area_equal_the_hand_calculation(self) -> None:
        """RF-017-24: las cotas mínima y máxima alcanzables (m) y el área alcanzable (m²) a ≤ 10⁻⁹: en la rampa del 5 % son las de la primera y la última columna
        (``0,05 · 0,5`` y ``0,05 · 59,5``) y las 2.400 celdas; con un escalón de 40 m, solo la meseta de la entrada menos las dos columnas del escalón (la que sube y la que
        baja: 29 columnas de 40 celdas) a 10 m; con celdas de 2 m el área es la de las celdas por 4."""
        plane = road_access.access(steps_of(ramp(5.0), walk_pct=10.0, width_m=1.0, entries=[(30.5, 20.5)]))
        self.assertAlmostEqual(plane.z_min_m, 0.05 * 0.5, delta=TOL)
        self.assertAlmostEqual(plane.z_max_m, 0.05 * 59.5, delta=TOL)
        self.assertAlmostEqual(plane.area_m2, 2400.0, delta=TOL)
        cliff = np.where(rd.local_centers(GRID)[0] < 30.0, 10.0, 50.0)
        found = road_access.access(steps_of(cliff, walk_pct=10.0, width_m=1.0, entries=[(5.5, 20.5)]))
        self.assertAlmostEqual(found.z_min_m, 10.0, delta=TOL)
        self.assertAlmostEqual(found.z_max_m, 10.0, delta=TOL)
        self.assertAlmostEqual(found.area_m2, 29 * 40 * 1.0, delta=TOL)
        self.assertEqual(int(found.reachable.sum()), 29 * 40)
        coarse = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 40.0, 2.0, 2.0, 30, 20)
        wide = road_access.access(steps_of(np.full(coarse.shape, 100.0), walk_pct=10.0, width_m=2.0, entries=[(5.0, 5.0)], grid=coarse))
        self.assertAlmostEqual(wide.area_m2, 600 * 4.0, delta=TOL)
        self.assertEqual((wide.z_min_m, wide.z_max_m), (100.0, 100.0))

    def test_the_outcome_carries_the_name_the_code_and_a_read_only_grid(self) -> None:
        """RF-017-24: el resultado lleva el nombre y el código de la accesibilidad, la rejilla de lo alcanzable de la forma de la rejilla y de solo lectura (nueva: no
        comparte memoria con la superficie) y, de A10, ninguna cifra ni aviso todavía (los compone la operación: T17)."""
        job = steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5)])
        found = road_access.access(job)
        self.assertEqual((found.name, found.code), ("Accesibilidad de prueba", "ACC-001"))
        self.assertEqual(found.reachable.shape, GRID.shape)
        self.assertEqual(found.reachable.dtype, np.bool_)
        self.assertFalse(found.reachable.flags.writeable)
        self.assertFalse(np.shares_memory(found.reachable, job.surface))
        self.assertEqual((found.berms, found.platforms, found.zones, found.z_min_final_m), ((), (), (), None))


class RejectionTest(unittest.TestCase):
    def test_a_layer_without_entry_points_is_rejected_naming_the_layer(self) -> None:
        """RF-017-04: ningún punto de entrada se rechaza **al llamar** con ``des.access_no_entry``, nombrando la capa y la accesibilidad, y sin elegir ninguno."""
        job = steps_of(FLAT, walk_pct=10.0, width_m=1.0, entries=[])
        for call in (lambda: road_access.access(job), lambda: road_access.access_units(job), lambda: road_access.access_steps(job)):
            with self.assertRaises(messages.DesignError) as caught:
                call()
            error = caught.exception
            self.assertEqual(error.code, "des.access_no_entry")
            self.assertIn(rd.ENTRIES_LAYER, error.text)
            self.assertIn("Accesibilidad de prueba", error.text)
            self.assertEqual(error.values["layer"], rd.ENTRIES_LAYER)
            self.assertEqual(error.field, "des.access.acc_001.entries_layer")
            self.assertEqual(error.value, rd.ENTRIES_LAYER)
            self.assertIn("no se crea nada", error.text)

    def test_an_entry_point_without_data_is_rejected_with_its_place(self) -> None:
        """RF-017-04: un punto de entrada sin dato (una celda sin cota, o fuera de la rejilla) se rechaza **al llamar** con ``des.access_entry_no_data``, nombrando la capa, el
        punto (el segundo de la lista, aunque el primero esté bien), la superficie y su lugar (x e y absolutas, al cm)."""
        z = FLAT.copy()
        z[rd.cell_of((30.5, 20.5), GRID)] = np.nan
        for place in ((30.5, 20.5), (-5.0, 20.0), (30.5, 45.0)):
            with self.subTest(place=place):
                job = steps_of(z, walk_pct=10.0, width_m=1.0, entries=[(10.5, 20.5), place])
                with self.assertRaises(messages.DesignError) as caught:
                    road_access.access(job)
                error = caught.exception
                self.assertEqual(error.code, "des.access_entry_no_data")
                self.assertEqual(error.value, "E2")
                self.assertEqual(error.values["surface"], "gis_dtm_prueba")
                absolute = rd.absolute([place], GRID)[0]
                self.assertEqual((error.values["x"], error.values["y"]), (round(float(absolute[0]), 2), round(float(absolute[1]), 2)))
                for part in (rd.ENTRIES_LAYER, "E2", "gis_dtm_prueba", "Accesibilidad de prueba"):
                    self.assertIn(part, error.text)
                self.assertEqual(error.field, "des.access.acc_001.entries_layer")

    def test_a_grid_of_non_square_cells_is_a_program_error(self) -> None:
        """RF-017-24: la apertura con un disco exacto es de celdas cuadradas (la rejilla del proyecto lo es: ``project_grid``); otra es un error del programa (``ValueError``)."""
        grid = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 60.0, 2.0, 3.0, 30, 20)
        job = steps_of(np.full(grid.shape, 100.0), walk_pct=10.0, width_m=1.0, entries=[(5.0, 5.0)], grid=grid)
        with self.assertRaises(ValueError):
            road_access.access(job)


class StepsTest(unittest.TestCase):
    @staticmethod
    def case() -> Any:
        rng = np.random.default_rng(5)
        grid = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 200.0, 1.0, 1.0, 200, 200)
        x, y = rd.local_centers(grid)
        z = 100.0 + 2.0 * np.sin(x / 15.0) + 2.0 * np.cos(y / 11.0) + rng.normal(0.0, 0.02, grid.shape)
        return grid, rd.access_job(grid, z, [(20.5, 20.5), (150.5, 120.5)], untouchable=rd.in_box((90.0, 0.0, 95.0, 120.0), grid), access=rd.AccessData(30.0, 5.0, 0.0))

    def test_the_steps_end_in_the_same_result_as_one_go_and_each_call_is_short(self) -> None:
        """RF-017-24, RNF-017-06: por pasos, lo alcanzable, las cotas y el área son los mismos bit a bit que de una vez, hay varios pasos, cada llamada del paso tarda ≤ 0,2 s (en
        una rejilla de 200 × 200 celdas y con un disco de 5 m: no solo la última), el último ``Progress`` (fase ``road_access``) lleva el resultado y todos llevan su fase."""
        grid, job = self.case()
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
        self.assertGreater(count, 3)
        self.assertLessEqual(longest, 0.2)
        found = last.result
        np.testing.assert_array_equal(found.reachable, whole.reachable)
        self.assertEqual((found.z_min_m, found.z_max_m, found.area_m2), (whole.z_min_m, whole.z_max_m, whole.area_m2))
        self.assertTrue(whole.reachable.any() and not whole.reachable.all(), "un caso con lo alcanzable partido")
        self.assertEqual(grid.shape, whole.reachable.shape)

    def test_closing_the_steps_midway_leaves_the_inputs_and_nothing_else(self) -> None:
        """RF-017-24, RNF-017-06, principio 7: cerrar el generador a mitad no deja nada y **ninguna superficie ni restricción cambia** (el resumen de la superficie, de lo
        intocable y de la final, antes y después de calcular entero y de cerrar a mitad); una pasada después da el mismo resultado."""
        _grid, job = self.case()
        final = job.surface + 1.0
        job = dataclasses.replace(job, final=final)
        keep = digest(job.surface, job.untouchable, job.final)
        before = road_access.access(job)
        steps = road_access.access_steps(job, budget_s=0.0)
        next(steps)
        next(steps)
        steps.close()
        self.assertEqual(digest(job.surface, job.untouchable, job.final), keep)
        again = road_access.access(job)
        np.testing.assert_array_equal(again.reachable, before.reachable)
        self.assertEqual(digest(job.surface, job.untouchable, job.final), keep)
        for array in (job.surface, job.untouchable, job.final):
            self.assertFalse(array.flags.writeable)

    def test_the_units_compose_with_yield_from(self) -> None:
        """RF-017-24: las unidades (``access_units``: cada ``yield``, una; el resultado, el valor de ``StopIteration``) dan lo mismo que de una vez, para componerlas con otras en
        la operación (T17)."""
        _grid, job = self.case()
        units = road_access.access_units(job, budget_s=0.0)
        count = 0
        while True:
            try:
                next(units)
            except StopIteration as done:
                found = done.value
                break
            count += 1
        self.assertGreater(count, 3)
        np.testing.assert_array_equal(found.reachable, road_access.access(job).reachable)


if __name__ == "__main__":
    unittest.main()
