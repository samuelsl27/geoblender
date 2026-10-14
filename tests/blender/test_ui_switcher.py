# SPDX-License-Identifier: GPL-3.0-or-later
"""El conmutador Geoblender ⇄ Blender (spec 003, T15; CW §3; plan 003 §5.4, 4).

- RF-003-02: ``choose_target`` cubre CW §3.1–§3.3 (prueba por casos): a Geoblender, el
  último espacio marcado de la ventana, el principal, otro marcado o anexarlo; a Blender,
  el anterior sin marcar, «Layout», el primero sin marcar o anexar «Layout»; pedir el modo
  activo no hace nada.
- RF-003-02: ``geoblender.ui_toggle_mode`` en un fichero sin espacio marcado lo anexa de
  los recursos una sola vez, deja el destino pendiente (la asignación es diferida: se
  comprueba en la GUI, M2) y no cambia preferencias, escena ni datos (salvo el espacio
  anexado), ni es un paso de deshacer; ``target`` explícito funciona y repetir el modo
  activo no hace nada.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name, state_fingerprint

FALLBACK = "Layout"
MAIN = "GB"  # el principal en las pruebas de la función pura (el real sale del catálogo)


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class ChooseTargetTest(unittest.TestCase):
    """RF-003-02: la elección del destino (CW §3.1–§3.3), función pura de nombres."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.switcher = _module("bl.ui.switcher")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def choose(self, current: str, names: list[str], marked: set[str], **kw: object) -> object:
        return self.switcher.choose_target(current=current, names=names, marked=marked,
                                           main=MAIN, **kw)

    def test_to_geoblender(self) -> None:
        """RF-003-02, CW §3.1: el último marcado de la ventana; si no, el principal; si no,
        otro marcado (renombrado); si no hay ninguno, anexar el principal."""
        names = ["Layout", "Modeling", MAIN, "GB · Datos"]
        marked = {MAIN, "GB · Datos"}
        last = self.choose("Layout", names, marked, last_geoblender="GB · Datos")
        self.assertEqual((last.to_geoblender, last.target), (True, "GB · Datos"))
        self.assertEqual(self.choose("Layout", names, marked).target, MAIN)
        gone = self.choose("Layout", names, marked, last_geoblender="Borrado")
        self.assertEqual(gone.target, MAIN)
        renamed = self.choose("Layout", ["Layout", "Mi espacio"], {"Mi espacio"})
        self.assertEqual(renamed.target, "Mi espacio")
        empty = self.choose("Layout", ["Layout", "Modeling"], set())
        self.assertEqual((empty.target, empty.append), (None, MAIN))

    def test_to_blender(self) -> None:
        """RF-003-02, CW §3.2: el anterior de Blender si existe y no está marcado; si no,
        «Layout»; si no, el primero sin marcar; si no hay ninguno, anexar «Layout»."""
        names = ["Animation", FALLBACK, "Modeling", MAIN]
        marked = {MAIN}
        back = self.choose(MAIN, names, marked, previous_blender="Modeling")
        self.assertEqual((back.to_geoblender, back.target), (False, "Modeling"))
        self.assertEqual(self.choose(MAIN, names, marked, previous_blender="Borrado").target,
                         FALLBACK)
        self.assertEqual(self.choose(MAIN, names, marked | {"Modeling"},
                                     previous_blender="Modeling").target, FALLBACK)
        self.assertEqual(self.choose(MAIN, ["Animation", MAIN], marked).target, "Animation")
        alone = self.choose(MAIN, [MAIN], marked)
        self.assertEqual((alone.target, alone.append), (None, FALLBACK))

    def test_explicit_targets(self) -> None:
        """RF-003-02, CW §2: con ``target`` explícito se va a ese modo; pedir el modo
        activo no hace nada; ``TOGGLE`` va al otro."""
        names = [FALLBACK, MAIN]
        marked = {MAIN}
        self.assertTrue(self.choose(MAIN, names, marked, mode="GEOBLENDER").noop)
        self.assertTrue(self.choose(FALLBACK, names, marked, mode="BLENDER").noop)
        self.assertEqual(self.choose(FALLBACK, names, marked, mode="GEOBLENDER").target, MAIN)
        self.assertEqual(self.choose(MAIN, names, marked, mode="BLENDER").target, FALLBACK)
        self.assertEqual(self.choose(MAIN, names, marked, mode="TOGGLE").target, FALLBACK)
        with self.assertRaises(ValueError):
            self.choose(MAIN, names, marked, mode="OTRO")


