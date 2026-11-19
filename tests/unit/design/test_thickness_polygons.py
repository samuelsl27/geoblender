# SPDX-License-Identifier: GPL-3.0-or-later
"""Los polígonos de espesor y los avisos del cuerpo apoyado, en el dominio (spec 016, T25; HU-016-4; RF-016-20, RF-016-21,
RNF-016-02; plan 016 §5.4 A11 y §5.7 P-7; decisión de la sesión principal del 19/11/2026).

La T24 midió que los datos **en polígonos** (que la T23 lleva al centro de cada celda) forman una retícula de Delaunay degenerada
y su triangulación es muy cara (160.000 puntos, 8,3 s). La decisión: **las celdas del interior de un polígono toman su espesor
directamente** y **solo las de su contorno entran en el TIN** y en el dato más próximo, con el mismo valor.

- :class:`InteriorTest`: qué es el interior (una celda con dato y sus cuatro vecinas con dato), a mano con un bucle.
- :class:`PolygonInteriorTest`: el resultado **en las celdas de los polígonos es el mismo que celda a celda** (el mismo polígono
  dado como un punto por celda, que se triangula entero) a ≤ 10⁻⁹ m; el dato más próximo de fuera, el mismo; lo lejano ignora el
  interior (son celdas con dato) y se triangulan menos datos.
- :class:`NoticesTest`: los avisos nuevos del cálculo: las celdas de la huella sin superficie conocida, más de ``MANY_DATA`` datos
  triangulados (el aviso de lo lento por el coste del TIN, de la T44, está en ``milestone_thickness_estimate.py``).
"""

from __future__ import annotations

import itertools
import unittest
from typing import Any
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.design import test_thickness as tt

thickness = import_geoblender("design.thickness")

EXACT = tt.EXACT
UNSUPPORTED = "des.body_unsupported"
MANY_DATA = "des.body_many_data"


def hand_interior(data: np.ndarray, painted: np.ndarray) -> set[tuple[int, int]]:
    """Las celdas de un polígono con dato cuyas cuatro vecinas tienen dato, en un bucle (fuera del array no hay dato)."""
    rows, cols = data.shape
    found = set()
    for row, col in itertools.product(range(rows), range(cols)):
        if not (data[row, col] and painted[row, col]):
            continue
        if all(0 <= row + dr < rows and 0 <= col + dc < cols and data[row + dr, col + dc]
               for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))):
            found.add((row, col))
    return found


class InteriorTest(unittest.TestCase):
    """El interior de un polígono (T25): una celda de un polígono con las cuatro vecinas con dato."""

    def test_the_interior_is_what_a_loop_says(self) -> None:
        """RF-016-20 (decisión 19/11/2026): ``interior_cells`` coincide con el bucle de ``hand_interior`` en una mezcla de dos
        polígonos que se tocan, con un hueco y con una celda suelta, y **el borde del array no es interior**."""
        data = np.zeros((14, 16), dtype=bool)
        painted = np.zeros_like(data)
        data[2:9, 2:9] = painted[2:9, 2:9] = True
        data[5:12, 7:14] = painted[5:12, 7:14] = True
        data[4:6, 4:6] = painted[4:6, 4:6] = False  # un hueco: sus vecinas pasan a ser del borde
        data[12, 1] = True  # un dato suelto que no es de un polígono
        data[0:3, 14:16] = painted[0:3, 14:16] = True  # pegado al borde del array
        found = thickness.interior_cells(data, painted)
        self.assertEqual({(int(r), int(c)) for r, c in zip(*np.nonzero(found), strict=True)}, hand_interior(data, painted))
        self.assertGreater(int(found.sum()), 10)
        self.assertFalse(found[0, :].any() or found[-1, :].any() or found[:, 0].any() or found[:, -1].any())
        self.assertFalse(found[12, 1], "un dato que no es de un polígono no es interior")

    def test_a_datum_next_to_a_polygon_makes_its_cell_interior_when_it_closes_the_ring(self) -> None:
        """Las vecinas cuentan **de cualquier origen**: un punto en la vecina que faltaba cierra el anillo de la celda."""
        data = np.zeros((7, 7), dtype=bool)
        painted = np.zeros_like(data)
        data[2:5, 2:5] = painted[2:5, 2:5] = True
        data[2, 3] = painted[2, 3] = False  # la de arriba del centro, sin dato: el centro es del borde
        self.assertFalse(thickness.interior_cells(data, painted)[3, 3])
        data[2, 3] = True  # ... y con dato de un punto (no es de un polígono): el centro es del interior
        self.assertTrue(thickness.interior_cells(data, painted)[3, 3])


