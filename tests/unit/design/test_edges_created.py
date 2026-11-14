# SPDX-License-Identifier: GPL-3.0-or-later
"""El salto creado en el borde de un diseño (spec 014, T27; HU-014-5; RF-014-20, RF-014-21;
CE-014-06; plan 014 A11, §5.3.1).

``design.edges.created_steps``: las parejas de celdas vecinas (4 vecinos) del **borde del
diseño**, una celda movida (en el dominio, con dato en las dos superficies y ``|S − z|`` mayor que
el espesor mínimo de la 012) y la otra no (con dato en las dos); en cada una, el **salto creado**
``c = |S_a − S_b| − |z_a − z_b|`` (el salto con el diseño menos el que ya tenía el terreno: el
salto previo no cuenta, error 48); el informe da las parejas, el porcentaje con ``c`` mayor que el
salto admitido, el máximo con su lugar (el punto medio de la pareja; a igual salto, el primero de
norte a sur y de oeste a este) y los **tramos** (las componentes 4-conexas de las celdas de las
parejas que pasan) con sus parejas, su máximo y su centro (la media de los puntos medios). Se
avisa si queda dentro del salto admitido menos del porcentaje admitido de las parejas (D-6).

- A mano: un terreno llano con un escarpe de 3 m y celdas de 2 m; una regularización de 0,25 m
  junto al escarpe (absoluto 3,25 m, creado 0,25 m), una corta de 4 m (creado 4 m, también junto al
  escarpe, donde el absoluto es 7 m) y un relleno de 2 m.
- CE-014-06 en la ladera de la cantera sintética (``quarry_fixtures``, con su escarpe previo de 3 m
  al norte de y = 300): el escarpe previo no cuenta y el escalón creado de 4 m sí.
- Por fuerza bruta: rejillas al azar con cotas en cuartos de metro (muchos empates), celdas sin
  dato y bandas de una a tres filas.
"""

from __future__ import annotations

import math
import unittest
from collections import deque
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

edges = import_geoblender("design.edges")
messages = import_geoblender("design.messages")

THICKNESS_M = 0.02
"""El espesor mínimo de las pruebas (el de la 012 es un dato de entrada)."""
THRESHOLD_M = 1.0
"""El salto admitido por defecto (D-6)."""
SHARE_PCT = 99.0
"""El porcentaje admitido por defecto (D-6)."""
TOLERANCE_M = 1e-9


def finish(steps: Any) -> Any:
    return list(steps)[-1].result


def created(surface: np.ndarray, start: np.ndarray, domain: np.ndarray, geometry: Any, *,
            threshold: float = THRESHOLD_M, share: float = SHARE_PCT, **options: Any) -> Any:
    return finish(edges.created_steps(surface, start, domain, geometry, THICKNESS_M, threshold,
                                      share, **options))


# --- A mano: terreno llano con un escarpe de 3 m ---------------------------------------------------

STEP = 2.0
ROWS, COLS = 10, 12
LOW_M, SCARP_M = 100.0, 3.0
"""El terreno: 100 m en las filas 4 a 9 y 103 m en las 0 a 3 (el escarpe, entre las filas 3 y 4)."""


def hand_case() -> tuple[Any, np.ndarray, np.ndarray, np.ndarray]:
    """La rejilla, el terreno, el dominio y la superficie: la regularización W (filas 4 a 7,
    columnas 2 a 5) a 99,75 m, la corta E (filas 4 a 7, columnas 6 a 9) a 96 m y el relleno F
    (filas 1 y 2, columnas 1 y 2) a 105 m; el dominio, las tres y nada más."""
    geometry = dfx.grid_from(ROWS, COLS, STEP)
    start = np.full((ROWS, COLS), LOW_M)
    start[:4] += SCARP_M
    surface = start.copy()
    surface[4:8, 2:6] = LOW_M - 0.25
    surface[4:8, 6:10] = LOW_M - 4.0
    surface[1:3, 1:3] = LOW_M + SCARP_M + 2.0
    domain = np.zeros((ROWS, COLS), dtype=bool)
    domain[4:8, 2:10] = True
    domain[1:3, 1:3] = True
    return geometry, start, domain, surface


