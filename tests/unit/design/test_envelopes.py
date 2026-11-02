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


def solve_exact(seed: np.ndarray, tan: Any, step: float = 1.0, direction: str = "up",
                **options: Any) -> Any:
    """La envolvente euclídea exacta de ``seed`` (rejilla de paso ``step``) con la pendiente ``tan``
    (una constante o ya una ``SlopeField``)."""
    slope = tan if isinstance(tan, envelopes.SlopeField) else envelopes.SlopeField(tan)
    geometry = dfx.grid_from(seed.shape[0], seed.shape[1], step)
    return finish(envelopes.exact_steps(seed, geometry, slope, direction, name="e1", **options))[1]


def seed_set_of(seed: np.ndarray, step: float, inside: np.ndarray | None = None) -> Any:
    """El ``SeedSet`` de una rejilla de semillas de paso ``step`` con el dominio de trabajo
    ``inside`` (toda la rejilla por defecto), sin proyecto."""
    geometry = dfx.grid_from(seed.shape[0], seed.shape[1], step)
    labels = np.zeros(seed.shape, dtype=np.int16)
    mask = np.ones(seed.shape, dtype=bool) if inside is None else inside
    domain = seeds_mod.domain_of(mask, labels, (), geometry.cell_area)
    return seeds_mod.collect_seeds(seed, None, domain, geometry)


def request_of(**changes: Any) -> Any:
    """Una petición de envolvente descendente de 35° con semillas a 100 m, con los campos que se
    cambien."""
    fields: dict[str, Any] = {
        "name": "e1", "direction": "down",
        "seeds": model.SeedSource("fixed", elevation_m=100.0, zone=model.Zone("domain")),
        "slope_deg": 35.0}
    return model.EnvelopeRequest(**{**fields, **changes})


def safe_reach(distance: np.ndarray, target: float) -> float:
    """Un alcance cercano a ``target`` que no cae sobre la distancia de ninguna celda (a más de
    10⁻⁶ m de todas): el punto medio del mayor hueco entre las distancias vecinas de ``target``."""
    values = np.unique(distance[(distance > target - 1.0) & (distance < target + 1.0)])
    gaps = np.diff(values)
    pick = int(np.argmax(gaps))
    assert gaps[pick] > 1e-6, "ninguna separación utilizable"
    return float((values[pick] + values[pick + 1]) / 2.0)


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

    def test_units_are_the_same_work_as_the_steps(self) -> None:
        """T10: ``chamfer_units`` es el trabajo de ``chamfer_steps`` sin ritmo (quien compone el
        barrido con otros cálculos, como la regularización y el recorte final, lo marca él): cada
        ``yield`` es una unidad, el valor del generador es la misma ``Envelope`` y las entradas que
        no casan se rechazan al llamar, no al avanzar."""
        rng = np.random.default_rng(8)
        seed = random_seeds(rng, (30, 33))
        geometry = dfx.grid_from(30, 33, 1.0)
        slope = envelopes.constant_slope(35.0)
        units = envelopes.chamfer_units(seed, geometry, slope, "down", name="e1",
                                        cells_per_unit=100)
        count = 0
        while True:
            try:
                next(units)
            except StopIteration as stop:
                found = stop.value
                break
            count += 1
        self.assertGreater(count, 10)
        same = solve(seed, slope, 1.0, "down")
        self.assertIsInstance(found, envelopes.Envelope)
        self.assertTrue(np.array_equal(found.grid, same.grid))
        wide = gis.Grid(0.0, 30.0, 2.0, 1.0, 33, 30)
        with self.assertRaises(ValueError):
            envelopes.chamfer_units(seed, wide, slope, "down")
        with self.assertRaises(ValueError):
            envelopes.chamfer_units(seed, geometry, slope, "down", max_iterations=0)

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
        return seed_set_of(seed, step)

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


class AscendingTest(unittest.TestCase):
    """RF-013-11: la envolvente ascendente (relleno), ``E↑(p) = mín_q [s(q) + t·d(p, q)]``."""

    def test_a_row_of_toe_seeds_rises_by_the_slope_row_by_row(self) -> None:
        """RF-013-11 (R-39): el pie de un relleno —la fila sur de una rejilla de 10 × 12 celdas de
        2 m, a 100 m— sube con la pendiente de 18° por 0,8 de factor de malla: a mano,
        ``E↑ = 100 + escala·tan(18°)·0,8·2·(filas desde el pie)`` en todas sus columnas; la
        petición ascendente da lo mismo que ``chamfer_steps``."""
        seed = np.full((10, 12), np.inf)
        seed[9, :] = 100.0
        request = request_of(direction="up", slope_deg=18.0, mesh_factor=0.8)
        slope = envelopes.constant_slope(18.0, 0.8)
        found = finish(envelopes.envelope_steps(request, seed_set_of(seed, 2.0), slope))[1]
        rise = SCALE * math.tan(math.radians(18.0)) * 0.8 * 2.0
        by_hand = 100.0 + rise * (9 - np.arange(10.0))[:, None] * np.ones((1, 12))
        self.assertLessEqual(float(np.abs(found.grid - by_hand).max()), TOLERANCE_M)
        self.assertTrue(np.array_equal(found.grid, solve(seed, slope, 2.0, "up").grid))
        self.assertTrue((found.grid[9] == 100.0).all())

    def test_it_never_passes_a_seed_nor_falls_below_the_lowest_one(self) -> None:
        """RF-013-11, RF-013-15: la ascendente queda en cada semilla a su cota o por debajo (la
        descendente, o por encima) y nunca baja de la cota más baja (sube de la más alta, la
        descendente): una envolvente de relleno no pasa de sus semillas y no hunde nada."""
        rng = np.random.default_rng(21)
        for _ in range(10):
            seed = random_seeds(rng, (16, 19))
            cells = np.isfinite(seed)
            up = solve(seed, 0.6, 1.0, "up").grid
            down = solve(seed, 0.6, 1.0, "down").grid
            self.assertTrue((up[cells] <= seed[cells]).all())
            self.assertTrue((down[cells] >= seed[cells]).all())
            self.assertGreaterEqual(float(up.min()), float(seed[cells].min()))
            self.assertLessEqual(float(down.max()), float(seed[cells].max()))

    def test_the_request_enumerates_the_direction(self) -> None:
        """RF-013-11: la dirección de la petición puede ser el enumerado o su texto, y la
        ascendente y la descendente de las mismas semillas son distintas."""
        rng = np.random.default_rng(5)
        seed = random_seeds(rng, (12, 14))
        found = seed_set_of(seed, 1.0)
        slope = envelopes.constant_slope(40.0)
        grids = {}
        for way in (model.Direction.UP, "up", model.Direction.DOWN, "down"):
            request = request_of(direction=way, slope_deg=40.0)
            grids[str(way)] = finish(envelopes.envelope_steps(request, found, slope))[1].grid
        self.assertTrue(np.array_equal(grids["up"], grids[str(model.Direction.UP)]))
        self.assertTrue(np.array_equal(grids["down"], grids[str(model.Direction.DOWN)]))
        self.assertFalse(np.array_equal(grids["up"], grids["down"]))