class PolygonInteriorTest(unittest.TestCase):
    """RF-016-20, RNF-016-02: un polígono grande, el mismo resultado en sus celdas y mucho menos que triangular."""

    POLY = ((tt.ring(6, 16, 6, 16),), 2.0)
    OUTSIDE = {(2, 2): 1.0, (2, 20): 4.0, (20, 2): 3.0, (20, 20): 0.5}
    FOOT = tt.box(1, 22, 1, 22)

    def both(self, **extra: Any) -> tuple[Any, Any]:
        """El polígono de 10 × 10 celdas (2 m) con cuatro puntos fuera, como polígono y como **un punto por celda** (la T23: cada
        celda un vértice del TIN)."""
        cells = {(row, col): 2.0 for row in range(6, 16) for col in range(6, 16)}
        as_polygon = tt.run(tt.job_of(self.FOOT, points=tt.points_of(self.OUTSIDE), polygons=[self.POLY], **extra))
        one_by_one = tt.run(tt.job_of(self.FOOT, points=tt.points_of({**self.OUTSIDE, **cells}), **extra))
        return as_polygon, one_by_one

    def test_the_polygon_cells_have_the_same_thickness_as_cell_by_cell(self) -> None:
        """RF-016-20 (decisión 19/11/2026): en las celdas del polígono el espesor es el suyo, **igual** (≤ 10⁻⁹ m) que dando el
        polígono celda a celda; las 8 × 8 del interior son directas y se triangulan 100 − 64 + 4 datos (frente a 104)."""
        found, wanted = self.both()
        inside = tt.box(6, 16, 6, 16)
        np.testing.assert_allclose(found.thickness[inside], wanted.thickness[inside], rtol=0.0, atol=EXACT)
        np.testing.assert_array_equal(found.thickness[inside], np.full(100, 2.0))
        self.assertEqual((found.direct_cells, wanted.direct_cells), (64, 0))
        self.assertEqual((found.tin_points, wanted.tin_points), (100 - 64 + 4, 104))
        self.assertEqual((found.data_cells, found.ignored), (wanted.data_cells, wanted.ignored))
        self.assertEqual(found.tin_cells + found.nearest_cells + found.direct_cells, int(np.count_nonzero(found.body)))
        self.assertEqual((wanted.tin_cells + wanted.nearest_cells + wanted.direct_cells), int(np.count_nonzero(wanted.body)))

    def test_outside_the_hull_the_nearest_datum_is_the_same(self) -> None:
        """Lo que el interior quita **no cambia el dato más próximo** de ninguna celda sin dato (el más próximo a un punto sin dato es
        siempre una celda del borde): el anillo de celdas de la huella fuera de la envolvente de los datos, que toma el más próximo,
        es igual bit a bit; y el volumen, el máximo y lo lejano coinciden con celda a celda."""
        found, wanted = self.both()
        ring_cells = ~tt.box(2, 21, 2, 21) & self.FOOT
        np.testing.assert_array_equal(found.thickness[ring_cells], wanted.thickness[ring_cells])
        self.assertEqual(found.thickness_max_m, wanted.thickness_max_m)
        self.assertLessEqual(float(np.nanmax(found.thickness)), 4.0)
        self.assertGreaterEqual(float(np.nanmin(found.thickness)), 0.5)

    def test_the_far_cells_ignore_the_interior_that_left_the_nearest_datum(self) -> None:
        """RF-016-21: el interior son celdas **con dato**, a 0 m de él, aunque ya no sean fuente del dato más próximo: con el
        polígono de 20 × 20 como huella y una distancia máxima de una celda, **nada es lejano** (si el interior contara su distancia
        al contorno, el centro, a 15 celdas, lo sería)."""
        big = ((tt.ring(3, 23, 3, 23),), 2.5)
        foot = tt.box(3, 23, 3, 23)
        outcome = tt.run(tt.job_of(foot, polygons=[big], distance=2.0))
        self.assertEqual(outcome.far_m2, 0.0)
        self.assertEqual(outcome.farthest_m, 0.0)
        self.assertNotIn(tt.FAR, [notice.code for notice in outcome.notices])
        self.assertEqual(outcome.direct_cells, 18 * 18)
        np.testing.assert_array_equal(outcome.thickness[foot], np.full(400, 2.5))

    def test_overlapping_polygons_take_the_mean_in_their_interior(self) -> None:
        """RF-016-20: donde coinciden dos polígonos, su media, también en el interior directo: 2 m y 4 m dan 3 m en el solape; el
        interior, contado a mano en un bucle."""
        p1 = ((tt.ring(3, 15, 3, 15),), 2.0)
        p2 = ((tt.ring(6, 18, 6, 18),), 4.0)
        found = tt.run(tt.job_of(tt.box(2, 19, 2, 19), polygons=[p1, p2]))
        expected: dict[tuple[int, int], list[float]] = {}
        for row, col in itertools.product(range(3, 15), range(3, 15)):
            expected.setdefault((row, col), []).append(2.0)
        for row, col in itertools.product(range(6, 18), range(6, 18)):
            expected.setdefault((row, col), []).append(4.0)
        data = np.zeros(tt.GRID.shape, dtype=bool)
        for row, col in expected:
            data[row, col] = True
        self.assertEqual(found.direct_cells, len(hand_interior(data, data)))
        for (row, col), values in expected.items():
            self.assertLessEqual(abs(found.thickness[row, col] - sum(values) / len(values)), EXACT, (row, col))
        self.assertLessEqual(abs(found.thickness[9, 9] - 3.0), EXACT)
        self.assertIn((9, 9), hand_interior(data, data))


    def test_the_gap_between_two_polygons_is_still_interpolated_and_a_lone_polygon_needs_no_triangle(self) -> None:
        """RF-016-20, RNF-016-02: los triángulos **dentro** de un polígono (sus tres vértices de polígono y su centroide en él) se
        descartan —rasterizarlos costaba lo que sus cajas—, pero **el hueco entre dos polígonos se sigue interpolando** (los
        triángulos que unen uno con otro): con 1 m a la izquierda y 3 m a la derecha, el hueco de cinco columnas da la recta
        ``1 + 2·(columna − 8)/6`` a ≤ 10⁻⁹ m; y un polígono solo no deja ningún triángulo y todo es suyo."""
        left = ((tt.ring(6, 16, 3, 9),), 1.0)
        right = ((tt.ring(6, 16, 14, 20),), 3.0)
        found = tt.run(tt.job_of(tt.box(5, 17, 2, 21), polygons=[left, right]))
        for row in range(6, 16):
            for col in range(9, 14):
                self.assertLessEqual(abs(found.thickness[row, col] - (1.0 + 2.0 * (col - 8) / 6.0)), EXACT, (row, col))
        self.assertGreater(found.tin_cells, 5 * 10 - 1)
        self.assertGreater(found.direct_cells, 0)
        lone = tt.run(tt.job_of(tt.box(5, 17, 2, 10), polygons=[left]))
        self.assertEqual(lone.tin_cells, 0, "ningún triángulo: todo es del polígono o del más próximo")
        np.testing.assert_array_equal(lone.thickness[tt.box(6, 16, 3, 9)], np.full(60, 1.0))


