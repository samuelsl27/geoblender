# SPDX-License-Identifier: GPL-3.0-or-later
"""Las bases, los espesores y el terreno sin acopios de una detección, y la detección de principio a fin (spec 016,
T09; RF-016-01, RF-016-02, RF-016-03, RF-016-06, RF-016-09; RF-016-07; plan 016 A5 y A0 a A4; ADR-0031 §3; P-4, P-5).

:func:`design.stockpiles.detect_stockpiles` (y :func:`detect_steps`, por pasos) recorre las marcas de un
:class:`StockpileJob` (todo lo leído: rejilla, superficie, marcas con sus celdas, superficies de base propias,
parámetros resueltos, perímetro; nada del proyecto) y da el :class:`StockpileOutcome`: por acopio, su huella (celdas de
la rejilla entera), su plano (o su base propia: sin corona, ajuste ni límite, RF-016-03), su base, su espesor
``máx(z − base, 0)`` (RF-016-01), el terreno sin acopios ``mín(z, base)`` y la superficie con que se detectó, **solo en
sus huellas** (P-4, P-5), y, **por material**, la base y el espesor (D-19). Se prueba con:

- **cuentas a mano**: bloques de altura conocida sobre un terreno llano (volumen, espesor y terreno sin acopios
  contados sobre el papel), con un hueco por debajo de la base y otro por debajo del umbral;
- **implementaciones independientes** (``tests.support.design_oracles``): ``hand_layers`` (A5 celda a celda),
  ``hand_footprint``, ``hand_volume`` y ``hand_share`` (A3), y el ``hand_grow`` de ``test_stockpile_footprint`` (A2 y A3
  enteros), que dan todo lo de la detección a mano sobre la misma ventana;
- **la cantera de la 016** (``tests.support.stockpile_data``): el cono de CE-016-02 con sus celdas atípicas, los dos
  acopios que se tocan de E1 (celdas de 1 m: con 2 m el par es pequeño para la celda, ``docs/trampas.md`` §2) y el
  levantamiento de CE-016-01 con sus cinco marcas, dos materiales, una base propia y los candidatos.
"""

from __future__ import annotations

import dataclasses
import math
import random
import time
import unittest
from contextlib import closing

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design.test_stockpile_candidates import cparams
from tests.unit.design.test_stockpile_footprint import (MARGIN_M, SPIKES, THRESHOLD_M, expected_codes, hand_grow,
                                                        params_of, small_scene)

gis = import_geoblender("gis")
stockpiles = import_geoblender("design.stockpiles")
provenance = import_geoblender("design.provenance")

NO_CELLS = "des.stockpile_no_cells"
NO_TERRAIN = "des.stockpile_no_terrain"
AT_EDGE = "des.stockpile_footprint_at_edge"
TILT = "des.stockpile_tilt_limited"
SHARED = "des.stockpile_shared_cells"
SEVERAL = "des.stockpile_several_zones"
FEW_FLAT = "des.stockpile_crown_few_flat"
NOT_CONVERGED = "des.stockpile_not_converged"
PLANE_NOTES = (FEW_FLAT, TILT, NOT_CONVERGED)


# --- Ayudas ---------------------------------------------------------------------------------------------------------


def mark_of(key: str, mask: np.ndarray, **more: object) -> object:
    """La marca ``key`` con las celdas de ``mask`` (máscara de la rejilla entera)."""
    return stockpiles.StockpileMark(key=key, cells=np.flatnonzero(mask), **more)


def job_of(grid: object, z: np.ndarray, marks: list, *, params: object = None, bases: dict | None = None,
           candidates: object = None, perimeter: np.ndarray | None = None, name: str = "Detección de prueba",
           code: str = "STK-001") -> object:
    """El trabajo de detección sobre ``z`` con las ``marks`` y los umbrales de D-3 de ``params_of``."""
    return stockpiles.StockpileJob(name=name, code=code, grid=grid, surface=z, marks=tuple(marks),
                                   params=params or params_of(), bases=bases, candidates=candidates,
                                   perimeter=perimeter)


def last_result(steps: object) -> object:
    """Recorre ``steps`` y da el resultado de su último ``Progress``."""
    last = None
    with closing(steps):
        for last in steps:
            pass
    return last.result


def detect(job: object) -> object:
    return stockpiles.detect_stockpiles(job)


def codes_of(notices: object) -> list[str]:
    return [notice.code for notice in notices]


def dense(grid: object, item: object, values: np.ndarray) -> np.ndarray:
    """``values`` (uno por celda de ``item.cells``) en una rejilla entera con NaN fuera de ellas."""
    found = np.full(grid.shape, np.nan)
    rows, cols = np.divmod(item.cells, grid.ncols)
    found[rows, cols] = values
    return found


def mask_of(grid: object, item: object) -> np.ndarray:
    """La huella de ``item`` como máscara de la rejilla entera."""
    return np.isfinite(dense(grid, item, np.zeros(item.cells.size)))


def where(grid: object, row: int, col: int) -> tuple[float, float]:
    x, y = grid.centers()
    return float(x[row, col]), float(y[row, col])


def by_key(outcome: object, key: str) -> object:
    (found,) = [item for item in outcome.stockpiles if item.key == key]
    return found


def check_layers(case: unittest.TestCase, grid: object, z: np.ndarray, item: object, *, delta: float = 1e-9) -> None:
    """Lo que dan A5 y A3 para ``item`` es lo del oráculo ``hand_layers`` sobre su misma huella y su misma base (RF-016-01,
    RF-016-09): el espesor, el terreno sin acopios, la superficie, el volumen y el espesor máximo, y que nada es
    negativo."""
    rows, cols = np.divmod(item.cells, grid.ncols)
    box = (slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1))
    mask = mask_of(grid, item)[box]  # el oráculo recorre la caja de la huella, no la rejilla entera
    base = np.where(mask, dense(grid, item, item.base)[box], 0.0)
    hand = oracles.hand_layers(z[box].tolist(), base.tolist(), mask.tolist(), grid.cell_area, THRESHOLD_M)
    for name in ("base", "thickness", "ground", "surface"):
        expected = np.array([getattr(hand, name)[int(r) - box[0].start, int(c) - box[1].start]
                             for r, c in zip(rows, cols, strict=True)])
        np.testing.assert_allclose(getattr(item, name), expected, rtol=0.0, atol=delta, err_msg=name)
    case.assertGreaterEqual(float(item.thickness.min()), 0.0)
    case.assertAlmostEqual(item.volume_m3 / hand.volume - 1.0, 0.0, delta=delta)
    case.assertAlmostEqual(item.thickness_max_m, hand.thickness_max, delta=delta)
    case.assertEqual(item.area_m2, item.cells.size * grid.cell_area)


# --- A5 con cuentas a mano: un bloque sobre un terreno llano -------------------------------------------------------------

LEVEL_M = 100.0
BLOCK = (20.0, 20.0, 30.0, 30.0)
"""El bloque de 10 × 10 celdas (local) sobre un terreno llano a 100 m."""
BLOCK_M = 2.0
LOW_BOX = (24.0, 24.0, 26.0, 25.0)
"""Dos celdas del hueco del bloque, por debajo de la base (99,0 m)."""
SHALLOW_BOX = (24.0, 25.0, 26.0, 26.0)
"""Otras dos, por encima de la base pero por debajo del umbral de la huella (100,2 m)."""


def block_scene() -> tuple[object, np.ndarray, np.ndarray]:
    """Una ventana de 60 × 60 celdas de 1 m, llana a 100 m, con el bloque de 2 m de alto (100 celdas) y en medio un hueco
    de 2 × 2 celdas: dos celdas a 99,0 m (bajo la base) y dos a 100,2 m (sobre ella, por debajo del umbral de 0,3 m).
    Devuelve la rejilla, la superficie y la marca (14 × 14 celdas en torno al bloque)."""
    grid = sdata.window_grid(1.0, 60.0)
    z = np.full(grid.shape, LEVEL_M)
    z[sdata.in_box(BLOCK, grid)] += BLOCK_M
    z[sdata.in_box(LOW_BOX, grid)] = 99.0
    z[sdata.in_box(SHALLOW_BOX, grid)] = 100.2
    return grid, z, sdata.in_box((18.0, 18.0, 32.0, 32.0), grid)