class ReachTest(unittest.TestCase):
    """RF-013-14 (A6): el alcance máximo, la distancia a la semilla más próxima con la misma
    métrica y ``t = 1``, y ``NaN`` más allá; sin alcance, ninguno."""

    def envelope(self, seed: np.ndarray, step: float, reach: float | None, direction: str = "up",
                 degrees: float = 30.0, **changes: Any) -> Any:
        request = request_of(direction=direction, slope_deg=degrees, reach_m=reach, **changes)
        slope = envelopes.constant_slope(degrees, request.mesh_factor)
        return finish(envelopes.envelope_steps(request, seed_set_of(seed, step), slope))[1]

    def distance_to(self, seed: np.ndarray, step: float) -> np.ndarray:
        """La distancia *chamfer* (m) a la semilla más próxima, por el oráculo (``t = 1``)."""
        origin = np.where(np.isfinite(seed), 0.0, np.inf)
        return oracles.dijkstra(origin, 1.0, step)

    def test_a_row_by_hand(self) -> None:
        """RF-013-14: en una fila de 12 celdas de 1 m con la semilla en el extremo, la distancia
        *chamfer* es ``0,98644·n``: con 4 m de alcance quedan las celdas 0 a 4 (3,9458 m la
        última), con 3,9 m, de 0 a 3, y con 0,5 m solo la semilla; el resto, ``NaN``. La
        envolvente de las que quedan es ``100 + 0,5·0,98644·n``."""
        seed = single_seed((1, 12), 0, 0, 100.0)
        degrees = math.degrees(math.atan(0.5))
        for reach, last in ((4.0, 4), (3.9, 3), (0.5, 0)):
            with self.subTest(reach=reach):
                row = self.envelope(seed, 1.0, reach, degrees=degrees).grid[0]
                self.assertEqual(int(np.isfinite(row).sum()), last + 1)
                self.assertTrue(np.isfinite(row[:last + 1]).all())
                self.assertTrue(np.isnan(row[last + 1:]).all())
                by_hand = 100.0 + 0.5 * SCALE * np.arange(last + 1.0)
                self.assertLessEqual(float(np.abs(row[:last + 1] - by_hand).max()), 1e-12)
        wide = self.envelope(seed, 2.0, 8.0, degrees=degrees).grid[0]  # el paso 2 m: 1,97288·n
        self.assertEqual(int(np.isfinite(wide).sum()), 5)

    def test_the_mask_is_the_chamfer_distance_to_the_nearest_seed(self) -> None:
        """RF-013-14, A6: las celdas con envolvente son las que están a ``distancia ≤ alcance`` de
        la semilla más próxima, con la distancia del oráculo (Dijkstra sobre los 16
        desplazamientos con ``t = 1``); en ellas la envolvente es la de siempre, bit a bit; en las
        demás, ``NaN``; en las dos direcciones, con pasos de 1,5 y 2 m."""
        rng = np.random.default_rng(31)
        for step in (1.5, 2.0):
            seed = random_seeds(rng, (30, 40))
            distance = self.distance_to(seed, step)
            for target in (4.0, 9.0, 15.0):
                reach = safe_reach(distance, target * step / 1.5)
                for direction in ("up", "down"):
                    with self.subTest(step=step, reach=round(reach, 3), direction=direction):
                        found = self.envelope(seed, step, reach, direction)
                        plain = self.envelope(seed, step, None, direction)
                        inside = distance <= reach
                        self.assertTrue(0 < int(inside.sum()) < inside.size)
                        self.assertTrue(np.array_equal(np.isfinite(found.grid), inside))
                        self.assertTrue(np.array_equal(np.isnan(found.grid), ~inside))
                        self.assertTrue(np.array_equal(found.grid[inside], plain.grid[inside]))
                        self.assertEqual((found.iterations, found.violation),
                                         (plain.iterations, plain.violation))

    def test_reach_steps_gives_the_distance_with_nan_beyond(self) -> None:
        """RF-013-14, A6: ``reach_steps`` entrega la distancia (m, float64, array nuevo) a la
        semilla más próxima donde no pasa del alcance —igual al oráculo a ≤ 10⁻⁹ m— y ``NaN``
        donde pasa; las celdas de semilla, a 0. Es de la fase «reach», con su resultado en el último
        paso."""
        rng = np.random.default_rng(32)
        seed = random_seeds(rng, (25, 30))
        before = seed.copy()
        distance = self.distance_to(seed, 2.0)
        reach = safe_reach(distance, 12.0)
        geometry = dfx.grid_from(25, 30, 2.0)
        steps, found = finish(envelopes.reach_steps(seed, geometry, reach, name="e1",
                                                    budget_s=1e-9))
        self.assertTrue(steps)
        for item in steps:
            self.assertEqual(item.phase, "reach")
            self.assertIsNone(item.result)
        self.assertEqual(found.dtype, np.float64)
        self.assertEqual(found.shape, seed.shape)
        self.assertFalse(np.shares_memory(found, seed))
        inside = distance <= reach
        self.assertTrue(np.array_equal(np.isfinite(found), inside))
        self.assertLessEqual(float(np.abs(found[inside] - distance[inside]).max()), TOLERANCE_M)
        self.assertTrue((found[np.isfinite(seed)] == 0.0).all())
        self.assertTrue(np.array_equal(seed, before))

    def test_without_a_reach_nothing_is_cut(self) -> None:
        """RF-013-14: sin alcance (``None``) toda la rejilla tiene envolvente (ninguna celda
        ``NaN``) y es la misma que el *chamfer* sin más; con un alcance mayor que la rejilla,
        también."""
        rng = np.random.default_rng(33)
        seed = random_seeds(rng, (20, 24))
        plain = solve(seed, envelopes.constant_slope(30.0), 1.0, "down")
        for reach in (None, 1_000.0):
            found = self.envelope(seed, 1.0, reach, "down")
            self.assertTrue(np.isfinite(found.grid).all())
            self.assertTrue(np.array_equal(found.grid, plain.grid))

    def test_the_reach_does_not_depend_on_the_slope_the_direction_or_the_mesh_factor(self) -> None:
        """RF-013-14: el alcance se mide con ``t = 1`` (distancia pura): la misma máscara con
        cualquier pendiente (5° a 80°), factor de malla y dirección, y con una pendiente por
        sectores."""
        rng = np.random.default_rng(34)
        seed = random_seeds(rng, (22, 26))
        reach = safe_reach(self.distance_to(seed, 1.0), 6.0)
        masks = []
        for degrees, mesh, direction in ((5.0, 1.0, "up"), (35.0, 0.5, "down"),
                                         (80.0, 1.0, "down"), (0.0, 1.0, "up")):
            found = self.envelope(seed, 1.0, reach, direction, degrees, mesh_factor=mesh)
            masks.append(np.isnan(found.grid))
        labels = (1 + (np.arange(26) >= 13).astype(np.int16))[None, :] * np.ones((22, 1), np.int16)
        slope = envelopes.sector_slope(labels, [envelopes.SlopeRule(0.2),
                                                envelopes.SlopeRule(3.0)], None)
        request = request_of(slope_mode="sectors", slope_deg=None, reach_m=reach,
                             direction="up")
        by_sectors = finish(envelopes.envelope_steps(request, seed_set_of(seed, 1.0),
                                                     slope))[1]
        masks.append(np.isnan(by_sectors.grid))
        for other in masks[1:]:
            self.assertTrue(np.array_equal(masks[0], other))
        self.assertTrue(0 < int(masks[0].sum()) < masks[0].size)

    def test_a_larger_reach_contains_the_smaller_one_and_the_seeds_always_stay(self) -> None:
        """RF-013-14: con más alcance, más celdas y siempre las anteriores con la misma cota; con un
        alcance casi nulo, solo las celdas de semilla, a su cota."""
        rng = np.random.default_rng(35)
        seed = random_seeds(rng, (24, 28))
        previous = None
        for reach in (1e-9, 3.3, 7.7, 12.1, 30.3):
            found = self.envelope(seed, 1.0, reach).grid
            if previous is not None:
                before = np.isfinite(previous)
                self.assertTrue(np.isfinite(found)[before].all())
                self.assertTrue(np.array_equal(found[before], previous[before]))
                self.assertGreaterEqual(int(np.isfinite(found).sum()), int(before.sum()))
            previous = found
            self.assertTrue(np.isfinite(found[np.isfinite(seed)]).all())
        tiny = self.envelope(seed, 1.0, 1e-9).grid
        plain = self.envelope(seed, 1.0, None).grid
        cells = np.isfinite(seed)
        self.assertTrue(np.array_equal(np.isfinite(tiny), cells))
        self.assertTrue(np.array_equal(tiny[cells], plain[cells]))

    def test_seeds_outside_the_work_domain_count_for_the_reach(self) -> None:
        """RF-013-01, RF-013-14: las semillas fuera del dominio de trabajo se usan (la envolvente
        las conserva y el recorte al dominio es posterior): el alcance es el mismo con el dominio
        entero que con medio dominio."""
        rng = np.random.default_rng(36)
        seed = random_seeds(rng, (20, 24))
        half = np.zeros(seed.shape, dtype=bool)
        half[:, :12] = True
        request = request_of(direction="up", slope_deg=30.0, reach_m=5.5)
        slope = envelopes.constant_slope(30.0)
        whole = finish(envelopes.envelope_steps(request, seed_set_of(seed, 1.0), slope))[1]
        part = finish(envelopes.envelope_steps(request, seed_set_of(seed, 1.0, half), slope))[1]
        self.assertTrue(np.array_equal(np.isnan(whole.grid), np.isnan(part.grid)))
        self.assertTrue(np.array_equal(whole.grid[np.isfinite(whole.grid)],
                                       part.grid[np.isfinite(part.grid)]))

    def test_the_reach_modifies_no_input_and_leaves_nothing_if_closed(self) -> None:
        """Principio 7, D-20: ni las semillas ni el dominio ni el mapa de pendientes cambian con un
        alcance; el resultado no comparte memoria con ellos; cerrar a mitad no entrega nada; con
        presupuesto casi nulo hay un paso por unidad."""
        rng = np.random.default_rng(37)
        seed = random_seeds(rng, (60, 70))
        found = seed_set_of(seed, 1.0)
        before = (found.grid.copy(), found.domain.mask.copy())
        request = request_of(direction="down", slope_deg=30.0, reach_m=11.5)
        slope = envelopes.constant_slope(30.0)
        steps, result = finish(envelopes.envelope_steps(request, found, slope, budget_s=1e-9))
        self.assertGreater(len(steps), 3)
        self.assertTrue(all(item.result is None for item in steps))
        self.assertFalse(np.shares_memory(result.grid, found.grid))
        self.assertTrue(np.array_equal(found.grid, before[0]))
        self.assertTrue(np.array_equal(found.domain.mask, before[1]))
        half_way = envelopes.envelope_steps(request, found, slope, budget_s=1e-9)
        self.assertIsNone(next(half_way).result)
        half_way.close()
        self.assertTrue(np.array_equal(found.grid, before[0]))

    def test_the_reach_step_is_checked(self) -> None:
        """Una forma que no casa es un error del programa; un alcance fuera de rango, un rechazo
        de RF-013-16 (``des.reach_range``)."""
        seed = single_seed((6, 7), 2, 3, 100.0)
        with self.assertRaises(ValueError):
            list(envelopes.reach_steps(seed, dfx.grid_from(6, 8, 1.0), 5.0))
        for bad in (0.0, -2.0, math.nan, math.inf):
            with self.subTest(reach=bad), self.assertRaises(messages.DesignError) as caught:
                list(envelopes.reach_steps(seed, dfx.grid_from(6, 7, 1.0), bad, name="e1"))
            self.assertEqual((caught.exception.code, caught.exception.field),
                             ("des.reach_range", "reach_m"))


