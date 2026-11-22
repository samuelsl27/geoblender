# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_crossing» (spec 017, T42; RF-017-04; RNF-017-06; B-4 y A-5 (M8) de la verificación única): lo que pasa de ~50 ms y no entra en el «verde»
(``tools/check.py``, RNF-017-09); lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **El oráculo** (miles de líneas): ``road_store._first_crossing`` da **el mismo punto** (o ninguno) que la versión de todos contra todos de la T19 (``reference_first_crossing``,
  copiada tal cual) en líneas al azar y degeneradas de todas las formas que tiene la capa de una cantera: cuadrículas enteras (muchos vértices repetidos, colineales y tocándose,
  con tramos de longitud cero), múltiplos de 0,25 (exactos), coordenadas continuas, líneas casi rectas y sin cruces, caminatas al azar como una línea digitalizada, un vértice
  **puesto sobre un tramo** (que el redondeo deja a 10⁻¹⁰ m de él: el caso difícil de una búsqueda por cajas) o sobre un extremo, un vértice sin dato, tramos larguísimos entre
  miles de cortos; con coordenadas locales y con las absolutas de la cantera (UTM).
- **La única diferencia** (``test_in_the_noise_regime_the_search_never_rejects_what_the_quadratic_version_accepts``): con coordenadas pequeñas (cerca del origen, que una capa de
  cantera nunca tiene) y vértices sobre una recta que **no son exactamente colineales** (``k · d`` redondeado), las cuentas de todos contra todos dan un cruce falso entre tramos que
  no se tocan —el cociente de dos errores de redondeo cae en [0, 1]— y rechazan una recta (512 de 1.500 rectas con el origen en 0); la búsqueda por cajas no los ve, porque están
  separados. Con las coordenadas de la cantera (UTM) no hay ninguna diferencia. **Nunca rechaza lo que la otra acepta.**
- **El plazo** (RNF-017-06): una línea de 5.000, de 20.000 y de 100.000 vértices sin cruces se comprueba en ≤ 0,2 s por llamada (con todos contra todos: 0,58 s, 8,1 s y, por n², ≈ 200 s), y
  ``_read_line`` entera con 20.000, y una línea que se corta nada más empezar se rechaza sin mirar el resto.
