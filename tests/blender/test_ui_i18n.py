# SPDX-License-Identifier: GPL-3.0-or-later
"""Idioma de Geoblender, propio e independiente del de Blender (spec 003, T28; RF-003-20,
RF-003-21; RNF-003-05; plan 003 §5.4, 11, DT4; II §2).

- RF-003-20: con Blender en inglés, Geoblender se ve en español (por defecto): la barra,
  los nombres de los comandos (F3) y los atajos.
- RF-003-20, RF-003-21: con Blender en español y Geoblender en inglés, «Project» y no
  «Proyectar»: las clases llevan ``bl_translation_context = "Geoblender"`` y Blender no
  traduce sus textos (y se dibujan con ``translate=False``).
- RF-003-21, RNF-003-05: cambiar de idioma sin reiniciar (``bl.ui.i18n.apply``) vuelve a
  registrar las clases con los textos nuevos en ≤ 500 ms; los 49 atajos siguen registrados
  y con el nombre nuevo; la pestaña «Proyecto» de la barra lateral también cambia.
- RF-003-21: elegir el idioma en las preferencias lo deja pendiente y se aplica en el
  siguiente ciclo (temporizador, que en segundo plano no corre: la prueba lo aplica a
  mano); el idioma de Blender no cambia.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw

TOGGLE = "geoblender.ui_toggle_mode"
SWITCH_ES = "Conmutar Geoblender ⇄ Blender"
SWITCH_EN = "Switch Geoblender ⇄ Blender"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class LanguageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.ui_i18n = _module("bl.ui.i18n")
        cls.i18n = _module("core.i18n")
        cls.keymap = _module("bl.ui.keymap")
        cls.registry = _module("bl.ui.registry")
        cls.commands = _module("bl.ui.commands")
        cls.context = cls.commands.TRANSLATION_CONTEXT
        view = bpy.context.preferences.view
        cls.blender_language = (view.language, view.use_translate_interface)

    @classmethod
    def tearDownClass(cls) -> None:
        view = bpy.context.preferences.view
        view.language, view.use_translate_interface = cls.blender_language
        blender_ext.load_file()
        blender_ext.unload()

    def tearDown(self) -> None:
        prefs = self.commands.preferences()
        if prefs.language != "ES":
            prefs.language = "ES"
        self.ui_i18n.apply("es")
        self.ui_i18n.cancel()
        view = bpy.context.preferences.view
        view.language, view.use_translate_interface = self.blender_language

    def blender_in(self, language: str) -> None:
        view = bpy.context.preferences.view
        view.language = language
        view.use_translate_interface = True

    def topbar_texts(self) -> list[str]:
        ctx = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                              region=SimpleNamespace(width=1920), screen=None, area=None,
                              scene=bpy.context.scene)
        layout = draw(bpy.types.TOPBAR_HT_upper_bar, ctx, method="draw_left")
        return layout.texts()

    def operator_name(self, idname: str) -> str:
        module, _, name = idname.partition(".")
        return getattr(getattr(bpy.ops, module), name).get_rna_type().name

    def test_spanish_with_blender_in_english(self) -> None:
        """RF-003-20: Blender en inglés, Geoblender en español."""
        self.blender_in("en_US")
        self.assertIn("Proyecto", self.topbar_texts())
        self.assertEqual(bpy.types.GEOBLENDER_MT_ui_project.bl_label, "Proyecto")
        self.assertEqual(self.operator_name(TOGGLE), SWITCH_ES)
        self.assertEqual(bpy.types.GEOBLENDER_PT_core_project.bl_category, "Proyecto")

    def test_english_with_blender_in_spanish(self) -> None:
        """RF-003-20, RF-003-21: Blender en español, Geoblender en inglés: «Project», no
        «Proyectar»; todas las clases con el contexto de traducción propio."""
        self.blender_in("es")
        self.ui_i18n.apply("en")
        self.assertIn("Project", self.topbar_texts())
        self.assertNotIn("Proyectar", self.topbar_texts())
        label = bpy.types.GEOBLENDER_MT_ui_project.bl_label
        self.assertEqual(label, "Project")
        self.assertEqual(bpy.app.translations.pgettext_iface(label, self.context), "Project")
        self.assertEqual(bpy.app.translations.pgettext_iface("Project"), "Proyectar")
        self.assertEqual(self.operator_name(TOGGLE), SWITCH_EN)
        cat = self.commands.catalog()
        for name in (*sorted(cat.operator_idnames()), *sorted(cat.class_names())):
            cls = self.commands.registered_class(name)
            if cls is not None:
                self.assertEqual(cls.bl_translation_context, self.context, name)
        self.assertEqual(bpy.context.preferences.view.language, "es")

    def test_switch_without_restart(self) -> None:
        """RF-003-21, RNF-003-05: el cambio vuelve a registrar las clases en ≤ 500 ms; los
        49 atajos siguen y con el nombre nuevo; la pestaña «Proyecto» cambia."""
        items = self.keymap.registered_items()
        self.assertEqual(len(items), 49)
        elapsed = self.ui_i18n.apply("en")
        self.assertLess(elapsed, 500.0)
        self.assertEqual(self.keymap.registered_items(), items)
        toggle = [item for _keymap, item in items if item.idname == TOGGLE]
        self.assertEqual([item.name for item in toggle], [SWITCH_EN])
        self.assertEqual(bpy.types.GEOBLENDER_PT_core_project.bl_category, "Project")
        self.assertEqual(self.i18n.language(), "en")
        self.ui_i18n.apply("es")
        self.assertEqual([item.name for item in toggle], [SWITCH_ES])
        self.assertEqual(bpy.types.GEOBLENDER_PT_core_project.bl_category, "Proyecto")

    def test_preference_schedules_change(self) -> None:
        """RF-003-21: elegir el idioma en las preferencias lo deja pendiente (se aplica en
        el siguiente ciclo); el idioma de Blender no cambia."""
        before = bpy.context.preferences.view.language
        prefs = self.commands.preferences()
        prefs.language = "EN"
        self.assertEqual(self.ui_i18n.pending(), "en")
        self.assertEqual(self.i18n.language(), "es")  # aún no
        self.ui_i18n.apply_pending()
        self.assertEqual(self.i18n.language(), "en")
        self.assertEqual(self.operator_name(TOGGLE), SWITCH_EN)
        self.assertIsNone(self.ui_i18n.pending())
        self.assertEqual(bpy.context.preferences.view.language, before)

    def test_operator_properties_follow_the_language(self) -> None:
        """RF-003-21 (T33): los nombres de las propiedades de los operadores (panel F9,
        mapa de teclado) y de los elementos de sus enumerados cambian con el idioma, sin
        reiniciar, con el contexto propio; los atajos con propiedades siguen igual."""
        def half_width() -> bpy.types.Property:
            return bpy.ops.geoblender.geo_set_clip_mode.get_rna_type().properties["half_width"]

        def plan_item() -> str:
            view = bpy.ops.geoblender.ui_set_view.get_rna_type().properties["view"]
            return view.enum_items["PLAN"].name

        self.assertEqual((half_width().name, half_width().translation_context),
                         ("Semiancho", self.context))
        self.assertEqual(plan_item(), "Planta")
        self.assertEqual(half_width().default, 5.0)
        slots = [item.properties.slot for _km, item in self.keymap.registered_items()
                 if item.idname == "geoblender.ui_recall_view"]
        self.ui_i18n.apply("en")
        self.assertEqual(half_width().name, "Half width")
        self.assertEqual(plan_item(), "Plan")
        self.assertEqual([item.properties.slot for _km, item in self.keymap.registered_items()
                          if item.idname == "geoblender.ui_recall_view"], slots)
        self.ui_i18n.apply("es")
        self.assertEqual(half_width().name, "Semiancho")

    def test_property_groups_after_restart(self) -> None:
        """RF-003-20, RF-003-21 (T37; spec §8): las propiedades de los grupos (las
        preferencias, la escena) se registran en el idioma de la última sesión: cambian al
        reiniciar (aquí, deshabilitar y volver a habilitar) y vuelven a su texto al
        desregistrar."""
        props_ui = _module("bl.props.ui")
        spanish = "Idioma de la interfaz de Geoblender, independiente del de Blender"
        english = "Language of the Geoblender interface, independent of Blender's"

        def description() -> str:
            rna = props_ui.GEOBLENDER_PG_ui_preferences.bl_rna
            return rna.properties["language"].description

        self.assertEqual(description(), spanish)
        self.assertEqual(props_ui.remembered_language(), "es")
        self.ui_i18n.apply("en")
        self.assertEqual(props_ui.remembered_language(), "en")
        self.assertEqual(description(), spanish)  # hasta reiniciar
        blender_ext.disable()
        self.addCleanup(self.ui_i18n.apply, "es")
        blender_ext.enable()
        self.assertEqual(description(), english)
        self.assertEqual(self.i18n.language(), "es")  # el de las preferencias
        blender_ext.disable()
        blender_ext.enable()
        self.assertEqual(description(), spanish)


if __name__ == "__main__":
    unittest.main()
