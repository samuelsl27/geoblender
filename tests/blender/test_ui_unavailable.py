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
- RF-003-08 (convergencia, T45): con «Ocultar lo no disponible», ese menú abierto muestra
  su nota sin un separador colgando, y ningún menú generado deja separadores al principio,
  al final o seguidos, ni el rótulo de un grupo vacío.
- RF-003-24 (convergencia, T45): Ayuda ▸ Reparar la interfaz recalcula la disponibilidad
  y pone otra vez las descripciones (con o sin «Disponible en …»).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

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

    def drawn_menus(self, hide: bool) -> dict[str, list]:
        """Lo que dibuja cada menú generado (salvo los circulares) con «Ocultar lo no
        disponible» en ``hide``."""
        prefs = bpy.context.preferences.addons[module_name()].preferences.ui
        pies = set(self.cat.pies)
        prefs.hide_unavailable = hide
        try:
            return {cls.bl_idname: draw(cls, _context()).items
                    for cls in self.registry.own_classes()
                    if issubclass(cls, bpy.types.Menu) and cls.bl_idname not in pies}
        finally:
            prefs.hide_unavailable = False

    def test_no_dangling_separator(self) -> None:
        """RF-003-08, RF-003-07 (convergencia, T45): con «Ocultar lo no disponible», un
        menú no disponible que se abre (un contextual, por el clic derecho o «<Tipo> ▾»)
        muestra su nota sin un separador colgando; en ningún menú generado queda un
        separador al principio, al final o junto a otro, ni el rótulo de un grupo sin
        nada debajo; sin la preferencia, los separadores son los del catálogo."""
        group_labels = 0
        for hide in (False, True):
            for name, items in self.drawn_menus(hide).items():
                with self.subTest(hide=hide, name=name):
                    kinds = [item.kind for item in items]
                    if "separator" in kinds:
                        self.assertNotEqual(kinds[0], "separator")
                        self.assertNotEqual(kinds[-1], "separator")
                    for index, item in enumerate(items[:-1]):
                        if item.kind == "separator":
                            self.assertNotEqual(items[index + 1].kind, "separator")
                    for index, item in enumerate(items[1:], start=1):
                        group_label = (item.kind == "label" and item.enabled
                                       and not item.active)
                        if group_label and items[index - 1].kind == "separator":
                            group_labels += 1
                            following = items[index + 1:index + 2]
                            self.assertTrue(following, f"«{item.text}» sin nada debajo")
                            self.assertNotEqual(following[0].kind, "separator", item.text)
                    if hide and not self.commands.is_available(name):
                        notes = [item for item in items if item.kind == "label"
                                 and item.text == self.note(name, "es")]
                        self.assertEqual(len(notes), 1)
        self.assertGreater(group_labels, 20)
        hidden = self.drawn_menus(True)
        # Los contextuales no disponibles en los que no queda nada que dibujar.
        alone = [spec.id for spec in self.cat.contexts.values()
                 if not self.commands.is_available(spec.id)
                 and not any(item.placeholder or (item.key is not None
                                                  and self.commands.is_available(item.key))
                             for item in spec.items)]
        self.assertTrue(alone)
        for name in alone:
            with self.subTest(contextual=name):
                self.assertEqual([item.kind for item in hidden[name]], ["label"])
        shown = self.drawn_menus(False)
        for menu_id, spec in self.cat.menus.items():
            if menu_id not in shown:
                continue
            with self.subTest(catalog=menu_id):
                lines = [i for i in shown[menu_id]
                         if i.kind == "separator" and i.options.get("type") == "LINE"]
                plain = [i for i in shown[menu_id]
                         if i.kind == "separator" and i.options.get("type") != "LINE"]
                lead = bool(spec.step) or not self.commands.is_available(menu_id)
                self.assertEqual(len(lines), len(spec.groups) - 1 + int(lead))
                self.assertEqual(len(plain), sum(item.separator for group in spec.groups
                                                 for item in group.items))

    def test_repair_relabels(self) -> None:
        """RF-003-24, RF-003-07 (convergencia, T45): Ayuda ▸ Reparar la interfaz
        recalcula la disponibilidad y pone otra vez los textos: un menú que pasa a estar
        disponible pierde su «Disponible en …» de la descripción emergente, y lo recupera
        cuando deja de estarlo."""
        name = "GEOBLENDER_MT_geo_boolean_solids"
        self.assertFalse(self.commands.is_available(name))
        cls = self.commands.registered_class(name)
        self.assertIn("\n", cls.bl_description)
        about = self.cat.commands[name].description_es
        original = self.commands._compute

        def forced(cat, cmd):
            return True if cmd.key == name else original(cat, cmd)

        ui = _module("bl.ui")
        self.addCleanup(ui.repair)  # la disponibilidad de verdad, también si falla
        with mock.patch.object(self.commands, "_compute", forced):
            self.assertEqual(bpy.ops.geoblender.ui_repair_interface(), {"FINISHED"})
            self.assertTrue(self.commands.is_available(name))
            self.assertEqual(self.commands.registered_class(name).bl_description, about)
        ui.repair()
        self.assertFalse(self.commands.is_available(name))
        self.assertEqual(self.commands.registered_class(name).bl_description,
                         f"{about}\n{self.note(name, 'es')}")


if __name__ == "__main__":
    unittest.main()