class BlockTest(unittest.TestCase):
    """A5 con cuentas a mano (RF-016-01, RF-016-09): el espesor ``máx(z − plano, 0)`` (nunca negativo), el terreno sin
    acopios ``mín(z, plano)`` y la superficie, solo en la huella; el volumen y el espesor máximo."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid, cls.z, mark = block_scene()
        cls.outcome = detect(job_of(cls.grid, cls.z, [mark_of("Bloque", mark, material="mineral")]))
        (cls.item,) = cls.outcome.stockpiles

    def expected(self, mine: float, low: float, shallow: float) -> np.ndarray:
        """Un valor por celda de la huella, en su orden: ``mine`` en el bloque, ``low`` en las dos celdas bajas y
        ``shallow`` en las dos someras."""
        grid = self.grid
        low_cells, shallow_cells = (sdata.in_box(box, grid).ravel()[self.item.cells] for box in (LOW_BOX, SHALLOW_BOX))
        return np.where(low_cells, low, np.where(shallow_cells, shallow, mine))

    def test_the_footprint_is_the_block_with_its_hole(self) -> None:
        """RF-016-02, D-18: el bloque de 10 × 10 celdas con el hueco relleno es la huella (100 m²)."""
        self.assertEqual(self.item.cells.tolist(), np.flatnonzero(sdata.in_box(BLOCK, self.grid)).tolist())
        self.assertEqual(self.item.area_m2, 100.0)
        self.assertEqual(self.outcome.notices, ())
        self.assertEqual(self.item.notes, ())

    def test_the_base_is_the_flat_plane(self) -> None:
        """RF-016-02: el plano de la corona de un terreno llano a 100 m es 100 m (≤ 10⁻⁹) y no se inclina."""
        np.testing.assert_allclose(self.item.base, LEVEL_M, rtol=0.0, atol=1e-9)
        self.assertAlmostEqual(self.item.plane.tilt_deg, 0.0, delta=1e-9)
        self.assertAlmostEqual(self.item.plane_level_m, LEVEL_M, delta=1e-9)
        self.assertAlmostEqual(self.item.plane_slope_percent, 0.0, delta=1e-9)
        self.assertIsNone(self.item.base_surface)

    def test_the_thickness_is_never_negative_and_follows_the_formula(self) -> None:
        """RF-016-01: 2,0 m en el bloque, 0 donde el terreno queda bajo la base (nunca −1,0 m) y 0,2 m en el hueco
        somero; el techo (base + espesor) es la superficie donde ésta no baja de la base."""
        np.testing.assert_allclose(self.item.thickness, self.expected(BLOCK_M, 0.0, 0.2), rtol=0.0, atol=1e-9)
        self.assertGreaterEqual(float(self.item.thickness.min()), 0.0)
        self.assertAlmostEqual(self.item.thickness_max_m, BLOCK_M, delta=1e-9)
        top = self.item.base + self.item.thickness
        np.testing.assert_allclose(top, np.maximum(self.item.surface, self.item.base), rtol=0.0, atol=1e-9)

    def test_the_sum_of_the_thickness_is_the_volume_of_the_footprint(self) -> None:
        """RF-016-01, RF-016-09: la suma del espesor por el área de celda, **donde pasa del umbral** (la presencia de la
        011, ``res.anthropic_presence_m``), es el volumen de la huella a ≤ 10⁻⁹ relativo: (100 − 4) celdas · 2 m = 192 m³;
        el espesor de las celdas que no lo pasan (0,2 m en dos) es lo que queda hasta los 192,4 m³ de la suma entera."""
        present = self.item.thickness > THRESHOLD_M
        counted = math.fsum((self.item.thickness[present] * self.grid.cell_area).tolist())
        self.assertAlmostEqual(counted / 192.0 - 1.0, 0.0, delta=1e-9)
        self.assertAlmostEqual(self.item.volume_m3 / 192.0 - 1.0, 0.0, delta=1e-9)
        self.assertAlmostEqual(counted / self.item.volume_m3 - 1.0, 0.0, delta=1e-9)
        self.assertAlmostEqual(math.fsum(self.item.thickness.tolist()), 192.4, delta=1e-9)

    def test_the_ground_without_stockpiles_is_the_lower_of_the_surface_and_the_plane(self) -> None:
        """RF-016-09, P-5: ``mín(z, plano)`` en las celdas de la huella (100 m en el bloque, 99 m en las dos celdas bajas) y
        la superficie con que se detectó ahí; fuera de la huella no hay dato (la compone quien lo lee)."""
        np.testing.assert_allclose(self.item.ground, self.expected(LEVEL_M, 99.0, LEVEL_M), rtol=0.0, atol=1e-9)
        np.testing.assert_array_equal(self.item.surface, self.z.ravel()[self.item.cells])
        ground = self.outcome.ground_grid()
        self.assertEqual(ground.shape, self.grid.shape)
        self.assertEqual(int(np.isfinite(ground).sum()), 100)
        whole = np.where(np.isfinite(ground), ground, self.z)
        np.testing.assert_array_equal(whole[~sdata.in_box(BLOCK, self.grid)], self.z[~sdata.in_box(BLOCK, self.grid)])
        self.assertTrue((whole <= self.z + 1e-9).all())
        # lo que baja el terreno sin acopios es el espesor: z − mín(z, plano) = máx(z − plano, 0), a mano 96 · 2 m
        # del bloque y 2 · 0,2 m del hueco somero
        self.assertAlmostEqual(math.fsum((self.z - whole).ravel().tolist()), 192.4, delta=1e-9)

    def test_the_layers_are_the_hand_layers(self) -> None:
        """RF-016-01, RF-016-09: todo lo anterior, igual que el oráculo ``hand_layers`` celda a celda."""
        check_layers(self, self.grid, self.z, self.item)

    def test_the_dense_grids_are_sparse(self) -> None:
        """P-4: la base y el espesor del material y las otras dos rejillas solo tienen dato en la huella."""
        for found in (self.outcome.base_grid("mineral"), self.outcome.thickness_grid("mineral"),
                      self.outcome.ground_grid(), self.outcome.surface_grid()):
            self.assertEqual(found.shape, self.grid.shape)
            self.assertEqual(int(np.isfinite(found).sum()), 100)
            self.assertTrue(np.isfinite(found[sdata.in_box(BLOCK, self.grid)]).all())
        np.testing.assert_array_equal(self.outcome.thickness_grid("mineral")[sdata.in_box(BLOCK, self.grid)],
                                      self.item.thickness[np.argsort(self.item.cells)])

    def test_the_runs_of_the_footprint(self) -> None:
        """La huella en tramos: una fila del bloque por tramo (fila, primera columna, columna final excluida)."""
        expected = [[row, 20, 30] for row in range(30, 40)]
        self.assertEqual(self.item.runs.tolist(), expected)

    def test_the_stockpile_is_at_its_centre(self) -> None:
        """El lugar de «ir a»: el centro de la huella (el bloque va de x = 20 a 30 m y de y = 20 a 30 m)."""
        self.assertAlmostEqual(self.item.x, sdata.BASE[0] + 25.0, delta=1e-6)
        self.assertAlmostEqual(self.item.y, sdata.BASE[1] + 25.0, delta=1e-6)


# --- Dos materiales (D-19), el orden de los acopios y lo que no se rechaza ------------------------------------------------

MATERIAL_BLOCKS = (
    # (clave, caja del bloque, altura, material)
    ("A", (10.0, 40.0, 20.0, 50.0), 2.0, "mineral"),
    ("B", (40.0, 40.0, 52.0, 52.0), 3.0, "estéril"),
    ("C", (70.0, 40.0, 80.0, 50.0), 1.0, "mineral"),
    ("D", (10.0, 70.0, 22.0, 82.0), 1.5, None),
)


def materials_scene() -> tuple[object, np.ndarray, list]:
    """Una ventana de 100 × 100 celdas llana a 100 m con cuatro bloques a 20 m o más unos de otros: dos de mineral, uno de
    estéril y uno sin material; la marca de cada uno, 2 m mayor que su bloque."""
    grid = sdata.window_grid(1.0, 100.0)
    z = np.full(grid.shape, LEVEL_M)
    marks = []
    for key, (left, bottom, right, top), height, material in MATERIAL_BLOCKS:
        z[sdata.in_box((left, bottom, right, top), grid)] += height
        mark = sdata.in_box((left - 2.0, bottom - 2.0, right + 2.0, top + 2.0), grid)
        marks.append(mark_of(key, mark, material=material, name=f"Acopio {key}"))
    return grid, z, marks


class MaterialsTest(unittest.TestCase):
    """RF-016-09, D-19: dos materiales dan dos bases y dos espesores (y un tercero, sin material)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid, cls.z, cls.marks = materials_scene()
        cls.outcome = detect(job_of(cls.grid, cls.z, cls.marks))
        cls.blocks = {key: sdata.in_box(box, cls.grid) for key, box, _height, _material in MATERIAL_BLOCKS}

    def test_each_block_is_a_stockpile_in_the_order_of_the_job(self) -> None:
        self.assertEqual([item.key for item in self.outcome.stockpiles], ["A", "B", "C", "D"])
        self.assertEqual([item.name for item in self.outcome.stockpiles], [f"Acopio {k}" for k in "ABCD"])
        self.assertEqual([item.material for item in self.outcome.stockpiles], ["mineral", "estéril", "mineral", None])
        for key, block in self.blocks.items():
            self.assertEqual(by_key(self.outcome, key).cells.tolist(), np.flatnonzero(block).tolist(), key)
        self.assertEqual(self.outcome.rejected, ())
        self.assertEqual(self.outcome.shared, ())
        self.assertEqual(self.outcome.notices, ())

    def test_the_materials_come_in_order_of_appearance(self) -> None:
        self.assertEqual(self.outcome.materials, ("mineral", "estéril", None))
        self.assertEqual(self.outcome.count, 4)

    def test_each_material_has_its_own_base_and_thickness(self) -> None:
        """RF-016-09: la base y el espesor de «mineral» tienen dato en A y C y en ninguna otra celda; los de «estéril», en B;
        los del acopio sin material, en D."""
        wanted = {"mineral": (("A", 2.0), ("C", 1.0)), "estéril": (("B", 3.0),), None: (("D", 1.5),)}
        for material, parts in wanted.items():
            base, thick = self.outcome.base_grid(material), self.outcome.thickness_grid(material)
            union = np.zeros(self.grid.shape, dtype=bool)
            for key, height in parts:
                union |= self.blocks[key]
                np.testing.assert_allclose(thick[self.blocks[key]], height, rtol=0.0, atol=1e-9)
            np.testing.assert_array_equal(np.isfinite(base), union, str(material))
            np.testing.assert_array_equal(np.isfinite(thick), union, str(material))
            np.testing.assert_allclose(base[union], LEVEL_M, rtol=0.0, atol=1e-9)

    def test_the_ground_and_the_surface_cover_every_footprint(self) -> None:
        union = np.zeros(self.grid.shape, dtype=bool)
        for block in self.blocks.values():
            union |= block
        ground, surface = self.outcome.ground_grid(), self.outcome.surface_grid()
        np.testing.assert_array_equal(np.isfinite(ground), union)
        np.testing.assert_array_equal(np.isfinite(surface), union)
        np.testing.assert_allclose(ground[union], LEVEL_M, rtol=0.0, atol=1e-9)
        np.testing.assert_array_equal(surface[union], self.z[union])

    def test_an_unknown_material_is_refused(self) -> None:
        for call in (self.outcome.base_grid, self.outcome.thickness_grid):
            with self.assertRaises(ValueError):
                call("grava")

    def test_each_stockpile_is_the_hand_layers(self) -> None:
        for item in self.outcome.stockpiles:
            with self.subTest(item.key):
                check_layers(self, self.grid, self.z, item)

    def test_the_volumes_are_counted_by_hand(self) -> None:
        """RF-016-02: A, 100 celdas · 2 m; B, 144 · 3 m; C, 100 · 1 m; D, 144 · 1,5 m."""
        expected = {"A": 200.0, "B": 432.0, "C": 100.0, "D": 216.0}
        for key, volume in expected.items():
            self.assertAlmostEqual(by_key(self.outcome, key).volume_m3 / volume - 1.0, 0.0, delta=1e-9, msg=key)

    def test_the_order_of_the_marks_in_the_job_is_the_order_of_the_stockpiles(self) -> None:
        reversed_outcome = detect(job_of(self.grid, self.z, self.marks[::-1]))
        self.assertEqual([item.key for item in reversed_outcome.stockpiles], ["D", "C", "B", "A"])
        self.assertEqual(reversed_outcome.materials, (None, "mineral", "estéril"))
        for item in reversed_outcome.stockpiles:
            self.assertEqual(item.cells.tolist(), by_key(self.outcome, item.key).cells.tolist())
            self.assertEqual(item.volume_m3, by_key(self.outcome, item.key).volume_m3)


