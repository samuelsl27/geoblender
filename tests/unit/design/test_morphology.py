# SPDX-License-Identifier: GPL-3.0-or-later
"""La morfología con un disco exacto (spec 016, T05; RF-016-02, RF-016-08; RNF-016-01, RNF-016-03,
RNF-016-04; plan 016 A1, §2.1, §5.7 P-6, D-13).

:mod:`design.morphology` da la erosión, la dilatación, la apertura y el cierre con un disco de radio
``r`` celdas (las celdas ``(dy, dx)`` con ``dx² + dy² ≤ r²``), en escala de grises y binarias, y el
relleno de huecos. Se compara con la **fuerza bruta** (cada celda contra cada desplazamiento del
disco, con enteros: ``4 (dx² + dy²) ≤ (2 r)²``) con radios de 1 a 31 m de media en media celda, en
matrices pequeñas (el disco sale de la rejilla: los bordes) y en una de 100 × 110 con el disco de
31 m de diámetro; la apertura por bandas, igual **bit a bit** que la de una pieza; ``NaN`` como «sin
dato»; los tipos; los rechazos; la variante por pasos (mismo resultado, un paso por banda con
presupuesto 0 y pasos de ≤ 0,05 s con el de la interfaz, sobre filas de 1.699 columnas, como la
rejilla de ``plan.md`` §7.3); y ``fill_holes`` frente a una inundación de referencia.
"""

from __future__ import annotations

import time
import unittest
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np

from tests.support.package import import_geoblender

morphology = import_geoblender("design.morphology")

HALF_CELLS = tuple(range(2, 63))  # 2 r de 1 a 31 m en pasos de media celda


def disk_offsets(twice_radius: int) -> list[tuple[int, int]]:
    """Los desplazamientos ``(dy, dx)`` del disco de radio ``twice_radius / 2`` celdas (oráculo, con
    enteros: ``4 (dx² + dy²) ≤ (2 r)²``, sin raíces ni redondeos)."""
    reach = twice_radius // 2
    return [(dy, dx) for dy in range(-reach, reach + 1) for dx in range(-reach, reach + 1)
            if 4 * (dx * dx + dy * dy) <= twice_radius * twice_radius]


def brute(a: np.ndarray, twice_radius: int, *, erode: bool) -> np.ndarray:
    """La fuerza bruta: el mínimo (``erode``) o el máximo de ``a`` en cada celda y en cada
    desplazamiento del disco que cae dentro de la rejilla (lo de fuera no cuenta; el ``NaN``, tampoco:
    ``fmin`` y ``fmax``, con ``NaN`` si no hay ningún dato)."""
    rows, cols = a.shape
    combine: Callable[..., Any]
    if a.dtype.kind == "f":
        combine = np.fmin if erode else np.fmax
    else:
        combine = np.minimum if erode else np.maximum
    out = a.copy()  # el desplazamiento (0, 0) está en todo disco
    for dy, dx in disk_offsets(twice_radius):
        if dy == 0 and dx == 0:
            continue
        top, bottom = max(0, -dy), min(rows, rows - dy)
        left, right = max(0, -dx), min(cols, cols - dx)
        if top >= bottom or left >= right:
            continue
        out[top:bottom, left:right] = combine(out[top:bottom, left:right],
                                              a[top + dy:bottom + dy, left + dx:right + dx])
    return out


def terrain(shape: tuple[int, int], seed: int, dtype: Any = np.float64) -> np.ndarray:
    """Una superficie con relieve y ruido (cotas con muchos valores distintos)."""
    rng = np.random.default_rng(seed)
    rows, cols = shape
    y, x = np.mgrid[0:rows, 0:cols]
    base = 100.0 + 3.0 * np.sin(x / 5.0) * np.cos(y / 7.0) + 0.02 * (x + y)
    return (base + rng.normal(0.0, 0.5, shape)).astype(dtype)


