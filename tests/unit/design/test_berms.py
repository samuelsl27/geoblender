# SPDX-License-Identifier: GPL-3.0-or-later
"""Las cotas reales de las bermas (spec 013, T11; HU-013-5; RF-013-28; plan 013 A12; N-14).

``design.berms`` mide, **desde el resultado**, dónde están las bermas de una superficie escalonada:
una rejilla con la cota real de cada celda de berma (``NaN`` en las demás) y una tabla con, por
sector, perfil y cota, el número de celdas, su área, la cota de anclaje más próxima y la diferencia.
Nada se supone múltiplo de nada (N-14: las líneas de rotura supusieron bermas en múltiplos de 5 m).
Una celda es de berma si está en una cota ``z₀ + n·h`` de su perfil a menos de 10⁻⁶ m, tiene una
vecina en la misma cota (de su fila o de su columna) y tiene movimiento. Se comprueba:

- **A mano** (RF-013-28): el plano del escalonado de CE-013-03 con ``EXPL_10_60_6`` y
  ``REST_5_35_6`` en corte y en relleno da una fila por cota que cruza el plano, con el número de
  celdas del cálculo a mano (racionales), el área, la cota de anclaje y la diferencia 0.
- **Sin suponer múltiplos** (N-14): alturas no enteras (7,3 m) y una rejilla de anclas dan sus
  cotas reales; una berma fuera de su cota de anclaje no se da por berma, y con una tolerancia más
  ancha la diferencia medida sale tal cual.
- **Qué celdas** (plan A12): sin movimiento no hay berma; una celda suelta, una pareja en diagonal,
  una pareja con una vecina sin movimiento y una cota sin dato no son berma; una pareja en la fila
  o en la columna, sí.
- **Los sectores**: la tabla distingue el sector y el perfil, la misma cota de dos sectores da dos
  filas, el área es la de la celda de la rejilla y el orden es el de las zonas y luego el de la cota.
- **Contra la fuerza bruta**: con 30 rejillas aleatorias (perfiles por sector, anclas en rejilla,
  movimiento y huecos) la rejilla y la tabla son las de un cálculo celda a celda en Python.
- **Los datos y los pasos**: sin avisos de numpy con ``NaN`` e infinitos, float32 se calcula en
  float64, las entradas no se tocan, partir la rejilla en bandas no cambia ni un bit, cerrar a
  mitad no deja nada, y los errores del programa son ``ValueError``.
"""

from __future__ import annotations

import math
import unittest
import warnings
from collections.abc import Sequence
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender

benching = import_geoblender("design.benching")
berms = import_geoblender("design.berms")
progress_mod = import_geoblender("core.project.model")

EXPL = dfx.EXPL_10_60_6
REST = dfx.REST_5_35_6
TOLERANCE_M = 1e-9
SCOPE = berms.BermScope("sector_1", "expl_10_60_6")
"""El sector y el perfil de las pruebas de un solo perfil."""


def tan_of(profile: Any) -> float:
    return math.tan(math.radians(profile.face_deg))


def measure(design: Any, *, height: Any = 10.0, anchor: Any = 125.0, labels: Any = None,
            scopes: Sequence[Any] | None = None, moved: Any = None, step: float = 1.0,
            **options: Any) -> Any:
    """Las bermas de ``design`` (último paso de ``berms_steps``) en una rejilla de celdas de
    ``step`` m, con un solo sector y perfil salvo que se digan."""
    cells = np.asarray(design)
    geometry = dfx.grid_from(cells.shape[0], cells.shape[1], step)
    zones = np.zeros(cells.shape, dtype=np.int16) if labels is None else labels
    steps = berms.berms_steps(cells, geometry, height, anchor, zones,
                              (SCOPE,) if scopes is None else scopes, moved=moved, **options)
    return list(steps)[-1].result


def stairs(profile: Any, surface: np.ndarray, *, fill: bool) -> np.ndarray:
    function = benching.bench_fill if fill else benching.bench_cut
    return function(surface, profile.height_m, tan_of(profile), profile.berm_m, profile.anchor_m)


def hand(profile: Any, surface: np.ndarray, *, fill: bool) -> np.ndarray:
    return oracles.hand_stairs(surface, profile.height_m, tan_of(profile), profile.berm_m,
                               profile.anchor_m, fill=fill)


def cells_set(grid: np.ndarray) -> set[tuple[int, int]]:
    """Las celdas con cota de una rejilla de bermas."""
    return {(int(row), int(col)) for row, col in np.argwhere(np.isfinite(grid))}


