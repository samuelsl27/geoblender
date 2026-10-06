# SPDX-License-Identifier: GPL-3.0-or-later
"""Menús y paneles no disponibles con su «Disponible en …» (spec 003, T39; convergencia,
hallazgo 1 de la verificación).

- RF-003-07, CE-003-04: un submenú (``layout.menu``) o una ventana emergente
  (``popover``) no disponible se dibuja desactivado y no se abre, así que su nota solo se
  puede leer en la descripción emergente: **todos** los menús y paneles del catálogo y
  todos los generados que no están disponibles llevan en su ``bl_description`` la
  descripción del comando y, en otra línea, «Disponible en <entrada · título>» (el mismo
  formato y el mismo ``msgid`` que la de un operador provisional), en español y en inglés
  (al cambiar de idioma sin reiniciar). Los disponibles conservan su descripción, sin
  nota.
- RF-003-07: un menú generado no disponible que sí se puede abrir (el «<Tipo> ▾» de la
  fila 1, el clic derecho, Mayús+Alt+B, ``wm.call_menu``) empieza con la línea gris
  «Disponible en …» (los menús circulares no: sus ranuras ya la dicen en la suya); uno
  disponible, no.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw

# Los 15 elementos del hallazgo (Sección ▾ de la fila 2 es el mismo menú que Geología ▸
# Nueva sección ▸).
FINDING = (
    "GEOBLENDER_MT_core_versions",
    "GEOBLENDER_MT_ui_work_profile",
    "GEOBLENDER_MT_gis_web_services",
    "GEOBLENDER_MT_geo_new_section",
    "GEOBLENDER_MT_geo_boolean_solids",
    "GEOBLENDER_MT_geo_vertical_exaggeration",
    "GEOBLENDER_MT_ui_work_plane",
    "GEOBLENDER_MT_gis_boolean_polygons",
    "GEOBLENDER_MT_plan_drawing_list",
    "GEOBLENDER_PT_geo_band",
    "GEOBLENDER_PT_ui_work_plane",
    "GEOBLENDER_PT_ui_current_object",
    "GEOBLENDER_PT_ui_selection_filter",
    "GEOBLENDER_PT_core_version",
)
NOTE_START = {"es": "Disponible en ", "en": "Available in "}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        workspace=SimpleNamespace(geoblender_mode=True),
        screen=SimpleNamespace(show_fullscreen=False),
        area=None,
        scene=bpy.context.scene,
        space_data=None,
        window=bpy.context.window_manager.windows[0],
    )


class UnavailableNoteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.catalog = _module("core.catalog")
        cls.i18n = _module("core.i18n")
        cls.ui_i18n = _module("bl.ui.i18n")
        cls.commands = _module("bl.ui.commands")
        cls.registry = _module("bl.ui.registry")
        cls.cat = cls.commands.catalog()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def tearDown(self) -> None:
        self.ui_i18n.apply("es")

    def names(self) -> list[str]:
        """Los menús y paneles del catálogo y los que generó la interfaz."""
        generated = {cls.bl_idname for cls in self.registry.own_classes()
                     if issubclass(cls, (bpy.types.Menu, bpy.types.Panel))}
        return sorted(set(self.cat.class_names()) | generated)

    def note(self, name: str, language: str) -> str:
        return self.catalog.unavailable_text(self.cat, self.cat.commands[name], language)

    def test_tooltips_in_both_languages(self) -> None:
        """RF-003-07, CE-003-04: cada menú o panel no disponible lleva «Disponible en …»
        en otra línea de su descripción emergente, en los dos idiomas; los disponibles,
        su descripción sin cambios."""
        for language in ("es", "en"):
            self.ui_i18n.apply(language)
            unavailable: list[str] = []
            available = 0
            for name in self.names():
                with self.subTest(language=language, name=name):
                    cls = self.commands.registered_class(name)
                    self.assertIsNotNone(cls)
                    about = self.i18n.translate(language,
                                                self.cat.commands[name].description)
                    if self.commands.is_available(name):
                        available += 1
                        self.assertEqual(cls.bl_description, about)
                        continue
                    unavailable.append(name)
                    note = self.note(name, language)
                    self.assertTrue(note.startswith(NOTE_START[language]), note)
                    self.assertEqual(cls.bl_description, f"{about}\n{note}")
            self.assertGreater(available, 40, language)
            self.assertGreaterEqual(len(unavailable), 30, language)
            self.assertEqual(sorted(set(FINDING) - set(unavailable)), [], language)

    def test_same_format_as_operators(self) -> None:
        """RF-003-07: la nota de un menú no disponible es la misma línea que añade a su
        descripción un operador provisional de la misma entrada (R-16)."""
        section = self.commands.registered_class("GEOBLENDER_MT_geo_new_section")
        operator = self.commands.registered_class("geoblender.geo_new_section")
        tooltip = operator.description(bpy.context, SimpleNamespace(mode="NORTH_SOUTH"))
        self.assertEqual(section.bl_description.splitlines()[-1], tooltip.splitlines()[-1])
        self.assertTrue(tooltip.splitlines()[-1].startswith("Disponible en R-16 · "))

    def test_first_line_inside(self) -> None:
        """RF-003-07: un menú generado no disponible (salvo los circulares) empieza con la
        línea gris «Disponible en …» (tras «Paso n de 11», si la tiene); uno disponible no
        la dibuja; en los dos idiomas."""
        pies = set(self.cat.pies)
        for language in ("es", "en"):
            self.ui_i18n.apply(language)
            checked = 0
            for cls in self.registry.own_classes():
                name = cls.bl_idname
                if not issubclass(cls, bpy.types.Menu) or name in pies:
                    continue
                with self.subTest(language=language, name=name):
                    note = self.note(name, language)
                    labels = [item for item in draw(cls, _context()).items
                              if item.kind == "label"]
                    if self.commands.is_available(name):
                        self.assertNotIn(note, [item.text for item in labels])
                        continue
                    checked += 1
                    self.assertTrue(labels, "sin ninguna línea")
                    first = labels[0]
                    if first.text.startswith(("Paso ", "Step ")):
                        first = labels[1]
                    self.assertEqual(first.text, note)
                    self.assertFalse(first.enabled and first.active)
            self.assertGreaterEqual(checked, 20, language)


if __name__ == "__main__":
    unittest.main()