def same_bits(case: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """``got`` y ``expected`` son la misma rejilla, con el mismo tipo y los mismos bytes."""
    case.assertEqual(got.dtype, expected.dtype)
    case.assertEqual(got.shape, expected.shape)
    case.assertEqual(got.tobytes(), expected.tobytes())


class DiskTest(unittest.TestCase):
    """RF-016-02, RF-016-08 (plan 016 A1): el disco es exacto, no una aproximación."""

    def test_the_disk_is_the_lattice_points_within_the_radius(self) -> None:
        """Dilatar una celda da el disco: sus celdas son las de la cuenta a mano (los puntos de la
        retícula a distancia ≤ r: 5, 9, 13, 21, 29, 81, 317; 749 con 15,5 y 3.001 con 31)."""
        counts = {1.0: 5, 1.5: 9, 2.0: 13, 2.5: 21, 3.0: 29, 5.0: 81, 10.0: 317, 15.5: 749, 31.0: 3001}
        for radius, expected in counts.items():
            with self.subTest(radius=radius):
                grid = np.zeros((81, 83), dtype=bool)
                grid[40, 41] = True
                got = morphology.dilate(grid, radius, 1.0)
                self.assertEqual(int(got.sum()), expected)
                found = {(int(y) - 40, int(x) - 41) for y, x in zip(*np.nonzero(got), strict=True)}
                self.assertEqual(found, set(disk_offsets(int(2 * radius))))

    def test_the_radius_is_in_meters_over_the_cell_side(self) -> None:
        """El radio es en metros: el mismo disco con celdas de 1 m, de 0,5 m y de 2 m; y un cociente que
        se queda una unidad en el último decimal por debajo del entero (0,3 / 0,1) sigue siendo 3."""
        a = terrain((40, 44), 1)
        expected = morphology.erode(a, 15.5, 1.0)
        for radius_m, cell in ((7.75, 0.5), (31.0, 2.0), (15.5, 1.0), (3.1, 0.2)):
            with self.subTest(radius_m=radius_m, cell=cell):
                same_bits(self, morphology.erode(a, radius_m, cell), expected)
        same_bits(self, morphology.erode(a, 0.3, 0.1), brute(a, 6, erode=True))
        same_bits(self, morphology.dilate(a, 0.7, 0.1), brute(a, 14, erode=False))

    def test_a_radius_under_one_cell_is_the_identity(self) -> None:
        """Un disco de una sola celda (radio 0 o menor que una celda) deja la rejilla como estaba."""
        a = terrain((9, 11), 2)
        for radius in (0.0, 0.4, 0.999):
            for function in (morphology.erode, morphology.dilate, morphology.opening, morphology.closing):
                with self.subTest(radius=radius, function=function.__name__):
                    got = function(a, radius, 1.0)
                    same_bits(self, got, a)
                    self.assertIsNot(got, a)


class BruteForceTest(unittest.TestCase):
    """RF-016-02, RF-016-08 (plan 016 A1, RNF-016-01): la erosión y la dilatación son iguales a la
    fuerza bruta con discos de 1 a 31 m, de media en media celda."""

    def test_float_grid_with_every_radius(self) -> None:
        """Una rejilla de reales de 23 × 29 (el disco sale de ella: los bordes y el recorte del alcance):
        los 61 radios, erosión y dilatación; y la apertura y el cierre, que son su composición, con uno
        de cada cuatro (la composición de dos fuerzas brutas es lo que más cuesta de la prueba)."""
        a = terrain((23, 29), 3)
        for twice in HALF_CELLS:
            radius = twice / 2.0
            with self.subTest(radius=radius):
                eroded = brute(a, twice, erode=True)
                dilated = brute(a, twice, erode=False)
                same_bits(self, morphology.erode(a, radius, 1.0), eroded)
                same_bits(self, morphology.dilate(a, radius, 1.0), dilated)
                if twice % 4 == 3 or twice < 8:
                    same_bits(self, morphology.opening(a, radius, 1.0),
                              brute(eroded, twice, erode=False))
                    same_bits(self, morphology.closing(a, radius, 1.0),
                              brute(dilated, twice, erode=True))

    def test_the_disk_of_31_m_of_diameter_on_a_grid_bigger_than_its_disk(self) -> None:
        """Una rejilla de 100 × 110 con el disco de 31 m de diámetro (r = 15,5, el de P-6) y con el de 31 m
        de radio: sale de la rejilla por todos lados y cabe por el centro."""
        a = terrain((100, 110), 4)
        for twice in (31, 62):
            with self.subTest(radius=twice / 2.0):
                same_bits(self, morphology.erode(a, twice / 2.0, 1.0), brute(a, twice, erode=True))
                same_bits(self, morphology.dilate(a, twice / 2.0, 1.0), brute(a, twice, erode=False))

    def test_masks_with_every_radius(self) -> None:
        """Máscaras (``bool``): la erosión es el ``Y`` de su disco y la dilatación, el ``O``; devuelven
        ``bool``; con todos los radios, y con la rejilla llena y la vacía."""
        rng = np.random.default_rng(5)
        mask = rng.random((23, 29)) < 0.8
        for twice in HALF_CELLS:
            with self.subTest(radius=twice / 2.0):
                eroded = morphology.erode(mask, twice / 2.0, 1.0)
                self.assertEqual(eroded.dtype, np.bool_)
                np.testing.assert_array_equal(eroded, brute(mask, twice, erode=True))
                np.testing.assert_array_equal(morphology.dilate(mask, twice / 2.0, 1.0),
                                              brute(mask, twice, erode=False))
        for value in (True, False):
            full = np.full((12, 15), value)
            for function in (morphology.erode, morphology.dilate, morphology.opening, morphology.closing):
                with self.subTest(full=value, function=function.__name__):
                    np.testing.assert_array_equal(function(full, 4.5, 1.0), full)

    def test_an_island_survives_the_opening_only_if_the_disk_fits(self) -> None:
        """La apertura de una máscara deja lo que cabe un disco: un cuadrado de 9 × 9 se queda, con una
        apertura de radio 4, en el único disco que cabe (49 celdas: las esquinas desaparecen) y
        desaparece con la de radio 5; y el cierre rellena un agujero de una celda con radio 1 (y no un
        hueco de 3 × 3)."""
        mask = np.zeros((30, 30), dtype=bool)
        mask[10:19, 10:19] = True
        opened = morphology.opening(mask, 4.0, 1.0)
        self.assertEqual(int(opened.sum()), 49)
        self.assertEqual({(int(y) - 14, int(x) - 14) for y, x in zip(*np.nonzero(opened), strict=True)},
                         set(disk_offsets(8)))
        self.assertFalse(morphology.opening(mask, 5.0, 1.0).any())
        pierced = np.ones((12, 12), dtype=bool)
        pierced[5, 5] = False
        self.assertTrue(morphology.closing(pierced, 1.0, 1.0).all())
        hole = np.ones((12, 12), dtype=bool)
        hole[4:7, 4:7] = False
        self.assertFalse(morphology.closing(hole, 1.0, 1.0)[5, 5])

    def test_the_order_of_the_composition_and_the_two_inequalities(self) -> None:
        """``abrir(a) ≤ a ≤ cerrar(a)`` en toda celda, también junto al borde, y la apertura es la
        dilatación de la erosión (y el cierre, la erosión de la dilatación)."""
        a = terrain((40, 47), 6)
        for radius in (1.0, 3.5, 8.0, 15.5):
            with self.subTest(radius=radius):
                opened = morphology.opening(a, radius, 1.0)
                closed = morphology.closing(a, radius, 1.0)
                self.assertTrue((opened <= a).all())
                self.assertTrue((closed >= a).all())
                same_bits(self, opened, morphology.dilate(morphology.erode(a, radius, 1.0), radius, 1.0))
                same_bits(self, closed, morphology.erode(morphology.dilate(a, radius, 1.0), radius, 1.0))

    def test_the_opening_removes_what_sticks_out_more_than_the_disk(self) -> None:
        """RF-016-08: una cúpula pequeña sobre un llano desaparece con la apertura y deja su altura
        completa en ``z − apertura``; un cerro ancho (que cabe el disco) se queda."""
        z = np.full((60, 80), 100.0)
        z[10:14, 10:14] = 105.0   # 4 × 4: no cabe un disco de 5 m de diámetro
        z[30:50, 30:60] = 108.0   # 20 × 30: sí cabe
        opened = morphology.opening(z, 2.5, 1.0)  # diámetro 5 m
        self.assertEqual(float(opened[11, 11]), 100.0)
        self.assertEqual(float((z - opened)[11, 11]), 5.0)
        self.assertEqual(float(opened[40, 45]), 108.0)
        self.assertEqual(float((z - opened)[40, 45]), 0.0)


class BandsTest(unittest.TestCase):
    """RF-016-02, RF-016-08; RNF-016-03, RNF-016-04 (plan 016 A1): por bandas de filas, igual bit a bit
    que de una pieza."""

    def test_the_opening_and_the_closing_by_bands_are_the_one_piece_ones(self) -> None:
        """Con bandas de 1, 3, 7, 32 y 100 filas (que no dividen las 70 de la rejilla: la última es
        más corta) y varios radios (más y menos que la banda)."""
        a = terrain((70, 83), 7)
        for radius, bands in ((2.0, (1, 3, 7, 32, 100)), (7.5, (3, 7, 32, 100)), (15.5, (7, 32, 100))):
            once = {function.__name__: function(a, radius, 1.0)
                    for function in (morphology.erode, morphology.dilate, morphology.opening,
                                     morphology.closing)}
            for rows in bands:
                for function in (morphology.erode, morphology.dilate, morphology.opening,
                                 morphology.closing):
                    with self.subTest(radius=radius, band_rows=rows, function=function.__name__):
                        same_bits(self, function(a, radius, 1.0, band_rows=rows), once[function.__name__])

    def test_bands_with_nodata_masks_and_other_types(self) -> None:
        """Lo mismo con ``NaN``, con máscaras, con enteros y con ``float32``."""
        rng = np.random.default_rng(8)
        withnan = terrain((50, 61), 9)
        withnan[rng.random(withnan.shape) < 0.3] = np.nan
        withnan[10:25, 20:40] = np.nan
        grids = {"nan": withnan, "mask": rng.random((50, 61)) < 0.6,
                 "int": rng.integers(-50, 50, (50, 61)).astype(np.int16),
                 "float32": terrain((50, 61), 10, np.float32)}
        for name, grid in grids.items():
            for radius in (3.0, 9.5):
                with self.subTest(grid=name, radius=radius):
                    same_bits(self, morphology.opening(grid, radius, 1.0, band_rows=9),
                              morphology.opening(grid, radius, 1.0))
                    same_bits(self, morphology.closing(grid, radius, 1.0, band_rows=32),
                              morphology.closing(grid, radius, 1.0))

    def test_the_input_is_not_modified_and_the_result_is_new(self) -> None:
        a = terrain((30, 33), 11)
        before = a.copy()
        for function in (morphology.erode, morphology.dilate, morphology.opening, morphology.closing):
            got = function(a, 4.0, 1.0, band_rows=8)
            same_bits(self, a, before)
            self.assertFalse(np.shares_memory(got, a))


class DataTest(unittest.TestCase):
    """Los tipos, ``NaN`` como «sin dato», los bordes y los rechazos."""

    def test_nodata_is_neutral_and_an_empty_disk_is_nodata(self) -> None:
        """``NaN`` no cuenta (``fmin`` y ``fmax`` de la fuerza bruta) y una celda cuyo disco entero no
        tiene dato sale ``NaN``; el resto, finitas."""
        a = terrain((26, 30), 12)
        rng = np.random.default_rng(13)
        a[rng.random(a.shape) < 0.25] = np.nan
        a[3:20, 4:22] = np.nan
        for twice in (2, 3, 5, 8, 11):
            with self.subTest(radius=twice / 2.0):
                eroded = morphology.erode(a, twice / 2.0, 1.0)
                same_bits(self, eroded, brute(a, twice, erode=True))
                same_bits(self, morphology.dilate(a, twice / 2.0, 1.0), brute(a, twice, erode=False))
        eroded = morphology.erode(a, 1.5, 1.0)
        self.assertTrue(np.isnan(eroded[10, 10]))
        self.assertTrue(np.isfinite(morphology.erode(a, 8.0, 1.0)[10, 10]))
        self.assertFalse(np.isinf(eroded).any())

    def test_the_opening_with_nodata_never_lifts_a_cell(self) -> None:
        """Con huecos sin dato, la apertura no sube ninguna celda con dato por encima de su cota."""
        a = terrain((40, 40), 14)
        a[15:30, 15:30] = np.nan
        opened = morphology.opening(a, 5.5, 1.0)
        both = np.isfinite(a) & np.isfinite(opened)
        self.assertTrue(both.any())
        self.assertTrue((opened[both] <= a[both]).all())

    def test_the_types_are_kept(self) -> None:
        """``bool``, enteros con y sin signo (el neutro de su tipo) y ``float32``: el mismo tipo a la
        salida y la fuerza bruta."""
        rng = np.random.default_rng(15)
        for dtype in (np.int8, np.int32, np.int64, np.uint8, np.uint16, np.float32, np.float64):
            grid = (rng.integers(0, 120, (21, 24))).astype(dtype)
            for twice in (3, 6, 13):
                with self.subTest(dtype=np.dtype(dtype).name, radius=twice / 2.0):
                    eroded = morphology.erode(grid, twice / 2.0, 1.0)
                    self.assertEqual(eroded.dtype, grid.dtype)
                    np.testing.assert_array_equal(eroded, brute(grid, twice, erode=True))
                    np.testing.assert_array_equal(morphology.dilate(grid, twice / 2.0, 1.0),
                                                  brute(grid, twice, erode=False))

    def test_the_border_does_not_erode_and_does_not_grow(self) -> None:
        """Lo de fuera de la rejilla no cuenta: una máscara que ocupa toda una fila de borde no se
        erosiona desde él, y una celda de borde dilata solo hacia dentro."""
        mask = np.zeros((10, 10), dtype=bool)
        mask[:, :4] = True
        eroded = morphology.erode(mask, 2.0, 1.0)
        self.assertTrue(eroded[:, :2].all())          # pegada al borde: no se erosiona
        self.assertFalse(eroded[:, 2:].any())          # lejos del borde, sí
        one = np.zeros((10, 10), dtype=bool)
        one[0, 0] = True
        self.assertEqual(int(morphology.dilate(one, 2.0, 1.0).sum()), 6)  # el cuarto de disco de r = 2

    def test_empty_grids(self) -> None:
        for shape in ((0, 5), (5, 0), (0, 0)):
            for function in (morphology.erode, morphology.dilate, morphology.opening, morphology.closing):
                with self.subTest(shape=shape, function=function.__name__):
                    got = function(np.zeros(shape), 3.0, 1.0)
                    self.assertEqual(got.shape, shape)

    def test_program_errors(self) -> None:
        """Lo que no es una rejilla, un radio o un lado válidos, o tiene infinitos, se rechaza."""
        good = np.zeros((5, 6))
        cases: list[tuple[str, Callable[[], Any]]] = [
            ("1D", lambda: morphology.erode(np.zeros(6), 1.0, 1.0)),
            ("3D", lambda: morphology.dilate(np.zeros((2, 3, 4)), 1.0, 1.0)),
            ("complex", lambda: morphology.erode(np.zeros((3, 3), dtype=complex), 1.0, 1.0)),
            ("text", lambda: morphology.opening(np.array([["a", "b"]]), 1.0, 1.0)),
            ("inf", lambda: morphology.erode(np.array([[1.0, np.inf]]), 1.0, 1.0)),
            ("-inf", lambda: morphology.dilate(np.array([[1.0, -np.inf]]), 1.0, 1.0)),
            ("negative radius", lambda: morphology.erode(good, -1.0, 1.0)),
            ("nan radius", lambda: morphology.erode(good, float("nan"), 1.0)),
            ("inf radius", lambda: morphology.erode(good, float("inf"), 1.0)),
            ("bool radius", lambda: morphology.erode(good, True, 1.0)),
            ("text radius", lambda: morphology.erode(good, "2", 1.0)),
            ("zero cell", lambda: morphology.erode(good, 1.0, 0.0)),
            ("negative cell", lambda: morphology.closing(good, 1.0, -1.0)),
            ("nan cell", lambda: morphology.closing(good, 1.0, float("nan"))),
            ("zero band", lambda: morphology.erode(good, 1.0, 1.0, band_rows=0)),
            ("fractional band", lambda: morphology.erode(good, 1.0, 1.0, band_rows=2.5)),
            ("bool band", lambda: morphology.erode(good, 1.0, 1.0, band_rows=True)),
            ("steps 1D", lambda: morphology.opening_steps(np.zeros(6), 1.0, 1.0)),
            ("steps radius", lambda: morphology.erode_steps(good, -1.0, 1.0)),
            ("steps inf", lambda: morphology.closing_steps(np.array([[np.inf]]), 1.0, 1.0)),
            ("fill 1D", lambda: morphology.fill_holes(np.zeros(6, dtype=bool))),
            ("fill 3D", lambda: morphology.fill_holes(np.zeros((2, 2, 2), dtype=bool))),
        ]
        for name, call in cases:
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    call()


class StepsTest(unittest.TestCase):
    """RNF-016-03 (plan 016 A1, §5.3.2): por pasos, con el mismo resultado."""

    @staticmethod
    def steps_of(function: Callable[..., Any], a: np.ndarray, radius: float, **kwargs: Any
                 ) -> tuple[list[Any], np.ndarray]:
        found = list(function(a, radius, 1.0, **kwargs))
        return found, found[-1].result

    def test_the_steps_end_with_the_same_result(self) -> None:
        """El último ``Progress`` (fase ``morphology``) lleva lo mismo que la llamada directa y ninguno
        de los demás lleva resultado; las cuatro, con reales con ``NaN`` y con máscaras."""
        withnan = terrain((75, 40), 16)
        withnan[20:30, 5:15] = np.nan
        grids = (terrain((75, 40), 17), withnan, np.random.default_rng(18).random((75, 40)) < 0.7)
        pairs = ((morphology.erode_steps, morphology.erode), (morphology.dilate_steps, morphology.dilate),
                 (morphology.opening_steps, morphology.opening),
                 (morphology.closing_steps, morphology.closing))
        for grid in grids:
            for steps, direct in pairs:
                with self.subTest(function=steps.__name__, dtype=grid.dtype.name):
                    before = grid.copy()
                    found, done = self.steps_of(steps, grid, 6.5)
                    self.assertTrue(all(step.phase == "morphology" for step in found))
                    self.assertTrue(all(step.result is None for step in found[:-1]))
                    self.assertEqual(found[-1].done, found[-1].total)
                    same_bits(self, done, direct(grid, 6.5, 1.0))
                    same_bits(self, grid, before)

    def test_without_budget_each_band_is_a_step_and_the_opening_is_two_phases(self) -> None:
        """Con presupuesto 0, un paso por banda de 32 filas: la apertura de 75 filas son 3 bandas
        erosionadas y 3 dilatadas (6 pasos) y el último, con el resultado; la erosión, 3 + 1."""
        a = terrain((75, 40), 19)
        self.assertEqual(morphology.BAND_ROWS, 32)
        found, done = self.steps_of(morphology.opening_steps, a, 6.5, budget_s=0.0)
        self.assertEqual(len(found), 6 + 1)
        same_bits(self, done, morphology.opening(a, 6.5, 1.0))
        found, _done = self.steps_of(morphology.erode_steps, a, 6.5, budget_s=0.0)
        self.assertEqual(len(found), 3 + 1)

    def test_a_step_never_holds_the_thread_for_more_than_0_05_s(self) -> None:
        """RNF-016-03: con el presupuesto de la interfaz, ninguna llamada pasa de 0,05 s de CPU, y
        cede más de una vez. Filas de 1.699 columnas (como la rejilla de ``plan.md`` §7.3) con el disco
        de 31 m de diámetro."""
        a = terrain((192, 1699), 20)
        steps = morphology.opening_steps(a, 15.5, 1.0)
        longest, count = 0.0, 0
        while True:
            started = time.process_time()
            try:
                step = next(steps)
            except StopIteration:
                break
            longest = max(longest, time.process_time() - started)
            count += 1
            if step.result is not None:
                break
        self.assertGreater(count, 2)
        self.assertLessEqual(longest, 0.05)

    def test_closing_halfway_is_clean(self) -> None:
        """Cerrar el generador a mitad no deja nada ni se queja."""
        a = terrain((100, 30), 21)
        steps = morphology.opening_steps(a, 5.0, 1.0, budget_s=0.0)
        next(steps)
        steps.close()
        same_bits(self, a, terrain((100, 30), 21))

    def test_the_rejections_come_on_the_call(self) -> None:
        """Los rechazos salen en la llamada, antes de dar ningún paso (como ``nearest_value_steps``)."""
        with self.assertRaises(ValueError):
            morphology.opening_steps(np.zeros((4, 4)), -1.0, 1.0)


def flood_holes(mask: np.ndarray) -> np.ndarray:
    """La referencia de ``fill_holes``: lo que no es de la máscara y se alcanza desde fuera de la rejilla
    por celdas que tampoco lo son (4-conexión) es exterior; el resto de lo que no es de la máscara, hueco."""
    rows, cols = mask.shape
    seen = np.zeros(mask.shape, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for r in range(rows):
        for c in range(cols):
            if (r in (0, rows - 1) or c in (0, cols - 1)) and not mask[r, c]:
                seen[r, c] = True
                queue.append((r, c))
    while queue:
        r, c = queue.popleft()
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < rows and 0 <= nc < cols and not mask[nr, nc] and not seen[nr, nc]:
                seen[nr, nc] = True
                queue.append((nr, nc))
    return mask | ~(seen | mask)


class FillHolesTest(unittest.TestCase):
    """RF-016-02 (D-18; plan 016 A1): los huecos interiores se rellenan; lo que toca el borde, no."""

    @staticmethod
    def grid(text: str) -> np.ndarray:
        return np.array([[ch == "#" for ch in line] for line in text.split()], dtype=bool)

    def test_a_ring_is_filled_and_a_cup_open_to_the_border_is_not(self) -> None:
        ring = self.grid("""
            .......
            .#####.
            .#...#.
            .#...#.
            .#####.
            .......
        """)
        filled = morphology.fill_holes(ring)
        self.assertEqual(int(filled.sum()), 5 * 4)
        np.testing.assert_array_equal(filled[1:5, 1:6], True)
        cup = self.grid("""
            #####
            #...#
            #...#
            .....
        """)
        np.testing.assert_array_equal(morphology.fill_holes(cup), cup)  # abierta por abajo: no es un hueco
        closed_by_the_border = self.grid("""
            #...#
            #...#
            #####
        """)
        np.testing.assert_array_equal(morphology.fill_holes(closed_by_the_border), closed_by_the_border)

    def test_two_holes_and_an_island_inside_a_hole(self) -> None:
        """Dos huecos; y un islote dentro de un hueco: el hueco se rellena y el islote, que ya es de la
        máscara, se queda."""
        two = self.grid("""
            ..........
            .########.
            .#..#..#..
            .########.
            ..........
        """)
        got = morphology.fill_holes(two)
        self.assertTrue(got[2, 2] and got[2, 3] and got[2, 5] and got[2, 6])
        self.assertFalse(got[2, 9])  # el borde derecho está abierto: no es un hueco
        nested = self.grid("""
            .........
            .#######.
            .#.....#.
            .#.###.#.
            .#.....#.
            .#######.
            .........
        """)
        got = morphology.fill_holes(nested)
        self.assertEqual(int(got[1:6, 1:8].sum()), 5 * 7)
        self.assertEqual(int(got.sum()), 5 * 7)

    def test_four_connected_holes_are_filled_across_a_diagonal_gap(self) -> None:
        """La conexión es la de las zonas de ``label_components`` (4): un hueco que solo se une al
        exterior por una diagonal está encerrado y se rellena."""
        leaky = self.grid("""
            ........
            ..####..
            ..#..#..
            ..#..##.
            ...###..
            ........
        """)
        got = morphology.fill_holes(leaky)
        self.assertTrue(got[2, 3] and got[2, 4] and got[3, 3] and got[3, 4])

    def test_trivial_grids_and_types(self) -> None:
        np.testing.assert_array_equal(morphology.fill_holes(np.ones((4, 5), dtype=bool)), True)
        self.assertFalse(morphology.fill_holes(np.zeros((4, 5), dtype=bool)).any())
        self.assertEqual(morphology.fill_holes(np.zeros((0, 5), dtype=bool)).shape, (0, 5))
        ints = np.array([[0, 1, 1, 1], [0, 1, 0, 1], [0, 1, 1, 1]])
        got = morphology.fill_holes(ints)
        self.assertEqual(got.dtype, np.bool_)
        self.assertTrue(got[1, 2])
        before = ints.copy()
        morphology.fill_holes(ints)
        np.testing.assert_array_equal(ints, before)

    def test_equals_the_flood_in_random_masks(self) -> None:
        """200 máscaras aleatorias de formas y densidades distintas: igual que la inundación de
        referencia desde el borde."""
        rng = np.random.default_rng(22)
        for _ in range(200):
            shape = (int(rng.integers(1, 15)), int(rng.integers(1, 15)))
            mask = rng.random(shape) < rng.uniform(0.2, 0.8)
            np.testing.assert_array_equal(morphology.fill_holes(mask), flood_holes(mask))

    def test_the_hole_counts_in_the_footprint(self) -> None:
        """D-18: un hueco de 4 × 4 dentro de una huella de 10 × 10 se rellena (el área de la huella son
        las 100 celdas, no las 84 de antes)."""
        mask = np.zeros((20, 20), dtype=bool)
        mask[5:15, 5:15] = True
        mask[8:12, 8:12] = False
        self.assertEqual(int(mask.sum()), 100 - 16)
        self.assertEqual(int(morphology.fill_holes(mask).sum()), 100)


if __name__ == "__main__":
    unittest.main()
