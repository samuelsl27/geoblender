# SPDX-License-Identifier: GPL-3.0-or-later
"""La línea que se corta a sí misma (spec 017, T42; HU-017-1; RF-017-04; RNF-017-06; hallazgos B-4 y A-5 (M8) de la verificación única): la comprobación de
``road_store._first_crossing`` rechaza una línea cuyos tramos no contiguos se cortan, se tocan o se solapan (RF-017-04) **sin pasar de 0,2 s por llamada** (RNF-017-06) con
las líneas densas de una capa digitalizada (5.000 vértices: 0,58 s con la versión de todos contra todos).

El oráculo es la versión de todos contra todos de la T19 (:func:`reference_first_crossing`, **copiada tal cual**): lo que no cambia es **qué rechaza** ni **dónde dice que
se corta** (el mismo primer par de tramos y el mismo punto, bit a bit) en las seis formas de la línea —el cruce, la T, el lazo cerrado que solo se toca en un extremo (el
mutante M8 de A-5), el vértice repetido, los tramos colineales que se solapan y los que no— y en líneas al azar, con las coordenadas locales y con las absolutas de la
cantera (UTM: la parte entera de 7 cifras es la que más redondea). Lo que pasa de ~50 ms (miles de líneas al azar y degeneradas, 20.000 vértices, las líneas con tramos muy
largos) es de ``milestone_road_crossing``.
"""

from __future__ import annotations

import unittest

import numpy as np

from tests.support.package import import_geoblender
from tests.support.timing import best_of

road_store = import_geoblender("design.road_store")

EAST, NORTH = 500000.0, 4400000.0
"""Una esquina de la cantera en UTM (25830): las coordenadas absolutas que lee la preparación."""
STEP_LIMIT_S = 0.2
"""Lo que puede tardar cada llamada (RNF-017-06)."""


