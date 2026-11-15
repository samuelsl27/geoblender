# SPDX-License-Identifier: GPL-3.0-or-later
"""La geometría de los datos de rendimiento de las entidades (spec 015, T33; RNF-015-01, RNF-015-02, RNF-015-06,
RNF-015-08 y RNF-015-09; plan 015 §7.1 y §7.3): ``tests/support/entity_data.py`` y
``tests/support/entity_synthetic.py``, que usan a la vez ``tests/rendimiento/des/test_entities_perf.py`` (con el
Python de Blender) y ``tests/rendimiento/blender/perf_entities.py`` (dentro de Blender).

Las pruebas de rendimiento no son del «verde» (``tools/check.py --rendimiento``): esto sí lo es y no genera el
terreno de escala (un par de segundos): comprueba solo lo que no se ve en una medida que sale bien o mal sin
decir por qué: que las 20 plataformas de la cadena caben en la ventana y en el perímetro de ``design_perf``, no se
tocan ni con su borde, y su huella es de menos de 1 ha (RNF-015-08); que la grande tiene 10 ha (RNF-015-01); y que
las huellas de las entidades sintéticas de las 200 (RNF-015-02 y RNF-015-06) no se solapan y caben en la rejilla.
"""

from __future__ import annotations

import unittest

from tests.support import constraints_data as cdata
from tests.support import design_data as ddata
from tests.support import entity_data as edata
from tests.support import entity_synthetic


def footprint_box(index: int) -> tuple[float, float, float, float]:
    """La caja local de la huella de la plataforma ``index`` de la cadena: de su eje (extremos planos, de
    ``CHAIN_AXIS_M`` de largo) y su ancho."""
    (x0, y), (x1, _same) = edata.chain_axis(index)
    half = edata.CHAIN_WIDTH_M / 2.0
    return x0, y - half, x1, y + half


class ChainGeometryTest(unittest.TestCase):
    """RNF-015-08: las 20 plataformas de ≤ 1 ha de la cadena."""

    def test_each_footprint_is_under_a_hectare_and_inside_the_perimeter(self) -> None:
        """RNF-015-08: la huella de cada una (``CHAIN_AXIS_M`` × ``CHAIN_WIDTH_M``, hasta una celda más de largo)
        es de menos de 1 ha (10.000 celdas de 1 m) y, con su borde, queda dentro del perímetro de actuación de la
        ventana de escala (``design_data.MARGIN_M`` dentro de ella)."""
        self.assertLess((edata.CHAIN_AXIS_M + 1.0) * edata.CHAIN_WIDTH_M, edata.FOOTPRINT_LIMIT_CELLS)
        margin = ddata.MARGIN_M + edata.CHAIN_REACH_M
        for index in range(edata.CHAIN_LENGTH):
            left, bottom, right, top = footprint_box(index)
            with self.subTest(plataforma=edata.chain_name(index)):
                self.assertGreater(left, margin)
                self.assertGreater(bottom, margin)
                self.assertLess(right, cdata.COLS * cdata.STEP_M - margin)
                self.assertLess(top, cdata.ROWS * cdata.STEP_M - margin)

    def test_no_edge_reaches_another_footprint(self) -> None:
        """RNF-015-08: entre dos huellas hay más que el alcance del borde (``CHAIN_REACH_M``): el borde de una no
        toca la huella de otra, así que ninguna cascada depende de que una cambie lo que otra ya hizo y la
        detección de lo que se apoya (A6) no encuentra nada que apoyar."""
        boxes = [footprint_box(index) for index in range(edata.CHAIN_LENGTH)]
        for first in range(len(boxes)):
            for second in range(first + 1, len(boxes)):
                a, b = boxes[first], boxes[second]
                gap_x = max(b[0] - a[2], a[0] - b[2])
                gap_y = max(b[1] - a[3], a[1] - b[3])
                with self.subTest(par=(first + 1, second + 1)):
                    self.assertGreater(max(gap_x, gap_y), edata.CHAIN_REACH_M)

    def test_the_names_are_the_ones_of_the_layer(self) -> None:
        """Los nombres son ``Plataforma 01`` a ``Plataforma 20``, distintos: la capa los usa para encontrar cada
        geometría."""
        names = [edata.chain_name(index) for index in range(edata.CHAIN_LENGTH)]
        self.assertEqual(names[0], "Plataforma 01")
        self.assertEqual(names[-1], "Plataforma 20")
        self.assertEqual(len(set(names)), edata.CHAIN_LENGTH)
        self.assertNotIn(edata.BIG_NAME, names)


