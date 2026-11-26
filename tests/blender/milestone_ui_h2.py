# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de la spec 019 (todas las HU; RF-019-01 a 22; RNF-019-01 a 04; plan 019 §7.3, §7.5): el modo Geoblender sin ruido, el panel y el aspecto
de punta a punta, las reglas con sus listas base y los RNF, juntos.

Con el proyecto de ``tests/support/views_fixtures.py`` y una superficie, una corta y una pista (el tipo que lleva su vista, como el H1), cada tramo cita
la tarea que lo hace pasar: si falta una, el tramo falla con su nombre.

- ``Chain`` (T09, T10, T14, T24): la ficha y el aspecto de punta a punta, sin una clave interna a la vista (el nombre estable, el código de la
  operación, el papel), con color y transparencia que sobreviven a guardar y reabrir, y 100 objetos en ≤ 0,4 s (RNF-019-03, T29).
- ``Mode`` (T15, T16, T19, T20, T21): el modo Geoblender sin línea de tiempo (salvo «Fases»), sin pestañas de Propiedades de Blender y sin paneles
  nativos; «Ajustes de Blender» y «Blender ▾»; conmutar ida y vuelta con el estado idéntico en ≤ 2 s (RF-019-04, RNF-019-04).
- ``Rules`` (T24 a T28): las cuatro pruebas de reglas (claves internas, formatos, alturas de los diálogos y etiquetas cortadas) y el contraste, con
  sus listas base (``tests/data/ui_baseline.toml``): ninguna crece (solo baja) y cada prueba, en verde. Las puras, con el Python de Blender, como
  ``check.py``; las que dibujan, en este mismo Blender.
- ``Cost`` (T29): las cuatro pruebas de rendimiento existen (``perf_ui_h2``, ``perf_ui_mix``); sus cifras, con ``check.py --rendimiento``.

