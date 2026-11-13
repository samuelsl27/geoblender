# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera sintética de la 014 (spec 014, T01; plan 014 §7.1; hito H2).

Recorre ``tests.support.quarry_fixtures`` antes de que la usen las pruebas del núcleo (que aún no
existe), con cuentas a mano: la rejilla de 400 × 400 celdas de 1 m, el terreno de ladera con su
escarpe previo de 3 m, las restricciones y sus máscaras (recinto, franja, torre con 8 m y «sin
corte»), los dos sectores con su búsqueda vigente, las cinco capas (dos fondos, la zona a
conservar, el corredor de 200 × 20 m, el relleno y la lámina) leídas del proyecto con
``gis.store.read_features``, los dos perfiles y que la plantilla se construye en ≤ 2 s de CPU. Y
que los nombres de la 013 y la 012 en los que se apoya el plan 014 (§5.3) siguen ahí.

Ningún dato de cliente: todo es sintético.
"""

from __future__ import annotations

import math
import time
import unittest

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
access = import_geoblender("gis.masks.access")
gis_store = import_geoblender("gis.store")

COPY_BUDGET_S = 1.0
"""Una copia del proyecto por clase, en menos de 1 s de CPU."""


class SiteTest(unittest.TestCase):
    """La rejilla, el terreno y la geometría, sin proyecto."""

    def test_grid(self) -> None:
        """400 × 400 celdas de 1 m desde la esquina de los casos, en EPSG:25830 + 5782."""
        self.assertEqual(qfx.GRID.shape, (400, 400))
        self.assertEqual((qfx.GRID.dx, qfx.GRID.dy), (1.0, 1.0))
        self.assertEqual((qfx.GRID.west, qfx.GRID.north), (cfx.BASE[0], cfx.BASE[1] + 400.0))
        raster = qfx.start_raster()
        self.assertEqual((raster.crs.epsg, raster.vertical.epsg), (25830, 5782))

    def test_coarse_grid(self) -> None:
        """La rejilla gruesa (T35; plan 014 §7.4, las unitarias en ≤ 200 × 200): 200 × 200 celdas
        de 2 m con la extensión de :data:`GRID`; con el paso de 1 m, la misma ``GRID``. Su terreno
        es la ladera en sus centros: la media exacta de los cuatro de 1 m de cada celda (el
        escarpe de y = 300 cae en un borde de celda de 2 m); sus cajas, las de 2 m."""
        coarse = qfx.grid_of(qfx.COARSE_STEP_M)
        self.assertIs(qfx.grid_of(), qfx.GRID)
        self.assertEqual(coarse.shape, (200, 200))
        self.assertEqual((coarse.dx, coarse.dy), (2.0, 2.0))
        self.assertEqual(coarse.extent, qfx.GRID.extent)
        with self.assertRaises(ValueError):
            qfx.grid_of(3.0)
        z = qfx.terrain(coarse)
        np.testing.assert_array_equal(z, qfx.terrain().reshape(200, 2, 200, 2).mean(axis=(1, 3)))
        self.assertEqual(float(z[-1, 0]), 180.0 + 0.25 + 0.0625)  # el centro (1, 1)
        raster = qfx.start_raster(coarse)
        self.assertEqual(raster.grid, coarse)
        np.testing.assert_array_equal(raster.values, z)
        self.assertEqual(int(qfx.in_box(qfx.FILL_ZONE_LOCAL, coarse).sum()), 3_000 // 4)

    def test_terrain_by_hand(self) -> None:
        """La ladera ``180 + 0,25·y + 0,0625·x`` con el escarpe de 3 m al norte de y = 300:
        mínimo y máximo a mano, exactos en binario; el salto entre las filas a los lados del
        escarpe es 0,25 + 3 m; un array nuevo cada vez."""
        z = qfx.terrain()
        self.assertEqual(z.dtype, np.float64)
        self.assertEqual(float(z.min()), qfx.TERRAIN_MIN_M)
        self.assertEqual(float(z.max()), qfx.TERRAIN_MAX_M)
        self.assertEqual(float(z[-1, 0]), qfx.TERRAIN_MIN_M)
        self.assertEqual(float(z[0, -1]), qfx.TERRAIN_MAX_M)
        north_row = 400 - 301  # el centro y = 300,5
        steps = z[north_row, :] - z[north_row + 1, :]
        self.assertTrue(np.all(steps == qfx.TERRAIN_NORTH + qfx.SCARP_M))
        self.assertTrue(np.all(np.diff(z[:north_row + 1, 7]) == -qfx.TERRAIN_NORTH))
        self.assertTrue(np.all(np.diff(z[north_row + 1:, 7]) == -qfx.TERRAIN_NORTH))
        self.assertTrue(np.all(np.diff(z[200, :]) == qfx.TERRAIN_EAST))
        z[0, 0] = 0.0
        self.assertNotEqual(float(qfx.terrain()[0, 0]), 0.0)

    def test_areas_by_hand(self) -> None:
        """Las áreas de las docstrings con las celdas de cada caja (m², celdas de 1 m²)."""
        legal, perimeter = qfx.in_box(qfx.LEGAL_LOCAL), qfx.in_box(qfx.PERIMETER_LOCAL)
        self.assertEqual(int(legal.sum()), qfx.LEGAL_AREA_M2)
        self.assertEqual(int(perimeter.sum()), qfx.PERIMETER_AREA_M2)
        self.assertEqual(int((legal & perimeter).sum()), qfx.INTERSECTION_M2)
        self.assertEqual(int((perimeter & ~legal).sum()), qfx.STRIP_M2)
        left, bottom, right, top = qfx.LEGAL_LOCAL
        inner = qfx.in_box((left + qfx.LEGAL_INWARD_M, bottom + qfx.LEGAL_INWARD_M,
                            right - qfx.LEGAL_INWARD_M, top - qfx.LEGAL_INWARD_M))
        self.assertEqual(int((legal & perimeter & ~inner).sum()), qfx.INWARD_BAND_M2)
        self.assertEqual(int(qfx.in_box(qfx.NO_CUT_LOCAL).sum()), qfx.NO_CUT_CELLS)
        for floor, area in zip(qfx.FLOORS, (6_400.0, 4_800.0), strict=True):
            self.assertEqual(floor.area_m2, area)
            self.assertEqual(int(qfx.in_box(floor.box).sum()), area)
        self.assertEqual(int(qfx.in_box(qfx.CONSERVE_LOCAL).sum()), 2_400)
        self.assertEqual(int(qfx.in_box(qfx.FILL_ZONE_LOCAL).sum()), 3_000)
        self.assertEqual(int(qfx.in_box(qfx.WATER_LOCAL).sum()), 1_200)

    def test_tower_zone_by_hand(self) -> None:
        """Las celdas que tocan el disco abierto de 8 m de la torre: 224 (56 por cuadrante)."""
        x, y = qfx.local_centers()
        tx, ty = qfx.TOWER_LOCAL
        near_x = np.maximum(np.abs(x - tx) - 0.5, 0.0)
        near_y = np.maximum(np.abs(y - ty) - 0.5, 0.0)
        touched = near_x ** 2 + near_y ** 2 < qfx.TOWER_OUTWARD_M ** 2
        self.assertEqual(int(touched.sum()), qfx.TOWER_ZONE_CELLS)

    def test_floors_below_terrain_and_apart(self) -> None:
        """Los fondos no se solapan, están por debajo del terreno y la rasante del corredor
        también (de 125 a 141 m); la lámina corta el terreno."""
        z = qfx.terrain()
        boxes = [qfx.in_box(floor.box) for floor in qfx.FLOORS]
        self.assertFalse((boxes[0] & boxes[1]).any())
        for floor, inside in zip(qfx.FLOORS, boxes, strict=True):
            self.assertGreater(float(z[inside].min()), floor.level_m + 40.0)
        end = qfx.CORRIDOR_START_M + qfx.CORRIDOR_LENGTH_M * qfx.CORRIDOR_GRADE_PCT / 100.0
        self.assertEqual(end, 141.0)
        self.assertGreater(float(z.min()), end)
        water = z[qfx.in_box(qfx.WATER_LOCAL)]
        self.assertLess(float(water.min()), qfx.WATER_LEVEL_M)
        self.assertGreater(float(water.max()), qfx.WATER_LEVEL_M)

    def test_corridor_axis(self) -> None:
        """El eje del corredor mide 200 m (120 + 80) y sale del borde del fondo de 125 m."""
        axis = np.asarray(qfx.CORRIDOR_AXIS_LOCAL)
        length = float(np.hypot(*np.diff(axis, axis=0).T).sum())
        self.assertEqual(length, qfx.CORRIDOR_LENGTH_M)
        left, bottom, right, top = qfx.FLOORS[0].box
        self.assertEqual(tuple(axis[0]), (right, (bottom + top) / 2.0))

    def test_profiles(self) -> None:
        """Los perfiles son los de la 013: ``EXPL_10_60_6`` y ``REST_5_35_6``, con ancla 125 m."""
        self.assertEqual(tuple(qfx.PROFILES), ("EXPL_10_60_6", "REST_5_35_6"))
        self.assertIs(qfx.EXPLOITATION_PROFILE, dfx.EXPL_10_60_6)
        self.assertIs(qfx.FINAL_PROFILE, dfx.REST_5_35_6)
        for profile in qfx.PROFILES.values():
            self.assertEqual(profile.anchor_m, qfx.FLOORS[0].level_m)
        self.assertAlmostEqual(qfx.EXPLOITATION_PROFILE.general_deg, 40.3, places=1)
        self.assertAlmostEqual(qfx.FINAL_PROFILE.general_deg, 20.83, places=2)


class PlanNamesTest(unittest.TestCase):
    """Los nombres de main en los que se apoya el plan 014 (§5.3) existen con la forma que dice."""

    def test_domain_names(self) -> None:
        pipeline = import_geoblender("design.pipeline")
        zones = import_geoblender("design.zones")
        for name in ("envelope_compute_steps", "design_compute_steps", "forward", "EnvelopeJob",
                     "DesignJob"):
            self.assertTrue(callable(getattr(pipeline, name)), name)
        self.assertTrue(callable(zones.cells_inside))
        self.assertTrue(callable(gis_store.read_features))
        for name in ("cut_allowed", "fill_allowed", "zone", "default_domain"):
            self.assertTrue(callable(getattr(access.MaskSet, name)), name)
        self.assertIn("ctypes", access.MaskSet.__dataclass_fields__)


class QuarryProjectTest(qfx.QuarryProjectCase):
    """El proyecto de la cantera: restricciones, sectores, terreno, capas y máscaras."""

    def test_built_once_within_budget(self) -> None:
        """La plantilla se crea una vez por proceso en ≤ 2 s de CPU y cada clase la copia en
        menos de 1 s."""
        template = qfx.project_template()
        self.assertIs(template, qfx.project_template())
        self.assertLessEqual(template["build_s"], qfx.BUILD_BUDGET_S)
        started = time.process_time()
        with qfx.open_quarry_project() as (_project, _clock):
            elapsed = time.process_time() - started
        self.assertLess(elapsed, COPY_BUDGET_S)

    def test_versions_constraints_and_searches(self) -> None:
        """V01 y V02, las cuatro restricciones y los dos sectores con su búsqueda vigente."""
        self.assertEqual((self.v1.code, self.v2.code), ("V01", "V02"))
        codes = tuple(sorted(item.code for item in self.stored_constraints()))
        self.assertEqual(codes, qfx.CONSTRAINT_CODES)
        states = access.sector_states(self.project, self.v1.uid)
        self.assertEqual([state.code for state in states], ["sector_1", "sector_2"])
        for state in states:
            self.assertIsNotNone(state.search, state.code)

    def test_masks_by_hand(self) -> None:
        """Las máscaras de V01 al día (V02 sin compilar): dominio, corte admitido (el recinto de
        A1), la franja de solo relleno, la torre con 8 m y «sin corte», con las cuentas a mano."""
        found, pending = access.mask_state(self.project, self.v1.uid)
        self.assertIs(found, access.MaskState.CURRENT)
        self.assertEqual(pending, ())
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.MISSING)
        masks = self.masks()
        self.assertEqual(masks.grid, qfx.GRID)
        domain = masks.default_domain()
        self.assertEqual(int(domain.sum()), qfx.DOMAIN_CELLS)
        self.assertEqual(int(masks.cut_allowed().sum()), qfx.CUT_ALLOWED_CELLS)
        self.assertTrue((masks.cut_allowed() <= domain).all())
        self.assertEqual(int(masks.fill_strip().sum()), qfx.STRIP_M2)
        self.assertEqual(masks.zone("torre").cells, qfx.TOWER_ZONE_CELLS)
        self.assertEqual(masks.zone("sin_corte").cells, qfx.NO_CUT_CELLS)
        self.assertEqual(masks.ctypes["torre"], "untouchable")
        self.assertEqual(masks.ctypes["sin_corte"], "no_cut")
        cut = masks.cut_allowed()
        for box in (*(floor.box for floor in qfx.FLOORS), qfx.CONSERVE_LOCAL):
            self.assertTrue(cut[qfx.in_box(box)].all(), box)
        self.assertFalse(cut[qfx.in_box(qfx.NO_CUT_LOCAL)].any())

    def test_start_surface(self) -> None:
        """El terreno de partida es una rejilla del proyecto igual a :func:`terrain`."""
        raster = gis_store.load_raster(self.project, qfx.START_DATASET)
        self.assertEqual(raster.grid, qfx.GRID)
        self.assertTrue(np.array_equal(raster.values, qfx.terrain()))

    def test_layers_read_back(self) -> None:
        """Las cinco capas se leen con ``gis.store.read_features`` con su geometría bit a bit,
        sus nombres y sus campos numéricos."""
        for layer in qfx.layers():
            found = self.read_layer(layer.name)
            self.assertEqual(found.kind, layer.kind, layer.name)
            self.assertTrue(qfx.same_entities(found.parts, layer.entities), layer.name)
            self.assertEqual(tuple(found.values["nombre"]), layer.names)
            for field, values in layer.fields.items():
                self.assertEqual(tuple(found.values[field]), values, (layer.name, field))
        corridor = self.read_layer(qfx.CORRIDORS_LAYER)
        self.assertEqual(corridor.values["ancho"], (20.0,))
        self.assertTrue(math.isclose(corridor.values["pendiente"][0], 8.0))
        floors = self.read_layer(qfx.FLOORS_LAYER)
        self.assertEqual(floors.values["cota"], (125.0, 175.0))


if __name__ == "__main__":
    unittest.main()
