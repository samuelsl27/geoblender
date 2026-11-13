# SPDX-License-Identifier: GPL-3.0-or-later
"""Las dos superficies de la cantera y el orden (spec 014, T16; HU-014-3; RF-014-12, RF-014-13,
RF-014-14; plan 014 A8, §5.3.1, §5.3.2).

``design.quarry.quarry_steps`` calcula en una sola orden los dos lados de la cantera (la final y la
explotación, cada uno con ``side_steps`` de la T13), primero el que dice el orden del diseño, y
los ata con la regla de orden (``order_surfaces``): «final primero» sube la explotación donde
queda por debajo de la final (``explotación = máx(explotación, final)``) y «explotación primero»
baja la final donde queda por encima (``final = mín(final, explotación)``); después, las dos
``≤ z``. Antes de dar el resultado comprueba ``final ≤ explotación ≤ terreno`` celda a celda a
1 mm (``check_order``): si fallara, es un error del programa (``des.quarry_order_broken``) y no
sale nada que crear. Un lado con la euclídea exacta se rechaza al llamar (T45): los dos van con la
pendiente de sus sectores.

Las reglas, con rejillas a mano; el orden y el invariante, con la corta de E3 sobre la cantera
sintética de ``tests.support.quarry_fixtures`` (T01), en la que la final (``REST_5_35_6``, más
tendida) sale por encima de la explotación (``EXPL_10_60_6``) en casi todo el recinto.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
seeds_mod = import_geoblender("design.seeds")
messages = import_geoblender("design.messages")
gis_grid = import_geoblender("gis.grid")

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
NAN = math.nan


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


# --- La regla de orden y el invariante, a mano ---------------------------------------------------

GRID = gis_grid.Grid(500_000.0, 4_400_010.0, 2.0, 2.0, 3, 2)
"""Una rejilla de 3 × 2 celdas de 2 m: el centro de la celda (fila ``i``, columna ``j``) está en
``x = 500.000 + (j + 0,5)·2``, ``y = 4.400.010 − (i + 0,5)·2``."""
FINAL = np.array([[100.0, 105.0, 95.0], [90.0, 97.0, NAN]])
EXPLOITATION = np.array([[102.0, 100.0, 96.0], [90.0, 99.0, NAN]])
TERRAIN = np.array([[110.0, 104.0, 95.5], [98.0, 98.0, NAN]])
"""La final sale por encima de la explotación en (0, 1) (105 > 100); la explotación, por encima
del terreno en (0, 2) (96 > 95,5) y en (1, 1) (99 > 98); la celda (1, 2) no tiene terreno."""


class OrderRuleTest(unittest.TestCase):
    """RF-014-13 y la segunda mitad de A8 (``≤ z``), con rejillas a mano."""

    def test_final_first_raises_the_exploitation_to_the_final(self) -> None:
        """«Final primero»: la final se queda (salvo ``≤ z``) y la explotación sube a la final
        donde queda por debajo (``máx``); después, las dos ``≤ z``; la celda sin terreno sigue sin
        dato. Una celda cambiada por la regla: la (0, 1)."""
        found = quarry.order_surfaces("final_first", FINAL, EXPLOITATION, TERRAIN)
        self.assertIs(found.order, model.Order.FINAL_FIRST)
        np.testing.assert_array_equal(found.final,
                                      [[100.0, 104.0, 95.0], [90.0, 97.0, NAN]])
        np.testing.assert_array_equal(found.exploitation,
                                      [[102.0, 104.0, 95.5], [90.0, 98.0, NAN]])
        self.assertEqual(found.adjusted, 1)

    def test_exploitation_first_lowers_the_final_to_the_exploitation(self) -> None:
        """«Explotación primero»: la explotación se queda (salvo ``≤ z``) y la final baja a la
        explotación donde queda por encima (``mín``); después, las dos ``≤ z``."""
        found = quarry.order_surfaces(model.Order.EXPLOITATION_FIRST, FINAL, EXPLOITATION,
                                      TERRAIN)
        self.assertIs(found.order, model.Order.EXPLOITATION_FIRST)
        np.testing.assert_array_equal(found.final,
                                      [[100.0, 100.0, 95.0], [90.0, 97.0, NAN]])
        np.testing.assert_array_equal(found.exploitation,
                                      [[102.0, 100.0, 95.5], [90.0, 98.0, NAN]])
        self.assertEqual(found.adjusted, 1)

    def test_the_cells_it_changes_count_with_the_tolerance(self) -> None:
        """RF-014-14 (T60; el punto 1 de la T53): las celdas que cambió la regla se cuentan con la
        tolerancia del invariante, 1 mm (``ORDER_TOLERANCE_M``: las que cambian más de 1 mm), no en
        sentido estricto. Con la final 4·10⁻¹³ m o 0,9 mm por encima de la explotación la regla
        cambia la segunda (es exacta: ``final ≤ explotación`` sin tolerancia) pero no cuenta; con
        1,1 mm y 5 m, sí: 2 celdas, con los dos órdenes."""
        final = np.array([[100.0 + 4e-13, 100.0009, 100.0011], [105.0, 99.0, NAN]])
        exploitation = np.full(final.shape, 100.0)
        terrain = np.full(final.shape, 110.0)
        for order in model.Order:
            with self.subTest(order=order):
                found = quarry.order_surfaces(order, final, exploitation, terrain)
                self.assertEqual(found.adjusted, 2)
                with np.errstate(invalid="ignore"):
                    self.assertTrue(bool(np.all((found.final <= found.exploitation)
                                                | np.isnan(found.final))))
                    self.assertEqual(int(np.count_nonzero(final > exploitation)), 4)

    def test_both_orders_keep_the_invariant_and_the_inputs(self) -> None:
        """RF-014-14: con los dos órdenes, ``final ≤ explotación ≤ terreno`` (``check_order`` no
        dice nada); las rejillas son nuevas y las de entrada no cambian."""
        before = (FINAL.copy(), EXPLOITATION.copy(), TERRAIN.copy())
        for order in model.Order:
            found = quarry.order_surfaces(order, FINAL, EXPLOITATION, TERRAIN)
            quarry.check_order("Cantera a mano", found.final, found.exploitation, TERRAIN, GRID)
            self.assertIsNot(found.final, FINAL)
            self.assertIsNot(found.exploitation, EXPLOITATION)
        for old, new in zip(before, (FINAL, EXPLOITATION, TERRAIN), strict=True):
            np.testing.assert_array_equal(old, new)

    def test_the_grids_must_match(self) -> None:
        """Error del programa: rejillas de formas distintas."""
        with self.assertRaises(ValueError):
            quarry.order_surfaces("final_first", FINAL, EXPLOITATION[:, :2], TERRAIN)


class CheckOrderTest(unittest.TestCase):
    """RF-014-14: el invariante ``final ≤ explotación ≤ terreno`` celda a celda a 1 mm."""

    def broken(self, final: np.ndarray, exploitation: np.ndarray) -> Any:
        with self.assertRaises(messages.DesignError) as caught:
            quarry.check_order("Cantera a mano", final, exploitation, TERRAIN, GRID)
        self.assertEqual(caught.exception.code, "des.quarry_order_broken")
        return caught.exception

    def test_within_one_millimetre_it_holds(self) -> None:
        """Hasta 1 mm por encima (0,9 mm) se admite: la final sobre la explotación y la explotación
        sobre el terreno; las celdas sin dato en las tres, también."""
        self.assertEqual(quarry.ORDER_TOLERANCE_M, 0.001)
        exploitation = np.array([[109.0, 104.0009, 95.0], [90.0, 97.0, NAN]])
        final = exploitation + np.array([[0.0009, 0.0, 0.0], [0.0, 0.0009, 0.0]])
        quarry.check_order("Cantera a mano", final, exploitation, TERRAIN, GRID)

    def test_over_one_millimetre_it_is_a_program_error_with_the_first_cell(self) -> None:
        """Más de 1 mm (1,1 mm) es un error del programa: ``des.quarry_order_broken`` con la
        primera celda que falla fila a fila desde el norte, sus coordenadas absolutas y las tres
        cotas; no se crea nada."""
        exploitation = np.array([[109.0, 104.0, 95.0], [90.0, 97.0, NAN]])
        final = exploitation.copy()
        final[0, 2] += 0.0011  # la final sobre la explotación
        final[1, 0] += 5.0
        error = self.broken(final, exploitation)
        self.assertEqual(error.values["x"], 500_005.0)
        self.assertEqual(error.values["y"], 4_400_009.0)
        self.assertEqual(error.values["final"], 95.001)
        self.assertEqual(error.values["exploitation"], 95.0)
        self.assertEqual(error.values["terrain"], 95.5)
        self.assertEqual(error.values["value"], 2)
        text = str(error)
        self.assertIn("Error del programa", text)
        self.assertIn("x = 500005 m, y = 4400009 m", text)
        self.assertIn("no se crea nada", text)

    def test_the_exploitation_over_the_terrain_is_broken(self) -> None:
        """La explotación más de 1 mm por encima del terreno (98,0011 m sobre 98 m)."""
        exploitation = np.array([[109.0, 104.0, 95.0], [90.0, 98.0011, NAN]])
        error = self.broken(exploitation.copy(), exploitation)
        self.assertEqual((error.values["x"], error.values["y"]), (500_003.0, 4_400_007.0))
        self.assertEqual(error.values["exploitation"], 98.001)

    def test_a_surface_without_value_where_the_terrain_has_one_is_broken(self) -> None:
        """Una superficie sin dato donde el terreno lo tiene (o al revés) tampoco cumple."""
        exploitation = np.array([[109.0, 104.0, 95.0], [90.0, 97.0, NAN]])
        final = exploitation.copy()
        final[0, 0] = NAN
        error = self.broken(final, exploitation)
        self.assertEqual((error.values["x"], error.values["y"]), (500_001.0, 4_400_009.0))
        self.assertEqual(error.values["final"], "—")
        other = exploitation.copy()
        other[1, 2] = 90.0
        error = self.broken(other.copy(), other)
        self.assertEqual((error.values["x"], error.values["y"]), (500_005.0, 4_400_007.0))
        self.assertEqual(error.values["terrain"], "—")


# --- Las dos superficies de la cantera -----------------------------------------------------------


class QuarryStepsTest(qfx.QuarryProjectCase):
    """RF-014-12 a RF-014-14 sobre la cantera: los dos órdenes, la final por encima de la
    explotación que el orden corrige y el invariante."""

    request: ClassVar[Any]
    final_first: ClassVar[Any]
    exploitation_first: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        access = import_geoblender("gis.masks.access")
        gstore = import_geoblender("gis.store")
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        refs, labels = seeds_mod.sector_layout(cls.project, cls.masks_v1)
        cls.geometry = cls.masks_v1.grid
        cls.start = qfx.terrain()
        cls.area = quarry.excavation_area(cls.masks_v1, cls.start)
        cls.domain = seeds_mod.domain_of(cls.area, labels, refs, cls.geometry.cell_area)
        with cls.project.read() as conn:
            floors_layer = gstore.read_features(conn, qfx.FLOORS_LAYER)
            corridors_layer = gstore.read_features(conn, qfx.CORRIDORS_LAYER)
        floor_part = quarry.floor_map(floors_layer, model.LayerField(qfx.FLOORS_LAYER, "cota"),
                                      cls.start, cls.geometry)
        corridors = quarry.corridor_cells(corridors_layer, CORRIDOR, cls.geometry)
        cls.floors = quarry.join_floors(floor_part, corridors)
        zone = quarry.ConserveZone("Ladera a conservar", qfx.in_box(qfx.CONSERVE_LOCAL))
        cls.ceiling = last_result(quarry.conservation_ceiling_steps(
            (zone,), cls.start, cls.geometry, CONSERVE_SLOPE_DEG))
        cls.request = model.QuarryRequest(
            name="Cantera E3", start=qfx.START_DATASET, final=side(REST),
            exploitation=side(EXPL, anchor="nearest_floor"),
            floors=model.LayerField(qfx.FLOORS_LAYER, "cota"),
            conserve=(model.Zone("layer", qfx.CONSERVE_LAYER),), corridors=CORRIDOR)
        cls.inputs = (cls.start.copy(), cls.floors.grid.copy(), cls.ceiling.grid.copy(),
                      cls.area.copy())
        cls.final_steps = list(quarry.quarry_steps(cls.job()))
        cls.final_first = cls.final_steps[-1].result
        cls.exploitation_steps = list(quarry.quarry_steps(cls.job(
            request=replace(cls.request, order="exploitation_first"))))
        cls.exploitation_first = cls.exploitation_steps[-1].result

    @classmethod
    def job(cls, **changes: Any) -> Any:
        values: dict[str, Any] = {
            "request": cls.request, "start": cls.start, "masks": cls.masks_v1,
            "domain": cls.domain, "values": profile_values(), "ring_cells": RING_CELLS,
            "min_thickness_m": MIN_THICKNESS_M, "face_tolerance_deg": FACE_TOLERANCE_DEG,
            "warning_ratio": WARNING_RATIO, "floors": cls.floors, "ceiling": cls.ceiling}
        values.update(changes)
        return quarry.QuarryJob(**values)

    # --- Los pasos y el orden de cálculo ------------------------------------------------------

    def test_it_goes_by_steps_and_the_last_one_carries_the_two_surfaces(self) -> None:
        """RF-014-12: una sola orden, por pasos (los de los dos lados y los del orden; §5.3.2);
        solo el último lleva el resultado, un ``QuarryOutcome`` con los dos lados y las dos
        superficies, y no se escribe nada (es dominio puro)."""
        for steps, outcome in ((self.final_steps, self.final_first),
                               (self.exploitation_steps, self.exploitation_first)):
            self.assertTrue(all(step.result is None for step in steps[:-1]))
            phases = {step.phase for step in steps}
            self.assertTrue({"side", "anchors", "benching", "order"} <= phases, phases)
            self.assertIsInstance(outcome, quarry.QuarryOutcome)
            self.assertIs(outcome.final.surface, model.Surface.FINAL)
            self.assertIs(outcome.exploitation.surface, model.Surface.EXPLOITATION)
            self.assertIs(outcome.side("final"), outcome.final)
            self.assertIn("Cantera E3", outcome.message)
            for grid in (outcome.final_grid, outcome.exploitation_grid):
                self.assertEqual(grid.dtype, np.float64)
                self.assertEqual(grid.shape, self.start.shape)

    def test_the_order_says_which_side_is_computed_first(self) -> None:
        """RF-014-13: «final primero» calcula antes la final y «explotación primero», antes la
        explotación; el resultado lo dice."""
        for steps, outcome, first in (
                (self.final_steps, self.final_first, "superficie final"),
                (self.exploitation_steps, self.exploitation_first, "superficie de explotación")):
            sides = [step.message for step in steps if step.phase == "side"]
            self.assertTrue(sides[0].startswith("Preparando la "), sides)
            self.assertTrue(sides[0].endswith(f"{first}…"), sides)
        self.assertIs(self.final_first.order, model.Order.FINAL_FIRST)
        self.assertIs(self.exploitation_first.order, model.Order.EXPLOITATION_FIRST)
        self.assertIn("final primero", self.final_first.message)
        self.assertIn("explotación primero", self.exploitation_first.message)

    def test_each_side_is_the_one_of_side_steps(self) -> None:
        """Cada lado es el de ``side_steps`` (T13) con su ``SideJob`` y no depende del orden: la
        explotación, igual bit a bit a la calculada aparte, y los dos lados, iguales con los dos
        órdenes."""
        alone = last_result(quarry.side_steps(self.job().side_job("exploitation")))
        np.testing.assert_array_equal(self.final_first.exploitation.grid, alone.grid)
        for surface in model.Surface:
            np.testing.assert_array_equal(self.final_first.side(surface).grid,
                                          self.exploitation_first.side(surface).grid)

    # --- La regla de orden ----------------------------------------------------------------------

    def test_the_final_comes_out_above_the_exploitation_and_the_order_fixes_it(self) -> None:
        """RF-014-13 con el caso construido: la final (``REST_5_35_6``, talud general de 20,8°)
        sale más de 1 m por encima de la explotación (``EXPL_10_60_6``, 40,3°) en miles de celdas.
        «Final primero» deja la final y sube la explotación a ella (``máx``); «explotación
        primero» deja la explotación y baja la final (``mín``); las dos dicen cuántas celdas
        cambió la regla más de 1 mm (T60: una celda con la final 0,91 mm por encima la cambia la
        regla, pero no cuenta)."""
        final, exploitation = self.final_first.final.grid, self.final_first.exploitation.grid
        above = final > exploitation
        self.assertGreater(int(np.count_nonzero(final > exploitation + 1.0)), 10_000)
        first = self.final_first
        np.testing.assert_array_equal(first.final_grid, final)
        np.testing.assert_array_equal(first.exploitation_grid,
                                      np.minimum(np.maximum(exploitation, final), self.start))
        np.testing.assert_array_equal(first.exploitation_grid[above], final[above])
        second = self.exploitation_first
        np.testing.assert_array_equal(second.exploitation_grid, exploitation)
        np.testing.assert_array_equal(second.final_grid, np.minimum(final, exploitation))
        np.testing.assert_array_equal(second.final_grid[above], exploitation[above])
        counted = int(np.count_nonzero(final - exploitation > quarry.ORDER_TOLERANCE_M))
        self.assertGreater(int(np.count_nonzero(above)), counted)
        for outcome in (first, second):
            self.assertEqual(outcome.adjusted, counted)

    def test_final_below_exploitation_below_terrain_everywhere(self) -> None:
        """RF-014-14: con los dos órdenes, ``final ≤ explotación ≤ terreno`` en todas las celdas
        (exacto: la regla no deja ni el milímetro de tolerancia); fuera del recinto las dos son la
        de partida bit a bit."""
        for outcome in (self.final_first, self.exploitation_first):
            final, exploitation = outcome.final_grid, outcome.exploitation_grid
            self.assertTrue(bool(np.all(final <= exploitation)))
            self.assertTrue(bool(np.all(exploitation <= self.start)))
            np.testing.assert_array_equal(final[~self.area], self.start[~self.area])
            np.testing.assert_array_equal(exploitation[~self.area], self.start[~self.area])
            quarry.check_order("Cantera E3", final, exploitation, self.start, self.geometry)

    def test_a_broken_invariant_is_a_program_error_and_nothing_comes_out(self) -> None:
        """RF-014-14: si la regla de orden dejara la final más de 1 mm por encima de la
        explotación (aquí, forzado en una celda del recinto), los pasos se paran con
        ``des.quarry_order_broken`` en esa celda y ninguno lleva un resultado que crear."""
        real = quarry.order_surfaces
        row, col = 200, 150
        self.assertTrue(bool(self.area[row, col]))

        def broken(*args: Any) -> Any:
            found = real(*args)
            final = found.final.copy()
            final[row, col] = found.exploitation[row, col] + 0.002
            return replace(found, final=final)

        seen: list[Any] = []
        with mock.patch.object(quarry, "order_surfaces", broken), \
                self.assertRaises(messages.DesignError) as caught:
            seen.extend(quarry.quarry_steps(self.job()))
        self.assertEqual(caught.exception.code, "des.quarry_order_broken")
        self.assertTrue(all(step.result is None for step in seen))
        x = self.geometry.west + (col + 0.5) * self.geometry.dx
        y = self.geometry.north - (row + 0.5) * self.geometry.dy
        self.assertEqual((caught.exception.values["x"], caught.exception.values["y"]),
                         (round(x, 2), round(y, 2)))
        self.assertIn("Cantera E3", caught.exception.obj)

    # --- El trabajo ------------------------------------------------------------------------------

    def test_the_job_gives_each_side_its_seeds_and_anchors(self) -> None:
        """``QuarryJob.side_job``: lo común a los dos lados (partida, máscaras, dominio, fondos,
        techo…) y lo de cada uno (sus semillas de la 013 y su rejilla de anclas). Errores del
        programa: un lado que no existe y unas semillas o una rejilla que no casan con su lado
        (los de ``side_steps``, al llamar)."""
        user = model.SeedSource("surface", surface=qfx.START_DATASET, zone=model.Zone("domain"))
        grid_side = side(EXPL, seeds=user, anchor="grid", anchor_grid="gis_dtm_anclas")
        crown = self.final_first.exploitation.seeds
        anchors = np.full(self.start.shape, EXPL.anchor_m)
        job = self.job(request=replace(self.request, exploitation=grid_side),
                       seeds={"exploitation": crown}, anchors={"exploitation": anchors})
        exploitation, final = job.side_job("exploitation"), job.side_job(model.Surface.FINAL)
        self.assertIs(exploitation.seeds, crown)
        self.assertIs(exploitation.anchors, anchors)
        self.assertIsNone(final.seeds)
        self.assertIsNone(final.anchors)
        for item in (exploitation, final):
            self.assertIs(item.request, job.request)
            self.assertIs(item.floors, self.floors)
            self.assertIs(item.ceiling, self.ceiling)
            self.assertIs(item.domain, self.domain)
        with self.assertRaises(ValueError):
            self.job(seeds={"bench": crown})
        with self.assertRaises(ValueError):
            quarry.quarry_steps(self.job(seeds={"final": crown}))
        with self.assertRaises(ValueError):
            quarry.quarry_steps(self.job(anchors={"final": anchors}))

    def test_the_exact_metric_is_refused_when_asked(self) -> None:
        """RF-014-12 (T45, hallazgo F-6): cada lado va con la pendiente de sus sectores y la
        euclídea exacta solo admite una pendiente constante, así que un lado con la exacta se
        rechaza al llamar, antes de calcular nada (ni el techo ni un lado), con su código
        —nunca ``des.exact_needs_constant_slope``, que manda a la orden de la 013—, nombrando la
        cantera y el lado (su campo, ``final.metric`` o ``exploitation.metric``, y su valor) y
        diciendo que se use el chamfer 5×5; con los dos lados, el de la final."""
        exact = {surface: replace(self.request.side(surface), metric="exact")
                 for surface in ("final", "exploitation")}
        cases = (({"final": exact["final"]}, "des.quarry_final_exact", "final"),
                 ({"exploitation": exact["exploitation"]}, "des.quarry_exploitation_exact",
                  "exploitation"),
                 (exact, "des.quarry_final_exact", "final"))
        for sides, code, surface in cases:
            with self.subTest(lados=sorted(sides)):
                with mock.patch.object(quarry, "side_steps", side_effect=AssertionError), \
                        self.assertRaises(messages.DesignError) as caught:
                    quarry.quarry_steps(self.job(request=replace(self.request, **sides)))
                error = caught.exception
                self.assertEqual((error.code, error.field, error.value),
                                 (code, f"{surface}.metric", "exact"))
                self.assertIn("«Cantera E3»", error.obj)
                self.assertIn("Cantera «Cantera E3»", error.text)
                self.assertIn("use el chamfer 5×5", error.text)
                english = messages.render(code, language="en", **error.values)
                self.assertIn("Quarry «Cantera E3»", english)
                self.assertIn("use the 5×5 chamfer", english)

    def test_each_side_is_compared_with_its_own_previous(self) -> None:
        """RF-014-12 con RF-013-30 de la 013 (spec 014, T51, hallazgo F-12 (g)): cada lado compara
        su desmonte y su terraplén con lo suyo de la cantera anterior (``QuarryJob.previous``, por
        superficie: ``side_job`` da a cada uno el suyo) y avisa con el nombre del lado
        (``des.magnitude_cut``); sin lo anterior, ningún lado dice que no se compara (lo dice la
        cantera, una vez: ``store.quarry_notices``), ni con un orden ni con el otro."""
        for outcome in (self.final_first, self.exploitation_first):
            for surface in model.Surface:
                with self.subTest(order=outcome.order, surface=surface):
                    codes = [n.code for n in outcome.side(surface).design.report.notices]
                    self.assertNotIn("des.magnitude_no_reference", codes)
        report = import_geoblender("design.report")
        final_before = report.Previous("Cantera E3 (superficie final)", "V01.r1", 5.0, 0.0)
        before = report.Previous("Cantera E3 (superficie de explotación)", "V01.r1", 1.0, 0.0)
        job = self.job(previous={"final": final_before, model.Surface.EXPLOITATION: before})
        self.assertIs(job.side_job(model.Surface.FINAL).previous, final_before)
        self.assertIs(job.side_job("exploitation").previous, before)
        self.assertIsNone(self.job().side_job("final").previous)
        with self.assertRaises(ValueError):
            self.job(previous={"bench": before})
        side = last_result(quarry.side_steps(job.side_job("exploitation")))
        alone = self.final_first.exploitation.design
        np.testing.assert_array_equal(side.design.design, alone.design)
        (warned,) = [n for n in side.design.report.notices if n.code == "des.magnitude_cut"]
        self.assertEqual(warned.values["operation"], "Cantera E3 (superficie de explotación)")
        self.assertEqual((warned.values["revision"], warned.values["previous"]), ("V01.r1", 1))
        self.assertEqual(warned.values["current"], round(alone.report.cut_m3))
        self.assertNotIn("des.magnitude_no_reference",
                         [n.code for n in side.design.report.notices])

    def test_closing_half_way_leaves_nothing(self) -> None:
        """§5.3.2: cerrar los pasos a mitad (Esc) no deja nada ni lanza nada."""
        steps = quarry.quarry_steps(self.job())
        for _step in range(3):
            next(steps)
        steps.close()

    def test_the_inputs_are_not_modified(self) -> None:
        """Ninguna entrada se modifica."""
        after = (self.start, self.floors.grid, self.ceiling.grid, self.area)
        for old, new in zip(self.inputs, after, strict=True):
            np.testing.assert_array_equal(old, new)


if __name__ == "__main__":
    unittest.main()