Lo hace pasar la sesión principal con ``tools/check.py --completo`` (paso «hito»). Se ejecuta con ``tools/run_blender_tests.py``.
"""

import io
import os
import subprocess
import sys
import time
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender import test_ui_areas as areas_test
from tests.blender.test_ui_appearance_roundtrip import KINDS, RoundtripCase, _appearance, _hex
from tests.blender.test_ui_switch_roundtrip import FakeWindow, _areas, _natives, _poll_results, _tabs, gate_mode
from tests.support import blender_ext
from tests.support import ui_strings as us
from tests.support import views_fixtures as vf
from tests.support.fake_layout import draw
from tests.support.repo import ROOT

ELEMENT = "GEOBLENDER_PT_ui_element"
LOOK = "GEOBLENDER_PT_ui_element_look"
BASELINE = ROOT / "tests" / "data" / "ui_baseline.toml"
# El tamaño de cada lista base al cerrar el bloque (T24 a T28): solo baja (la vacía la spec 020).
BASELINE_CAPS = {"strings": 8, "formats": 10, "dialogs": 10, "labels": 10, "contrast": 57}
UNIT_RULES = ("tests.unit.test_ui_strings", "tests.unit.test_ui_formats", "tests.unit.test_ui_contrast", "tests.unit.test_ui_literals")
BLENDER_RULES = ("tests.blender.test_ui_dialogs", "tests.blender.test_ui_labels_cut")
PERF_FILES = ("tests/rendimiento/blender/perf_ui_h2.py", "tests/rendimiento/blender/perf_ui_mix.py", "tests/rendimiento/blender/perf_ui_draw_cost.py")
SWITCH_BUDGET_S = 2.0
APPEARANCE_BUDGET_S = 0.4


class ChainTest(RoundtripCase):
    """HU-019-1 (T09, T10, T14, T24, T29): el panel y el aspecto de punta a punta."""

    def drawn(self, panel: str) -> list[str]:
        with mock.patch.object(vf.extension("bl.ui.labels"), "sidebar_width", return_value=1000.0):
            layout = draw(getattr(bpy.types, panel), bpy.context)
        return [item.text for item in layout.of_kind("label")]

    def activate(self, obj: bpy.types.Object) -> None:
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

    def test_a_the_card_has_no_internal_key_and_the_look_survives_save_and_reopen(self) -> None:
        """T09/T24: la ficha de cada elemento sin clave interna (UI-07, UI-08); T10/T14: color y transparencia de cada uno, guardar, cerrar, abrir."""
        stable = {self.name(obj) for obj in self.objs}
        before = self.counts()
        wanted = {}
        for index, obj in enumerate(self.objs):
            self.activate(obj)
            self.assertTrue(getattr(bpy.types, ELEMENT).poll(bpy.context), f"T09: sin panel de {obj.geoblender.kind}")
            lines = self.drawn(ELEMENT) + self.drawn(LOOK)
            self.assertEqual(us.findings(lines), [], f"T24: claves internas a la vista en la ficha de {obj.geoblender.kind}")
            for name in stable:
                self.assertFalse(any(name in line for line in lines), f"T24: el nombre estable {name} a la vista")
            obj.geoblender.look.color = (0.1 * (index + 1), 0.5, 0.9)
            obj.geoblender.look.transparency = 25 + 10 * index
            wanted[self.name(obj)] = (_hex(obj), 25 + 10 * index)
        self.assertEqual(_appearance().flush(), 6, "T08: la escritura diferida")
        path = str(Path(self.folder) / "h2.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        self.data.close()
        blender_ext.load_file(path)
        objs = [o for o in bpy.data.objects if o.geoblender.kind in KINDS]
        for obj in objs:
            obj.geoblender.look.property_unset("color")
            obj.geoblender.look.property_unset("transparency")
            obj.color = (0.5, 0.5, 0.5, 1.0)
        self.reopen()
        for obj in objs:
            name = self.name(obj)
            self.assertEqual((_hex(obj), obj.geoblender.look.transparency), wanted[name], f"T14: {name} perdió su aspecto")
        after = self.counts()
        for table in ("gb_version", "gb_stale"):
            self.assertEqual(before[table], after[table], f"RF-019-08, T14: {table} cambió")

    def test_b_100_objects_change_colour_and_transparency_within_the_budget(self) -> None:
        """RNF-019-03 (T29): cambiar color y transparencia con 100 objetos seleccionados ≤ 0,4 s (el mejor de cinco)."""
        scene = bpy.context.scene
        extra = []
        for index in range(100):
            obj = bpy.data.objects.new(f"h2-{index:03d}", bpy.data.meshes.new(f"h2-{index:03d}"))
            scene.collection.objects.link(obj)
            obj.geoblender.kind = "DTM"
            obj.geoblender.project_uid = self.data.project.uid
            obj.geoblender.dataset_uid = self.objs[0].geoblender.dataset_uid
            extra.append(obj)
        for other in bpy.data.objects:
            other.select_set(False)
        for obj in extra:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = extra[0]
        times = []
        for step in range(5):
            start = time.perf_counter()
            extra[0].geoblender.look.color = (0.2 + 0.1 * step, 0.4, 0.6)
            extra[0].geoblender.look.transparency = 40 + step
            _appearance().flush()
            times.append(time.perf_counter() - start)
        self.assertLessEqual(min(times), APPEARANCE_BUDGET_S, f"RNF-019-03, T29: {min(times):.3f} s")


class ModeTest(unittest.TestCase):
    """HU-019-2 (T15, T16, T19, T20, T21): el modo Geoblender sin ruido, «Ajustes de Blender», «Blender ▾» y la ida y vuelta."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        cls.before_enable = blender_ext.ui_snapshot()
        cls.module = blender_ext.enable()
        cls.blend = Path(cls.module.__file__).parent / "resources" / areas_test.BLEND_NAME
        cls.switcher = areas_test._module("bl.ui.switcher")
        cls.nf = areas_test._module("bl.ui.native_filter")
        cls.cat = areas_test._module("core.catalog").load()
        cls.names = [layout.workspace for layout in cls.cat.layouts if layout.entry == "003"]
        with bpy.data.libraries.load(str(cls.blend)) as (source, target):
            original = list(source.workspaces)
            target.workspaces = list(original)
        cls.loaded = dict(zip(original, target.workspaces, strict=True))

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def tearDown(self) -> None:
        self.nf.remove()
        self.switcher.forget()

    def test_a_the_areas_have_no_timeline_but_phases_and_no_property_tabs_but_object(self) -> None:
        """RF-019-02, RF-019-03 (T16, T17): sin línea de tiempo salvo «Fases», sin pestañas de Propiedades de Blender y Propiedades abre en Objeto."""
        self.assertIn(areas_test.PHASES, self.names, "T16: falta la disposición «Fases»")
        for name in self.names:
            workspace = self.loaded[name]
            timelines = [a for a in workspace.screens[0].areas if a.type == "DOPESHEET_EDITOR" and a.ui_type == "TIMELINE"]
            self.assertEqual(timelines, [], f"T16: {name} lleva línea de tiempo")
            sheets = [a for a in workspace.screens[0].areas if a.type == "DOPESHEET_EDITOR"]
            self.assertEqual(len(sheets), 1 if name == areas_test.PHASES else 0, f"T16: {name}")
            for space in areas_test._spaces(workspace, "PROPERTIES"):
                tabs = areas_test._tabs(space)
                self.assertEqual([k for k, v in tabs.items() if v], ["show_properties_object"], f"T16: pestañas de {name}")
                self.assertEqual(space.context, "OBJECT", f"T16: {name}")
            for view in areas_test._spaces(workspace, "VIEW_3D"):
                self.assertEqual(view.shading.color_type, "OBJECT", f"T16: {name} no colorea por objeto")
        main = next(layout.workspace for layout in self.cat.layouts if layout.main)
        self.assertEqual(sorted(a.type for a in self.loaded[main].screens[0].areas), ["OUTLINER", "PROPERTIES", "VIEW_3D"], "T16: la principal")
        for name in self.names:
            self.assertEqual(self.loaded[name].get(areas_test.REV_KEY), _revision(), f"T18: la revisión de {name}")

    def test_b_no_native_panel_passes_and_the_blender_door_is_there(self) -> None:
        """RF-019-03 (T15, T19, T20): ningún panel nativo pasa en una ventana de Geoblender; «Ajustes de Blender» y «Blender ▾» existen y se quitan."""
        gb = SimpleNamespace(name="gbtest_h2_geoblender", geoblender_mode=True)
        natives = _natives()
        self.assertTrue(natives, "T15: no hay paneles nativos que filtrar")
        before = {c: c.__dict__.get("poll") for c in natives}
        self.assertTrue(self.nf.sync([SimpleNamespace(workspace=gb)]), "T15: el filtro no se instaló")
        self.assertEqual([c.__name__ for c in natives if c.poll(SimpleNamespace(workspace=gb))], [], "T15: un panel nativo pasa en Geoblender")
        self.assertTrue(self.nf.menu_installed(), "T20: falta «Blender ▾»")
        self.assertIn("geoblender.ui_blender_settings", self.cat.commands, "T19: falta «Ajustes de Blender»")
        self.assertTrue(hasattr(bpy.ops.geoblender, "ui_blender_settings"), "T19: la orden no está registrada")
        self.nf.remove()
        self.assertEqual({c: c.__dict__.get("poll") for c in natives}, before, "T15: el filtro no devolvió los poll")
        self.assertFalse(self.nf.menu_installed(), "T20: «Blender ▾» no se retiró")

    def test_c_switching_to_blender_and_back_leaves_the_state_as_it_was(self) -> None:
        """RF-019-04, RNF-019-04 (T21): conmutar a Blender y volver deja áreas, pestañas, cabeceras y ``poll`` idénticos, en ≤ 2 s, sin tocar tema,
        idioma ni preferencias."""
        gb, bl = bpy.data.workspaces["Layout"], bpy.data.workspaces["Modeling"]
        was = gb.geoblender_mode
        gb.geoblender_mode = True
        self.addCleanup(setattr, gb, "geoblender_mode", was)
        win_a, win_b = FakeWindow(gb), FakeWindow(bl)
        windows = [win_a, win_b]

        def state() -> dict[str, object]:
            snapshot = blender_ext.ui_snapshot()
            snapshot.pop("window_workspaces", None)
            snapshot.update(areas=_areas(), tabs=_tabs(), polls=_poll_results({"gb": gb, "bl": bl}),
                            tree=[c.__name__ for c in self.nf._STATE.tree], menu=self.nf.menu_installed(),  # noqa: SLF001
                            modes={w.as_pointer(): gate_mode(w) for w in windows})
            return snapshot

        self.assertTrue(self.nf.sync(windows))
        before = state()
        preferences = blender_ext.state_fingerprint()["preferences"]
        self.switcher.window_state(win_a).previous_blender = bl.name
        # Las ventanas de esta prueba son de mentira y la real de ``-b`` no cuenta: se conmuta con solo ``win_a`` (T40: no se elige un espacio de otra ventana).
        started = time.perf_counter()
        self.assertEqual(self.switcher.toggle(win_a, "BLENDER", [win_a]).workspace, bl.name, "T21: no conmutó a Blender")
        self.nf.sync(windows)
        self.assertEqual(self.switcher.toggle(win_a, "GEOBLENDER", [win_a]).workspace, gb.name, "T21: no volvió a Geoblender")
        self.assertTrue(self.nf.sync(windows))
        elapsed = time.perf_counter() - started
        self.assertLessEqual(elapsed, SWITCH_BUDGET_S, f"RNF-019-04: {elapsed:.3f} s")
        # Blender aplica la asignación y el temporizador de lo pendiente se retira solo al cumplirse; en ``-b`` no corre: se hace a mano.
        self.switcher.window_state(win_a).pending = None
        if bpy.app.timers.is_registered(self.switcher.check_pending):
            bpy.app.timers.unregister(self.switcher.check_pending)
        self.assertEqual(blender_ext.fingerprint_diff(before, state()), [], "T21: el estado no es idéntico")
        self.assertEqual(blender_ext.state_fingerprint()["preferences"], preferences, "T21: cambiaron las preferencias")


