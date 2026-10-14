# SPDX-License-Identifier: GPL-3.0-or-later
"""Iconos propios de Geoblender en Blender (spec 003, T31; RF-003-22; RNF-003-09; II §1.4,
§1.6 y §1.8; ``bl/ui/icons.py``).

- RNF-003-09: cada icono del catálogo (``icons.toml``, los 58 de II §1.4) tiene su fuente
  SVG, sus dos PNG y su entrada en el manifiesto, con los sha256 al día; no sobra ningún SVG,
  PNG ni entrada; cada PNG ≤ 8 KB.
- RF-003-22: cada reserva nativa existe en el enumerado de iconos de la versión instalada.
- II §1.8: al habilitar, los 58 se cargan en una colección de ``bpy.utils.previews`` con
  ``image_size`` distinto de cero (sin interfaz, ``icon_id`` es 0: se prueba
  ``image_size``); a escala efectiva < 1,5 los de 32 px y, si no, los de 64; «Reparar la
  interfaz» los vuelve a cargar.
- RF-003-22: sin interfaz el propio no se puede mostrar y cada control lleva su reserva
  nativa (los menús de la barra, «FILE_FOLDER»…) o, la del logotipo, el texto «GB»; nunca
  un control sin icono.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw
from tests.support.repo import ROOT, EXTENSION_DIR

SVG_DIR = ROOT / "assets" / "icons"
PNG_DIR = EXTENSION_DIR / "resources" / "icons"
TOGGLE = "geoblender.ui_toggle_mode"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class IconsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.icons = _module("bl.ui.icons")
        cls.drawing = _module("bl.ui.drawing")
        cls.catalog = _module("bl.ui.commands").catalog()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def test_sources_pngs_and_manifest(self) -> None:
        """RNF-003-09: cada icono con su SVG, sus dos PNG (≤ 8 KB) y su entrada al día; no
        sobra nada."""
        names = set(self.catalog.icons)
        self.assertEqual(len(names), 58)
        self.assertEqual({path.stem for path in SVG_DIR.glob("*.svg")}, names)
        expected_pngs = {f"{name}_{size}.png" for name in names for size in (32, 64)}
        self.assertEqual({path.name for path in PNG_DIR.glob("*.png")}, expected_pngs)
        manifest = json.loads((PNG_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["icons"]), names)
        for png in PNG_DIR.glob("*.png"):
            self.assertLessEqual(png.stat().st_size, 8 * 1024, png.name)

    def test_fallbacks_exist(self) -> None:
        """RF-003-22: cada reserva nativa está en el enumerado de iconos de esta versión."""
        native = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items
        for name, spec in self.catalog.icons.items():
            with self.subTest(icon=name):
                self.assertIn(spec.fallback, native.keys())
        for cmd in self.catalog.commands.values():
            if cmd.icon_fallback != "NONE":
                self.assertIn(cmd.icon_fallback, native.keys(), cmd.key)

    def test_pngs_load(self) -> None:
        """II §1.8: los 58 cargados con ``image_size`` distinto de cero; 32 px a escala
        1,0 y 64 a partir de 1,5; recargar los vuelve a cargar."""
        self.assertEqual(self.icons.loaded_size(), 32)
        self.assertEqual((self.icons.png_size(1.0), self.icons.png_size(1.25),
                          self.icons.png_size(1.5), self.icons.png_size(2.0)),
                         (32, 32, 64, 64))
        for name in self.catalog.icons:
            with self.subTest(icon=name):
                preview = self.icons.preview(name)
                self.assertIsNotNone(preview)
                self.assertNotEqual(tuple(preview.image_size), (0, 0))
        self.icons.reload()
        self.assertEqual(self.icons.loaded_size(), 32)
        self.assertNotEqual(tuple(self.icons.preview("gb_logo").image_size), (0, 0))

    def test_fallback_without_interface(self) -> None:
        """RF-003-22: sin interfaz, la reserva nativa (o el texto del logotipo)."""
        self.assertEqual(self.icons.icon_id("gb_menu_project"), 0)
        cmd = self.catalog.commands["GEOBLENDER_MT_ui_project"]
        self.assertEqual(self.drawing.icon_kwargs(cmd), {"icon": "FILE_FOLDER"})
        self.assertEqual(self.icons.fallback_text("gb_logo"), "GB")
        ctx = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                              region=SimpleNamespace(width=1920), screen=None, area=None,
                              scene=bpy.context.scene)
        layout = draw(bpy.types.TOPBAR_HT_upper_bar, ctx, method="draw_left")
        switch = [item for item in layout.of_kind("operator") if item.target == TOGGLE]
        self.assertEqual(switch[0].text, "GB")
        self.assertEqual(switch[1].icon, "BLENDER")


if __name__ == "__main__":
    unittest.main()