"""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

import numpy as np

from tests.support.package import import_geoblender
from tests.support.timing import best_of
from tests.unit.design.test_road_crossing import EAST, NORTH, STEP_LIMIT_S, reference_first_crossing

road_store = import_geoblender("design.road_store")
messages = import_geoblender("design.messages")

OFFSET = np.array([EAST, NORTH])


def digitised(count: int) -> np.ndarray:
    """Una línea de ``count`` vértices a lo largo de 2,4 km con una onda de ± 80 m (UTM), sin cruces."""
    t = np.linspace(0.0, 6.0, count)
    return np.column_stack([EAST + 400.0 * t, NORTH + 80.0 * np.sin(t * 2.0)])


class OracleTest(unittest.TestCase):
    """RF-017-04: el mismo punto, bit a bit, que la versión de todos contra todos."""

    def compare(self, lines: list[np.ndarray]) -> tuple[int, int]:
        """Cuántas de ``lines`` se cortan y cuántas no, con **0 diferencias** frente al oráculo."""
        crossing = 0
        for line in lines:
            want = reference_first_crossing(line)
            crossing += want is not None
            self.assertEqual(road_store._first_crossing(line), want, line.tolist())
        return crossing, len(lines) - crossing

    def test_random_lines_on_integer_grids_with_repeated_vertices(self) -> None:
        """RF-017-04, A-5 (M8): 4.000 líneas de 3 a 30 vértices en cuadrículas enteras de 3 × 3, 6 × 6, 12 × 12 y 40 × 40 (con un vértice igual al anterior, tramos de longitud
        cero, en el 30 %), locales o en UTM: el mismo primer punto o ninguno; hay cruces y no los hay."""
        rng = np.random.default_rng(7)
        for size in (3, 6, 12, 40):
            lines = []
            for _ in range(1000):
                count = int(rng.integers(3, 31))
                points = rng.integers(0, size, size=(count, 2)).astype(np.float64)
                if rng.random() < 0.3:
                    k = int(rng.integers(1, count))
                    points[k] = points[k - 1]
                lines.append(points + OFFSET if rng.random() < 0.5 else points)
            with self.subTest(size=size):
                crossing, free = self.compare(lines)
                self.assertGreater(crossing, 100)
                self.assertGreater(free, 20 if size < 40 else 0)

    def test_lines_that_are_exact_in_floating_point_or_continuous(self) -> None:
        """RF-017-04: múltiplos de 0,25 (exactos en UTM), coordenadas continuas al azar, líneas casi rectas que avanzan en x (casi sin cruces) y caminatas al azar con pasos de 0,5
        a 5 m (una línea digitalizada: ángulos que giran poco o mucho): el mismo punto o ninguno."""
        rng = np.random.default_rng(11)
        quarter = [rng.integers(0, 20, size=(int(rng.integers(3, 31)), 2)) * 0.25 + OFFSET for _ in range(1500)]
        random = [rng.random((int(rng.integers(3, 41)), 2)) * 100.0 + OFFSET for _ in range(1500)]
        monotone = []
        for _ in range(600):
            count = int(rng.integers(3, 60))
            x = np.sort(rng.random(count)) * 1000.0
            y = rng.random(count) * (5.0 if rng.random() < 0.5 else 400.0)
            monotone.append(np.column_stack([x, y]) + OFFSET)
        walks = []
        for _ in range(200):
            count = int(rng.integers(50, 400))
            angle = np.cumsum(rng.normal(0.0, rng.choice([0.05, 0.3, 1.0]), count))
            step = rng.uniform(0.5, 5.0, count)
            walks.append(np.column_stack([np.cumsum(step * np.cos(angle)), np.cumsum(step * np.sin(angle))]) + OFFSET)
        found = {}
        for name, lines in (("múltiplos de 0,25", quarter), ("continuas", random), ("casi rectas", monotone), ("caminatas", walks)):
            with self.subTest(family=name):
                found[name] = self.compare(lines)
        self.assertEqual(found["casi rectas"][0], 0, "las líneas que solo avanzan en x no se cortan")
        self.assertGreater(min(found["caminatas"]), 30, "hay caminatas con cruces y sin ellos")
        self.assertGreater(found["continuas"][0], 1000)

    def test_a_vertex_placed_on_a_segment_or_on_an_end_is_the_hard_case_of_a_search_by_boxes(self) -> None:
        """RF-017-04, A-5 (M8): el último vértice puesto **sobre el interior de un tramo** (``p + t · r``: el redondeo lo deja a ~10⁻¹⁰ m de él, a un lado u otro, y las cuentas de
        siempre lo dan por tocado o no según el lado) y sobre **un extremo** de un tramo (un lazo, una T): el mismo punto o ninguno, 4.000 líneas en UTM."""
        rng = np.random.default_rng(13)
        interior, extreme = [], []
        for _ in range(2000):
            count = int(rng.integers(4, 12))
            points = rng.random((count, 2)) * 100.0 + OFFSET
            k = int(rng.integers(0, count - 2))
            points[-1] = points[k] + rng.random() * (points[k + 1] - points[k])
            interior.append(points)
            other = rng.random((count, 2)) * 100.0 + OFFSET
            other[-1] = other[k + int(rng.integers(0, 2))]
            extreme.append(other)
        self.assertGreater(self.compare(interior)[0], 1000)
        self.assertGreater(self.compare(extreme)[0], 1000)

    def test_a_vertex_a_few_ulps_off_an_end_is_still_found_by_the_search_by_boxes(self) -> None:
        """RF-017-04, B-4: el último vértice a 0 a 3 unidades de la última cifra (un ``nextafter`` por eje) de un extremo o de un punto de un tramo, con las coordenadas pequeñas (el cuadrado
        unidad y 100 m desde el origen), donde ``t`` y ``u`` de las cuentas de siempre caen justo en 0 o en 1 con las cajas separadas una unidad: el mismo punto o ninguno (**sin el margen
        de las cajas, 13 de 6.000 líneas dan otro resultado**: lo fija esta prueba)."""
        rng = np.random.default_rng(5)

        def nudged(value: float, ulps: int) -> float:
            for _ in range(abs(ulps)):
                value = float(np.nextafter(value, np.inf if ulps > 0 else -np.inf))
            return value

        for scale in (1.0, 100.0):
            lines = []
            for _ in range(3000):
                count = int(rng.integers(4, 9))
                points = rng.random((count, 2)) * scale
                k = int(rng.integers(0, count - 2))
                base = points[k + 1] if rng.random() < 0.5 else points[k] + rng.random() * (points[k + 1] - points[k])
                ulps = rng.integers(-3, 4, size=2)
                points[-1] = [nudged(float(base[0]), int(ulps[0])), nudged(float(base[1]), int(ulps[1]))]
                lines.append(points)
            with self.subTest(scale=scale):
                self.assertGreater(self.compare(lines)[0], 1000)

    def test_in_the_noise_regime_the_search_never_rejects_what_the_quadratic_version_accepts(self) -> None:
        """RF-017-04, B-4: rectas con vértices en ``k · d`` (no exactamente colineales: el redondeo los separa de la recta ~10⁻¹⁶) **con las coordenadas de la cantera** dan lo mismo
        que todos contra todos; con las coordenadas pequeñas (cerca del origen) las cuentas de siempre rechazan una recta por un cruce falso entre tramos que no se tocan (512 de 1.500
        rectas) y la búsqueda por cajas **no**: nunca rechaza lo que la otra acepta, y una recta con los vértices en orden no se rechaza nunca."""
        rng = np.random.default_rng(7)
        straight_utm, straight_origin, shuffled = [], [], []
        for _ in range(1500):
            count = int(rng.integers(4, 20))
            direction = rng.random(2) * 3.0
            k = rng.choice(60, size=count, replace=False).astype(np.float64)
            straight_origin.append(np.outer(np.sort(k), direction))
            straight_utm.append(np.outer(np.sort(k), direction) + OFFSET)
            shuffled.append(np.outer(k, direction) + (OFFSET if rng.random() < 0.5 else 0.0))
        self.compare(straight_utm)
        false_rejections = 0
        for line in straight_origin:
            found = road_store._first_crossing(line)
            self.assertIsNone(found, "una recta con los vértices en orden no se corta")
            false_rejections += reference_first_crossing(line) is not None
        self.assertGreater(false_rejections, 100, "con las coordenadas cerca del origen las cuentas de siempre rechazan rectas: la diferencia es real")
        for line in shuffled:
            if reference_first_crossing(line) is None:
                self.assertIsNone(road_store._first_crossing(line), line.tolist())

    def test_degenerate_lines(self) -> None:
        """RF-017-04: una línea de uno o dos vértices, con todos los vértices iguales, con un vértice sin dato (``NaN``: ninguna comparación suya da cierto, como siempre),
        con coordenadas enormes y el lazo cerrado de cuatro puntos dan lo mismo que todos contra todos."""
        square = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]])
        lines = [np.zeros((0, 2)), np.array([[0.0, 0.0]]), np.array([[0.0, 0.0], [1.0, 1.0]]), np.tile(OFFSET, (10, 1)), square + OFFSET,
                 np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [np.nan, np.nan], [2.0, 4.0], [2.0, 0.0]]) + OFFSET,
                 np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [2.0, 4.0], [2.0, 0.0], [np.nan, 1.0]]) + OFFSET,
                 square * 1e6 + 1e12, square * 1e-6]
        self.compare(lines)

    def test_a_very_long_segment_among_thousands_of_short_ones(self) -> None:
        """RF-017-04, B-4: un tramo de 6 km seguido de 3.000 vértices de una línea que ondula (la rejilla de la búsqueda no se llena por el tramo largo: sus celdas crecen), sin
        cruce y con el tramo largo cruzando la cola: el mismo resultado que todos contra todos."""
        t = np.linspace(0.0, 1.0, 3000)
        tail = np.column_stack([6000.0 + 300.0 * t, 100.0 * np.sin(t * 40.0)])
        free = np.vstack([[[0.0, 0.0]], tail]) + OFFSET
        crossing = np.vstack([[[6200.0, -200.0]], [[6200.0, 200.0]], tail[::-1]]) + OFFSET
        self.assertEqual(self.compare([free, crossing]), (1, 1))

    def test_a_crossing_between_segments_far_apart_in_the_line(self) -> None:
        """RF-017-04, B-4: en una línea de 5.000 vértices el último tramo que vuelve a cortar el 10.º: el cruce de los tramos 9 y 4.998 es el que da todos contra todos (0,6 s)."""
        line = digitised(5000)
        line[-1] = line[10] + np.array([0.0, 100.0])
        line[-2] = line[10] - np.array([0.0, 100.0])
        want = reference_first_crossing(line)
        self.assertIsNotNone(want)
        self.assertEqual(road_store._first_crossing(line), want)


class StepLimitTest(unittest.TestCase):
    """RNF-017-06: cada llamada, ≤ 0,2 s."""

    def test_dense_lines_without_crossings_are_checked_in_at_most_0_2_s(self) -> None:
        """RNF-017-06, RF-017-04, B-4: 5.000 vértices (con todos contra todos, 0,58 s), 20.000 (8,1 s) y 100.000 (≈ 200 s por n²) sin cruces, una recta de 20.000 y la ida y vuelta a 0,5 m
        (8.000 vértices: 1,4 s) se comprueban en ≤ 0,2 s **por llamada** (los plazos, de 1 a 40 ms en reposo: la mejor de las medidas)."""
        out = np.column_stack([np.linspace(0.0, 4000.0, 4000), np.zeros(4000)])
        back = np.column_stack([np.linspace(4000.0, 0.0, 4000), np.full(4000, 0.5)])
        straight = np.column_stack([np.linspace(0.0, 20000.0, 20000), np.linspace(0.0, 6000.0, 20000)]) + OFFSET
        for name, line in (("5.000", digitised(5000)), ("20.000", digitised(20000)), ("100.000", digitised(100000)), ("recta de 20.000", straight),
                           ("ida y vuelta", np.vstack([out, back]) + OFFSET)):
            with self.subTest(line=name):
                self.assertIsNone(road_store._first_crossing(line))
                self.assertLessEqual(best_of(lambda line=line: road_store._first_crossing(line), STEP_LIMIT_S, attempts=1, max_attempts=3), STEP_LIMIT_S)

    def test_a_line_that_crosses_at_the_start_is_rejected_without_looking_at_the_rest(self) -> None:
        """RNF-017-06, B-4: una línea de 20.000 vértices de tramos de 5 km (una pasada de ida y vuelta) que se corta en sus cuatro primeros vértices da el mismo punto que todos
        contra todos y no tarda más de 0,2 s (la búsqueda por lotes para en el primero con un cruce)."""
        n = 20001
        line = np.column_stack([np.where(np.arange(n) % 2 == 0, 0.0, 5000.0), np.arange(n) * 0.1 + (np.arange(n) % 2) * 0.3]) + OFFSET
        line[0:4] = np.array([[0.0, 0.0], [4.0, 4.0], [4.0, 0.0], [0.0, 4.0]]) + OFFSET
        self.assertEqual(road_store._first_crossing(line), reference_first_crossing(line))
        self.assertLessEqual(best_of(lambda: road_store._first_crossing(line), STEP_LIMIT_S, attempts=1, max_attempts=3), STEP_LIMIT_S)

    def test_reading_a_line_of_20000_vertices_is_in_at_most_0_2_s(self) -> None:
        """RNF-017-06, RF-017-04, B-4: ``_read_line`` entera (las comprobaciones de una parte, de longitud, de vértice repetido y de cruce) con 20.000 vértices tarda ≤ 0,2 s por
        llamada, y una línea de 20.000 que se corta al final se rechaza con ``des.road_line_self_intersects`` y el lugar."""
        line = digitised(20000)
        layer = SimpleNamespace(parts=[[(line,)]])
        asked = SimpleNamespace(name="Pista larga", layer="gis_fea_ejes", fields=SimpleNamespace(layer="gis_fea_ejes"))
        self.assertTrue(np.array_equal(road_store._read_line(layer, 0, "Eje largo", asked, "RDW-001"), line))
        self.assertLessEqual(best_of(lambda: road_store._read_line(layer, 0, "Eje largo", asked, "RDW-001"), STEP_LIMIT_S, attempts=1, max_attempts=3), STEP_LIMIT_S)
        looped = np.vstack([line, [line[5, 0], line[5, 1] + 300.0], [line[5, 0], line[5, 1] - 300.0]])
        with self.assertRaises(messages.DesignError) as caught:
            road_store._read_line(SimpleNamespace(parts=[[(looped,)]]), 0, "Eje largo", asked, "RDW-001")
        self.assertEqual(caught.exception.code, "des.road_line_self_intersects")
        started = time.perf_counter()
        with self.assertRaises(messages.DesignError):
            road_store._read_line(SimpleNamespace(parts=[[(looped,)]]), 0, "Eje largo", asked, "RDW-001")
        self.assertLessEqual(time.perf_counter() - started, STEP_LIMIT_S)


if __name__ == "__main__":
    unittest.main()