class HandTest(unittest.TestCase):
    """RF-014-20, RF-014-21, A11: el salto creado y su informe a mano."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry, cls.start, cls.domain, cls.surface = hand_case()
        cls.before = (cls.start.copy(), cls.domain.copy(), cls.surface.copy())
        cls.report = created(cls.surface, cls.start, cls.domain, cls.geometry)

    def test_pairs_and_share_by_hand(self) -> None:
        """RF-014-20: 24 parejas de W y E (12 de W a 0,25 m y 12 de E a 4 m: norte, este y sur;
        entre W y E, las dos movidas, ninguna) y 8 de F a 2 m; pasan de 1 m las 20 de E y F:
        62,5 % (37,5 % dentro)."""
        self.assertEqual(self.report.pairs, 32)
        self.assertEqual(self.report.over, 20)
        self.assertEqual(self.report.over_pct, 62.5)
        self.assertEqual(self.report.within_pct, 37.5)
        self.assertEqual(self.report.threshold_m, THRESHOLD_M)
        self.assertEqual(self.report.min_share_pct, SHARE_PCT)
        self.assertEqual(self.report.min_thickness_m, THICKNESS_M)

    def test_previous_scarp_does_not_count(self) -> None:
        """RF-014-20 (error 48): junto al escarpe, W tiene un salto absoluto de 3,25 m y uno
        creado de 0,25 m, así que no pasa; medido como salto absoluto, pasarían también sus 4
        parejas del norte (24 en vez de 20)."""
        absolute = 0
        for row in range(ROWS):
            for col in range(COLS):
                for other_row, other_col in ((row + 1, col), (row, col + 1)):
                    if other_row >= ROWS or other_col >= COLS:
                        continue
                    one = self.domain[row, col] and self.surface[row, col] != self.start[row, col]
                    two = (self.domain[other_row, other_col]
                           and self.surface[other_row, other_col]
                           != self.start[other_row, other_col])
                    if one != two and abs(self.surface[row, col]
                                          - self.surface[other_row, other_col]) > THRESHOLD_M:
                        absolute += 1
        self.assertEqual(absolute, 24)
        self.assertEqual(self.report.over, 20)

    def test_maximum_and_its_place(self) -> None:
        """RF-014-21: el mayor salto creado es el de la corta, 4 m (no 7 m junto al escarpe),
        empatado en sus 12 parejas; el primero de norte a sur y de oeste a este es la pareja de
        las filas 3 y 4 en la columna 6: punto medio a 13 m de la esquina oeste y 8 m de la
        norte."""
        self.assertEqual(self.report.maximum_m, 4.0)
        self.assertAlmostEqual(self.report.x, self.geometry.west + 13.0, delta=TOLERANCE_M)
        self.assertAlmostEqual(self.report.y, self.geometry.north - 8.0, delta=TOLERANCE_M)

    def test_stretches_by_hand(self) -> None:
        """RF-014-21: dos tramos, en el orden de su primera celda fila a fila: el relleno F (8
        parejas a 2 m, centro en el de sus 4 celdas, a 4 m de las esquinas oeste y norte) y la
        corta E (12 parejas a 4 m; centro, la media de los puntos medios: x = 208/12 m, y = 12
        m)."""
        west, north = self.geometry.west, self.geometry.north
        stretches = self.report.stretches
        self.assertEqual([item.stretch for item in stretches], [1, 2])
        self.assertEqual([item.pairs for item in stretches], [8, 12])
        self.assertEqual([item.maximum_m for item in stretches], [2.0, 4.0])
        expected = ((west + 4.0, north - 4.0), (west + 208.0 / 12.0, north - 12.0))
        for item, (x, y) in zip(stretches, expected, strict=True):
            self.assertAlmostEqual(item.x, x, delta=TOLERANCE_M)
            self.assertAlmostEqual(item.y, y, delta=TOLERANCE_M)

    def test_warning_text_in_both_languages(self) -> None:
        """RF-014-21: el aviso (``des.edge_created_step``) con el porcentaje, las parejas, el
        salto y el porcentaje admitidos, el máximo y su lugar y los tramos, y una nota por tramo
        (``des.edge_stretch``), en español y en inglés."""
        self.assertTrue(self.report.warned)
        x, y = round(self.report.x, 2), round(self.report.y, 2)
        first, second = self.report.stretches
        expected = (
            messages.render("des.edge_created_step", share=62.5, pairs=32, threshold=1.0,
                            admitted=99.0, maximum=4.0, x=x, y=y, stretches=2),
            messages.render("des.edge_stretch", stretch=1, pairs=8, maximum=2.0,
                            x=round(first.x, 2), y=round(first.y, 2)),
            messages.render("des.edge_stretch", stretch=2, pairs=12, maximum=4.0,
                            x=round(second.x, 2), y=round(second.y, 2)),
        )
        self.assertEqual(self.report.notices, expected)
        self.assertEqual(self.report.lines("es"), expected)
        self.assertTrue(self.report.notices[0].startswith(
            "El 62,5 % de las 32 parejas del borde tiene un salto creado mayor que 1 m (al menos "
            "el 99 % debería quedar por debajo); el mayor, 4 m, en x = "))
        self.assertIn("en 2 tramos", self.report.notices[0])
        english = self.report.lines("en")
        self.assertEqual(len(english), 3)
        self.assertTrue(english[0].startswith("62.5 % of the 32 pairs of the edge"))

    def test_share_boundary(self) -> None:
        """D-6: se avisa si queda dentro **menos** del porcentaje admitido; con exactamente el
        37,5 % admitido, no; con el 37,6 %, sí. Con un salto admitido de 4 m no pasa ninguna
        pareja (el salto creado tiene que ser **mayor**): sin aviso y sin tramos."""
        exact = created(self.surface, self.start, self.domain, self.geometry, share=37.5)
        self.assertFalse(exact.warned)
        self.assertEqual(exact.notices, ())
        self.assertTrue(created(self.surface, self.start, self.domain, self.geometry,
                                share=37.6).warned)
        none = created(self.surface, self.start, self.domain, self.geometry, threshold=4.0)
        self.assertEqual((none.pairs, none.over, none.stretches, none.warned), (32, 0, (), False))
        self.assertEqual(none.maximum_m, 4.0)

    def test_moved_cells_need_the_domain_and_the_thickness(self) -> None:
        """RF-014-20: una celda movida está en el dominio y se mueve más que el espesor mínimo;
        sin el relleno F en el dominio, F no es del borde (24 parejas); con un espesor de 0,25 m,
        W no se mueve y las parejas son las de E con W y con el terreno, y las de F (12 + 4 + 8)."""
        domain = self.domain.copy()
        domain[1:3, 1:3] = False
        found = created(self.surface, self.start, domain, self.geometry)
        self.assertEqual((found.pairs, found.over), (24, 12))
        thick = finish(edges.created_steps(self.surface, self.start, self.domain, self.geometry,
                                           0.25, THRESHOLD_M, SHARE_PCT))
        self.assertEqual((thick.pairs, thick.over), (24, 24))
        self.assertEqual(thick.min_thickness_m, 0.25)

    def test_inputs_are_not_modified_and_steps(self) -> None:
        """Ninguna entrada se modifica; por pasos, el último de la fase ``created_step`` con el
        informe; cerrar el generador a mitad no deja nada."""
        for current, before in zip((self.start, self.domain, self.surface), self.before,
                                   strict=True):
            np.testing.assert_array_equal(current, before)
        steps = list(edges.created_steps(self.surface, self.start, self.domain, self.geometry,
                                         THICKNESS_M, THRESHOLD_M, SHARE_PCT, cells_per_unit=12,
                                         budget_s=0.0))
        self.assertGreater(len(steps), ROWS)
        self.assertEqual(steps[-1].result.pairs, self.report.pairs)
        self.assertEqual(steps[-1].phase, "created_step")
        self.assertIsInstance(steps[-1].result, edges.EdgeReport)
        running = edges.created_steps(self.surface, self.start, self.domain, self.geometry,
                                      THICKNESS_M, THRESHOLD_M, SHARE_PCT, cells_per_unit=12,
                                      budget_s=0.0)
        next(running)
        running.close()


# --- CE-014-06 en la ladera de la cantera ----------------------------------------------------------

A_BOX = (100.0, 260.0, 200.0, 300.0)
"""La corta de 4 m (local: izquierda, abajo, derecha, arriba), al pie del escarpe previo."""
B_BOX = (200.0, 296.0, 300.0, 300.0)
"""La regularización de 0,5 m, a lo largo del escarpe previo."""
C_BOX = (250.0, 150.0, 260.0, 160.0)
"""El relleno de 2 m, lejos del escarpe."""


class QuarryScarpTest(unittest.TestCase):
    """CE-014-06 (errores 42 y 48), RF-014-20, RF-014-21: en la ladera de la cantera
    (``180 + 0,25·y + 0,0625·x`` m, más 3 m al norte de y = 300), una corta de 4 m al pie del
    escarpe, una regularización de 0,5 m a lo largo de él y un relleno de 2 m."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry = qfx.GRID
        cls.start = qfx.terrain()
        cls.surface = cls.start.copy()
        for box, change in ((A_BOX, -4.0), (B_BOX, -0.5), (C_BOX, 2.0)):
            inside = qfx.in_box(box)
            cls.surface[inside] += change
        cls.domain = qfx.in_box(qfx.LEGAL_LOCAL)
        cls.report = created(cls.surface, cls.start, cls.domain, cls.geometry)

    def test_previous_scarp_does_not_count_and_created_step_does(self) -> None:
        """CE-014-06: a lo largo del escarpe, las 100 parejas de la regularización tienen un salto
        absoluto de 3,75 m y uno creado de 0,5 m (no pasan) y las 100 de la corta, 7,25 m y 4 m
        (pasan, con 4 m); el mayor salto creado es 4 m, no 7,25 m."""
        self.assertEqual(self.report.maximum_m, 4.0)
        self.assertAlmostEqual(self.report.x, qfx.BASE[0] + 100.5, delta=TOLERANCE_M)
        self.assertAlmostEqual(self.report.y, qfx.BASE[1] + 300.0, delta=TOLERANCE_M)

    def test_pairs_by_hand(self) -> None:
        """RF-014-20, A11: corta (100 × 40 celdas) al norte 100 parejas a 4 m, al este 36 a 4 m
        (las 4 de arriba lindan con la regularización, movida), al sur 100 a 3,5 m y al oeste 40
        a 3,875 m; regularización (100 × 4) al norte 100 a 0,5 m, al sur 100 a 0 m y al este 4 a
        0,5 m; relleno (10 × 10) 40 a 1,5, 2, 1,875 y 2 m: 520 parejas y 316 de más de 1 m."""
        self.assertEqual(self.report.pairs, 100 + 36 + 100 + 40 + 100 + 100 + 4 + 40)
        self.assertEqual(self.report.over, 100 + 36 + 100 + 40 + 40)
        self.assertAlmostEqual(self.report.over_pct, 316 / 520 * 100, delta=1e-12)
        self.assertTrue(self.report.warned)

    def test_stretches_by_hand(self) -> None:
        """RF-014-21: dos tramos: el borde de la corta (276 parejas, hasta 4 m; centro, la media
        de los puntos medios: Σx = 41.200 m y Σy = 77.208 m) y el del relleno (40 parejas, hasta
        2 m, centro en (255, 155))."""
        first, second = self.report.stretches
        self.assertEqual((first.stretch, first.pairs, first.maximum_m), (1, 276, 4.0))
        self.assertAlmostEqual(first.x, qfx.BASE[0] + 41_200 / 276, delta=TOLERANCE_M)
        self.assertAlmostEqual(first.y, qfx.BASE[1] + 77_208 / 276, delta=TOLERANCE_M)
        self.assertEqual((second.stretch, second.pairs, second.maximum_m), (2, 40, 2.0))
        self.assertAlmostEqual(second.x, qfx.BASE[0] + 255.0, delta=TOLERANCE_M)
        self.assertAlmostEqual(second.y, qfx.BASE[1] + 155.0, delta=TOLERANCE_M)
        self.assertEqual(len(self.report.notices), 3)
        self.assertIn("en 2 tramos", self.report.notices[0])


