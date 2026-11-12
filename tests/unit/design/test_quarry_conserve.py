# SPDX-License-Identifier: GPL-3.0-or-later
"""El techo de conservación de la cantera (spec 014, T10; HU-014-2; RF-014-07, RF-014-08; plan 014
A5, §5.3.1, §5.9; CE-014-02).

- ``design.quarry.conservation_ceiling_steps``: el **techo** ``U = ENV↑(z en la zona Z,
  tan(talud de conservación))`` sobre la envolvente de la 013, a ≤ 10⁻⁹ m del cálculo a mano (la
  euclídea exacta por fuerza bruta); las celdas de la zona sin dato de terreno no lo siembran y se
  avisa con su área (``des.conserve_nodata``); el talud es el parámetro ``des.conserve.slope_deg``,
  sin valor por defecto (D-9).
- ``design.quarry.apply_ceiling``: sus tres reglas: en ``Z``, la superficie es ``z`` (0 m³); fuera,
  ninguna celda con ``z > U`` se excava (``KEEP``) y la superficie no pasa de ``máx(U, z)``: un
  relleno no entierra la zona (error 37).
- ``design.quarry.conserve_moved``: el error de RF-014-08, el volumen que el diseño mueve dentro de
  las zonas (con el espesor mínimo de la 012) y el centro de cada parte (``des.conserve_moved``,
  ``des.conserve_part``).

Sobre una rejilla pequeña de 2 m (la fuerza bruta) y sobre la cantera sintética de
``tests.support.quarry_fixtures`` (T01) para el CE-014-02.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
envelopes = import_geoblender("design.envelopes")
messages = import_geoblender("design.messages")

TOLERANCE_M = 1e-9
SLOPE_DEG = 35.0
"""El talud de conservación de las pruebas (el del análisis, D-9: aquí, un dato de entrada)."""
MIN_THICKNESS_M = 0.1

ROWS, COLS, STEP = 20, 24, 2.0
"""La rejilla pequeña: 20 × 24 celdas de 2 m (48 × 40 m locales)."""
ZONE_ROWS, ZONE_COLS = slice(6, 12), slice(8, 14)
"""La zona a conservar de la rejilla pequeña: 6 × 6 celdas (144 m²)."""


def small_grid() -> Any:
    return dfx.grid_from(ROWS, COLS, STEP)


def small_terrain() -> np.ndarray:
    """Una ladera irregular (m): ``280 + 0,5·x + 0,25·y`` más una onda, para que el techo no sea un
    plano."""
    columns = (np.arange(COLS) + 0.5) * STEP
    rows = ROWS * STEP - (np.arange(ROWS) + 0.5) * STEP
    x, y = np.meshgrid(columns, rows)
    return 280.0 + 0.5 * x + 0.25 * y + 3.0 * np.sin(x / 7.0) * np.cos(y / 5.0)


def small_zone() -> np.ndarray:
    found = np.zeros((ROWS, COLS), dtype=bool)
    found[ZONE_ROWS, ZONE_COLS] = True
    return found


def finish(steps: Any) -> Any:
    return list(steps)[-1].result


def ceiling(zones: Any, start: np.ndarray, geometry: Any, metric: str = "exact") -> Any:
    return finish(quarry.conservation_ceiling_steps(zones, start, geometry, SLOPE_DEG,
                                                    metric=metric))


class CeilingTest(unittest.TestCase):
    """RF-014-07, A5: ``U = ENV↑(z en Z, tan(talud de conservación))``."""

    def setUp(self) -> None:
        self.start = small_terrain()
        self.zone = quarry.ConserveZone("Ladera", small_zone())

    def test_exact_ceiling_against_the_hand_calculation(self) -> None:
        """La euclídea exacta queda a ≤ 10⁻⁹ m de la fuerza bruta ``mín_q [z(q) + t·|p − q|]``
        sobre las celdas de la zona; la zona, el nombre y el talud se conservan."""
        before = self.start.copy()
        found = ceiling((self.zone,), self.start, small_grid())
        seeds = np.where(small_zone(), self.start, np.inf)
        by_hand = oracles.brute_force_euclidean(seeds, math.tan(math.radians(SLOPE_DEG)), STEP)
        self.assertLessEqual(float(np.abs(found.grid - by_hand).max()), TOLERANCE_M)
        np.testing.assert_array_equal(found.zone, small_zone())
        self.assertEqual(found.slope_deg, SLOPE_DEG)
        self.assertEqual(found.names, ("Ladera",))
        self.assertEqual(found.notices, ())
        np.testing.assert_array_equal(self.start, before)

    def test_chamfer_ceiling_is_the_ascending_envelope_of_the_013(self) -> None:
        """Con el *chamfer* 5×5 (por defecto), el techo es la envolvente ascendente de la 013 de
        las mismas semillas, a ≤ 10⁻⁹ m."""
        found = finish(quarry.conservation_ceiling_steps((self.zone,), self.start, small_grid(),
                                                         SLOPE_DEG))
        seeds = np.where(small_zone(), self.start, np.inf)
        expected = finish(envelopes.chamfer_steps(seeds, small_grid(),
                                                  envelopes.constant_slope(SLOPE_DEG), "up"))
        self.assertLessEqual(float(np.abs(found.grid - expected.grid).max()), TOLERANCE_M)

    def test_two_zones_give_the_lower_of_their_ceilings(self) -> None:
        """Dos zonas: el techo es el mínimo de los dos (la envolvente ascendente es un mínimo)."""
        other = np.zeros((ROWS, COLS), dtype=bool)
        other[14:17, 2:5] = True
        second = quarry.ConserveZone("Fuente", other)
        found = ceiling((self.zone, second), self.start, small_grid())
        one = ceiling((self.zone,), self.start, small_grid())
        two = ceiling((second,), self.start, small_grid())
        self.assertLessEqual(float(np.abs(found.grid - np.minimum(one.grid, two.grid)).max()),
                             TOLERANCE_M)
        self.assertEqual(found.names, ("Ladera", "Fuente"))

    def test_cells_without_terrain_do_not_seed_and_are_reported(self) -> None:
        """Las celdas de la zona sin dato no siembran el techo y se avisa con su área (4 celdas de
        4 m², 16 m²)."""
        start = self.start.copy()
        start[6:8, 8:10] = np.nan
        found = ceiling((self.zone,), start, small_grid())
        seeds = np.where(small_zone() & np.isfinite(start), start, np.inf)
        by_hand = oracles.brute_force_euclidean(seeds, math.tan(math.radians(SLOPE_DEG)), STEP)
        self.assertLessEqual(float(np.abs(found.grid - by_hand).max()), TOLERANCE_M)
        self.assertEqual(found.nodata_cells, (4,))
        self.assertEqual(found.notices, (messages.render("des.conserve_nodata", zone="Ladera",
                                                         area=16.0),))

    def test_zone_without_terrain_sets_no_ceiling(self) -> None:
        """Una zona sin ninguna celda con dato no siembra nada: sin techo (``+inf``), y el aviso."""
        start = self.start.copy()
        start[small_zone()] = np.nan
        found = ceiling((self.zone,), start, small_grid())
        self.assertTrue(np.isposinf(found.grid).all())
        self.assertEqual(found.nodata_cells, (36,))

    def test_slope_is_the_parameter_without_default(self) -> None:
        """El talud es ``des.conserve.slope_deg``: sin valor (D-9) o fuera de (0; 90) se rechaza al
        llamar, nombrando la clave."""
        for value, code in ((None, "des.quarry_param_missing"), (0.0, "des.quarry_param_range"),
                            (90.0, "des.quarry_param_range")):
            with self.subTest(value=value), self.assertRaises(messages.DesignError) as caught:
                quarry.conservation_ceiling_steps((self.zone,), self.start, small_grid(), value)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.field, "des.conserve.slope_deg")

    def test_wrong_shapes_are_program_errors(self) -> None:
        """Una zona o una superficie de otra forma es un error del programa al llamar."""
        wrong = quarry.ConserveZone("Ladera", np.zeros((3, 3), dtype=bool))
        with self.assertRaises(ValueError):
            quarry.conservation_ceiling_steps((wrong,), self.start, small_grid(), SLOPE_DEG)
        with self.assertRaises(ValueError):
            quarry.conservation_ceiling_steps((self.zone,), self.start[:3], small_grid(),
                                              SLOPE_DEG)


class RulesTest(unittest.TestCase):
    """RF-014-07 (spec 0.2, §5.9), A5: las tres reglas del techo."""

    def setUp(self) -> None:
        self.start = small_terrain()
        self.zone = small_zone()
        self.found = ceiling((quarry.ConserveZone("Ladera", self.zone),), self.start,
                             small_grid())

    def test_zone_keeps_the_terrain(self) -> None:
        """En ``Z`` la superficie es ``z``: una corta de 20 m no mueve nada allí."""
        cut = self.start - 20.0
        before = cut.copy()
        found = quarry.apply_ceiling(cut, self.start, self.found)
        np.testing.assert_array_equal(found[self.zone], self.start[self.zone])
        np.testing.assert_array_equal(cut, before)

    def test_terrain_above_the_ceiling_is_not_excavated(self) -> None:
        """Fuera de ``Z``, donde ``z > U`` no se excava (``KEEP``); donde ``z ≤ U``, la corta
        sigue."""
        keep = ~self.zone & (self.start > self.found.grid)
        self.assertTrue(keep.any())
        found = quarry.apply_ceiling(self.start - 20.0, self.start, self.found)
        np.testing.assert_array_equal(found[keep], self.start[keep])
        free = ~self.zone & ~keep
        np.testing.assert_array_equal(found[free], self.start[free] - 20.0)

    def test_fill_that_would_bury_the_zone_stays_under_the_ceiling(self) -> None:
        """Un relleno de 30 m que la enterraría queda por debajo de ``máx(U, z)`` (error 37) y la
        zona, con su terreno."""
        fill = self.start + 30.0
        found = quarry.apply_ceiling(fill, self.start, self.found)
        cap = np.maximum(self.found.grid, self.start)
        self.assertTrue((found <= cap).all())
        self.assertTrue((fill > cap).any())
        np.testing.assert_array_equal(found[self.zone], self.start[self.zone])
        lower = fill <= cap
        np.testing.assert_array_equal(found[lower], fill[lower])

    def test_no_data_stays_without_data(self) -> None:
        """Una celda sin dato en la superficie sigue sin dato."""
        surface = self.start - 1.0
        surface[0, 0] = np.nan
        found = quarry.apply_ceiling(surface, self.start, self.found)
        self.assertTrue(np.isnan(found[0, 0]))

    def test_shapes_must_match(self) -> None:
        """Una superficie de otra forma que el techo es un error del programa."""
        with self.assertRaises(ValueError):
            quarry.apply_ceiling(self.start[:3], self.start, self.found)


class MovedTest(unittest.TestCase):
    """RF-014-08: lo que el diseño mueve dentro de una zona a conservar es un error del diseño con
    su volumen y el centro de cada parte."""

    def setUp(self) -> None:
        self.start = small_terrain()
        self.zone = quarry.ConserveZone("Ladera", small_zone())
        self.geometry = small_grid()

    def test_two_parts_with_their_volume_and_centre(self) -> None:
        """Una corta de 2 m en 2 × 3 celdas y un relleno de 0,5 m en 1 celda, separados: dos
        partes, 2·6·4 = 48 m³ y 0,5·4 = 2 m³, con el centro absoluto de sus celdas a mano."""
        design = self.start.copy()
        design[6:8, 8:11] -= 2.0
        design[10, 12] += 0.5
        found = quarry.conserve_moved(design, self.start, (self.zone,), self.geometry,
                                      MIN_THICKNESS_M)
        self.assertTrue(found.moved)
        self.assertEqual([(part.zone, part.part, part.cells) for part in found.parts],
                         [("Ladera", 1, 6), ("Ladera", 2, 1)])
        self.assertAlmostEqual(found.parts[0].volume_m3, 48.0, delta=1e-9)
        self.assertAlmostEqual(found.parts[1].volume_m3, 2.0, delta=1e-9)
        self.assertAlmostEqual(found.volume_m3, 50.0, delta=1e-9)
        west, north = self.geometry.west, self.geometry.north
        self.assertEqual((found.parts[0].x, found.parts[0].y),
                         (west + 9.5 * STEP, north - 7.0 * STEP))
        self.assertEqual((found.parts[1].x, found.parts[1].y),
                         (west + 12.5 * STEP, north - 10.5 * STEP))
        first = found.parts[0]
        self.assertEqual(found.notices, (
            messages.render("des.conserve_moved", volume=50.0, parts=2),
            messages.render("des.conserve_part", zone="Ladera", volume=48.0,
                            x=round(first.x, 2), y=round(first.y, 2)),
            messages.render("des.conserve_part", zone="Ladera", volume=2.0,
                            x=round(found.parts[1].x, 2), y=round(found.parts[1].y, 2))))

    def test_thin_changes_and_changes_outside_do_not_count(self) -> None:
        """Bajo el espesor mínimo de la 012, o fuera de la zona, no hay error: 0 m³, sin avisos."""
        design = self.start.copy()
        design[ZONE_ROWS, ZONE_COLS] -= 0.05
        design[0:4, 0:4] -= 10.0
        found = quarry.conserve_moved(design, self.start, (self.zone,), self.geometry,
                                      MIN_THICKNESS_M)
        self.assertFalse(found.moved)
        self.assertEqual(found.volume_m3, 0.0)
        self.assertEqual(found.notices, ())


class ConserveQuarryTest(unittest.TestCase):
    """CE-014-02 (error 37) sobre la cantera sintética: una corta junto a la ladera a conservar
    mueve 0 m³ en ella y el techo coincide con el cálculo a mano a ≤ 10⁻⁹ m."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.start = qfx.terrain()
        cls.zone_mask = qfx.in_box(qfx.CONSERVE_LOCAL)
        cls.zone = quarry.ConserveZone("Ladera a conservar", cls.zone_mask)
        cls.found = ceiling((cls.zone,), cls.start, qfx.GRID)

    def test_ceiling_against_the_hand_calculation(self) -> None:
        """En la zona (la ladera es un plano de pendiente 0,258 < tan 35°) el techo es el terreno;
        fuera, en puntos de los cuatro lados y de las esquinas, ``mín_q [z(q) + t·|p − q|]`` por
        fuerza bruta sobre las 2.400 celdas de la zona, a ≤ 10⁻⁹ m."""
        self.assertEqual(int(self.zone_mask.sum()), 2_400)
        inside = self.zone_mask
        self.assertLessEqual(float(np.abs(self.found.grid[inside] - self.start[inside]).max()),
                             TOLERANCE_M)
        tan = math.tan(math.radians(SLOPE_DEG))
        rows, cols = np.nonzero(inside)
        levels = self.start[inside]
        for row, col in ((150, 80), (230, 80), (200, 50), (200, 110), (150, 50), (240, 115),
                         (0, 0), (399, 399), (210, 60)):
            with self.subTest(row=row, col=col):
                by_hand = float((levels + tan * qfx.STEP_M * np.hypot(rows - row, cols - col))
                                .min())
                self.assertLessEqual(abs(float(self.found.grid[row, col]) - by_hand),
                                     TOLERANCE_M)

    def test_cut_beside_the_zone_moves_nothing_in_it(self) -> None:
        """Una corta de 30 m en toda la cantera, con el techo, mueve 0 m³ en la zona, y un relleno
        de 30 m no la entierra (queda por debajo del techo)."""
        cut = quarry.apply_ceiling(self.start - 30.0, self.start, self.found)
        moved = quarry.conserve_moved(cut, self.start, (self.zone,), qfx.GRID, MIN_THICKNESS_M)
        self.assertFalse(moved.moved)
        self.assertEqual(moved.volume_m3, 0.0)
        self.assertTrue((cut < self.start).any())
        fill = quarry.apply_ceiling(self.start + 30.0, self.start, self.found)
        self.assertTrue((fill <= np.maximum(self.found.grid, self.start)).all())
        np.testing.assert_array_equal(fill[self.zone_mask], self.start[self.zone_mask])
        # Sin el techo, la misma corta movería 30 m en las 2.400 celdas de la zona: 72.000 m³.
        raw = quarry.conserve_moved(self.start - 30.0, self.start, (self.zone,), qfx.GRID,
                                    MIN_THICKNESS_M)
        self.assertAlmostEqual(raw.volume_m3, 72_000.0, delta=1e-6)
        self.assertEqual(len(raw.parts), 1)


if __name__ == "__main__":
    unittest.main()