class RefusalsTest(unittest.TestCase):
    """RF-013-16: lo que se rechaza antes de calcular, en español y nombrando el objeto, el campo
    y el valor; no se calcula ni se registra nada."""

    COMMAND_ES = "Diseño ▸ Cantera ▸ Envolventes y escalonado…"
    COMMAND_EN = "Design ▸ Quarry ▸ Envelopes and benching…"
    SEED = single_seed((6, 7), 2, 3, 100.0)

    def refused(self, request: Any, found: Any = None) -> Any:
        """El ``DesignError`` con el que ``envelope_steps`` rechaza la petición al avanzar,
        antes de ceder un solo paso."""
        found = seed_set_of(self.SEED, 1.0) if found is None else found
        steps = envelopes.envelope_steps(request, found, envelopes.constant_slope(35.0))
        with self.assertRaises(messages.DesignError) as caught:
            next(steps)
        return caught.exception

    def assert_says(self, error: Any, code: str, field: str) -> None:
        """El código, el campo, el objeto, la orden y los dos idiomas sin marcadores sueltos."""
        self.assertEqual((error.code, error.field), (code, field))
        self.assertIn("e1", error.obj)
        self.assertIn("e1", error.text)
        self.assertIn(f"«{field}»", error.text)
        self.assertIn(self.COMMAND_ES, error.text)
        self.assertIn("no se calcula ni se registra nada", error.text)
        english = messages.render(code, language="en", **error.values)
        self.assertIn(self.COMMAND_EN, english)
        for text in (error.text, english):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)

    def test_a_slope_that_is_not_a_number_from_0_included_to_90_excluded_is_refused(self) -> None:
        """RF-013-16: una pendiente de -0,1°, de 90° (excluido), de 120°, NaN, infinita o sin
        valor se rechaza con ``des.slope_range`` nombrando la envolvente, el campo y el valor; 0°
        (incluido) y 89,999° pasan."""
        cases: list[tuple[float | None, Any]] = [(-0.1, -0.1), (90.0, 90.0), (120.0, 120.0),
                                                 (math.nan, "nan"), (math.inf, "inf"),
                                                 (None, "—")]
        for bad, shown in cases:
            with self.subTest(slope=bad):
                error = self.refused(request_of(slope_deg=bad))
                self.assert_says(error, "des.slope_range", "slope_deg")
                self.assertEqual(error.value, shown)
        for good in (0.0, 35.0, 89.999):
            with self.subTest(slope=good):
                self.assertIsNone(envelopes.check_request(request_of(slope_deg=good)))

    def test_a_mesh_factor_outside_0_excluded_to_1_is_refused(self) -> None:
        """RF-013-11, RF-013-16: el factor de malla de una pendiente constante ha de estar entre 0
        (excluido) y 1; fuera, ``des.mesh_factor_range`` con el campo y el valor; en 1 y en 0,0001
        pasa."""
        for bad in (0.0, -0.5, 1.0001, math.nan):
            with self.subTest(mesh_factor=bad):
                error = self.refused(request_of(mesh_factor=bad))
                self.assert_says(error, "des.mesh_factor_range", "mesh_factor")
        for good in (1.0, 0.0001):
            self.assertIsNone(envelopes.check_request(request_of(mesh_factor=good)))

    def test_the_exact_metric_with_slopes_by_sector_is_refused(self) -> None:
        """RF-013-13, RF-013-16: la euclídea exacta solo admite la pendiente constante; con la de
        los sectores, ``des.exact_needs_constant_slope`` (campo ``slope_mode``, valor
        «sectors»); el *chamfer* con sectores, y la exacta con una constante, pasan."""
        error = self.refused(request_of(metric="exact", slope_mode="sectors", slope_deg=None))
        self.assert_says(error, "des.exact_needs_constant_slope", "slope_mode")
        self.assertEqual(error.value, "sectors")
        for request in (request_of(metric="chamfer5", slope_mode="sectors", slope_deg=None),
                        request_of(metric="exact", slope_mode="constant")):
            self.assertIsNone(envelopes.check_request(request))

    def test_by_sectors_the_constant_slope_fields_are_not_asked_for(self) -> None:
        """RF-013-13: con la pendiente por sectores no se comprueban el grado ni el factor de malla
        de la petición (la pendiente sale de cada sector y de su perfil)."""
        request = request_of(slope_mode="sectors", slope_deg=None, mesh_factor=0.0)
        self.assertIsNone(envelopes.check_request(request))

    def test_a_reach_that_is_not_a_positive_number_is_refused(self) -> None:
        """RF-013-14, RF-013-16: un alcance de 0, negativo, NaN o infinito se rechaza con
        ``des.reach_range`` (campo ``reach_m``); sin alcance y uno positivo pasan."""
        for bad in (0.0, -5.0, math.nan, math.inf):
            with self.subTest(reach=bad):
                error = self.refused(request_of(reach_m=bad))
                self.assert_says(error, "des.reach_range", "reach_m")
        for good in (None, 0.001, 1.0e6):
            self.assertIsNone(envelopes.check_request(request_of(reach_m=good)))

    def test_seeds_without_a_finite_elevation_are_refused(self) -> None:
        """RF-013-16: unas semillas sin ninguna celda con cota finita (todas ``+inf``, NaN o
        ``−inf``) se rechazan con ``des.seeds_empty`` (campo ``seeds``, valor 0 celdas), con las
        celdas de su zona que no tenían cota (42 aquí)."""
        blank = np.full((6, 7), np.inf)
        blank[0, 0], blank[1, 1] = np.nan, -np.inf
        for seeds in (seed_set_of(blank, 1.0),
                      seeds_mod.collect_seeds(np.full((6, 7), np.nan), np.ones((6, 7), bool),
                                              seed_set_of(blank, 1.0).domain,
                                              dfx.grid_from(6, 7, 1.0))):
            error = self.refused(request_of(), seeds)
            self.assert_says(error, "des.seeds_empty", "seeds")
            self.assertEqual(error.value, 0)
        self.assertEqual(error.values["nodata"], 42)
        self.assertIn("42 celdas", error.text)

    def test_an_empty_work_domain_is_refused(self) -> None:
        """RF-013-16: un dominio de trabajo sin ninguna celda se rechaza con ``des.domain_empty``
        (campo ``domain``, valor 0 celdas) aunque haya semillas fuera de él."""
        error = self.refused(request_of(), seed_set_of(self.SEED, 1.0,
                                                       np.zeros(self.SEED.shape, dtype=bool)))
        self.assert_says(error, "des.domain_empty", "domain")
        self.assertEqual(error.value, 0)

    def test_the_request_is_checked_before_the_seeds_and_the_seeds_before_the_domain(self) -> None:
        """RF-013-16: con varias causas se rechaza primero la que no necesita leer nada (la
        petición), luego unas semillas vacías y luego un dominio vacío."""
        nothing = np.full((6, 7), np.inf)
        none_at_all = seed_set_of(nothing, 1.0, np.zeros((6, 7), dtype=bool))
        self.assertEqual(self.refused(request_of(slope_deg=95.0), none_at_all).code,
                         "des.slope_range")
        self.assertEqual(self.refused(request_of(), none_at_all).code, "des.seeds_empty")
        self.assertEqual(self.refused(request_of(), seed_set_of(
            self.SEED, 1.0, np.zeros((6, 7), dtype=bool))).code, "des.domain_empty")

    def test_a_valid_request_passes_every_check(self) -> None:
        """RF-013-16: una petición con pendiente, factor de malla y alcance en rango y unas semillas
        con dominio pasa las dos comprobaciones y se calcula."""
        request = request_of(reach_m=4.0, mesh_factor=0.9)
        found = seed_set_of(self.SEED, 1.0)
        self.assertIsNone(envelopes.check_request(request))
        self.assertIsNone(envelopes.check_seed_set(request, found))
        steps = envelopes.envelope_steps(request, found, envelopes.constant_slope(35.0, 0.9))
        self.assertIsInstance(finish(steps)[1], envelopes.Envelope)

    def test_a_refusal_yields_nothing_and_modifies_nothing(self) -> None:
        """RF-013-16 (como RF-011-03): el rechazo sale antes de ceder un solo ``Progress`` (nada se
        entrega) y deja las semillas y el dominio como estaban."""
        found = seed_set_of(self.SEED, 1.0, np.zeros(self.SEED.shape, dtype=bool))
        before = (found.grid.copy(), found.domain.mask.copy())
        for request in (request_of(), request_of(slope_deg=95.0)):
            steps = envelopes.envelope_steps(request, found, envelopes.constant_slope(35.0))
            produced = []
            with self.assertRaises(messages.DesignError):
                for item in steps:
                    produced.append(item)
            self.assertEqual(produced, [])
        self.assertTrue(np.array_equal(found.grid, before[0]))
        self.assertTrue(np.array_equal(found.domain.mask, before[1]))

    def test_request_slope_is_the_constant_slope_of_the_request(self) -> None:
        """RF-013-11, RF-013-13: la pendiente de una petición de pendiente constante es
        ``tan(°)·factor de malla`` (como ``constant_slope``), con los mismos rechazos; por sectores
        la resuelve quien llama (``ValueError``)."""
        slope = envelopes.request_slope(request_of(slope_deg=35.0, mesh_factor=0.9))
        self.assertTrue(slope.uniform)
        self.assertEqual(slope.tan, envelopes.constant_slope(35.0, 0.9).tan)
        for bad in (request_of(slope_deg=90.0), request_of(mesh_factor=0.0)):
            with self.assertRaises(messages.DesignError):
                envelopes.request_slope(bad)
        with self.assertRaises(ValueError):
            envelopes.request_slope(request_of(slope_mode="sectors", slope_deg=None))

    def test_the_six_codes_are_errors_in_both_languages(self) -> None:
        """Principio 10: los seis códigos de la tarea son errores del catálogo, con su texto en
        español y en inglés, y rellenos con sus valores no dejan ni «?» ni «{…}»."""
        codes = ("des.slope_range", "des.mesh_factor_range", "des.reach_range",
                 "des.exact_needs_constant_slope", "des.seeds_empty", "des.domain_empty")
        values = {"envelope": "e1", "nodata": 3}
        for code in codes:
            with self.subTest(code=code):
                self.assertEqual(messages.MESSAGES[code].severity, "error")
                error = messages.DesignError(code, obj="Envolvente «e1»", field="campo",
                                             value="v", **values)
                for language in ("es", "en"):
                    text = messages.render(code, language=language, **error.values)
                    self.assertNotIn("{", text)
                    self.assertNotIn("?", text)


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