# --- Por fuerza bruta ------------------------------------------------------------------------------


def brute_force(surface: np.ndarray, start: np.ndarray, domain: np.ndarray, geometry: Any,
                threshold: float) -> dict[str, Any]:
    """El informe recorriendo las parejas una a una, en el orden de sus puntos medios (de norte a
    sur y de oeste a este), con los tramos por inundación."""
    nrows, ncols = start.shape

    def valid(row: int, col: int) -> bool:
        return math.isfinite(surface[row, col]) and math.isfinite(start[row, col])

    def moved(row: int, col: int) -> bool:
        return (bool(domain[row, col]) and valid(row, col)
                and abs(surface[row, col] - start[row, col]) > THICKNESS_M)

    pairs: list[tuple[float, float, float, tuple[int, int], tuple[int, int]]] = []
    for key_row in range(2 * nrows - 1):
        for key_col in range(2 * ncols - 1):
            if key_row % 2 == key_col % 2:
                continue
            row, col = key_row // 2, key_col // 2
            other = (row + 1, col) if key_row % 2 else (row, col + 1)
            if not (valid(row, col) and valid(*other)) or moved(row, col) == moved(*other):
                continue
            step = (abs(surface[row, col] - surface[other])
                    - abs(start[row, col] - start[other]))
            x = geometry.west + (key_col + 1) * geometry.dx / 2
            y = geometry.north - (key_row + 1) * geometry.dy / 2
            pairs.append((step, x, y, (row, col), other))
    over = [pair for pair in pairs if pair[0] > threshold]
    marked = {cell for pair in over for cell in pair[3:]}
    tag: dict[tuple[int, int], int] = {}
    for row in range(nrows):
        for col in range(ncols):
            if (row, col) in marked and (row, col) not in tag:
                label = len(set(tag.values())) + 1
                queue = deque([(row, col)])
                tag[(row, col)] = label
                while queue:
                    here = queue.popleft()
                    for d_row, d_col in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        near = (here[0] + d_row, here[1] + d_col)
                        if near in marked and near not in tag:
                            tag[near] = label
                            queue.append(near)
    stretches = []
    for label in range(1, len(set(tag.values())) + 1):
        mine = [pair for pair in over if tag[pair[3]] == label]
        stretches.append((label, len(mine), max(pair[0] for pair in mine),
                          sum(pair[1] for pair in mine) / len(mine),
                          sum(pair[2] for pair in mine) / len(mine)))
    best = None
    for pair in pairs:
        if best is None or pair[0] > best[0]:
            best = pair
    return {"pairs": len(pairs), "over": len(over), "best": best, "stretches": stretches}