# --- A2 y A3 hasta A5 contra el oráculo (30 × 30) y CE-016-02 (el cono de 120 × 120 con atípicos) ---------------------------


class HandPlaneTest(unittest.TestCase):
    """RF-016-02, RF-016-07: sobre las escenas pequeñas de ``test_stockpile_footprint`` (un cono o una pirámide de 2 m, con
    atípicos, a 8° o con un cráter), la detección de principio a fin —la huella, el plano en cada celda, el volumen, el
    espesor y el terreno sin acopios— es la del oráculo de A2 y A3 enteros y la de ``hand_layers``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {
            "cono": small_scene("cone"),
            "pirámide con atípicas": small_scene("pyramid", blocks=SPIKES),
            "cono a 8°": small_scene("cone", 8.0),
            "cono con cráter": small_scene("cone", flatten=((13.0, 13.0, 17.0, 17.0),)),
        }
        cls.found = {}
        for what, scene in cls.cases.items():
            outcome = detect(job_of(scene.grid, scene.terrain, [mark_of("Cono", scene.mark)],
                                    params=params_of(margin_m=3.0)))
            hand = hand_grow(scene.terrain, scene.grid, scene.mark, margin_m=3.0)
            cls.found[what] = (scene, outcome, hand)

    def test_the_footprint_the_plane_and_the_volume_are_the_hand_ones(self) -> None:
        """La huella, el plano en cada celda a ≤ 10⁻⁹ relativo, el volumen a ≤ 10⁻⁹ relativo, las vueltas y los avisos."""
        for what, (scene, outcome, hand) in self.found.items():
            with self.subTest(what):
                (item,) = outcome.stockpiles
                self.assertEqual(item.cells.tolist(), np.flatnonzero(hand.found.mask).tolist())
                np.testing.assert_allclose(item.base, hand.base[hand.found.mask], rtol=1e-9)
                self.assertAlmostEqual(item.volume_m3 / hand.volume - 1.0, 0.0, delta=1e-9)
                self.assertEqual((item.turns, item.converged), (hand.turns, hand.converged))
                self.assertEqual(codes_of(item.notes), expected_codes(hand))
                check_layers(self, scene.grid, scene.terrain, item)

    def test_the_8_degree_plane_is_limited_with_its_note(self) -> None:
        """RF-016-07: el plano de 8° con la inclinación máxima de 4° da el aviso con las dos inclinaciones y la nota en el
        acopio (con su marca y su lugar); la inclinación del plano es la limitada y el azimut se conserva."""
        scene, outcome, hand = self.found["cono a 8°"]
        (item,) = outcome.stockpiles
        self.assertTrue(hand.plane.limited)
        (note,) = [note for note in item.notes if note.code == TILT]
        self.assertEqual(note.values["mark"], "Cono")
        self.assertAlmostEqual(note.values["fitted"], 8.0, delta=1e-6)
        self.assertEqual(note.values["limit"], 4.0)
        self.assertAlmostEqual(note.values["x"], item.x, delta=1e-6)
        self.assertAlmostEqual(note.values["y"], item.y, delta=1e-6)
        self.assertIn(TILT, codes_of(outcome.notices))
        self.assertAlmostEqual(item.plane.tilt_deg, 4.0, delta=1e-9)
        self.assertAlmostEqual(item.plane_azimuth_deg, sdata.AZIMUTH_DEG, delta=1e-4)
        self.assertAlmostEqual(item.plane_slope_percent, 100.0 * math.tan(math.radians(4.0)), delta=1e-9)
        figure = [f for f in outcome.figures if f.key == "des.stk_plane_tilt_deg"]
        self.assertEqual(len(figure), 1)
        self.assertAlmostEqual(figure[0].value, 4.0, delta=1e-9)

    def test_the_crater_is_part_of_the_footprint_and_its_thickness_is_zero(self) -> None:
        """D-18, RF-016-01: el cráter del cono (el terreno a la altura del plano) es un hueco que la huella rellena: cuenta
        en el área, no da espesor (0 m) ni volumen, y el terreno sin acopios ahí es el propio terreno."""
        scene, outcome, hand = self.found["cono con cráter"]
        (item,) = outcome.stockpiles
        crater = np.flatnonzero(sdata.in_box((13.0, 13.0, 17.0, 17.0), scene.grid))
        inside = np.isin(item.cells, crater)
        self.assertTrue(inside.any())
        np.testing.assert_allclose(item.thickness[inside], 0.0, rtol=0.0, atol=1e-9)
        self.assertEqual(item.area_m2, float(item.cells.size))

    def test_the_centre_level_is_the_plane_at_the_centre(self) -> None:
        for what, (_scene, outcome, _hand) in self.found.items():
            with self.subTest(what):
                (item,) = outcome.stockpiles
                self.assertAlmostEqual(item.plane_level_m, float(item.plane.at(item.x, item.y)), delta=1e-9)


class ConeTest(unittest.TestCase):
    """CE-016-02: el tronco de cono de la cantera sobre un plano de 3° con sus ocho celdas atípicas y sobre uno de 8° con la
    inclinación máxima de 4°, en la ventana de 120 × 120 celdas: el plano a ≤ 10⁻⁶ m del sintético y el volumen igual al
    cálculo a mano sobre el mismo plano (el oráculo de A2 y A3 enteros, en las escenas pequeñas de arriba)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = {}
        for tilt in (3.0, 8.0):
            case = sdata.mound_case("cone", tilt)
            outcome = detect(job_of(case.grid, case.terrain, [mark_of("Cono", sdata.in_box(case.mark_box, case.grid))]))
            cls.found[tilt] = (case, outcome, outcome.stockpiles[0])

    def test_a_3_degree_plane_is_recovered_with_its_outliers(self) -> None:
        """CE-016-02: el plano a ≤ 10⁻⁶ m del sintético en toda la huella, el espesor igual a la altura del cono, la
        inclinación de 3° con el azimut de 30°; las dos atípicas positivas que caen dentro de la marca son otras dos zonas
        que la tocan (la nota de RF-016-05, 3 zonas) y no entran en la huella."""
        case, outcome, item = self.found[3.0]
        rows, cols = np.divmod(item.cells, case.grid.ncols)
        np.testing.assert_allclose(item.base, case.base[rows, cols], rtol=0.0, atol=1e-6)
        np.testing.assert_allclose(item.thickness, case.height[rows, cols], rtol=0.0, atol=1e-6)
        self.assertEqual(int((case.height > THRESHOLD_M).sum()), item.cells.size)
        self.assertEqual(codes_of(item.notes), [SEVERAL])
        self.assertEqual(item.notes[0].values["zones"], 3)
        self.assertAlmostEqual(item.plane.tilt_deg, 3.0, delta=1e-6)
        self.assertAlmostEqual(item.plane_azimuth_deg, sdata.AZIMUTH_DEG, delta=1e-4)
        self.assertAlmostEqual(item.plane_slope_percent, 100.0 * math.tan(math.radians(3.0)), delta=1e-4)
        check_layers(self, case.grid, case.terrain, item)
        analytic = math.fsum(case.height[case.height > THRESHOLD_M].tolist())
        self.assertAlmostEqual(item.volume_m3 / analytic - 1.0, 0.0, delta=1e-9)  # 1 m, descontado el anillo bajo el umbral

    def test_an_8_degree_plane_is_limited_to_4_with_its_note(self) -> None:
        """RF-016-07: la inclinación máxima de 4° deja el plano en 4° y lo anota; el volumen es el cálculo a mano sobre el
        plano limitado (``hand_layers``) a ≤ 10⁻⁹."""
        case, outcome, item = self.found[8.0]
        self.assertEqual(codes_of(item.notes), [SEVERAL, TILT])
        self.assertAlmostEqual(item.plane.tilt_deg, 4.0, delta=1e-9)
        self.assertAlmostEqual(item.notes[1].values["fitted"], 8.0, delta=0.02)  # las atípicas la mueven 0,01°
        self.assertEqual(codes_of(outcome.notices), [SEVERAL, TILT])
        check_layers(self, case.grid, case.terrain, item)


