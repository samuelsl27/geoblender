# SPDX-License-Identifier: GPL-3.0-or-later
"""Un lado de la cantera (spec 014, T13; HU-014-1, HU-014-2; RF-014-01 a RF-014-11; plan 014 A1 a
A7, A8 por lado, §5.3.1, §5.3.2).

``design.quarry.side_steps`` es el escalonado de la 013 de una de las dos superficies con las piezas
de la 014: las semillas «coronación y zonas a sostener» (o las de la 013), los fondos y los
corredores (``design.quarry.join_floors``), el techo de conservación y el ancla «al fondo de cada
muro», sobre ``envelope_compute_steps`` y ``design_compute_steps``. La prueba es la corta de E1
sobre la cantera sintética de ``tests.support.quarry_fixtures`` (T01), y cada pieza se comprueba
contra su función de T06 a T11:

- el recinto (T06): fuera de él la superficie es la de partida bit a bit;
- las semillas (T07): las de ``crown_seeds``, y la envolvente sembrada además con los fondos y los
  corredores (T08, T09) y con lo que el techo retiene, a ≤ 10⁻⁹ m del máximo de las tres
  envolventes calculadas aparte (RF-014-05: ``máx(ENV↓(s), ENV↓(F))``);
- el techo (T10): la superficie cumple sus tres reglas (``apply_ceiling`` no la cambia) y mueve
  0 m³ en la zona a conservar (CE-014-02), que sin techo se excavaría;
- el ancla (T11): la rejilla es la de ``floor_anchor_steps`` de los fondos y los corredores juntos,
  y cada berma queda en la cota de su fondo más ``k`` bancos a ≤ 10⁻⁹ m (RF-014-11); donde el fondo
  manda, la superficie es su cota.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
pipeline = import_geoblender("design.pipeline")
envelopes = import_geoblender("design.envelopes")
seeds_mod = import_geoblender("design.seeds")
messages = import_geoblender("design.messages")
vector = import_geoblender("gis.vector")

TOLERANCE_M = 1e-9
RING_CELLS = 3
CONSERVE_SLOPE_DEG = 35.0
"""El talud de conservación de la prueba (D-9: un dato de entrada, el del análisis)."""
MIN_THICKNESS_M = 0.02
FACE_TOLERANCE_DEG = 1.0
WARNING_RATIO = 2.0
EXPL = qfx.EXPLOITATION_PROFILE
REST = qfx.FINAL_PROFILE
CORRIDOR = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                                gradient_field="pendiente")
CROWN_AND_HOLD_CELLS = 3_576 + qfx.TOWER_ZONE_CELLS + qfx.NO_CUT_CELLS
"""``|C ∪ H|`` con el anillo de 3 celdas (a mano en T07): 5.400 celdas."""


def last_result(steps: Any) -> Any:
    found = None
    for found in steps:
        pass
    return found.result


def profile_values() -> dict[str, object]:
    """Los parámetros de los dos perfiles de la cantera (clave → valor)."""
    found: dict[str, object] = {}
    for profile in (EXPL, REST):
        for param, value in (("height_m", profile.height_m), ("face_deg", profile.face_deg),
                             ("berm_m", profile.berm_m), ("anchor_m", profile.anchor_m),
                             ("mesh_factor", profile.mesh_factor)):
            found[params.bench_key(profile.code, param)] = value
    return found


def side(profile: Any, **changes: Any) -> Any:
    return model.QuarrySide(base_profile=profile.code, **changes)


class QuarrySideTest(qfx.QuarryProjectCase):
    """La corta de E1 (un lado, la explotación) con cada pieza contra su prueba de T06 a T11."""

    request: ClassVar[Any]
    outcome: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        access = import_geoblender("gis.masks.access")
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        cls.refs, cls.labels = seeds_mod.sector_layout(cls.project, cls.masks_v1)
        cls.geometry = cls.masks_v1.grid
        cls.start = qfx.terrain()
        cls.area = quarry.excavation_area(cls.masks_v1, cls.start)
        cls.domain = seeds_mod.domain_of(cls.area, cls.labels, cls.refs, cls.geometry.cell_area)
        gstore = import_geoblender("gis.store")
        with cls.project.read() as conn:
            floors_layer = gstore.read_features(conn, qfx.FLOORS_LAYER)
            corridors_layer = gstore.read_features(conn, qfx.CORRIDORS_LAYER)
        cls.floor_part = quarry.floor_map(floors_layer, model.LayerField(qfx.FLOORS_LAYER, "cota"),
                                          cls.start, cls.geometry)
        cls.corridors = quarry.corridor_cells(corridors_layer, CORRIDOR, cls.geometry)
        cls.floors = quarry.join_floors(cls.floor_part, cls.corridors)
        cls.zone = quarry.ConserveZone("Ladera a conservar", qfx.in_box(qfx.CONSERVE_LOCAL))
        cls.ceiling = last_result(quarry.conservation_ceiling_steps(
            (cls.zone,), cls.start, cls.geometry, CONSERVE_SLOPE_DEG))
        cls.request = model.QuarryRequest(
            name="Cantera E1", start=qfx.START_DATASET, final=side(REST),
            exploitation=side(EXPL, anchor="nearest_floor"),
            floors=model.LayerField(qfx.FLOORS_LAYER, "cota"),
            conserve=(model.Zone("layer", qfx.CONSERVE_LAYER),), corridors=CORRIDOR)
        cls.inputs = (cls.start.copy(), cls.floors.grid.copy(), cls.ceiling.grid.copy(),
                      cls.area.copy())
        cls.steps = list(quarry.side_steps(cls.job()))
        cls.outcome = cls.steps[-1].result

    @classmethod
    def job(cls, **changes: Any) -> Any:
        values: dict[str, Any] = {
            "request": cls.request, "surface": model.Surface.EXPLOITATION, "start": cls.start,
            "masks": cls.masks_v1, "domain": cls.domain, "values": profile_values(),
            "ring_cells": RING_CELLS, "min_thickness_m": MIN_THICKNESS_M,
            "face_tolerance_deg": FACE_TOLERANCE_DEG, "warning_ratio": WARNING_RATIO,
            "floors": cls.floors, "ceiling": cls.ceiling}
        values.update(changes)
        return quarry.SideJob(**values)

    def envelope_of(self, seeds: Any, profile: Any = EXPL) -> np.ndarray:
        """La envolvente descendente de la 013 de ``seeds`` con el talud general de ``profile``
        (por sectores, todos con él), calculada aparte."""
        request = model.EnvelopeRequest("Aparte", "down", model.SeedSource("surface", surface="x"),
                                        slope_mode="sectors", base_profile=profile.code)
        slope = pipeline.envelope_slope(request, self.refs, self.labels, profile_values())
        return last_result(envelopes.envelope_steps(request, seeds, slope)).grid

    # --- Los pasos ------------------------------------------------------------------------

    def test_it_goes_by_steps_and_the_last_one_carries_the_side(self) -> None:
        """Por pasos de la 013 (envolvente y escalonado; §5.3.2): solo el último lleva el
        resultado, un ``SideOutcome`` de la explotación con su nombre en los mensajes."""
        self.assertGreater(len(self.steps), 2)
        self.assertTrue(all(step.result is None for step in self.steps[:-1]))
        phases = {step.phase for step in self.steps}
        self.assertTrue({"anchors", "benching"} <= phases, phases)
        self.assertIsInstance(self.outcome, quarry.SideOutcome)
        self.assertIs(self.outcome.surface, model.Surface.EXPLOITATION)
        self.assertIn("Cantera E1 (superficie de explotación)", self.outcome.design.message)
        self.assertEqual(self.outcome.grid.dtype, np.float64)

    # --- El recinto (T06) y las semillas (T07) ---------------------------------------------

    def test_outside_the_excavation_area_nothing_moves(self) -> None:
        """RF-014-01 (A1): la superficie es la de partida bit a bit fuera del recinto, y dentro no
        la supera; la envolvente no tiene cota fuera de él."""
        design = self.outcome.grid
        np.testing.assert_array_equal(design[~self.area], self.start[~self.area])
        self.assertTrue(bool(np.all(design[self.area] <= self.start[self.area])))
        self.assertTrue(bool(np.isnan(self.outcome.envelope.grid[~self.area]).all()))
        self.assertGreater(self.outcome.design.report.cut_m3, 0.0)

    def test_the_seeds_are_the_crown_and_the_zones_to_hold(self) -> None:
        """RF-014-02 (A2): las semillas base son las de ``crown_seeds`` del recinto con el anillo
        de 3 celdas: 5.400 celdas, el terreno en ``C ∪ H`` y en ninguna otra."""
        expected = quarry.crown_seeds(self.area, self.start, self.masks_v1, RING_CELLS,
                                      domain=self.domain)
        found = self.outcome.seeds
        self.assertEqual(found.cells, CROWN_AND_HOLD_CELLS)
        np.testing.assert_array_equal(found.grid, expected.grid)

    def test_the_envelope_is_the_highest_of_the_seeds_floors_and_held_cells(self) -> None:
        """RF-014-05 (A4) con el corredor (A6) y el techo (A5): la envolvente es, en el recinto,
        el máximo de la de las semillas, la de los fondos y corredores y la de lo que el techo
        retiene (aquí, la zona a conservar), a ≤ 10⁻⁹ m de las tres calculadas aparte; y los
        fondos ganan en alguna celda."""
        crown = self.outcome.seeds
        floors = quarry.with_floors(replace(crown, grid=np.full(crown.grid.shape, np.inf)),
                                    self.floors)
        held = seeds_mod.collect_seeds(self.start, self.zone.mask, crown.domain, self.geometry)
        parts = [self.envelope_of(item) for item in (crown, floors, held)]
        expected = np.where(self.area, np.fmax(np.fmax(parts[0], parts[1]), parts[2]), np.nan)
        found = self.outcome.envelope.grid
        np.testing.assert_array_equal(np.isnan(found), np.isnan(expected))
        inside = np.isfinite(found)
        self.assertLessEqual(float(np.max(np.abs(found[inside] - expected[inside]))), TOLERANCE_M)
        self.assertTrue(bool(np.any(inside & (parts[1] > parts[0] + 1.0))))
        self.assertEqual(self.outcome.envelope_seeds.cells,
                         int(np.count_nonzero(np.isfinite(crown.grid) | np.isfinite(
                             self.floors.grid) | self.zone.mask)))

    # --- El techo (T10) --------------------------------------------------------------------

    def test_the_ceiling_rules_hold_and_nothing_moves_in_the_zone(self) -> None:
        """RF-014-07, RF-014-08 (A5; CE-014-02): la superficie cumple las tres reglas del techo
        (``apply_ceiling`` no cambia ni un bit), es el terreno en la zona y mueve 0 m³ en ella."""
        design = self.outcome.grid
        np.testing.assert_array_equal(quarry.apply_ceiling(design, self.start, self.ceiling),
                                      design)
        np.testing.assert_array_equal(design[self.zone.mask], self.start[self.zone.mask])
        moved = quarry.conserve_moved(design, self.start, (self.zone,), self.geometry,
                                      MIN_THICKNESS_M)
        self.assertFalse(moved.moved)
        self.assertEqual(moved.volume_m3, 0.0)
        np.testing.assert_array_equal(self.outcome.held, self.zone.mask)

    def test_without_the_ceiling_the_zone_is_excavated(self) -> None:
        """El contraste: sin techo, la misma corta excava la zona a conservar."""
        outcome = last_result(quarry.side_steps(self.job(ceiling=None)))
        moved = quarry.conserve_moved(outcome.grid, self.start, (self.zone,), self.geometry,
                                      MIN_THICKNESS_M)
        self.assertTrue(moved.moved)
        self.assertGreater(moved.volume_m3, 1_000.0)
        self.assertIsNone(outcome.held)

    # --- El ancla (T11) --------------------------------------------------------------------

    def test_the_anchor_grid_is_the_one_of_the_floors_and_corridors(self) -> None:
        """RF-014-11 (A7): la rejilla de anclas es la de ``floor_anchor_steps`` de los fondos y el
        corredor juntos, y cada berma queda en la cota de su fondo más ``k`` bancos de 10 m a
        ≤ 10⁻⁹ m."""
        anchors = last_result(quarry.floor_anchor_steps(self.floors, self.geometry))
        np.testing.assert_array_equal(self.outcome.anchors.grid, anchors.grid)
        berms = self.outcome.design.berms.grid
        found = np.isfinite(berms)
        self.assertGreater(int(np.count_nonzero(found)), 0)
        levels, floor = berms[found], anchors.grid[found]
        k = np.round((levels - floor) / EXPL.height_m)
        self.assertLessEqual(float(np.max(np.abs(levels - (floor + k * EXPL.height_m)))),
                             TOLERANCE_M)

    def test_where_a_floor_rules_the_surface_is_its_level(self) -> None:
        """RF-014-05 con RF-014-11: en las celdas de fondo donde la envolvente es su cota (el fondo
        de 125 m manda sobre las paredes) y queda bajo el terreno, la superficie es esa cota."""
        envelope = self.outcome.envelope.grid
        rules = (np.isfinite(self.floor_part.grid) & (envelope == self.floor_part.grid)
                 & (self.floor_part.grid < self.start))
        self.assertGreater(int(np.count_nonzero(rules)), 100)
        np.testing.assert_array_equal(self.outcome.grid[rules], self.floor_part.grid[rules])

    def test_the_fixed_anchor_is_the_one_of_the_profile(self) -> None:
        """Con el ancla del perfil (125 m), no hay rejilla y las bermas quedan en ``125 + k·10``."""
        request = replace(self.request, exploitation=side(EXPL))
        outcome = last_result(quarry.side_steps(self.job(request=request)))
        self.assertIsNone(outcome.anchors)
        berms = outcome.design.berms.grid
        levels = berms[np.isfinite(berms)]
        self.assertGreater(levels.size, 0)
        offset = np.mod(levels - EXPL.anchor_m, EXPL.height_m)
        self.assertTrue(bool(np.all(np.minimum(offset, EXPL.height_m - offset) <= TOLERANCE_M)))

    def test_the_final_side_takes_its_own_profile(self) -> None:
        """La final, con su perfil (``REST_5_35_6``) y sin ancla en rejilla: su envolvente es la de
        las mismas semillas con el talud general de su perfil."""
        outcome = last_result(quarry.side_steps(self.job(surface="final")))
        self.assertIs(outcome.surface, model.Surface.FINAL)
        self.assertIn("superficie final", outcome.design.message)
        crown = outcome.seeds
        floors = quarry.with_floors(replace(crown, grid=np.full(crown.grid.shape, np.inf)),
                                    self.floors)
        held = seeds_mod.collect_seeds(self.start, self.zone.mask, crown.domain, self.geometry)
        parts = [self.envelope_of(item, REST) for item in (crown, floors, held)]
        expected = np.fmax(np.fmax(parts[0], parts[1]), parts[2])[self.area]
        found = outcome.envelope.grid[self.area]
        self.assertLessEqual(float(np.max(np.abs(found - expected))), TOLERANCE_M)

    # --- Los rechazos ----------------------------------------------------------------------

    def test_a_nearest_floor_anchor_without_floors_is_refused(self) -> None:
        """«Al fondo de cada muro» sin fondos ni corredores: el escalonado rechaza la rejilla de
        anclas sin cota (``des.anchor_nodata``) con su nombre."""
        with self.assertRaises(messages.DesignError) as caught:
            last_result(quarry.side_steps(self.job(floors=None)))
        self.assertEqual(caught.exception.code, "des.anchor_nodata")
        self.assertIn("al fondo de cada muro", str(caught.exception))

    def test_the_seeds_and_the_grid_anchor_must_match_the_side(self) -> None:
        """Errores del programa al llamar: unas semillas de la 013 con un lado de «coronación» (o
        al revés), y una rejilla de anclas sin el ancla en rejilla (o al revés)."""
        crown = self.outcome.seeds
        with self.assertRaises(ValueError):
            quarry.side_steps(self.job(seeds=crown))
        user = model.SeedSource("surface", surface=qfx.START_DATASET, zone=model.Zone("domain"))
        with self.assertRaises(ValueError):
            quarry.side_steps(self.job(request=replace(
                self.request, exploitation=side(EXPL, seeds=user))))
        with self.assertRaises(ValueError):
            quarry.side_steps(self.job(anchors=np.full(self.start.shape, 125.0)))
        grid_side = side(EXPL, anchor="grid", anchor_grid="gis_dtm_anclas")
        with self.assertRaises(ValueError):
            quarry.side_steps(self.job(request=replace(self.request, exploitation=grid_side)))

    def test_the_013_seeds_and_a_grid_anchor_are_used_as_given(self) -> None:
        """Con semillas de la 013 (aquí, las de la coronación pasadas a mano) y una rejilla de
        anclas leída (125 m en todas las celdas), el lado las usa tal cual."""
        user = model.SeedSource("surface", surface=qfx.START_DATASET, zone=model.Zone("domain"))
        grid_side = side(EXPL, seeds=user, anchor="grid", anchor_grid="gis_dtm_anclas")
        crown = self.outcome.seeds
        outcome = last_result(quarry.side_steps(self.job(
            request=replace(self.request, exploitation=grid_side), seeds=crown,
            anchors=np.full(self.start.shape, EXPL.anchor_m))))
        self.assertIs(outcome.seeds, crown)
        self.assertIsNone(outcome.anchors)
        fixed = last_result(quarry.side_steps(self.job(
            request=replace(self.request, exploitation=side(EXPL)))))
        np.testing.assert_array_equal(outcome.grid, fixed.grid)

    def test_the_inputs_are_not_modified(self) -> None:
        """Ninguna entrada se modifica: las de la clase, copiadas antes de su primer lado, siguen
        igual tras él y tras los de las pruebas anteriores."""
        after = (self.start, self.floors.grid, self.ceiling.grid, self.area)
        for old, new in zip(self.inputs, after, strict=True):
            np.testing.assert_array_equal(old, new)


class JoinFloorsTest(unittest.TestCase):
    """Los fondos y los corredores en un solo mapa (A4, A6; RF-014-06, RF-014-09)."""

    SHAPE = (10, 12)

    def floor(self, layer: str, boxes: list[tuple[slice, slice]], levels: list[float]) -> Any:
        grid = np.full(self.SHAPE, np.nan)
        owner = np.zeros(self.SHAPE, dtype=np.int32)
        cells = []
        for index, (box, level) in enumerate(zip(boxes, levels, strict=True), start=1):
            grid[box] = level
            owner[box] = index
            cells.append(int(np.count_nonzero(owner == index)))
        fids = tuple(range(1, len(boxes) + 1))
        return quarry.FloorMap(layer, "cota", grid, owner, fids, tuple(levels), tuple(cells), 1.0)

    def test_floors_and_corridors_join_in_their_order(self) -> None:
        """Las celdas de los dos, con su cota; los corredores siguen a los fondos (su dueño,
        desplazado), y la capa nombra las dos."""
        floors = self.floor("fondos", [(slice(0, 3), slice(0, 3))], [125.0])
        lane = self.floor("corredores", [(slice(5, 7), slice(0, 12))], [130.0])
        corridors = quarry.CorridorMap(lane, (2.0,), (12.0,), (11.0,))
        joined = quarry.join_floors(floors, corridors)
        expected = np.fmax(np.nan_to_num(floors.grid, nan=-np.inf),
                           np.nan_to_num(lane.grid, nan=-np.inf))
        expected[np.isneginf(expected)] = np.nan
        np.testing.assert_array_equal(joined.grid, expected)
        np.testing.assert_array_equal(joined.owner, floors.owner + np.where(lane.owner > 0, 2, 0))
        self.assertEqual(joined.levels, (125.0, 130.0))
        self.assertEqual(joined.cells, (9, 24))
        self.assertEqual(joined.layer, "fondos y corredores")
        self.assertIs(quarry.join_floors(floors, None), floors)
        self.assertIs(quarry.join_floors(None, corridors), lane)
        self.assertIsNone(quarry.join_floors(None, None))

    def test_a_corridor_over_a_floor_is_refused(self) -> None:
        """RF-014-06 con RF-014-09: un corredor es un polígono de fondo; si pisa un fondo, se
        rechaza con los dos y sus celdas comunes (``des.floor_overlap``), sin elegir cota."""
        floors = self.floor("fondos", [(slice(0, 3), slice(0, 3))], [125.0])
        lane = self.floor("corredores", [(slice(2, 4), slice(0, 12))], [130.0])
        corridors = quarry.CorridorMap(lane, (2.0,), (12.0,), (11.0,))
        with self.assertRaises(messages.DesignError) as caught:
            quarry.join_floors(floors, corridors)
        self.assertEqual(caught.exception.code, "des.floor_overlap")
        text = str(caught.exception)
        for word in ("fondos", "corredores", " 3 "):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
