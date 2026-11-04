# SPDX-License-Identifier: GPL-3.0-or-later
"""El informe de la superficie de diseño (spec 013, T12; HU-013-2, HU-013-6; RF-013-30, RF-013-17;
CE-013-07; plan 013 A11, D-13, D-25).

``design.report`` da, frente a la superficie de partida y con el espesor mínimo de verificación de
la 012, las cifras CALCULADO de un diseño y los avisos que las acompañan:

- **Volúmenes** (A7 de la 012): desmonte y terraplén (m³) y área con movimiento (m²) de las celdas
  cuya diferencia pasa del espesor mínimo, con todo su espesor; lo que no lo pasa no cuenta.
- **Inclinación** (D-13): la de cada celda es la mayor a sus 8 vecinos; p90, p99 y máxima (°) sobre
  las celdas con movimiento, con el lugar absoluto (float64) de la celda del máximo.
- **Salto en el borde de lo prohibido** (D-9): el mayor escalón (m) entre una celda con movimiento y
  una vecina de lado que se quedó como estaba por no estar admitida.
- **Avisos**: movimiento en el borde de la rejilla, inclinación por encima de la cara más la
  tolerancia, magnitud frente a la operación del mismo tipo y nombre de la revisión congelada más
  reciente (D-25; si no hay, se dice), sector con la búsqueda pendiente y perfil no resuelto por la
  rejilla.

Se prueba a mano, contra cálculos celda a celda en Python con superficies aleatorias, con la ladera
y el relleno ×40 de CE-013-07 y en pasos (partir en bandas no cambia las cifras). Ninguna cifra es
NaN ni infinita (RF-013-17): lo que no se puede dar es ``None`` o un aviso.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

report = import_geoblender("design.report")
compose = import_geoblender("design.compose")
benching = import_geoblender("design.benching")
envelopes = import_geoblender("design.envelopes")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
i18n = import_geoblender("core.i18n")

THIN = i18n.THIN_SPACE
E = 0.25
"""Un espesor mínimo exacto en binario para los casos a mano."""
FACE_TOLERANCE_DEG = 1.0
RATIO = 2.0


def grid_of(rows: int, cols: int, dx: float = 1.0, dy: float | None = None) -> Any:
    """Una rejilla absoluta de ``rows × cols`` celdas de ``dx × dy`` m."""
    return dfx.gis.Grid(699_700.0, 4_399_700.0, dx, dx if dy is None else dy, cols, rows)


def run(start: Any, design: Any, geometry: Any, allowed: Any = None, **options: Any) -> Any:
    """El informe (último paso de ``report_steps``) con valores de prueba por defecto."""
    options.setdefault("min_thickness_m", E)
    options.setdefault("face_deg", 60.0)
    options.setdefault("face_tolerance_deg", FACE_TOLERANCE_DEG)
    options.setdefault("warning_ratio", RATIO)
    admitted = np.ones(np.shape(start), dtype=bool) if allowed is None else allowed
    return list(report.report_steps(start, design, geometry, admitted, **options))[-1].result


def brute_force_incline(design: np.ndarray, geometry: Any) -> np.ndarray:
    """La inclinación (°) de cada celda: la mayor a sus 8 vecinos con datos, en Python; ``NaN`` sin
    ningún vecino con dato."""
    rows, cols = design.shape
    out = np.full(design.shape, np.nan)
    for row in range(rows):
        for col in range(cols):
            best = None
            for d_row in (-1, 0, 1):
                for d_col in (-1, 0, 1):
                    other_row, other_col = row + d_row, col + d_col
                    if (d_row, d_col) == (0, 0) or not (0 <= other_row < rows
                                                         and 0 <= other_col < cols):
                        continue
                    a, b = float(design[row, col]), float(design[other_row, other_col])
                    if not (math.isfinite(a) and math.isfinite(b)):
                        continue
                    distance = math.hypot(d_col * geometry.dx, d_row * geometry.dy)
                    best = abs(a - b) / distance if best is None else max(
                        best, abs(a - b) / distance)
            if best is not None:
                out[row, col] = math.degrees(math.atan(best))
    return out


def brute_force_edge(design: np.ndarray, moved: np.ndarray, allowed: np.ndarray
                     ) -> tuple[float, int]:
    """El mayor escalón (m) entre una celda con movimiento y una vecina de lado no admitida, y
    cuántas celdas con movimiento tocan una no admitida, en Python."""
    rows, cols = design.shape
    step, touching = 0.0, 0
    for row in range(rows):
        for col in range(cols):
            if not moved[row, col]:
                continue
            touches = False
            for d_row, d_col in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                other_row, other_col = row + d_row, col + d_col
                if not (0 <= other_row < rows and 0 <= other_col < cols):
                    continue
                if allowed[other_row, other_col]:
                    continue
                touches = True
                jump = abs(float(design[row, col]) - float(design[other_row, other_col]))
                if math.isfinite(jump):
                    step = max(step, jump)
            touching += touches
    return step, touching


class VolumesByHandTest(unittest.TestCase):
    """RF-013-30: el desmonte, el terraplén y el área con movimiento con el espesor mínimo."""

    def setUp(self) -> None:
        self.geometry = grid_of(3, 3, 2.0, 3.0)  # celdas de 6 m²
        self.start = np.full((3, 3), 10.0)
        self.start[2, 1] = np.nan
        self.design = np.array([[9.0, 9.75, 9.5],
                                [11.0, 10.25, 10.5],
                                [np.nan, 10.0, 10.0]])

    def test_volumes_and_areas_use_the_cell_area(self) -> None:
        """Se cuenta con todo el espesor lo que pasa del mínimo (0,25 m): el corte de 1,0 y 0,5 m
        (9 m³), el relleno de 1,0 y 0,5 m (9 m³) y 4 celdas con movimiento (24 m²); las diferencias
        de 0,25 m justas (el umbral es estricto) y las celdas sin dato no cuentan."""
        found = run(self.start, self.design, self.geometry)
        self.assertEqual(found.cut_m3, 9.0)
        self.assertEqual(found.fill_m3, 9.0)
        self.assertEqual((found.cut_cells, found.fill_cells, found.moved_cells), (2, 2, 4))
        self.assertEqual(found.moved_area_m2, 24.0)
        self.assertEqual(found.nodata_cells, 2)
        self.assertEqual(found.nodata_area_m2, 12.0)
        self.assertEqual(found.min_thickness_m, E)

    def test_a_zero_minimum_counts_every_difference(self) -> None:
        """Con espesor mínimo 0 cuenta toda diferencia (las dos de 0,25 m entran)."""
        found = run(self.start, self.design, self.geometry, min_thickness_m=0.0)
        self.assertEqual((found.cut_cells, found.fill_cells), (3, 3))
        self.assertEqual(found.cut_m3, (1.0 + 0.25 + 0.5) * 6.0)
        self.assertEqual(found.fill_m3, (1.0 + 0.25 + 0.5) * 6.0)

    def test_volumes_function_is_the_one_of_the_report(self) -> None:
        """:func:`volumes` (la de las cifras de una envolvente) da lo mismo que el informe."""
        found = report.volumes(self.start, self.design, self.geometry, E)
        full = run(self.start, self.design, self.geometry)
        self.assertEqual((found.cut_m3, found.fill_m3, found.cut_cells, found.fill_cells),
                         (full.cut_m3, full.fill_m3, full.cut_cells, full.fill_cells))
        self.assertEqual((found.moved_area_m2, found.nodata_cells, found.nodata_area_m2),
                         (full.moved_area_m2, full.nodata_cells, full.nodata_area_m2))

    def test_moved_cells_never_counts_a_cell_without_finite_data(self) -> None:
        """Una celda sin dato (``NaN``) o con una cota infinita en alguna de las dos superficies no
        tiene movimiento (RF-013-17): sin comprobarlo, ``|∞ − z| > e`` lo contaría."""
        start = np.array([[1.0, 1.0, 1.0, np.nan, np.inf]])
        design = np.array([[np.inf, -np.inf, np.nan, 5.0, 5.0]])
        self.assertEqual(report.moved_cells(start, design, E).tolist(), [[False] * 5])

    def test_moved_cells_is_the_mask_of_the_report(self) -> None:
        """:func:`moved_cells` es la máscara con movimiento que usa el informe y que pide
        ``berms_steps`` (``moved``): cuenta lo mismo que las celdas con movimiento del informe."""
        mask = report.moved_cells(self.start, self.design, E)
        self.assertEqual(mask.dtype, np.bool_)
        self.assertEqual(int(mask.sum()), 4)
        self.assertEqual(mask.tolist(), [[True, False, True], [True, False, True],
                                         [False, False, False]])

    def test_random_surfaces_match_the_12th_spec_arithmetic(self) -> None:
        """Contra el cálculo de la 012 en Python (``d = partida − final``; corte si ``d > e``,
        relleno si ``−d > e``, solo con dato en las dos): cifras iguales a ≤ 10⁻¹² relativo."""
        rng = np.random.default_rng(12)
        geometry = grid_of(23, 31, 2.0)
        for case in range(10):
            start = 100.0 + rng.normal(0.0, 3.0, geometry.shape)
            design = start + rng.normal(0.0, 0.2, geometry.shape)
            start[rng.random(geometry.shape) < 0.05] = np.nan
            design[rng.random(geometry.shape) < 0.05] = np.nan
            e = float(rng.choice([0.0, 0.02, 0.1]))
            cut = fill = 0.0
            cells = 0
            for a, b in zip(start.ravel().tolist(), design.ravel().tolist(), strict=True):
                if math.isfinite(a) and math.isfinite(b):
                    if a - b > e:
                        cut += a - b
                        cells += 1
                    elif b - a > e:
                        fill += b - a
                        cells += 1
            with self.subTest(case=case):
                found = run(start, design, geometry, min_thickness_m=e)
                self.assertAlmostEqual(found.cut_m3 / (cut * 4.0), 1.0, delta=1e-12)
                self.assertAlmostEqual(found.fill_m3 / (fill * 4.0), 1.0, delta=1e-12)
                self.assertEqual(found.moved_cells, cells)
                self.assertEqual(found.moved_area_m2, cells * 4.0)


class InclineTest(unittest.TestCase):
    """RF-013-30, D-13: la inclinación de una celda es la mayor a sus 8 vecinos."""

    def test_a_plane_has_the_slope_of_its_steepest_direction(self) -> None:
        """Un plano hacia el este de pendiente 0,5 (exacta en binario) da 26,565° en toda celda
        (p90, p99 y máxima iguales); uno en diagonal ``0,25·(x + y)`` da ``atan(√2/4)`` = 19,47°,
        porque el vecino diagonal es el más empinado (la distancia es √2)."""
        geometry = grid_of(12, 20)
        x, y = np.meshgrid(np.arange(20.0), np.arange(12.0))
        for name, surface, tangent in (("este", 0.5 * x, 0.5),
                                       ("diagonal", 0.25 * (x + y), math.sqrt(2.0) / 4.0)):
            with self.subTest(plano=name):
                found = run(surface - 1.0, surface, geometry)
                expected = math.degrees(math.atan(tangent))
                self.assertEqual(found.moved_cells, 240)
                for value in (found.slope_p90_deg, found.slope_p99_deg, found.slope_max_deg):
                    self.assertAlmostEqual(value, expected, delta=1e-12)

    def test_random_surfaces_match_the_cell_by_cell_calculation(self) -> None:
        """Con superficies aleatorias con huecos, celdas no cuadradas y movimiento irregular, el
        p90, el p99 y el máximo son los de ``np.percentile`` de las inclinaciones de las celdas con
        movimiento calculadas celda a celda (≤ 10⁻¹² relativo), y el lugar es el de la primera
        celda del máximo."""
        rng = np.random.default_rng(31)
        for case in range(12):
            shape = (int(rng.integers(3, 22)), int(rng.integers(3, 22)))
            geometry = grid_of(*shape, 0.5, 0.75)
            design = 50.0 + np.cumsum(rng.normal(0.0, 0.4, shape), axis=1) + rng.normal(0, 0.3, shape)
            design[rng.random(shape) < 0.06] = np.nan
            start = design - np.where(rng.random(shape) < 0.6, 1.0, 0.0)
            start[rng.random(shape) < 0.04] = np.nan
            inclines = brute_force_incline(design, geometry)
            moved = report.moved_cells(start, design, E)
            picked = inclines[moved & np.isfinite(inclines)]
            with self.subTest(case=case):
                found = run(start, design, geometry)
                if picked.size == 0:
                    self.assertIsNone(found.slope_max_deg)
                    continue
                p90, p99 = np.percentile(picked, [90, 99])
                self.assertAlmostEqual(found.slope_p90_deg / p90, 1.0, delta=1e-12)
                self.assertAlmostEqual(found.slope_p99_deg / p99, 1.0, delta=1e-12)
                self.assertAlmostEqual(found.slope_max_deg / float(picked.max()), 1.0, delta=1e-12)
                masked = np.where(moved & np.isfinite(inclines), inclines, -1.0)
                row, col = np.unravel_index(int(np.argmax(masked)), shape)
                self.assertEqual((found.slope_max_at.row, found.slope_max_at.col),
                                 (int(row), int(col)))

    def test_the_first_of_the_equal_maxima_gives_the_place_in_any_band(self) -> None:
        """Con la inclinación máxima repetida en muchas celdas (un plano), el lugar es el de la
        primera de norte a sur y de oeste a este, sea cual sea el tamaño de la banda."""
        geometry = grid_of(9, 7)
        surface = 0.5 * np.meshgrid(np.arange(7.0), np.arange(9.0))[0]
        for per_unit in (7, 14, 10**9):
            with self.subTest(cells_per_unit=per_unit):
                found = run(surface - 1.0, surface, geometry, cells_per_unit=per_unit)
                self.assertEqual((found.slope_max_at.row, found.slope_max_at.col), (0, 0))

    def test_an_infinite_neighbour_is_no_data_not_a_wall(self) -> None:
        """Una vecina con cota infinita es una vecina sin dato (no una pared de 90°): la
        inclinación de la celda con movimiento es la que dan sus vecinas con dato."""
        geometry = grid_of(3, 3)
        design = np.zeros((3, 3))
        design[1, 2] = np.inf
        start = design.copy()
        start[1, 1] = 5.0  # solo la celda central tiene movimiento (relleno de 5 m)
        design[1, 1] = 10.0
        found = run(start, design, geometry)
        self.assertEqual(found.moved_cells, 1)
        self.assertAlmostEqual(found.slope_max_deg, math.degrees(math.atan(10.0)), delta=1e-12)

    def test_the_place_of_the_maximum_is_absolute_float64(self) -> None:
        """El lugar del máximo son las coordenadas absolutas del centro de la celda en float64
        (en float32 se perdería el cuarto de metro del norte, 4,4 Mm): una sola celda con
        movimiento, con vecinas sin movimiento muy distintas, es la del máximo; solo cuentan las
        celdas con movimiento, pero la inclinación se mide contra todas sus vecinas."""
        geometry = grid_of(8, 9, 0.25, 0.5)
        design = np.zeros((8, 9))
        design[3, 5] = 10.0
        start = design.copy()
        start[3, 5] = 5.0
        found = run(start, design, geometry)
        self.assertEqual(found.moved_cells, 1)
        self.assertAlmostEqual(found.slope_max_deg, math.degrees(math.atan(10.0 / 0.25)),
                               delta=1e-12)
        place = found.slope_max_at
        self.assertEqual((place.row, place.col), (3, 5))
        self.assertEqual(place.x, 699_700.0 + 5.5 * 0.25)
        self.assertEqual(place.y, 4_399_700.0 - 3.5 * 0.5)
        self.assertEqual(place.y, 4_399_698.25)
        self.assertNotEqual(float(np.float32(place.y)), place.y)
        self.assertEqual(found.slope_p90_deg, found.slope_p99_deg)
        self.assertEqual(found.slope_p99_deg, found.slope_max_deg)

    def test_no_movement_gives_no_inclines_and_says_so(self) -> None:
        """Sin ninguna celda con movimiento no hay inclinación que dar: ``None`` (nunca 0 ni NaN,
        RF-013-17) y un aviso lo dice."""
        geometry = grid_of(6, 6)
        surface = np.add.outer(np.arange(6.0), np.arange(6.0))
        found = run(surface, surface + E, geometry)
        self.assertEqual((found.cut_m3, found.fill_m3, found.moved_cells), (0.0, 0.0, 0))
        self.assertIsNone(found.slope_p90_deg)
        self.assertIsNone(found.slope_p99_deg)
        self.assertIsNone(found.slope_max_deg)
        self.assertIsNone(found.slope_max_at)
        self.assertIn("des.no_movement", [notice.code for notice in found.notices])

    def test_a_moved_cell_with_no_neighbour_data_is_not_counted(self) -> None:
        """Una celda con movimiento sin ningún vecino con dato no tiene inclinación: no entra en
        las cifras (ni las vuelve NaN)."""
        geometry = grid_of(3, 3)
        design = np.full((3, 3), np.nan)
        design[1, 1] = 5.0
        start = design.copy()
        start[1, 1] = 4.0
        found = run(start, design, geometry)
        self.assertEqual(found.moved_cells, 1)
        self.assertIsNone(found.slope_max_deg)


class EdgeStepTest(unittest.TestCase):
    """RF-013-30, D-9: el salto en el borde de lo prohibido."""

    def test_step_between_a_moved_cell_and_a_held_neighbour(self) -> None:
        """Un corte de 3 m junto a una celda no admitida deja un escalón de 3 m; otro de 1 m, de
        1 m; uno que solo la toca en diagonal, nada, y una celda admitida sin movimiento, aunque
        el terreno natural tenga un desnivel, tampoco: el salto es lo que crea el diseño."""
        geometry = grid_of(5, 6)
        start = np.full((5, 6), 100.0)
        start[4, 1] = 104.0  # desnivel natural contra la celda admitida (4, 2): no es un salto
        design = start.copy()
        allowed = np.ones((5, 6), dtype=bool)
        allowed[:, 0] = False  # columna 0 no admitida
        allowed[3, 3] = False  # una celda suelta no admitida
        design[2, 1] = 97.0  # junto a (2, 0) no admitida: escalón 3
        design[1, 1] = 99.0  # junto a (1, 0): escalón 1
        design[2, 2] = 90.0  # solo toca la celda suelta (3, 3) en diagonal: no es un borde
        found = run(start, design, geometry, allowed)
        self.assertEqual(found.edge_step_max_m, 3.0)
        self.assertEqual(found.edge_cells, 2)
        self.assertEqual(found.moved_cells, 3)

    def test_no_border_gives_zero(self) -> None:
        """Si ninguna celda con movimiento toca una no admitida, el salto es 0,0 m (no hay
        escalón creado) y ninguna toca el borde."""
        geometry = grid_of(5, 5)
        start = np.full((5, 5), 100.0)
        design = start.copy()
        design[2, 2] = 90.0
        allowed = np.ones((5, 5), dtype=bool)
        found = run(start, design, geometry, allowed)
        self.assertEqual(found.edge_step_max_m, 0.0)
        self.assertEqual(found.edge_cells, 0)

    def test_random_masks_match_the_cell_by_cell_calculation(self) -> None:
        rng = np.random.default_rng(77)
        for case in range(20):
            shape = (int(rng.integers(2, 18)), int(rng.integers(2, 18)))
            geometry = grid_of(*shape)
            start = 100.0 + rng.normal(0.0, 2.0, shape)
            allowed = rng.random(shape) < 0.7
            design = start + np.where(allowed & (rng.random(shape) < 0.5),
                                      rng.normal(0.0, 2.0, shape), 0.0)
            design[rng.random(shape) < 0.05] = np.nan
            start[rng.random(shape) < 0.03] = np.nan
            moved = report.moved_cells(start, design, E)
            step, touching = brute_force_edge(design, moved, allowed)
            with self.subTest(case=case):
                found = run(start, design, geometry, allowed)
                self.assertEqual(found.edge_step_max_m, step)
                self.assertEqual(found.edge_cells, touching)


def codes(found: Any) -> list[str]:
    return [notice.code for notice in found.notices]


class WarningsTest(unittest.TestCase):
    """RF-013-30: los avisos."""

    def test_movement_on_the_grid_border_warns(self) -> None:
        """Movimiento en la primera o última fila o columna avisa con las celdas y el área; en el
        interior, no."""
        geometry = grid_of(10, 10, 2.0)
        start = np.zeros((10, 10))
        inside = start.copy()
        inside[2:8, 2:8] = 3.0
        self.assertNotIn("des.edge_movement", codes(run(start, inside, geometry)))
        for row, col in ((0, 4), (9, 4), (4, 0), (4, 9)):
            with self.subTest(celda=(row, col)):
                edge = inside.copy()
                edge[row, col] = 3.0
                found = run(start, edge, geometry)
                (notice,) = [n for n in found.notices if n.code == "des.edge_movement"]
                self.assertEqual(dict(notice.values), {"cells": 1, "area": 4.0})
                self.assertEqual(notice.severity, "warning")

    def test_the_corners_of_the_grid_count_once(self) -> None:
        """Las celdas de las esquinas se cuentan una vez: con todo en movimiento, el borde de una
        rejilla de 10 × 12 son 40 celdas (160 m²); en una de 2 filas o de 2 columnas, todas."""
        for shape, expected in (((10, 12), 40), ((2, 5), 10), ((7, 2), 14), ((1, 4), 4)):
            with self.subTest(forma=shape):
                geometry = grid_of(*shape, 2.0)
                start = np.zeros(shape)
                found = run(start, start + 3.0, geometry)
                (notice,) = [n for n in found.notices if n.code == "des.edge_movement"]
                self.assertEqual(dict(notice.values), {"cells": expected, "area": expected * 4.0})

    def test_slope_over_the_face_warns_with_the_tolerance(self) -> None:
        """Una inclinación por encima de la cara más la tolerancia avisa (cuántas celdas, la peor,
        su límite y su lugar); justo en el límite, no."""
        geometry = grid_of(8, 8)
        x = np.meshgrid(np.arange(8.0), np.arange(8.0))[0]
        for deg, warns in ((60.0, False), (61.0 - 1e-9, False), (61.5, True), (80.0, True)):
            with self.subTest(grados=deg):
                design = math.tan(math.radians(deg)) * x  # cada celda sube exactamente ``deg``
                found = run(design - 1.0, design, geometry, face_deg=60.0,
                            face_tolerance_deg=1.0)
                if not warns:
                    self.assertNotIn("des.slope_over_face", codes(found))
                    continue
                (notice,) = [n for n in found.notices if n.code == "des.slope_over_face"]
                values = dict(notice.values)
                self.assertEqual(values["cells"], 64)
                self.assertAlmostEqual(values["max"], deg, delta=1e-9)
                self.assertEqual(values["limit"], 61.0)
                self.assertEqual(notice.severity, "warning")

    def test_exactly_the_limit_does_not_warn(self) -> None:
        """Una inclinación exactamente igual a la cara más la tolerancia (45° con tangente 1 y
        tolerancia 0) no pasa de ella."""
        geometry = grid_of(5, 5)
        x = np.meshgrid(np.arange(5.0), np.arange(5.0))[0]
        found = run(x - 1.0, x, geometry, face_deg=45.0, face_tolerance_deg=0.0)
        self.assertEqual(found.slope_max_deg, 45.0)
        self.assertNotIn("des.slope_over_face", codes(found))

    def test_the_worst_offender_is_the_steepest_of_all_the_bands(self) -> None:
        """La celda que se nombra en el aviso es la que más pasa de todas, no la de la primera
        banda: con la rejilla partida fila a fila y las filas cada vez más empinadas, la peor está
        en el sur (y, empatada con su pareja, la primera de norte a sur)."""
        geometry = grid_of(6, 6)
        rows = np.meshgrid(np.arange(6.0), np.arange(6.0))[1]
        design = 0.1 * rows ** 2
        found = run(design - 1.0, design, geometry, face_deg=1.0, face_tolerance_deg=0.0,
                    cells_per_unit=6)
        (notice,) = [n for n in found.notices if n.code == "des.slope_over_face"]
        values = dict(notice.values)
        self.assertEqual(values["cells"], 36)
        self.assertAlmostEqual(values["max"], math.degrees(math.atan(0.9)), delta=1e-9)
        place = found.slope_max_at
        self.assertEqual((place.row, place.col), (4, 0))
        self.assertEqual((values["x"], values["y"]), (place.x, place.y))

    def test_the_face_can_be_a_map_by_cell(self) -> None:
        """El perfil de cada sector tiene su cara: con un mapa, cada celda se compara con la suya
        (``NaN`` donde no hay escalonado, que no avisa)."""
        geometry = grid_of(6, 12)
        x = np.meshgrid(np.arange(12.0), np.arange(6.0))[0]
        design = math.tan(math.radians(50.0)) * x  # 50° en todas partes
        face = np.full((6, 12), 45.0)
        face[:, 6:] = 60.0  # la mitad este admite 60°: no pasa
        face[0, :] = np.nan  # una fila sin escalonado
        found = run(design - 1.0, design, geometry, face_deg=face, face_tolerance_deg=1.0)
        (notice,) = [n for n in found.notices if n.code == "des.slope_over_face"]
        offenders = dict(notice.values)["cells"]
        self.assertEqual(offenders, 5 * 6)  # 5 filas × 6 columnas con cara de 45° + 1° < 50°
        quiet = run(design - 1.0, design, geometry, face_deg=np.full((6, 12), 60.0))
        self.assertNotIn("des.slope_over_face", codes(quiet))

    def test_magnitude_against_the_frozen_revision(self) -> None:
        """CE-013-07, error 66: un relleno de 716.000 m³ frente a los 17.607 m³ de la revisión
        congelada (×40,7) avisa con el umbral (2,0); el desmonte, que no lo supera, no."""
        geometry = grid_of(100, 100, 2.0)
        start = np.zeros((100, 100))
        design = start + 17.9  # 17,9 m × 40.000 m² = 716.000 m³ de relleno
        previous = report.Previous("diseno_1", "V01.r1", cut_m3=100.0,
                                   fill_m3=dfx.FILL_PREVIOUS_M3)
        found = run(start, design, geometry, previous=previous, operation="diseno_1")
        self.assertAlmostEqual(found.fill_m3, dfx.FILL_CURRENT_M3, delta=1e-6)
        (notice,) = [n for n in found.notices if n.code == "des.magnitude_fill"]
        values = dict(notice.values)
        self.assertEqual((values["current"], values["previous"]), (716_000, 17_607))
        self.assertAlmostEqual(values["ratio"], dfx.FILL_RATIO, delta=1e-9)
        self.assertEqual((values["threshold"], values["revision"]), (RATIO, "V01.r1"))
        self.assertNotIn("des.magnitude_cut", codes(found))
        self.assertNotIn("des.magnitude_no_reference", codes(found))
        self.assertIn(f"716{THIN}000", notice.text("es"))
        self.assertIn(f"17{THIN}607", notice.text("es"))
        self.assertIn("40,7", notice.text("es"))
        self.assertIn("40.7", notice.text("en"))

    def test_the_cut_also_warns_and_the_threshold_is_strict(self) -> None:
        """El desmonte avisa igual que el terraplén; exactamente el umbral no avisa (supera en
        MÁS de ese número de veces); y con un anterior de 0 m³ no hay razón que dar."""
        geometry = grid_of(10, 10)
        start = np.zeros((10, 10))
        design = start - 1.0  # 100 m³ de desmonte
        for previous_cut, warns in ((50.0, False), (49.0, True), (0.0, False)):
            with self.subTest(anterior=previous_cut):
                previous = report.Previous("d", "V01.r2", previous_cut, 0.0)
                found = run(start, design, geometry, previous=previous, operation="d")
                self.assertEqual("des.magnitude_cut" in codes(found), warns)
                self.assertNotIn("des.magnitude_fill", codes(found))

    def test_without_a_frozen_revision_the_warning_is_not_given_and_it_says_so(self) -> None:
        """D-25: sin operación del mismo tipo y nombre en una revisión congelada, no hay aviso
        de magnitud y una nota lo dice (no se calla)."""
        geometry = grid_of(10, 10)
        start = np.zeros((10, 10))
        found = run(start, start - 1.0, geometry, previous=None, operation="diseno_1")
        self.assertIn("des.magnitude_no_reference", codes(found))
        self.assertNotIn("des.magnitude_cut", codes(found))
        (notice,) = [n for n in found.notices if n.code == "des.magnitude_no_reference"]
        self.assertEqual(notice.severity, "note")
        self.assertIn("diseno_1", notice.text("es"))

    def test_pending_sectors_and_unresolved_profiles_are_marked(self) -> None:
        """Un aviso por cada sector con la búsqueda pendiente (el de la T05) y por cada perfil
        que la rejilla no resuelve (el de la T02), con los valores del perfil."""
        geometry = grid_of(4, 4, 2.0)
        start = np.zeros((4, 4))
        narrow = model.BenchProfile("estrecho", "ESTRECHO_5_70_0_5", 5.0, 80.0, 0.5, 100.0)
        wide = model.BenchProfile("ancho", "ANCHO_10_45_6", 10.0, 45.0, 6.0, 100.0)
        self.assertIsNotNone(narrow.unresolved_by(geometry))
        self.assertIsNone(wide.unresolved_by(geometry))
        found = run(start, start - 1.0, geometry, pending=("Sector 1", "Sector 2"),
                    profiles=(narrow, wide))
        marks = [n for n in found.notices if n.code == "des.sector_pending_mark"]
        self.assertEqual([dict(n.values)["sector"] for n in marks], ["Sector 1", "Sector 2"])
        (unresolved,) = [n for n in found.notices if n.code == "des.profile_unresolved"]
        self.assertEqual(dict(unresolved.values)["profile"], "ESTRECHO_5_70_0_5")
        self.assertEqual(dict(unresolved.values), {"profile": "ESTRECHO_5_70_0_5", "face": 0.88,
                                                   "berm": 0.5, "step": 2.0})
        self.assertIn("ESTRECHO_5_70_0_5", unresolved.text("es"))
        self.assertIn("0,88", unresolved.text("es"))
        self.assertIn("0.88", unresolved.text("en"))

    def test_every_notice_reads_in_both_languages_without_gaps(self) -> None:
        """Todos los avisos y notas del informe están en el catálogo, con el texto de los dos
        idiomas sin huecos («?») ni marcadores sin sustituir."""
        geometry = grid_of(10, 10, 2.0)
        start = np.zeros((10, 10))
        design = start.copy()
        design[0:9, 0:3] = 20.0
        previous = report.Previous("d", "V01.r1", 1.0, 1.0)
        narrow = model.BenchProfile("estrecho", "ESTRECHO_5_70_0_5", 5.0, 80.0, 0.5, 100.0)
        lowering = report.Lowering(cells=531, drop_m=0.565, slope_deg=20.83,
                                   sectors=("Sector 2",))
        found = run(start, design, geometry, previous=previous, operation="d",
                    pending=("Sector 1",), profiles=(narrow,), face_deg=45.0, lowering=lowering)
        seen = set(codes(found))
        self.assertTrue({"des.edge_movement", "des.slope_over_face", "des.magnitude_fill",
                         "des.sector_pending_mark", "des.profile_unresolved",
                         "des.regularization_lowered"} <= seen)
        for notice in found.notices:
            for language in ("es", "en"):
                text = notice.text(language)
                self.assertNotIn("?", text, (notice.code, language))
                self.assertNotIn("{", text, (notice.code, language))
                self.assertNotIn("nan", text.lower(), (notice.code, language))
        self.assertEqual(found.warnings("es"), tuple(n.text("es") for n in found.notices
                                                     if n.severity == "warning"))
        self.assertEqual(found.lines("en"), tuple(n.text("en") for n in found.notices))


class RegularizationNoticeTest(unittest.TestCase):
    """RF-013-26, RF-013-30 (spec 0.4; F-1): el aviso de que la regularización entre sectores bajó
    la envolvente más que la tolerancia, con el número de celdas y el descenso máximo (m)."""

    def setUp(self) -> None:
        self.geometry = grid_of(4, 4, 2.0)
        self.start = np.zeros((4, 4))
        self.design = self.start - 1.0
        self.lowering = report.Lowering(cells=531, drop_m=0.565, slope_deg=20.83,
                                        sectors=("Sector 2", "Sector 3"))

    def notice(self, found: Any) -> Any:
        (notice,) = [n for n in found.notices if n.code == "des.regularization_lowered"]
        return notice

    def test_without_a_lowering_or_with_no_cells_there_is_no_notice(self) -> None:
        """RF-013-30: sin regularización bajada (``None``, el valor por defecto) o con 0 celdas, el
        informe no lleva el aviso: es el de siempre."""
        plain = run(self.start, self.design, self.geometry)
        self.assertNotIn("des.regularization_lowered", codes(plain))
        none = run(self.start, self.design, self.geometry, lowering=None)
        zero = run(self.start, self.design, self.geometry, lowering=report.Lowering(
            cells=0, drop_m=0.0, slope_deg=20.83, sectors=()))
        self.assertEqual(codes(none), codes(plain))
        self.assertEqual(codes(zero), codes(plain))

    def test_the_notice_carries_the_cells_the_drop_the_slope_and_the_sectors(self) -> None:
        """RF-013-30: con celdas bajadas, un aviso (``warning``) con su recuento, el descenso
        máximo (m), el talud con que se regularizó (°) y los sectores donde bajó, sin redondear;
        entra en los avisos del informe (``warnings``) y en sus líneas."""
        found = run(self.start, self.design, self.geometry, lowering=self.lowering)
        notice = self.notice(found)
        self.assertEqual(notice.severity, "warning")
        self.assertEqual(dict(notice.values), {"cells": 531, "drop": 0.565, "slope": 20.83,
                                               "sectors": "Sector 2, Sector 3"})
        self.assertIn(notice.text("es"), found.warnings("es"))
        self.assertIn(notice.text("en"), found.lines("en"))

    def test_the_notice_reads_in_both_languages_and_says_what_to_do(self) -> None:
        """RF-013-30, principio 10: el texto, en español y en inglés, dice las celdas, el descenso
        con su decimal, el talud y los sectores, que el escalonado puede quedar por debajo de la
        envolvente registrada y qué hacer (calcular la envolvente con el talud de cada sector o
        subir el talud impuesto), sin huecos ni marcadores sin sustituir."""
        notice = self.notice(run(self.start, self.design, self.geometry, lowering=self.lowering))
        es, en = notice.text("es"), notice.text("en")
        for text in (es, en):
            self.assertNotIn("?", text)
            self.assertNotIn("{", text)
            self.assertIn("531", text)
            self.assertIn("Sector 2, Sector 3", text)
            self.assertIn("20,8" if text is es else "20.8", text)
        self.assertIn("0,565", es)
        self.assertIn("0.565", en)
        self.assertIn("Talud de cada sector", es)
        self.assertIn("Slope of each sector", en)
        self.assertIn("por debajo de la envolvente registrada", es)
        self.assertIn("below the recorded envelope", en)
        self.assertIn("talud general máximo impuesto", es)
        self.assertIn("maximum general slope imposed", en)

    def test_it_comes_after_the_slope_notice_and_before_the_magnitude_ones(self) -> None:
        """RF-013-30: en el orden en que se enseñan, el aviso de la regularización va tras el de
        la inclinación pasada de la cara y antes de los de magnitud y los de los sectores
        pendientes y los perfiles."""
        design = self.start.copy()
        design[0:3, 0:2] = 20.0
        previous = report.Previous("d", "V01.r1", 1.0, 1.0)
        found = run(self.start, design, self.geometry, previous=previous, operation="d",
                    pending=("Sector 1",), face_deg=45.0, lowering=self.lowering)
        order = codes(found)
        self.assertLess(order.index("des.slope_over_face"),
                        order.index("des.regularization_lowered"))
        self.assertLess(order.index("des.regularization_lowered"),
                        order.index("des.magnitude_fill"))
        self.assertLess(order.index("des.regularization_lowered"),
                        order.index("des.sector_pending_mark"))

    def test_a_lowering_without_sectors_says_so_with_a_dash(self) -> None:
        """RF-013-30: si no se sabe en qué sectores bajó (las celdas bajadas no tienen sector), el
        texto lo dice con «—», no con un hueco."""
        none = report.Lowering(cells=3, drop_m=1.5, slope_deg=30.0, sectors=())
        notice = self.notice(run(self.start, self.design, self.geometry, lowering=none))
        self.assertEqual(notice.values["sectors"], "—")
        self.assertIn("—", notice.text("es"))
        self.assertNotIn("?", notice.text("es"))

    def test_a_bad_lowering_is_a_program_error(self) -> None:
        """Un descenso que no es finito y no negativo, unas celdas negativas, un talud que no es
        finito o que no es un ``Lowering`` son ``ValueError`` al llamar (RF-013-17: ninguna cifra
        NaN ni infinita)."""
        for changes in ({"cells": -1}, {"drop_m": math.nan}, {"drop_m": -0.1},
                        {"drop_m": math.inf}, {"slope_deg": math.nan}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                report.Lowering(**{"cells": 1, "drop_m": 1.0, "slope_deg": 30.0, "sectors": (),
                                   **changes})
        with self.assertRaises(ValueError):
            run(self.start, self.design, self.geometry, lowering=(531, 0.565))

    def test_the_report_figures_do_not_change(self) -> None:
        """RF-013-30: el aviso no cambia ninguna cifra del informe: las mismas con y sin él."""
        design = self.start.copy()
        design[0:3, 0:2] = 20.0
        plain = run(self.start, design, self.geometry)
        warned = run(self.start, design, self.geometry, lowering=self.lowering)
        for name in ("cut_m3", "fill_m3", "cut_cells", "fill_cells", "moved_area_m2",
                     "nodata_cells", "nodata_area_m2", "min_thickness_m", "slope_p90_deg",
                     "slope_p99_deg", "slope_max_deg", "slope_max_at", "edge_step_max_m",
                     "edge_cells"):
            self.assertEqual(getattr(plain, name), getattr(warned, name), name)
        self.assertEqual([code for code in codes(warned) if code != "des.regularization_lowered"],
                         codes(plain), "los demás avisos, los mismos y en el mismo orden")
        self.assertEqual(len(codes(warned)), len(codes(plain)) + 1)


class CE013007HillsideTest(unittest.TestCase):
    """CE-013-07 (errores 10, 17, 56 y 66): las semillas en toda la ladera mueven hasta el borde de
    la rejilla; el dominio acotado lo evita pero deja un salto."""

    def setUp(self) -> None:
        self.case = dfx.hillside_case()
        self.terrain = self.case.terrain()
        seeds = self.case.seeds() + 25.0  # una cresta 25 m sobre el terreno en las 60 filas del norte
        slope = envelopes.constant_slope(35.0)
        envelope = list(envelopes.chamfer_steps(seeds, self.case.grid, slope, "down",
                                                name="ladera"))[-1].result.grid
        tan_face = math.tan(math.radians(60.0))
        stairs = benching.bench_fill(envelope, 10.0, tan_face, 6.0, 100.0)
        self.stairs = stairs

    def test_a_whole_hillside_of_seeds_moves_the_grid_border(self) -> None:
        """Sin acotar el dominio, el relleno llega a la primera fila: aviso de movimiento en el
        borde de la rejilla con su área, y salto 0 (nada prohibido)."""
        allowed = np.ones(self.terrain.shape, dtype=bool)
        design = compose.compose(self.terrain, self.stairs, allowed, "fill")
        found = run(self.terrain, design, self.case.grid, allowed)
        self.assertGreater(found.fill_m3, 0.0)
        self.assertIn("des.edge_movement", codes(found))
        self.assertEqual(found.edge_step_max_m, 0.0)

    def test_a_bounded_domain_leaves_a_step_instead(self) -> None:
        """Acotado al dominio de 80 × 80 celdas, ningún movimiento llega al borde de la rejilla
        pero el relleno acaba en pared contra lo no admitido: un salto informado (D-9)."""
        allowed = self.case.domain()
        design = compose.compose(self.terrain, self.stairs, allowed, "fill")
        found = run(self.terrain, design, self.case.grid, allowed)
        self.assertGreater(found.fill_m3, 0.0)
        self.assertNotIn("des.edge_movement", codes(found))
        self.assertGreater(found.edge_step_max_m, 1.0)
        self.assertGreater(found.edge_cells, 0)


class StepsAndFiguresTest(unittest.TestCase):
    """Por pasos, sin tocar las entradas y sin cifras NaN ni infinitas."""

    def setUp(self) -> None:
        rng = np.random.default_rng(5)
        self.geometry = grid_of(61, 53, 2.0)
        self.start = 120.0 + np.cumsum(rng.normal(0.0, 0.3, self.geometry.shape), axis=0)
        self.allowed = rng.random(self.geometry.shape) < 0.8
        change = np.where(self.allowed & (rng.random(self.geometry.shape) < 0.5),
                          rng.normal(0.0, 3.0, self.geometry.shape), 0.0)
        self.design = self.start + change

    def test_the_unit_size_does_not_change_the_figures(self) -> None:
        """Partir la rejilla en bandas de otro tamaño da las mismas cifras: las sumas, a ≤ 10⁻¹²
        relativo; el resto, exactas."""
        whole = run(self.start, self.design, self.geometry, self.allowed,
                    cells_per_unit=10**9)
        for per_unit in (1, 53, 500, 4000):
            with self.subTest(cells_per_unit=per_unit):
                found = run(self.start, self.design, self.geometry, self.allowed,
                            cells_per_unit=per_unit)
                self.assertAlmostEqual(found.cut_m3 / whole.cut_m3, 1.0, delta=1e-12)
                self.assertAlmostEqual(found.fill_m3 / whole.fill_m3, 1.0, delta=1e-12)
                self.assertEqual((found.cut_cells, found.fill_cells, found.edge_cells),
                                 (whole.cut_cells, whole.fill_cells, whole.edge_cells))
                self.assertEqual((found.slope_p90_deg, found.slope_p99_deg, found.slope_max_deg,
                                  found.edge_step_max_m),
                                 (whole.slope_p90_deg, whole.slope_p99_deg, whole.slope_max_deg,
                                  whole.edge_step_max_m))
                self.assertEqual(found.slope_max_at, whole.slope_max_at)
                self.assertEqual(codes(found), codes(whole))

    def test_steps_are_progress_of_the_report_phase(self) -> None:
        """Da varios pasos de la fase «report»; el último lleva el informe, y los de antes no."""
        steps = list(report.report_steps(
            self.start, self.design, self.geometry, self.allowed, min_thickness_m=E,
            face_deg=60.0, face_tolerance_deg=1.0, warning_ratio=2.0, budget_s=0.0,
            cells_per_unit=500))
        self.assertGreater(len(steps), 3)
        self.assertEqual({step.phase for step in steps}, {"report"})
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        self.assertIsInstance(steps[-1].result, report.DesignReport)

    def test_inputs_are_not_modified_and_closing_leaves_nothing(self) -> None:
        before = (self.start.copy(), self.design.copy(), self.allowed.copy())
        steps = report.report_steps(self.start, self.design, self.geometry, self.allowed,
                                    min_thickness_m=E, face_deg=60.0, face_tolerance_deg=1.0,
                                    warning_ratio=2.0, budget_s=0.0, cells_per_unit=500)
        next(steps)
        steps.close()
        run(self.start, self.design, self.geometry, self.allowed)
        for after, then in zip((self.start, self.design, self.allowed), before, strict=True):
            self.assertEqual(after.tobytes(), then.tobytes())

    def test_no_figure_is_nan_or_infinite(self) -> None:
        """RF-013-17: toda cifra del informe es un número finito o ``None``; con huecos e
        infinitos en las superficies también."""
        start = self.start.copy()
        design = self.design.copy()
        start[3, 4] = np.nan
        design[5, 6] = np.inf
        design[7, 8] = -np.inf
        design[9, 9] = np.nan
        found = run(start, design, self.geometry, self.allowed)
        for name in ("cut_m3", "fill_m3", "moved_area_m2", "nodata_area_m2", "slope_p90_deg",
                     "slope_p99_deg", "slope_max_deg", "edge_step_max_m", "min_thickness_m"):
            value = getattr(found, name)
            self.assertTrue(value is None or math.isfinite(value), name)
        place = found.slope_max_at
        self.assertTrue(math.isfinite(place.x) and math.isfinite(place.y))
        self.assertGreaterEqual(found.nodata_cells, 4)

    def test_wrong_inputs_are_program_errors(self) -> None:
        """Formas que no casan, una máscara que no es booleana, un espesor negativo o no finito,
        un factor de aviso que no es mayor que 1 o unas celdas por unidad menores que 1 son
        errores del programa (``ValueError``) y salen al llamar."""
        good = dict(min_thickness_m=E, face_deg=60.0, face_tolerance_deg=1.0, warning_ratio=2.0)
        args = (self.start, self.design, self.geometry, self.allowed)
        for bad in (dict(min_thickness_m=-0.1), dict(min_thickness_m=float("nan")),
                    dict(warning_ratio=1.0), dict(warning_ratio=float("inf")),
                    dict(face_tolerance_deg=-1.0), dict(cells_per_unit=0),
                    dict(face_deg=np.ones((3, 3))), dict(face_deg=float("nan"))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                report.report_steps(*args, **{**good, **bad})
        with self.assertRaisesRegex(ValueError, "face_deg"):
            report.report_steps(*args, **{**good, "face_deg": np.ones((3, 3))})
        with self.assertRaisesRegex(ValueError, "cara del perfil"):
            report.report_steps(*args, **{**good, "face_deg": float("nan")})
        with self.assertRaises(ValueError):
            report.report_steps(self.start[:5], self.design, self.geometry, self.allowed, **good)
        with self.assertRaises(ValueError):
            report.report_steps(self.start, self.design, self.geometry,
                                self.allowed.astype(np.int8), **good)
        with self.assertRaises(ValueError):
            report.report_steps(self.start, self.design, grid_of(5, 5), self.allowed, **good)


if __name__ == "__main__":
    unittest.main()