def random_case(seed: int) -> tuple[Any, np.ndarray, np.ndarray, np.ndarray]:
    """Una rejilla de 9 × 11 celdas de 2 m con cotas en cuartos de metro (empates), una celda sin
    dato en el terreno y otra en la superficie a veces, un dominio con una parte de la rejilla y
    movimientos de 0 a ±5 m por bloques."""
    rng = np.random.default_rng(seed)
    nrows, ncols = 9, 11
    geometry = dfx.grid_from(nrows, ncols, STEP)
    start = 200.0 + 0.25 * rng.integers(0, 12, size=(nrows, ncols))
    change = 0.25 * rng.integers(-20, 21, size=(nrows, ncols))
    change[rng.random((nrows, ncols)) < 0.35] = 0.0
    change[rng.random((nrows, ncols)) < 0.05] = 0.01
    surface = start + change
    domain = np.zeros((nrows, ncols), dtype=bool)
    top, left = rng.integers(0, 3, size=2)
    domain[top:top + 7, left:left + 9] = True
    if seed % 3 == 0:
        start[rng.integers(nrows), rng.integers(ncols)] = np.nan
    if seed % 4 == 1:
        surface[rng.integers(nrows), rng.integers(ncols)] = np.nan
    return geometry, start, domain, surface


class BruteForceTest(unittest.TestCase):
    """RF-014-20, RF-014-21, A11: frente a la fuerza bruta en 40 rejillas al azar, con bandas de
    una, dos y tres filas y de toda la rejilla."""

    def test_against_the_brute_force(self) -> None:
        """Las parejas, las que pasan, el máximo y su lugar (a igual salto, el primero de norte a
        sur y de oeste a este) y cada tramo (parejas, máximo y centro) iguales a la fuerza bruta;
        el mismo informe con cualquier banda."""
        for seed in range(40):
            geometry, start, domain, surface = random_case(seed)
            threshold = (1.0, 2.5, 0.25)[seed % 3]
            expected = brute_force(surface, start, domain, geometry, threshold)
            for cells_per_unit in (11, 22, 33, 1_000):
                with self.subTest(seed=seed, cells_per_unit=cells_per_unit):
                    found = created(surface, start, domain, geometry, threshold=threshold,
                                    cells_per_unit=cells_per_unit)
                    self.assertEqual(found.pairs, expected["pairs"])
                    self.assertEqual(found.over, expected["over"])
                    best = expected["best"]
                    self.assertIsNotNone(best)
                    self.assertEqual(found.maximum_m, best[0])
                    self.assertAlmostEqual(found.x, best[1], delta=TOLERANCE_M)
                    self.assertAlmostEqual(found.y, best[2], delta=TOLERANCE_M)
                    self.assertEqual(len(found.stretches), len(expected["stretches"]))
                    for item, (label, count, top, x, y) in zip(found.stretches,
                                                               expected["stretches"],
                                                               strict=True):
                        self.assertEqual((item.stretch, item.pairs, item.maximum_m),
                                         (label, count, top))
                        self.assertAlmostEqual(item.x, x, delta=TOLERANCE_M)
                        self.assertAlmostEqual(item.y, y, delta=TOLERANCE_M)