class PlaneBermsTest(unittest.TestCase):
    """RF-013-28: el plano de CE-013-03 con los dos perfiles de la spec, en los dos sentidos."""

    def setUp(self) -> None:
        self.case = dfx.plane_case()
        self.surface = self.case.surface()
        self.row = self.surface[0].copy()

    def each(self) -> Any:
        for profile in (EXPL, REST):
            for sense, fill in (("corte", False), ("relleno", True)):
                scope = berms.BermScope("frente", profile.code)
                found = measure(stairs(profile, self.surface, fill=fill), height=profile.height_m,
                                anchor=profile.anchor_m, scopes=(scope,))
                yield profile, sense, fill, found

    def test_one_row_per_level_with_the_hand_counts(self) -> None:
        """RF-013-28: una fila por cota ``z₀ + n·h`` con celdas planas (la lista a mano de
        ``hand_levels``), con las celdas del cálculo a mano en racionales por las 40 filas, el
        área (celdas de 1 m²), la cota de anclaje igual a la cota y la diferencia 0, de menor a
        mayor cota."""
        for profile, sense, fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                expected_row = hand(profile, self.row, fill=fill)
                levels = dfx.hand_levels(profile, float(self.row.min()) - profile.height_m,
                                         float(self.row.max()) + profile.height_m)
                by_hand = [(level, int(np.count_nonzero(np.abs(expected_row - level)
                                                        <= TOLERANCE_M)) * 40)
                           for level in levels]
                by_hand = [item for item in by_hand if item[1] > 0]
                self.assertGreaterEqual(len(by_hand), 4)
                self.assertEqual(len(found.table), len(by_hand))
                for row, (level, cells) in zip(found.table, by_hand, strict=True):
                    self.assertEqual((row.sector, row.profile), ("frente", profile.code))
                    self.assertAlmostEqual(row.level_m, level, delta=1e-6)
                    self.assertEqual(row.cells, cells)
                    self.assertEqual(row.area_m2, cells * 1.0)
                    self.assertAlmostEqual(row.anchor_m, level, delta=TOLERANCE_M)
                    self.assertEqual(row.anchor_diff_m, 0.0)
                levels_found = [row.level_m for row in found.table]
                self.assertEqual(levels_found, sorted(levels_found))

    def test_grid_has_the_real_level_of_each_berm_cell_and_nothing_else(self) -> None:
        """RF-013-28: la rejilla tiene la cota real (la del resultado, sin redondear) en las celdas
        de berma y ``NaN`` en las demás; son todas las celdas planas del resultado a mano; el total
        de celdas y de área de ``Berms`` es el de la tabla."""
        for profile, sense, fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                design = stairs(profile, self.surface, fill=fill)
                self.assertEqual(found.grid.shape, design.shape)
                self.assertEqual(found.grid.dtype, np.float64)
                flat = np.isfinite(found.grid)
                np.testing.assert_array_equal(found.grid[flat], design[flat])
                self.assertTrue(np.isnan(found.grid[~flat]).all())
                on_level = np.abs(design - np.round((design - profile.anchor_m)
                                                    / profile.height_m) * profile.height_m
                                  - profile.anchor_m) <= TOLERANCE_M
                self.assertTrue(np.array_equal(flat, on_level))
                self.assertEqual(found.cells, int(flat.sum()))
                self.assertEqual(found.cells, sum(row.cells for row in found.table))
                self.assertEqual(found.area_m2, found.cells * 1.0)

    def test_summary_figures(self) -> None:
        """La cuenta de bermas (filas de la tabla) y las cotas más baja y más alta."""
        for profile, sense, _fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                self.assertEqual(found.count, len(found.table))
                self.assertEqual(found.lowest_m, found.table[0].level_m)
                self.assertEqual(found.highest_m, found.table[-1].level_m)
        empty = measure(np.full((3, 4), 100.0))
        self.assertEqual((empty.count, empty.cells, empty.area_m2), (0, 0, 0.0))
        self.assertIsNone(empty.lowest_m)
        self.assertIsNone(empty.highest_m)
        self.assertEqual(empty.table, ())
        self.assertTrue(np.isnan(empty.grid).all())


