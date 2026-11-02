# SPDX-License-Identifier: GPL-3.0-or-later
"""La envolvente *chamfer* 5×5 (spec 013, T06; HU-013-3; RF-013-11, RF-013-12, RF-013-13,
RF-013-15; CE-013-01, CE-013-02; plan 013 A2, A3, A4, D-21, D-33; ADR-0014).

``design.envelopes`` da ``E↑(p) = mín_q [s(q) + t·d(p, q)]`` (la descendente, ``E↓ = −E↑(−s)``) con
el *chamfer* 5×5 de pesos 1, √2 y √5 por la escala 0,98644 (nunca el 3×3), barrido por filas hasta
el punto fijo, y comprueba en cada ejecución el RF-013-15. Se compara con el oráculo independiente
(``tests/support/design_oracles.py``: Dijkstra sobre los 16 desplazamientos, donde entrar en una
celda cuesta con la pendiente de la celda de **llegada**, A2) a ≤ 10⁻⁹ m:

- **La pendiente por celda** (A2, RF-013-11, RF-013-13): una constante o el talud general de cada
  sector (el máximo impuesto o el del perfil), por la tangente y el factor de malla del perfil.
- **El *chamfer*** (RF-013-11, RF-013-12): igual al oráculo en rejillas pequeñas (también finas,
  de una fila o de una columna), con pendiente constante y por celdas, en las dos direcciones,
  con el paso y la pendiente; a mano, el cono de una semilla y el coste de entrar en una celda.
- **El punto fijo** (RF-013-15, CE-013-02): usar el resultado como semilla no cambia ninguna celda
  más de 10⁻⁹ m, las 16 relajaciones y las semillas se cumplen, y entre celdas vecinas no pasa de
  la pendiente efectiva; si no converge en las vueltas permitidas, o una comprobación falla, es un
  ``DesignError`` con la celda absoluta y la diferencia, y no se entrega nada.
- **Por pasos** (D-20): el último ``Progress`` lleva el resultado; cerrar el generador a mitad no
  deja nada; ninguna entrada se modifica.
- **Los sectores del proyecto** (RF-013-13; T05): la pendiente de cada sector sale de
  ``design.sectors.imposed_slopes`` (comprobada), no del valor en bruto del parámetro.
"""

from __future__ import annotations

import math
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender

envelopes = import_geoblender("design.envelopes")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
seeds_mod = import_geoblender("design.seeds")
sectors_mod = import_geoblender("design.sectors")
design_params = import_geoblender("design.params")
core_params = import_geoblender("core.params")
progress_mod = import_geoblender("core.project.model")

SCALE = 0.98644
TOLERANCE_M = 1e-9
SQRT2 = math.sqrt(2.0)
SQRT5 = math.sqrt(5.0)


def finish(steps: Any) -> tuple[list[Any], Any]:
    """Los ``Progress`` de unos pasos (menos el último) y el resultado del último."""
    found = list(steps)
    return found[:-1], found[-1].result


def solve(seed: np.ndarray, tan: Any, step: float = 1.0, direction: str = "up", **options: Any
          ) -> Any:
    """La envolvente *chamfer* de ``seed`` (rejilla de paso ``step``) con la pendiente ``tan``: una
    constante, un mapa por celdas o ya una ``SlopeField``."""
    slope = tan if isinstance(tan, envelopes.SlopeField) else envelopes.SlopeField(tan)
    geometry = dfx.grid_from(seed.shape[0], seed.shape[1], step)
    return finish(envelopes.chamfer_steps(seed, geometry, slope, direction, name="e1",
                                          **options))[1]


def single_seed(shape: tuple[int, int], row: int, col: int, z: float) -> np.ndarray:
    seed = np.full(shape, np.inf)
    seed[row, col] = z
    return seed


def random_seeds(rng: np.random.Generator, shape: tuple[int, int]) -> np.ndarray:
    seed = np.full(shape, np.inf)
    count = min(int(rng.integers(1, 7)), seed.size)
    seed.flat[rng.choice(seed.size, size=count, replace=False)] = rng.uniform(90.0, 130.0, count)
    return seed


def pair_slices(shape: tuple[int, int], d_row: int, d_col: int
                ) -> tuple[tuple[slice, slice], tuple[slice, slice]]:
    """Los trozos de una rejilla que son cada celda y su vecina desplazada ``(d_row, d_col)``
    (``d_row ≥ 0``), para medir la pendiente entre vecinas sin bucles."""
    rows, cols = shape
    first = (slice(0, rows - d_row), slice(max(0, -d_col), cols - max(0, d_col)))
    second = (slice(d_row, rows), slice(max(0, d_col), cols - max(0, -d_col)))
    return first, second


