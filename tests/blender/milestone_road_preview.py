# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de una pista con un proyecto de verdad, en Blender (spec 017, T28; HU-017-1; RF-017-26, RF-015-26, RF-017-09, RF-017-15, RF-017-17; RNF-017-06 y RNF-017-08; plan 017 §5.5 y §7.3;
comprobación manual M5), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_road_preview.py`` (los lotes y el ciclo de vida) y
``tests/unit/design/milestone_road_preview_data.py`` (lo que prepara ``design``).

El proyecto es **el de las pistas de las pruebas sin Blender** (``tests.support.road_data``: la cantera de la 015 con los terrenos como rejillas y las capas, en la de 2 m), el del hito H2
(``milestone_road_ce.RoadCETest``: lo abre la extensión, con el perfil de referencia y el de la «opción A15»), con la cadena **P1 → «Pista a P1» → «Ramal» → relleno** hecha con la orden real de la
plataforma y las funciones de la pista (las órdenes de la pista son de la fase G). Las pruebas, **en el orden de sus letras** sobre el mismo estado:

- **a**: la cadena.
- **b** (RF-017-26, RF-015-26; M5): la vista previa de **una pista de la versión** por su código con la orden real (``geoblender.des_entity_preview``): su eje guardado (``des_rdx_``), la rasante por
  tramos, los bordes de la sección y **lo que se le apoya** (el ramal y el relleno, con sus huellas y sus volúmenes, los de ``design.entities.dependents``); **no escribe nada** y el mismo control la quita.
- **c** (RF-017-26, RF-017-09): **antes de calcular** una pista «trazar» de la «opción A15» (la que pide el diálogo de «Pista…»): el origen, el destino y **el pasillo** de la ruta con lo que dice
  ``design`` (los mismos nodos que «Calcular»); sin escribir nada.
- **d** (RF-017-26, RF-017-17): **tras calcular** (``steps.road_run``): el eje, la rasante por tramos —los de más de pm en ámbar: 10,5 % de media frente a pm = 10 %, la «opción A15»— y los bordes, de lo que dejó
  «Calcular»; sin escribir nada.
- **e** (RF-015-26, RF-015-08): lo que rechazaría «Calcular» (la partida ya tiene dueño) es el aviso en lugar del dibujo.
- **f** (RF-017-26, RF-015-26): se quita al cancelar y **al conmutar a la interfaz de Blender** con el proyecto abierto, y ida y vuelta deja Blender como estaba; nada creado en la escena.
- **g** (RNF-017-08; plan §7.3): **con 20 pistas** (de 5.000 vértices: ``tests.support.road_data.scale_preview_lines``; la que se previsualiza y, apoyadas en ella, las otras 19 con sus huellas), sobre una
  superficie de 2,81 M celdas, activarla ≤ 1 s (la orden de dibujo, los pasos de su temporizador con los 5 ms de espera de cada uno) y cada redibujo ≤ 5 ms (``gpu`` y ``blf`` sustituidos: solo el
  Python de Geoblender); **medido sin la lectura del proyecto**, que la prepara ``design`` con la 013 y la 016 (la T34 lo mide entero con la orden de la fase G).
- **z** (principio 8): desactivar Geoblender con la vista previa activa lo quita todo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import statistics
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.blender import milestone_road_ce as road_ce
from tests.support import blender_ext
from tests.support import road_data as rd

PREVIEW = "geoblender.des_entity_preview"
MAX_PUMPS = 20_000
ACTIVATE_BUDGET_S = 1.0  # RNF-017-08
REDRAW_BUDGET_S = 0.005  # RNF-017-08
ACTIVATIONS = 5
REDRAWS = 120
REGION = (1920.0, 1080.0)
"""La región de la Vista 3D de los redibujos: la de la barra a 1920 px de las comprobaciones manuales."""
TICK_WAIT_S = 0.005  # bl.draw.entity.TICK_INTERVAL_S (lo comprueba la prueba)
NEW = "Pista A15 trazada"


def _module(name: str) -> Any:
    return road_ce._module(name)