class NoMultiplesTest(unittest.TestCase):
    """N-14: las cotas salen del resultado, no se suponen múltiplos de nada."""

    def test_non_integer_height_gives_its_own_levels(self) -> None:
        """Con ``h`` = 7,3 m y ancla 118,2 m las bermas están en 118,2 + 7,3·n (125,5; 132,8…),
        que no son múltiplos de 5 ni de 10 m, a ≤ 10⁻⁶ m."""
        surface = np.broadcast_to(120.0 + 0.25 * (np.arange(120) + 0.5), (6, 120)).copy()
        tan_face = math.tan(math.radians(55.0))
        design = benching.bench_cut(surface, 7.3, tan_face, 5.0, 118.2)
        found = measure(design, height=7.3, anchor=118.2)
        self.assertGreaterEqual(found.count, 3)
        for row in found.table:
            number = round((row.level_m - 118.2) / 7.3)
            self.assertAlmostEqual(row.level_m, 118.2 + 7.3 * number, delta=1e-6)
            self.assertAlmostEqual(row.anchor_m, 118.2 + 7.3 * number, delta=1e-8)
            self.assertAlmostEqual(row.anchor_diff_m, 0.0, delta=1e-8)
            self.assertGreater(abs(row.level_m / 5.0 - round(row.level_m / 5.0)), 1e-3)

    def test_anchor_grid_gives_each_cell_its_own_anchor(self) -> None:
        """RF-013-24, RF-013-28: con una rejilla de anclas (100 m al oeste y 103,5 m al este) las
        bermas del oeste están en 100 + 10·n y las del este en 103,5 + 10·n, y la fila de la tabla
        dice la cota de anclaje de su mitad."""
        surface = np.broadcast_to(120.0 + 0.5 * (np.arange(80) + 0.5), (4, 80)).copy()
        anchor = np.where(np.arange(80)[None, :] < 40, 100.0, 103.5) + np.zeros((4, 1))
        design = benching.bench_cut(surface, 10.0, tan_of(EXPL), 6.0, anchor)
        found = measure(design, height=10.0, anchor=anchor)
        west = [row for row in found.table if abs((row.level_m - 100.0) / 10.0
                                                  - round((row.level_m - 100.0) / 10.0)) < 1e-6]
        east = [row for row in found.table if abs((row.level_m - 103.5) / 10.0
                                                  - round((row.level_m - 103.5) / 10.0)) < 1e-6]
        self.assertGreaterEqual(len(west), 1)
        self.assertGreaterEqual(len(east), 1)
        self.assertEqual(len(west) + len(east), found.count)
        for row in found.table:
            base = 100.0 if row in west else 103.5
            self.assertAlmostEqual(row.anchor_m, base + 10.0 * round((row.level_m - base) / 10.0),
                                   delta=TOLERANCE_M)
            self.assertEqual(row.anchor_diff_m, 0.0)

    def test_a_flat_off_the_anchor_levels_is_not_a_berm(self) -> None:
        """Un resultado corrido 0,5 m (como el cierre del balance del error 12) no se da por berma
        ni se inventa una cota: la tolerancia es 10⁻⁶ m."""
        surface = np.broadcast_to(140.0 + 0.25 * (np.arange(160) + 0.5), (6, 160)).copy()
        design = stairs(EXPL, surface, fill=False)
        self.assertGreater(measure(design).count, 3)
        shifted = measure(design + 0.5)
        self.assertEqual((shifted.count, shifted.cells), (0, 0))
        self.assertTrue(np.isnan(shifted.grid).all())

    def test_difference_is_measured_not_assumed(self) -> None:
        """Con una tolerancia más ancha (1 mm), una berma 0,5 mm por encima de su cota entra con su
        cota real (la de la rejilla) y la tabla da la diferencia medida frente a la cota de
        anclaje, no 0; con la tolerancia por defecto no entra."""
        design = np.full((3, 5), 100.0)
        design[1, 1:4] = 145.0005
        self.assertEqual(measure(design).cells, 0)
        found = measure(design, tolerance_m=1e-3)
        self.assertEqual(found.cells, 3)
        self.assertEqual(found.grid[1, 2], 145.0005)
        row = found.table[0]
        self.assertAlmostEqual(row.level_m, 145.0005, delta=1e-9)
        self.assertAlmostEqual(row.anchor_m, 145.0, delta=1e-9)
        self.assertAlmostEqual(row.anchor_diff_m, 0.0005, delta=1e-9)

    def test_anchor_of_a_row_is_the_one_of_its_first_cell(self) -> None:
        """Con una tolerancia ancha, celdas de una misma cota con anclas distintas (125 m y
        144,8 m, ``h`` = 10 m) son una fila cuya cota de anclaje y diferencia son las de la primera
        celda de la rejilla (la más al norte), con cualquier tamaño de banda."""
        design = np.full((5, 5), 100.0)
        design[1, 1:3] = 145.0
        design[3, 1:3] = 145.0
        anchor = np.full(design.shape, 125.0)
        anchor[3, :] = 144.8
        for per_unit in (5, 10, 1000):
            with self.subTest(cells_per_unit=per_unit):
                found = measure(design, anchor=anchor, tolerance_m=0.5, cells_per_unit=per_unit)
                self.assertEqual([row.values() for row in found.table],
                                 [("sector_1", "expl_10_60_6", 145.0, 4, 4.0, 145.0, 0.0)])
        flipped = measure(design, anchor=anchor[::-1].copy(), tolerance_m=0.5)
        self.assertEqual(flipped.cells, 4)  # el ancla de (1,1) es ahora 144,8 y la de (3,1), 125
        self.assertAlmostEqual(flipped.table[0].anchor_m, 144.8, delta=1e-9)
        self.assertAlmostEqual(flipped.table[0].anchor_diff_m, 0.2, delta=1e-9)

    def test_residual_below_the_tolerance_groups_into_one_level(self) -> None:
        """Las celdas de una cota con diferencias de 4·10⁻⁷ m o de redondeo son una sola fila, a la
        cota redondeada a 10⁻⁶ m; la rejilla conserva su cota real."""
        design = np.full((3, 6), 100.0)
        design[1, 0:4] = (145.0, 145.0 + 4e-7, 145.0 - 3e-7, 145.0 + 1e-13)
        found = measure(design)
        self.assertEqual(found.count, 1)
        self.assertEqual((found.table[0].level_m, found.table[0].cells), (145.0, 4))
        self.assertEqual(float(found.grid[1, 1]), 145.0 + 4e-7)


