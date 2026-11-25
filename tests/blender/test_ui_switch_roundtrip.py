# SPDX-License-Identifier: GPL-3.0-or-later
"""Conmutar ida y vuelta, con lo nuevo (spec 019, T21; RF-019-04, RNF-019-04, R-12;
plan 019 §5.1, §7.1, §7.3; ADR-0032).

Con dos ventanas en modos distintos, conmutar una a Blender y volver deja **áreas, pestañas,
cabeceras y ``poll`` idénticos**; tarda ≤ 2 s; no cambia tema, idioma ni preferencias; y tras
desactivar la extensión no queda ninguna clase ``GEOBLENDER_*`` y todo lo parcheado vuelve a ser
**el mismo objeto**: el filtro de paneles (T15) y «Blender ▾» (T20).

En ``-b`` la asignación de ``window.workspace`` no se aplica nunca: las ventanas son falsas (con
``as_pointer`` y ``workspace``) y quien decide el filtro, ``native_filter.sync``, se llama con
ellas, como lo hace ``switcher.check_pending`` con las reales una vez aplicada la asignación.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import time
import unittest
from itertools import count
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

BUDGET_S = 2.0
TARGET = "VIEW3D_MT_editor_menus"
_IDS = count(1)


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class FakeWindow:
    """Una ventana: lo que usan el conmutador y el filtro (``as_pointer`` y ``workspace``)."""

    def __init__(self, workspace: object) -> None:
        self.workspace = workspace
        self._id = 0x7000 + next(_IDS)

    def as_pointer(self) -> int:
        return self._id


def _natives() -> list[type]:
    return [c for c in bpy.types.Panel.__subclasses__()
            if getattr(c, "bl_space_type", "") == "PROPERTIES"
            and not c.__name__.startswith("GEOBLENDER_") and getattr(c, "is_registered", False)]


def _own_polls() -> dict[type, object]:
    return {c: c.__dict__.get("poll") for c in _natives()}


def _poll_results(workspaces: dict[str, object]) -> dict[tuple[str, str], bool]:
    """El resultado del ``poll`` de cada panel nativo en el contexto de cada espacio."""
    results: dict[tuple[str, str], bool] = {}
    for cls in _natives():
        for label, workspace in workspaces.items():
            context = SimpleNamespace(workspace=workspace)
            try:
                poll = getattr(cls, "poll", None)
                value = True if poll is None else bool(poll(context))
            except Exception:  # noqa: BLE001 - como Blender: si falla, se dibuja
                value = True
            results[(cls.__name__, label)] = value
    return results


def _areas() -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    return {ws.name: [(a.type, tuple(r.type for r in a.regions))
                      for screen in ws.screens for a in screen.areas]
            for ws in bpy.data.workspaces}


def _tabs() -> list[tuple[str, str]]:
    """Las pestañas de Propiedades que alimentan los paneles (contexto y clase, en orden)."""
    return [(getattr(c, "bl_context", ""), c.__name__) for c in _natives()]


def _theme_and_language() -> tuple[object, ...]:
    preferences = bpy.context.preferences
    return (preferences.view.language, tuple(preferences.themes[0].view_3d.space.gradients.high_gradient),
            preferences.view.ui_scale, preferences.view.use_translate_interface)


class SwitchRoundTripTest(unittest.TestCase):
    """RF-019-04, RNF-019-04, R-12."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        cls.before_enable = blender_ext.ui_snapshot()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.switcher = _module("bl.ui.switcher")
        self.nf = _module("bl.ui.native_filter")
        self.names = [ws.name for ws in bpy.data.workspaces]
        self.gb = bpy.data.workspaces["Layout"]
        self.gb_was = self.gb.geoblender_mode
        self.gb.geoblender_mode = True
        self.bl = bpy.data.workspaces["Modeling"]
        self.addCleanup(self._unmark)
        self.cls = getattr(bpy.types, TARGET)

    def _unmark(self) -> None:
        try:
            self.gb.geoblender_mode = self.gb_was
        except AttributeError:  # la extensión se desactivó (la propiedad ya no existe)
            pass

    def tearDown(self) -> None:
        if blender_ext.is_enabled():
            self.nf.remove()
            self.switcher.forget()

    def _state(self, windows: list[FakeWindow]) -> dict[str, object]:
        """Todo lo que la ida y vuelta no debe cambiar."""
        snapshot = blender_ext.ui_snapshot()
        snapshot.pop("window_workspaces", None)  # lo que cambia a propósito, por ventana
        snapshot["areas"] = _areas()
        snapshot["tabs"] = _tabs()
        snapshot["polls"] = _poll_results({"gb": self.gb, "bl": self.bl})
        snapshot["tree"] = [c.__name__ for c in self.nf._STATE.tree]
        snapshot["menu"] = self.nf.menu_installed()
        snapshot["modes"] = {w.as_pointer(): gate_mode(w) for w in windows}
        return snapshot

    def test_round_trip_with_two_windows_leaves_everything_as_it_was(self) -> None:
        """RF-019-04, RNF-019-04: A en Geoblender y B en Blender; A a Blender y de vuelta deja
        áreas, pestañas, cabeceras y ``poll`` idénticos, en ≤ 2 s, sin tocar tema, idioma ni
        preferencias."""
        win_a, win_b = FakeWindow(self.gb), FakeWindow(self.bl)
        windows = [win_a, win_b]
        self.assertTrue(self.nf.sync(windows))
        before = self._state(windows)
        poll_objects = {c: c.__dict__.get("poll") for c in _natives()}
        look = _theme_and_language()
        preferences = blender_ext.state_fingerprint()["preferences"]

        self.switcher.window_state(win_a).previous_blender = self.bl.name
        started = time.perf_counter()
        self.assertEqual(self.switcher.toggle(win_a, "BLENDER").workspace, "Modeling")
        self.assertFalse(self.nf.sync(windows))  # ninguna ventana en Geoblender: se retira
        self.assertFalse(self.nf.installed())
        self.assertFalse(self.nf.menu_installed())
        self.assertNotIn("draw_collapsible", self.cls.__dict__)
        self.assertEqual(self.switcher.toggle(win_a, "GEOBLENDER").workspace, self.gb.name)
        self.assertTrue(self.nf.sync(windows))
        elapsed = time.perf_counter() - started

        self.assertLessEqual(elapsed, BUDGET_S)
        after = self._state(windows)
        self.assertEqual(blender_ext.fingerprint_diff(before, after), [])
        self.assertEqual({k: (before[k], after[k]) for k in before if before[k] != after[k]}, {})
        self.assertEqual(_theme_and_language(), look)
        self.assertEqual(blender_ext.state_fingerprint()["preferences"], preferences)
        self.assertEqual(set(poll_objects), set(_natives()))
        self.assertIn("draw_collapsible", self.cls.__dict__)
        self.assertNotIn("GEOBLENDER_PT_ui_blender_settings",
                         [c.__name__ for c in _natives()])

    def test_one_window_leaving_keeps_the_filter_for_the_other(self) -> None:
        """R-12, P-5: con dos ventanas en Geoblender, una que pasa a Blender no retira el
        filtro (la otra lo necesita), y cada una decide con su contexto."""
        win_a, win_b = FakeWindow(self.gb), FakeWindow(self.gb)
        windows = [win_a, win_b]
        self.assertTrue(self.nf.sync(windows))
        self.switcher.toggle(win_a, "BLENDER")
        self.assertTrue(self.nf.sync(windows))
        self.assertTrue(self.nf.installed())
        self.assertTrue(self.nf.menu_installed())
        results = _poll_results({"gb": self.gb, "bl": self.bl})
        for (name, label), value in results.items():
            if label == "gb":
                self.assertFalse(value, name)
        self.assertTrue(any(v for (n, label), v in results.items() if label == "bl"))
        self.assertEqual(self.switcher.window_state(win_b).last_geoblender, None)
        self.assertEqual(self.switcher.window_state(win_a).last_geoblender, self.gb.name)

    def test_the_switch_clears_nothing_of_the_user_and_leaves_no_timer_behind(self) -> None:
        """RNF-019-04, UI-11: tras la ida y vuelta no queda ningún temporizador propio vivo
        (el que comprueba lo pendiente se retira solo al cumplirse) y no cambian los espacios
        de trabajo del fichero."""
        win = FakeWindow(self.gb)
        workspaces = [ws.name for ws in bpy.data.workspaces]
        self.switcher.toggle(win, "BLENDER")
        self.switcher.toggle(win, "GEOBLENDER")
        win.workspace = self.gb  # lo que dejaría Blender al aplicarla
        self.switcher.window_state(win).pending = None
        self.assertEqual([ws.name for ws in bpy.data.workspaces], workspaces)
        self.assertIsNone(self.switcher.pending(win))

    def test_applied_switch_decides_the_filter(self) -> None:
        """RF-019-04, P-5: cuando la asignación diferida se aplica, ``check_pending`` deja
        pendiente nada y decide el filtro (``native_filter.sync``); sin cambio aplicado, no lo toca."""
        from unittest import mock

        window = bpy.context.window_manager.windows[0]
        state = self.switcher.window_state(window)
        with mock.patch.object(self.nf, "sync") as sync:
            state.pending = "no-existe"  # la asignación aún no se aplicó
            self.switcher.check_pending()
            sync.assert_not_called()
            state.pending = window.workspace.name  # ya aplicada
            self.switcher.check_pending()
            sync.assert_called_once_with()
        self.assertIsNone(self.switcher.pending(window))

    def test_unregister_leaves_no_trace(self) -> None:
        """RF-019-04: con el filtro y «Blender ▾» puestos, desactivar la extensión deja 0 clases
        ``GEOBLENDER_*``, cada ``poll`` es el mismo objeto de antes, ``draw_collapsible`` es el
        mismo y sin entrada propia, y la huella del estado vuelve a la de antes de habilitar."""
        blender_ext.release()
        self.assertEqual([n for n in blender_ext._registered_classes() if "GEOBLENDER_" in n], [])
        blender_ext.enable()
        self.gb.geoblender_mode = True
        nf = _module("bl.ui.native_filter")
        polls = _own_polls()
        raw = getattr(bpy.types, TARGET).draw_collapsible.__func__
        self.assertTrue(nf.sync([FakeWindow(self.gb)]))
        self.assertIsNot(getattr(bpy.types, TARGET).draw_collapsible.__func__, raw)
        self.assertTrue(any(polls[c] is not c.__dict__.get("poll") for c in polls))
        blender_ext.release()
        self.assertEqual(_own_polls(), polls)
        for cls, poll in polls.items():
            self.assertIs(cls.__dict__.get("poll"), poll, cls.__name__)
        cls = getattr(bpy.types, TARGET)
        self.assertNotIn("draw_collapsible", cls.__dict__)
        self.assertIs(cls.draw_collapsible.__func__, raw)
        self.assertEqual([n for n in blender_ext._registered_classes() if "GEOBLENDER_" in n], [])
        after = blender_ext.ui_snapshot()
        self.assertEqual(blender_ext.fingerprint_diff(self.before_enable, after), [])


def gate_mode(window: FakeWindow) -> bool:
    return bool(window.workspace.geoblender_mode)


if __name__ == "__main__":
    unittest.main()