class NoticesTest(unittest.TestCase):
    """RF-016-20, RNF-016-02: los avisos nuevos del cálculo (se puede crear igualmente)."""

    FOOT = tt.box(3, 21, 3, 21)

    def test_the_cells_of_the_footprint_without_the_known_surface_are_warned(self) -> None:
        """RF-016-20 (la nota de la T23): las celdas de la huella **sin superficie conocida** no tienen cuerpo y se avisan con su
        área (m²) y el nombre de la superficie; el cuerpo es solo donde hay (una banda de 4 × 18 celdas sin dato = 288 m²)."""
        support = np.full(tt.GRID.shape, 100.0)
        support[3:7, 3:21] = np.nan
        outcome = tt.run(tt.job_of(self.FOOT, points=tt.points_of({(10, 10): 2.0, (14, 14): 3.0}), support=support))
        self.assertEqual(outcome.unsupported_cells, 4 * 18)
        (notice,) = [item for item in outcome.notices if item.code == UNSUPPORTED]
        self.assertEqual(notice.values["entity"], "Cuerpo A")
        self.assertEqual(notice.values["surface"], "Terreno")
        self.assertEqual(notice.values["area"], 4 * 18 * tt.AREA)
        self.assertEqual(notice.severity, "warning")
        self.assertIn("Terreno", notice.text())
        self.assertNotIn("{", notice.text("en"))
        clean = tt.run(tt.job_of(self.FOOT, points=tt.points_of({(10, 10): 2.0, (14, 14): 3.0})))
        self.assertNotIn(UNSUPPORTED, [item.code for item in clean.notices])

    def test_more_triangulated_data_than_the_limit_are_warned(self) -> None:
        """RNF-016-02 (decisión 19/11/2026): con más de ``MANY_DATA`` datos triangulados el resumen avisa con su número y el
        límite; con los mismos o menos, no. Con el límite bajado a 20: 25 datos sueltos avisan, 20 no."""
        cells = list(itertools.product(range(4, 20, 3), range(4, 20, 3)))  # 36
        rows = {cell: 1.0 + (cell[0] + cell[1]) % 3 for cell in cells}
        with mock.patch.object(thickness, "MANY_DATA", 20):
            many = tt.run(tt.job_of(self.FOOT, points=tt.points_of(dict(list(rows.items())[:25]))))
            few = tt.run(tt.job_of(self.FOOT, points=tt.points_of(dict(list(rows.items())[:20]))))
        (notice,) = [item for item in many.notices if item.code == MANY_DATA]
        self.assertEqual((notice.values["data"], notice.values["limit"]), (25, 20))
        self.assertEqual(many.tin_points, 25)
        self.assertNotIn(MANY_DATA, [item.code for item in few.notices])
        self.assertEqual(thickness.MANY_DATA, 40_000)


if __name__ == "__main__":
    unittest.main()
