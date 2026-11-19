# SPDX-License-Identifier: GPL-3.0-or-later
"""Los candidatos sin marca de una detección de acopios y la regla de identidad al repetir (spec 016, T08; RF-016-08,
RF-016-10; CE-016-01 en el dominio; D-10, D-23; plan 016 A4, A1 y §7.3).

:mod:`design.stockpiles` busca, en el perímetro de actuación, las zonas conexas de las celdas con ``z − apertura(z, ⌀) >
altura mínima``, las filtra por su área (de la mínima a la máxima, ambas incluidas), no da como candidata la que contiene
o se solapa con la huella de una marca (los candidatos son «sin marca») y a las que pasan les da plano, huella y volumen
como si la zona fuera una marca (A2 y A3, en su ventana de trabajo). Y da la regla de identidad al repetir (D-23): un
candidato nuevo conserva la decisión de uno anterior si sus huellas comparten más de la mitad del área de cada una.
Se prueba con:

- **cuentas a mano**: bloques de altura y área conocidas (los umbrales justo en su valor y un poco más allá), las celdas
  de 2 m (el área es en m², no en celdas) y la regla de la mitad con enteros;
- **implementaciones independientes**: la apertura por fuerza bruta con enteros (``milestone_morphology.brute``) y las
  zonas, la huella y el volumen de A3 por bucles de Python (``design_oracles``, ``hand_grow``), que dan **todo A4 a mano**
  sobre una rejilla de 40 × 40 celdas y, sobre la rejilla entera, el mismo resultado que la ventana de cada candidato;
- **la cantera de la 016** (``tests.support.stockpile_data``): el levantamiento de CE-016-01 con sus 5 acopios marcados y
  sus 20 montículos sin marca (8 que pasan los filtros, 4 pequeños, 4 bajos y 4 fuera del perímetro).
"""

from __future__ import annotations

import dataclasses
import math
import random
import time
import unittest
from contextlib import closing
from fractions import Fraction

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design.milestone_morphology import brute
from tests.unit.design.test_stockpile_footprint import MARGIN_M, THRESHOLD_M, hand_grow, params_of

gis = import_geoblender("gis")
stockpiles = import_geoblender("design.stockpiles")
morphology = import_geoblender("design.morphology")

# Los umbrales de D-3 de los candidatos (ADOPTADO «sin confirmar»): valores de ENTRADA de estas pruebas, no los que la
# implementación da por defecto (no da ninguno: P-6 del plan).
OPEN_M, MIN_HEIGHT_M, MIN_AREA_M2, MAX_AREA_M2 = 31.0, 2.0, 150.0, 20_000.0


def cparams(*, open_diameter_m: float = OPEN_M, min_height_m: float = MIN_HEIGHT_M, min_area_m2: float = MIN_AREA_M2,
            max_area_m2: float = MAX_AREA_M2, **footprint: float) -> object:
    """Los parámetros de A4 con los umbrales de D-3 (y los de la huella de ``params_of``, con los cambios de
    ``footprint``)."""
    return stockpiles.CandidateParams(open_diameter_m, min_height_m, min_area_m2, max_area_m2, params_of(**footprint))