def _revision() -> int:
    return areas_test._module("bl.ui.areas").LAYOUT_REV


class RulesTest(unittest.TestCase):
    """HU-019-3 (T24 a T28): las reglas y sus listas base."""

    def test_a_the_baselines_only_go_down(self) -> None:
        """T24 a T28: ninguna lista base ha crecido desde que se escribió (solo baja; la vacía la spec 020) y todas están ordenadas y sin repetir."""
        data = tomllib.loads(BASELINE.read_bytes().decode("utf-8"))
        for section, cap in BASELINE_CAPS.items():
            self.assertIn(section, data, f"falta la lista base [{section}]")
            entries = [str(e) for e in data[section]["entries"]]
            self.assertLessEqual(len(entries), cap, f"[{section}] creció: {len(entries)} > {cap}")
            self.assertEqual(entries, sorted(set(entries)), f"[{section}] desordenada o con repetidas")

    def test_b_the_pure_rules_pass(self) -> None:
        """T24 (claves internas), T25 (formatos), T28 (contraste) y los literales: las pruebas sin Blender, con el Python de Blender, en verde."""
        python = Path(sys.prefix) / "bin" / "python.exe"
        if not python.exists():
            self.skipTest("no se encuentra el Python de Blender")
        site = ROOT / ".deps" / "site"
        env = dict(os.environ, PYTHONPATH=str(site) if site.exists() else "")
        done = subprocess.run([str(python), "-B", "-s", "-X", "utf8", "-m", "unittest", *UNIT_RULES], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=300, check=False)
        self.assertEqual(done.returncode, 0, f"las reglas puras fallan:\n{done.stderr[-3000:]}")

    def test_c_the_dialog_rules_pass(self) -> None:
        """T26 (alturas de los diálogos) y T27 (etiquetas cortadas), contra sus listas base, en este mismo Blender."""
        stream = io.StringIO()
        suite = unittest.TestLoader().loadTestsFromNames(BLENDER_RULES)
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(), f"las reglas de los diálogos fallan:\n{stream.getvalue()[-3000:]}")
        self.assertGreaterEqual(result.testsRun, 10)


class CostTest(unittest.TestCase):
    """RNF-019-01 a 04 (T29): las mediciones existen; sus cifras, con ``check.py --rendimiento``."""

    def test_the_four_measurements_exist(self) -> None:
        for relative in PERF_FILES:
            self.assertTrue((ROOT / relative).exists(), f"T29: falta {relative}")
        source = (ROOT / PERF_FILES[0]).read_text(encoding="utf-8")
        for rnf in ("rnf_019_01", "rnf_019_02", "rnf_019_03", "rnf_019_04"):
            self.assertIn(rnf, source, f"T29: sin la medición de {rnf.upper().replace('_', '-')}")


if __name__ == "__main__":
    unittest.main()