class ProjectRefusalsTest(dfx.DesignProjectCase):
    """RF-013-14, RF-013-16 sobre el proyecto del diseño (160 × 160 celdas de 2 m): una superficie
    en otra rejilla, otra con cota solo en un bloque, una capa dentro del sector 1 y otra fuera del
    perímetro: lo que se rechaza se rechaza antes de calcular y no deja nada en el proyecto."""

    LAYER = "gis_fea_cuadro"
    FAR = "gis_fea_lejos"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        grid = cfx.SITE_GRID
        rows, cols = np.indices(grid.shape)
        slope = 600.0 + 0.5 * cols + 0.25 * rows
        island = np.full(grid.shape, np.nan)
        island[:10, :10] = 650.0
        shifted = gis.Grid(grid.west + 2.0, grid.north, grid.dx, grid.dy, grid.ncols, grid.nrows)
        helper = cls("test_a_surface_in_another_grid_is_refused_before_calculating")
        helper.write_surfaces(("ladera", dfx.raster(grid, slope)),
                              ("desplazada", dfx.raster(shifted, slope)),
                              ("isla", dfx.raster(grid, island)))
        helper.write_layer(cls.LAYER, [[[cfx.rectangle(40.0, 40.0, 60.0, 60.0)]]])
        helper.write_layer(cls.FAR, [[[cfx.rectangle(230.0, -90.0, 290.0, -40.0)]]])
        cls.masks_ = helper.masks()

    def snapshot(self) -> tuple[Any, ...]:
        """Lo que escribiría un cálculo: filas de operaciones, datos y cifras, y los ficheros."""
        counts = tuple(self.query(f"SELECT COUNT(*) FROM {table}")[0][0]
                       for table in ("gb_operation", "gb_dataset", "gb_operation_io",
                                     "gb_figure"))
        files = tuple(sorted((path.relative_to(self.root).as_posix(), path.stat().st_size)
                             for path in self.root.rglob("*") if path.is_file()))
        return counts, files

    def calculate(self, request: Any) -> Any:
        """Lo que hará la orden: las semillas de la petición sobre las máscaras de V01 y su
        envolvente (la pendiente es constante)."""
        found = finish(seeds_mod.build_seeds_steps(self.project, request, self.masks_))[1]
        slope = envelopes.request_slope(request)
        return finish(envelopes.envelope_steps(request, found, slope))[1]

    def test_a_surface_in_another_grid_is_refused_before_calculating(self) -> None:
        """RF-013-16: unas semillas de una superficie en otra rejilla se rechazan nombrando la
        superficie, el campo (``west``) y la orden de la 006, antes de calcular, y no queda nada
        registrado ni escrito."""
        before = self.snapshot()
        request = request_of(seeds=model.SeedSource("surface", surface="gis_dtm_desplazada"))
        with self.assertRaises(messages.DesignError) as caught:
            self.calculate(request)
        error = caught.exception
        self.assertEqual((error.code, error.field), ("des.surface_mismatch", "west"))
        self.assertIn("gis_dtm_desplazada", error.text)
        self.assertIn("Topografía ▸ Superficies ▸ Rejilla de proyecto desde un MDT…", error.text)
        self.assertEqual(self.snapshot(), before)

    def test_seeds_without_elevation_in_their_zone_are_refused(self) -> None:
        """RF-013-16: unas semillas de una superficie cuya zona no tiene ninguna cota (la zona es
        una capa fuera del bloque con dato) se rechazan con ``des.seeds_empty`` y las 100 celdas
        de la zona sin cota; no queda nada escrito."""
        before = self.snapshot()
        request = request_of(seeds=model.SeedSource("surface", surface="gis_dtm_isla",
                                                    zone=model.Zone("layer", self.LAYER)))
        with self.assertRaises(messages.DesignError) as caught:
            self.calculate(request)
        error = caught.exception
        self.assertEqual((error.code, error.field, error.value), ("des.seeds_empty", "seeds", 0))
        self.assertEqual(error.values["nodata"], 100)
        self.assertIn("100 celdas", error.text)
        self.assertEqual(self.snapshot(), before)

    def test_an_empty_work_domain_is_refused(self) -> None:
        """RF-013-16: un dominio acotado a una capa fuera del perímetro de actuación queda vacío:
        se rechaza con ``des.domain_empty`` aunque haya semillas (750 celdas) en esa capa; no queda
        nada escrito."""
        before = self.snapshot()
        request = request_of(seeds=model.SeedSource("fixed", elevation_m=700.0,
                                                    zone=model.Zone("layer", self.FAR)),
                             domain=model.WorkDomain(layer=self.FAR))
        with self.assertRaises(messages.DesignError) as caught:
            self.calculate(request)
        self.assertEqual((caught.exception.code, caught.exception.field),
                         ("des.domain_empty", "domain"))
        self.assertEqual(self.snapshot(), before)

    def test_a_fill_with_a_reach_is_calculated_and_writes_nothing(self) -> None:
        """RF-013-11, RF-013-14: la envolvente ascendente de unas semillas fijas a 650 m en una
        capa de 10 × 10 celdas del sector 1, con 8 m de alcance y 30° (paso 2 m), da envolvente en
        las celdas a ≤ 8 m de las semillas (la distancia *chamfer* del oráculo, de 0,98644·2 m por
        celda en el eje), ``NaN`` en el resto y exactamente la cota de las semillas en el interior;
        calcular no escribe nada en el proyecto ni cambia la superficie."""
        before = self.snapshot()
        request = request_of(direction="up", slope_deg=30.0, reach_m=8.0,
                             seeds=model.SeedSource("fixed", elevation_m=650.0,
                                                    zone=model.Zone("layer", self.LAYER)))
        found = self.calculate(request)
        seeds = finish(seeds_mod.build_seeds_steps(self.project, request, self.masks_))[1]
        self.assertEqual(seeds.cells, 100)
        origin = np.where(np.isfinite(seeds.grid), 0.0, np.inf)
        distance = oracles.dijkstra(origin, 1.0, cfx.SITE_GRID.dx)
        self.assertTrue(np.array_equal(np.isfinite(found.grid), distance <= 8.0))
        self.assertGreater(int(np.isfinite(found.grid).sum()), seeds.cells)
        self.assertLess(int(np.isfinite(found.grid).sum()), found.grid.size)
        self.assertTrue((found.grid[np.isfinite(seeds.grid)] == 650.0).all())
        self.assertEqual(float(found.grid[np.isfinite(found.grid)].min()), 650.0)
        self.assertEqual(self.snapshot(), before)


