# SPDX-License-Identifier: GPL-3.0-or-later
"""Los menús generados desde el catálogo (spec 003, T12; BS §7.1 y §8.14; AR §4; PC §3).

- RF-003-06: cada comando tiene una única definición que comparten todos los sitios donde
  aparece: el mismo operador con las mismas propiedades se dibuja con la misma etiqueta y
  el mismo icono en su casa, en un acceso cruzado ↗ (con la marca), en «Datos ▾», en los
  menús circulares y en los contextuales.
- RF-003-04: «Geoblender ▾» tiene los 13 menús de la barra, en su orden; desde fuera de una
  Vista 3D (la barra superior), un comando de Geoblender pasa su ``poll`` también en modo
  Blender.
- Spec 008, T44 (RF-008-06, RF-008-16, RF-008-26, RF-008-28, RF-008-29): las órdenes de
  Proyecto ▸ Control y el panel de lo obsoleto son de la entrada ``008`` (mientras sean
  provisionales, «Disponible en 008 · …»; el panel, real desde T49, ya está disponible); lo
  de la 009 sigue «Disponible en R-07 · …»; las nueve órdenes internas del plan 008 §5.3.2
  están registradas con su ``bl_idname`` y no salen en los menús; al habilitar, los textos
  de la procedencia y de los parámetros están en ``core.i18n``.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw


PROVENANCE_NOTE = "Disponible en 008 · Procedencia: parámetros, entradas, operaciones y cifras"
VERSIONS_NOTE = "Disponible en R-07 · Versiones y procedencia"
# Proyecto ▸ Control (y su submenú Procedencia y registro): spec 008, plan §5.5.
CONTROL = {
    "GEOBLENDER_MT_ui_project": ("geoblender.core_show_parameters",
                                 "geoblender.core_show_inputs",
                                 "geoblender.core_check_inputs",
                                 "geoblender.core_recompute_stale"),
    "GEOBLENDER_MT_core_provenance": ("geoblender.core_show_lineage",),
}
LATER = ("geoblender.core_new_version", "geoblender.core_show_decisions",
         "geoblender.core_reproduce_version", "geoblender.core_refresh")
INTERNAL = ("core_set_parameter", "core_confirm_parameter", "core_resolve_input",
            "core_discard_input", "core_edit_input", "core_resolve_dataset",
            "core_accept_review", "core_resolve_unregistered", "core_cancel_checks")
# Las órdenes de la 008 que ya tienen su clase real (spec 008, fase 8): disponibles, sin nota.
REAL = ("geoblender.core_show_parameters", "geoblender.core_set_parameter",
        "geoblender.core_confirm_parameter", "geoblender.core_show_inputs",
        "geoblender.core_check_inputs", "geoblender.core_resolve_input",
        "geoblender.core_discard_input", "geoblender.core_edit_input",
        "geoblender.core_recompute_stale")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _reported(cls: type) -> list[tuple[set[str], str]]:
    """Lo que informa ``execute`` de un operador provisional."""
    reports: list[tuple[set[str], str]] = []
    fake = SimpleNamespace(properties=SimpleNamespace(),
                           report=lambda kind, text: reports.append((kind, text)))
    cls.execute(fake, bpy.context)
    return reports


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        workspace=SimpleNamespace(geoblender_mode=True),
        screen=SimpleNamespace(show_fullscreen=False),
        area=None,
        scene=bpy.context.scene,
        space_data=None,
        window=bpy.context.window_manager.windows[0],
    )


class UiCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.schema = _module("core.catalog.schema")
        cls.registry = _module("bl.ui.registry")
        cls.drawing = _module("bl.ui.drawing")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def test_mirrors_share_one_definition(self) -> None:
        """RF-003-06: en todos los menús generados, un mismo comando (operador y
        propiedades, o submenú) se dibuja con la misma etiqueta (sin la marca ↗) y el
        mismo icono; y los ↗ llevan la marca."""
        seen: dict[str, tuple[str, str, str]] = {}
        crosses = 0
        menus = [c for c in self.registry.own_classes() if issubclass(c, bpy.types.Menu)]
        for cls in menus:
            for item in draw(cls, _context()).items:
                if item.kind not in ("operator", "menu", "popover"):
                    continue
                props = vars(item.properties) if item.kind == "operator" else {}
                key = self.schema.make_key(item.target, props)
                text = item.text
                if text.startswith(self.drawing.CROSS_MARK):
                    crosses += 1
                    text = text[len(self.drawing.CROSS_MARK):]
                where = f"{cls.bl_idname}"
                first = seen.setdefault(key, (text, item.icon, where))
                self.assertEqual((text, item.icon), first[:2],
                                 f"{key}: en {where} y en {first[2]}")
        self.assertGreater(crosses, 20)
        plan = self.schema.make_key("geoblender.ui_set_view", {"view": "PLAN"})
        self.assertEqual(seen[plan][0], "Planta")

    def test_cross_access_marked(self) -> None:
        """RF-003-06 (BS §6): el MDT ráster tiene su casa en Topografía y aparece en
        Importar ▸ como acceso cruzado ↗, con la misma etiqueta."""
        dtm = "geoblender.gis_import_dtm"
        home = [i.text for i in draw(bpy.types.GEOBLENDER_MT_ui_topography, _context()).items
                if i.target == dtm]
        hub = [i.text for i in draw(bpy.types.GEOBLENDER_MT_io_import, _context()).items
               if i.target == dtm]
        label = self.cat.commands[dtm].label_es
        self.assertEqual(home, [label])
        self.assertEqual(hub, [self.drawing.CROSS_MARK + label])

    def test_geoblender_menu(self) -> None:
        """RF-003-04: «Geoblender ▾» tiene los 13 menús de la barra como submenús, en su
        orden y con su título."""
        layout = draw(bpy.types.GEOBLENDER_MT_ui_geoblender, _context())
        menus = [(i.target, i.text) for i in layout.items if i.kind == "menu"]
        self.assertEqual(menus, [(m, self.cat.commands[m].label_es) for m in self.cat.top_menus])
        self.assertTrue(all(i.enabled for i in layout.items if i.kind == "menu"))

    def test_pie_slots(self) -> None:
        """RF-003-06 (AR §4): el menú circular de vistas dibuja sus 8 ranuras en el orden
        de Blender con los comandos del catálogo."""
        pie = self.cat.pies["GEOBLENDER_MT_ui_pie_views"]
        layout = draw(bpy.types.GEOBLENDER_MT_ui_pie_views, _context())
        keys = [self.schema.make_key(i.target, vars(i.properties))
                for i in layout.items if i.kind == "operator"]
        self.assertEqual(keys, list(pie.slots))

    def test_poll_from_topbar_in_blender_mode(self) -> None:
        """RF-003-04: fuera de una Vista 3D (barra superior, «Geoblender ▾»), un comando de
        Geoblender pasa la puerta de modo con el espacio de trabajo sin marcar."""
        self.assertFalse(bpy.context.window.workspace.geoblender_mode)
        self.assertIsNone(bpy.context.area)
        self.assertTrue(bpy.ops.geoblender.res_compute_volume_between_surfaces.poll())
        self.assertTrue(bpy.ops.geoblender.ui_set_view.poll())

    def test_provenance_commands_in_008(self) -> None:
        """RF-008-06, RF-008-16, RF-008-26, RF-008-28, RF-008-29: Proyecto ▸ Control dibuja
        las órdenes de la 008 con su etiqueta; mientras su operador sea provisional, salen
        desactivadas y dicen «Disponible en 008 · …», y las que ya tienen su clase real
        (Parámetros del proyecto, T50; Registro de entradas y Comprobar cambios en las
        entradas, T51; Recalcular lo obsoleto, T53) salen disponibles; el panel de lo obsoleto
        del control 7 ya es el real (T49) y está disponible, sin nota; lo de la 009 sigue
        «Disponible en R-07 · …»."""
        commands = _module("bl.ui.commands")
        for menu, idnames in CONTROL.items():
            drawn = {i.target: i for i in draw(getattr(bpy.types, menu), _context()).items
                     if i.kind == "operator"}
            for idname in idnames:
                with self.subTest(idname=idname):
                    item = drawn[idname]
                    self.assertEqual(item.text, self.cat.commands[idname].label_es)
                    cls = commands.registered_class(idname)
                    if idname in REAL:
                        self.assertFalse(commands.is_provisional(cls))
                        self.assertTrue(item.enabled)
                        self.assertTrue(commands.is_available(idname))
                        continue
                    self.assertTrue(commands.is_provisional(cls))
                    self.assertFalse(item.enabled)
                    self.assertEqual(_reported(cls), [({"INFO"}, PROVENANCE_NOTE)])
        stale = self.cat.commands["GEOBLENDER_PT_core_stale"]
        self.assertTrue(commands.is_available(stale.key))
        self.assertFalse(commands.is_provisional(commands.registered_class(stale.key)))
        self.assertNotIn(PROVENANCE_NOTE, bpy.types.GEOBLENDER_PT_core_stale.bl_description)
        for idname in LATER:
            with self.subTest(idname=idname):
                self.assertEqual(commands.unavailable_note(self.cat.commands[idname]),
                                 VERSIONS_NOTE)

    def test_internal_provenance_operators(self) -> None:
        """RF-008-06, RF-008-26, RF-008-28 (plan 008 §5.3.2): las nueve órdenes internas
        están registradas con su ``bl_idname`` (internas: fuera de F3) y ningún menú las
        dibuja; las provisionales, invocadas, informan «Disponible en 008 · …» sin hacer
        nada, y las que ya tienen su clase real (Cambiar y Confirmar parámetro, T50; Decidir
        sobre una entrada cambiada, Descartar y Editar entrada, T52) están disponibles."""
        commands = _module("bl.ui.commands")
        drawn = {i.target for cls in self.registry.own_classes()
                 if issubclass(cls, bpy.types.Menu)
                 for i in draw(cls, _context()).items if i.kind == "operator"}
        for name in INTERNAL:
            idname = f"geoblender.{name}"
            with self.subTest(idname=idname):
                cls = commands.registered_class(idname)
                self.assertIn("INTERNAL", cls.bl_options)
                self.assertNotIn(idname, drawn)
                if idname in REAL:
                    self.assertFalse(commands.is_provisional(cls))
                    self.assertTrue(commands.is_available(idname))
                    continue
                self.assertTrue(commands.is_provisional(cls))
                self.assertEqual(getattr(bpy.ops.geoblender, name)(), {"CANCELLED"})
                self.assertEqual(_reported(cls), [({"INFO"}, PROVENANCE_NOTE)])

    def test_provenance_messages_installed(self) -> None:
        """RF-008-29 (principio 10; plan 008 §5.1): al habilitar Geoblender, los textos de
        la procedencia y de los parámetros están en ``core.i18n``: cada ``msgid`` sale en
        español y igual que su ``render``."""
        i18n = _module("core.i18n")
        provenance = _module("core.provenance.messages")
        params = _module("core.params")
        self.assertEqual(i18n.untranslated([*provenance.CATALOG_ES, *params.CATALOG_ES]), [])
        read_only = provenance.MESSAGES["core.read_only"]
        values = {"project": "Cantera", "reason": "cerrojo de otra sesión"}
        self.assertEqual(i18n.translate("es", read_only.msgid, **values),
                         provenance.render("core.read_only", **values))
        self.assertEqual(i18n.translate("es", provenance.ACCEPT_REVIEW_MSGID), "Dar por buena")
        missing = params.MESSAGES["core.param_missing"]
        self.assertEqual(i18n.translate("es", missing.msgid, key="res.k"),
                         params.render("core.param_missing", key="res.k"))


if __name__ == "__main__":
    unittest.main()