def embed(item: object, mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """``mask`` (de la ventana de ``item``) en una máscara de la rejilla entera, de forma ``shape``."""
    full = np.zeros(shape, dtype=bool)
    full[item.window] = mask
    return full


def cell_of(grid: object, mound: object) -> tuple[int, int]:
    """La celda ``(fila, columna)`` cuyo centro es ``(cx + 0,5, cy + 0,5)`` locales: la que está al noreste del centro
    (un metro entero, esquina de celda) del montículo."""
    return grid.nrows - 1 - int(mound.cy), int(mound.cx)


def run_steps(steps: object) -> tuple[object, float, int]:
    """Recorre ``steps`` midiendo la llamada más larga: el último ``Progress``, su duración (s) y cuántos pasos dio."""
    longest, count, last = 0.0, 0, None
    with closing(steps):
        while True:
            started = time.perf_counter()
            try:
                last = next(steps)
            except StopIteration:
                break
            longest, count = max(longest, time.perf_counter() - started), count + 1
    return last, longest, count


# --- La cantera de CE-016-01: 5 marcados y 20 sin marca ------------------------------------------------------------------


def marked_cells(grid: object, z: np.ndarray) -> np.ndarray:
    """Las huellas de los cinco acopios marcados (la unión de las celdas de su montículo sobre su base, con el umbral de
    la huella): sobre el plano del levantamiento y, el Acopio 5, sobre su base propia (el levantamiento anterior)."""
    found = np.zeros(grid.shape, dtype=bool)
    for mark in sdata.MARKS:
        base = sdata.previous_survey(grid) if mark.base else sdata.survey_plane().values(grid)
        cells = sdata.in_box(mark.box, grid)
        enlarged = morphology.dilate(cells, mark.margin_m or MARGIN_M, grid.dx)
        found |= stockpiles.footprint_above(z, base, cells, enlarged, grid, THRESHOLD_M).mask
    return found


class SurveyTest(unittest.TestCase):
    """CE-016-01 en el dominio (RF-016-08): sobre el levantamiento de 5 marcados y 20 sin marca, salen los 8 candidatos
    que pasan los filtros y ninguno de los 12 que no (ni de los 5 que ya tienen marca)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = qfx.GRID
        cls.z = sdata.survey()
        cls.perimeter = sdata.in_box(qfx.PERIMETER_LOCAL)
        cls.marked = marked_cells(cls.grid, cls.z)
        cls.params = cparams()
        cls.found = stockpiles.find_candidates(cls.z, cls.grid, cls.perimeter, cls.marked, cls.params)

    def centre_in(self, item: object, name: str, what: str) -> bool:
        row, col = cell_of(self.grid, sdata.survey_mound(name))
        mask = item.zone if what == "zone" else item.footprint.mask
        return bool(embed(item, mask, self.grid.shape)[row, col])

    def test_eight_pass_and_none_of_the_others(self) -> None:
        """RF-016-08, CE-016-01: los 8 montículos que pasan los filtros salen, cada uno en un candidato distinto (su
        zona y su huella tienen el centro del montículo); de los 17 restantes (los 4 pequeños, los 4 bajos, los 4 de
        fuera del perímetro y los 5 marcados) no sale ninguno: ni su centro está en una zona o una huella, ni una zona
        se solapa con la huella de una marca."""
        names = sdata.SURVEY_GROUPS["pass"]
        self.assertEqual(len(self.found.items), 8)
        owners = []
        for name in names:
            holders = [k for k, item in enumerate(self.found.items) if self.centre_in(item, name, "zone")]
            self.assertEqual(len(holders), 1, name)
            self.assertTrue(self.centre_in(self.found.items[holders[0]], name, "footprint"), name)
            owners.append(holders[0])
        self.assertEqual(sorted(owners), list(range(8)))
        for group in ("small", "low", "outside", "marked"):
            for name in sdata.SURVEY_GROUPS[group]:
                for item in self.found.items:
                    self.assertFalse(self.centre_in(item, name, "zone"), name)
                    self.assertFalse(self.centre_in(item, name, "footprint"), name)
        for item in self.found.items:
            self.assertFalse((embed(item, item.zone, self.grid.shape) & self.marked).any())

    def test_what_the_filter_discards_is_counted_and_not_listed(self) -> None:
        """RF-016-08, error 64: 18 zonas antes de filtrar (8 que pasan, 4 pequeñas, las 5 de los marcados y una de una sola
        celda que la apertura de 31 m deja en el flanco del Acopio 1, dentro de su huella: cuenta como zona con marca, 6);
        los 4 bajos no pasan de 2 m y los 4 de fuera no están en el perímetro. El resultado solo lleva los candidatos que
        pasan y los **contadores** de lo que se descartó (nunca una lista): lo que se lista no da ninguno de los 12."""
        found = self.found
        self.assertEqual((found.zones, found.on_marks, found.too_small, found.too_large, found.rejected),
                         (18, 6, 4, 0, 0))
        self.assertEqual(found.filtered, 4)
        self.assertEqual(len(found.items) + found.on_marks + found.filtered + found.rejected, found.zones)
        self.assertEqual({field.name for field in dataclasses.fields(stockpiles.Candidates)},
                         {"grid", "items", "zones", "on_marks", "too_small", "too_large", "rejected"})
        self.assertEqual({field.name for field in dataclasses.fields(stockpiles.Candidate)},
                         {"zone", "footprint", "window", "grid", "cells"})
        self.assertIs(found.grid, self.grid)

    def test_the_zones_and_the_filters_are_the_brute_force_ones(self) -> None:
        """RF-016-08: con la apertura de 31 m por **fuerza bruta con enteros** (``milestone_morphology.brute``, sin
        ``design.morphology``) y las zonas por una búsqueda en anchura (``hand_zones``), salen las mismas 18 zonas, con
        los mismos contadores (con marca, pequeñas, grandes) y, las que pasan, con las mismas celdas que las zonas de los
        candidatos, en el mismo orden."""
        twice = round(OPEN_M / self.grid.dx)
        opened = brute(brute(self.z, twice, erode=True), twice, erode=False)
        zones = oracles.hand_zones((self.perimeter & (self.z - opened > MIN_HEIGHT_M)).tolist())
        counts, passing = {"marked": 0, "small": 0, "large": 0}, []
        for cells in zones:
            area = len(cells) * self.grid.cell_area
            if any(self.marked[row, col] for row, col in cells):
                counts["marked"] += 1
            elif area < MIN_AREA_M2:
                counts["small"] += 1
            elif area > MAX_AREA_M2:
                counts["large"] += 1
            else:
                passing.append(set(cells))
        found = self.found
        self.assertEqual((len(zones), counts["marked"], counts["small"], counts["large"], len(passing)),
                         (found.zones, found.on_marks, found.too_small, found.too_large, len(found.items)))
        got = [set(map(tuple, np.argwhere(embed(item, item.zone, self.grid.shape)).tolist())) for item in found.items]
        self.assertEqual(got, passing)

    def test_without_marks_the_five_marked_ones_also_pass(self) -> None:
        """La decisión de RF-016-08 («sin marca»): sin excluir lo que ya tiene marca, los 5 marcados pasarían los
        filtros y saldrían 13 candidatos (el Acopio 1 y el 2 son dos zonas de 185 y 225 m²) y la zona de una celda del
        flanco del Acopio 1 contaría como pequeña (5); con ``marked=None``, también."""
        for marked in (None, np.zeros(self.grid.shape, dtype=bool)):
            found = stockpiles.find_candidates(self.z, self.grid, self.perimeter, marked, self.params)
            self.assertEqual((len(found.items), found.on_marks, found.too_small), (13, 0, 5))
            extra = [name for name in sdata.SURVEY_GROUPS["marked"]
                     if sum(self.centre_in(item, name, "zone") for item in found.items) == 1]
            self.assertEqual(extra, list(sdata.SURVEY_GROUPS["marked"]))

    def test_the_volume_of_each_one_is_the_hand_calculation(self) -> None:
        """RF-016-08, RF-016-02: el volumen de cada candidato es el cálculo a mano (``hand_volume``: ``fsum`` de
        ``(z − base)·área`` donde pasa del umbral, con un bucle de Python) sobre **su misma huella y su mismo plano** a
        ≤ 10⁻⁹ relativo; y, a menos del 1 %, el del montículo sobre el umbral (los planos de las pirámides están a 4,5 mm
        del sintético: T06). Su área son sus celdas por 1 m²."""
        heights = sdata.mound_heights(self.grid.shape, 1.0, sdata.SURVEY_MOUNDS)
        for name in sdata.SURVEY_GROUPS["pass"]:
            item = next(it for it in self.found.items if self.centre_in(it, name, "zone"))
            footprint = item.footprint
            by_hand = oracles.hand_volume(self.z[item.window].tolist(), footprint.base.tolist(),
                                          footprint.mask.tolist(), 1.0, THRESHOLD_M)
            self.assertAlmostEqual(footprint.volume_m3 / by_hand - 1.0, 0.0, delta=1e-9, msg=name)
            mound = sdata.survey_mound(name)
            above = sdata.in_box(mound.foot_box, self.grid) & (heights > THRESHOLD_M)
            self.assertAlmostEqual(footprint.volume_m3 / float(heights[above].sum()) - 1.0, 0.0, delta=1e-2, msg=name)
            self.assertEqual(footprint.area_m2, float(footprint.mask.sum()))
            self.assertEqual(int(footprint.mask.sum()), int(above.sum()), name)

    def test_the_window_does_not_change_the_result(self) -> None:
        """A0, RF-016-02: A2 y A3 en la ventana de cada candidato (la caja de su zona ampliada por el margen, la corona y
        dos celdas) dan lo mismo que sobre la rejilla entera: la misma huella, el mismo volumen (≤ 10⁻⁹ relativo: la
        ventana tiene su propia esquina, así que los centros de celda difieren en el último bit) y el mismo plano."""
        shape = self.grid.shape
        for item in self.found.items:
            zone = embed(item, item.zone, shape)
            whole = stockpiles.grow_footprint(self.z, zone, self.grid, self.params.footprint)
            np.testing.assert_array_equal(embed(item, item.footprint.mask, shape), whole.mask)
            self.assertAlmostEqual(item.footprint.volume_m3 / whole.volume_m3 - 1.0, 0.0, delta=1e-9)
            np.testing.assert_allclose(item.footprint.base, whole.base[item.window], rtol=1e-11)
            self.assertEqual((item.footprint.turns, item.footprint.converged), (whole.turns, whole.converged))
            self.assertEqual([note.code for note in item.footprint.notes], [note.code for note in whole.notes])
            rows, cols = np.nonzero(zone)
            self.assertEqual(item.window, stockpiles.mark_window(zone, self.grid, self.params.footprint))
            self.assertLessEqual(item.window[0].start, rows.min())
            self.assertGreaterEqual(item.window[0].stop, rows.max() + 1)
            self.assertLess(item.window[0].stop - item.window[0].start, self.grid.nrows // 2)
            self.assertLess(item.window[1].stop - item.window[1].start, self.grid.ncols // 2)

    def test_the_window_grid_is_the_part_of_the_grid(self) -> None:
        """La rejilla de la ventana empieza en la esquina de su primera celda y tiene las celdas de la entera."""
        for item in self.found.items:
            rows, cols = item.window
            self.assertEqual(item.grid.shape, (rows.stop - rows.start, cols.stop - cols.start))
            self.assertEqual((item.grid.dx, item.grid.dy), (self.grid.dx, self.grid.dy))
            self.assertEqual(item.grid.west, self.grid.west + cols.start * self.grid.dx)
            self.assertEqual(item.grid.north, self.grid.north - rows.start * self.grid.dy)
            self.assertEqual(item.zone.shape, item.grid.shape)
            self.assertEqual(item.footprint.mask.shape, item.grid.shape)

    def test_the_candidates_come_in_reading_order_with_their_cell_keys(self) -> None:
        """Los candidatos salen en el orden de la primera celda de su zona recorriendo la rejilla fila a fila (el de la
        etiqueta de ``label_components``); ``cells`` son las celdas de su huella en la rejilla entera (fila·columnas +
        columna), ordenadas y sin repetir: las que usa la regla de identidad."""
        firsts = []
        for item in self.found.items:
            zone = embed(item, item.zone, self.grid.shape)
            firsts.append(int(np.flatnonzero(zone.ravel())[0]))
            expected = np.flatnonzero(embed(item, item.footprint.mask, self.grid.shape).ravel())
            np.testing.assert_array_equal(item.cells, expected)
            self.assertEqual(item.cells.dtype, np.int64)
        self.assertEqual(firsts, sorted(firsts))

    def test_nothing_is_modified(self) -> None:
        before = [array.copy() for array in (self.z, self.perimeter, self.marked)]
        stockpiles.find_candidates(self.z, self.grid, self.perimeter, self.marked, self.params)
        for array, kept in zip((self.z, self.perimeter, self.marked), before, strict=True):
            np.testing.assert_array_equal(array, kept)


class StepsTest(unittest.TestCase):
    """La variante por pasos (RNF-016-03): el mismo resultado, en pasos pequeños y sin dejar nada a mitad."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = qfx.GRID
        cls.z = sdata.survey()
        cls.perimeter = sdata.in_box(qfx.PERIMETER_LOCAL)
        cls.marked = marked_cells(cls.grid, cls.z)
        cls.params = cparams()

    def test_the_steps_give_the_same_candidates_in_small_steps(self) -> None:
        """El último paso (fase ``candidates``) lleva los mismos candidatos que el de una pieza y ninguna llamada pasa de
        0,05 s; con el presupuesto de la interfaz salen menos pasos."""
        whole = stockpiles.find_candidates(self.z, self.grid, self.perimeter, self.marked, self.params)
        last, longest, count = run_steps(stockpiles.candidates_steps(
            self.z, self.grid, self.perimeter, self.marked, self.params, budget_s=0.0))
        self.assertEqual(last.phase, "candidates")
        self.assertGreater(count, 8)
        self.assertLess(longest, 0.05)
        found = last.result
        self.assertIsInstance(found, stockpiles.Candidates)
        self.assertEqual((found.zones, found.on_marks, found.too_small, found.too_large, found.rejected),
                         (whole.zones, whole.on_marks, whole.too_small, whole.too_large, whole.rejected))
        for item, expected in zip(found.items, whole.items, strict=True):
            self.assertEqual(item.window, expected.window)
            np.testing.assert_array_equal(item.zone, expected.zone)
            np.testing.assert_array_equal(item.footprint.mask, expected.footprint.mask)
            np.testing.assert_array_equal(item.cells, expected.cells)
            self.assertEqual(item.footprint.volume_m3, expected.footprint.volume_m3)
        _last, _longest, paced = run_steps(stockpiles.candidates_steps(
            self.z, self.grid, self.perimeter, self.marked, self.params))
        self.assertLess(paced, count)

    def test_closing_halfway_leaves_the_inputs_as_they_were(self) -> None:
        before = [array.copy() for array in (self.z, self.perimeter, self.marked)]
        steps = stockpiles.candidates_steps(self.z, self.grid, self.perimeter, self.marked, self.params, budget_s=0.0)
        next(steps)
        next(steps)
        steps.close()
        for array, kept in zip((self.z, self.perimeter, self.marked), before, strict=True):
            np.testing.assert_array_equal(array, kept)

    def test_refusals_come_in_the_call(self) -> None:
        """Los rechazos de la entrada (rejilla de celdas no cuadradas, formas que no cuadran, máscaras que no son
        booleanas, parámetros que no son ``CandidateParams``) salen **en la llamada**, no al avanzar."""
        bad_grid = type(self.grid)(self.grid.west, self.grid.north, 1.0, 2.0, self.grid.ncols, self.grid.nrows)
        wrong = np.zeros((3, 3), dtype=bool)
        infinite = self.z.copy()
        infinite[5, 5] = np.inf
        calls = (
            (infinite, self.grid, self.perimeter, self.marked, self.params),
            (self.z, bad_grid, self.perimeter, self.marked, self.params),
            (self.z[:-1], self.grid, self.perimeter, self.marked, self.params),
            (self.z, self.grid, wrong, self.marked, self.params),
            (self.z, self.grid, self.perimeter.astype(np.int8), self.marked, self.params),
            (self.z, self.grid, self.perimeter, wrong, self.params),
            (self.z, self.grid, self.perimeter, self.marked.astype(float), self.params),
            (self.z, self.grid, self.perimeter, self.marked, self.params.footprint),
        )
        for args in calls:
            with self.assertRaises((ValueError, TypeError)):
                stockpiles.candidates_steps(*args)
        with self.assertRaises(ValueError):
            stockpiles.candidates_steps(self.z.ravel(), self.grid, self.perimeter, self.marked, self.params)


# --- A4 entero a mano, sobre una rejilla pequeña -------------------------------------------------------------------------

SMALL_M = 40.0
SMALL_OPEN_M = 11.0
"""Rejilla de 40 × 40 celdas y la apertura de los bloques de ``FilterTest`` (11 m: no cabe en un bloque de 6 × 6 celdas)."""
HAND_OPEN_M = 7.0
HAND_PARAMS = dict(open_diameter_m=HAND_OPEN_M, min_height_m=1.0, min_area_m2=10.0, max_area_m2=200.0, margin_m=4.0)
HAND_MOUNDS = (
    # Pies de 6 m, menos que los 7 m del disco, a 9 celdas o más del borde (el alcance de la apertura son 6): la apertura
    # no se ve afectada por el borde. Los pies caben en su huella (la última corona sobre el umbral de 0,3 m: 0,5, 0,5625
    # y 0,375 m), así que la corona de la huella es plano, sin las esquinas de la pirámide de T06; alturas exactas en binario.
    sdata.Mound("A", "pyramid", 12.0, 12.0, 3.0, 0.0, 3.0),     # pendiente 1; 16 celdas sobre 1 m
    sdata.Mound("B", "pyramid", 28.0, 12.0, 3.0, 1.0, 2.25),    # pendiente 1,125; 16 celdas sobre 1 m
    sdata.Mound("C", "pyramid", 12.0, 28.0, 2.0, 0.0, 1.5),     # pendiente 0,75; 4 celdas sobre 1 m: menos de 10 m²
    sdata.Mound("E", "pyramid", 28.0, 28.0, 3.0, 0.0, 3.0),     # el marcado
)


def hand_candidates(z: np.ndarray, grid: object, perimeter: np.ndarray, marked: np.ndarray, *, open_diameter_m: float,
                    min_height_m: float, min_area_m2: float, max_area_m2: float, margin_m: float) -> list[tuple]:
    """A4 entero **a mano** (RF-016-08): la apertura por fuerza bruta con enteros (``milestone_morphology.brute``), las zonas
    por una búsqueda en anchura, el filtro del área y de las marcas, y A2 y A3 de cada zona con ``hand_grow`` sobre la
    rejilla entera. Da ``(zona, huella, plano, volumen)`` por candidato, en el orden de lectura."""
    twice = round(open_diameter_m / grid.dx)
    opened = brute(brute(z, twice, erode=True), twice, erode=False)
    with np.errstate(invalid="ignore"):
        above = perimeter & (z - opened > min_height_m)
    found = []
    for cells in oracles.hand_zones(above.tolist()):
        area = len(cells) * grid.cell_area
        zone = np.zeros(grid.shape, dtype=bool)
        for row, col in cells:
            zone[row, col] = True
        if (zone & marked).any() or not min_area_m2 <= area <= max_area_m2:
            continue
        grown = hand_grow(z, grid, zone, margin_m=margin_m)
        found.append((zone, grown.found.mask, grown.base, grown.volume))
    return found


class SmallCaseTest(unittest.TestCase):
    """RF-016-08: A4 entero contra el cálculo a mano en una rejilla de 40 × 40 celdas de 1 m, sobre un plano de 3°: dos
    montículos que pasan (A y B), uno pequeño (C), uno marcado (E) y un disco de apertura de 7 m (más ancho que los pies
    de 6 m)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = sdata.window_grid(1.0, SMALL_M)
        cls.base = sdata.plane(3.0, pivot=(20.0, 20.0)).values(cls.grid)
        cls.z = cls.base + sdata.mound_heights(cls.grid.shape, 1.0, HAND_MOUNDS)
        cls.perimeter = sdata.in_box((2.0, 2.0, 38.0, 38.0), cls.grid)
        cls.marked = sdata.in_box(HAND_MOUNDS[3].foot_box, cls.grid) & (cls.z - cls.base > THRESHOLD_M)
        cls.params = cparams(**HAND_PARAMS)
        cls.found = stockpiles.find_candidates(cls.z, cls.grid, cls.perimeter, cls.marked, cls.params)
        cls.by_hand = hand_candidates(cls.z, cls.grid, cls.perimeter, cls.marked, **HAND_PARAMS)

    def test_the_counts(self) -> None:
        """Cuatro zonas (A, B, C y E, de 16, 16, 4 y 16 celdas: las de cada montículo sobre 1 m); E tiene marca, C no
        llega al área mínima de 10 m², A y B son candidatos; el oráculo ve las mismas."""
        found = self.found
        self.assertEqual((found.zones, found.on_marks, found.too_small, found.too_large, found.rejected, len(found.items)),
                         (4, 1, 1, 0, 0, 2))
        self.assertEqual([int(item.zone.sum()) for item in found.items], [16, 16])
        self.assertEqual(len(self.by_hand), 2)

    def test_the_zones_the_footprints_and_the_volumes_are_the_hand_ones(self) -> None:
        """La zona, la huella, el plano de base y el volumen (≤ 10⁻⁹ relativo) de cada candidato son los del oráculo
        sobre la rejilla entera (la ventana de cada uno es menor que ella)."""
        shape = self.grid.shape
        for item, (zone, mask, base, volume) in zip(self.found.items, self.by_hand, strict=True):
            self.assertLess(item.grid.nrows * item.grid.ncols, shape[0] * shape[1])
            np.testing.assert_array_equal(embed(item, item.zone, shape), zone)
            np.testing.assert_array_equal(embed(item, item.footprint.mask, shape), mask)
            np.testing.assert_allclose(item.footprint.base, base[item.window], rtol=1e-9)
            self.assertAlmostEqual(item.footprint.volume_m3 / volume - 1.0, 0.0, delta=1e-9)

    def test_the_centre_is_the_middle_of_the_footprint(self) -> None:
        """El lugar de un candidato es el centro de su huella (la media de los centros de celda, absolutos): la huella de
        A y de B es el cuadrado de 6 × 6 m del pie, centrado en (12, 12) y en (28, 12) locales."""
        for item, (cx, cy) in zip(self.found.items, ((12.0, 12.0), (28.0, 12.0)), strict=True):
            x, y = item.centre
            self.assertAlmostEqual(x, sdata.BASE[0] + cx, delta=1e-9)
            self.assertAlmostEqual(y, sdata.BASE[1] + cy, delta=1e-9)

    def test_the_plane_of_each_one_is_the_synthetic_one(self) -> None:
        """Con los pies dentro de la huella, el plano de cada candidato es el sintético (3°) a ≤ 10⁻⁶ m, y su volumen el
        de su montículo (la altura de cada celda sobre el umbral de 0,3 m, sumada) a ≤ 10⁻⁹ relativo; son 36 celdas."""
        shape = self.grid.shape
        for item, mound in zip(self.found.items, HAND_MOUNDS[:2], strict=True):
            np.testing.assert_allclose(item.footprint.base, self.base[item.window], atol=1e-6)
            heights = sdata.mound_heights(shape, 1.0, (mound,))
            expected = math.fsum(heights[heights > THRESHOLD_M].tolist())
            self.assertAlmostEqual(item.footprint.volume_m3 / expected - 1.0, 0.0, delta=1e-9)
            self.assertEqual(int(item.footprint.mask.sum()), 36)

    def test_the_opening_is_the_brute_force_one(self) -> None:
        """Las zonas de A4 salen de ``z − apertura`` por encima de la altura mínima dentro del perímetro con la apertura
        de la fuerza bruta con enteros (el oráculo las calcula aparte); el disco, de 7 m, no cabe en los pies de 6 m y la
        apertura deja el plano casi entero: ``plano − 0,2 m ≤ apertura ≤ z`` (la rejilla acaba en su borde)."""
        twice = round(HAND_OPEN_M / self.grid.dx)
        opened = brute(brute(self.z, twice, erode=True), twice, erode=False)
        above = self.perimeter & (self.z - opened > HAND_PARAMS["min_height_m"])
        zones = oracles.hand_zones(above.tolist())
        self.assertEqual(self.found.zones, len(zones))
        self.assertEqual(sorted(len(cells) for cells in zones), [4, 16, 16, 16])
        self.assertTrue((opened <= self.z + 1e-12).all())
        self.assertGreater(float((opened - self.base).min()), -0.2)


class FilterTest(unittest.TestCase):
    """Los filtros de RF-016-08 con las cifras justo en su valor y un poco más allá: bloques de altura y área contadas
    a mano, sobre un terreno llano de 40 × 40 celdas (apertura de 11 m: un bloque de 6 × 6 celdas no la deja pasar)."""

    def block(self, *, height: float = 3.0, rows: tuple[int, int] = (10, 15), cols: tuple[int, int] = (10, 15),
              step_m: float = 1.0) -> tuple[object, np.ndarray]:
        grid = sdata.window_grid(step_m, SMALL_M * step_m)
        z = np.zeros(grid.shape)
        z[rows[0]:rows[1] + 1, cols[0]:cols[1] + 1] = height
        return grid, z

    def run_case(self, grid: object, z: np.ndarray, *, perimeter: np.ndarray | None = None,
                 marked: np.ndarray | None = None, **changes: float) -> object:
        wanted = {**dict(open_diameter_m=SMALL_OPEN_M, min_height_m=1.0, min_area_m2=36.0, max_area_m2=36.0),
                  **changes}
        everywhere = np.ones(grid.shape, dtype=bool) if perimeter is None else perimeter
        return stockpiles.find_candidates(z, grid, everywhere, marked, cparams(**wanted))

    def test_the_minimum_height_is_strict(self) -> None:
        """``z − apertura > altura mínima``: un bloque de 1 m con la altura mínima en 1 m no es candidato (las 36 celdas
        valen justo 1 m: no la superan) y con 1,001 m sí (el área, 36 m², es la mínima y la máxima: ambas incluidas)."""
        grid, flat = self.block(height=1.0)
        found = self.run_case(grid, flat)
        self.assertEqual((len(found.items), found.zones), (0, 0))
        grid, tall = self.block(height=1.001)
        found = self.run_case(grid, tall)
        self.assertEqual((len(found.items), found.zones, found.too_small, found.too_large), (1, 1, 0, 0))
        self.assertEqual(int(found.items[0].zone.sum()), 36)

    def test_the_area_bounds_are_included_and_counted_in_square_metres(self) -> None:
        """Con 36 celdas de 1 m, el área vale 36 m²: la mínima de 36 pasa, la de 36,5 no (``too_small``); la máxima de 36
        pasa y la de 35,5 no (``too_large``)."""
        grid, z = self.block()
        self.assertEqual(len(self.run_case(grid, z, min_area_m2=36.0, max_area_m2=36.0).items), 1)
        small = self.run_case(grid, z, min_area_m2=36.5, max_area_m2=100.0)
        self.assertEqual((len(small.items), small.too_small, small.too_large), (0, 1, 0))
        large = self.run_case(grid, z, min_area_m2=1.0, max_area_m2=35.5)
        self.assertEqual((len(large.items), large.too_small, large.too_large), (0, 0, 1))

    def test_the_area_is_in_square_metres_with_cells_of_two_metres(self) -> None:
        """Con celdas de 2 m, un bloque de 3 × 3 celdas son 36 m² (no 9): pasa con 36 m² como mínimo y máximo, no con
        un mínimo de 36,5 m² ni un máximo de 35,5 m²; el disco de la apertura (11 m: 5,5 celdas de diámetro) no cabe en
        un bloque de 6 m."""
        grid, z = self.block(rows=(10, 12), cols=(10, 12), step_m=2.0)
        found = self.run_case(grid, z)
        self.assertEqual((len(found.items), int(found.items[0].zone.sum())), (1, 9))
        self.assertEqual(found.items[0].footprint.area_m2, 36.0)
        self.assertEqual(self.run_case(grid, z, min_area_m2=36.5, max_area_m2=100.0).too_small, 1)
        self.assertEqual(self.run_case(grid, z, min_area_m2=1.0, max_area_m2=35.5).too_large, 1)

    def test_the_perimeter_cuts_the_zones(self) -> None:
        """«Dentro del perímetro de actuación»: con el perímetro desde la fila 12, la zona son las 24 celdas de dentro
        (4 filas de 6), no las 36, y no llega al área mínima de 36 m²; con todo el perímetro, sí."""
        grid, z = self.block()
        inside = np.zeros(grid.shape, dtype=bool)
        inside[12:, :] = True
        cut = self.run_case(grid, z, perimeter=inside)
        self.assertEqual((len(cut.items), cut.zones, cut.too_small), (0, 1, 1))
        self.assertEqual(len(self.run_case(grid, z, perimeter=inside, min_area_m2=24.0, max_area_m2=24.0).items), 1)
        self.assertEqual(len(self.run_case(grid, z).items), 1)

    def test_a_zone_that_holds_or_overlaps_the_footprint_of_a_mark_is_not_a_candidate(self) -> None:
        """Decisión de la sesión principal sobre RF-016-08 («sin marca»): una zona cuya componente contiene o se solapa
        con la huella de una marca no sale (``on_marks``): la que se solapa en una celda, la que contiene la huella
        entera y la huella que contiene a la zona; la que solo la toca por un lado sin compartir una celda, y la lejana,
        sí. Dos bloques de 36 celdas, el segundo al este."""
        grid, z = self.block()
        z[10:16, 24:30] = 3.0
        far = np.zeros(grid.shape, dtype=bool)
        far[30:34, 30:34] = True

        def mark(rows: tuple[int, int], cols: tuple[int, int]) -> np.ndarray:
            found = np.zeros(grid.shape, dtype=bool)
            found[rows[0]:rows[1] + 1, cols[0]:cols[1] + 1] = True
            return found

        cases = {
            "una celda en la esquina": (mark((15, 15), (15, 15)), 1, 1),
            "una huella dentro de la zona": (mark((11, 13), (11, 13)), 1, 1),
            "la zona dentro de la huella": (mark((8, 17), (8, 17)), 1, 1),
            "pegada, sin compartir celdas": (mark((10, 15), (16, 17)), 0, 2),
            "lejana": (far, 0, 2),
            "ninguna": (None, 0, 2),
        }
        for label, (marked, on_marks, kept) in cases.items():
            found = self.run_case(grid, z, marked=marked, min_area_m2=36.0, max_area_m2=36.0)
            self.assertEqual((found.zones, found.on_marks, len(found.items)), (2, on_marks, kept), label)
            for item in found.items:
                if marked is not None:
                    self.assertFalse((embed(item, item.zone, grid.shape) & marked).any(), label)

    def test_a_plateau_wider_than_the_disk_is_not_a_candidate(self) -> None:
        """La apertura deja pasar lo que cabe el disco: una meseta de 20 × 20 m, más ancha que los 11 m de la apertura, solo
        da sus cuatro esquinas redondeadas (zonas pequeñas, descartadas por el área); su centro no es candidato."""
        grid, z = self.block(height=3.0, rows=(8, 27), cols=(8, 27))
        found = self.run_case(grid, z, min_area_m2=20.0, max_area_m2=500.0)
        opened = brute(brute(z, 11, erode=True), 11, erode=False)
        zones = oracles.hand_zones((z - opened > 1.0).tolist())
        self.assertEqual(len(zones), 4)
        self.assertTrue(all(len(cells) < 20 for cells in zones))
        self.assertEqual((found.zones, found.too_small, len(found.items)), (4, 4, 0))

    def test_a_zone_without_terrain_in_its_footprint_is_rejected_not_listed(self) -> None:
        """RF-016-04: una celda sin dato dentro de la zona deja un hueco que la huella rellena (D-18) y falta terreno en
        ella: A3 rechaza la marca (``des.stockpile_no_terrain``) y el candidato no sale; se cuenta (``rejected``)."""
        grid, z = self.block()
        z[12, 12] = np.nan
        found = self.run_case(grid, z, min_area_m2=30.0, max_area_m2=36.0)
        self.assertEqual((found.zones, len(found.items), found.rejected, found.too_small), (1, 0, 1, 0))

    def test_a_pile_touching_the_edge_of_the_grid_is_not_a_candidate(self) -> None:
        """Consecuencia de la decisión (4) de T05 («lo de fuera de la rejilla no cuenta»): en la esquina de la rejilla el
        disco de la apertura (de 11 m), recortado por el borde, cabe entero en un bloque de 6 × 6 celdas que lo toca (la
        celda de la esquina solo ve 30 celdas del bloque a no más de 5,5 m) y la apertura deja el bloque salvo las 6
        celdas lejanas (las de dx² + dy² > 30,25: (4,4), (4,5), (5,4), (5,5), (3,5) y (5,3)): una zona de 6 m², que el
        filtro del área descarta. Un acopio que toca el borde de la rejilla no es candidato (con una celda de separación,
        sí: la prueba siguiente)."""
        grid, z = self.block(rows=(0, 5), cols=(0, 5))
        found = self.run_case(grid, z)
        self.assertEqual((found.zones, found.too_small, len(found.items)), (1, 1, 0))
        opened = brute(brute(z, 11, erode=True), 11, erode=False)
        self.assertEqual(int((z - opened > 1.0).sum()), 6)

    def test_a_candidate_next_to_the_edge_of_the_grid_is_the_whole_grid_one(self) -> None:
        """Un bloque a una celda de la esquina noroeste: la ventana se recorta a la rejilla y el resultado es el de A2 y
        A3 sobre la rejilla entera."""
        grid, z = self.block(rows=(1, 6), cols=(1, 6))
        found = self.run_case(grid, z)
        self.assertEqual(len(found.items), 1)
        item = found.items[0]
        self.assertEqual((item.window[0].start, item.window[1].start), (0, 0))
        zone = embed(item, item.zone, grid.shape)
        whole = stockpiles.grow_footprint(z, zone, grid, cparams().footprint)
        np.testing.assert_array_equal(embed(item, item.footprint.mask, grid.shape), whole.mask)
        self.assertAlmostEqual(item.footprint.volume_m3 / whole.volume_m3 - 1.0, 0.0, delta=1e-12)

    def test_the_centre_is_that_of_the_footprint_not_of_the_zone(self) -> None:
        """El lugar de un candidato es el centro de su **huella**: un bloque de 6 × 6 celdas de 3 m (la zona) con una
        repisa de 0,5 m al este (4 × 6 celdas, sobre el umbral de la huella pero no de la altura mínima) da una huella de
        10 × 6 celdas, de x = 10 a 20 y de y = 24 a 30 locales: su centro es (15, 27), no el de la zona (13, 27)."""
        grid, z = self.block()
        z[10:16, 16:20] = 0.5
        found = self.run_case(grid, z)
        self.assertEqual(len(found.items), 1)
        item = found.items[0]
        self.assertEqual((int(item.zone.sum()), int(item.footprint.mask.sum())), (36, 60))
        x, y = item.centre
        self.assertAlmostEqual(x, sdata.BASE[0] + 15.0, delta=1e-9)
        self.assertAlmostEqual(y, sdata.BASE[1] + 27.0, delta=1e-9)

    def test_the_cell_keys_are_those_of_the_whole_grid_even_if_it_is_not_square(self) -> None:
        """``cells`` son ``fila · columnas + columna`` de la rejilla **entera** (con 60 columnas y 40 filas el número de
        filas no sirve de paso), sin repetir y ordenadas; el bloque de 6 × 6, al este de una rejilla de 40 × 60."""
        grid = gis.Grid(sdata.BASE[0], sdata.BASE[1] + 40.0, 1.0, 1.0, 60, 40)
        z = np.zeros(grid.shape)
        z[10:16, 40:46] = 3.0
        found = self.run_case(grid, z)
        self.assertEqual(len(found.items), 1)
        item = found.items[0]
        expected = np.flatnonzero(embed(item, item.footprint.mask, grid.shape).ravel())
        np.testing.assert_array_equal(item.cells, expected)
        self.assertEqual(item.cells.size, 36)
        self.assertEqual(int(item.cells[0]), 10 * 60 + 40)

    def test_no_data_around_does_not_count_in_the_opening(self) -> None:
        """«Sin dato» no cuenta en la apertura (T05): una rejilla de cota 3 m con una meseta, rodeada de ``NaN``, no da
        candidatos donde no hay dato; el bloque sí (``NaN`` ya no está encima de nada)."""
        grid, z = self.block()
        z[:, :6] = np.nan
        found = self.run_case(grid, z)
        self.assertEqual(len(found.items), 1)
        self.assertFalse(embed(found.items[0], found.items[0].zone, grid.shape)[:, :6].any())


class WindowTest(unittest.TestCase):
    """A0 (plan 016 §5.4): la ventana de trabajo de una marca y su rejilla, contadas a mano."""

    def test_the_window_of_a_mark_is_its_box_plus_the_reach_and_two_cells(self) -> None:
        """El alcance de A2 y A3 es el margen más la corona exterior (4 + 3 = 7 m) y ``work_window`` añade dos celdas:
        ``⌈7 / lado⌉ + 2`` por cada lado, recortado a la rejilla: 9 celdas con las de 1 m, 6 con las de 2 m."""
        footprint = params_of(margin_m=4.0)
        grid = sdata.window_grid(1.0, 100.0)
        mark = np.zeros(grid.shape, dtype=bool)
        mark[20:26, 30:36] = True
        self.assertEqual(stockpiles.mark_window(mark, grid, footprint), (slice(11, 35), slice(21, 45)))
        mark = np.zeros(grid.shape, dtype=bool)
        mark[2:5, 96:99] = True  # junto al borde norte y al este: se recorta
        self.assertEqual(stockpiles.mark_window(mark, grid, footprint), (slice(0, 14), slice(87, 100)))
        coarse = sdata.window_grid(2.0, 100.0)
        mark = np.zeros(coarse.shape, dtype=bool)
        mark[10:13, 15:18] = True
        self.assertEqual(stockpiles.mark_window(mark, coarse, footprint), (slice(4, 19), slice(9, 24)))
        far = params_of(margin_m=10.0)  # 10 + 3 = 13 m: 15 celdas
        mark = np.zeros(grid.shape, dtype=bool)
        mark[40:43, 50:53] = True
        self.assertEqual(stockpiles.mark_window(mark, grid, far), (slice(25, 58), slice(35, 68)))

    def test_the_window_refuses_a_mark_without_cells_or_of_another_shape(self) -> None:
        grid = sdata.window_grid(1.0, 100.0)
        with self.assertRaises(ValueError):
            stockpiles.mark_window(np.zeros(grid.shape, dtype=bool), grid, params_of())
        with self.assertRaises(ValueError):
            stockpiles.mark_window(np.ones((3, 3), dtype=bool), grid, params_of())

    def test_the_grid_of_a_window_starts_at_the_corner_of_its_first_cell(self) -> None:
        """La esquina noroeste de la ventana es la de su primera celda (``west + columna·dx``, ``north − fila·dy``) y su
        forma, la de la ventana; una ventana vacía o que sale de la rejilla es un ``ValueError``."""
        grid = gis.Grid(500_000.0, 4_400_100.0, 2.0, 2.0, 60, 40)
        place = stockpiles.window_grid(grid, (slice(10, 20), slice(30, 50)))
        self.assertEqual((place.west, place.north, place.dx, place.dy, place.nrows, place.ncols),
                         (500_060.0, 4_400_080.0, 2.0, 2.0, 10, 20))
        for window in ((slice(5, 5), slice(0, 10)), (slice(0, 41), slice(0, 10)), (slice(0, 10), slice(-1, 10)),
                       (slice(0, 10), slice(0, 61))):
            with self.assertRaises(ValueError):
                stockpiles.window_grid(grid, window)


class ParamsTest(unittest.TestCase):
    """Los umbrales de A4 son entrada: sin valor por defecto, con los rangos de ``STOCKPILE_RANGES`` (RF-016-08)."""

    def test_the_params_have_no_default(self) -> None:
        fields = dataclasses.fields(stockpiles.CandidateParams)
        self.assertEqual([field.name for field in fields],
                         ["open_diameter_m", "min_height_m", "min_area_m2", "max_area_m2", "footprint"])
        for field in fields:
            self.assertIs(field.default, dataclasses.MISSING, field.name)
            self.assertIs(field.default_factory, dataclasses.MISSING, field.name)

    def test_values_out_of_range_are_refused_with_their_name(self) -> None:
        for name, value in (("open_diameter_m", 0.0), ("open_diameter_m", -1.0), ("open_diameter_m", 1000.5),
                            ("min_height_m", -0.1), ("min_area_m2", 0.0), ("max_area_m2", 0.0),
                            ("max_area_m2", 2.0e9), ("open_diameter_m", math.nan), ("min_height_m", math.inf)):
            with self.assertRaisesRegex(ValueError, name, msg=f"{name}={value}"):
                cparams(**{name: value})

    def test_the_minimum_area_cannot_pass_the_maximum(self) -> None:
        with self.assertRaisesRegex(ValueError, "min_area_m2"):
            cparams(min_area_m2=200.0, max_area_m2=100.0)
        self.assertEqual(cparams(min_area_m2=100.0, max_area_m2=100.0).max_area_m2, 100.0)

    def test_the_footprint_params_are_footprint_params(self) -> None:
        with self.assertRaises(TypeError):
            stockpiles.CandidateParams(31.0, 2.0, 150.0, 20_000.0, "huella")


# --- D-23: la identidad al repetir ----------------------------------------------------------------------------------------


def hand_carry(new: list[list[int]], previous: list[list[int]]) -> tuple[int | None, ...]:
    """La regla de D-23 a mano, con conjuntos de Python y fracciones: cada pareja cuyas huellas comparten más de la mitad
    del área de **cada una** compite por su decisión; gana la pareja con más celdas comunes (a igualdad, el candidato
    nuevo y después el anterior de índice menor) y cada decisión anterior se conserva una sola vez."""
    pairs = []
    for i, first in enumerate(new):
        for j, second in enumerate(previous):
            shared = len(set(first) & set(second))
            if Fraction(shared) > Fraction(len(set(first)), 2) and Fraction(shared) > Fraction(len(set(second)), 2):
                pairs.append((-shared, i, j))
    found: list[int | None] = [None] * len(new)
    used: set[int] = set()
    for _shared, i, j in sorted(pairs):
        if found[i] is None and j not in used:
            found[i] = j
            used.add(j)
    return tuple(found)


def keys(*cells: int) -> np.ndarray:
    return np.array(cells, dtype=np.int64)


class IdentityRuleTest(unittest.TestCase):
    """RF-016-10, D-23: un candidato conserva su decisión si su huella nueva y la anterior comparten **más de la mitad
    del área de cada una**; si no, se vuelve a preguntar. Las huellas son celdas de la rejilla entera (``cells``)."""

    def test_less_than_half_more_than_half_and_exactly_half(self) -> None:
        """Con huellas de 10 celdas: 4 comunes, no; 5 (justo la mitad), no; 6, sí."""
        previous = [keys(*range(10))]
        for shared, kept in ((4, None), (5, None), (6, 0), (10, 0)):
            fresh = keys(*range(10 - shared, 20 - shared))
            self.assertEqual(len(np.intersect1d(fresh, previous[0])), shared)
            self.assertEqual(stockpiles.carry_decisions([fresh], previous), (kept,), shared)

    def test_it_must_be_more_than_half_of_each_one(self) -> None:
        """«De cada una»: si la nueva contiene la anterior (10 de 10 de la anterior, pero 10 de 30 de la nueva), no; y a la
        inversa (la nueva dentro de la anterior); con 16 de 30 y 16 de 20, sí; con 15 de 30 (justo la mitad de la nueva),
        no."""
        old = keys(*range(10))
        self.assertEqual(stockpiles.carry_decisions([keys(*range(30))], [old]), (None,))
        self.assertEqual(stockpiles.carry_decisions([old], [keys(*range(30))]), (None,))
        fresh = keys(*range(14, 44))
        self.assertEqual(stockpiles.carry_decisions([fresh], [keys(*range(28, 48))]), (0,))
        self.assertEqual(stockpiles.carry_decisions([fresh], [keys(*range(29, 49))]), (None,))

    def test_the_decision_goes_to_the_candidate_that_shares_most(self) -> None:
        """Una decisión se conserva **una vez**: si dos candidatos nuevos se solapan con el mismo anterior, la conserva el
        que comparte más celdas (a igualdad, el primero); y un candidato nuevo que cumple con dos anteriores toma la de
        más celdas comunes."""
        old = keys(*range(10))
        first, second = keys(*range(0, 8)), keys(*range(3, 11))
        self.assertEqual(stockpiles.carry_decisions([first, second], [old]), (0, None))
        self.assertEqual(stockpiles.carry_decisions([second, first], [old]), (None, 0))
        tie = [keys(*range(0, 7)), keys(*range(3, 10))]
        self.assertEqual(stockpiles.carry_decisions(tie, [old]), (0, None))
        wide = keys(*range(0, 12))
        self.assertEqual(stockpiles.carry_decisions([wide], [keys(*range(0, 7)), keys(*range(0, 10))]), (1,))
        self.assertEqual(stockpiles.carry_decisions([wide], [keys(*range(0, 9)), keys(*range(3, 12))]), (0,))

    def test_degenerate_inputs(self) -> None:
        old = [keys(1, 2, 3)]
        self.assertEqual(stockpiles.carry_decisions([], old), ())
        self.assertEqual(stockpiles.carry_decisions([keys(1, 2, 3), keys(7, 8)], []), (None, None))
        self.assertEqual(stockpiles.carry_decisions([keys()], [keys()]), (None,))
        self.assertEqual(stockpiles.carry_decisions([keys(1, 1, 2, 2, 3)], old), (0,))  # los repetidos no cuentan
        # Cinco veces la misma celda y otra: son 2 celdas, de las que 1 está en la anterior (la mitad, no más).
        self.assertEqual(stockpiles.carry_decisions([keys(1, 1, 1, 1, 1, 9)], [keys(1, 2, 3, 4)]), (None,))
        self.assertEqual(stockpiles.carry_decisions([keys(1, 2, 3, 4)], [keys(1, 1, 1, 1, 1, 9)]), (None,))
        for bad in (np.zeros((2, 2), dtype=np.int64), np.array([1.5, 2.5]), np.array([True, False])):
            with self.assertRaises(ValueError):
                stockpiles.carry_decisions([bad], old)

    def test_it_is_the_hand_rule_on_random_cases(self) -> None:
        """Contra la regla a mano (conjuntos y fracciones): 400 casos al azar de huellas que se solapan, con empates."""
        rng = random.Random(23)
        for _ in range(400):
            universe = rng.choice((12, 30, 80))
            fresh = [sorted(rng.sample(range(universe), rng.randint(0, min(universe, 14)))) for _ in range(rng.randint(0, 5))]
            old = [sorted(rng.sample(range(universe), rng.randint(0, min(universe, 14)))) for _ in range(rng.randint(0, 5))]
            self.assertEqual(stockpiles.carry_decisions([keys(*f) for f in fresh], [keys(*o) for o in old]),
                             hand_carry(fresh, old), (fresh, old))

    def test_repeating_the_survey_keeps_the_candidates_and_a_moved_pile_decides_by_the_half(self) -> None:
        """RF-016-10 con la cantera: repetir la detección con otro umbral (altura mínima 2,5 m) da los mismos 8 candidatos
        con las mismas huellas, y cada uno conserva su decisión; si el montículo P1 se corre 6 m al este (el solape es el
        77 % de cada huella) la conserva, y si se corre 15 m (el 42 %), no."""
        grid, perimeter = qfx.GRID, sdata.in_box(qfx.PERIMETER_LOCAL)
        z = sdata.survey()
        marked = marked_cells(grid, z)
        old = stockpiles.find_candidates(z, grid, perimeter, marked, cparams())
        again = stockpiles.find_candidates(z, grid, perimeter, marked, cparams(min_height_m=2.5))
        self.assertEqual(len(again.items), 8)
        self.assertEqual(stockpiles.carry_decisions([item.cells for item in again.items],
                                                    [item.cells for item in old.items]), tuple(range(8)))
        def holder(found: object, mound: object) -> int:
            return next(k for k, item in enumerate(found.items)
                        if embed(item, item.zone, grid.shape)[cell_of(grid, mound)])

        pile = sdata.survey_mound("P1")
        index = holder(old, pile)
        for shift, expected in ((6.0, index), (15.0, None)):
            moved = tuple(m.moved(shift, 0.0) if m.name == "P1" else m for m in sdata.SURVEY_MOUNDS)
            z2 = sdata.previous_survey() + sdata.mound_heights(grid.shape, 1.0, moved)
            new = stockpiles.find_candidates(z2, grid, perimeter, marked, cparams())
            self.assertEqual(len(new.items), 8, shift)
            mapping = stockpiles.carry_decisions([item.cells for item in new.items], [item.cells for item in old.items])
            slot = holder(new, pile.moved(shift, 0.0))
            self.assertEqual(mapping[slot], expected, shift)
            self.assertEqual([m for k, m in enumerate(mapping) if k != slot], [k for k in range(8) if k != index], shift)


if __name__ == "__main__":
    unittest.main()
