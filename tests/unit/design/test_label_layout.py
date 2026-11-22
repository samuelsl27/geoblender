# SPDX-License-Identifier: GPL-3.0-or-later
"""La colocación sin solapes de los nombres de la vista previa de una pista (spec 017, T50; hallazgo H3-3 del H3; HU-017-1; RF-017-26, RF-015-26).

``design.label_layout.place_labels`` es una función **pura** (sin ``bpy``, sin ``blf``): recibe los sitios (px) y los anchos de los nombres, la altura del texto y el rango de cada uno, y dice
**cuáles se dibujan**: se ponen primero los de más rango (los que no tienen rango, siempre) y se salta el que cae a menos de una altura de texto de otro ya puesto (su caja se solapa con la de
aquel). Las pruebas, con posiciones hechas a mano, en el orden de sus letras:

- (a) el origen y su primer tramo a unos 3 m (a 520 m de la cámara, unos píxeles): se dibuja el origen y se salta el tramo; igual el destino y el último; los tramos de 1 m entre sí;
- (b) un solo nombre se dibuja siempre; los que están a una altura de texto o más (o a un lado del otro) se dibujan todos;
- (c) entre iguales gana el primero; el de más rango gana aunque esté después, y el tramo más empinado sobrevive a los de su alrededor;
- (d) los que no tienen rango no se saltan nunca (como los nombres de lo que se apoya en la pista y los de las demás vistas previas) y los demás los esquivan;
- (e) lo que no es de la función (listas de distinto largo, una altura que no es positiva) es un error del programa.
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

place_labels = import_geoblender("design.label_layout").place_labels

HEIGHT = 12.0
"""La altura del texto de la prueba (px)."""
WIDTH = 150.0
"""El ancho de un nombre de la prueba (px)."""


class PlaceLabelsTest(unittest.TestCase):
    """``place_labels`` con casos a mano."""

    def test_a_what_falls_on_another_is_skipped_the_origin_and_the_destination_first(self) -> None:
        """RF-017-26 (H3-3): el origen y su primer tramo a 3 m —a 520 m de distancia, 2 px de por medio— se solapan: se dibuja el origen y se salta el tramo; el destino y el último, igual; tres tramos de
        1 m entre sí (1 px), uno solo; y los nombres lejanos se dibujan todos: origen, destino y un tramo del medio."""
        origin, first, middle, last, destination = (100.0, 300.0), (101.0, 301.5), (400.0, 300.0), (698.0, 299.0), (700.0, 300.0)
        points = [origin, first, middle, last, destination]
        ranks = [2, 0, 0, 0, 2]
        self.assertEqual(place_labels(points, [WIDTH] * 5, HEIGHT, ranks), [0, 2, 4])
        tiny = [(500.0, 100.0), (501.0, 100.0), (502.0, 100.5), (503.0, 99.5)]
        self.assertEqual(place_labels(tiny, [WIDTH] * 4, HEIGHT, [0] * 4), [0], "tramos de 1 m: se dibuja uno")

    def test_b_a_single_label_and_the_ones_a_text_height_apart_or_side_by_side_are_all_drawn(self) -> None:
        """RF-017-26 (H3-3): un solo nombre (un solo tramo) se dibuja; dos a una altura de texto de distancia (sin tocarse) o más, también; y dos en la misma línea pero uno a la derecha del otro (sin
        que se solapen sus cajas), también; sin ninguno, nada."""
        self.assertEqual(place_labels([(10.0, 10.0)], [WIDTH], HEIGHT, [0]), [0])
        self.assertEqual(place_labels([], [], HEIGHT, []), [])
        self.assertEqual(place_labels([(10.0, 10.0), (12.0, 10.0 + HEIGHT)], [WIDTH] * 2, HEIGHT, [0, 0]), [0, 1], "a justo una altura: no se tocan")
        self.assertEqual(place_labels([(10.0, 10.0), (12.0, 10.0 + HEIGHT - 0.5)], [WIDTH] * 2, HEIGHT, [0, 0]), [0], "a menos de una altura: se solapan")
        self.assertEqual(place_labels([(10.0, 10.0), (10.0 + WIDTH, 10.0)], [WIDTH] * 2, HEIGHT, [0, 0]), [0, 1], "uno a continuación del otro")
        self.assertEqual(place_labels([(10.0, 10.0), (10.0 + WIDTH - 1.0, 10.0)], [WIDTH] * 2, HEIGHT, [0, 0]), [0], "uno monta sobre el otro")
        self.assertEqual(place_labels([(10.0, 10.0), (500.0, 10.0), (10.0, 400.0)], [WIDTH] * 3, HEIGHT, [0, 0, 0]), [0, 1, 2])

    def test_c_the_first_wins_among_equals_the_higher_rank_wins_and_the_steepest_survives(self) -> None:
        """RF-017-26 (H3-3): entre dos de igual rango se dibuja el primero; el de más rango gana aunque esté después (el origen sobre el tramo que lo tapaba); y entre seis tramos que se tapan
        entre sí, el más empinado (rango 1) es el que queda, con el origen y el destino (rango 2) aparte; el resultado sale en el orden de los nombres."""
        self.assertEqual(place_labels([(10.0, 10.0), (11.0, 10.0)], [WIDTH] * 2, HEIGHT, [0, 0]), [0])
        self.assertEqual(place_labels([(10.0, 10.0), (11.0, 10.0)], [WIDTH] * 2, HEIGHT, [0, 1]), [1])
        stretches = [(300.0 + index, 200.0) for index in range(6)]
        points = [(100.0, 500.0), *stretches, (900.0, 500.0)]
        ranks = [2, 0, 0, 1, 0, 0, 0, 2]
        self.assertEqual(place_labels(points, [WIDTH] * 8, HEIGHT, ranks), [0, 3, 7])

    def test_d_a_label_without_rank_is_never_skipped_and_the_others_avoid_it(self) -> None:
        """RF-017-26, RF-015-26 (H3-3): el nombre sin rango (``None``: lo de las demás vistas previas y lo que se apoya en la pista) se dibuja siempre, aunque se solape con otro sin rango, y los que
        tienen rango se saltan si caen sobre él; sin ningún rango, todos se dibujan."""
        points = [(10.0, 10.0), (11.0, 10.0), (12.0, 10.0)]
        self.assertEqual(place_labels(points, [WIDTH] * 3, HEIGHT, [None, None, None]), [0, 1, 2])
        self.assertEqual(place_labels(points, [WIDTH] * 3, HEIGHT, [0, None, 1]), [1], "los de rango esquivan al que no lo tiene")
        self.assertEqual(place_labels(points, [WIDTH] * 3, HEIGHT, [5, None, 7]), [1])
        self.assertEqual(place_labels(points, [WIDTH] * 3, HEIGHT), [0, 1, 2], "sin rangos: todos")

    def test_e_what_the_function_does_not_take_is_an_error_of_the_program(self) -> None:
        """Una altura que no es positiva o listas de distinto largo no son de la función: ``ValueError``."""
        for bad in ({"points": [(0.0, 0.0)], "widths": [1.0, 2.0], "height": HEIGHT, "ranks": [0]},
                    {"points": [(0.0, 0.0)], "widths": [1.0], "height": HEIGHT, "ranks": [0, 1]},
                    {"points": [(0.0, 0.0)], "widths": [1.0], "height": 0.0, "ranks": [0]},
                    {"points": [(0.0, 0.0)], "widths": [1.0], "height": float("nan"), "ranks": [0]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                place_labels(**bad)


if __name__ == "__main__":
    unittest.main()