# --- RF-016-03: la base propia ----------------------------------------------------------------------------------------------

SURVEY_CROP = (slice(148, 212), slice(208, 272))
"""La ventana del Acopio 5 en el levantamiento (filas y columnas de la rejilla de 400 × 400): de x = 208 a 272 m y de
y = 188 a 252 m, con su marca, su margen de 10 m y la terraza dentro."""


def survey_marks(grid: object, only: tuple[str, ...] | None = None) -> list:
    """Las marcas de la cantera (``sdata.MARKS``) como marcas del trabajo, con su margen, su material y su base."""
    return [mark_of(mark.name, sdata.in_box(mark.box, grid), margin_m=mark.margin_m, material=mark.material,
                    base=mark.base) for mark in sdata.MARKS if only is None or mark.name in only]


class OwnBaseTest(unittest.TestCase):
    """RF-016-03: una marca con la superficie de un levantamiento anterior como base forma su huella y su volumen sobre
    ella como sobre el plano, sin corona, ajuste ni límite de inclinación, y anota de qué superficie sale su base. La
    terraza de 0,5 m del levantamiento anterior queda bajo la base: no es del acopio."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = qfx.GRID
        cls.z = sdata.survey()
        cls.previous = sdata.previous_survey(cls.grid)
        cls.bases = {sdata.PREVIOUS_LABEL: cls.previous}
        cls.marks = survey_marks(cls.grid, ("Acopio 5",))
        cls.outcome = detect(job_of(cls.grid, cls.z, cls.marks, bases=cls.bases))
        (cls.item,) = cls.outcome.stockpiles
        mound = sdata.survey_mound("Acopio 5")
        cls.height = sdata.mound_heights(cls.grid.shape, 1.0, (mound,))

    def test_the_stockpile_notes_the_surface_its_base_comes_from(self) -> None:
        self.assertEqual(self.item.base_surface, sdata.PREVIOUS_LABEL)
        self.assertEqual(self.item.material, "mineral")

    def test_there_is_no_plane_no_crown_no_fit_and_no_limit(self) -> None:
        """RF-016-03: sin plano (ni su cota, pendiente o azimut), una sola vuelta que ya converge y ninguna nota de la
        corona, del ajuste o de la inclinación."""
        self.assertIsNone(self.item.plane)
        self.assertIsNone(self.item.plane_level_m)
        self.assertIsNone(self.item.plane_slope_percent)
        self.assertIsNone(self.item.plane_azimuth_deg)
        self.assertIsNone(self.item.plane_tilt_deg)
        self.assertEqual((self.item.turns, self.item.converged), (1, True))
        self.assertEqual(self.item.notes, ())

    def test_the_base_is_the_previous_survey_bit_by_bit(self) -> None:
        rows, cols = np.divmod(self.item.cells, self.grid.ncols)
        np.testing.assert_array_equal(self.item.base, self.previous[rows, cols])
        np.testing.assert_array_equal(self.item.surface, self.z[rows, cols])

    def test_the_footprint_and_the_volume_are_the_pyramid_over_the_terrace(self) -> None:
        """La huella son las celdas de la pirámide a más de 0,3 m (la terraza de 0,5 m del levantamiento anterior no
        cuenta: está en la base) y su volumen, la suma de sus alturas (a mano: la altura es 7,25 − 0,5·k m en la corona
        de k celdas de la cima), a ≤ 10⁻⁹."""
        expected = np.flatnonzero(self.height > THRESHOLD_M)
        self.assertEqual(self.item.cells.tolist(), expected.tolist())
        by_hand = math.fsum(self.height[self.height > THRESHOLD_M].tolist())
        self.assertAlmostEqual(self.item.volume_m3 / by_hand - 1.0, 0.0, delta=1e-9)
        rows, cols = np.divmod(self.item.cells, self.grid.ncols)
        np.testing.assert_allclose(self.item.thickness, self.height[rows, cols], rtol=0.0, atol=1e-9)
        # a mano: 0,5·(15 − d) > 0,3 con d la distancia de Chebyshev, de k + 0,5 m: d ≤ 13,5 m, así que las celdas van
        # de y = 206,5 a 233,5 m (las de 205,5 y 234,5 m quedan en 0,25 m), las filas 400 − 1 − 233 = 166 a 193
        self.assertEqual((int(rows.min()), int(rows.max())), (166, 193))

    def test_it_is_the_hand_footprint_on_the_same_surface(self) -> None:
        """RF-016-02, RF-016-03: la huella y el volumen son los del oráculo (``hand_footprint`` y ``hand_volume``) sobre
        la misma superficie de base, en una ventana de 64 × 64 celdas en torno al acopio."""
        rows, cols = SURVEY_CROP
        z, base = self.z[SURVEY_CROP], self.previous[SURVEY_CROP]
        mark = sdata.in_box(sdata.MARKS[4].box, self.grid)[SURVEY_CROP]
        enlarged = oracles.hand_dilate(mark.tolist(), 1.0, MARGIN_M)
        hand = oracles.hand_footprint(z.tolist(), base.tolist(), mark.tolist(), enlarged.tolist(), THRESHOLD_M)
        inside_rows, inside_cols = np.nonzero(hand.mask)
        expected = (inside_rows + rows.start) * self.grid.ncols + (inside_cols + cols.start)
        self.assertEqual(self.item.cells.tolist(), sorted(expected.tolist()))
        by_hand = oracles.hand_volume(z.tolist(), base.tolist(), hand.mask.tolist(), 1.0, THRESHOLD_M)
        self.assertAlmostEqual(self.item.volume_m3 / by_hand - 1.0, 0.0, delta=1e-9)
        check_layers(self, self.grid, self.z, self.item)

    def test_the_crown_the_fit_and_the_limit_do_not_matter(self) -> None:
        """RF-016-03: con otra corona, otra pendiente de corona, una sola vuelta de ajuste y una inclinación máxima de
        0,01° el resultado es el mismo."""
        other = params_of(crown_inner_m=2.0, crown_outer_m=9.0, crown_slope_deg=1.0, crown_flat_min_m2=100_000.0,
                          fit_rounds=1, tilt_max_deg=0.01, max_residual_m=0.01, support_quantile=0.0)
        again = detect(job_of(self.grid, self.z, self.marks, bases=self.bases, params=other)).stockpiles[0]
        self.assertEqual(again.cells.tolist(), self.item.cells.tolist())
        self.assertEqual(again.volume_m3, self.item.volume_m3)
        self.assertEqual(again.notes, ())

    def test_the_terrace_would_count_if_the_base_were_the_plane(self) -> None:
        """Sin la base propia, la terraza de 0,5 m (más de 0,3 m sobre el plano) entra en la huella de la marca: el
        resultado con la base propia es, de verdad, otro."""
        plain = detect(job_of(self.grid, self.z, survey_marks(self.grid, ("Acopio 3",)))).stockpiles[0]
        self.assertIsNotNone(plain.plane)  # el Acopio 3 no está sobre la terraza; lo que importa es que lleva plano
        marks = [mark_of("Acopio 5", sdata.in_box(sdata.MARKS[4].box, self.grid), material="mineral")]
        with_plane = detect(job_of(self.grid, self.z, marks)).stockpiles[0]
        self.assertIsNone(with_plane.base_surface)
        self.assertGreater(with_plane.cells.size, self.item.cells.size)

    def test_missing_data_in_the_base_rejects_the_stockpile(self) -> None:
        """RF-016-04: una celda sin dato en el hueco de la huella (la base propia no la tiene) rechaza el acopio nombrando
        su marca, como una superficie sin terreno."""
        holed = self.previous.copy()
        holed[400 - 220, 240] = np.nan  # el centro de la pirámide, en medio de su huella
        outcome = detect(job_of(self.grid, self.z, self.marks, bases={sdata.PREVIOUS_LABEL: holed}))
        self.assertEqual(outcome.stockpiles, ())
        (rejected,) = outcome.rejected
        self.assertEqual((rejected.key, rejected.name), ("Acopio 5", "Acopio 5"))
        self.assertEqual(rejected.notice.code, NO_TERRAIN)
        self.assertEqual(rejected.notice.values["mark"], "Acopio 5")
        self.assertEqual(rejected.notice.values["cells"], 1)
        self.assertEqual(codes_of(outcome.notices), [NO_TERRAIN])
        self.assertEqual(outcome.count, 0)
        self.assertEqual(outcome.materials, ())

    def test_the_inputs_are_not_modified(self) -> None:
        """Principio 7: ni la superficie ni la base propia cambian."""
        z, previous = self.z.copy(), self.previous.copy()
        detect(job_of(self.grid, self.z, self.marks, bases=self.bases))
        np.testing.assert_array_equal(self.z, z)
        np.testing.assert_array_equal(self.previous, previous)


# --- E1, RF-016-06: dos acopios que se tocan -----------------------------------------------------------------------------


class TouchingPairTest(unittest.TestCase):
    """E1, RF-016-06: el Acopio 1 y el 2 (celdas de 1 m) dan dos acopios de huellas disjuntas, con el aviso de las dos
    marcas y del área repartida en cada uno, y los volúmenes sobre lo que les queda."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = sdata.touching_pair()
        grid = cls.case.grid
        cls.masks = [sdata.in_box(mark.box, grid) for mark in cls.case.marks]
        cls.marks = [mark_of(mark.name, mask, material="mineral") for mark, mask in zip(cls.case.marks, cls.masks,
                                                                                        strict=True)]
        cls.outcome = detect(job_of(grid, cls.case.terrain, cls.marks))
        # lo que sale de cada marca sola (A2 y A3, verificados contra el oráculo en ``HandPlaneTest``) y el reparto a mano
        cls.alone = [stockpiles.grow_footprint(cls.case.terrain, mask, grid, params_of()) for mask in cls.masks]
        cls.expected = oracles.hand_share([found.mask.tolist() for found in cls.alone],
                                          [mask.tolist() for mask in cls.masks])

    def test_the_footprints_are_the_hand_share(self) -> None:
        """RF-016-06: cada celda común, a la marca que la contiene o a la más próxima: las huellas del oráculo."""
        for item, mask in zip(self.outcome.stockpiles, self.expected, strict=True):
            self.assertEqual(item.cells.tolist(), np.flatnonzero(mask).tolist())
        first, second = (mask_of(self.case.grid, item) for item in self.outcome.stockpiles)
        self.assertFalse((first & second).any())
        np.testing.assert_array_equal(first | second, self.alone[0].mask | self.alone[1].mask)

    def test_the_planes_are_the_ones_of_each_mark_alone(self) -> None:
        """Cada acopio lleva el plano de su corona (el de su marca sola), no el del otro."""
        for item, alone in zip(self.outcome.stockpiles, self.alone, strict=True):
            np.testing.assert_allclose(item.base, alone.base.ravel()[item.cells], rtol=1e-9)
            self.assertAlmostEqual(item.plane.tilt_deg, alone.plane.tilt_deg, delta=1e-9)

    def test_the_volume_is_measured_on_the_cells_each_keeps(self) -> None:
        """RF-016-02, RF-016-06: cada volumen es el del cálculo a mano sobre las celdas que le quedan y su plano, a ≤
        10⁻⁹ relativo; no se cuenta nada dos veces (la suma son 2.143 m³ de los 2.145 analíticos, a 0,1 %)."""
        total = []
        for item, alone, mask in zip(self.outcome.stockpiles, self.alone, self.expected, strict=True):
            by_hand = oracles.hand_volume(self.case.terrain.tolist(), alone.base.tolist(), mask.tolist(), 1.0,
                                          THRESHOLD_M)
            self.assertAlmostEqual(item.volume_m3 / by_hand - 1.0, 0.0, delta=1e-9)
            check_layers(self, self.case.grid, self.case.terrain, item)
            total.append(item.volume_m3)
        analytic = math.fsum(self.case.height[self.case.height > THRESHOLD_M].tolist())
        self.assertAlmostEqual(math.fsum(total) / analytic - 1.0, 0.0, delta=2e-3)

    def test_the_share_is_noted_in_both_stockpiles_and_told_once(self) -> None:
        """RF-016-06: el aviso con las dos marcas y el área repartida (436 m²) lo lleva cada acopio; el resumen lo cuenta
        una vez. La pareja la da también ``outcome.shared``."""
        common = self.alone[0].mask & self.alone[1].mask
        self.assertEqual(int(common.sum()), 436)
        (pair,) = self.outcome.shared
        self.assertEqual((pair.mark, pair.other, pair.area_m2), ("Acopio 1", "Acopio 2", 436.0))
        for item in self.outcome.stockpiles:
            (note,) = [note for note in item.notes if note.code == SHARED]
            self.assertEqual((note.values["mark"], note.values["other"], note.values["area"]),
                             ("Acopio 1", "Acopio 2", 436.0))
            self.assertAlmostEqual(note.values["x"], sdata.BASE[0] + 60.0, delta=1e-6)
            self.assertAlmostEqual(note.values["y"], sdata.BASE[1] + 60.0, delta=1e-6)
        # cada huella llega, sola, al borde de su marca ampliada (se lleva el otro montón: nota de RF-016-05); el aviso de la
        # pareja sale una vez, en el primer acopio al que se llega
        self.assertEqual(codes_of(self.outcome.notices), [AT_EDGE, SHARED, AT_EDGE])

    def test_the_order_of_the_marks_in_the_job_does_not_change_the_result(self) -> None:
        """Con el orden de las marcas cambiado sale lo mismo (por clave); lo que sale es el orden del trabajo."""
        swapped = detect(job_of(self.case.grid, self.case.terrain, self.marks[::-1]))
        self.assertEqual([item.key for item in swapped.stockpiles], ["Acopio 2", "Acopio 1"])
        for item in swapped.stockpiles:
            before = by_key(self.outcome, item.key)
            self.assertEqual(item.cells.tolist(), before.cells.tolist())
            self.assertEqual(item.volume_m3, before.volume_m3)
        self.assertEqual(swapped.shared[0].area_m2, 436.0)

    def test_the_notices_name_the_marks_and_the_pairs_carry_the_keys(self) -> None:
        """Con una clave que no es el nombre (``m01``, el ``fid`` o el ``nombre`` de la capa: la clave del acopio), los avisos
        nombran la marca por su nombre y las parejas de ``outcome.shared``, por su clave."""
        named = [mark_of(f"m0{k}", mask, name=mark.name, material="mineral")
                 for k, (mark, mask) in enumerate(zip(self.case.marks, self.masks, strict=True), start=1)]
        outcome = detect(job_of(self.case.grid, self.case.terrain, named))
        (pair,) = outcome.shared
        self.assertEqual((pair.mark, pair.other), ("m01", "m02"))
        for item in outcome.stockpiles:
            (note,) = [note for note in item.notes if note.code == SHARED]
            self.assertEqual((note.values["mark"], note.values["other"]), ("Acopio 1", "Acopio 2"))
            self.assertEqual([n.values["mark"] for n in item.notes if n.code == AT_EDGE], [item.name])
        self.assertEqual([item.key for item in outcome.stockpiles], ["m01", "m02"])
        self.assertEqual([item.name for item in outcome.stockpiles], ["Acopio 1", "Acopio 2"])

    def test_a_far_stockpile_is_not_shared_with_anyone(self) -> None:
        """Un tercer acopio lejos no entra en el reparto: su huella es la de calcularlo solo."""
        far = sdata.in_box((92.0, 92.0, 108.0, 108.0), self.case.grid)
        z = self.case.terrain.copy()
        z[sdata.in_box((96.0, 96.0, 104.0, 104.0), self.case.grid)] += 2.0
        trio = detect(job_of(self.case.grid, z, [*self.marks, mark_of("Lejos", far)]))
        alone = detect(job_of(self.case.grid, z, [mark_of("Lejos", far)])).stockpiles[0]
        self.assertEqual(len(trio.shared), 1)
        self.assertEqual(by_key(trio, "Lejos").cells.tolist(), alone.cells.tolist())