def plateaus() -> np.ndarray:
    """Una rejilla de 6 × 9 a 100 m (no es una cota de ancla: 125 + 10·n) con:
    ``A`` una pareja en la fila a 135 m (1,1) (1,2); ``B`` una pareja en la columna (3,5) (4,5);
    ``C`` una celda suelta (4,1); ``D`` una pareja en diagonal (1,7) (2,8)."""
    design = np.full((6, 9), 100.0)
    design[1, 1:3] = 135.0
    design[3:5, 5] = 135.0
    design[4, 1] = 135.0
    design[1, 7] = 135.0
    design[2, 8] = 135.0
    return design


BERM_CELLS = {(1, 1), (1, 2), (3, 5), (4, 5)}


class WhichCellsTest(unittest.TestCase):
    """Plan 013 A12: qué celdas son de berma."""

    def test_pairs_in_the_row_and_in_the_column_but_not_single_or_diagonal(self) -> None:
        """Una pareja de celdas vecinas a la misma cota (en la fila o en la columna) es berma; una
        celda suelta y una pareja en diagonal no."""
        found = measure(plateaus())
        self.assertEqual(cells_set(found.grid), BERM_CELLS)
        self.assertEqual(found.cells, 4)
        self.assertEqual(found.count, 1)
        self.assertEqual(found.table[0].level_m, 135.0)

    def test_without_movement_there_is_no_berm(self) -> None:
        """Una celda sin movimiento no es berma aunque esté a una cota de anclaje y plana (un
        banco natural): con ``moved`` falso en una pareja, ni ella ni su vecina sin movimiento lo
        son, y una pareja con movimiento sigue siéndolo."""
        design = plateaus()
        moved = np.ones(design.shape, dtype=bool)
        moved[1, 1:3] = False
        found = measure(design, moved=moved)
        self.assertEqual(cells_set(found.grid), {(3, 5), (4, 5)})
        half = moved.copy()
        half[1, 1] = True  # (1, 1) se mueve, (1, 2) no: una celda sola con vecina fija
        self.assertEqual(cells_set(measure(design, moved=half).grid), {(3, 5), (4, 5)})
        self.assertEqual(cells_set(measure(design, moved=np.zeros(design.shape, bool)).grid), set())

    def test_flat_means_the_same_level_within_the_tolerance(self) -> None:
        """Dos vecinas a 135 m y 135 m + 2·10⁻⁶ m (más que la tolerancia) no son una berma; a
        + 5·10⁻⁷ m, sí."""
        design = np.full((3, 6), 100.0)
        design[1, 1:3] = (135.0, 135.0 + 2e-6)
        self.assertEqual(measure(design).cells, 0)
        design[1, 1:3] = (135.0, 135.0 + 5e-7)
        self.assertEqual(measure(design).cells, 2)

    def test_tolerance_is_inclusive_at_both_comparisons(self) -> None:
        """Una cota a exactamente ``tolerance_m`` de su cota de anclaje y dos vecinas a exactamente
        ``tolerance_m`` entre sí (0,5 m, exacto en binario) entran; con una tolerancia un ulp menor,
        no."""
        design = np.full((3, 5), 100.0)
        design[1, 1:3] = (145.0, 145.5)  # 145,5 está a 0,5 m de 145
        found = measure(design, tolerance_m=0.5)
        self.assertEqual(cells_set(found.grid), {(1, 1), (1, 2)})
        smaller = measure(design, tolerance_m=float(np.nextafter(0.5, 0.0)))
        self.assertEqual(smaller.cells, 0)
        design[1, 1:3] = (145.25, 145.75)  # a 0,25 y 0,75 m... la segunda ya no es candidata
        self.assertEqual(measure(design, tolerance_m=0.5).cells, 0)
        design[1, 1:3] = (144.75, 145.25)  # las dos a 0,25 m de 145 y entre sí a 0,5 m
        self.assertEqual(measure(design, tolerance_m=0.5).cells, 2)
        self.assertEqual(measure(design, tolerance_m=float(np.nextafter(0.5, 0.0))).cells, 0)
        column = np.full((4, 3), 100.0)
        column[1:3, 1] = (144.75, 145.25)  # lo mismo con una pareja de la columna
        self.assertEqual(measure(column, tolerance_m=0.5).cells, 2)
        self.assertEqual(measure(column, tolerance_m=float(np.nextafter(0.5, 0.0))).cells, 0)

    def test_cells_without_data_are_not_berm_and_raise_no_warnings(self) -> None:
        """Una celda ``NaN``, ``+inf`` o ``−inf`` no es berma y no deja a su vecina sin pareja
        si esta tiene otra; no hay avisos de numpy."""
        design = plateaus()
        design[1, 3] = np.nan
        design[2, 2] = np.inf
        design[0, 2] = -np.inf
        design[3, 5] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            found = measure(design)
        self.assertEqual(cells_set(found.grid), {(1, 1), (1, 2)})

    def test_levels_of_the_edges_of_the_grid(self) -> None:
        """Una berma contra el borde de la rejilla (primera y última fila y columna) se mide
        igual."""
        design = np.full((4, 6), 100.0)
        design[0, 0:2] = 135.0
        design[3, 4:6] = 145.0
        design[1:3, 5] = 135.0
        found = measure(design)
        self.assertEqual(cells_set(found.grid), {(0, 0), (0, 1), (3, 4), (3, 5), (1, 5), (2, 5)})
        self.assertEqual([(row.level_m, row.cells) for row in found.table],
                         [(135.0, 4), (145.0, 2)])

    def test_two_levels_that_touch_are_two_rows(self) -> None:
        """Dos cotas de anclaje vecinas son dos filas (no una berma de dos cotas): sus celdas se
        unen con las de su propia cota."""
        design = np.full((4, 6), 100.0)
        design[1, 1:3] = 135.0
        design[2, 1:3] = 145.0
        found = measure(design)
        self.assertEqual([(row.level_m, row.cells) for row in found.table],
                         [(135.0, 2), (145.0, 2)])


