# SPDX-License-Identifier: GPL-3.0-or-later
"""Los menús generados desde el catálogo (spec 003, T12; BS §7.1 y §8.14; AR §4; PC §3).

- RF-003-06: cada comando tiene una única definición que comparten todos los sitios donde
  aparece: el mismo operador con las mismas propiedades se dibuja con la misma etiqueta y
  el mismo icono en su casa, en un acceso cruzado ↗ (con la marca), en «Datos ▾», en los
  menús circulares y en los contextuales.
- RF-003-04: «Geoblender ▾» tiene los 13 menús de la barra, en su orden; desde fuera de una
  Vista 3D (la barra superior), un comando de Geoblender pasa su ``poll`` también en modo
  Blender.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw


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


if __name__ == "__main__":
    unittest.main()
