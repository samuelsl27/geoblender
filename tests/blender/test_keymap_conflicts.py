# SPDX-License-Identifier: GPL-3.0-or-later
"""Atajos de Geoblender: registro, choques y puerta de modo (spec 003, T16; AT §1–§3).

- RF-003-18: las 49 combinaciones del catálogo están en el *keyconfig* de complementos
  (``Ctrl+F10`` en «Window», solo con ``ctrl``; las demás en «3D View»), con sus
  propiedades; desregistrar no deja ningún elemento.
- RF-003-18, RNF-003-10: con el método de AT §3.1 y la versión instalada
  (``generate_keymaps`` de ``blender_default.py``, selección con el botón izquierdo y con
  el derecho), ninguna de las 49 está asignada en el ámbito de la Vista 3D, y el control
  positivo ``Ctrl+Alt+G`` sí se detecta (el método funciona).
- RF-003-19: todo operador con atajo en «3D View» falla su ``poll`` en modo Blender sobre
  una Vista 3D y lo pasa desde fuera de ella (la barra superior), y en modo Geoblender.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import functools
import importlib
import importlib.util
import unittest
from pathlib import Path
from collections.abc import Iterator, Mapping
from types import ModuleType
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

# Ámbito de la Vista 3D (AT §3.1): una coincidencia en estos mapas es un choque.
SCOPE = frozenset({
    "Window", "Screen", "Screen Editing", "3D View", "3D View Generic", "Object Mode",
    "Object Non-modal", "Mesh", "Curve", "Curves", "Frames", "User Interface",
    "Grease Pencil", "Point Cloud", "Annotate",
})
SELECT_MOUSE = ("LEFT", "RIGHT")
TOTAL = 49


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _blender_default() -> ModuleType:
    path = Path(bpy.utils.system_resource("SCRIPTS"), "presets", "keyconfig", "keymap_data",
                "blender_default.py")
    spec = importlib.util.spec_from_file_location("gb_test_blender_default", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _modifier(value: object) -> object:
    """``True``, ``False`` o ``"any"`` (``-1`` o ``KM_ANY`` en ``keymap_data``)."""
    if value in (-1, "ANY"):
        return "any"
    return bool(value)


def _matches(event: Mapping[str, Any], combo: tuple[str, bool, bool, bool]) -> bool:
    """Si una asignación de ``keymap_data`` reacciona a ``combo`` (tipo, ctrl, shift,
    alt): mismo tipo, sin tecla mantenida y modificadores iguales (o «cualquiera»)."""
    kind, ctrl, shift, alt = combo
    if event.get("type") != kind or event.get("key_modifier"):
        return False
    if event.get("any"):
        return True
    if _modifier(event.get("oskey", False)) is True:
        return False
    for name, wanted in (("ctrl", ctrl), ("shift", shift), ("alt", alt)):
        value = _modifier(event.get(name, False))
        if value != "any" and value != wanted:
            return False
    return True


@functools.cache
def _assignments(select_mouse: str) -> tuple[tuple[str, str, Mapping[str, Any]], ...]:
    """(mapa, operador, evento) de los mapas por defecto de la versión instalada."""
    data = _blender_default()
    params = data.Params(select_mouse=select_mouse)
    return tuple(_items(data.generate_keymaps(params)))


def _items(keymaps: Any) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    for name, _args, content in keymaps:
        for item in content.get("items", ()) or ():
            if item is not None:
                yield name, item[0], item[1]


def _conflicts(combo: tuple[str, bool, bool, bool], select_mouse: str) -> list[str]:
    return sorted({f"{name}: {idname}" for name, idname, event in _assignments(select_mouse)
                   if name in SCOPE and _matches(event, combo)})


class KeymapConflictTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.keymap = _module("bl.ui.keymap")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def test_registered(self) -> None:
        """RF-003-18: las 49 del catálogo, en su mapa y con sus propiedades; Ctrl+F10 en
        «Window» con solo ``ctrl``."""
        items = self.keymap.registered_items()
        self.assertEqual(len(items), TOTAL)
        self.assertEqual(len(self.cat.shortcuts()), TOTAL)
        by_map: dict[str, int] = {}
        for (keymap, item), shortcut in zip(items, self.cat.shortcuts(), strict=True):
            by_map[keymap.name] = by_map.get(keymap.name, 0) + 1
            self.assertEqual((item.idname, item.type, item.ctrl, item.shift, item.alt),
                             (shortcut.idname, shortcut.event, shortcut.ctrl, shortcut.shift,
                              shortcut.alt), shortcut.key)
            for name, value in self.keymap.split_key(shortcut.key)[1]:
                self.assertEqual(getattr(item.properties, name), value, shortcut.key)
        self.assertEqual(by_map, {"Window": 1, "3D View": TOTAL - 1})
        (toggle,) = [item for keymap, item in items if keymap.name == "Window"]
        self.assertEqual((toggle.idname, toggle.type, toggle.ctrl, toggle.shift, toggle.alt,
                          toggle.oskey), ("geoblender.ui_toggle_mode", "F10", True, False,
                                          False, False))

    def test_no_conflicts_in_3d_view_scope(self) -> None:
        """RF-003-18, RNF-003-10 (AT §3.1 y §3.4): ninguna de las 49 choca en el ámbito
        de la Vista 3D, con selección izquierda y derecha; Ctrl+Alt+G sí (control)."""
        combos = {(s.event, s.ctrl, s.shift, s.alt) for s in self.cat.shortcuts()}
        self.assertEqual(len(combos), TOTAL)
        for select_mouse in SELECT_MOUSE:
            self.assertGreater(len(_assignments(select_mouse)), 3000)
            found = {combo: _conflicts(combo, select_mouse) for combo in sorted(combos)}
            self.assertEqual({combo: hits for combo, hits in found.items() if hits}, {},
                             select_mouse)
            control = _conflicts(("G", True, False, True), select_mouse)
            self.assertTrue(any(hit.startswith("Object Mode") for hit in control), control)

    def test_gate_on_3d_view_shortcuts(self) -> None:
        """RF-003-19: cada operador con atajo en «3D View» falla su ``poll`` sobre una
        Vista 3D en modo Blender y lo pasa en modo Geoblender y desde fuera de la Vista 3D
        (la barra superior)."""
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        workspace = window.workspace
        idnames = sorted({s.idname for s in self.cat.shortcuts() if s.keymap == "3D View"})
        self.assertGreater(len(idnames), 20)
        for idname in idnames:
            module, _, name = idname.partition(".")
            operator = getattr(getattr(bpy.ops, module), name)
            with bpy.context.temp_override(window=window, area=area, region=region):
                self.assertFalse(operator.poll(), idname)
                workspace.geoblender_mode = True
                try:
                    self.assertTrue(operator.poll(), idname)
                finally:
                    workspace.geoblender_mode = False
            self.assertTrue(operator.poll(), idname)


class KeymapCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def test_unregister_leaves_no_items(self) -> None:
        """RF-003-18, RF-003-23: deshabilitar no deja ningún atajo de Geoblender en el
        *keyconfig* de complementos."""
        keyconfig = bpy.context.window_manager.keyconfigs.addon
        blender_ext.enable()
        self.assertTrue(any(item.idname.startswith("geoblender.")
                            for keymap in keyconfig.keymaps for item in keymap.keymap_items))
        blender_ext.disable()
        left = [item.idname for keymap in keyconfig.keymaps for item in keymap.keymap_items
                if item.idname.startswith("geoblender.")]
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
