# SPDX-License-Identifier: GPL-3.0-or-later
"""El ancla al fondo de cada muro (spec 014, T11; HU-014-2; RF-014-11; plan 014 A7, §5.3.1).

- ``design.quarry.floor_anchor_steps``: la **rejilla de anclas** de un mapa de fondos, en la que
  cada celda lleva la cota del fondo más próximo en planta (distancia euclídea entre centros de
  celda; a igual distancia, la cota más baja), comprobada celda a celda contra la distancia a mano a
  las cajas de los dos fondos de la cantera sintética (``tests.support.quarry_fixtures``).
- ``design.quarry.anchored_request``: su paso al escalonado de la 013 como ancla en rejilla (D-18 de
  la 013): con dos fondos, las bermas de cada muro quedan en ``fondo + k·h`` a ≤ 10⁻⁹ m; con el ancla
  del perfil, no. Sin ningún fondo, la rejilla no tiene cota y el escalonado la rechaza
  (``des.anchor_nodata``) nombrando el ancla.
"""

from __future__ import annotations

import math
import types
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
pipeline = import_geoblender("design.pipeline")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")

TOLERANCE_M = 1e-9
SOURCE = model.LayerField(qfx.FLOORS_LAYER, "cota")
EXPL = "expl_10_60_6"
HEIGHT_M = 10.0
PROFILE_ANCHOR_M = 125.0


def last_result(steps: Any) -> Any:
    found = None
    for found in steps:
        pass
    return found.result


def floor_map_of(levels: np.ndarray, *, layer: str = qfx.FLOORS_LAYER) -> Any:
    """Un ``FloorMap`` de la rejilla ``levels`` (la cota en cada celda de fondo, ``NaN`` fuera): un
    solo polígono por cota distinta, en orden creciente."""
    distinct = sorted({float(value) for value in levels[np.isfinite(levels)]})
    owner = np.zeros(levels.shape, dtype=np.int32)
    for index, value in enumerate(distinct, start=1):
        owner[levels == value] = index
    cells = tuple(int(np.count_nonzero(owner == index))
                  for index in range(1, len(distinct) + 1))
    return quarry.FloorMap(layer, "cota", np.array(levels, dtype=np.float64), owner,
                           tuple(range(1, len(distinct) + 1)), tuple(distinct), cells, 1.0)


class FloorAnchorGridTest(unittest.TestCase):
    """RF-014-11, A7: la rejilla de anclas de los dos fondos de la cantera, celda a celda."""

    @classmethod
    def setUpClass(cls) -> None:
        grid = np.full(qfx.GRID.shape, np.nan)
        for item in qfx.FLOORS:
            grid[qfx.in_box(item.box)] = item.level_m
        cls.floors = floor_map_of(grid)
        cls.anchors = last_result(quarry.floor_anchor_steps(cls.floors, qfx.GRID))

    def test_each_cell_takes_the_level_of_the_nearest_floor_lowest_on_a_tie(self) -> None:
        """Cada celda lleva la cota del fondo cuyo centro de celda más próximo está a menor
        distancia (a mano: la distancia de su centro a la caja de los centros de cada fondo); donde
        las dos distancias son iguales, la más baja (125 m). La cantera tiene empates."""
        x, y = qfx.local_centers()
        d2 = []
        for item in qfx.FLOORS:
            left, bottom, right, top = item.box
            dx = np.maximum(np.maximum((left + 0.5) - x, x - (right - 0.5)), 0.0)
            dy = np.maximum(np.maximum((bottom + 0.5) - y, y - (top - 0.5)), 0.0)
            d2.append(dx * dx + dy * dy)
        low, high = (item.level_m for item in qfx.FLOORS)
        self.assertLess(low, high)
        expected = np.where(d2[1] < d2[0], high, low)
        self.assertGreater(int(np.count_nonzero(d2[0] == d2[1])), 0)
        self.assertEqual(self.anchors.grid.dtype, np.float64)
        np.testing.assert_array_equal(self.anchors.grid, expected)
        np.testing.assert_array_equal(self.anchors.d2_m2, np.minimum(d2[0], d2[1]))
        self.assertEqual(self.anchors.layer, qfx.FLOORS_LAYER)

    def test_the_floor_cells_keep_their_own_level(self) -> None:
        """En un fondo, el más próximo es él mismo (distancia 0)."""
        inside = np.isfinite(self.floors.grid)
        np.testing.assert_array_equal(self.anchors.grid[inside], self.floors.grid[inside])

    def test_the_inputs_are_not_modified_and_the_grid_must_match(self) -> None:
        """Ninguna entrada se modifica; un mapa de otra rejilla es un error del programa."""
        before = self.floors.grid.copy()
        last_result(quarry.floor_anchor_steps(self.floors, qfx.GRID))
        np.testing.assert_array_equal(self.floors.grid, before)
        with self.assertRaises(ValueError):
            quarry.floor_anchor_steps(self.floors, dfx.grid_from(10, 10, 1.0))