class TieTest(unittest.TestCase):
    """RF-016-06 y el orden determinista: una celda a igual distancia de dos marcas que no la contienen es de la primera
    **por clave**, esté donde esté en el trabajo (con una base propia llana, sin ajuste)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = sdata.window_grid(1.0, 50.0)
        cls.z = np.full(cls.grid.shape, LEVEL_M)
        cls.block = sdata.in_box((10.0, 15.0, 31.0, 25.0), cls.grid)
        cls.z[cls.block] += 3.0
        cls.left = sdata.in_box((10.0, 15.0, 20.0, 25.0), cls.grid)
        cls.right = sdata.in_box((21.0, 15.0, 31.0, 25.0), cls.grid)
        cls.gap = sdata.in_box((20.0, 15.0, 21.0, 25.0), cls.grid)
        cls.bases = {"llano": np.full(cls.grid.shape, LEVEL_M)}

    def run_with(self, left_key: str, right_key: str, *, left_first: bool) -> object:
        marks = [mark_of(left_key, self.left, base="llano"), mark_of(right_key, self.right, base="llano")]
        return detect(job_of(self.grid, self.z, marks if left_first else marks[::-1], bases=self.bases,
                             params=params_of(margin_m=15.0)))  # con 15 m cada marca alcanza todo el bloque de 21 m

    def test_the_cell_in_the_gap_goes_to_the_smaller_key_whatever_the_job_order(self) -> None:
        for left_first in (True, False):
            with self.subTest(left_first=left_first):
                outcome = self.run_with("A", "B", left_first=left_first)
                a, b = by_key(outcome, "A"), by_key(outcome, "B")
                self.assertEqual(a.cells.tolist(), np.flatnonzero(self.left | self.gap).tolist())
                self.assertEqual(b.cells.tolist(), np.flatnonzero(self.right).tolist())
                self.assertAlmostEqual(a.volume_m3, 330.0, delta=1e-9)  # (100 + 10) celdas · 3 m
                self.assertAlmostEqual(b.volume_m3, 300.0, delta=1e-9)

    def test_with_the_keys_swapped_the_gap_goes_to_the_other_side(self) -> None:
        for left_first in (True, False):
            with self.subTest(left_first=left_first):
                outcome = self.run_with("B", "A", left_first=left_first)
                a, b = by_key(outcome, "A"), by_key(outcome, "B")
                self.assertEqual(a.cells.tolist(), np.flatnonzero(self.right | self.gap).tolist())
                self.assertEqual(b.cells.tolist(), np.flatnonzero(self.left).tolist())

    def test_the_whole_zone_was_claimed_by_both_before_the_share(self) -> None:
        """Las dos reclaman las 210 celdas del bloque y el reparto no pierde ninguna."""
        outcome = self.run_with("A", "B", left_first=True)
        (pair,) = outcome.shared
        self.assertEqual((pair.cells, pair.area_m2), (210, 210.0))
        union = sum(item.cells.size for item in outcome.stockpiles)
        self.assertEqual(union, 210)


class ChainTest(unittest.TestCase):
    """RF-016-06: tres acopios en fila, el primero y el segundo con celdas comunes y el segundo y el tercero también, pero el
    primero y el tercero no: el reparto es de los tres juntos (un solo grupo) y cada celda común va al que manda la regla,
    contada a mano; el aviso es el de cada pareja, una vez."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = sdata.window_grid(1.0, 50.0)
        cls.z = np.full(cls.grid.shape, LEVEL_M)
        cls.z[sdata.in_box((10.0, 15.0, 36.0, 25.0), cls.grid)] += 3.0  # 26 columnas, de x = 10,5 a 35,5 m
        cls.bases = {"llano": np.full(cls.grid.shape, LEVEL_M)}
        cls.boxes = {"A": (10.0, 15.0, 15.0, 25.0), "B": (18.0, 15.0, 23.0, 25.0), "C": (26.0, 15.0, 31.0, 25.0)}

    def run_with(self, keys: str) -> object:
        marks = [mark_of(key, sdata.in_box(self.boxes[key], self.grid), base="llano", margin_m=5.0) for key in keys]
        return detect(job_of(self.grid, self.z, marks, bases=self.bases))

    def columns(self, item: object) -> list[float]:
        """Los x (locales, m) de las columnas de la huella de ``item``: cada una con sus 10 celdas."""
        rows, cols = np.divmod(item.cells, self.grid.ncols)
        self.assertEqual(len(rows), 10 * len(set(cols.tolist())))
        return sorted(float(col) + 0.5 for col in set(cols.tolist()))

    def test_the_three_share_by_the_rule_counted_by_hand(self) -> None:
        """Con 5 m de margen, A llega a x = 19,5 m, B de 13,5 a 27,5 y C desde 21,5: A y B comparten de 13,5 a 19,5 y B y C de
        21,5 a 27,5. Las que contiene una marca van a ella; el empate (a 16,5 m entre A y B, a 24,5 m entre B y C) va a la
        menor clave. A queda de 10,5 a 16,5 m (7 columnas), B de 17,5 a 24,5 (8) y C de 25,5 a 35,5 (11)."""
        outcome = self.run_with("ABC")
        found = {item.key: item for item in outcome.stockpiles}
        self.assertEqual(self.columns(found["A"]), [10.5 + k for k in range(7)])
        self.assertEqual(self.columns(found["B"]), [17.5 + k for k in range(8)])
        self.assertEqual(self.columns(found["C"]), [25.5 + k for k in range(11)])
        for key, volume in (("A", 210.0), ("B", 240.0), ("C", 330.0)):
            self.assertAlmostEqual(found[key].volume_m3, volume, delta=1e-9, msg=key)
        self.assertEqual([(pair.mark, pair.other, pair.cells) for pair in outcome.shared],
                         [("A", "B", 70), ("B", "C", 70)])
        self.assertEqual(codes_of(outcome.notices).count(SHARED), 2)

    def test_the_order_of_the_job_does_not_change_it(self) -> None:
        one, other = self.run_with("ABC"), self.run_with("CAB")
        for key in "ABC":
            self.assertEqual(by_key(one, key).cells.tolist(), by_key(other, key).cells.tolist(), key)
        self.assertEqual([(pair.mark, pair.other) for pair in other.shared], [("A", "B"), ("B", "C")])

    def test_two_that_do_not_touch_are_not_shared(self) -> None:
        """A y C no tienen celdas comunes: sin B no hay reparto, y cada una conserva todo lo que alcanza."""
        outcome = self.run_with("AC")
        self.assertEqual(outcome.shared, ())
        self.assertEqual(self.columns(by_key(outcome, "A")), [10.5 + k for k in range(10)])
        self.assertEqual(self.columns(by_key(outcome, "C")), [21.5 + k for k in range(15)])