class RoadPreviewMilestone(road_ce.RoadCETest):
    """Lo de ``RoadCETest`` (el proyecto de las pistas abierto por la extensión y sus ayudantes; sus pruebas no se repiten) con la vista previa."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.entity = _module("bl.draw.entity")
        cls.design_draw = _module("bl.draw.design")
        cls.constraints = _module("bl.draw.constraints")
        cls.dpreview = _module("design.preview")
        cls.switcher = _module("bl.ui.switcher")
        cls.road_steps = _module("design.steps")
        cls.addClassCleanup(cls.entity.disable)

    def tearDown(self) -> None:
        if self.entity.enabled():  # lo que deja una prueba que falla no pasa a la siguiente
            self.entity.disable()
        super().tearDown()

    # --- Ayudas -------------------------------------------------------------------------------

    def untouched(self) -> tuple[Any, ...]:
        """Lo que la vista previa no cambia: el proyecto (operaciones, datos, parámetros, cifras y ficheros) y la escena (objetos, mallas y colecciones)."""
        project = (self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid"), self.rows("SELECT name, status FROM gb_dataset ORDER BY name"),
                   self.rows("SELECT key, scope, value FROM gb_parameter ORDER BY fid"), self.rows("SELECT count(*) FROM gb_figure"),
                   sorted(path.name for path in (Path(self.project.root) / "rasters").iterdir()))
        return (project, len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.collections))

    def pump(self) -> Any:
        """Los pasos de la construcción, uno por llamada del temporizador (en ``blender -b`` no corren) hasta que acaba: lo construido."""
        for _ in range(MAX_PUMPS):
            if self.entity.tick() is None:
                built = self.entity.built()
                self.assertIsNotNone(built, "la vista previa no construyó nada")
                return built
        self.fail("la vista previa no acaba de construirse")

    @staticmethod
    def batch(built: Any, key: str) -> Any:
        return next((batch for batch in built.lines.batches if batch.key == key), None)

    def show(self, plan: Any) -> Any:
        """Activa la vista previa de ``plan`` y la lleva hasta el final: lo construido."""
        self.entity.enable(plan)
        return self.pump()

    def a15_trace(self) -> Any:
        """La pista «trazar» de la «opción A15» (el terreno del 10,5 % con el perfil de pd = 12 %): de «Origen rampa» a «Destino rampa»."""
        return self.road_request(NEW, surface=road_ce.A15, profile=road_ce.A15_PROFILE.lower(), origin="Origen rampa", destination="Destino rampa")

    # --- a: la cadena -----------------------------------------------------------------------------

    def test_a_the_chain_of_the_platform_the_road_the_branch_and_the_fill_is_made(self) -> None:
        """La cadena P1 → «Pista a P1» (``RDW-001``) → «Ramal» (``RDW-002``) → el relleno sobre la calzada (``PLT-002``): las cuatro «al día» (como el E1 del hito H2) y las máscaras de V01 compiladas."""
        self.platform_made(name=road_ce.PLATFORM, feature=road_ce.PLATFORM, start=road_ce.RAMP)
        asked = self.road_request(road_ce.FIRST, layer=road_ce.PLATFORM_LAYER, origin="Entrada", destination="entity:PLT-001", surface="entity:PLT-001")
        self.road_made(asked)
        self.road_made(self.road_request(road_ce.SECOND, origin="RDW-001@100", destination="Destino del ramal", surface="entity:RDW-001"))
        self.platform_made(name=road_ce.FILL, layer=rd.PLATFORMS_LAYER, feature=road_ce.FILL, start="entity:RDW-002", mode="CUT_FILL", reach="20")
        self.assertEqual(self.states(), {"PLT-001": "current", "RDW-001": "current", "RDW-002": "current", "PLT-002": "current"})
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})  # las máscaras al día para preparar una pista nueva
        self.masks = _module("gis.masks.access").load_masks(self.project, self.v01.uid)

    # --- b: una pista de la versión ---------------------------------------------------------------

    def test_b_a_road_of_the_version_is_previewed_by_its_code_with_what_rests_on_it(self) -> None:
        """RF-017-26, RF-015-26, RF-015-15 (M5): ``geoblender.des_entity_preview`` con el código de la pista de la versión dibuja su eje **guardado** (el de su ``des_rdx_``, bit a bit), la rasante en
        tramos (el perfil de referencia: pd = pm = 10 %, la rampa va al 4 %: todos dentro), los dos bordes de la sección (11,5 m) y lo que se le apoya —**el ramal y el relleno**, con sus huellas y sus
        volúmenes, los mismos de ``design.entities.dependents``—, con su leyenda y su resumen en los dos idiomas; **no escribe nada**; el mismo control la quita."""
        entity = self.entity
        before = self.untouched()
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="RDW-001"), {"FINISHED"})
        self.assertEqual(entity.plan().kind, "road")
        built = self.pump()
        found = entity.preview()
        stations, levels = self.axis_levels(road_ce.FIRST)
        locator = self.dprov.dataset_locator(self.dprov.ROAD_AXIS_TABLE, road_ce.FIRST, self.v01.code)
        points = np.array(self.rows(f'SELECT x, y FROM "{locator}" ORDER BY fid'), dtype=np.float64)
        np.testing.assert_array_equal(found.stations, stations)
        np.testing.assert_array_equal(found.levels, levels)
        np.testing.assert_array_equal(found.axis, points)
        self.assertTrue(found.calculated and found.drawable)
        self.assertEqual((found.code, found.mode, found.max_gradient_pct, found.max_mean_gradient_pct, found.section_m, found.carriageway_m),
                         ("RDW-001", "trace", rd.PROFILE.max_gradient_pct, rd.PROFILE.max_mean_gradient_pct, rd.PROFILE.section_m, rd.PROFILE.carriageway_m))
        self.assertTrue(all(item.status is self.dpreview.GradientStatus.WITHIN for item in found.stretches))
        count = len(stations) - 1
        self.assertEqual(self.batch(built, entity.AXIS).segments, count)
        self.assertEqual(sum(self.batch(built, key).segments for key in (entity.GRADIENT_WITHIN, entity.GRADIENT_MEAN, entity.GRADIENT_DESIGN) if self.batch(built, key)), count)
        self.assertEqual(self.batch(built, entity.SECTION).segments, 2 * count)
        self.assertGreaterEqual(self.batch(built, entity.ARROW).segments, 2)  # sus dos rayas, partidas para seguir la superficie
        listed = {row.name: row for row in self.entities.dependents(self.project, self.v01.uid, "RDW-001")}
        self.assertEqual(sorted(listed), sorted([road_ce.SECOND, road_ce.FILL]))
        self.assertEqual({item.name: item.volume_m3 for item in found.resting}, {name: row.volume_m3 for name, row in listed.items()})
        self.assertTrue(all(item.rings for item in found.resting), "los dos tienen huella")
        self.assertGreater(self.batch(built, entity.RESTING).segments, 8)
        names = [label.text for label in built.lines.labels]
        self.assertTrue(any(text.startswith(f"«{road_ce.SECOND}» · ") for text in names), names)
        self.assertTrue(any(text.startswith(f"«{road_ce.FILL}» · ") for text in names), names)
        self.assertTrue(built.summary[0][0].startswith(f"Vista previa de «{road_ce.FIRST}» (RDW-001) en V01: eje de {found.length_m:.1f} m guardado en la versión".replace(".", ",")), built.summary[0][0])
        self.assertEqual([item.code for item in found.notices][:2], ["des.preview_road_stored", "des.preview_entity_supported"])
        self.assertTrue(all("{" not in text for language in ("es", "en") for text, _alert in found.lines(language)))
        self.assertEqual(self.untouched(), before, "la vista previa no escribe")
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT"), {"FINISHED"})  # el mismo control la quita
        self.assertFalse(entity.enabled() or entity.drawing())

    # --- c: antes de calcular --------------------------------------------------------------------

    def test_c_before_calculating_a_trace_road_draws_the_origin_the_destination_and_the_corridor(self) -> None:
        """RF-017-26, RF-017-09, RF-015-26 (M5): la pista «trazar» que prepara el diálogo (la «opción A15» de «Origen rampa» a «Destino rampa»): el origen y el destino en cruz con su cota, el pasillo de la
        ruta —**los mismos nodos que «Calcular»** (``RouteReport.corridor_nodes``)— y su cota inferior, y la leyenda con su holgura; sin eje; y **nada escrito** (ni la base, ni los datos, ni los
        parámetros, ni los ficheros)."""
        entity = self.entity
        before = self.untouched()
        asked = self.a15_trace()
        built = self.show(entity.EntityPlan(road=self.dpreview.RoadAsk(request=asked)))
        found = entity.preview()
        self.assertIsNone(found.refusal, found.lines("es"))
        self.assertEqual((found.mode, found.start_surface, found.calculated), ("trace", road_ce.A15, False))
        self.assertEqual([batch.key for batch in built.lines.batches], [entity.CORRIDOR, entity.ORIGIN, entity.DESTINATION])
        self.assertEqual({item.which for item in found.points}, {"origin", "destination"})
        calculation = _last_calculation(self.road_steps.road_run(self.project, asked, version=self.v01.uid, masks=self.masks))
        self.assertEqual(found.corridor_nodes, calculation.outcome.route.corridor_nodes)
        self.assertAlmostEqual(found.lower_bound_m, calculation.outcome.route.lower_bound_m, delta=1e-9)
        calculation.discard()
        text = [row.text for row in built.lines.legend]
        self.assertTrue(any(row.startswith("Pasillo de la ruta (") and f"holgura de {rd.ROUTE.margin_m:,.1f}".replace(".", ",") in row for row in text), text)
        self.assertEqual([alert for _text, alert in built.summary], [False, False])
        self.assertEqual(self.untouched(), before, "la vista previa no escribe")
        entity.disable()

    # --- d: tras calcular ---------------------------------------------------------------------------

    def test_d_after_calculating_the_stretches_above_pm_are_painted_from_what_calculate_left(self) -> None:
        """RF-017-26, RF-017-15, RF-017-17 (M5): tras «Calcular» (``steps.road_run``), la vista previa dibuja lo que dejó —el eje, la rasante y la sección del resultado, **sin repetir la preparación**— con la
        «opción A15» al 10,5 % de media frente a pm = 10 %: **los tramos de más de pm en ámbar** (y ninguno por encima de pd = 12 %) y el resto dentro, cada lote con los tramos de su estado, la flecha y los
        bordes de la sección; la leyenda dice pm; no escribe nada."""
        entity = self.entity
        before = self.untouched()
        asked = self.a15_trace()
        calculation = _last_calculation(self.road_steps.road_run(self.project, asked, version=self.v01.uid, masks=self.masks))
        built = self.show(entity.EntityPlan(road=self.dpreview.RoadAsk(request=asked, prepared=calculation.entity, outcome=calculation.outcome)))
        found = entity.preview()
        outcome = calculation.outcome
        np.testing.assert_array_equal(found.axis, outcome.axis.points)
        np.testing.assert_array_equal(found.levels, outcome.levels)
        self.assertTrue(found.calculated)
        self.assertEqual(found.corridor, (), "no es de después de calcular")
        status = self.dpreview.GradientStatus
        pm, pd = found.max_mean_gradient_pct, found.max_gradient_pct
        self.assertEqual((pm, pd), (rd.PROFILE.max_mean_gradient_pct, 12.0))
        for item in found.stretches:  # el estado de cada tramo es el que dicen sus cifras: ninguno por encima de pd, y por encima de pm solo los de media > 10 %
            self.assertLessEqual(item.max_gradient_pct, pd + 1e-9)
            self.assertIs(item.status, status.ABOVE_MEAN if item.gradient_pct > pm + 1e-9 else status.WITHIN, item)
        self.assertIn(status.ABOVE_MEAN, {item.status for item in found.stretches}, "la media de la pista pasa de pm: algún tramo va por encima")
        self.assertEqual({batch.key for batch in built.lines.batches}, {entity.SECTION, entity.GRADIENT_WITHIN, entity.GRADIENT_MEAN, entity.AXIS, entity.ARROW, entity.ORIGIN, entity.DESTINATION})
        self.assertEqual(self.batch(built, entity.GRADIENT_MEAN).color, entity.GRADIENT_COLORS[entity.GRADIENT_MEAN])
        for key, wanted in ((entity.GRADIENT_MEAN, status.ABOVE_MEAN), (entity.GRADIENT_WITHIN, status.WITHIN)):
            self.assertEqual(self.batch(built, key).segments, sum(item.last - item.first for item in found.stretches if item.status is wanted), key)
        self.assertIn("Tramo con la pendiente media por encima de la media máxima pm (10,0 %)", [row.text for row in built.lines.legend])
        calculation.discard()
        self.assertEqual(self.untouched(), before, "la vista previa no escribe")
        entity.disable()

    # --- e: lo que rechazaría «Calcular» ---------------------------------------------------------------

    def test_e_what_calculating_would_refuse_is_the_warning_instead_of_the_drawing(self) -> None:
        """RF-015-26, RF-015-08, RF-015-04 (M5): una pista que parte de la superficie de otra entidad (la «Pista a P1» parte de ``P1`` y ahora otra pide la misma) se rechaza al calcular con
        ``des.entity_start_taken``; la vista previa dice **lo mismo**, en alerta y en lugar del dibujo, sin escribir nada."""
        entity = self.entity
        before = self.untouched()
        asked = self.road_request("Otra desde la rampa", origin="Origen rampa", destination="Destino rampa", surface=road_ce.RAMP)
        built = self.show(entity.EntityPlan(road=self.dpreview.RoadAsk(request=asked)))
        found = entity.preview()
        self.assertEqual(found.refusal.code, "des.entity_start_taken")
        self.assertEqual(built.lines.batches, ())
        self.assertEqual([alert for _text, alert in built.summary], [True])
        with self.assertRaises(_module("design.messages").DesignError) as caught:
            _last_calculation(self.road_steps.road_run(self.project, asked, version=self.v01.uid, masks=self.masks))
        self.assertEqual(built.summary[0][0], caught.exception.text)
        self.assertEqual(self.untouched(), before)
        entity.disable()

    # --- f: quitarla -----------------------------------------------------------------------------

    def test_f_it_is_removed_by_leaving_for_the_blender_interface_with_the_project_open(self) -> None:
        """RF-015-26, RF-017-26 (M5): **al conmutar a la interfaz de Blender** (``switcher.add_blender_hook``), con el proyecto abierto y la vista previa de una pista de la versión construida, se quita; ida y
        vuelta deja Blender como estaba (los manejadores de dibujo, el temporizador y los ganchos) y volver no la pone sola; nada creado en la escena ni escrito en el proyecto."""
        entity, switcher = self.entity, self.switcher
        before_fingerprint = blender_ext.state_fingerprint()
        before = self.untouched()
        self.show(entity.EntityPlan(road=self.dpreview.RoadAsk(code="RDW-001")))
        self.assertTrue(entity.enabled() and entity.drawing())
        self.assertIn(entity.disable, switcher.blender_hooks())
        window = bpy.context.window_manager.windows[0]
        self.addCleanup(switcher.forget)
        with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
            self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        other_space = next(space.name for space in bpy.data.workspaces if space.name != window.workspace.name)
        with mock.patch.object(switcher, "_marked", return_value={other_space}):
            self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other_space)
        self.assertFalse(entity.enabled(), "volver no la pone sola")
        diff = blender_ext.fingerprint_diff(before_fingerprint, blender_ext.state_fingerprint())
        mine = [line for line in diff if line.startswith(("draw_handlers", "handlers", "timers")) and "switcher" not in line]
        self.assertEqual(mine, [], diff)
        self.assertEqual(self.untouched(), before)

    # --- g: con 20 pistas (RNF-017-08) ----------------------------------------------------------------

    def twenty_roads(self) -> tuple[Any, Any]:
        """La vista previa de la primera de las 20 pistas de 5.000 vértices (su eje por estaciones, su rasante del 4 %, sus tramos y sus bordes) con las otras 19 apoyadas en ella, cada una con la huella de
        su sección (el contorno de sus dos bordes: 10.000 vértices), y la superficie de 2,81 M celdas (un plano) sobre la que se dibuja (junto al GeoOrigin del proyecto)."""
        lines = rd.scale_preview_lines()
        origin = self.project.origin
        lines[:, :, 0] += origin.x0 + 50.0 - lines[0, 0, 0]  # las pistas de la rejilla de escala, junto al GeoOrigin del proyecto
        lines[:, :, 1] += origin.y0 + 50.0 - lines[0, 0, 1]
        dp = self.dpreview
        resting = []
        for index in range(1, rd.SCALE_ROADS):
            left, right = dp.section_edges(lines[index, :, :2], 5.75)
            ring = np.vstack([left, right[::-1], left[:1]])
            resting.append(dp.RestingItem(f"Pista {index + 1}", f"RDW-{index + 1:03d}", "des.road", "current", 1000.0 + index, (ring,)))
        points = lines[0, :, :2]
        stations = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(points, axis=0).T))])
        levels = lines[0, :, 2]
        found = dp.RoadPreview(
            "Pista 1", "RDW-001", "V01", _module("gis.masks.access").MaskState.CURRENT, mode="trace", start_surface="Escala", profile="PISTA_PRINCIPAL", cell_m=1.0,
            points=(dp.RoadPoint("origin", *points[0], float(levels[0])), dp.RoadPoint("destination", *points[-1], float(levels[-1]))), calculated=True, axis=points, stations=stations,
            levels=levels, edges=dp.section_edges(points, 5.75), length_m=float(stations[-1]), gradient_mean_pct=100.0 * float(abs(np.diff(levels)).sum() / stations[-1]),
            carriageway_m=10.5, section_m=11.5, max_gradient_pct=10.0, max_mean_gradient_pct=10.0, stretches=dp.gradient_stretches(stations, levels, 10.0, 10.0), resting=tuple(resting))
        grid = _module("gis.grid").Grid(west=float(origin.x0 - 50), north=float(origin.y0 + 1_650), dx=1.0, dy=1.0, ncols=1_654, nrows=1_699)
        x = grid.west + (np.arange(grid.ncols) + 0.5)
        plane = np.broadcast_to(120.0 + 0.04 * (x - grid.west), grid.shape).copy()
        crs, vertical = _module("gis.store").project_references(self.project)
        surface = self.constraints.Surface("Escala", _module("gis.raster").Raster(grid, plane, crs, vertical))
        return found, surface

    def test_g_with_twenty_roads_it_activates_in_a_second_and_each_redraw_takes_five_milliseconds(self) -> None:
        """RNF-017-08 (plan 017 §7.3; M5): con **20 pistas de 5.000 vértices** —la que se previsualiza (su eje, 40 tramos, sus bordes) y las otras 19 apoyadas en ella con la huella de su sección—, sobre una
        superficie de 2,81 M celdas, **activarla ≤ 1 s** (mediana de 5: ``enable``, los pasos de su temporizador con los 5 ms de espera de cada uno, los lotes sobre la superficie, los nombres y la leyenda) y
        **cada redibujo ≤ 5 ms** (los lotes, los nombres, la leyenda y el resumen, con ``gpu`` y ``blf`` sustituidos: solo el Python de Geoblender; la GPU de verdad es de la comprobación manual M5).
        Se mide el CPU de preparar el lote; la lectura del proyecto la hace ``design`` (la 013 y la 016 la miden) y la T34 la mide entera con la orden de la fase G."""
        entity, constraints = self.entity, self.constraints
        found, surface = self.twenty_roads()
        self.assertEqual(entity.TICK_INTERVAL_S, TICK_WAIT_S)
        plan = entity.EntityPlan(road=self.dpreview.RoadAsk(code="RDW-001"))

        def activate() -> tuple[float, float, int, Any]:
            self.assertFalse(entity.enabled())
            started, cpu = time.perf_counter(), time.process_time()
            with (mock.patch.object(self.dpreview, "road_preview_steps", side_effect=_steps_of(found)), mock.patch.object(entity, "stamp", return_value=("sello",)),
                  mock.patch.object(constraints, "ground_steps", side_effect=_ground_of(surface))):
                entity.enable(plan)
                ticks = 0
                for _ in range(MAX_PUMPS):
                    ticks += 1
                    if entity.tick() is None:
                        break
                else:
                    self.fail("la vista previa no acaba de construirse")
            wall = time.perf_counter() - started + TICK_WAIT_S * max(0, ticks - 1)
            built = entity.built()
            self.assertIsNotNone(built)
            return wall, time.process_time() - cpu, ticks, built

        cold = activate()
        entity.disable()
        found_runs = []
        for _ in range(ACTIVATIONS):
            found_runs.append(activate())
            entity.disable()
        walls = [item[0] for item in found_runs]
        wall = statistics.median(walls)
        built = activate()[3]
        segments = sum(batch.segments for batch in built.lines.batches)
        self.assertGreaterEqual(self.batch(built, entity.RESTING).segments, 19 * 10_000, "las otras 19, con su huella")
        self.assertEqual(self.batch(built, entity.AXIS).segments, 4_999)
        report = (f"RNF-017-08: activar la vista previa de una pista con {rd.SCALE_ROADS} pistas de {rd.SCALE_ROAD_VERTICES:,} vértices (la que se previsualiza y {rd.SCALE_ROADS - 1} apoyadas en ella con "
                  f"la huella de su sección: {len(built.lines.batches)} lotes, {segments:,} segmentos, {len(built.lines.labels)} nombres), sobre una superficie de 2,81 M celdas: mediana de {ACTIVATIONS} "
                  f"{wall:.3f} s (la peor {max(walls):.3f} s; la primera, en frío, {cold[0]:.3f} s en {cold[2]} pasos) frente a {ACTIVATE_BUDGET_S:.1f} s")
        print(report)
        self.assertLessEqual(wall, ACTIVATE_BUDGET_S, report)

        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        sx, sy = 1.0 / 800.0, REGION[0] / (REGION[1] * 800.0)
        local = (800.0, 800.0)
        matrix = np.array([[sx, 0.0, 0.0, -local[0] * sx], [0.0, sy, 0.0, -local[1] * sy], [0.0, 0.0, -0.001, 0.0], [0.0, 0.0, 0.0, 1.0]])
        view = {"view_matrix": Matrix.Identity(4), "projection_matrix": Matrix.Identity(4), "perspective": True, "view_distance": 100.0, "viewport_size": REGION, "pixel_size": 1.0}
        redraws: list[float] = []
        with mock.patch.object(constraints, "gpu", gpu), mock.patch.object(constraints, "batch_for_shader") as lots:
            for index in range(REDRAWS):
                started = time.perf_counter()  # el reloj de CPU de Windows mide de 16 ms en 16 ms: aquí, el de pared
                drawn = constraints.draw_lines(built.lines, **view)
                items = self.design_draw.screen_items(built, matrix, REGION, measure=lambda text: 7.0 * len(text), scale=1.0)
                if index >= 20:  # los primeros: los lotes de gpu se crean una vez
                    redraws.append(time.perf_counter() - started)
            self.assertEqual((drawn, lots.call_count), (len(built.lines.batches),) * 2)
        percentile = sorted(redraws)[int(0.95 * len(redraws))]
        again = (f"RNF-017-08: cada redibujo de la vista previa con {rd.SCALE_ROADS} pistas ({len(built.lines.batches)} lotes, {segments:,} segmentos, {len(built.lines.labels)} nombres, "
                 f"{len(items)} elementos en pantalla; región de {REGION[0]:.0f} × {REGION[1]:.0f} px): mediana {statistics.median(redraws) * 1000:.3f} ms, p95 {percentile * 1000:.3f} ms, la peor "
                 f"{max(redraws) * 1000:.3f} ms frente a {REDRAW_BUDGET_S * 1000:.0f} ms")
        print(again)
        self.assertGreater(len(items), 10)
        self.assertLessEqual(statistics.median(redraws), REDRAW_BUDGET_S, again)
        self.assertLessEqual(percentile, REDRAW_BUDGET_S, again)  # y el percentil 95: la carga ajena no cuenta de más
        entity.disable()

    # --- z: Geoblender se desactiva ----------------------------------------------------------------------

    def test_z_disabling_geoblender_with_the_preview_of_a_road_on_leaves_nothing(self) -> None:
        """Principio 8: con la vista previa de una pista de la versión activa, desactivar Geoblender quita los manejadores de dibujo, los ganchos, el temporizador y los lotes, y la huella de Blender
        vuelve a la del principio de la sesión."""
        entity = self.entity
        entity.enable(entity.EntityPlan(road=self.dpreview.RoadAsk(code="RDW-001")))
        self.assertTrue(entity.drawing())
        self.assertTrue(bpy.app.timers.is_registered(entity.tick))
        blender_ext.release()
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


def _last_calculation(work: Any) -> Any:
    """La ``Calculation`` que lleva el último paso de ``work``."""
    found = None
    for step in work:
        found = step.result if step.result is not None else found
    assert found is not None
    return found


def _steps_of(found: Any) -> Any:
    """Lo que sustituye a ``design.preview.road_preview_steps``: un solo paso, que lleva ``found`` (la lectura del proyecto no se mide aquí)."""
    def steps(_project: Any, _ask: Any, _version_uid: str, *, budget_s: float = 0.0) -> Any:
        return iter([_module("core.project.model").Progress("preview_road", 1, 1, "Vista previa de la pista lista", result=found)])

    return steps


def _ground_of(surface: Any) -> Any:
    """Lo que sustituye a ``bl.draw.constraints.ground_steps``: la superficie ``surface`` ya hecha (sin leerla del proyecto)."""
    def ground(*_args: Any, **_kwargs: Any) -> Any:
        return surface
        yield  # noqa: B901 - lo hace un generador

    return ground


for _name in dir(road_ce.RoadCETest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_") and _name not in vars(RoadPreviewMilestone):
        setattr(RoadPreviewMilestone, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