class ExactByHandTest(unittest.TestCase):
    """RF-013-12 (A5): la euclídea exacta, ``E↑(p) = mín_q [f_q + t·h·|p − q|]``, a mano."""

    def test_cone_of_one_seed_is_the_distance_between_cell_centres(self) -> None:
        """RF-013-12, CE-013-01: una semilla a 100 m en una rejilla de 30 × 40 celdas de 2 m, con
        ``t = 0,5``: en las celdas de los triángulos pitagóricos 3-4-5, 5-12-13, 8-15-17 y 20-21-29
        (en los cuatro cuadrantes) la cota es ``100 ± 0,5·2·n`` (``n`` = 5, 13, 17, 29) a ≤ 10⁻⁹ m,
        sin la escala del *chamfer*; la celda de la semilla queda exactamente a su cota."""
        seed = single_seed((30, 40), 12, 17, 100.0)
        for direction, sign in (("up", 1.0), ("down", -1.0)):
            found = solve_exact(seed, 0.5, 2.0, direction).grid
            self.assertEqual(found[12, 17], 100.0)
            for d_row, d_col, cells in ((3, 4, 5.0), (5, 12, 13.0), (8, 15, 17.0),
                                        (12, 16, 20.0), (0, 20, 20.0), (12, 0, 12.0)):
                for sign_row in (1, -1):
                    for sign_col in (1, -1):
                        cell = (12 + sign_row * d_row, 17 + sign_col * d_col)
                        if not (0 <= cell[0] < 30 and 0 <= cell[1] < 40):
                            continue
                        with self.subTest(direction=direction, cell=cell):
                            self.assertAlmostEqual(found[cell], 100.0 + sign * 0.5 * 2.0 * cells,
                                                   delta=TOLERANCE_M)

    def test_two_seeds_take_the_envelope_of_both(self) -> None:
        """RF-013-11, RF-013-12: dos semillas de 100 y 104 m en una fila de 10 celdas de 1 m con
        ``t = 1``: la ascendente es la menor de las dos pirámides, ``100,101,102,103,104,105,106,
        106,105,104``; la descendente, la mayor, ``100,99,98,98,99,100,101,102,103,104``."""
        seed = np.full((1, 10), np.inf)
        seed[0, 0], seed[0, 9] = 100.0, 104.0
        up = solve_exact(seed, 1.0).grid[0]
        down = solve_exact(seed, 1.0, direction="down").grid[0]
        self.assertTrue(np.array_equal(up, [100, 101, 102, 103, 104, 105, 106, 106, 105, 104]))
        self.assertTrue(np.array_equal(down, [100, 99, 98, 98, 99, 100, 101, 102, 103, 104]))

    def test_zero_slope_is_a_flat_envelope_at_the_lowest_seed(self) -> None:
        """Con pendiente 0° la ascendente es plana a la cota de la semilla más baja y la
        descendente, a la de la más alta, en toda la rejilla."""
        rng = np.random.default_rng(41)
        seed = random_seeds(rng, (13, 17))
        finite = seed[np.isfinite(seed)]
        up = solve_exact(seed, 0.0, 2.0).grid
        down = solve_exact(seed, 0.0, 2.0, "down").grid
        self.assertTrue((up == finite.min()).all())
        self.assertTrue((down == finite.max()).all())

    def test_no_seeds_leave_everything_without_envelope(self) -> None:
        """Sin ninguna semilla, ``+inf`` (``−inf`` en la descendente), sin fallar (el rechazo es de
        RF-013-16, antes de calcular); NaN, ``+inf`` y ``−inf`` no son semillas."""
        blank = np.full((6, 7), np.inf)
        self.assertTrue((solve_exact(blank, 0.7).grid == np.inf).all())
        self.assertTrue((solve_exact(blank, 0.7, direction="down").grid == -np.inf).all())
        noisy = blank.copy()
        noisy[0, 0], noisy[1, 1], noisy[2, 2] = np.nan, -np.inf, 50.0
        plain = single_seed((6, 7), 2, 2, 50.0)
        self.assertTrue(np.array_equal(solve_exact(noisy, 0.7).grid, solve_exact(plain, 0.7).grid))

    def test_the_result_has_the_reduction_counts(self) -> None:
        """La ``Envelope`` de la exacta lleva las cuentas de las reducciones (RF-013-12: ninguna
        semilla se descarta en silencio): en un bloque macizo plano de 9 × 9 semillas, las 49 de
        dentro son redundantes y las 32 del anillo quedan; el *chamfer* no tiene reducción; la
        exacta hace una sola pasada."""
        seed = np.full((15, 15), np.inf)
        seed[3:12, 3:12] = 100.0
        found = solve_exact(seed, 0.5, 1.0)
        reduced = found.reduction
        self.assertEqual((reduced.seeds, reduced.dominated, reduced.redundant, reduced.kept),
                         (81, 0, 49, 32))
        self.assertEqual(found.iterations, 1)
        self.assertLessEqual(found.violation, TOLERANCE_M)
        self.assertIsNone(solve(seed, 0.5, 1.0).reduction)


