# SPDX-License-Identifier: GPL-3.0-or-later
"""Los fondos de la cantera (spec 014, T08; HU-014-2; RF-014-05, RF-014-06; plan 014 A4, §5.3.1).

- ``design.quarry.floor_map``: el **mapa de cotas de fondo** de una capa de polígonos con su campo
  de cota (cada celda con el centro dentro de un polígono, su cota; ``NaN`` fuera), y sus
  rechazos (RF-014-06): dos polígonos que se solapan (``des.floor_overlap``), un polígono sin cota
  o con una cota fuera de las del terreno ± 1.000 m (``des.floor_level``), un campo que la capa no
  tiene o que no es numérico (``des.quarry_layer_field``) y una capa que no es de polígonos
  (``des.layer_not_polygons``), nombrando la capa, el polígono, el campo y el valor.
- ``design.quarry.floors_above_terrain``: el área de los fondos por encima del terreno, que se
  admite y se informa (``des.floor_above_terrain``).
- ``design.quarry.with_floors`` y ``design.quarry.floor_cut_steps``: la corta ``máx(ENV↓(s),
  ENV↓(F))`` sobre la envolvente de la 013 (``zdes = máx(BASE0, ZF)`` de la V7), a ≤ 10⁻⁹ m del
  cálculo a mano (la euclídea exacta por fuerza bruta de cada parte y su máximo) con dos fondos.

Sobre la cantera sintética de ``tests.support.quarry_fixtures`` (T01), sin proyecto (la capa se
arma como la escribe ``write_feature_layer``), y sobre una rejilla pequeña de 2 m para la corta.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
envelopes = import_geoblender("design.envelopes")
seeds_mod = import_geoblender("design.seeds")
messages = import_geoblender("design.messages")
vector = import_geoblender("gis.vector")

TOLERANCE_M = 1e-9
SOURCE = model.LayerField(qfx.FLOORS_LAYER, "cota")
HIGH_BOX = (60.0, 100.0, 80.0, 110.0)
"""Un fondo de 20 × 10 m a 300 m donde el terreno no pasa de 212,34 m: 200 celdas por encima."""
HIGH_LEVEL = 300.0


def floor_layer(boxes: tuple[tuple[float, float, float, float], ...],
                levels: tuple[Any, ...], *, kind: str = "polygon",
                columns: tuple[tuple[str, str], ...] = (("cota", "DOUBLE"),)) -> Any:
    """Una capa de entidades (``FeatureLayer``) con un rectángulo local por entidad (fids 1…n),
    el campo ``nombre`` y los campos de ``columns`` con los valores ``levels`` (el mismo en cada
    uno), como la escribe ``quarry_fixtures.write_feature_layer``."""
    parts = tuple(((cfx.rectangle(*box),),) for box in boxes)
    fields = (vector.FieldColumn("nombre", "nombre", "TEXT"),
              *(vector.FieldColumn(name, name, sql_type) for name, sql_type in columns))
    values = {"nombre": tuple(f"Fondo {index}" for index in range(1, len(boxes) + 1)),
              **{name: tuple(levels) for name, _ in columns}}
    return vector.FeatureLayer(kind, tuple(range(1, len(boxes) + 1)), parts, fields, values)


def fixture_layer(*extra: tuple[tuple[float, float, float, float], Any]) -> Any:
    """La capa de los dos fondos de la cantera (:data:`qfx.FLOORS`) y los ``extra`` (caja local y
    cota) detrás."""
    boxes = tuple(item.box for item in qfx.FLOORS) + tuple(box for box, _ in extra)
    levels = tuple(item.level_m for item in qfx.FLOORS) + tuple(level for _, level in extra)
    return floor_layer(boxes, levels)


class FloorMapTest(unittest.TestCase):
    """RF-014-05, A4: el mapa de cotas de fondo de la cantera."""

    def setUp(self) -> None:
        self.start = qfx.terrain()

    def test_each_cell_inside_a_polygon_takes_its_level(self) -> None:
        """Cada celda con el centro dentro de un fondo lleva su cota (125 m en 80 × 80 m y 175 m en
        80 × 60 m, a mano: 6.400 y 4.800 celdas) y las demás, ``NaN``."""
        found = quarry.floor_map(fixture_layer(), SOURCE, self.start, qfx.GRID)
        first, second = (qfx.in_box(item.box) for item in qfx.FLOORS)
        expected = np.where(first, 125.0, np.where(second, 175.0, np.nan))
        self.assertEqual(found.grid.dtype, np.float64)
        np.testing.assert_array_equal(found.grid, expected)
        self.assertEqual(found.layer, qfx.FLOORS_LAYER)
        self.assertEqual(found.field, "cota")
        self.assertEqual(found.fids, (1, 2))
        self.assertEqual(found.levels, (125.0, 175.0))
        self.assertEqual(found.cells, (6400, 4800))
        self.assertEqual(int(np.count_nonzero(found.owner == 1)), 6400)
        self.assertEqual(int(np.count_nonzero(found.owner == 2)), 4800)
        self.assertEqual(int(np.count_nonzero(found.owner)), 6400 + 4800)
        self.assertEqual(found.area_m2, 6400.0 + 4800.0)

    def test_inputs_are_not_modified(self) -> None:
        """Regla 6: ni la capa ni el terreno cambian."""
        layer = fixture_layer()
        rings = [ring.copy() for entity in layer.parts for part in entity for ring in part]
        start = self.start.copy()
        quarry.floor_map(layer, SOURCE, self.start, qfx.GRID)
        np.testing.assert_array_equal(self.start, start)
        after = [ring for entity in layer.parts for part in entity for ring in part]
        for before, now in zip(rings, after, strict=True):
            np.testing.assert_array_equal(before, now)
        self.assertEqual(layer.values["cota"], (125.0, 175.0))

    def test_a_floor_above_the_terrain_is_admitted_and_reported(self) -> None:
        """RF-014-05 (tabla de errores: se admite): un fondo de 20 × 10 m a 300 m donde el terreno
        no pasa de 180 + 27,375 + 4,96875 m queda entero por encima: 200 celdas, 200 m²,
        informado; los dos de la cantera, por debajo, no informan nada."""
        found = quarry.floor_map(fixture_layer((HIGH_BOX, HIGH_LEVEL)), SOURCE, self.start,
                                 qfx.GRID)
        np.testing.assert_array_equal(found.grid[qfx.in_box(HIGH_BOX)], HIGH_LEVEL)
        above = quarry.floors_above_terrain(found, self.start)
        self.assertEqual(above.cells, 200)
        self.assertEqual(above.area_m2, 200.0)
        self.assertEqual(above.notice, messages.render("des.floor_above_terrain", area=200.0))
        self.assertIn("200 m² de los fondos quedan por encima del terreno", above.notice)
        below = quarry.floors_above_terrain(
            quarry.floor_map(fixture_layer(), SOURCE, self.start, qfx.GRID), self.start)
        self.assertEqual((below.cells, below.area_m2, below.notice), (0, 0.0, None))

    def test_levels_at_the_limits_of_the_terrain_are_admitted(self) -> None:
        """RF-014-06: «fuera de las cotas del terreno ± 1.000 m»; justo en el borde, se admite."""
        low = qfx.TERRAIN_MIN_M - 1000.0
        high = qfx.TERRAIN_MAX_M + 1000.0
        found = quarry.floor_map(floor_layer(tuple(item.box for item in qfx.FLOORS),
                                             (low, high)), SOURCE, self.start, qfx.GRID)
        self.assertEqual(found.levels, (low, high))


class FloorRejectionTest(unittest.TestCase):
    """RF-014-06: los rechazos nombran la capa, el polígono, el campo y el valor, y no eligen cota."""

    def setUp(self) -> None:
        self.start = qfx.terrain()

    def rejected(self, layer: Any, source: Any = SOURCE) -> Any:
        with self.assertRaises(messages.DesignError) as caught:
            quarry.floor_map(layer, source, self.start, qfx.GRID)
        return caught.exception

    def test_overlapping_polygons(self) -> None:
        """Un tercer fondo de (180, 180) a (210, 190) pisa el de 125 m en 20 × 10 celdas (a mano):
        ``des.floor_overlap`` con los dos polígonos (1 y 3) y las celdas comunes."""
        error = self.rejected(fixture_layer(((180.0, 180.0, 210.0, 190.0), 130.0)))
        self.assertEqual(error.code, "des.floor_overlap")
        self.assertEqual(error.values["layer"], qfx.FLOORS_LAYER)
        self.assertEqual((error.values["value"], error.values["other"]), (1, 3))
        self.assertEqual(error.values["cells"], 200)
        self.assertIn(f"Capa «{qfx.FLOORS_LAYER}»: los polígonos de fondo 1 y 3 se solapan en "
                      "200 celdas", error.text)

    def test_a_polygon_without_level(self) -> None:
        """Una cota vacía (NULL) o no finita: ``des.floor_level`` con el polígono y el campo."""
        for level, shown in ((None, "—"), (math.nan, "nan"), (math.inf, "inf")):
            with self.subTest(level=level):
                error = self.rejected(fixture_layer((HIGH_BOX, level)))
                self.assertEqual(error.code, "des.floor_level")
                self.assertEqual(error.values["layer"], qfx.FLOORS_LAYER)
                self.assertEqual(error.values["polygon"], 3)
                self.assertEqual(error.values["field"], "cota")
                self.assertIn(f"Capa «{qfx.FLOORS_LAYER}», polígono 3: «cota» = {shown} falta",
                              error.text)

    def test_a_level_outside_the_terrain_plus_minus_1000_m(self) -> None:
        """Una cota por debajo de la mínima del terreno − 1.000 m o por encima de la máxima + 1.000
        m (de −819,84375 a 1.307,84375 m, a mano): ``des.floor_level`` con el rango."""
        for level in (qfx.TERRAIN_MIN_M - 1000.5, qfx.TERRAIN_MAX_M + 1000.5, -900.0, 1400.0):
            with self.subTest(level=level):
                error = self.rejected(fixture_layer((HIGH_BOX, level)))
                self.assertEqual(error.code, "des.floor_level")
                self.assertEqual(error.values["value"], level)
                self.assertEqual(error.values["polygon"], 3)
                self.assertEqual(error.values["low"], -819.84375)
                self.assertEqual(error.values["high"], 1307.84375)
                self.assertIn("(de -819,84375 a 1307,84375 m)", error.text)

    def test_a_field_the_layer_does_not_have_or_is_not_numeric(self) -> None:
        """``des.quarry_layer_field`` con el campo pedido y los numéricos de la capa."""
        for name in ("altura", "nombre"):
            with self.subTest(field=name):
                error = self.rejected(fixture_layer(), model.LayerField(qfx.FLOORS_LAYER, name))
                self.assertEqual(error.code, "des.quarry_layer_field")
                self.assertEqual(error.values["value"], name)
                self.assertEqual(error.values["fields"], "cota")

    def test_a_layer_that_is_not_of_polygons(self) -> None:
        """Una capa de líneas no da fondos: ``des.layer_not_polygons``."""
        lines = vector.FeatureLayer(
            "line", (1,), (((cfx.absolute(qfx.CORRIDOR_AXIS_LOCAL),),),),
            (vector.FieldColumn("cota", "cota", "DOUBLE"),), {"cota": (125.0,)})
        error = self.rejected(lines)
        self.assertEqual(error.code, "des.layer_not_polygons")
        self.assertEqual(error.values["layer"], qfx.FLOORS_LAYER)

    def test_a_terrain_of_another_grid_is_a_program_error(self) -> None:
        with self.assertRaises(ValueError):
            quarry.floor_map(fixture_layer(), SOURCE, self.start[:-1], qfx.GRID)


# --- La corta máx(ENV↓(s), ENV↓(F)) (A4) ----------------------------------------------------------

ROWS, COLS, STEP = 20, 24, 2.0
"""La rejilla pequeña de la corta: 20 × 24 celdas de 2 m (48 × 40 m locales)."""
FLOOR_A = ((8.0, 8.0, 20.0, 20.0), 240.0)
FLOOR_B = ((28.0, 16.0, 40.0, 32.0), 294.0)
"""Una plataforma a 294 m (el terreno, de 298,75 m arriba): más alta que la corta de las semillas en
parte de sus celdas, así que la sostiene una pared."""
SLOPE_DEG = 50.0


def small_grid() -> Any:
    return dfx.grid_from(ROWS, COLS, STEP)


def small_terrain() -> np.ndarray:
    """``280 + 0,5·x + 0,25·y`` (m) en los centros locales de la rejilla pequeña."""
    columns = (np.arange(COLS) + 0.5) * STEP
    rows = ROWS * STEP - (np.arange(ROWS) + 0.5) * STEP
    x, y = np.meshgrid(columns, rows)
    return 280.0 + 0.5 * x + 0.25 * y


def border_seeds(start: np.ndarray) -> Any:
    """Las semillas en el borde de la rejilla pequeña (la «coronación»), con el terreno; dominio,
    toda la rejilla."""
    ring = np.ones(start.shape, dtype=bool)
    ring[1:-1, 1:-1] = False
    geometry = small_grid()
    domain = seeds_mod.domain_of(np.ones(start.shape, dtype=bool),
                                 np.zeros(start.shape, dtype=np.int16), (), geometry.cell_area)
    return seeds_mod.collect_seeds(start, ring, domain, geometry)


def request(metric: str = "exact", direction: str = "down") -> Any:
    return model.EnvelopeRequest("Corta E1", direction,
                                 model.SeedSource(model.SeedKind.SURFACE, surface="terreno"),
                                 slope_deg=SLOPE_DEG, metric=metric)


def finish(steps: Any) -> Any:
    return list(steps)[-1].result


class FloorCutTest(unittest.TestCase):
    """RF-014-05, A4: la corta es ``máx(ENV↓(s), ENV↓(F))`` sobre la envolvente de la 013."""

    def setUp(self) -> None:
        self.start = small_terrain()
        self.seeds = border_seeds(self.start)
        layer = floor_layer((FLOOR_A[0], FLOOR_B[0]), (FLOOR_A[1], FLOOR_B[1]))
        self.floors = quarry.floor_map(layer, SOURCE, self.start, small_grid())
        self.slope = envelopes.constant_slope(SLOPE_DEG)

    def test_two_floors_against_the_hand_calculation(self) -> None:
        """Con dos fondos (240 m en 6 × 6 celdas y una plataforma a 294 m en 6 × 8), la euclídea
        exacta queda a ≤ 10⁻⁹ m del máximo de las dos envolventes por fuerza bruta: la de las
        semillas y la de los fondos."""
        self.assertEqual(self.floors.cells, (36, 48))
        found = finish(quarry.floor_cut_steps(request(), self.seeds, self.floors, self.slope))
        tan = math.tan(math.radians(SLOPE_DEG))
        from_seeds = oracles.brute_force_euclidean(self.seeds.grid, tan, STEP, direction="down")
        floors = np.where(np.isfinite(self.floors.grid), self.floors.grid, np.inf)
        from_floors = oracles.brute_force_euclidean(floors, tan, STEP, direction="down")
        by_hand = np.maximum(from_seeds, from_floors)
        self.assertLessEqual(float(np.abs(found.grid - by_hand).max()), TOLERANCE_M)
        # Los fondos mandan donde están (más altos que la corta de las semillas) …
        inside = np.isfinite(self.floors.grid)
        self.assertTrue((by_hand[inside] >= self.floors.grid[inside]).all())
        self.assertTrue((from_floors > from_seeds).any())
        # … y alrededor de ellos, la pared que los sostiene.
        self.assertTrue(((from_floors > from_seeds) & ~inside).any())

    def test_chamfer_is_the_maximum_of_the_two_envelopes(self) -> None:
        """Con el *chamfer* 5×5, la corta es el máximo de las dos envolventes de la 013 calculadas
        por separado, a ≤ 10⁻⁹ m."""
        found = finish(quarry.floor_cut_steps(request("chamfer5"), self.seeds, self.floors,
                                              self.slope))
        geometry = small_grid()
        alone = finish(envelopes.chamfer_steps(self.seeds.grid, geometry, self.slope, "down"))
        floors = np.where(np.isfinite(self.floors.grid), self.floors.grid, np.inf)
        of_floors = finish(envelopes.chamfer_steps(floors, geometry, self.slope, "down"))
        expected = np.maximum(alone.grid, of_floors.grid)
        self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)

    def test_with_floors_joins_the_seeds(self) -> None:
        """Las semillas de la corta: las de ``s`` y las celdas de los fondos con su cota (el
        máximo de las dos donde coinciden); las entradas no cambian."""
        before = self.seeds.grid.copy()
        joined = quarry.with_floors(self.seeds, self.floors)
        np.testing.assert_array_equal(self.seeds.grid, before)
        inside = np.isfinite(self.floors.grid)
        np.testing.assert_array_equal(joined.grid[inside], self.floors.grid[inside])
        np.testing.assert_array_equal(joined.grid[~inside], before[~inside])
        self.assertEqual(joined.cells, self.seeds.cells + 36 + 48)
        self.assertEqual(joined.area_m2, joined.cells * STEP * STEP)
        self.assertEqual(joined.min_m, 240.0)
        # Un fondo sobre una semilla se queda con la más alta de las dos.
        crowded = seeds_mod.collect_seeds(np.full(self.start.shape, 250.0), None,
                                          self.seeds.domain, small_grid())
        both = quarry.with_floors(crowded, self.floors)
        self.assertEqual(float(both.grid[np.isfinite(self.floors.grid)].min()), 250.0)
        self.assertEqual(float(both.grid.max()), 294.0)
        self.assertEqual(both.cells, ROWS * COLS)

    def test_the_cut_goes_down(self) -> None:
        """La corta es descendente: pedirla hacia arriba es un error del programa."""
        with self.assertRaises(ValueError):
            quarry.floor_cut_steps(request(direction="up"), self.seeds, self.floors, self.slope)


if __name__ == "__main__":
    unittest.main()
