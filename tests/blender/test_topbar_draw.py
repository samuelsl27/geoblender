# SPDX-License-Identifier: GPL-3.0-or-later
"""Barra superior con el *layout* simulado (spec 003, T12 y T13; BS §1, §3, §4, §8; CW §2,
§4 y §5).

- RF-003-01, RF-003-03: en modo Geoblender, el conmutador lo primero, con GB hundido, y
  después, en el orden de BS §1, Disposición ▾, ≡, los 11 menús del flujo, Herramientas,
  Ayuda y el acceso rápido del proyecto; con el área maximizada, también «Volver»;
  ``draw_right`` sin tocar.
- RF-003-04: en modo Blender, el conmutador con B hundido, «Geoblender ▾» y todas las
  llamadas del ``draw_left`` original.
- RF-003-06: los 11 menús del flujo empiezan con «Paso n de 11 · <etapa>»; los dibujos de
  los menús solo referencian operadores, menús y paneles registrados.
- RF-003-07, RF-003-08: lo no disponible, desactivado; con «Ocultar lo no disponible», fuera
  de los menús, pero los 13 menús de la barra siguen.
- RF-003-24: instalar dos veces no envuelve dos veces y restaurar devuelve el mismo objeto.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, Item, draw

TOGGLE = "geoblender.ui_toggle_mode"
VOLUME = "geoblender.res_compute_volume_between_surfaces"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def context(*, geoblender: bool, fullscreen: bool = False) -> SimpleNamespace:
    """Lo que leen la barra y los menús: el espacio de trabajo (su marca), la pantalla,
    el área, la ventana y la escena."""
    return SimpleNamespace(
        workspace=SimpleNamespace(geoblender_mode=geoblender),
        screen=SimpleNamespace(show_fullscreen=fullscreen, show_statusbar=True),
        area=SimpleNamespace(show_menus=True, type="TOPBAR"),
        region=SimpleNamespace(alignment="LEFT", width=1920),
        window=bpy.context.window_manager.windows[0],
        scene=bpy.context.scene,
        space_data=None,
    )


def draw_topbar(ctx: SimpleNamespace) -> FakeLayout:
    return draw(bpy.types.TOPBAR_HT_upper_bar, ctx, method="draw_left")


def controls(layout: FakeLayout) -> list[tuple[str, str]]:
    """(tipo, destino) de los operadores, menús y ventanas emergentes, en orden."""
    kinds = ("operator", "menu", "popover", "menu_contents", "template_ID_tabs")
    return [(item.kind, item.target) for item in layout.items if item.kind in kinds]


class TopbarDrawTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        # En un diccionario: una función como atributo de la clase sería un método.
        cls.saved = {"draw_left": bpy.types.TOPBAR_HT_upper_bar.draw_left,
                     "draw_right": bpy.types.TOPBAR_HT_upper_bar.draw_right}
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.topbar = _module("bl.ui.topbar")
        cls.registry = _module("bl.ui.registry")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def preferences(self) -> object:
        return bpy.context.preferences.addons[module_name()].preferences.ui

    def label(self, key: str) -> str:
        return self.cat.commands[key].label_es

    def test_geoblender_mode_order(self) -> None:
        """RF-003-01, RF-003-03: en modo Geoblender, el orden de BS §1 con GB hundido y
        el bloque derecho sin tocar."""
        layout = draw_topbar(context(geoblender=True))
        first, second = [item for item in layout.items if item.target == TOGGLE]
        self.assertIs(layout.items[0], first)
        self.assertEqual((first.properties.target, first.options["depress"]),
                         ("GEOBLENDER", True))
        self.assertEqual((second.properties.target, second.options["depress"]),
                         ("BLENDER", False))
        top = list(self.cat.top_menus)
        quick = [("operator", "geoblender.core_save_project"), ("operator", "ed.undo"),
                 ("operator", "ed.redo"), ("menu", "GEOBLENDER_MT_core_data"),
                 ("operator", "geoblender.core_refresh"),
                 ("popover", "GEOBLENDER_PT_core_version")]
        expected = [("operator", TOGGLE), ("operator", TOGGLE),
                    ("popover", "GEOBLENDER_PT_ui_layouts"),
                    ("menu", "TOPBAR_MT_editor_menus"),
                    *[("menu", menu_id) for menu_id in top], *quick]
        self.assertEqual(controls(layout), expected)
        titles = [item.text for item in layout.items if item.target in top]
        self.assertEqual(titles, [self.label(menu_id) for menu_id in top])
        self.assertEqual(titles[0], "Proyecto")
        self.assertIs(bpy.types.TOPBAR_HT_upper_bar.draw_right, self.saved["draw_right"])
        self.assertNotIn("screen.back_to_previous", [t for _k, t in controls(layout)])

    def test_fullscreen_back(self) -> None:
        """CW §3.3: con el área maximizada, la barra dibuja también «Volver»."""
        layout = draw_topbar(context(geoblender=True, fullscreen=True))
        self.assertEqual(controls(layout)[-1], ("operator", "screen.back_to_previous"))

    def test_blender_mode(self) -> None:
        """RF-003-01, RF-003-04: en modo Blender, el conmutador con B hundido, «Geoblender
        ▾» y después exactamente lo que dibuja el original."""
        ctx = context(geoblender=False)
        layout = draw_topbar(ctx)
        first, second = layout.items[0], layout.items[1]
        self.assertEqual((first.target, first.options["depress"]), (TOGGLE, False))
        self.assertEqual((second.target, second.options["depress"]), (TOGGLE, True))
        self.assertEqual((layout.items[2].kind, layout.items[2].target),
                         ("menu", "GEOBLENDER_MT_ui_geoblender"))
        blender = SimpleNamespace(draw_left=self.saved["draw_left"])
        original = draw(blender, ctx, method="draw_left")
        tail = [(i.kind, i.target, i.text, i.icon) for i in layout.items[3:]]
        self.assertEqual(tail, [(i.kind, i.target, i.text, i.icon) for i in original.items])
        self.assertIn(("template_ID_tabs", ""), controls(layout))

    def test_flow_menus_step_line(self) -> None:
        """RF-003-06: los 11 menús del flujo empiezan con la línea no pulsable «Paso n de
        11 · <etapa>»; Herramientas y Ayuda, no."""
        flow = 0
        for menu_id in self.cat.top_menus:
            spec = self.cat.menus[menu_id]
            layout = draw(getattr(bpy.types, menu_id), context(geoblender=True))
            first = layout.items[0]
            if spec.step is None:
                self.assertFalse(first.text.startswith("Paso "), menu_id)
                continue
            flow += 1
            self.assertEqual(first.kind, "label")
            self.assertEqual(first.text, f"Paso {spec.step} de 11 · {spec.stage_es}")
            self.assertFalse(first.active, menu_id)
        self.assertEqual(flow, 11)

    def test_menus_reference_registered_classes(self) -> None:
        """RF-003-06 (BS §7.2, prueba 5): todo lo que dibujan los menús generados existe:
        operadores, menús y paneles registrados."""
        menus = [cls for cls in self.registry.own_classes() if issubclass(cls, bpy.types.Menu)]
        self.assertGreater(len(menus), 60)
        checked = 0
        for cls in menus:
            for item in draw(cls, context(geoblender=True)).items:
                if item.kind not in ("operator", "menu", "popover"):
                    continue
                checked += 1
                self.assertTrue(_exists(item), f"{cls.bl_idname}: {item.kind} {item.target}")
        self.assertGreater(checked, 400)

    def test_unavailable_disabled_and_hidden(self) -> None:
        """RF-003-07, RF-003-08: lo no disponible se dibuja desactivado; con «Ocultar lo no
        disponible» no se dibuja dentro de los menús, y los 13 menús de la barra siguen."""
        volumetrics = bpy.types.GEOBLENDER_MT_ui_volumetrics
        items = [i for i in draw(volumetrics, context(geoblender=True)).items
                 if i.target == VOLUME]
        self.assertEqual([i.enabled for i in items], [False])
        save = [i for i in draw(bpy.types.GEOBLENDER_MT_ui_project, context(geoblender=True)).items
                if i.target == "geoblender.core_save_project"]
        self.assertEqual([i.enabled for i in save], [True])
        preferences = self.preferences()
        preferences.hide_unavailable = True
        try:
            hidden = draw(volumetrics, context(geoblender=True))
            self.assertNotIn(VOLUME, [i.target for i in hidden.items])
            bar = draw_topbar(context(geoblender=True))
            shown = [t for _k, t in controls(bar) if t in self.cat.top_menus]
            self.assertEqual(shown, list(self.cat.top_menus))
        finally:
            preferences.hide_unavailable = False

    def test_icons_level(self) -> None:
        """BS §3 (nivel D con la preferencia «Iconos»): los 11 menús del flujo, Herramientas
        y Ayuda sin título, con su icono de reserva."""
        preferences = self.preferences()
        preferences.topbar_titles = "ICONS"
        try:
            layout = draw_topbar(context(geoblender=True))
        finally:
            preferences.topbar_titles = "AUTO"
        menus = [i for i in layout.items if i.target in self.cat.top_menus]
        self.assertEqual(len(menus), 13)
        self.assertTrue(all(i.text == "" and i.icon != "NONE" for i in menus))

    def test_install_twice_and_restore(self) -> None:
        """RF-003-24: instalar otra vez no envuelve dos veces; restaurar devuelve el mismo
        objeto original; volver a instalar lo deja como estaba."""
        header = bpy.types.TOPBAR_HT_upper_bar
        wrapper = header.draw_left
        self.assertIsNot(wrapper, self.saved["draw_left"])
        self.assertIs(self.topbar.original_of(wrapper), self.saved["draw_left"])
        self.topbar.install()
        self.assertIs(header.draw_left, wrapper)
        self.topbar.restore()
        self.assertIs(header.draw_left, self.saved["draw_left"])
        self.topbar.install()
        self.assertIs(self.topbar.original_of(header.draw_left), self.saved["draw_left"])
        self.assertTrue(self.topbar.is_installed())


def _exists(item: Item) -> bool:
    if item.kind == "operator":
        module, _, name = item.target.partition(".")
        try:
            getattr(getattr(bpy.ops, module), name).get_rna_type()
        except (AttributeError, KeyError):
            return False
        return True
    cls = getattr(bpy.types, item.target, None)
    return isinstance(cls, type) and (not hasattr(cls, "is_registered") or cls.is_registered)


if __name__ == "__main__":
    unittest.main()
