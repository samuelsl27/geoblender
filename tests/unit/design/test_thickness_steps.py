# SPDX-License-Identifier: GPL-3.0-or-later
"""El cuerpo apoyado por pasos: la triangulación y la rasterización del TIN por bandas (spec 016, T24; HU-016-4; RF-016-20;
RNF-016-02, RNF-016-03; plan 016 §2.1, §5.4 A11, §5.7 P-7, §7.3, §8).

La T23 dejó la triangulación y la rasterización del TIN como **una unidad cada una** (``thickness._triangulate_units`` y
``thickness._rasterize_units``): con datos en líneas (secciones) los triángulos diagonales son astillas de 200 × 200 celdas de caja y
``tin_to_raster`` cuesta lo que suman esas cajas (6,9 s por 100 ha). La T24 las parte —la triangulación, en pasos de 256 puntos
(``PureTriangulator.triangulate_steps``) y el TIN, en **bandas de filas** de coste acotado— **sin cambiar** ``BodyJob``,
``BodyOutcome`` ni ``body_steps``:

- **Bit a bit** (:class:`RasterBandsTest`): el espesor de las bandas es el de ``gis.tin.tin_to_raster`` de una pieza (el primer
  triángulo, en el orden del TIN, que contiene el centro de cada celda), con cualquier tamaño de banda, con triángulos que no cubren
  toda la ventana y con las bandas sin triángulos.
- **Bandas de coste acotado** (:class:`RasterBandsTest`): cada fila está en una sola banda y, salvo la última de ella, las filas de
  una banda suman menos del coste máximo (una fila sola no se puede partir).
- **Triangulación por pasos** (:class:`TriangulationUnitsTest`): ``_triangulate_units`` cede cada 256 puntos y da lo que da
  ``PureTriangulator.triangulate``.
- **Cada llamada ≤ 0,2 s** (:class:`CallsTest`, RNF-016-03): con 12 ha de datos en secciones diagonales (de una pieza, el TIN solo
  costaba 0,44 s) ninguna llamada de ``body_steps`` pasa de 0,2 s. Las ventanas de 20 y 100 ha (los 1,0 y los 6,9 s del plan §7.3)
  están en ``milestone_thickness_steps.py`` (P-13).
"""

from __future__ import annotations

import time
import unittest
from collections.abc import Generator
from typing import Any
from unittest import mock

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design import test_thickness as base

cdt = import_geoblender("gis.cdt")
gis = import_geoblender("gis")
thickness = import_geoblender("design.thickness")
tin_module = import_geoblender("gis.tin")

LIMIT_S = 0.2
"""RNF-016-03: ninguna llamada del hilo de Blender dura más."""


def drain(work: Generator[None, None, Any]) -> tuple[Any, int]:
    """Agota ``work``: lo que devuelve y cuántas unidades cedió."""
    units = 0
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value, units
        units += 1


def make_tin(xy: np.ndarray, z: np.ndarray | None = None) -> Any:
    """El TIN de Delaunay de ``xy`` (unidades de celda), como lo arma ``_tin_units``: con las cotas ``z`` (por defecto, una
    rampa)."""
    faces = cdt.PureTriangulator().triangulate(xy, np.empty((0, 2), dtype=np.int32))
    height = np.linspace(1.0, 9.0, len(xy)) if z is None else z
    vertices = np.column_stack([xy, height])
    return tin_module.Tin(vertices, faces, np.empty((0, 2), dtype=np.int32), np.full(len(vertices), 5, dtype=np.uint8),
                          triangulator=cdt.PureTriangulator.name)


