# SPDX-License-Identifier: GPL-3.0-or-later
"""Los oráculos de las envolventes (spec 013, T01; plan 013 §7.1; CE-013-01, CE-013-02; ADR-0014).

Comprueba ``tests.support.design_oracles`` antes de que lo usen las pruebas del núcleo (que aún
no existe), con cuentas hechas a mano y entre sí:

- **La máscara del *chamfer* 5×5**: 16 desplazamientos (4 de eje, 4 diagonales y 8 de caballo), con
  los pesos 1, √2 y √5 (la longitud real del paso), simétrica y sin el (0, 0).
- **Dijkstra sobre los desplazamientos** (``E_up(p) = mín_q [s(q) + t·d_c(p, q)]``; la descendente,
  ``−E_up(−s)``): a mano, sin escala, un cono de una semilla da 3, 3√2, √5, 1 + √5 y √2 + √5 en los
  desplazamientos (0, 3), (3, 3), (1, 2), (3, 1) y (3, 2); con escala, ``f + escala·t·h·d``; el
  coste de entrar en una celda usa el ``t`` de la celda de llegada (A2); una celda sin cota finita
  no es semilla.
- **Fuerza bruta euclídea** (``mín_q [f_q + t·h·|p − q|]``): a mano, la distancia entre centros de
  celda con triángulos pitagóricos (3-4-5, 5-12-13), el mínimo entre dos semillas y el máximo en la
  descendente.
- **Entre sí** (plan §7.1: «los dos oráculos coinciden entre sí en rejillas pequeñas»): el Dijkstra
  con todos los desplazamientos, pesados con su longitud real, da la fuerza bruta a ≤ 10⁻⁹ m en
  rejillas pequeñas con semillas sueltas de cotas distintas y en las dos direcciones; el
  *chamfer* sin escala nunca queda por debajo de la euclídea y la pasa como mucho un 2,75 %; con
  la escala 0,98644 queda dentro de ±1,36 % (ADR-0014; RF-013-12: ≤ 1,4 %); y a lo largo de una
  pared alineada con la rejilla coincide con la euclídea sin escala y la escala solo la acorta ese
  1,356 %.
- **Comprobaciones del punto fijo** (A4, RF-013-15): la mayor violación de las 16 relajaciones y la
  de las semillas, que son 0 para el resultado del Dijkstra y miden lo que se desvía una celda.
- **El escalonado a mano** (T09, A8; RF-013-22, RF-013-23): ``hand_stairs`` da, con
  ``EXPL_10_60_6`` y ``REST_5_35_6``, las cotas hechas a mano de la cara y de la berma en corte y
  en relleno, los pisos también bajo el ancla, la difusión de los argumentos y NaN donde falta un
  dato.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import design_oracles as oracles

SQRT2 = math.sqrt(2.0)
SQRT5 = math.sqrt(5.0)
TOLERANCE_M = 1e-9
"""D-33: τ de las comparaciones de las envolventes (m)."""
UNSCALED_MAX_EXCESS = 0.0275
"""El *chamfer* 5×5 sin escala sobrestima la distancia como mucho 1,0274863 − 1 (medido en
121 × 121)."""
SCALED_MAX_ERROR = 0.0136
"""Con la escala 0,98644 el error de distancia es de −1,356 % a +1,3554 % (ADR-0014)."""


def _cone(size: int, row: int, col: int, z: float) -> np.ndarray:
    seed = np.full((size, size), np.inf)
    seed[row, col] = z
    return seed


class MaskTest(unittest.TestCase):
    """La máscara de 16 desplazamientos del *chamfer* 5×5."""

    def test_sixteen_displacements_with_the_real_length_as_weight(self) -> None:
        """16 desplazamientos: 4 de eje (1), 4 diagonales (√2) y 8 de caballo (√5), cada uno con
        su longitud real, simétricos y sin el (0, 0)."""
        found = oracles.CHAMFER5
        self.assertEqual(len(found), 16)
        self.assertEqual(len({(row, col) for row, col, _ in found}), 16)
        self.assertNotIn((0, 0), {(row, col) for row, col, _ in found})
        for row, col, weight in found:
            self.assertIn((-row, -col, weight), found)
            self.assertAlmostEqual(weight, math.hypot(row, col), delta=1e-15)
        weights = sorted(round(weight, 12) for _, _, weight in found)
        self.assertEqual(weights, sorted([1.0] * 4 + [round(SQRT2, 12)] * 4
                                         + [round(SQRT5, 12)] * 8))

    def test_euclidean_displacements(self) -> None:
        """Todos los desplazamientos hasta un radio, con su longitud real: (2r + 1)² − 1."""
        found = oracles.euclidean_displacements(3)
        self.assertEqual(len(found), 7 * 7 - 1)
        for row, col, weight in found:
            self.assertEqual(weight, math.hypot(row, col))
        self.assertEqual(oracles.CHAMFER_SCALE, 0.98644)


class DijkstraHandTest(unittest.TestCase):
    """Dijkstra sobre los desplazamientos, con cuentas hechas a mano."""

    def test_single_seed_without_scale(self) -> None:
        """Sin escala, t = 1 y paso 1: lo que cuesta llegar desde el centro, a mano."""
        seed = _cone(9, 4, 4, 0.0)
        found = oracles.dijkstra(seed, 1.0, 1.0, scale=1.0)
        by_hand = {(0, 0): 0.0, (0, 1): 1.0, (0, 3): 3.0, (3, 3): 3 * SQRT2, (1, 2): SQRT5,
                   (2, 1): SQRT5, (3, 1): 1.0 + SQRT5, (3, 2): SQRT2 + SQRT5, (0, 4): 4.0}
        for (drow, dcol), value in by_hand.items():
            for sign_row in (1, -1):
                for sign_col in (1, -1):
                    cell = (4 + sign_row * drow, 4 + sign_col * dcol)
                    self.assertAlmostEqual(found[cell], value, delta=1e-12, msg=str(cell))

    def test_scale_slope_height_and_step(self) -> None:
        """Con escala: f + escala·t·h·d, con la cota de la semilla, la pendiente y el paso."""
        seed = _cone(7, 3, 3, 100.0)
        found = oracles.dijkstra(seed, 0.5, 2.0)  # escala por defecto, la del ADR-0014
        factor = 0.5 * 2.0 * 0.98644
        self.assertEqual(found[3, 3], 100.0)
        self.assertAlmostEqual(found[3, 6], 100.0 + factor * 3.0, delta=1e-12)
        self.assertAlmostEqual(found[0, 0], 100.0 + factor * 3.0 * SQRT2, delta=1e-12)
        self.assertAlmostEqual(found[5, 4], 100.0 + factor * SQRT5, delta=1e-12)

    def test_down_is_the_negated_up(self) -> None:
        """La descendente es −E_up(−s): el cono hacia abajo, f − escala·t·h·d."""
        seed = _cone(7, 3, 3, 100.0)
        down = oracles.dijkstra(seed, 0.5, 2.0, direction="down")
        up = oracles.dijkstra(seed, 0.5, 2.0, direction="up")
        self.assertEqual(down[3, 3], 100.0)
        self.assertAlmostEqual(down[3, 6], 100.0 - (up[3, 6] - 100.0), delta=1e-12)
        negated = -oracles.dijkstra(-seed, 0.5, 2.0)
        self.assertTrue(np.array_equal(down, negated))

    def test_cost_of_entering_uses_the_arrival_cell_slope(self) -> None:
        """A2: el coste de entrar en una celda usa el t de la celda de llegada (no el de salida):
        en una fila de 5 celdas con semilla en la primera, E = f + Σ t(llegada)·h."""
        seed = np.full((1, 5), np.inf)
        seed[0, 0] = 10.0
        tangents = np.array([[0.1, 1.0, 2.0, 3.0, 4.0]])
        found = oracles.dijkstra(seed, tangents, 1.0, scale=1.0)
        self.assertTrue(np.allclose(found[0], [10.0, 11.0, 13.0, 16.0, 20.0], atol=1e-12))
        mirrored = np.full((1, 5), np.inf)
        mirrored[0, 4] = 10.0
        back = oracles.dijkstra(mirrored, tangents, 1.0, scale=1.0)
        self.assertTrue(np.allclose(back[0], [10.0 + 3.0 + 2.0 + 1.0 + 0.1, 10.0 + 3.0 + 2.0 + 1.0,
                                              10.0 + 3.0 + 2.0, 10.0 + 3.0, 10.0], atol=1e-12))

    def test_two_seeds_take_the_lower_value(self) -> None:
        """Dos semillas de cotas distintas: en cada celda, la menor de las dos."""
        seed = np.full((1, 9), np.inf)
        seed[0, 0] = 0.0
        seed[0, 8] = 3.0
        found = oracles.dijkstra(seed, 1.0, 1.0, scale=1.0)
        by_hand = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 4.0, 3.0]  # mín(c, 3 + 8 − c)
        self.assertTrue(np.allclose(found[0], by_hand, atol=1e-12), found[0])

    def test_non_finite_cells_are_not_seeds(self) -> None:
        """Una celda con +inf, −inf o NaN no es semilla; sin ninguna, todo queda sin envolvente."""
        seed = np.full((3, 3), np.inf)
        seed[0, 0] = np.nan
        seed[2, 2] = -np.inf
        self.assertTrue(np.isposinf(oracles.dijkstra(seed, 1.0, 1.0)).all())
        self.assertTrue(np.isneginf(oracles.dijkstra(seed, 1.0, 1.0, direction="down")).all())
        self.assertTrue(np.isposinf(oracles.brute_force_euclidean(seed, 1.0, 1.0)).all())

    def test_inputs_are_not_modified_and_bad_input_is_refused(self) -> None:
        """No toca la semilla ni las pendientes; una pendiente negativa o no finita, o una
        dirección desconocida, se rechazan."""
        seed = _cone(5, 2, 2, 5.0)
        tangents = np.full((5, 5), 0.5)
        before = (seed.copy(), tangents.copy())
        oracles.dijkstra(seed, tangents, 1.0)
        self.assertTrue(np.array_equal(seed, before[0]))
        self.assertTrue(np.array_equal(tangents, before[1]))
        for bad in (-0.1, np.nan, np.inf):
            with self.assertRaises(ValueError):
                oracles.dijkstra(seed, bad, 1.0)
        with self.assertRaises(ValueError):
            oracles.dijkstra(seed, 1.0, 1.0, direction="sideways")
        with self.assertRaises(ValueError):
            oracles.dijkstra(seed, 1.0, 0.0)


class BruteForceHandTest(unittest.TestCase):
    """La fuerza bruta euclídea, con triángulos pitagóricos."""

    def test_distance_between_cell_centres(self) -> None:
        """3-4-5 y 5-12-13 entre centros de celda, con paso 2 y t = 0,75: f + t·h·d."""
        seed = _cone(20, 2, 3, 50.0)
        found = oracles.brute_force_euclidean(seed, 0.75, 2.0)
        self.assertEqual(found[2, 3], 50.0)
        self.assertAlmostEqual(found[5, 7], 50.0 + 0.75 * 2.0 * 5.0, delta=1e-12)
        self.assertAlmostEqual(found[14, 8], 50.0 + 0.75 * 2.0 * 13.0, delta=1e-12)
        self.assertAlmostEqual(found[2, 15], 50.0 + 0.75 * 2.0 * 12.0, delta=1e-12)

    def test_min_of_two_seeds_up_and_max_down(self) -> None:
        """La ascendente toma el mínimo de los conos y la descendente, el máximo."""
        seed = np.full((1, 11), np.inf)
        seed[0, 0] = 10.0
        seed[0, 10] = 0.0
        up = oracles.brute_force_euclidean(seed, 1.0, 1.0)
        down = oracles.brute_force_euclidean(seed, 1.0, 1.0, direction="down")
        cone_left = 10.0 + np.arange(11.0)
        cone_right = 0.0 + np.arange(10.0, -1.0, -1.0)
        self.assertTrue(np.allclose(up, np.minimum(cone_left, cone_right), atol=1e-12))
        self.assertTrue(np.allclose(down, np.maximum(10.0 - np.arange(11.0),
                                                     -np.arange(10.0, -1.0, -1.0)), atol=1e-12))

    def test_slope_must_be_constant(self) -> None:
        """La euclídea exacta solo admite una pendiente constante (RF-013-16): un mapa que varía
        se rechaza; uno constante vale."""
        seed = _cone(4, 1, 1, 0.0)
        varied = np.full((4, 4), 0.5)
        varied[0, 0] = 0.6
        with self.assertRaises(ValueError):
            oracles.brute_force_euclidean(seed, varied, 1.0)
        same = oracles.brute_force_euclidean(seed, np.full((4, 4), 0.5), 1.0)
        self.assertTrue(np.array_equal(same, oracles.brute_force_euclidean(seed, 0.5, 1.0)))


class AgreementTest(unittest.TestCase):
    """Los dos oráculos entre sí, en rejillas pequeñas (plan §7.1)."""

    @staticmethod
    def _random_seeds(rng: np.random.Generator, shape: tuple[int, int]) -> np.ndarray:
        seed = np.full(shape, np.inf)
        count = int(rng.integers(1, 7))
        cells = rng.choice(shape[0] * shape[1], size=count, replace=False)
        seed.flat[cells] = rng.uniform(90.0, 130.0, size=count)
        return seed

    def test_dijkstra_with_every_displacement_is_the_brute_force(self) -> None:
        """Con todos los desplazamientos pesados con su longitud real, el camino más corto es el
        segmento recto: Dijkstra y fuerza bruta coinciden a ≤ 10⁻⁹ m, en 16 casos de rejillas de
        hasta 9 × 8, semillas sueltas de cotas distintas, pendientes y pasos variados y las dos
        direcciones."""
        rng = np.random.default_rng(20_261_102)
        for index in range(16):
            shape = (int(rng.integers(3, 10)), int(rng.integers(3, 9)))
            seed = self._random_seeds(rng, shape)
            tangent = float(rng.choice([0.2, 0.5, 0.7002075382097097, 1.5]))
            step = float(rng.choice([1.0, 2.0, 2.5]))
            direction = "up" if index % 2 == 0 else "down"
            everything = oracles.euclidean_displacements(max(shape))
            slow = oracles.dijkstra(seed, tangent, step, displacements=everything, scale=1.0,
                                    direction=direction)
            exact = oracles.brute_force_euclidean(seed, tangent, step, direction=direction)
            self.assertLessEqual(float(np.abs(slow - exact).max()), TOLERANCE_M,
                                 f"caso {index} {shape} {direction}")

    def test_unscaled_chamfer_never_undershoots_the_euclidean(self) -> None:
        """El *chamfer* 5×5 sin escala es la longitud de un camino real: nunca baja de la
        euclídea y la sobrestima como mucho un 2,75 % de la distancia (cono de una semilla)."""
        seed = _cone(61, 30, 30, 100.0)
        cham = oracles.dijkstra(seed, 1.0, 1.0, scale=1.0) - 100.0
        euclid = oracles.brute_force_euclidean(seed, 1.0, 1.0) - 100.0
        self.assertGreaterEqual(float((cham - euclid).min()), -TOLERANCE_M)
        far = euclid > 0.0
        excess = (cham[far] - euclid[far]) / euclid[far]
        self.assertLessEqual(float(excess.max()), UNSCALED_MAX_EXCESS)
        self.assertGreater(float(excess.max()), 0.02)  # y la cota se alcanza: no es trivial

    def test_scaled_chamfer_is_within_the_adr_error(self) -> None:
        """Con la escala 0,98644: de −1,356 % a +1,355 % de la distancia (ADR-0014; RF-013-12:
        ≤ 1,4 %) en el cono de una semilla, en las dos direcciones."""
        seed = _cone(61, 30, 30, 100.0)
        for direction, sign in (("up", 1.0), ("down", -1.0)):
            cham = sign * (oracles.dijkstra(seed, 0.7, 1.0, direction=direction) - 100.0)
            euclid = sign * (oracles.brute_force_euclidean(seed, 0.7, 1.0, direction=direction)
                             - 100.0)
            far = euclid > 0.0
            error = (cham[far] - euclid[far]) / euclid[far]
            self.assertLessEqual(float(np.abs(error).max()), SCALED_MAX_ERROR)
            self.assertAlmostEqual(float(error.min()), -0.01356, delta=1e-5)

    def test_wall_aligned_with_the_grid(self) -> None:
        """Una pared de semillas en una columna: sin escala el *chamfer* da la cota exacta de la
        euclídea (≤ 10⁻⁹ m); con la escala 0,98644 la distancia a lo largo del eje queda un 1,356 %
        más corta (n·h·escala): la pared solo es exacta con la escala 1."""
        seed = np.full((21, 21), np.inf)
        seed[:, 10] = 250.0
        exact = oracles.brute_force_euclidean(seed, 0.5, 2.0)
        unscaled = oracles.dijkstra(seed, 0.5, 2.0, scale=1.0)
        scaled = oracles.dijkstra(seed, 0.5, 2.0)
        self.assertLessEqual(float(np.abs(unscaled - exact).max()), TOLERANCE_M)
        self.assertAlmostEqual(exact[7, 15], 250.0 + 0.5 * 2.0 * 5.0, delta=1e-12)
        self.assertAlmostEqual(scaled[7, 15], 250.0 + 0.5 * 2.0 * 5.0 * 0.98644, delta=1e-12)
        self.assertAlmostEqual(float(((exact - 250.0) - (scaled - 250.0))[:, 15].max()),
                               0.5 * 2.0 * 5.0 * (1.0 - 0.98644), delta=1e-12)


class FixedPointTest(unittest.TestCase):
    """Las comprobaciones de A4 (RF-013-15): relajaciones y semillas."""

    def test_dijkstra_result_is_a_fixed_point(self) -> None:
        """El resultado del Dijkstra no viola ninguna de las 16 relajaciones (≤ 10⁻⁹ m) ni sus
        semillas, con pendientes por celda, en las dos direcciones; usarlo como semilla no lo
        cambia."""
        rng = np.random.default_rng(7)
        seed = np.full((12, 15), np.inf)
        cells = rng.choice(seed.size, size=5, replace=False)
        seed.flat[cells] = rng.uniform(50.0, 80.0, size=5)
        tangents = rng.uniform(0.2, 1.2, size=seed.shape)
        for direction in ("up", "down"):
            found = oracles.dijkstra(seed, tangents, 2.0, direction=direction)
            self.assertLessEqual(oracles.relaxation_violation(
                found, tangents, 2.0, direction=direction), TOLERANCE_M)
            self.assertLessEqual(oracles.seed_violation(found, seed, direction=direction), 0.0)
            again = oracles.dijkstra(found, tangents, 2.0, direction=direction)
            self.assertLessEqual(float(np.abs(again - found).max()), TOLERANCE_M)

    def test_violations_measure_the_deviation(self) -> None:
        """Subir 1 m una celda del cono (o bajarla 1 m) viola una relajación en exactamente 1 m;
        subir 0,3 m la cota de la semilla viola la semilla en 0,3 m (E_up debe quedar ≤ f)."""
        seed = _cone(15, 7, 7, 100.0)
        found = oracles.dijkstra(seed, 0.8, 1.0)
        bumped = found.copy()
        bumped[3, 9] += 1.0
        self.assertAlmostEqual(oracles.relaxation_violation(bumped, 0.8, 1.0), 1.0, delta=1e-12)
        dipped = found.copy()
        dipped[3, 9] -= 1.0
        self.assertAlmostEqual(oracles.relaxation_violation(dipped, 0.8, 1.0), 1.0, delta=1e-12)
        raised = found.copy()
        raised[7, 7] += 0.3
        self.assertAlmostEqual(oracles.seed_violation(raised, seed), 0.3, delta=1e-12)
        lowered = oracles.dijkstra(seed, 0.8, 1.0, direction="down")
        lowered[7, 7] -= 0.3  # la descendente debe quedar ≥ f
        self.assertAlmostEqual(oracles.seed_violation(lowered, seed, direction="down"), 0.3,
                               delta=1e-12)


class HandStairsTest(unittest.TestCase):
    """El oráculo del escalonado (T09, A8): el piso ``n`` y la fracción ``f`` exactos."""

    def test_expl_10_60_6_by_hand(self) -> None:
        """RF-013-22, RF-013-23: ``h`` 10 m, cara de 60° (``tan`` = √3), berma de 6 m, ancla 125 m:
        ``a·tan α`` = 10 + 6√3 = 20,3923; la cota 145 es un piso (berma) en las dos; 146 m (n = 2,
        f = 0,1) queda en la cara en corte (145 + 0,1·20,3923 = 147,0392) y en la berma en relleno
        (145); 140,125 (n = 1, f = 0,5125) está en la berma del banco de arriba en corte (145) y en
        la cara en relleno (135 + 0,5125·20,3923 − 6√3 = 135,0588); a 154,999 el relleno queda
        6√3·0,0001 m por debajo."""
        found = {}
        for fill in (False, True):
            found[fill] = oracles.hand_stairs([145.0, 146.0, 140.125, 154.999], 10.0,
                                              math.sqrt(3.0), 6.0, 125.0, fill=fill)
        np.testing.assert_allclose(found[False], [145.0, 147.03923048454132, 145.0, 155.0],
                                   rtol=0.0, atol=1e-9)
        np.testing.assert_allclose(found[True], [145.0, 145.0, 135.05875138786104,
                                                 154.99796076951546], rtol=0.0, atol=1e-9)

    def test_floors_below_the_anchor(self) -> None:
        """RF-013-24: bajo el ancla el piso es negativo: 100 m (u = −2,5, n = −3, f = 0,5) queda
        en la berma de 105 m en corte; 95 m (u = −3 exacto) es un piso."""
        found = oracles.hand_stairs([100.0, 95.0], 10.0, math.sqrt(3.0), 6.0, 125.0)
        np.testing.assert_allclose(found, [105.0, 95.0], rtol=0.0, atol=1e-9)

    def test_rest_5_35_6_by_hand(self) -> None:
        """RF-013-22, RF-013-23: ``h`` 5 m, cara de 35°, berma de 6 m, ancla 125 m: a 140,125 m
        (n = 3, f = 0,025) el corte sube 0,025·(5 + 6 tan 35°) = 0,2300 sobre 140 m y el relleno se
        queda en la berma, 140; a 142,4 m (f = 0,48) el corte da 144,4166 y el relleno 140,2154."""
        tan = math.tan(math.radians(35.0))
        cut = oracles.hand_stairs([140.125, 142.4], 5.0, tan, 6.0, 125.0)
        fill = oracles.hand_stairs([140.125, 142.4], 5.0, tan, 6.0, 125.0, fill=True)
        np.testing.assert_allclose(cut, [140.23003113073145, 144.41659771004396], rtol=0.0,
                                   atol=1e-9)
        np.testing.assert_allclose(fill, [140.0, 140.2153524807857], rtol=0.0, atol=1e-9)

    def test_broadcast_and_non_finite(self) -> None:
        """Los argumentos se difunden; con algún dato no finito, la celda sale NaN; ninguna entrada
        se modifica."""
        surface = np.array([[130.0, np.nan], [np.inf, 131.0]])
        before = surface.copy()
        found = oracles.hand_stairs(surface, [[10.0], [5.0]], 1.0, 0.0, 125.0)
        self.assertEqual(found.shape, (2, 2))
        self.assertTrue(np.isnan(found[0, 1]) and np.isnan(found[1, 0]))
        self.assertFalse(np.isnan(found[0, 0]) or np.isnan(found[1, 1]))
        np.testing.assert_array_equal(surface, before)


if __name__ == "__main__":
    unittest.main()