# --- CE-016-01 y RF-016-08: el levantamiento, los candidatos y las cifras ---------------------------------------------------


class SurveyTest(unittest.TestCase):
    """CE-016-01 de principio a fin en el dominio: las cinco marcas del levantamiento (dos materiales, una base propia, el
    Acopio 1 y el 2 que se tocan) y los candidatos sin marca, que son 8 y no 13."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = qfx.GRID
        cls.z = sdata.survey()
        cls.previous = sdata.previous_survey(cls.grid)
        cls.perimeter = sdata.in_box(qfx.PERIMETER_LOCAL)
        cls.job = job_of(cls.grid, cls.z, survey_marks(cls.grid), bases={sdata.PREVIOUS_LABEL: cls.previous},
                         candidates=cparams(), perimeter=cls.perimeter)
        cls.outcome = detect(cls.job)

    def test_the_five_marks_are_five_stockpiles(self) -> None:
        self.assertEqual([item.key for item in self.outcome.stockpiles], [f"Acopio {k}" for k in range(1, 6)])
        self.assertEqual(self.outcome.rejected, ())
        self.assertEqual(self.outcome.materials, ("mineral", "estéril"))
        self.assertEqual(self.outcome.count, 5)

    def test_the_candidates_are_the_eight_that_pass_and_none_of_the_marked(self) -> None:
        """RF-016-08, CE-016-01: 8 candidatos (y no 13): las zonas de los acopios marcados no son candidatos; lo demás se
        cuenta sin listarse (18 zonas: 8 candidatos, 6 con marca, 4 pequeñas)."""
        found = self.outcome.candidates
        self.assertEqual(len(found.items), 8)
        self.assertEqual((found.zones, found.on_marks, found.too_small, found.too_large, found.rejected),
                         (18, 6, 4, 0, 0))
        taken = np.zeros(self.grid.shape, dtype=bool)
        for item in self.outcome.stockpiles:
            taken |= mask_of(self.grid, item)
        for candidate in found.items:
            self.assertFalse(np.isin(candidate.cells, np.flatnonzero(taken)).any())

    def test_the_candidates_are_the_ones_of_the_search_alone(self) -> None:
        """Los candidatos de la detección son los de ``find_candidates`` con las huellas y las marcas como celdas con marca:
        el mismo orden de lectura, las mismas huellas."""
        taken = np.zeros(self.grid.shape, dtype=bool)
        for item in self.outcome.stockpiles:
            taken |= mask_of(self.grid, item)
        for mark in self.job.marks:
            taken.ravel()[mark.cells] = True
        alone = stockpiles.find_candidates(self.z, self.grid, self.perimeter, taken, cparams())
        self.assertEqual(len(alone.items), len(self.outcome.candidates.items))
        for mine, other in zip(self.outcome.candidates.items, alone.items, strict=True):
            self.assertEqual(mine.cells.tolist(), other.cells.tolist())
            self.assertEqual(mine.footprint.volume_m3, other.footprint.volume_m3)

    def test_a_rejected_mark_does_not_come_back_as_a_candidate(self) -> None:
        """Un acopio rechazado (una marca sobre el montículo P1 con el propio levantamiento como base: ninguna celda por
        encima del umbral) no se registra, se informa nombrando la marca y su zona no sale como candidato (7, no 8):
        la marca ya la ocupa."""
        mound = sdata.survey_mound("P1")
        box = (mound.cx - 10.0, mound.cy - 10.0, mound.cx + 10.0, mound.cy + 10.0)
        marks = [*survey_marks(self.grid), mark_of("Sobre P1", sdata.in_box(box, self.grid), base="el propio")]
        bases = {sdata.PREVIOUS_LABEL: self.previous, "el propio": self.z}
        outcome = detect(job_of(self.grid, self.z, marks, bases=bases, candidates=cparams(), perimeter=self.perimeter))
        self.assertEqual([item.key for item in outcome.stockpiles], [f"Acopio {k}" for k in range(1, 6)])
        (rejected,) = outcome.rejected
        self.assertEqual((rejected.key, rejected.notice.code), ("Sobre P1", NO_CELLS))
        self.assertEqual(rejected.notice.values["mark"], "Sobre P1")
        self.assertAlmostEqual(rejected.notice.values["x"], sdata.BASE[0] + mound.cx, delta=1e-6)
        self.assertAlmostEqual(rejected.notice.values["y"], sdata.BASE[1] + mound.cy, delta=1e-6)
        self.assertEqual(rejected.notice.values["threshold"], THRESHOLD_M)
        self.assertEqual(codes_of(outcome.notices)[0], NO_CELLS)
        self.assertEqual(len(outcome.candidates.items), 7)
        self.assertEqual(outcome.candidates.on_marks, 7)

    def test_without_candidates_there_are_none(self) -> None:
        plain = detect(job_of(self.grid, self.z, survey_marks(self.grid), bases={sdata.PREVIOUS_LABEL: self.previous}))
        self.assertIsNone(plain.candidates)
        self.assertEqual([item.cells.tolist() for item in plain.stockpiles],
                         [item.cells.tolist() for item in self.outcome.stockpiles])

    def test_the_materials_have_their_own_base_and_thickness(self) -> None:
        """RF-016-09, D-19: «mineral» (Acopio 1, 2 y 5) y «estéril» (3 y 4), cada uno con su base y su espesor."""
        names = {"mineral": ("Acopio 1", "Acopio 2", "Acopio 5"), "estéril": ("Acopio 3", "Acopio 4")}
        for material, keys in names.items():
            union = np.zeros(self.grid.shape, dtype=bool)
            for key in keys:
                union |= mask_of(self.grid, by_key(self.outcome, key))
            np.testing.assert_array_equal(np.isfinite(self.outcome.base_grid(material)), union, material)
            np.testing.assert_array_equal(np.isfinite(self.outcome.thickness_grid(material)), union, material)
        both = self.outcome.base_grid("mineral")
        self.assertTrue(np.isnan(both[mask_of(self.grid, by_key(self.outcome, "Acopio 3"))]).all())

    def test_the_layers_of_every_stockpile_are_the_hand_layers(self) -> None:
        for item in self.outcome.stockpiles:
            with self.subTest(item.key):
                check_layers(self, self.grid, self.z, item)
                rows, cols = np.divmod(item.cells, self.grid.ncols)
                self.assertTrue((item.ground <= self.z[rows, cols] + 1e-9).all())

    def test_the_volume_of_a_pyramid_is_the_analytic_one_to_half_a_percent(self) -> None:
        """RF-016-02: los planos de las pirámides quedan a 4,5 mm del sintético (T06), así que el volumen es el analítico a
        menos de 0,5 % (el Acopio 3, de 5 m de altura, sobre su plano; el 5 es exacto sobre su base propia)."""
        item = by_key(self.outcome, "Acopio 3")
        height = sdata.mound_heights(self.grid.shape, 1.0, (sdata.survey_mound("Acopio 3"),))
        analytic = math.fsum(height[height > THRESHOLD_M].tolist())
        self.assertAlmostEqual(item.volume_m3 / analytic - 1.0, 0.0, delta=5e-3)

    def test_the_margin_of_a_mark_is_its_own(self) -> None:
        """RF-016-02: el campo ``margen`` de la marca manda sobre el de la detección: con 2 m el Acopio 3 (pie de 14 m de
        semilado, marca de 10) llega al borde de su marca ampliada y lo anota; con el suyo de 6 m, no."""
        marks = survey_marks(self.grid, ("Acopio 3",))
        self.assertEqual(marks[0].margin_m, 6.0)
        self.assertNotIn(AT_EDGE, codes_of(by_key(self.outcome, "Acopio 3").notes))
        tight = dataclasses.replace(marks[0], margin_m=2.0)
        outcome = detect(job_of(self.grid, self.z, [tight]))
        self.assertIn(AT_EDGE, codes_of(outcome.stockpiles[0].notes))
        self.assertLess(outcome.stockpiles[0].cells.size, by_key(self.outcome, "Acopio 3").cells.size)

    def test_the_figures_are_the_ones_of_the_row(self) -> None:
        """RF-016-02, RF-016-08: ``des.stk_count`` y ``des.stk_candidates`` de la detección y, por acopio (ámbito: su clave y
        su material), el área, el volumen, el espesor máximo y la inclinación del plano (sin ella el de la base propia)."""
        figures = self.outcome.figures
        keys = [(figure.key, figure.scope.get("stockpile")) for figure in figures]
        self.assertEqual(keys[0], ("des.stk_count", None))
        self.assertEqual(keys[1], ("des.stk_candidates", None))
        self.assertEqual(figures[0].value, 5.0)
        self.assertEqual(figures[1].value, 8.0)
        self.assertEqual(len(figures), 2 + 5 * 4 - 1)
        by_figure = {(figure.key, figure.scope.get("stockpile")): figure for figure in figures[2:]}
        for item in self.outcome.stockpiles:
            area, volume, thick = (by_figure[key, item.key] for key in ("des.stk_area_m2", "des.stk_volume_m3",
                                                                        "des.stk_thickness_max_m"))
            self.assertEqual((area.value, volume.value, thick.value),
                             (item.area_m2, item.volume_m3, item.thickness_max_m))
            self.assertEqual((area.unit, volume.unit, thick.unit), ("m2", "m3", "m"))
            self.assertEqual(area.scope["material"], item.material)
            self.assertEqual(area.scope["entity"], "STK-001")
            tilt = by_figure.get(("des.stk_plane_tilt_deg", item.key))
            if item.plane is None:
                self.assertIsNone(tilt)
            else:
                self.assertEqual((tilt.value, tilt.unit), (item.plane.tilt_deg, "deg"))
        self.assertEqual(len({tuple(sorted(figure.scope.items())) for figure in figures[2:]}), 5)

    def test_the_figures_are_the_ones_the_provenance_builds(self) -> None:
        """Las cifras son las de ``provenance.stockpile_figures`` con los números del acopio."""
        expected = provenance.stockpile_figures(
            self.job.name, self.job.code, count=5, candidates=8,
            stockpiles=[provenance.StockpileFigures(item.key, item.material, item.area_m2, item.volume_m3,
                                                    item.thickness_max_m,
                                                    None if item.plane is None else item.plane.tilt_deg)
                        for item in self.outcome.stockpiles])
        self.assertEqual(self.outcome.figures, expected)

    def test_without_candidates_the_figure_is_not_registered(self) -> None:
        plain = detect(job_of(self.grid, self.z, survey_marks(self.grid), bases={sdata.PREVIOUS_LABEL: self.previous}))
        self.assertNotIn("des.stk_candidates", [figure.key for figure in plain.figures])

    def test_the_shared_pair_is_the_first_two(self) -> None:
        """E1 dentro del levantamiento: el Acopio 1 y el 2 comparten 436 m² (en una ventana propia de los dos)."""
        (pair,) = self.outcome.shared
        self.assertEqual((pair.mark, pair.other, pair.area_m2), ("Acopio 1", "Acopio 2", 436.0))
        self.assertEqual(codes_of(self.outcome.notices).count(SHARED), 1)


class FootprintExcludesCandidateTest(unittest.TestCase):
    """RF-016-08: una zona que se solapa con la **huella** de una marca (aunque no toque la marca) tampoco es candidata: los
    candidatos son «sin marca». Dos pirámides de 5 m a 20 m una de otra cuyos pies se solapan; la primera, con su marca, y la
    segunda, sin ella: la huella de la primera se lleva parte de la segunda (hasta el borde de su marca ampliada) y la zona
    de la segunda, que sobresale más de 2 m, la solapa sin tocar la marca."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = sdata.window_grid(1.0, 120.0)
        cls.mounds = (sdata.Mound("Marcada", "pyramid", 60.0, 60.0, 12.0, 4.0, 5.0),
                      sdata.Mound("Sin marca", "pyramid", 80.0, 60.0, 12.0, 4.0, 5.0))
        cls.z = sdata.plane(0.0).values(cls.grid) + sdata.mound_heights(cls.grid.shape, 1.0, cls.mounds)
        cls.mark = sdata.in_box((50.0, 50.0, 70.0, 70.0), cls.grid)
        cls.perimeter = np.ones(cls.grid.shape, dtype=bool)

    def test_the_zone_touching_the_footprint_is_not_a_candidate(self) -> None:
        outcome = detect(job_of(self.grid, self.z, [mark_of("Marcada", self.mark)], candidates=cparams(),
                                perimeter=self.perimeter))
        (item,) = outcome.stockpiles
        self.assertGreater(item.cells.size, int(self.mark.sum()))
        self.assertEqual(len(outcome.candidates.items), 0)
        self.assertEqual(outcome.candidates.on_marks, 2)  # la zona de la marcada y la de la otra, que solapa su huella

    def test_the_same_zone_is_a_candidate_when_only_the_mark_is_taken(self) -> None:
        """El control: si solo se toman las celdas de la marca, la segunda pirámide sí es candidata (la prueba de arriba no
        pasa por casualidad)."""
        found = stockpiles.find_candidates(self.z, self.grid, self.perimeter, self.mark, cparams())
        self.assertEqual(len(found.items), 1)
        self.assertEqual(found.on_marks, 1)