class LimitsTest(unittest.TestCase):
    """RF-014-20, RF-014-21: los rechazos y los diseños sin borde."""

    def setUp(self) -> None:
        self.geometry, self.start, self.domain, self.surface = hand_case()

    def test_parameters_are_checked_when_called(self) -> None:
        """El salto y el porcentaje admitidos son ``des.edge.max_created_step_m`` y
        ``des.edge.min_share``: sin valor o fuera de rango se rechazan al llamar, nombrando la
        clave."""
        cases = (((None, SHARE_PCT), "des.quarry_param_missing", "des.edge.max_created_step_m"),
                 ((0.0, SHARE_PCT), "des.quarry_param_range", "des.edge.max_created_step_m"),
                 ((THRESHOLD_M, None), "des.quarry_param_missing", "des.edge.min_share"),
                 ((THRESHOLD_M, 0.0), "des.quarry_param_range", "des.edge.min_share"),
                 ((THRESHOLD_M, 100.5), "des.quarry_param_range", "des.edge.min_share"))
        for (threshold, share), code, field in cases:
            with (self.subTest(threshold=threshold, share=share),
                  self.assertRaises(messages.DesignError) as caught):
                edges.created_steps(self.surface, self.start, self.domain, self.geometry,
                                    THICKNESS_M, threshold, share)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.field, field)

    def test_program_errors(self) -> None:
        """Una rejilla de otra forma, un espesor negativo o no finito y una banda vacía son
        errores del programa al llamar."""
        for surface, start, domain in ((self.surface[:3], self.start, self.domain),
                                       (self.surface, self.start[:3], self.domain),
                                       (self.surface, self.start, self.domain[:3])):
            with self.assertRaises(ValueError):
                edges.created_steps(surface, start, domain, self.geometry, THICKNESS_M,
                                    THRESHOLD_M, SHARE_PCT)
        for thickness in (-0.01, math.nan):
            with self.assertRaises(ValueError):
                edges.created_steps(self.surface, self.start, self.domain, self.geometry,
                                    thickness, THRESHOLD_M, SHARE_PCT)
        with self.assertRaises(ValueError):
            edges.created_steps(self.surface, self.start, self.domain, self.geometry,
                                THICKNESS_M, THRESHOLD_M, SHARE_PCT, cells_per_unit=0)

    def test_without_edge_pairs(self) -> None:
        """Sin celdas movidas, o con todas movidas, no hay borde: 0 parejas, el máximo 0 m sin
        lugar, sin tramos y sin aviso."""
        everything = np.ones(self.domain.shape, dtype=bool)
        for surface, domain in ((self.start.copy(), self.domain),
                                (self.start + 5.0, everything)):
            found = created(surface, self.start, domain, self.geometry)
            self.assertEqual((found.pairs, found.over, found.stretches), (0, 0, ()))
            self.assertEqual(found.maximum_m, 0.0)
            self.assertIsNone(found.x)
            self.assertIsNone(found.y)
            self.assertEqual((found.over_pct, found.within_pct), (0.0, 100.0))
            self.assertFalse(found.warned)
            self.assertEqual(found.notices, ())


