# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de una corta en la Vista 3D (spec 018, T29; HU-018-1, HU-018-4; RF-018-32, RF-015-26; RNF-018-08; plan 018 §5.5; comprobación manual M3; principio 8).

La vista previa (``bl.draw.entity`` con ``EntityPlan(pit=…)``; los lotes los arma ``bl.draw.pit``) es un manejador de dibujo **sin objetos ni escritura**: lo que dibuja se prueba en sus lotes (sin
``gpu``: ``docs/trampas.md`` §3), sus nombres y su leyenda. Aquí, **sin proyecto**: una ``design.preview.PitPreview`` sintética entra por ``pit_preview_steps`` y sale en lotes.

- RF-018-32 (a): **antes de calcular**, los polígonos, los sectores, una flecha por rango de la roseta con su nombre, el punto de inicio de las rampas, las zonas sin rampa y los bancos fijados.
- RF-018-32 (b): **tras calcular**, las polilíneas **a su cota** coloreadas por banco (la paleta da la vuelta) o por tipo, la línea de cielo, el eje de la rampa con su flecha y cada hallazgo en su lugar,
  con la leyenda y el resumen, en los dos idiomas.
- RF-018-32, RF-015-08 (c): el rechazo de «Calcular» y las máscaras sin compilar son el aviso en lugar del dibujo.
- RF-015-26 (d): la orden ``geoblender.des_entity_preview`` ofrece una corta de la versión por su código; una vista previa es de una sola cosa.
- RF-015-26, RF-018-32 (e): activarla pone los manejadores y el temporizador, la construye por pasos y **se quita** con su control, al cambiar de proyecto y al conmutar a la interfaz de Blender.
- Principio 8 (z): desactivar Geoblender con la vista previa de una corta activa lo quita todo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Generator
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name

WEST, SOUTH, GROUND_M = 700_000, 4_400_000, 100
ORIGIN = SimpleNamespace(x0=WEST, y0=SOUTH, z0=GROUND_M)
VERSION = SimpleNamespace(uid="uid-v01", code="V01")
MAX_PUMPS = 2_000


def _module(name: str) -> Any:
    return importlib.import_module(f"{module_name()}.{name}")


def _no_ground(*_args: Any, **_kwargs: Any) -> Generator[None, None, None]:
    return None
    yield  # noqa: B901 - lo hace un generador