# --- Los pasos -------------------------------------------------------------------------------------------------------------


class StepsTest(unittest.TestCase):
    """RNF-016-03, RNF-016-05: la detección por pasos de ≤ 0,05 s, con el mismo resultado, y cerrar a mitad no deja nada."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = SurveyTest
        cls.case.setUpClass()
        cls.job, cls.outcome = cls.case.job, cls.case.outcome

    def steps_of(self, job: object, budget_s: float) -> tuple[object, float, int]:
        longest, count, last = 0.0, 0, None
        steps = stockpiles.detect_steps(job, budget_s=budget_s)
        with closing(steps):
            while True:
                started = time.perf_counter()
                try:
                    last = next(steps)
                except StopIteration:
                    break
                longest, count = max(longest, time.perf_counter() - started), count + 1
        return last, longest, count

    def test_the_steps_give_the_same_outcome_in_small_steps(self) -> None:
        last, longest, count = self.steps_of(self.job, 0.0)
        self.assertGreater(count, 5)
        self.assertLess(longest, 0.05)
        other = last.result
        self.assertEqual(len(other.stockpiles), len(self.outcome.stockpiles))
        for mine, theirs in zip(other.stockpiles, self.outcome.stockpiles, strict=True):
            self.assertEqual(mine.cells.tolist(), theirs.cells.tolist())
            np.testing.assert_array_equal(mine.base, theirs.base)
            self.assertEqual(mine.volume_m3, theirs.volume_m3)
        self.assertEqual(other.figures, self.outcome.figures)
        self.assertEqual(len(other.candidates.items), 8)

    def test_with_the_budget_of_the_interface_there_are_fewer_steps(self) -> None:
        _, _, tight = self.steps_of(self.job, 0.0)
        _, longest, count = self.steps_of(self.job, 0.05)
        self.assertLess(count, tight)
        self.assertLess(longest, 0.1)

    def test_the_progress_is_the_one_of_a_calculation(self) -> None:
        """Cada paso es un ``Progress`` con una fase y un mensaje; solo el último lleva el resultado."""
        found = list(stockpiles.detect_steps(self.job, budget_s=0.0))
        for step in found[:-1]:
            self.assertIsNone(step.result)
            self.assertTrue(step.phase and step.message)
            self.assertLessEqual(step.done, step.total)
        self.assertIsInstance(found[-1].result, stockpiles.StockpileOutcome)

    def test_closing_halfway_leaves_the_inputs_as_they_were(self) -> None:
        z, previous = self.job.surface.copy(), self.job.bases[sdata.PREVIOUS_LABEL].copy()
        cells = [mark.cells.copy() for mark in self.job.marks]
        steps = stockpiles.detect_steps(self.job, budget_s=0.0)
        for _ in range(4):
            next(steps)
        steps.close()
        np.testing.assert_array_equal(self.job.surface, z)
        np.testing.assert_array_equal(self.job.bases[sdata.PREVIOUS_LABEL], previous)
        for mark, before in zip(self.job.marks, cells, strict=True):
            np.testing.assert_array_equal(mark.cells, before)

    def test_it_is_deterministic(self) -> None:
        again = detect(self.job)
        for mine, theirs in zip(again.stockpiles, self.outcome.stockpiles, strict=True):
            self.assertEqual(mine.cells.tolist(), theirs.cells.tolist())
            self.assertEqual(mine.volume_m3, theirs.volume_m3)
        self.assertEqual(again.figures, self.outcome.figures)


# --- La huella en tramos ---------------------------------------------------------------------------------------------------


class RunsTest(unittest.TestCase):
    """La huella en tramos de la tabla de acopios: una fila de celdas contiguas por tramo, y su inversa."""

    def test_the_runs_by_hand(self) -> None:
        # 3 columnas: fila 0: celdas 0 y 1 y la 2; fila 1: la 4; fila 2: 6 y 8 (dos tramos)
        cells = np.array([0, 1, 2, 4, 6, 8])
        self.assertEqual(stockpiles.footprint_runs(cells, 3).tolist(), [[0, 0, 3], [1, 1, 2], [2, 0, 1], [2, 2, 3]])
        self.assertEqual(stockpiles.footprint_runs(np.array([], dtype=np.int64), 3).shape, (0, 3))

    def test_a_run_does_not_wrap_to_the_next_row(self) -> None:
        """Las celdas 2 y 3 de una rejilla de 3 columnas son vecinas en el vector pero no en la rejilla."""
        self.assertEqual(stockpiles.footprint_runs(np.array([2, 3]), 3).tolist(), [[0, 2, 3], [1, 0, 1]])

    def test_the_round_trip_on_random_footprints(self) -> None:
        rng = random.Random(20_261_118)
        for _ in range(60):
            nrows, ncols = rng.randint(1, 9), rng.randint(1, 9)
            chosen = sorted(rng.sample(range(nrows * ncols), rng.randint(0, nrows * ncols)))
            cells = np.array(chosen, dtype=np.int64)
            runs = stockpiles.footprint_runs(cells, ncols)
            self.assertEqual(stockpiles.runs_cells(runs, ncols).tolist(), chosen)
            self.assertEqual(int((runs[:, 2] - runs[:, 1]).sum()), len(chosen))

    def test_the_refusals(self) -> None:
        with self.assertRaises(ValueError):
            stockpiles.footprint_runs(np.array([[1, 2]]), 3)
        with self.assertRaises(ValueError):
            stockpiles.footprint_runs(np.array([1.5]), 3)
        with self.assertRaises(ValueError):
            stockpiles.footprint_runs(np.array([1]), 0)
        with self.assertRaises(ValueError):
            stockpiles.runs_cells(np.array([[0, 2, 1]]), 3)  # un tramo vacío o al revés
        with self.assertRaises(ValueError):
            stockpiles.runs_cells(np.array([[0, 0, 4]]), 3)  # sale de la fila


# --- Lo que el trabajo rechaza ---------------------------------------------------------------------------------------------


class JobRefusalsTest(unittest.TestCase):
    """Errores del programa (``ValueError`` o ``TypeError``) que salen al construir el trabajo, antes de calcular nada."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid, cls.z, mark = block_scene()
        cls.mark = mark_of("Bloque", mark)
        cls.params = params_of()

    def job(self, **changes: object) -> object:
        fields = {"name": "Detección", "code": "STK-001", "grid": self.grid, "surface": self.z,
                  "marks": (self.mark,), "params": self.params, **changes}
        return stockpiles.StockpileJob(**fields)

    def test_a_good_job_is_accepted(self) -> None:
        found = self.job()
        self.assertIsNone(found.candidates)
        self.assertEqual(dict(found.bases), {})

    def test_refusals_of_the_job(self) -> None:
        flat = np.full(self.grid.shape, LEVEL_M)
        cases = {
            "dos marcas con la misma clave": {"marks": (self.mark, self.mark)},
            "dos marcas con celdas comunes": {"marks": (self.mark, stockpiles.StockpileMark("Otra", self.mark.cells))},
            "una base que no está": {"marks": (dataclasses.replace(self.mark, base="no está"),)},
            "una base de otra forma": {"marks": (dataclasses.replace(self.mark, base="b"),),
                                       "bases": {"b": np.zeros((3, 3))}},
            "una base con un infinito": {"marks": (dataclasses.replace(self.mark, base="b"),),
                                         "bases": {"b": np.where(flat > 0, np.inf, 0.0)}},
            "una superficie de otra forma": {"surface": np.zeros((3, 3))},
            "una superficie con un infinito": {"surface": np.where(self.z > 0, np.inf, 0.0)},
            "un código que no es de una entidad": {"code": "acopio"},
            "sin nombre": {"name": "  "},
            "un nombre que no da un dato": {"name": "¡¿!?"},
            "sin marcas ni candidatos": {"marks": ()},
            "un candidato sin perímetro": {"candidates": cparams()},
            "un perímetro que no es booleano": {"candidates": cparams(), "perimeter": np.ones(self.grid.shape)},
            "un perímetro de otra forma": {"candidates": cparams(), "perimeter": np.ones((3, 3), dtype=bool)},
            "unos candidatos con otros umbrales de huella": {
                "candidates": cparams(margin_m=3.0), "perimeter": np.ones(self.grid.shape, dtype=bool)},
            "una rejilla de celdas no cuadradas": {"grid": gis.Grid(0.0, 60.0, 1.0, 2.0, 60, 30)},
            "unos parámetros que no son de huella": {"params": self.params.plane},
            "una marca fuera de la rejilla": {"marks": (stockpiles.StockpileMark(
                "Fuera", np.array([self.grid.nrows * self.grid.ncols])),)},
            "una marca que no es una marca": {"marks": (self.mark, "otra")},
        }
        for what, changes in cases.items():
            with self.subTest(what), self.assertRaises((ValueError, TypeError, gis.GisError)):
                self.job(**changes)

    def test_refusals_of_a_mark(self) -> None:
        cells = np.array([1, 2, 3])
        for what, build in {
            "sin clave": lambda: stockpiles.StockpileMark(" ", cells),
            "sin celdas": lambda: stockpiles.StockpileMark("M", np.array([], dtype=np.int64)),
            "celdas reales": lambda: stockpiles.StockpileMark("M", np.array([1.5, 2.0])),
            "celdas negativas": lambda: stockpiles.StockpileMark("M", np.array([-1, 2])),
            "celdas en dos dimensiones": lambda: stockpiles.StockpileMark("M", np.array([[1, 2]])),
            "un margen negativo": lambda: stockpiles.StockpileMark("M", cells, margin_m=-1.0),
            "un margen que no es un número": lambda: stockpiles.StockpileMark("M", cells, margin_m="diez"),
            "un material en blanco": lambda: stockpiles.StockpileMark("M", cells, material=" "),
            "una base en blanco": lambda: stockpiles.StockpileMark("M", cells, base=" "),
        }.items():
            with self.subTest(what), self.assertRaises((ValueError, TypeError)):
                build()

    def test_a_mark_keeps_its_cells_sorted_and_without_repeats(self) -> None:
        mark = stockpiles.StockpileMark("M", np.array([5, 3, 3, 4]))
        self.assertEqual(mark.cells.tolist(), [3, 4, 5])
        self.assertEqual(mark.name, "M")
        self.assertEqual(stockpiles.StockpileMark("M", np.array([1]), name="Acopio M").name, "Acopio M")

    def test_the_outcome_of_a_job_without_marks_has_only_candidates(self) -> None:
        """Una detección que solo busca candidatos (sin marcas) es válida."""
        outcome = detect(self.job(marks=(), candidates=cparams(), perimeter=np.ones(self.grid.shape, dtype=bool)))
        self.assertEqual(outcome.stockpiles, ())
        self.assertIsNotNone(outcome.candidates)


if __name__ == "__main__":
    unittest.main()