# --- Lo que enseña el resumen (T61; el H3) ---------------------------------------------------------

Notice = import_geoblender("design.preview").Notice


def warned(surface: str, first: int, count: int) -> list[Any]:
    """El aviso ``des.edge_surface_step`` de ``surface`` y sus ``count`` tramos, numerados desde
    ``first`` (los valores, de mentira: solo cuenta lo que se enseña)."""
    found = [Notice("des.edge_surface_step", {"surface": surface, "stretches": count})]
    found += [Notice("des.edge_stretch", {"surface": surface, "stretch": number, "pairs": 1})
              for number in range(first, first + count)]
    return found


class SummaryNoticesTest(unittest.TestCase):
    """RF-014-21 (T61; lo que vio el H3: con 101, 138 y 204 tramos, «Crear» quedaba fuera de la
    ventana): ``edges.summary_notices`` deja los :data:`SUMMARY_STRETCHES` (10) primeros tramos de
    cada aviso del salto creado y una nota con los que faltan; lo demás, tal cual."""

    def test_ten_stretches_of_each_warning_and_how_many_are_left(self) -> None:
        """Dos superficies con 17 y 12 tramos (numerados seguidos) entre otros avisos: de cada una,
        su aviso, sus 10 primeros tramos y «… y 7 tramos más (en el informe)» / «… y 2 …»; la nota
        de antes y la de después, en su sitio."""
        self.assertEqual(edges.SUMMARY_STRETCHES, 10)
        before = Notice("des.quarry_unsplit_zone", {"zone": 1})
        after = Notice("des.magnitude_no_reference", {"operation": "Corta"})
        first, second = warned("des_fin_corta", 1, 17), warned("des_exp_corta", 18, 12)
        found = edges.summary_notices([before, *first, *second, after])
        self.assertEqual(found, (
            before, *first[:11], Notice("des.edge_more_stretches", {"stretches": 7}),
            *second[:11], Notice("des.edge_more_stretches", {"stretches": 2}), after))
        self.assertEqual(found[12].text(), "… y 7 tramos más (en el informe).")
        self.assertEqual(found[12].text("en"), "… and 7 more stretches (in the report).")

    def test_the_limit_itself_one_more_and_a_refit(self) -> None:
        """Con 10 tramos, todos y ninguna nota; con 11, la nota en singular («… y 1 tramo más»);
        un ajuste (sin informe) lo dice con la suya; con ``limit`` 0, solo el aviso y la nota; un
        tramo suelto (sin su aviso delante) no se toca, y un límite negativo es un error del
        programa."""
        ten = warned("des_fin_corta", 1, 10)
        self.assertEqual(edges.summary_notices(ten), tuple(ten))
        eleven = warned("des_fin_corta", 1, 11)
        found = edges.summary_notices(eleven)
        self.assertEqual(found[-1], Notice("des.edge_more_stretches", {"stretches": 1}))
        self.assertEqual(found[-1].text(), "… y 1 tramo más (en el informe).")
        self.assertEqual(len(found), 12)
        refit = edges.summary_notices(eleven, reported=False)
        self.assertEqual(refit[-1], Notice("des.edge_more_stretches_refit", {"stretches": 1}))
        self.assertEqual(edges.summary_notices(eleven, limit=0),
                         (eleven[0], Notice("des.edge_more_stretches", {"stretches": 11})))
        created_step = [Notice("des.edge_created_step", {"stretches": 12}),
                        *warned("x", 1, 12)[1:]]
        self.assertEqual(len(edges.summary_notices(created_step)), 12)
        loose = warned("des_fin_corta", 1, 12)[1:]
        self.assertEqual(edges.summary_notices(loose), tuple(loose))
        with self.assertRaises(ValueError):
            edges.summary_notices(ten, limit=-1)


if __name__ == "__main__":
    unittest.main()