class ScopesTest(unittest.TestCase):
    """Los sectores y los perfiles de la tabla."""

    def two_sectors(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """4 × 8 a 100 m con dos mitades: al oeste (zona 0) ``h`` 10 y ancla 125; al este (zona 1)
        ``h`` 5 y ancla 100. Las dos tienen 135 m en 16 celdas y el este, además, 140 m en 4."""
        design = np.full((4, 8), 100.0)
        design[:, 0:4] = 135.0
        design[:, 4:8] = 135.0
        design[1:3, 6:8] = 140.0
        labels = np.zeros(design.shape, dtype=np.int16)
        labels[:, 4:] = 1
        height = np.where(labels == 0, 10.0, 5.0)
        anchor = np.where(labels == 0, 125.0, 100.0)
        return design, labels, height, anchor

    def test_one_row_per_sector_profile_and_level(self) -> None:
        """RF-013-28: la misma cota en dos sectores son dos filas, cada una con su sector, su
        perfil y su cota de anclaje; el orden es el de las zonas y luego el de la cota; el área es
        la de la celda de la rejilla (2,5 m → 6,25 m²)."""
        design, labels, height, anchor = self.two_sectors()
        scopes = (berms.BermScope("oeste", "expl_10_60_6"), berms.BermScope("este", "rest_5_35_6"))
        found = measure(design, height=height, anchor=anchor, labels=labels, scopes=scopes,
                        step=2.5)
        self.assertEqual([row.values() for row in found.table], [
            ("oeste", "expl_10_60_6", 135.0, 16, 100.0, 135.0, 0.0),
            ("este", "rest_5_35_6", 135.0, 12, 75.0, 135.0, 0.0),
            ("este", "rest_5_35_6", 140.0, 4, 25.0, 140.0, 0.0)])
        self.assertEqual(found.cells, 32)
        self.assertEqual(found.area_m2, 32 * 6.25)

    def test_table_is_ordered_by_zone_and_level_whatever_the_order_of_the_rows(self) -> None:
        """Las filas salen por zona y luego por cota aunque en la rejilla aparezca antes (más al
        norte) una zona o una cota mayor, y con cualquier tamaño de banda."""
        design = np.full((8, 4), 100.0)
        labels = np.zeros(design.shape, dtype=np.int16)
        design[0:2, :] = 145.0
        labels[0:2, :] = 1
        design[2:4, :] = 155.0
        design[4:6, :] = 135.0
        design[6:8, :] = 145.0
        scopes = (berms.BermScope("a", "p"), berms.BermScope("b", "p"))
        expected = [("a", 135.0), ("a", 145.0), ("a", 155.0), ("b", 145.0)]
        for per_unit in (4, 8, 1000):
            with self.subTest(cells_per_unit=per_unit):
                found = measure(design, labels=labels, scopes=scopes, cells_per_unit=per_unit)
                self.assertEqual([(row.sector, row.level_m) for row in found.table], expected)
                self.assertEqual([row.cells for row in found.table], [8, 8, 8, 8])

    def test_a_scope_without_berms_has_no_row_and_a_label_can_repeat_the_profile(self) -> None:
        """Una zona sin bermas no sale en la tabla; dos zonas con el mismo perfil y distinto
        sector son dos filas."""
        design, labels, height, anchor = self.two_sectors()
        scopes = (berms.BermScope("a", "p"), berms.BermScope("b", "p"), berms.BermScope("c", "q"))
        found = measure(design, height=height, anchor=anchor, labels=labels, scopes=scopes)
        self.assertEqual([(row.sector, row.profile) for row in found.table],
                         [("a", "p"), ("b", "p"), ("b", "p")])
        only_east = measure(design, height=height, anchor=anchor, labels=labels, scopes=scopes,
                            moved=labels == 1)
        self.assertEqual([row.sector for row in only_east.table], ["b", "b"])

    def test_sector_code_may_be_empty(self) -> None:
        """El perímetro de actuación (código vacío) y el perfil base se escriben tal cual."""
        design, labels, height, anchor = self.two_sectors()
        scopes = (berms.BermScope("", "base"), berms.BermScope("sector_2", "otro"))
        found = measure(design, height=height, anchor=anchor, labels=labels, scopes=scopes)
        self.assertEqual(found.table[0].sector, "")
        self.assertEqual(found.table[0].profile, "base")


# --- La fuerza bruta -------------------------------------------------------------------------------


def brute_force(design: np.ndarray, height: np.ndarray, anchor: np.ndarray, labels: np.ndarray,
                scopes: Sequence[Any], moved: np.ndarray, tolerance: float, area: float
                ) -> tuple[np.ndarray, list[tuple[Any, ...]]]:
    """El mismo cálculo celda a celda, con bucles de Python y conjuntos, sin ningún array de
    numpy en la lógica: la rejilla y las filas (``values()``) de la tabla."""
    rows, cols = design.shape
    candidates: set[tuple[int, int]] = set()
    for row in range(rows):
        for col in range(cols):
            level = float(design[row, col])
            if not math.isfinite(level) or not bool(moved[row, col]):
                continue
            h, z0 = float(height[row, col]), float(anchor[row, col])
            if abs(level - (z0 + round((level - z0) / h) * h)) <= tolerance:
                candidates.add((row, col))
    berm: list[tuple[int, int]] = []
    for row, col in sorted(candidates):
        for d_row, d_col in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            other = (row + d_row, col + d_col)
            if other in candidates and abs(float(design[row, col])
                                           - float(design[other])) <= tolerance:
                berm.append((row, col))
                break
    grid = np.full(design.shape, np.nan)
    groups: dict[tuple[int, int], list[Any]] = {}
    for row, col in berm:
        grid[row, col] = design[row, col]
        key = (int(labels[row, col]), round(float(design[row, col]) * 1e6))
        if key not in groups:
            groups[key] = [0, float(height[row, col]), float(anchor[row, col])]
        groups[key][0] += 1
    table = []
    for (label, units), (count, h, z0) in sorted(groups.items()):
        level = units / 1e6
        near = z0 + round((level - z0) / h) * h
        scope = scopes[label]
        table.append((scope.sector, scope.profile, level, count, count * area, round(near, 9),
                      round(level - near, 9) + 0.0))
    return grid, table


def random_case(seed: int) -> dict[str, Any]:
    """Un diseño aleatorio de 14 × 17: tres zonas con alturas y anclas propias (el ancla, a veces
    una rejilla), escalonado en corte de un terreno ondulado, con huecos, infinitos y movimiento
    aleatorio."""
    rng = np.random.default_rng(seed)
    shape = (14, 17)
    labels = rng.integers(0, 3, size=shape).astype(np.int16)
    labels = np.sort(labels, axis=1)  # franjas: las bermas caben dentro de una zona
    heights = np.array([10.0, 5.0, 7.3])[labels]
    anchors = np.array([125.0, 100.0, 118.2])[labels]
    if seed % 2:
        anchors = anchors + rng.choice([0.0, 3.5], size=shape)
    columns = np.arange(shape[1])[None, :] + 0.5
    rows = np.arange(shape[0])[:, None] + 0.5
    surface = 130.0 + rng.uniform(0.1, 0.6) * columns + rng.uniform(-0.2, 0.2) * rows \
        + 2.0 * np.sin(columns / rng.uniform(2.0, 6.0))
    design = benching.bench_cut(surface, heights, tan_of(REST), 6.0, anchors)
    design[rng.random(shape) < 0.04] = np.nan
    design[rng.random(shape) < 0.02] = np.inf
    return {"design": design, "height": heights, "anchor": anchors, "labels": labels,
            "moved": rng.random(shape) < 0.85}


class BruteForceTest(unittest.TestCase):
    """RF-013-28: la rejilla y la tabla son las de un cálculo celda a celda."""

    def test_random_designs_match_the_cell_by_cell_calculation(self) -> None:
        """Con 30 diseños aleatorios (tres zonas, anclas en rejilla, huecos, infinitos y
        movimiento) la rejilla es igual bit a bit y las filas de la tabla son las mismas, con
        la cota, la cota de anclaje y la diferencia a 10⁻⁹ m."""
        scopes = (berms.BermScope("a", "p"), berms.BermScope("b", "q"), berms.BermScope("", "r"))
        total = 0
        for seed in range(30):
            case = random_case(seed)
            with self.subTest(seed=seed):
                found = measure(case["design"], height=case["height"], anchor=case["anchor"],
                                labels=case["labels"], scopes=scopes, moved=case["moved"],
                                step=2.0)
                grid, table = brute_force(case["design"], case["height"], case["anchor"],
                                          case["labels"], scopes, case["moved"],
                                          berms.ANCHOR_TOLERANCE_M, 4.0)
                self.assertTrue(np.array_equal(found.grid, grid, equal_nan=True))
                self.assertEqual(len(found.table), len(table))
                for row, expected in zip(found.table, table, strict=True):
                    values = row.values()
                    self.assertEqual(values[:2], expected[:2])
                    self.assertEqual(values[3], expected[3])
                    for index in (2, 4, 5, 6):
                        self.assertAlmostEqual(values[index], expected[index], delta=TOLERANCE_M)
                total += found.cells
        self.assertGreater(total, 300)


class DataTest(unittest.TestCase):
    """Los datos y los errores del programa."""

    def test_float32_is_computed_in_float64_and_inputs_are_not_modified(self) -> None:
        """Un resultado float32 se calcula como float64; la salida es nueva (float64, sin memoria
        compartida) y la superficie, el movimiento, las zonas y los mapas no se tocan."""
        design = plateaus()
        moved = np.ones(design.shape, dtype=bool)
        labels = np.zeros(design.shape, dtype=np.int16)
        height = np.full(design.shape, 10.0)
        anchor = np.full(design.shape, 125.0)
        before = [item.copy() for item in (design, moved, labels, height, anchor)]
        found = measure(design, height=height, anchor=anchor, labels=labels, moved=moved)
        for item, original in zip((design, moved, labels, height, anchor), before, strict=True):
            self.assertTrue(np.array_equal(item, original))
        self.assertEqual(found.grid.dtype, np.float64)
        self.assertFalse(np.shares_memory(found.grid, design))
        narrow = measure(design.astype(np.float32))
        self.assertEqual(narrow.grid.dtype, np.float64)
        self.assertTrue(np.array_equal(narrow.grid, measure(design.astype(np.float32)
                                                            .astype(np.float64)).grid,
                                       equal_nan=True))

    def test_height_and_anchor_of_cells_that_cannot_be_berm_are_not_checked(self) -> None:
        """Un perfil o un ancla sin valor (``NaN``) en una celda sin superficie o sin movimiento no
        impide medir las demás."""
        design = plateaus()
        design[5, 8] = np.nan
        moved = np.ones(design.shape, dtype=bool)
        moved[0, 0] = False
        height = np.full(design.shape, 10.0)
        anchor = np.full(design.shape, 125.0)
        height[5, 8] = height[0, 0] = np.nan
        anchor[5, 8] = anchor[0, 0] = np.nan
        found = measure(design, height=height, anchor=anchor, moved=moved)
        self.assertEqual(cells_set(found.grid), BERM_CELLS)

    def test_bad_values_of_a_live_cell_are_program_errors(self) -> None:
        """Una altura que no sea finita y mayor que 0 o un ancla no finita en una celda con
        superficie y movimiento son ``ValueError`` que nombra el parámetro, como escalar y como
        array."""
        design = plateaus()
        cases = (("height", 0.0), ("height", -10.0), ("height", math.nan), ("height", math.inf),
                 ("anchor", math.nan), ("anchor", math.inf))
        for name, value in cases:
            for as_array in (False, True):
                good = {"height": 10.0, "anchor": 125.0}
                if as_array:
                    array = np.full(design.shape, good[name])
                    array[1, 1] = value
                    good[name] = array
                else:
                    good[name] = value
                with self.subTest(name=name, value=value, as_array=as_array):
                    with self.assertRaisesRegex(ValueError, name):
                        measure(design, **good)

    def test_bad_shapes_and_arguments_are_program_errors(self) -> None:
        """Una superficie que no es de la forma de la rejilla, unas zonas o un movimiento de otra
        forma o tipo, una zona fuera de la lista, un mapa que no cabe, una tolerancia o unas celdas
        por unidad inválidas son ``ValueError``."""
        design = plateaus()
        shape = design.shape
        geometry = dfx.grid_from(shape[0], shape[1], 1.0)
        zero = np.zeros(shape, dtype=np.int16)
        cases: list[tuple[str, dict[str, Any]]] = [
            ("superficie 1D", {"design": design[0]}),
            ("superficie de otra forma", {"design": design[:, :-1]}),
            ("zonas de otra forma", {"labels": zero[:, :-1]}),
            ("zonas decimales", {"labels": zero.astype(np.float64)}),
            ("zona negativa", {"labels": zero - 1}),
            ("zona sin perfil", {"labels": zero + 1}),
            ("sin zonas", {"scopes": ()}),
            ("movimiento entero", {"moved": np.ones(shape, dtype=np.int8)}),
            ("movimiento de otra forma", {"moved": np.ones((2, 2), dtype=bool)}),
            ("altura que no cabe", {"height": np.full((shape[0], shape[1] + 1), 10.0)}),
            ("ancla que no cabe", {"anchor": np.full((2, shape[0], shape[1]), 125.0)}),
            ("tolerancia 0", {"tolerance_m": 0.0}),
            ("tolerancia negativa", {"tolerance_m": -1e-6}),
            ("tolerancia NaN", {"tolerance_m": math.nan}),
            ("tolerancia infinita", {"tolerance_m": math.inf}),
            ("celdas por unidad 0", {"cells_per_unit": 0}),
        ]
        for label, change in cases:
            arguments: dict[str, Any] = {"design": design, "height": 10.0, "anchor": 125.0,
                                         "labels": zero, "scopes": (SCOPE,)}
            arguments.update(change)
            surface = arguments.pop("design")
            positional = [arguments.pop(name) for name in ("height", "anchor", "labels", "scopes")]
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    list(berms.berms_steps(surface, geometry, *positional, **arguments))

    def test_geometry_of_another_shape_is_refused(self) -> None:
        """Una rejilla (geometría) que no es de la forma de la superficie es ``ValueError``."""
        design = plateaus()
        geometry = dfx.grid_from(design.shape[0] + 1, design.shape[1], 1.0)
        with self.assertRaises(ValueError):
            list(berms.berms_steps(design, geometry, 10.0, 125.0,
                                   np.zeros(design.shape, dtype=np.int16), (SCOPE,)))

    def test_refusals_come_at_the_call_not_when_stepping(self) -> None:
        """Los rechazos de forma, tipo y rango salen al llamar, antes de ceder ningún paso."""
        design = plateaus()
        geometry = dfx.grid_from(*design.shape, 1.0)
        zero = np.zeros(design.shape, dtype=np.int16)
        with self.assertRaises(ValueError):
            berms.berms_steps(design[0], geometry, 10.0, 125.0, zero, (SCOPE,))
        with self.assertRaises(ValueError):
            berms.berms_steps(design, geometry, 10.0, 125.0, zero + 1, (SCOPE,))
        with self.assertRaises(ValueError):
            berms.berms_steps(design, geometry, 0.0, 125.0, zero, (SCOPE,))

    def test_row_type_and_columns(self) -> None:
        """La tabla tiene las columnas de la spec, en su orden, y ``values()`` las da todas."""
        self.assertEqual(berms.COLUMNS, ("sector", "profile", "level_m", "cells", "area_m2",
                                         "anchor_m", "anchor_diff_m"))
        row = berms.BermRow("s", "p", 135.0, 4, 4.0, 135.0, 0.0)
        self.assertEqual(row.values(), ("s", "p", 135.0, 4, 4.0, 135.0, 0.0))
        self.assertEqual(len(row.values()), len(berms.COLUMNS))
        self.assertIsInstance(row.cells, int)

    def test_numbers_of_the_table_are_python_types(self) -> None:
        """Las cifras de la tabla son ``int``, ``float`` y ``str`` de Python (no de numpy), listas
        para escribirse en la base de datos."""
        found = measure(plateaus())
        for value, kind in zip(found.table[0].values(),
                               (str, str, float, int, float, float, float), strict=True):
            self.assertIs(type(value), kind)


class StepsTest(unittest.TestCase):
    """Por pasos, con presupuesto y cancelación (RNF-013-07)."""

    def test_banding_does_not_change_a_bit(self) -> None:
        """Partir la rejilla en bandas de 1, 3 o todas las filas da la misma rejilla y la misma
        tabla bit a bit (con una berma que cruza el borde entre bandas)."""
        case = random_case(5)
        scopes = (berms.BermScope("a", "p"), berms.BermScope("b", "q"), berms.BermScope("", "r"))
        options = {"height": case["height"], "anchor": case["anchor"], "labels": case["labels"],
                   "scopes": scopes, "moved": case["moved"]}
        whole = measure(case["design"], cells_per_unit=10_000_000, **options)
        self.assertGreater(whole.cells, 10)
        for per_unit in (1, 17, 34, 51, 100):
            with self.subTest(cells_per_unit=per_unit):
                banded = measure(case["design"], cells_per_unit=per_unit, **options)
                self.assertTrue(np.array_equal(banded.grid, whole.grid, equal_nan=True))
                self.assertEqual(banded.table, whole.table)
                self.assertEqual((banded.cells, banded.area_m2), (whole.cells, whole.area_m2))

    def test_progress_and_result(self) -> None:
        """D-20: los ``Progress`` son de la fase «berms», con avance creciente, y solo el último
        lleva el resultado (``Berms``)."""
        design = plateaus()
        geometry = dfx.grid_from(*design.shape, 1.0)
        steps = list(berms.berms_steps(design, geometry, 10.0, 125.0,
                                       np.zeros(design.shape, dtype=np.int16), (SCOPE,),
                                       budget_s=1e-9, cells_per_unit=9))
        self.assertGreater(len(steps), 4)
        done = [item.done for item in steps]
        self.assertEqual(done, sorted(done))
        for item in steps:
            self.assertIsInstance(item, progress_mod.Progress)
            self.assertEqual(item.phase, "berms")
            self.assertTrue(item.message)
        self.assertTrue(all(item.result is None for item in steps[:-1]))
        self.assertIsInstance(steps[-1].result, berms.Berms)
        self.assertEqual(steps[-1].done, steps[-1].total)

    def test_closing_midway_leaves_nothing(self) -> None:
        """Cerrar el generador a mitad no deja nada ni toca las entradas."""
        design = plateaus()
        before = design.copy()
        geometry = dfx.grid_from(*design.shape, 1.0)
        half_way = berms.berms_steps(design, geometry, 10.0, 125.0,
                                     np.zeros(design.shape, dtype=np.int16), (SCOPE,),
                                     budget_s=1e-9, cells_per_unit=9)
        self.assertIsNone(next(half_way).result)
        half_way.close()
        self.assertTrue(np.array_equal(design, before))

    def test_large_grid_by_rows_gives_the_same(self) -> None:
        """Una rejilla de 600 × 700 celdas con varios niveles, medida fila a fila (mil celdas por
        unidad), da la misma rejilla y la misma tabla que en bandas grandes."""
        surface = np.broadcast_to(100.0 + 0.1 * (np.arange(700) + 0.5), (600, 700)).copy()
        design = benching.bench_cut(surface, 10.0, tan_of(EXPL), 6.0, 125.0)
        found = measure(design)
        self.assertGreater(found.count, 4)
        again = measure(design, cells_per_unit=1000)
        self.assertEqual(again.table, found.table)
        self.assertTrue(np.array_equal(again.grid, found.grid, equal_nan=True))


if __name__ == "__main__":
    unittest.main()