def reference_first_crossing(points: np.ndarray) -> tuple[float, float] | None:
    """``road_store._first_crossing`` de la T19 (todos contra todos, O(n²)), copiada tal cual: el oráculo de la T42."""
    start, end = points[:-1], points[1:]
    for i in range(len(start) - 2):
        others = np.arange(i + 2, len(start))
        p, r = start[i], end[i] - start[i]
        q, s = start[others], end[others] - start[others]
        offset = q - p
        cross = r[0] * s[:, 1] - r[1] * s[:, 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (offset[:, 0] * s[:, 1] - offset[:, 1] * s[:, 0]) / cross
            u = (offset[:, 0] * r[1] - offset[:, 1] * r[0]) / cross
            long = float(r @ r)
            t0 = (offset @ r) / long
            t1 = t0 + (s @ r) / long
        hit = (cross != 0.0) & (t >= 0.0) & (t <= 1.0) & (u >= 0.0) & (u <= 1.0)
        parallel = (cross == 0.0) & ((offset[:, 0] * r[1] - offset[:, 1] * r[0]) == 0.0) & (np.maximum(np.minimum(t0, t1), 0.0) <= np.minimum(np.maximum(t0, t1), 1.0))
        found = hit | parallel
        if found.any():
            k = int(np.argmax(found))
            point = p + t[k] * r if bool(hit[k]) else q[k]
            return float(point[0]), float(point[1])
    return None


SHAPES: dict[str, tuple[tuple[tuple[float, float], ...], tuple[float, float] | None]] = {
    "cruce": (((0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)), (1.0, 1.0)),
    "T: un vértice sobre el interior de un tramo": (((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 4.0), (2.0, 0.0)), (2.0, 0.0)),
    "lazo cerrado: solo se toca en un extremo": (((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)), (0.0, 0.0)),
    "vértice repetido (no consecutivo)": (((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0)), (2.0, 0.0)),
    "colineales que se solapan": (((0.0, 0.0), (6.0, 0.0), (7.0, 5.0), (9.0, 0.0), (4.0, 0.0)), (9.0, 0.0)),
    "colineales que no se solapan": (((0.0, 0.0), (2.0, 0.0), (2.0, 3.0), (6.0, 3.0), (6.0, 0.0), (8.0, 0.0)), None),
    "sin cruce (un caracol)": (((0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (2.0, 6.0), (2.0, 2.0), (5.0, 2.0), (5.0, 4.0)), None),
}
"""Las formas de la línea con el primer punto en que se corta (local) o ``None``."""


def placed(local: tuple[tuple[float, float], ...], *, absolute: bool) -> np.ndarray:
    """La forma ``local`` como array ``(k, 2)``: tal cual o con la esquina de la cantera en UTM (la suma de un entero: sin redondeo, la forma es la misma)."""
    points = np.array(local, dtype=np.float64)
    return points + np.array([EAST, NORTH]) if absolute else points


class FirstCrossingTest(unittest.TestCase):
    def test_the_six_shapes_of_a_line_give_what_the_quadratic_version_gives(self) -> None:
        """RF-017-04, A-5 (M8): el cruce, la T, el lazo cerrado que solo se toca en un extremo, el vértice repetido, los colineales que se solapan y los que no, y una línea
        sin cruce dan **el mismo punto** que la versión de todos contra todos (y el esperado a mano), con las coordenadas locales y con las de la cantera en UTM."""
        for name, (local, expected) in SHAPES.items():
            for absolute in (False, True):
                with self.subTest(shape=name, absolute=absolute):
                    line = placed(local, absolute=absolute)
                    found = road_store._first_crossing(line)
                    self.assertEqual(found, reference_first_crossing(line))
                    if expected is None:
                        self.assertIsNone(found)
                    else:
                        want = placed((expected,), absolute=absolute)[0]
                        self.assertEqual(found, (float(want[0]), float(want[1])))

    def test_a_line_that_only_touches_itself_at_one_end_is_rejected(self) -> None:
        """RF-017-04, A-5 (M8): el lazo cerrado (el último vértice es el primero) y la T (el último vértice cae sobre un tramo) **se rechazan**: tocarse en un extremo cuenta
        (``t = 0`` o ``u = 1``: los extremos del intervalo son del cruce), y una línea abierta que no se toca no."""
        loop = placed(SHAPES["lazo cerrado: solo se toca en un extremo"][0], absolute=True)
        self.assertEqual(road_store._first_crossing(loop), (EAST, NORTH))
        self.assertIsNone(road_store._first_crossing(loop[:-1]), "sin cerrar el lazo no se toca")
        tee = placed(SHAPES["T: un vértice sobre el interior de un tramo"][0], absolute=True)
        self.assertEqual(road_store._first_crossing(tee), (EAST + 2.0, NORTH))
        self.assertIsNone(road_store._first_crossing(tee[:-1]))

    def test_short_lines_at_random_give_what_the_quadratic_version_gives(self) -> None:
        """RF-017-04: líneas al azar de 3 a 9 vértices en una cuadrícula entera de 5 × 5 (muchos vértices repetidos, colineales y tocándose) dan el mismo punto o ninguno que la
        versión de todos contra todos; la prueba de miles, en ``milestone_road_crossing``."""
        rng = np.random.default_rng(42)
        crossing = 0
        for _ in range(40):
            count = int(rng.integers(3, 10))
            line = rng.integers(0, 5, size=(count, 2)).astype(np.float64) + np.array([EAST, NORTH])
            want = reference_first_crossing(line)
            crossing += want is not None
            self.assertEqual(road_store._first_crossing(line), want, line.tolist())
        self.assertTrue(0 < crossing < 40, "las líneas al azar tienen cruces y no los tienen")

    def test_a_dense_line_of_5000_vertices_is_checked_in_at_most_0_2_s(self) -> None:
        """RNF-017-06, RF-017-04, B-4: una línea digitalizada a ~1 m en 5 km (5.000 vértices, sin cruces) se comprueba en ≤ 0,2 s **por llamada** (la versión de todos contra
        todos tardaba 0,58 s; con 20.000 vértices, 8 s: ``milestone_road_crossing``)."""
        t = np.linspace(0.0, 6.0, 5000)
        line = np.column_stack([EAST + 400.0 * t, NORTH + 80.0 * np.sin(t * 2.0)])
        self.assertIsNone(road_store._first_crossing(line))
        self.assertLessEqual(best_of(lambda: road_store._first_crossing(line), STEP_LIMIT_S, attempts=1, max_attempts=3), STEP_LIMIT_S)


if __name__ == "__main__":
    unittest.main()