def column_bands(shape: tuple[int, int], width: int, values: tuple[float, ...]) -> np.ndarray:
    """Un mapa de pendientes en franjas de ``width`` columnas que alternan ``values``."""
    bands = (np.arange(shape[1]) // width) % len(values)
    return np.broadcast_to(np.asarray(values)[bands], shape).copy()


class SlopeFieldTest(unittest.TestCase):
    """A2 (RF-013-11, RF-013-13): la pendiente efectiva de cada celda."""

    def test_constant_slope_is_the_tangent_times_the_mesh_factor(self) -> None:
        """RF-013-11, RF-013-13: una constante en grados da ``tan(°)·factor de malla`` en toda la
        rejilla (un escalar); 0° es válida (envolvente plana) y el 90° o un número que no es de
        [0; 90) °, un error del programa (el rechazo para la persona es de RF-013-16)."""
        slope = envelopes.constant_slope(35.0, 0.8)
        self.assertTrue(slope.uniform)
        self.assertAlmostEqual(slope.tan, math.tan(math.radians(35.0)) * 0.8, delta=1e-15)
        self.assertAlmostEqual(slope.max_tan, slope.tan, delta=0.0)
        self.assertEqual(envelopes.constant_slope(0.0).tan, 0.0)
        self.assertAlmostEqual(envelopes.constant_slope(45.0).tan, 1.0, delta=1e-15)
        for bad in (-0.1, 90.0, 120.0, math.nan, math.inf):
            with self.subTest(degrees=bad), self.assertRaises(ValueError):
                envelopes.constant_slope(bad)
        for bad in (0.0, -0.5, 1.0001, math.nan):
            with self.subTest(mesh_factor=bad), self.assertRaises(ValueError):
                envelopes.constant_slope(35.0, bad)
        self.assertEqual(envelopes.constant_slope(35.0, 1.0).tan,
                         envelopes.constant_slope(35.0).tan)

    def test_sector_slope_paints_each_cell_with_its_sector_rule(self) -> None:
        """A2: la celda de un sector toma su talud (el impuesto, ``tan(β)``, o el del perfil,
        ``h/avance``) por el factor de malla de su perfil; la que no es de ningún sector (etiqueta
        0), la regla del perfil base. La rejilla es nueva y no toca las etiquetas."""
        labels = np.array([[0, 1, 1, 2, 2, 0]], dtype=np.int16)
        before = labels.copy()
        imposed = envelopes.SlopeRule.from_degrees(10.6, 0.5)
        profile = dfx.REST_5_35_6
        by_profile = envelopes.SlopeRule(profile.general_tan, profile.mesh_factor)
        base = envelopes.SlopeRule.from_degrees(35.0)
        slope = envelopes.sector_slope(labels, [imposed, by_profile], base)
        by_hand = np.array([[math.tan(math.radians(35.0)),
                             math.tan(math.radians(10.6)) * 0.5,
                             math.tan(math.radians(10.6)) * 0.5,
                             profile.general_tan, profile.general_tan,
                             math.tan(math.radians(35.0))]])
        self.assertFalse(slope.uniform)
        self.assertEqual(slope.tan.dtype, np.float64)
        self.assertEqual(slope.tan.shape, labels.shape)
        self.assertTrue(np.allclose(slope.tan, by_hand, rtol=0.0, atol=1e-15))
        self.assertAlmostEqual(slope.max_tan, math.tan(math.radians(35.0)), delta=1e-15)
        self.assertEqual(imposed.effective, math.tan(math.radians(10.6)) * 0.5)
        self.assertTrue(np.array_equal(labels, before))

    def test_a_missing_rule_or_a_stray_label_is_a_program_error(self) -> None:
        """Una celda con un sector sin regla, con una etiqueta que no es de ningún sector, con
        etiqueta negativa, o sin sector y sin regla base, es un error del programa (``ValueError``:
        quien llama lo resuelve antes, T07 y T14); una regla que no se usa no estorba."""
        rule = envelopes.SlopeRule.from_degrees(20.0)
        labels = np.array([[0, 1, 2]], dtype=np.int16)
        with self.assertRaises(ValueError):
            envelopes.sector_slope(labels, [rule, None], rule)
        with self.assertRaises(ValueError):
            envelopes.sector_slope(labels, [rule], rule)
        with self.assertRaises(ValueError):
            envelopes.sector_slope(np.array([[0, -1]], dtype=np.int16), [rule], rule)
        with self.assertRaises(ValueError):
            envelopes.sector_slope(labels, [rule, rule], None)
        ready = envelopes.sector_slope(np.array([[1, 2]], dtype=np.int16), [rule, rule], None)
        self.assertEqual(ready.tan.shape, (1, 2))
        unused = envelopes.sector_slope(np.array([[0, 1]], dtype=np.int16), [rule, None], rule)
        self.assertEqual(unused.tan.shape, (1, 2))

    def test_invalid_rules_and_fields_are_program_errors(self) -> None:
        """Una tangente negativa o no finita, o un factor de malla fuera de (0; 1], se rechazan al
        crear la regla o el campo."""
        for bad in (-0.1, math.nan, math.inf):
            with self.subTest(tan=bad):
                with self.assertRaises(ValueError):
                    envelopes.SlopeRule(bad)
                with self.assertRaises(ValueError):
                    envelopes.SlopeField(bad)
        for bad in (0.0, 1.5, math.nan):
            with self.subTest(mesh=bad), self.assertRaises(ValueError):
                envelopes.SlopeRule(0.5, bad)
        with self.assertRaises(ValueError):
            envelopes.SlopeField(np.array([[0.1, math.nan]]))
        with self.assertRaises(ValueError):
            envelopes.SlopeField(np.array([[0.1, -1.0]]))


class ChamferByHandTest(unittest.TestCase):
    """Cuentas hechas a mano (RF-013-11, RF-013-12; ADR-0014)."""

    def test_the_scale_is_the_one_of_adr_0014(self) -> None:
        """RF-013-12, ADR-0014: pesos 1, √2 y √5 por la escala 0,98644; solo hay esa."""
        self.assertEqual(envelopes.CHAMFER_SCALE, SCALE)
        self.assertEqual(envelopes.TOLERANCE_M, TOLERANCE_M)
        self.assertEqual(envelopes.MAX_ITERATIONS, 8)

    def test_cone_of_one_seed(self) -> None:
        """RF-013-11: con t = 1 y paso 1, el cono de una semilla a 100 m da ``f + escala·d`` con
        ``d`` la longitud del camino más corto por los 16 desplazamientos: 3, 3√2, √5, 1 + √5 y
        √2 + √5 en (0, 3), (3, 3), (1, 2), (3, 1) y (3, 2); en los cuatro cuadrantes."""
        found = solve(single_seed((9, 9), 4, 4, 100.0), 1.0).grid
        by_hand = {(0, 0): 0.0, (0, 1): 1.0, (0, 3): 3.0, (3, 3): 3 * SQRT2, (1, 2): SQRT5,
                   (2, 1): SQRT5, (3, 1): 1.0 + SQRT5, (3, 2): SQRT2 + SQRT5, (0, 4): 4.0}
        for (d_row, d_col), length in by_hand.items():
            for sign_row in (1, -1):
                for sign_col in (1, -1):
                    cell = (4 + sign_row * d_row, 4 + sign_col * d_col)
                    self.assertAlmostEqual(found[cell], 100.0 + SCALE * length, delta=1e-12,
                                           msg=str(cell))

    def test_slope_step_and_elevation_scale_the_cone(self) -> None:
        """RF-013-11: ``E = f + escala·t·h·d`` con la cota, la pendiente y el paso (2 m), en las dos
        direcciones (la descendente baja lo mismo)."""
        seed = single_seed((7, 7), 3, 3, 100.0)
        factor = 0.5 * 2.0 * SCALE
        up = solve(seed, 0.5, 2.0).grid
        down = solve(seed, 0.5, 2.0, "down").grid
        for found, sign in ((up, 1.0), (down, -1.0)):
            self.assertEqual(found[3, 3], 100.0)
            self.assertAlmostEqual(found[3, 6], 100.0 + sign * factor * 3.0, delta=1e-12)
            self.assertAlmostEqual(found[0, 0], 100.0 + sign * factor * 3.0 * SQRT2, delta=1e-12)
            self.assertAlmostEqual(found[5, 4], 100.0 + sign * factor * SQRT5, delta=1e-12)

    def test_the_cost_of_entering_a_cell_uses_its_own_slope(self) -> None:
        """A2: en una fila de 5 celdas el coste de entrar en una celda usa su pendiente (la de
        llegada, no la de salida): con la semilla en un extremo, ``E = f + escala·Σ t(llegada)·h``,
        y al revés en el otro."""
        tangents = np.array([[0.1, 1.0, 2.0, 3.0, 4.0]])
        left = solve(single_seed((1, 5), 0, 0, 10.0), tangents).grid
        self.assertTrue(np.allclose(left[0], [10.0, 10.0 + SCALE * 1.0, 10.0 + SCALE * 3.0,
                                              10.0 + SCALE * 6.0, 10.0 + SCALE * 10.0],
                                    rtol=0.0, atol=1e-12))
        right = solve(single_seed((1, 5), 0, 4, 10.0), tangents).grid
        self.assertTrue(np.allclose(right[0], [10.0 + SCALE * 6.1, 10.0 + SCALE * 6.0,
                                               10.0 + SCALE * 5.0, 10.0 + SCALE * 3.0, 10.0],
                                    rtol=0.0, atol=1e-12))

    def test_two_seeds_take_the_envelope_of_both(self) -> None:
        """Dos semillas de cotas distintas: la ascendente toma el mínimo de los dos conos y la
        descendente el máximo (a mano, en una fila de 9)."""
        seed = np.full((1, 9), np.inf)
        seed[0, 0] = 0.0
        seed[0, 8] = 3.0
        up = solve(seed, 1.0).grid[0]
        down = solve(seed, 1.0, direction="down").grid[0]
        cols = np.arange(9.0)
        self.assertTrue(np.allclose(up, np.minimum(SCALE * cols, 3.0 + SCALE * (8.0 - cols)),
                                    rtol=0.0, atol=1e-12))
        self.assertTrue(np.allclose(down, np.maximum(-SCALE * cols, 3.0 - SCALE * (8.0 - cols)),
                                    rtol=0.0, atol=1e-12))

    def test_zero_slope_is_a_flat_envelope(self) -> None:
        """RF-013-13: 0° (válido) da una envolvente plana: la cota de la semilla más baja
        (ascendente) o más alta (descendente) en toda la rejilla."""
        seed = single_seed((5, 6), 1, 1, 100.0)
        seed[4, 4] = 90.0
        self.assertTrue(np.array_equal(solve(seed, 0.0).grid, np.full((5, 6), 90.0)))
        self.assertTrue(np.array_equal(solve(seed, 0.0, direction="down").grid,
                                       np.full((5, 6), 100.0)))

    def test_down_is_the_negated_up_of_the_negated_seeds(self) -> None:
        """RF-013-11: ``E↓(s) = −E↑(−s)``, bit a bit, con pendiente por celdas."""
        rng = np.random.default_rng(3)
        seed = random_seeds(rng, (14, 17))
        tangents = column_bands(seed.shape, 5, (0.7, 0.19))
        down = solve(seed, tangents, 2.0, "down").grid
        negated = np.where(np.isfinite(seed), -seed, np.inf)
        up = solve(negated, tangents, 2.0, "up").grid
        self.assertTrue(np.array_equal(down, -up))

    def test_no_seeds_leave_everything_without_envelope(self) -> None:
        """Una celda sin cota finita (``+inf``, ``−inf`` o NaN) no es semilla; sin ninguna, nada
        tiene envolvente (``+inf`` ascendente, ``−inf`` descendente) y no hay nada que violar (el
        rechazo de unas semillas vacías es de RF-013-16, T07)."""
        seed = np.full((3, 4), np.inf)
        seed[0, 0] = np.nan
        seed[2, 2] = -np.inf
        up = solve(seed, 1.0)
        down = solve(seed, 1.0, direction="down")
        self.assertTrue(np.isposinf(up.grid).all())
        self.assertTrue(np.isneginf(down.grid).all())
        self.assertEqual((up.iterations, up.violation), (1, 0.0))


class ChamferOracleTest(unittest.TestCase):
    """RF-013-11, RF-013-12, RF-013-13: igual al oráculo (Dijkstra) a ≤ 10⁻⁹ m."""

    def test_constant_slope_equals_dijkstra(self) -> None:
        """Pendiente constante (también 0 y 3), pasos 0,5 a 2,5 y las dos direcciones, en 20
        rejillas aleatorias de hasta 30 × 30 con semillas sueltas de cotas distintas: la envolvente
        difiere del oráculo ≤ 10⁻⁹ m y con una pendiente constante bastan una o dos vueltas."""
        rng = np.random.default_rng(20_261_106)
        for index in range(20):
            shape = (int(rng.integers(3, 31)), int(rng.integers(3, 31)))
            seed = random_seeds(rng, shape)
            tangent = float(rng.choice([0.0, 0.2, 0.5, 0.7002075382097097, 1.5, 3.0]))
            step = float(rng.choice([0.5, 1.0, 2.0, 2.5]))
            direction = "up" if index % 2 == 0 else "down"
            expected = oracles.dijkstra(seed, tangent, step, direction=direction)
            found = solve(seed, tangent, step, direction)
            with self.subTest(case=index, shape=shape, direction=direction):
                self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)
                self.assertLessEqual(found.violation, TOLERANCE_M)
                self.assertLessEqual(found.iterations, 2)

    def test_a_grid_of_90_by_90(self) -> None:
        """El tamaño más grande del oráculo (plan §7.1): 90 × 90 celdas de 1,5 m, quince semillas y
        una pendiente de 35°, en las dos direcciones."""
        rng = np.random.default_rng(90)
        seed = np.full((90, 90), np.inf)
        seed.flat[rng.choice(seed.size, size=15, replace=False)] = rng.uniform(90.0, 130.0, 15)
        tangent = math.tan(math.radians(35.0))
        for direction in ("up", "down"):
            expected = oracles.dijkstra(seed, tangent, 1.5, direction=direction)
            found = solve(seed, tangent, 1.5, direction)
            self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)

    def test_thin_grids(self) -> None:
        """Rejillas de una celda, de una fila, de una columna y de 2 × 2: los cortes de los
        vecinos de cinco por cinco no fallan y dan lo del oráculo."""
        rng = np.random.default_rng(11)
        for shape in ((1, 1), (1, 7), (7, 1), (2, 2), (2, 9), (9, 2), (3, 3), (4, 1)):
            seed = random_seeds(rng, shape)
            tangents = rng.uniform(0.1, 1.5, size=shape)
            for direction in ("up", "down"):
                with self.subTest(shape=shape, direction=direction):
                    expected = oracles.dijkstra(seed, tangents, 1.0, direction=direction)
                    found = solve(seed, tangents, 1.0, direction)
                    self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)

    def test_per_cell_slope_equals_dijkstra(self) -> None:
        """A2, RF-013-13: con pendiente por celdas (franjas de sectores y bloques de 5 × 5 de tres
        pendientes) la envolvente es la del oráculo, que cobra la pendiente de la celda de llegada,
        a ≤ 10⁻⁹ m y converge en las vueltas permitidas; en 24 casos de las dos direcciones."""
        rng = np.random.default_rng(5)
        longest = 0
        for index in range(24):
            shape = (int(rng.integers(10, 31)), int(rng.integers(10, 31)))
            seed = random_seeds(rng, shape)
            if index % 2 == 0:
                tangents = column_bands(shape, 7, (0.7, 0.19))
            else:
                blocks = rng.choice([0.19, 0.7, 1.5], size=(shape[0] // 5 + 1, shape[1] // 5 + 1))
                tangents = blocks.repeat(5, 0).repeat(5, 1)[:shape[0], :shape[1]].copy()
            direction = "up" if index % 4 < 2 else "down"
            expected = oracles.dijkstra(seed, tangents, 2.0, direction=direction)
            found = solve(seed, tangents, 2.0, direction)
            longest = max(longest, found.iterations)
            with self.subTest(case=index, shape=shape, direction=direction):
                self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)
                self.assertLessEqual(found.violation, TOLERANCE_M)
        self.assertGreaterEqual(longest, 2)  # y la iteración hasta el punto fijo se ejerce

    def test_a_single_slope_map_is_the_constant_one(self) -> None:
        """Un mapa con el mismo valor en todas las celdas da lo mismo, a ≤ 10⁻⁹ m, que la
        constante (el camino uniforme y el de celdas no se separan)."""
        rng = np.random.default_rng(8)
        seed = random_seeds(rng, (16, 19))
        constant = solve(seed, 0.6, 1.5).grid
        mapped = solve(seed, np.full(seed.shape, 0.6), 1.5).grid
        self.assertLessEqual(float(np.abs(constant - mapped).max()), TOLERANCE_M)


class FixedPointTest(unittest.TestCase):
    """RF-013-15, CE-013-02: la envolvente converge y respeta las semillas."""

    def cases(self) -> Iterator[tuple[str, np.ndarray, Any, str]]:
        rng = np.random.default_rng(13)
        for direction in ("up", "down"):
            seed = random_seeds(rng, (20, 24))
            yield "constante", seed, 0.7, direction
            yield "franjas", seed, column_bands(seed.shape, 6, (0.7, 0.19, 1.2)), direction

    def test_using_the_result_as_a_seed_changes_nothing(self) -> None:
        """RF-013-15, CE-013-02: usar la envolvente como semilla en todas sus celdas no cambia
        ninguna más de 10⁻⁹ m (con el cálculo mismo y con el oráculo), las 16 relajaciones y las
        semillas se cumplen, y la violación que entrega es ≤ 10⁻⁹ m."""
        for label, seed, tangents, direction in self.cases():
            with self.subTest(slope=label, direction=direction):
                found = solve(seed, tangents, 2.0, direction)
                again = solve(found.grid, tangents, 2.0, direction)
                self.assertLessEqual(float(np.abs(again.grid - found.grid).max()), TOLERANCE_M)
                self.assertEqual(again.iterations, 1)
                by_oracle = oracles.dijkstra(found.grid, tangents, 2.0, direction=direction)
                self.assertLessEqual(float(np.abs(by_oracle - found.grid).max()), TOLERANCE_M)
                self.assertLessEqual(oracles.relaxation_violation(
                    found.grid, tangents, 2.0, direction=direction), TOLERANCE_M)
                self.assertEqual(oracles.seed_violation(found.grid, seed, direction=direction),
                                 0.0)
                self.assertLessEqual(found.violation, TOLERANCE_M)

    def test_a_seed_cell_never_ends_on_the_wrong_side(self) -> None:
        """RF-013-15: en cada semilla ``E↑ ≤ f`` (``E↓ ≥ f``), exactamente: una semilla más alta
        que el cono de otra más baja queda por debajo de la suya (ascendente) y una más baja que
        el cono de otra más alta, por encima (descendente)."""
        seed = np.full((1, 12), np.inf)
        seed[0, 0] = 100.0
        seed[0, 5] = 130.0  # el cono de la primera (100 + escala·5) pasa por debajo
        seed[0, 11] = 90.0  # y la tercera baja más aún
        up = solve(seed, 1.0).grid[0]
        self.assertLess(up[5], 130.0)
        for column in (0, 5, 11):
            self.assertLessEqual(up[column], seed[0, column])
        down = solve(seed, 1.0, direction="down").grid[0]
        for column in (0, 5, 11):
            self.assertGreaterEqual(down[column], seed[0, column])
        self.assertGreater(down[11], 90.0)

    def test_neighbour_slope_never_exceeds_the_effective_slope(self) -> None:
        """RF-013-15: entre celdas vecinas (los 8 vecinos 3 × 3) la pendiente, medida aparte, no
        pasa de la efectiva de las dos celdas: con el *chamfer* escalado queda por debajo de la
        tangente (``escala·t``), con pendiente constante y por franjas, en las dos direcciones."""
        step = 2.0
        for label, seed, tangents, direction in self.cases():
            found = solve(seed, tangents, step, direction).grid
            tan = np.broadcast_to(np.asarray(tangents, dtype=np.float64), found.shape)
            worst = -math.inf
            for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
                first, second = pair_slices(found.shape, d_row, d_col)
                slope = np.abs(found[second] - found[first]) / (math.hypot(d_row, d_col) * step)
                limit = np.maximum(tan[first], tan[second])
                worst = max(worst, float((slope - limit).max()))
            with self.subTest(slope=label, direction=direction):
                self.assertLessEqual(worst, 0.0)

    def test_the_check_names_the_absolute_cell_and_the_difference(self) -> None:
        """RF-013-15: si una celda sube 1 m sobre lo que permite su vecina, ``check_envelope`` lanza
        ``des.envelope_not_fixed_point`` con la celda (fila, columna y coordenadas absolutas del
        centro, en float64) y la diferencia (1 m); un resultado sano no lanza nada."""
        seed = single_seed((15, 15), 7, 7, 100.0)
        geometry = dfx.grid_from(15, 15, 1.0)
        slope = envelopes.SlopeField(0.8)
        good = solve(seed, 0.8).grid
        envelopes.check_envelope(good, seed, slope, geometry, "up", name="e1")
        bumped = good.copy()
        bumped[3, 9] += 1.0
        with self.assertRaises(messages.DesignError) as caught:
            envelopes.check_envelope(bumped, seed, slope, geometry, "up", name="e1")
        error = caught.exception
        self.assertEqual(error.code, "des.envelope_not_fixed_point")
        self.assertEqual((error.values["row"], error.values["col"]), (3, 9))
        self.assertEqual(error.values["x"], round(geometry.west + 9.5, 3))
        self.assertEqual(error.values["y"], round(geometry.north - 3.5, 3))
        self.assertAlmostEqual(error.value, 1.0, delta=1e-9)
        self.assertIn("e1", error.text)
        self.assertIn("fila 3", error.text)
        self.assertIn("columna 9", error.text)
        self.assertNotIn("{", error.text)
        english = messages.render(error.code, language="en", **error.values)
        self.assertIn("row 3", english)

    def test_the_check_names_a_seed_on_the_wrong_side(self) -> None:
        """RF-013-15: una semilla que queda 0,3 m por encima de su cota en la ascendente (por
        debajo en la descendente) lanza ``des.envelope_seed_above`` (``..._below``) con su celda
        absoluta y los 0,3 m; con una tolerancia nula."""
        seed = single_seed((15, 15), 7, 7, 100.0)
        geometry = dfx.grid_from(15, 15, 1.0)
        slope = envelopes.SlopeField(0.8)
        raised = solve(seed, 0.8).grid
        raised[7, 7] += 0.3
        with self.assertRaises(messages.DesignError) as above:
            envelopes.check_envelope(raised, seed, slope, geometry, "up", name="e1")
        self.assertEqual(above.exception.code, "des.envelope_seed_above")
        self.assertEqual((above.exception.values["row"], above.exception.values["col"]), (7, 7))
        self.assertAlmostEqual(above.exception.value, 0.3, delta=1e-9)
        self.assertEqual(above.exception.values["seed"], 100.0)
        lowered = solve(seed, 0.8, direction="down").grid
        lowered[7, 7] -= 0.3
        with self.assertRaises(messages.DesignError) as below:
            envelopes.check_envelope(lowered, seed, slope, geometry, "down", name="e1")
        self.assertEqual(below.exception.code, "des.envelope_seed_below")
        self.assertAlmostEqual(below.exception.value, 0.3, delta=1e-9)
        for code in ("des.envelope_seed_above", "des.envelope_seed_below"):
            self.assertNotIn("{", messages.render(code, row=1, col=2, x=3.0, y=4.0, value=0.3,
                                                  seed=5.0, envelope="e1"))

    def test_not_converging_in_the_allowed_rounds_is_an_error_and_delivers_nothing(self) -> None:
        """RF-013-15, A3: si tras las vueltas permitidas aún no es un punto fijo, ``DesignError``
        (``des.envelope_not_fixed_point``) con la celda más violada y la diferencia, sin el último
        ``Progress`` con el resultado: nada se entrega ni se registra. El mismo caso, con las
        vueltas que necesita, converge."""
        rng = np.random.default_rng(5)
        seed = random_seeds(rng, (24, 30))
        tangents = column_bands(seed.shape, 7, (0.7, 0.19))
        found = solve(seed, tangents, 2.0)
        self.assertGreaterEqual(found.iterations, 2)
        geometry = dfx.grid_from(24, 30, 2.0)
        slope = envelopes.SlopeField(tangents)
        seen: list[Any] = []
        with self.assertRaises(messages.DesignError) as caught:
            for item in envelopes.chamfer_steps(seed, geometry, slope, "up", name="e1",
                                                max_iterations=1):
                seen.append(item)
        self.assertEqual(caught.exception.code, "des.envelope_not_fixed_point")
        self.assertGreater(caught.exception.value, TOLERANCE_M)
        self.assertEqual(caught.exception.values["iterations"], 1)
        self.assertTrue(all(item.result is None for item in seen))
        enough = finish(envelopes.chamfer_steps(seed, geometry, slope, "up", name="e1",
                                                max_iterations=found.iterations))[1]
        self.assertEqual(enough.iterations, found.iterations)
        self.assertTrue(np.array_equal(enough.grid, found.grid))


class StepsTest(unittest.TestCase):
    """D-20: por pasos, sin tocar las entradas."""

    def test_progress_and_result(self) -> None:
        """Los ``Progress`` son de la fase «envelope» con sus textos en español y avance creciente;
        solo el último lleva el resultado, una ``Envelope`` con la rejilla (float64, nueva), las
        vueltas y la violación. Con un presupuesto casi nulo hay un paso por unidad (una fila, con
        ``cells_per_unit`` pequeño): más de cien."""
        rng = np.random.default_rng(2)
        seed = random_seeds(rng, (60, 70))
        geometry = dfx.grid_from(60, 70, 1.0)
        slope = envelopes.constant_slope(35.0)
        steps, result = finish(envelopes.chamfer_steps(seed, geometry, slope, "down", name="e1",
                                                       budget_s=1e-9, cells_per_unit=100))
        self.assertGreater(len(steps), 100)
        done = [item.done for item in steps]
        self.assertEqual(done, sorted(done))
        for item in steps:
            self.assertIsInstance(item, progress_mod.Progress)
            self.assertEqual(item.phase, "envelope")
            self.assertIsNone(item.result)
            self.assertLessEqual(item.done, item.total)
            self.assertTrue(item.message)
        self.assertIsInstance(result, envelopes.Envelope)
        self.assertEqual(result.grid.dtype, np.float64)
        self.assertEqual(result.grid.shape, seed.shape)
        self.assertFalse(np.shares_memory(result.grid, seed))
        self.assertGreaterEqual(result.iterations, 1)
        self.assertLessEqual(result.violation, TOLERANCE_M)
        same = solve(seed, envelopes.constant_slope(35.0), 1.0, "down")
        self.assertTrue(np.array_equal(same.grid, result.grid))  # el presupuesto no cambia nada

    def test_no_input_is_modified(self) -> None:
        """Principio 7, RF-013-01: las semillas, el mapa de pendientes, las etiquetas y la rejilla
        no se modifican (ni se marcan de solo lectura) y el resultado no comparte memoria."""
        rng = np.random.default_rng(4)
        seed = random_seeds(rng, (18, 21))
        tangents = column_bands(seed.shape, 4, (0.5, 0.25))
        labels = np.zeros(seed.shape, dtype=np.int16)
        before = (seed.copy(), tangents.copy(), labels.copy())
        slope = envelopes.sector_slope(labels, [], envelopes.SlopeRule(0.5))
        for field in (envelopes.SlopeField(tangents), slope):
            for direction in ("up", "down"):
                found = solve(seed, field, 1.0, direction)
                self.assertFalse(np.shares_memory(found.grid, seed))
                self.assertFalse(np.shares_memory(found.grid, tangents))
        self.assertTrue(np.array_equal(seed, before[0]))
        self.assertTrue(np.array_equal(tangents, before[1]))
        self.assertTrue(np.array_equal(labels, before[2]))
        self.assertTrue(seed.flags.writeable and tangents.flags.writeable)

    def test_float32_seeds_are_taken_as_float64(self) -> None:
        """Unas semillas en float32 dan una envolvente float64, la misma que con sus valores
        pasados a float64 (no se calcula a menor precisión)."""
        rng = np.random.default_rng(14)
        narrow = random_seeds(rng, (12, 15)).astype(np.float32)
        for direction in ("up", "down"):
            found = solve(narrow, 0.7, 1.0, direction)
            self.assertEqual(found.grid.dtype, np.float64)
            same = solve(narrow.astype(np.float64), 0.7, 1.0, direction)
            self.assertTrue(np.array_equal(found.grid, same.grid))

    def test_closing_midway_leaves_nothing(self) -> None:
        """Cerrar el generador a mitad (Esc, desactivar Geoblender) no da resultado ni falla ni
        deja nada: las entradas siguen como estaban."""
        rng = np.random.default_rng(6)
        seed = random_seeds(rng, (60, 70))
        before = seed.copy()
        steps = envelopes.chamfer_steps(seed, dfx.grid_from(60, 70, 1.0),
                                        envelopes.constant_slope(30.0), "up", budget_s=1e-9,
                                        cells_per_unit=100)
        first = next(steps)
        self.assertIsNone(first.result)
        steps.close()
        self.assertTrue(np.array_equal(seed, before))

    def test_bad_input_is_a_program_error(self) -> None:
        """Una rejilla de celdas no cuadradas (la del proyecto siempre es cuadrada, ADR-0014), una
        forma que no casa, una dirección desconocida o un máximo de vueltas menor que 1 son
        errores del programa (``ValueError``), al avanzar el generador."""
        seed = single_seed((6, 7), 2, 3, 100.0)
        slope = envelopes.constant_slope(30.0)
        wide = gis.Grid(0.0, 12.0, 2.0, 1.0, 7, 6)
        cases: list[tuple[Any, ...]] = [
            (seed, wide, slope, "up"),
            (seed, dfx.grid_from(6, 8, 1.0), slope, "up"),
            (seed, dfx.grid_from(6, 7, 1.0), envelopes.SlopeField(np.full((6, 8), 0.5)), "up"),
            (seed, dfx.grid_from(6, 7, 1.0), slope, "sideways"),
            (seed[0], dfx.grid_from(6, 7, 1.0), slope, "up"),
        ]
        for args in cases:
            with self.subTest(grid=getattr(args[1], "shape", None), direction=args[3]):
                with self.assertRaises(ValueError):
                    list(envelopes.chamfer_steps(*args))
        with self.assertRaises(ValueError):
            list(envelopes.chamfer_steps(seed, dfx.grid_from(6, 7, 1.0), slope, "up",
                                         max_iterations=0))


class RequestTest(unittest.TestCase):
    """``envelope_steps``: la envolvente de una petición sobre unas semillas (plan §5.3.1)."""

    def seed_set(self, seed: np.ndarray, step: float) -> Any:
        geometry = dfx.grid_from(seed.shape[0], seed.shape[1], step)
        labels = np.zeros(seed.shape, dtype=np.int16)
        domain = seeds_mod.domain_of(np.ones(seed.shape, dtype=bool), labels, (),
                                     geometry.cell_area)
        return seeds_mod.collect_seeds(seed, None, domain, geometry)

    def test_direction_and_name_come_from_the_request(self) -> None:
        """RF-013-11: la dirección sale de la petición y la rejilla y el paso, de las semillas
        (``SeedSet``): lo mismo que ``chamfer_steps``; el nombre de la petición sale en el error."""
        rng = np.random.default_rng(9)
        seed = random_seeds(rng, (20, 25))
        found = self.seed_set(seed, 2.0)
        source = model.SeedSource("fixed", elevation_m=100.0, zone=model.Zone("domain"))
        slope = envelopes.constant_slope(35.0, 0.9)
        for direction in ("up", "down"):
            request = model.EnvelopeRequest("e1", direction, source, slope_deg=35.0,
                                            mesh_factor=0.9)
            steps, result = finish(envelopes.envelope_steps(request, found, slope, budget_s=1e-9))
            self.assertTrue(steps)
            self.assertIsInstance(result, envelopes.Envelope)
            expected = solve(seed, slope, 2.0, direction)
            self.assertTrue(np.array_equal(result.grid, expected.grid))
        self.assertFalse(np.shares_memory(result.grid, found.grid))
        self.assertTrue(np.array_equal(found.grid, seed))


@contextmanager
def families_registered() -> Iterator[None]:
    core_params.register_families(design_params.FAMILIES)
    try:
        yield
    finally:
        core_params.unregister_families("des")


class ProjectSectorsTest(dfx.DesignProjectCase):
    """RF-013-13: la pendiente de cada sector sale de ``design.sectors`` (T05), sobre el proyecto
    del diseño: el sector 1 impone 10,6° en V01 y el 2 no impone ninguno (usa el perfil)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(families_registered())
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            store.create(conn, sectors_mod.slope_key("sector_1"), 10.6, kind="ADOPTADO",
                         reason="Talud impuesto por la propiedad (prueba)", version=cls.v1.code,
                         source="Escritura de la finca (prueba)", source_kind="document",
                         decided_by="Samuel (IMGA)")
        sectors = sectors_mod.design_sectors(cls.project, cls.v1.uid)
        cls.imposed = sectors_mod.imposed_slopes(sectors)
        masks = cls.masks_of_v1()
        steps = seeds_mod.work_domain_steps(cls.project, model.WorkDomain(), masks)
        cls.domain = list(steps)[-1].result

    @classmethod
    def masks_of_v1(cls) -> Any:
        return cls("test_the_slope_of_a_sector_comes_from_imposed_slopes").masks()

    def rules(self) -> tuple[list[Any], Any]:
        profile = dfx.REST_5_35_6
        by_profile = envelopes.SlopeRule(profile.general_tan, profile.mesh_factor)
        found = [envelopes.SlopeRule.from_degrees(self.imposed[ref.code])
                 if ref.code in self.imposed else by_profile for ref in self.domain.sectors]
        return found, by_profile

    def test_the_slope_of_a_sector_comes_from_imposed_slopes(self) -> None:
        """RF-013-09, RF-013-13: ``imposed_slopes`` da 10,6° solo para el sector 1; la rejilla de
        pendientes pinta ``tan(10,6°)`` en sus celdas y el talud general del perfil
        (``REST_5_35_6``) en las del sector 2 y en las que no son de ningún sector."""
        self.assertEqual(self.imposed, {"sector_1": 10.6})
        rules, base = self.rules()
        slope = envelopes.sector_slope(self.domain.labels, rules, base)
        labels = self.domain.labels
        self.assertEqual(slope.tan.shape, cfx.SITE_GRID.shape)
        self.assertTrue((slope.tan[labels == 1] == math.tan(math.radians(10.6))).all())
        self.assertTrue((slope.tan[labels == 2] == dfx.REST_5_35_6.general_tan).all())
        self.assertTrue((slope.tan[labels == 0] == dfx.REST_5_35_6.general_tan).all())
        self.assertEqual(int((labels == 1).sum()), 2_800)

    def test_the_envelope_across_the_sectors_equals_dijkstra(self) -> None:
        """A2, RF-013-13: con esa rejilla de pendientes, en una ventana de 40 × 48 celdas que cruza
        el sector 1, el hueco y el sector 2, con semillas sueltas, la envolvente iguala al oráculo
        (que cobra la pendiente de la celda de llegada) a ≤ 10⁻⁹ m en las dos direcciones."""
        rules, base = self.rules()
        slope = envelopes.sector_slope(self.domain.labels, rules, base)
        window = (slice(40, 80), slice(36, 84))
        tangents = slope.tan[window]
        self.assertEqual(len(np.unique(tangents)), 2)
        seed = np.full(tangents.shape, np.inf)
        rng = np.random.default_rng(12)
        seed.flat[rng.choice(seed.size, size=5, replace=False)] = rng.uniform(600.0, 640.0, 5)
        for direction in ("up", "down"):
            expected = oracles.dijkstra(seed, tangents, cfx.SITE_GRID.dx, direction=direction)
            found = solve(seed, tangents, cfx.SITE_GRID.dx, direction)
            self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)

    def test_the_envelope_of_the_whole_site_converges(self) -> None:
        """RF-013-15: la envolvente descendente de una cresta de semillas sobre toda la rejilla del
        proyecto (160 × 160 celdas de 2 m) con esas pendientes converge y es un punto fijo."""
        rules, base = self.rules()
        slope = envelopes.sector_slope(self.domain.labels, rules, base)
        seed = np.full(cfx.SITE_GRID.shape, np.inf)
        seed[10, 20:140:3] = 700.0
        found = finish(envelopes.chamfer_steps(seed, cfx.SITE_GRID, slope, "down", name="e1"))[1]
        self.assertLessEqual(found.violation, TOLERANCE_M)
        again = solve(found.grid, slope, 2.0, "down")
        self.assertLessEqual(float(np.abs(again.grid - found.grid).max()), TOLERANCE_M)


if __name__ == "__main__":
    unittest.main()