class PitPreviewTest(unittest.TestCase):
    """La extensión habilitada una vez; la vista previa se prueba con datos de ``design`` hechos a mano y los pasos de su preparación sustituidos."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        for name, module in (("entity", "bl.draw.entity"), ("pit", "bl.draw.pit"), ("constraints", "bl.draw.constraints"), ("dpreview", "design.preview"), ("switcher", "bl.ui.switcher"),
                             ("ps", "bl.scene.project_session"), ("scene_versions", "bl.scene.versions"), ("i18n", "core.i18n"), ("des_ops", "bl.ops.des"), ("entities", "design.entities"), ("access", "gis.masks.access"),
                             ("model", "core.project.model"), ("pit_model", "design.pit_model"), ("messages", "design.messages")):
            setattr(cls, name, _module(module))
        cls.addClassCleanup(cls.entity.disable)

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        if self.entity.enabled():
            self.entity.disable()

    # --- Datos --------------------------------------------------------------------------------

    def absolute(self, x: float, y: float) -> tuple[float, float]:
        return (WEST + x, SOUTH + y)

    def ring(self, size: float, x: float = 100.0, y: float = 100.0) -> np.ndarray:
        return np.array([self.absolute(x, y), self.absolute(x + size, y), self.absolute(x + size, y + size), self.absolute(x, y + size)])

    def line(self, kind: str, bench: int, z: float, size: float = 20.0) -> Any:
        ring = self.ring(size)
        return self.dpreview.PitLine(kind, bench, np.column_stack([ring, np.full(len(ring), z)]), True)

    def before(self) -> Any:
        dp = self.dpreview
        arrows = tuple(dp.PitArrow(WEST + 110.0, SOUTH + 110.0, az, 6.0, az - 45.0, az + 45.0, 60.0, 6.0) for az in (45.0, 135.0, 225.0, 315.0))
        fixed = dp.PitLine("fixed", 2, np.column_stack([self.ring(10.0, 130.0, 100.0), np.full(4, 145.0)]), True)
        return dp.PitPreview("Corta 1", "PIT-001", "V01", self.access.MaskState.CURRENT, mode="up", start_surface="terreno", cell_m=2.0, sources=(dp.PitShape("fondo", (self.ring(20.0),), 125.0),),
                             sectors=(dp.PitShape("Sector norte", (self.ring(8.0, 102.0, 102.0),)),), arrows=arrows, starts=(dp.PitStart("rampa", WEST + 105.0, SOUTH + 105.0, "Inicio A"),),
                             noramp=(self.ring(4.0, 112.0, 112.0),), fixed=(fixed,),
                             notices=(dp.Notice("des.preview_pit_before", {"entity": "Corta 1", "code": "PIT-001", "version": "V01", "surface": "terreno", "sources": 1, "arrows": 4, "starts": 1,
                                                                            "noramp": 1, "fixed": 1}),))

    def after(self, by: str = "bench", benches: int = 3) -> Any:
        dp = self.dpreview
        lines = []
        for number in range(1, benches + 1):
            lines += [self.line("foot", number, 120.0 + 10.0 * number), self.line("crest", number, 130.0 + 10.0 * number)]
        axis = np.array([[WEST + 100.0, SOUTH + 100.0, 125.0], [WEST + 110.0, SOUTH + 100.0, 127.0], [WEST + 120.0, SOUTH + 100.0, 129.0]])
        finding = self.pit_model.Finding("berm_width", 3.0, 6.0, (WEST + 105.0, SOUTH + 107.0), bench=2)
        sky = dp.PitLine("sky", None, np.array([[WEST + 100.0, SOUTH + 100.0, 170.0], [WEST + 120.0, SOUTH + 100.0, 171.0], [WEST + 120.0, SOUTH + 120.0, 172.0]]), False)
        return dp.PitPreview("Corta 1", "PIT-001", "V01", self.access.MaskState.CURRENT, mode="up", start_surface="terreno", cell_m=2.0, by=by, calculated=True, polylines=tuple(lines),
                             skyline=(sky,), ramps=(dp.PitRampLine("rampa", 1, axis, 20.0, 10.0, 10.0),), findings=(finding,), bench_numbers=tuple(range(1, benches + 1)), cut_m3=12345.0,
                             notices=(dp.Notice("des.preview_pit_calculated", {"entity": "Corta 1", "code": "PIT-001", "version": "V01", "benches": benches, "cut": 12345.0, "ramps": 1,
                                                                                "findings": 1, "by": by}),))

    def request(self, *, version: Any = VERSION, language: str = "es") -> Any:
        plan = self.entity.EntityPlan(pit=self.dpreview.PitAsk(request=object()))
        return self.entity.Request(SimpleNamespace(origin=ORIGIN), None if version is None else version.uid, "" if version is None else version.code, plan, language, ("sello",))

    def build(self, found: Any, **options: Any) -> Any:
        def steps(_project: Any, _ask: Any, _uid: str, *, budget_s: float = 0.0) -> Any:
            return iter([self.model.Progress("preview_pit", 1, 1, "lista", result=found)])
        with mock.patch.object(self.dpreview, "pit_preview_steps", side_effect=steps), mock.patch.object(self.constraints, "ground_steps", side_effect=_no_ground):
            work = self.entity.build_steps(self.request(**options))
            while True:
                try:
                    next(work)
                except StopIteration as done:
                    return done.value

    @staticmethod
    def batch(built: Any, key: str) -> Any:
        return next((batch for batch in built.lines.batches if batch.key == key), None)

    def local(self, batch: Any) -> np.ndarray:
        return batch.positions.astype(np.float64) + [ORIGIN.x0, ORIGIN.y0, ORIGIN.z0]

    # --- (a) antes de calcular ------------------------------------------------------------------

    def test_a_before_calculating_it_draws_polygons_sectors_arrows_start_zones_and_fixed_benches(self) -> None:
        """RF-018-32 (M3): antes de calcular, un lote por pieza en su orden de dibujo (los de debajo primero): polígono (4 lados), sector (4), zona sin rampa (4), banco fijado (4, a su cota), las 4 flechas
        (cada una con su asta y las 2 rayas de su punta: 12 segmentos) y la cruz del inicio (2); sin polilíneas; los nombres de las flechas dicen su rango, α y B; la leyenda las lleva."""
        pit = self.pit
        built = self.build(self.before())
        keys = [batch.key for batch in built.lines.batches]
        self.assertEqual(keys, [pit.SOURCE, pit.SECTOR, pit.NORAMP, pit.FIXED, pit.ARROW, pit.START])
        self.assertEqual([self.batch(built, key).segments for key in keys], [4, 4, 4, 4, 12, 2])
        fixed = self.local(self.batch(built, pit.FIXED))
        np.testing.assert_allclose(fixed[:, 2], 145.0, atol=1e-4)
        np.testing.assert_allclose(self.local(self.batch(built, pit.SOURCE))[:, 2], GROUND_M, atol=1e-6)  # sin superficie: a la cota del GeoOrigen
        names = [label.text for label in built.lines.labels]
        self.assertIn("Inicio de «rampa»: Inicio A", names)
        arrows = [text for text in names if text.startswith("Cara hacia")]
        self.assertEqual(len(arrows), 4)
        self.assertEqual(arrows[0], "Cara hacia 45° · α 60° · B 6 m (0° a 90°)")
        legend = [row.text for row in built.lines.legend]
        self.assertEqual(legend[0], "Vista previa de «Corta 1» (PIT-001) · V01")
        self.assertIn("Dirección de la cara de cada rango de la roseta: hacia donde baja", legend)
        self.assertEqual(legend[-1], "A la cota del GeoOrigin")
        self.assertEqual([alert for _text, alert in built.summary], [False])

    # --- (b) tras calcular ------------------------------------------------------------------------

    def test_b_after_calculating_polylines_by_bench_or_by_type_the_skyline_the_ramp_and_the_findings(self) -> None:
        """RF-018-32 (M3): tras calcular, las polilíneas a su propia cota (4 lados cada una) en lotes por banco (la paleta da la vuelta) o por tipo (pie y cresta), la línea de cielo (2 tramos), el eje de la
        rampa (2) con su flecha (2) y cada hallazgo en su lugar (cruz de 2 rayas) con su nombre; la leyenda y el resumen, en español y en inglés; nada de lo de antes de calcular."""
        pit = self.pit
        built = self.build(self.after())
        keys = [batch.key for batch in built.lines.batches]
        self.assertEqual(keys, [pit.bench_key(1), pit.bench_key(2), pit.bench_key(3), pit.SKY, pit.RAMP, pit.RAMP_ARROW, pit.FINDING])
        self.assertEqual([self.batch(built, key).segments for key in keys], [8, 8, 8, 2, 2, 2, 2])
        np.testing.assert_allclose(sorted(set(np.round(self.local(self.batch(built, pit.bench_key(2)))[:, 2], 4))), [140.0, 150.0], atol=1e-4)
        self.assertEqual(len({self.batch(built, pit.bench_key(number)).color for number in (1, 2, 3)}), 3)
        self.assertEqual(pit.bench_key(1), pit.bench_key(1 + len(pit.BENCH_COLORS)), "la paleta da la vuelta")
        names = [label.text for label in built.lines.labels]
        self.assertIn("Berma real menor que la pedida: 3,0 m (límite 6,0 m) · banco 2", names)
        self.assertIn("Rampa «rampa»: 20,0 m · 10,0 % de media", names)
        text = [row.text for row in built.lines.legend]
        self.assertIn("Bancos (3): cada banco, de un color; los colores se repiten", text)
        self.assertIn("Línea de cielo", text)
        self.assertTrue(built.summary[0][0].startswith("Vista previa de «Corta 1» (PIT-001) en V01, tal como la dejó «Calcular»: 3 bancos"))
        by_type = self.build(self.after("type"))
        keys = [batch.key for batch in by_type.lines.batches]
        self.assertEqual(keys[:2], [pit.FOOT, pit.CREST])
        self.assertEqual([self.batch(by_type, key).segments for key in keys[:2]], [12, 12])
        self.assertIn("Pie de banco", [row.text for row in by_type.lines.legend])
        self.i18n.set_language("en")
        english = self.build(self.after(), language="en")
        self.assertTrue(english.summary[0][0].startswith("Preview of «Corta 1» (PIT-001) in V01, as left by «Calculate»: 3 benches"))
        self.assertIn("Skyline", [row.text for row in english.lines.legend])

    def test_b2_a_ramp_finding_is_named_without_its_internal_key_and_the_crowd_is_capped(self) -> None:
        """RF-018-32, RF-018-31 (T40c; H3-2): el nombre de un hallazgo de rampa dice qué pasa (no la clave «des.…») y, con 21 hallazgos, se nombran como mucho ``PIT_FINDING_LABELS`` (uno por lugar)
        aunque las 21 cruces se dibujan; el texto de arriba lleva «… y N avisos como éste»."""
        dp, pit = self.dpreview, self.pit
        base = self.after()
        finds = tuple(self.pit_model.Finding("ramp", 15.0, 20.0, (WEST + 100.0 + 5.0 * (number % 12), SOUTH + 105.0), 1, "m", "Espiral: des.pit_ramp_radius_reduced") for number in range(21))
        warnings = tuple(dp.Notice("des.pit_ramp_radius_reduced", {"entity": "Espiral", "bench": 1, "vertex": number, "fitted": 15.0, "radius": 20.0, "x": 1.0, "y": 2.0}) for number in range(21))
        crowded = dp.PitPreview(base.name, base.code, base.version, base.masks, mode=base.mode, start_surface=base.start_surface, cell_m=base.cell_m, calculated=True, polylines=base.polylines,
                                ramps=base.ramps, findings=finds, bench_numbers=base.bench_numbers, notices=(*base.notices, *warnings))
        built = self.build(crowded)
        self.assertEqual(self.batch(built, pit.FINDING).segments, 2 * 21)
        names = [label.text for label in built.lines.labels]
        self.assertTrue(all("des." not in text for text in names), names)
        self.assertTrue(any(text.startswith("Rampa «Espiral»: ") for text in names), names)
        self.assertLessEqual(len([text for text in names if text.startswith("Rampa «Espiral»")]), dp.PIT_FINDING_LABELS)
        self.assertLessEqual(len(built.summary), 6)

    # --- (c) el aviso en lugar del dibujo ------------------------------------------------------------

    def test_c_what_calculating_would_refuse_or_missing_masks_are_the_warning_instead_of_the_drawing(self) -> None:
        """RF-018-32, RF-015-08: sin las máscaras al día o con el rechazo de «Calcular» no hay dibujo: el aviso en alerta y la leyenda solo con su título; sin versión activa, solo lo dice."""
        dp = self.dpreview
        error = self.messages.DesignError("des.pit_no_ramp_fit", obj="Corta «Corta 1»", field="des.pit", value=None)
        for found in (dp.PitPreview("Corta 1", "", "V01", self.access.MaskState.MISSING, notices=(dp.Notice("des.preview_entity_masks_missing", {"version": "V01", "entity": "Corta 1"}),)),
                      dp.PitPreview("Corta 1", "", "V01", self.access.MaskState.CURRENT, refusal=error)):
            built = self.build(found)
            self.assertEqual((built.lines.batches, built.lines.labels), ((), ()))
            self.assertEqual([row.text for row in built.lines.legend], ["Vista previa de «Corta 1» · V01"])
            self.assertEqual([item[1] for item in built.summary], [True])
        nothing = self.build(self.before(), version=None)
        self.assertEqual(nothing.lines.batches, ())
        self.assertTrue(nothing.summary[0][1])

    # --- (d) la orden y lo que se pide ---------------------------------------------------------------

    def test_d_the_command_offers_a_pit_of_the_version_by_its_code(self) -> None:
        """RF-015-26, RF-018-32: ``geoblender.des_entity_preview`` previsualiza **una corta de la versión** (``EntityPlan(pit=PitAsk(code=…))``) sin calcular nada."""
        entry = SimpleNamespace(record=SimpleNamespace(kind=self.entities.EntityKind.PIT, code="PIT-001", name="Corta 1"), operation_uid=None)
        plan = self.des_ops.GEOBLENDER_OT_des_entity_preview._plan(SimpleNamespace(), VERSION, entry)
        self.assertEqual((plan.kind, plan.pit.code, plan.pit.request, plan.road, plan.code), ("pit", "PIT-001", None, None, None))

    def test_f_a_preview_is_of_one_thing(self) -> None:
        """Una vista previa es de una sola cosa: ninguna, dos o una inserción con una corta son errores del programa."""
        entity, asked = self.entity, self.dpreview.PitAsk(code="PIT-001")
        self.assertEqual(entity.EntityPlan(pit=asked).kind, "pit")
        for bad in ({}, {"pit": asked, "code": "PLT-001"}, {"pit": asked, "road": object()}, {"pit": asked, "insert_before": "PLT-002"}):
            with self.subTest(bad=sorted(bad)), self.assertRaises(ValueError):
                entity.EntityPlan(**bad)

    # --- (e) activar y quitar ----------------------------------------------------------------------------

    def pump(self) -> Any:
        for _ in range(MAX_PUMPS):
            if self.entity.tick() is None:
                return self.entity.built()
        self.fail("la construcción no acaba")

    def patched(self, found: Any) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(mock.patch.object(self.ps, "current", return_value=SimpleNamespace(origin=ORIGIN)))
        stack.enter_context(mock.patch.object(self.scene_versions, "active", return_value=VERSION))
        stack.enter_context(mock.patch.object(self.entity, "stamp", return_value=("sello",)))
        stack.enter_context(mock.patch.object(self.dpreview, "pit_preview_steps", side_effect=self.steps_of(found)))
        stack.enter_context(mock.patch.object(self.constraints, "ground_steps", side_effect=_no_ground))
        return stack

    def steps_of(self, found: Any) -> Any:
        def steps(_project: Any, _ask: Any, _uid: str, *, budget_s: float = 0.0) -> Any:
            return iter([self.model.Progress("preview_pit", 1, 1, "lista", result=found)])
        return steps

    def test_e_it_is_registered_built_by_steps_and_removed_by_every_way_out(self) -> None:
        """RF-015-26, RF-018-32, RNF-018-08 (M3): ``enable`` pone los manejadores de dibujo y el temporizador, la construye por pasos (``tick``) y deja el resumen; se quita **con su control**, **al
        cambiar de proyecto** y **al conmutar a la interfaz de Blender**; y **no crea ningún objeto** ni escribe nada."""
        entity, switcher = self.entity, self.switcher
        before_fingerprint = blender_ext.state_fingerprint()
        scene = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.curves), len(bpy.data.collections))
        found = self.after()
        with self.patched(found):
            entity.enable(entity.EntityPlan(pit=self.dpreview.PitAsk(request=object())))
            self.assertTrue(entity.enabled() and entity.drawing() and entity.building())
            self.assertTrue(bpy.app.timers.is_registered(entity.tick))
            self.assertEqual(entity.plan().kind, "pit")
            built = self.pump()
            self.assertIs(entity.preview(), found)
            self.assertEqual(len(built.lines.batches), 7)
            entity.disable()
            self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
            self.assertIsNone(entity.built())
            self.assertNotIn(entity.disable, switcher.blender_hooks())
            entity.enable(entity.EntityPlan(pit=self.dpreview.PitAsk(request=object())))  # conmutar a la interfaz de Blender: ida y vuelta
            self.pump()
            window = bpy.context.window_manager.windows[0]
            self.addCleanup(switcher.forget)
            with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
                self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
            self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
            other_space = next(space.name for space in bpy.data.workspaces if space.name != window.workspace.name)
            with mock.patch.object(switcher, "_marked", return_value={other_space}):
                self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other_space)
            self.assertFalse(entity.enabled(), "volver no la pone sola")
            entity.enable(entity.EntityPlan(pit=self.dpreview.PitAsk(request=object())))  # cerrar el proyecto
            self.pump()
            entity.on_project_changed(None)
            self.assertFalse(entity.enabled() or entity.drawing())
        diff = blender_ext.fingerprint_diff(before_fingerprint, blender_ext.state_fingerprint())
        mine = [line for line in diff if line.startswith(("draw_handlers", "handlers", "timers")) and "switcher" not in line]
        self.assertEqual(mine, [], diff)
        self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.curves), len(bpy.data.collections)), scene, "no crea nada en la escena")

    def test_z_disabling_geoblender_with_the_preview_of_a_pit_on_leaves_nothing(self) -> None:
        """Principio 8: con la vista previa de una corta activa, desactivar Geoblender quita los manejadores, los ganchos, el temporizador y los lotes."""
        entity = self.entity
        with self.patched(self.after()):
            entity.enable(entity.EntityPlan(pit=self.dpreview.PitAsk(request=object())))
            self.assertTrue(entity.drawing())
            blender_ext.release()
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