class FloorAnchorBenchingTest(unittest.TestCase):
    """RF-014-11, D-18 de la 013: la rejilla de anclas en el escalonado de la 013."""

    SHAPE = (40, 100)
    START_M = 160.0
    LEFT = (slice(10, 30), slice(5, 25))
    RIGHT = (slice(10, 30), slice(70, 90))
    LEFT_M = 100.0
    RIGHT_M = 117.0
    """Dos fondos que no están a un número entero de bancos el uno del otro ni del ancla del
    perfil (125 m): con ella, las bermas de los muros no caerían en ``fondo + k·h``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry = dfx.grid_from(*cls.SHAPE, 1.0)
        levels = np.full(cls.SHAPE, np.nan)
        levels[cls.LEFT] = cls.LEFT_M
        levels[cls.RIGHT] = cls.RIGHT_M
        cls.floors = floor_map_of(levels)
        values: dict[str, object] = {}
        for param, value in (("height_m", HEIGHT_M), ("face_deg", 60.0), ("berm_m", 6.0),
                             ("anchor_m", PROFILE_ANCHOR_M), ("mesh_factor", 1.0)):
            values[params.bench_key(EXPL, param)] = value
        cls.profiles = pipeline.bench_profiles(values, [EXPL])
        general = cls.profiles[EXPL].general_tan
        rows, cols = np.indices(cls.SHAPE)
        walls = []
        for box, level in ((cls.LEFT, cls.LEFT_M), (cls.RIGHT, cls.RIGHT_M)):
            dr = np.maximum(np.maximum(box[0].start - rows, rows - (box[0].stop - 1)), 0)
            dc = np.maximum(np.maximum(box[1].start - cols, cols - (box[1].stop - 1)), 0)
            walls.append(level + general * np.hypot(dr, dc))
        # Una corta que sube desde cada fondo con el talud general del perfil, hasta el terreno.
        cls.envelope = np.minimum(np.minimum(walls[0], walls[1]), cls.START_M)
        cls.request = model.DesignRequest("Bancos", "Corta", "cut", EXPL)

    def job(self, request: Any, anchors: np.ndarray | None) -> Any:
        everything = np.ones(self.SHAPE, dtype=bool)
        masks = types.SimpleNamespace(cut_allowed=lambda: everything.copy(),
                                      fill_allowed=lambda: everything.copy(),
                                      fill_strip=lambda: np.zeros(self.SHAPE, dtype=bool))
        return pipeline.DesignJob(
            request=request, geometry=self.geometry, start=np.full(self.SHAPE, self.START_M),
            envelope=self.envelope, masks=masks, sectors=(),
            labels=np.zeros(self.SHAPE, dtype=np.int16), imposed={}, profiles=self.profiles,
            anchors=anchors, min_thickness_m=0.02, face_tolerance_deg=1.0, warning_ratio=2.0)

    def bench_levels(self, anchors: Any) -> tuple[np.ndarray, np.ndarray]:
        """Las cotas de las bermas medidas y la cota de su fondo más próximo, celda a celda."""
        request = quarry.anchored_request(self.request, anchors)
        outcome = last_result(pipeline.design_compute_steps(self.job(request, anchors.grid)))
        berm = np.isfinite(outcome.berms.grid)
        return outcome.berms.grid[berm], anchors.grid[berm]

    def test_the_berms_of_each_wall_are_at_its_floor_plus_k_benches(self) -> None:
        """Con dos fondos (100 y 117 m), cada berma queda en la cota de su fondo más ``k`` veces la
        altura del banco (10 m), a ≤ 10⁻⁹ m, y hay bermas de los dos muros por encima del fondo."""
        anchors = last_result(quarry.floor_anchor_steps(self.floors, self.geometry))
        self.assertEqual(anchors.label, f"al fondo de cada muro, capa {qfx.FLOORS_LAYER}")
        levels, floor = self.bench_levels(anchors)
        self.assertGreater(levels.size, 0)
        k = np.round((levels - floor) / HEIGHT_M)
        self.assertTrue(bool(np.all(k >= 0)))
        self.assertLessEqual(float(np.max(np.abs(levels - (floor + k * HEIGHT_M)))), TOLERANCE_M)
        for level in (self.LEFT_M, self.RIGHT_M):
            self.assertTrue(bool(np.any((floor == level) & (k >= 1))), level)

    def test_with_the_profile_anchor_the_walls_miss_their_floors(self) -> None:
        """El contraste: con el ancla del perfil (125 m), ninguna berma del muro de 117 m queda en
        ``117 + k·10``."""
        anchors = last_result(quarry.floor_anchor_steps(self.floors, self.geometry))
        outcome = last_result(pipeline.design_compute_steps(self.job(self.request, None)))
        berm = np.isfinite(outcome.berms.grid) & (anchors.grid == self.RIGHT_M)
        offset = np.mod(outcome.berms.grid[berm] - self.RIGHT_M, HEIGHT_M)
        self.assertGreater(offset.size, 0)
        self.assertTrue(bool(np.all(np.abs(offset - 8.0) <= 1e-6)))

    def test_without_floors_the_benching_refuses_the_anchor(self) -> None:
        """Sin ninguna celda de fondo no hay ancla: la rejilla es ``NaN`` y el escalonado la
        rechaza (``des.anchor_nodata``) con su nombre y las celdas del dominio."""
        empty = floor_map_of(np.full(self.SHAPE, np.nan))
        anchors = last_result(quarry.floor_anchor_steps(empty, self.geometry))
        self.assertTrue(bool(np.isnan(anchors.grid).all()))
        self.assertTrue(bool(np.isinf(anchors.d2_m2).all()))
        request = quarry.anchored_request(self.request, anchors)
        with self.assertRaises(messages.DesignError) as caught:
            last_result(pipeline.design_compute_steps(self.job(request, anchors.grid)))
        self.assertEqual(caught.exception.code, "des.anchor_nodata")
        self.assertIn(anchors.label, str(caught.exception))
        self.assertIn(str(math.prod(self.SHAPE)), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