class BigPlatformTest(unittest.TestCase):
    """RNF-015-01: la plataforma grande."""

    def test_it_is_ten_hectares_inside_the_window_with_room_for_its_edge(self) -> None:
        """RNF-015-01: 500 m de eje por 200 m de ancho son 10 ha (100.000 celdas de 1 m) y, con los 150 m de su
        borde, caben en la ventana de escala."""
        (x0, y0), (x1, y1) = edata.BIG_AXIS_LOCAL
        self.assertEqual(y0, y1)
        self.assertEqual((x1 - x0) * edata.BIG_WIDTH_M, 100_000.0)
        margin = ddata.MARGIN_M + edata.BIG_REACH_M
        self.assertGreater(x0, margin)
        self.assertLess(x1, cdata.COLS * cdata.STEP_M - margin)
        self.assertGreater(y0 - edata.BIG_WIDTH_M / 2.0, margin)
        self.assertLess(y0 + edata.BIG_WIDTH_M / 2.0, cdata.ROWS * cdata.STEP_M - margin)

    def test_the_big_platform_does_not_touch_the_chain(self) -> None:
        """RNF-015-01: la grande y la cadena están en la misma capa, pero lejos (aunque no se crean en el mismo
        proyecto): ni la huella de una de las veinte ni su borde alcanzan la grande ni el suyo."""
        (x0, y0), (x1, _y1) = edata.BIG_AXIS_LOCAL
        half = edata.BIG_WIDTH_M / 2.0
        big = (x0 - edata.BIG_REACH_M, y0 - half - edata.BIG_REACH_M, x1 + edata.BIG_REACH_M,
               y0 + half + edata.BIG_REACH_M)
        for index in range(edata.CHAIN_LENGTH):
            left, bottom, right, top = footprint_box(index)
            outside = right < big[0] or left > big[2] or top < big[1] or bottom > big[3]
            with self.subTest(plataforma=edata.chain_name(index)):
                self.assertTrue(outside)


class SyntheticFootprintsTest(unittest.TestCase):
    """RNF-015-02 y RNF-015-06: las huellas de juguete de las entidades de las 200."""

    def test_the_blocks_of_the_synthetic_entities_do_not_overlap_and_fit_in_the_grid(self) -> None:
        """Las 200 huellas de juguete son bloques de ``BLOCK_CELLS`` de lado, separados, dentro de la rejilla, con su
        ventana ``[fila0, fila1, col0, col1]`` y sus tramos de fila ``[fila, col0, col1]`` coherentes."""
        seen: set[tuple[int, int]] = set()
        for index in range(edata.SYNTHETIC_ENTITIES):
            runs, window = entity_synthetic.footprint(index)
            with self.subTest(entidad=index):
                self.assertEqual(len(runs), entity_synthetic.BLOCK_CELLS)
                self.assertEqual(window[1] - window[0], entity_synthetic.BLOCK_CELLS)
                self.assertEqual(window[3] - window[2], entity_synthetic.BLOCK_CELLS)
                for row, first, last in runs:
                    self.assertTrue(window[0] <= row < window[1])
                    self.assertEqual((first, last), (window[2], window[3]))
                self.assertLess(window[1], cdata.ROWS)
                self.assertLess(window[3], cdata.COLS)
                found = (window[0], window[2])
                self.assertNotIn(found, seen, "dos entidades con el mismo bloque")
                seen.add(found)
        self.assertEqual(len(seen), edata.SYNTHETIC_ENTITIES)


if __name__ == "__main__":
    unittest.main()