def _data_state() -> dict[str, object]:
    """El número de elementos de cada colección de ``bpy.data`` salvo los espacios de
    trabajo y sus pantallas (anexar el principal los añade, CW §3.1): tampoco una
    biblioteca, porque el anexado no deja la referencia a los recursos."""
    state: dict[str, object] = {}
    for name in dir(bpy.data):
        value = getattr(bpy.data, name, None)
        if isinstance(value, bpy.types.bpy_prop_collection) and name not in (
            "workspaces", "screens", "all_ids"
        ):
            state[name] = len(value)
    return state


class ToggleOperatorTest(unittest.TestCase):
    """RF-003-02: el operador en un Blender de fábrica (sin interfaz, la asignación queda
    pendiente)."""

    def setUp(self) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        self.addCleanup(blender_ext.release)
        self.addCleanup(blender_ext.load_file)
        self.switcher = _module("bl.ui.switcher")
        self.window = bpy.context.window_manager.windows[0]

    def test_appends_once_and_leaves_pending(self) -> None:
        """RF-003-02, CW §3.1: sin espacio marcado, el primer conmutado anexa el
        principal de los recursos (marcado) y lo deja pendiente; el segundo no anexa otro;
        preferencias, escena y datos no cambian y no es un paso de deshacer."""
        main = self.switcher.main_workspace()
        self.assertNotIn(main, bpy.data.workspaces)
        before = _data_state()
        preferences = state_fingerprint()["preferences"]
        scene = self.window.scene
        self.assertEqual(bpy.ops.geoblender.ui_toggle_mode(), {"FINISHED"})
        self.assertIn(main, bpy.data.workspaces)
        self.assertTrue(bpy.data.workspaces[main].geoblender_mode)
        self.assertIsNone(bpy.data.workspaces[main].library)
        self.assertEqual(self.switcher.pending(self.window), main)
        state = self.switcher.window_state(self.window)
        self.assertEqual(state.previous_blender, FALLBACK)
        count = len(bpy.data.workspaces)
        result = self.switcher.toggle(self.window)
        self.assertEqual((result.workspace, result.appended), (main, False))
        self.assertEqual(len(bpy.data.workspaces), count)
        after = _data_state()
        self.assertEqual({k: (v, after[k]) for k, v in before.items() if after[k] != v}, {})
        self.assertEqual(state_fingerprint()["preferences"], preferences)
        self.assertEqual(self.window.scene, scene)
        self.assertNotIn("UNDO", bpy.types.GEOBLENDER_OT_ui_toggle_mode.bl_options)
        self.assertTrue(bpy.app.timers.is_registered(self.switcher.check_pending))

    def test_same_mode_does_nothing(self) -> None:
        """RF-003-02, CW §2: pulsar el botón del modo activo no hace nada."""
        self.assertEqual(bpy.ops.geoblender.ui_toggle_mode(target="BLENDER"), {"CANCELLED"})
        self.assertIsNone(self.switcher.pending(self.window))

    def test_from_geoblender_to_blender(self) -> None:
        """RF-003-02, CW §3.2: desde un espacio marcado se va a uno sin marcar y se
        recuerda el de Geoblender."""
        current = self.window.workspace
        current.geoblender_mode = True
        try:
            self.assertEqual(bpy.ops.geoblender.ui_toggle_mode(target="BLENDER"),
                             {"FINISHED"})
            target = self.switcher.pending(self.window)
            self.assertIsNotNone(target)
            self.assertFalse(bpy.data.workspaces[target].geoblender_mode)
            state = self.switcher.window_state(self.window)
            self.assertEqual(state.last_geoblender, current.name)
        finally:
            current.geoblender_mode = False


if __name__ == "__main__":
    unittest.main()