def cell_centers(rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Los centros de celda en unidades de celda: ``(columna + ½, −(fila + ½))``."""
    return np.column_stack([cols + 0.5, -(rows + 0.5)]).astype(np.float64)


def loose(shape: tuple[int, int], count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    flat = rng.choice(shape[0] * shape[1], count, replace=False)
    rows, cols = np.divmod(flat, shape[1])
    return cell_centers(rows, cols)


def sections(side: int, lines: int, spacing: int) -> np.ndarray:
    """Secciones diagonales (a 45°) de una ventana cuadrada de ``side`` celdas: las astillas del plan §5.7 P-7."""
    found = []
    for k in range(lines):
        t = np.arange(side)
        r = t + k * spacing - side // 2
        ok = (r >= 0) & (r < side)
        found.append(cell_centers(r[ok], t[ok]))
    return np.vstack(found)


def one_piece(tin: Any, shape: tuple[int, int]) -> np.ndarray:
    """El espesor de una pieza: ``gis.tin.tin_to_raster`` sobre la ventana entera, sin bandas."""
    unit = gis.Grid(0.0, 0.0, 1.0, 1.0, shape[1], shape[0])
    return np.asarray(tin_module.tin_to_raster(tin, unit, crs=sdata.CRS, vertical=sdata.VERTICAL).values)


def by_bands(tin: Any, shape: tuple[int, int]) -> tuple[np.ndarray, int]:
    """El espesor por bandas (``thickness._rasterize_units``) y cuántas unidades cedió."""
    job = base.job_of(np.ones(base.GRID.shape, dtype=bool))  # solo lleva el CRS y la referencia vertical del ráster intermedio
    return drain(thickness._rasterize_units(tin, shape, job))


class RasterBandsTest(unittest.TestCase):
    """RF-016-20, RNF-016-03: el TIN por bandas de filas es el de una pieza, bit a bit, y cada banda cuesta poco."""

    def cases(self) -> dict[str, tuple[Any, tuple[int, int]]]:
        shape = (90, 120)
        found: dict[str, tuple[Any, tuple[int, int]]] = {
            "datos sueltos": (make_tin(loose(shape, 300, 1)), shape),
            "secciones diagonales": (make_tin(sections(150, 3, 40)), (150, 150)),
            "secciones con huecos": (make_tin(sections(100, 2, 70)), (100, 100)),
        }
        # El TIN no cubre toda la ventana: dos triángulos en una esquina (filas sin triángulos) y uno enorme (toda la ventana).
        corner = cell_centers(np.array([2, 2, 9]), np.array([3, 17, 8]))
        found["una esquina"] = (make_tin(corner), (60, 70))
        wide = cell_centers(np.array([0, 59, 59]), np.array([0, 0, 69]))
        found["un triángulo de toda la ventana"] = (make_tin(wide), (60, 70))
        return found

    def test_the_bands_equal_the_one_piece_raster_bit_by_bit(self) -> None:
        """Con el coste por defecto, con una banda por fila y con una sola banda: los mismos bytes que ``tin_to_raster``, tipo y
        forma incluidos (los triángulos sobre una arista compartida o un vértice toman el primero del TIN, también por
        bandas)."""
        for name, (tin, shape) in self.cases().items():
            whole = one_piece(tin, shape)
            self.assertTrue(np.isnan(whole).any() or name != "una esquina", "el caso de la esquina deja celdas sin TIN")
            for cost in (thickness.RASTER_UNIT_COST, 1, 10**12):
                with self.subTest(caso=name, coste=cost), mock.patch.object(thickness, "RASTER_UNIT_COST", cost):
                    banded, units = by_bands(tin, shape)
                    self.assertEqual((banded.dtype, banded.shape), (whole.dtype, whole.shape))
                    self.assertEqual(banded.tobytes(), whole.tobytes())
                    if cost == 1:
                        self.assertGreater(units, 1)

    def test_the_data_are_reproduced_exactly_in_their_cells(self) -> None:
        """Cada dato cae en el centro de su celda: el espesor por bandas lo reproduce a 0,0 m, también en las filas de las
        junturas de banda."""
        xy = loose((60, 80), 400, 2)
        z = np.random.default_rng(3).uniform(0.5, 4.0, len(xy))
        tin = make_tin(xy, z)
        with mock.patch.object(thickness, "RASTER_UNIT_COST", 1):
            banded, units = by_bands(tin, (60, 80))
        self.assertGreater(units, 30)
        rows, cols = (-xy[:, 1] - 0.5).astype(int), (xy[:, 0] - 0.5).astype(int)
        np.testing.assert_array_equal(banded[rows, cols], z)

    def test_the_bands_cover_every_row_once_and_only_a_single_row_exceeds_the_cost(self) -> None:
        """Las bandas son filas contiguas de la 0 a la última, cada fila en una sola banda, y las filas de una banda, salvo su
        última, suman menos que el coste máximo (una fila sola no se puede partir)."""
        tin, shape = make_tin(sections(200, 4, 50)), (200, 200)
        for cost in (50_000, 5_000, 200):
            with self.subTest(coste=cost):
                with mock.patch.object(thickness, "RASTER_UNIT_COST", cost):
                    rows_cost, first, last = thickness._row_costs(tin, shape)
                    bands = thickness._raster_bands(rows_cost)
                self.assertEqual(bands[0][0], 0)
                self.assertEqual(bands[-1][1], shape[0])
                self.assertEqual([a[1] for a in bands[:-1]], [b[0] for b in bands[1:]])
                for top, bottom in bands:
                    self.assertGreater(bottom, top)
                    self.assertLess(float(rows_cost[top:bottom - 1].sum()), cost)
                self.assertEqual(len(first), len(tin.faces))
                self.assertEqual(len(last), len(tin.faces))
        self.assertGreater(len(bands), 10)

    def test_rows_without_triangles_cost_nothing_and_stay_empty(self) -> None:
        """Una banda sin ningún triángulo no llama a ``tin_to_raster`` y queda sin dato (``NaN``)."""
        corner = cell_centers(np.array([2, 2, 9]), np.array([3, 17, 8]))
        tin, shape = make_tin(corner), (60, 70)
        with mock.patch.object(thickness, "RASTER_UNIT_COST", 1), mock.patch.object(thickness, "tin_to_raster",
                                                                                   wraps=thickness.tin_to_raster) as spy:
            banded, _units = by_bands(tin, shape)
        self.assertTrue(np.isnan(banded[10:]).all())
        self.assertLess(spy.call_count, shape[0], "las bandas sin triángulos no se rasterizan")
        self.assertEqual(banded.tobytes(), one_piece(tin, shape).tobytes())


class TriangulationUnitsTest(unittest.TestCase):
    """RNF-016-03: la triangulación del cuerpo cede cada 256 puntos y da lo que ``PureTriangulator.triangulate``."""

    def test_it_gives_up_control_every_256_points_and_gives_the_same_triangles(self) -> None:
        xy = loose((200, 200), 1500, 4)
        triangles, units = drain(thickness._triangulate_units(xy))
        expected = cdt.PureTriangulator().triangulate(xy, np.empty((0, 2), dtype=np.int32))
        self.assertEqual(triangles.dtype, np.int32)
        self.assertEqual(triangles.tobytes(), expected.tobytes())
        self.assertGreaterEqual(units, 1500 // cdt.STEP_POINTS)


class CallsTest(unittest.TestCase):
    """RNF-016-03: ninguna llamada de ``body_steps`` pasa de 0,2 s con datos en secciones."""

    SIDE = 350  # 12 ha de celdas de 1 m
    GRID = sdata.window_grid(1.0, float(SIDE))

    def job(self, xy: np.ndarray) -> Any:
        """Un cuerpo «bajo un techo» sobre un plano a 100 m con un espesor ondulante, positivo, en cada dato."""
        x = self.GRID.west + (xy[:, 0] - 0.0)
        y = self.GRID.north + xy[:, 1]
        thick = 2.0 + 0.5 * np.sin(xy[:, 0] / 17.0) + 0.0005 * (-xy[:, 1])
        points = np.column_stack([x, y, thick])
        footprint = np.ones(self.GRID.shape, dtype=bool)
        return base.job_of(footprint, points=points, grid=self.GRID, support=np.full(self.GRID.shape, 100.0), distance=5000.0)

    def test_no_call_lasts_more_than_a_fifth_of_a_second(self) -> None:
        """12 ha con datos en secciones diagonales (los triángulos son astillas de caja grande: de una pieza el TIN costaba
        0,44 s): cada llamada de ``body_steps`` con el presupuesto de la interfaz (0,05 s) dura ≤ 0,2 s, y son varias."""
        xy = sections(self.SIDE, 4, 90)
        job = self.job(xy)
        work = thickness.body_steps(job, budget_s=0.05)
        laps: list[float] = []
        last = None
        while True:
            started = time.perf_counter()
            try:
                last = next(work)
            except StopIteration:
                break
            laps.append(time.perf_counter() - started)
        self.assertGreater(len(laps), 5)
        self.assertLessEqual(max(laps), LIMIT_S, f"la llamada más larga, {max(laps):.3f} s de {len(laps)}")
        self.assertIsNotNone(last)
        assert last is not None and last.result is not None
        outcome = last.result
        self.assertGreater(outcome.tin_cells, 10_000)  # el TIN llega a buena parte de la ventana
        self.assertEqual(outcome.nearest_cells + outcome.tin_cells, int(np.count_nonzero(outcome.body)))


if __name__ == "__main__":
    unittest.main()