def exact_cases(rng: np.random.Generator, count: int, low: int, high: int
                ) -> Iterator[tuple[str, np.ndarray, float, float, str]]:
    """Casos aleatorios de la euclídea exacta: ``(etiqueta, semillas, tan, paso, dirección)`` con
    semillas sueltas, de contorno, macizas y mezcladas, pendientes de 0 a 3, pasos de 0,5 a 2,5 m y
    las dos direcciones, en rejillas de ``low`` a ``high − 1`` celdas de lado."""
    for index in range(count):
        shape = (int(rng.integers(low, high)), int(rng.integers(low, high)))
        tan = float(rng.choice([0.0, 0.1, 0.3, 0.7, 1.5, 3.0]))
        step = float(rng.choice([0.5, 1.0, 2.5]))
        kind = dfx.ZONE_KINDS[index % 4]
        direction = "up" if (index // 4) % 2 == 0 else "down"
        label = f"caso {index} ({kind}, {shape[0]}×{shape[1]}, t={tan}, h={step}, {direction})"
        yield label, dfx.random_zone(rng, shape, kind, tan * step), tan, step, direction


class ExactOracleTest(unittest.TestCase):
    """RF-013-12: la euclídea exacta es igual a la fuerza bruta (oráculo) a ≤ 10⁻⁹ m."""

    def check(self, label: str, seed: np.ndarray, tan: float, step: float, direction: str,
              **options: Any) -> Any:
        expected = oracles.brute_force_euclidean(seed, tan, step, direction=direction)
        found = solve_exact(seed, tan, step, direction, **options)
        difference = float(np.abs(found.grid - expected).max())
        if difference > TOLERANCE_M:
            self.fail(f"{label}: difiere de la fuerza bruta {difference:.3g} m")
        return found

    def test_400_random_cases_with_small_blocks(self) -> None:
        """RF-013-12, plan A5: 400 casos aleatorios (semillas sueltas, de contorno, macizas y
        mezcladas; pendientes de 0 a 3; pasos de 0,5 a 2,5 m; las dos direcciones; rejillas de 5 a
        13 celdas de lado) con bloques de 3 × 3 y superbloques de 2 × 2 bloques (muchos bloques
        parciales en el borde) y unidades de 500 evaluaciones: igual a la fuerza bruta a ≤ 10⁻⁹ m;
        las dos reducciones han retirado semillas de verdad."""
        rng = np.random.default_rng(20_261_103)
        dominated = redundant = cases = 0
        for label, seed, tan, step, direction in exact_cases(rng, 400, 5, 14):
            found = self.check(label, seed, tan, step, direction, block=3, group=2,
                               evals_per_unit=500)
            dominated += found.reduction.dominated
            redundant += found.reduction.redundant
            cases += 1
        self.assertEqual(cases, 400)
        self.assertGreater(dominated, 1_000)
        self.assertGreater(redundant, 10)

    def test_random_cases_with_the_default_blocks(self) -> None:
        """Con los bloques de 8 × 8 y superbloques de 128 por defecto: 40 casos de 5 a 39 celdas de
        lado, iguales a la fuerza bruta."""
        rng = np.random.default_rng(20_261_104)
        for label, seed, tan, step, direction in exact_cases(rng, 40, 5, 40):
            self.check(label, seed, tan, step, direction)

    def test_a_grid_that_crosses_the_superblock_boundary(self) -> None:
        """Una rejilla de 150 × 140 celdas, que cruza el límite de 128 del superbloque por defecto
        (con bloques parciales de 6 y 12 celdas en el borde), con una zona maciza rugosa, un
        contorno y semillas sueltas, igual a la fuerza bruta a ≤ 10⁻⁹ m."""
        rng = np.random.default_rng(20_261_105)
        shape = (150, 140)
        for tan, step, kind, direction in ((0.7, 1.0, "solid", "down"), (1.5, 2.0, "contour", "up"),
                                           (0.3, 0.5, "loose", "up")):
            seed = dfx.random_zone(rng, shape, kind, tan * step)
            found = self.check(f"{kind} {direction}", seed, tan, step, direction)
            self.assertEqual(found.grid.shape, shape)

    def test_a_smooth_zone_is_redundant_inside_and_a_steep_one_is_dominated(self) -> None:
        """RF-013-12, plan A5, a mano: una zona maciza de 30 × 30 semillas en una rejilla de 40 × 45
        celdas con un plano de 0,3 de ``k`` por fila y 0,2 por columna (menos que el umbral, aun en
        la diagonal) deja redundantes las 28 × 28 = 784 de dentro y quedan las 116 del anillo; con
        1,3 de ``k`` por columna (más empinada que el cono) todas las de las columnas 1 a 29 de la
        zona (870) quedan dominadas por la de su izquierda y queda la columna de más abajo (30).
        En los dos casos, igual a la fuerza bruta."""
        tan, step = 0.5, 2.0
        rise = tan * step
        rows, cols = np.indices((30, 30))
        for gradient, counts in (((0.3, 0.2), (0, 784, 116)), ((0.0, 1.3), (870, 0, 30))):
            seed = np.full((40, 45), np.inf)
            seed[5:35, 5:35] = 100.0 + rise * (gradient[0] * rows + gradient[1] * cols)
            for direction in ("up", "down"):
                found = self.check(f"plano {gradient} {direction}", seed, tan, step, direction,
                                   block=4, group=2)
                reduced = found.reduction
                with self.subTest(gradient=gradient, direction=direction):
                    self.assertEqual((reduced.dominated, reduced.redundant, reduced.kept), counts)

    def test_a_rough_solid_zone_at_the_threshold_of_the_redundant_rule(self) -> None:
        """Una zona maciza cuyas vecinas difieren justo en torno al umbral de la redundante
        (``k = t·h`` por celda): 40 casos con alturas que son múltiplos de ``k/2`` más un ruido de
        ±10⁻¹², iguales a la fuerza bruta aunque cada semilla esté en el filo de ser redundante."""
        rng = np.random.default_rng(20_261_106)
        retired = 0
        for index in range(40):
            tan, step = float(rng.choice([0.5, 1.0])), float(rng.choice([1.0, 2.0]))
            rise = tan * step
            shape = (int(rng.integers(6, 14)), int(rng.integers(6, 14)))
            steps = rng.integers(-3, 4, size=shape).cumsum(axis=0).cumsum(axis=1) % 5
            seed = 100.0 + steps * rise / 2.0 + rng.uniform(-1e-12, 1e-12, shape)
            direction = "up" if index % 2 == 0 else "down"
            found = self.check(f"umbral {index}", seed, tan, step, direction, block=4, group=2,
                               evals_per_unit=100)  # pocas evaluaciones: la búsqueda va por trozos
            retired += found.reduction.redundant
        self.assertGreater(retired, 100)

    def test_thin_and_tiny_grids(self) -> None:
        """Rejillas de una fila, de una columna, de 1 × 1 y de 2 × 2, con semillas en el borde, en
        una esquina o en todas las celdas."""
        rng = np.random.default_rng(42)
        shapes = [(1, 1), (1, 9), (9, 1), (2, 2), (2, 7), (3, 3), (1, 40), (40, 1)]
        for shape in shapes:
            for fill in (0.0, 0.5, 1.0):
                seed = np.full(shape, np.inf)
                mask = rng.random(shape) <= fill
                mask.flat[int(rng.integers(0, mask.size))] = True
                seed[mask] = rng.uniform(90.0, 120.0, int(mask.sum()))
                for direction in ("up", "down"):
                    self.check(f"{shape} relleno {fill} {direction}", seed, 0.7, 1.5, direction,
                               block=2, group=2)

    def test_the_unscaled_chamfer_is_the_upper_bound_the_search_needs(self) -> None:
        """Plan A5 (1): la cota ``U`` es el *chamfer* sin escala, que nunca queda por debajo de la
        euclídea (es la longitud de un camino real) y no la pasa más de un 2,75 % de la mayor
        distancia de la rejilla por la pendiente: con el oráculo, en 30 casos aleatorios."""
        rng = np.random.default_rng(43)
        for label, seed, tan, step, _direction in exact_cases(rng, 30, 6, 20):
            upper = oracles.dijkstra(seed, tan, step, scale=1.0)
            exact = oracles.brute_force_euclidean(seed, tan, step)
            longest = step * math.hypot(*seed.shape)
            with self.subTest(label):
                self.assertGreaterEqual(float((upper - exact).min()), -1e-9)
                self.assertLessEqual(float((upper - exact).max()),
                                     0.0275 * tan * longest + 1e-9)


class ExactFixedPointTest(unittest.TestCase):
    """RF-013-15, CE-013-02: la euclídea exacta converge y respeta las semillas."""

    def test_using_the_result_as_a_seed_changes_nothing(self) -> None:
        """RF-013-15, CE-013-02: usar la envolvente exacta como semilla en todas sus celdas no
        cambia ninguna más de 10⁻⁹ m (con el cálculo mismo y con la fuerza bruta de las propias
        celdas), las 16 relajaciones con los pesos sin escala y las semillas se cumplen, y la
        violación que entrega es ≤ 10⁻⁹ m; en las dos direcciones."""
        rng = np.random.default_rng(44)
        for label, seed, tan, step, direction in exact_cases(rng, 24, 6, 18):
            found = solve_exact(seed, tan, step, direction)
            again = solve_exact(found.grid, tan, step, direction)
            with self.subTest(label):
                self.assertLessEqual(float(np.abs(again.grid - found.grid).max()), TOLERANCE_M)
                self.assertLessEqual(oracles.relaxation_violation(
                    found.grid, tan, step, scale=1.0, direction=direction), TOLERANCE_M)
                self.assertEqual(oracles.seed_violation(found.grid, seed, direction=direction),
                                 0.0)
                self.assertLessEqual(found.violation, TOLERANCE_M)

    def test_neighbour_slope_never_exceeds_the_effective_slope(self) -> None:
        """RF-013-15: entre celdas vecinas (los 8 vecinos 3 × 3) la pendiente, medida aparte, no
        pasa de la efectiva con la tolerancia de la métrica exacta (0, salvo el redondeo: ≤ 10⁻⁹
        de pendiente), en las dos direcciones."""
        rng = np.random.default_rng(45)
        for label, seed, tan, step, direction in exact_cases(rng, 30, 6, 18):
            found = solve_exact(seed, tan, step, direction).grid
            worst = -math.inf
            for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
                first, second = pair_slices(found.shape, d_row, d_col)
                slope = np.abs(found[second] - found[first]) / (math.hypot(d_row, d_col) * step)
                worst = max(worst, float((slope - tan).max()))
            with self.subTest(label):
                self.assertLessEqual(worst, TOLERANCE_M)

    def test_the_check_uses_the_metric_of_the_envelope(self) -> None:
        """RF-013-15: ``check_envelope`` con ``metric="exact"`` da por buena la envolvente exacta
        (sus pesos son los de la longitud real); con el *chamfer* escalado la daría por mala (su
        peso es un 1,356 % menor), así que la métrica cuenta. Una celda 1 m alta sobre lo que
        permite su vecina la nombra con su celda absoluta y 1 m."""
        seed = single_seed((15, 15), 7, 7, 100.0)
        geometry = dfx.grid_from(15, 15, 1.0)
        slope = envelopes.SlopeField(0.8)
        good = solve_exact(seed, 0.8).grid
        envelopes.check_envelope(good, seed, slope, geometry, "up", name="e1", metric="exact")
        with self.assertRaises(messages.DesignError) as scaled:
            envelopes.check_envelope(good, seed, slope, geometry, "up", name="e1")
        self.assertEqual(scaled.exception.code, "des.envelope_not_fixed_point")
        bumped = good.copy()
        bumped[3, 9] += 1.0
        with self.assertRaises(messages.DesignError) as caught:
            envelopes.check_envelope(bumped, seed, slope, geometry, "up", name="e1",
                                     metric="exact")
        error = caught.exception
        self.assertEqual(error.code, "des.envelope_not_fixed_point")
        self.assertEqual((error.values["row"], error.values["col"]), (3, 9))
        self.assertAlmostEqual(error.value, 1.0, delta=1e-9)

    def test_a_seed_on_the_wrong_side_is_named_with_the_exact_metric(self) -> None:
        """RF-013-15: una semilla 0,3 m por encima de su cota en la ascendente lanza
        ``des.envelope_seed_above`` con su celda absoluta y los 0,3 m, también con la exacta."""
        seed = single_seed((15, 15), 7, 7, 100.0)
        raised = solve_exact(seed, 0.8).grid
        raised[7, 7] += 0.3
        with self.assertRaises(messages.DesignError) as caught:
            envelopes.check_envelope(raised, seed, envelopes.SlopeField(0.8),
                                     dfx.grid_from(15, 15, 1.0), "up", name="e1", metric="exact")
        self.assertEqual(caught.exception.code, "des.envelope_seed_above")
        self.assertAlmostEqual(caught.exception.value, 0.3, delta=1e-9)

    def test_a_wrong_metric_name_is_a_program_error(self) -> None:
        """Una métrica que no es ``chamfer5`` ni ``exact`` es un error del programa."""
        seed = single_seed((6, 7), 2, 3, 100.0)
        geometry = dfx.grid_from(6, 7, 1.0)
        with self.assertRaises(ValueError):
            envelopes.check_envelope(seed, seed, envelopes.SlopeField(0.5), geometry, "up",
                                     metric="chamfer3")
        with self.assertRaises(ValueError):
            list(envelopes.reach_steps(seed, geometry, 3.0, "chamfer3"))


class ExactRequestTest(unittest.TestCase):
    """``envelope_steps`` con la métrica exacta: la petición, los rechazos y el alcance."""

    def test_the_request_selects_the_exact_metric(self) -> None:
        """RF-013-12: ``metric="exact"`` en la petición da la envolvente exacta (la de
        ``exact_steps``, bit a bit) y la de ``chamfer5``, el *chamfer*; en un cono de 60 m las dos
        difieren más de 0,1 m y la exacta es la de la fuerza bruta a ≤ 10⁻⁹ m."""
        seed = single_seed((60, 70), 30, 35, 100.0)
        found = seed_set_of(seed, 2.0)
        slope = envelopes.constant_slope(35.0)
        exact_request = request_of(metric="exact", direction="up", slope_deg=35.0)
        chamfer_request = request_of(metric="chamfer5", direction="up", slope_deg=35.0)
        exact = finish(envelopes.envelope_steps(exact_request, found, slope))[1]
        chamfer = finish(envelopes.envelope_steps(chamfer_request, found, slope))[1]
        by_hand = oracles.brute_force_euclidean(seed, float(slope.tan), 2.0)
        self.assertLessEqual(float(np.abs(exact.grid - by_hand).max()), TOLERANCE_M)
        self.assertGreater(float(np.abs(exact.grid - chamfer.grid).max()), 0.1)
        self.assertTrue(np.array_equal(exact.grid, solve_exact(seed, slope, 2.0).grid))
        self.assertIsNotNone(exact.reduction)
        self.assertIsNone(chamfer.reduction)

    def test_the_exact_metric_with_slopes_by_sector_is_refused_when_advancing(self) -> None:
        """RF-013-13, RF-013-16: la exacta con pendiente por sectores da un ``DesignError`` de
        ``des.exact_needs_constant_slope`` (campo ``slope_mode``) al avanzar, antes de ceder un solo
        paso ni calcular nada, aunque la pendiente que se pasa sea uniforme."""
        found = seed_set_of(single_seed((6, 7), 2, 3, 100.0), 1.0)
        request = request_of(metric="exact", slope_mode="sectors", slope_deg=None)
        for slope in (envelopes.SlopeField(0.7), envelopes.SlopeField(np.full((6, 7), 0.7))):
            produced: list[Any] = []
            with self.assertRaises(messages.DesignError) as caught:
                for item in envelopes.envelope_steps(request, found, slope):
                    produced.append(item)
            self.assertEqual(produced, [])
            self.assertEqual((caught.exception.code, caught.exception.field),
                             ("des.exact_needs_constant_slope", "slope_mode"))
            self.assertEqual(caught.exception.value, "sectors")
            self.assertIn("no se calcula ni se registra nada", caught.exception.text)

    def test_a_slope_map_is_accepted_only_if_it_is_constant(self) -> None:
        """Un mapa de pendientes de un solo valor es la constante y da lo mismo; uno con valores
        distintos es un error del programa (``ValueError``) al avanzar: la exacta no admite
        pendiente por celdas (RF-013-16 lo rechaza antes con la petición)."""
        seed = single_seed((8, 9), 3, 4, 100.0)
        constant = solve_exact(seed, 0.7).grid
        same = solve_exact(seed, envelopes.SlopeField(np.full((8, 9), 0.7))).grid
        self.assertTrue(np.array_equal(constant, same))
        varied = np.full((8, 9), 0.7)
        varied[0, 0] = 0.71
        with self.assertRaises(ValueError):
            list(envelopes.exact_steps(seed, dfx.grid_from(8, 9, 1.0),
                                       envelopes.SlopeField(varied), "up"))

    def test_bad_input_is_a_program_error(self) -> None:
        """Una rejilla de celdas no cuadradas, una forma que no casa, una dirección desconocida y
        unos bloques, superbloques o evaluaciones por unidad menores que 1 son errores del programa
        (``ValueError``), al avanzar el generador."""
        seed = single_seed((6, 7), 2, 3, 100.0)
        slope = envelopes.SlopeField(0.7)
        square = dfx.grid_from(6, 7, 1.0)
        wide = gis.Grid(0.0, 12.0, 2.0, 1.0, 7, 6)
        cases: list[tuple[Any, ...]] = [(seed, wide, slope, "up"),
                                        (seed, dfx.grid_from(6, 8, 1.0), slope, "up"),
                                        (seed, square, slope, "sideways"),
                                        (seed[0], square, slope, "up")]
        for args in cases:
            with self.subTest(direction=args[3], shape=getattr(args[1], "shape", None)):
                with self.assertRaises(ValueError):
                    list(envelopes.exact_steps(*args))
        for option in ("block", "group", "evals_per_unit", "cells_per_unit"):
            with self.subTest(option=option), self.assertRaises(ValueError):
                list(envelopes.exact_steps(seed, square, slope, "up", **{option: 0}))

    def test_the_reach_with_the_exact_metric_is_the_euclidean_distance(self) -> None:
        """RF-013-14, A6: con la exacta, el alcance es la distancia euclídea (m) a la semilla más
        próxima —la fuerza bruta con ``f = 0`` y ``t = 1``— y deja ``NaN`` lo que pasa de él: las
        celdas con envolvente son exactamente las de distancia ≤ alcance (con alcances a más de
        10⁻⁶ m de toda celda), y en ellas la envolvente es la de siempre, bit a bit."""
        rng = np.random.default_rng(45)
        for step in (1.5, 2.0):
            seed = random_seeds(rng, (30, 40))
            origin = np.where(np.isfinite(seed), 0.0, np.inf)
            distance = oracles.brute_force_euclidean(origin, 1.0, step)
            plain = envelopes.constant_slope(30.0)
            whole = finish(envelopes.envelope_steps(
                request_of(metric="exact", direction="down", slope_deg=30.0),
                seed_set_of(seed, step), plain))[1]
            for target in (4.0, 9.0, 15.0):
                reach = safe_reach(distance, target * step / 1.5)
                request = request_of(metric="exact", direction="down", slope_deg=30.0,
                                     reach_m=reach)
                found = finish(envelopes.envelope_steps(request, seed_set_of(seed, step),
                                                        plain))[1]
                inside = distance <= reach
                with self.subTest(step=step, reach=round(reach, 3)):
                    self.assertTrue(0 < int(inside.sum()) < inside.size)
                    self.assertTrue(np.array_equal(np.isfinite(found.grid), inside))
                    self.assertTrue(np.array_equal(np.isnan(found.grid), ~inside))
                    self.assertTrue(np.array_equal(found.grid[inside], whole.grid[inside]))
            steps, measured = finish(envelopes.reach_steps(seed, dfx.grid_from(30, 40, step),
                                                           reach, "exact", name="e1"))
            self.assertTrue(all(item.phase == "reach" for item in steps))
            inside = distance <= reach
            self.assertLessEqual(float(np.abs(measured[inside] - distance[inside]).max()),
                                 TOLERANCE_M)
            self.assertTrue(np.isnan(measured[~inside]).all())

    def test_the_exact_reach_is_narrower_than_the_chamfer_one_by_its_scale(self) -> None:
        """RF-013-12, A6: a lo largo del eje, la celda ``n`` (paso 1 m, semilla en el extremo de una
        fila de 14 celdas) está a ``n`` m con la exacta y a ``0,98644·n`` con el *chamfer*: con
        9,95 m de alcance la exacta deja 10 celdas (0 a 9) y el *chamfer*, 11 (la décima queda a
        9,8644 m); con 10,05, 10,15 y 0,5 m, las dos dejan 11, 11 y 1."""
        seed = single_seed((1, 14), 0, 0, 100.0)
        geometry = dfx.grid_from(1, 14, 1.0)
        cases = ((10.05, 11, 11), (9.95, 10, 11), (10.15, 11, 11), (0.5, 1, 1))
        for reach, exact_cells, chamfer_cells in cases:
            exact = finish(envelopes.reach_steps(seed, geometry, reach, "exact"))[1]
            chamfer = finish(envelopes.reach_steps(seed, geometry, reach, "chamfer5"))[1]
            with self.subTest(reach=reach):
                self.assertEqual(int(np.isfinite(exact).sum()), exact_cells)
                self.assertEqual(int(np.isfinite(chamfer).sum()), chamfer_cells)
        whole = finish(envelopes.reach_steps(seed, geometry, 20.0, "exact"))[1]
        self.assertLessEqual(float(np.abs(whole[0] - np.arange(14.0)).max()), TOLERANCE_M)

    def test_by_steps_and_closing_midway(self) -> None:
        """D-20: la exacta es por pasos de la fase «envelope», con avance creciente y su resultado
        solo en el último; con unidades pequeñas hay muchos pasos y el resultado es el mismo, bit a
        bit, que con las de por defecto; cerrar a mitad no entrega nada; ninguna entrada se
        modifica y el resultado no comparte memoria con ella."""
        rng = np.random.default_rng(46)
        seed = dfx.random_zone(rng, (60, 70), "mixed", 0.7)
        before = seed.copy()
        geometry = dfx.grid_from(60, 70, 1.0)
        slope = envelopes.constant_slope(35.0)
        steps, result = finish(envelopes.exact_steps(
            seed, geometry, slope, "down", name="e1", budget_s=1e-9, cells_per_unit=200,
            evals_per_unit=1_000, block=4, group=2))
        self.assertGreater(len(steps), 30)
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
        self.assertFalse(np.shares_memory(result.grid, seed))
        self.assertTrue(np.array_equal(seed, before))
        self.assertTrue(np.array_equal(result.grid, solve_exact(seed, slope, 1.0, "down").grid))
        half_way = envelopes.exact_steps(seed, geometry, slope, "down", budget_s=1e-9,
                                         cells_per_unit=200, evals_per_unit=1_000, block=4,
                                         group=2)
        self.assertIsNone(next(half_way).result)
        half_way.close()
        self.assertTrue(np.array_equal(seed, before))

    def test_float32_seeds_are_taken_as_float64(self) -> None:
        """Unas semillas en float32 dan una envolvente float64, la misma que con sus valores
        pasados a float64."""
        rng = np.random.default_rng(47)
        narrow = random_seeds(rng, (12, 15)).astype(np.float32)
        found = solve_exact(narrow, 0.7)
        self.assertEqual(found.grid.dtype, np.float64)
        self.assertTrue(np.array_equal(found.grid, solve_exact(narrow.astype(np.float64),
                                                               0.7).grid))


if __name__ == "__main__":
    unittest.main()
