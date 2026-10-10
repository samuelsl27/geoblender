# SPDX-License-Identifier: GPL-3.0-or-later
"""Nivel de la barra superior según la anchura (spec 003, T18; BS §2.3 y §3; RF-003-10,
RNF-003-01).

Los títulos se miden con ``blf`` (fuente de la interfaz a 11 pt, la de BS §2.2) en el
idioma pedido, y el modelo usa las constantes de ``bl/compat.py`` de la versión de Blender
en ejecución (sin interfaz, ``ui_scale`` vale 0: la escala se pasa como parámetro):

- RNF-003-01: a 1920 px, el nivel B deja ≥ 150 px libres a escala 1,0 y el nivel C ≥ 24 px
  a escala 1,25, en español y en inglés; en automático, B a 1,0 en español (en inglés cabe
  también A, el primero de A a E) y C a 1,25 en los dos (RF-003-10).
- RF-003-10: el nivel fijado en las preferencias («Texto» = B, «Iconos» = D) se respeta
  aunque no quepa o sobre sitio.
- RF-003-10 (dibujo, con el *layout* simulado): cada nivel dibuja lo suyo (A: icono y
  título; B: títulos; C: Herramientas y Ayuda en icono; D: los 11 del flujo en icono; E: un
  único «Geoblender ▾»), y cada menú de texto lleva su ancho explícito (``ui_units_x``) con
  sitio para el título entero: no se recorta ninguno.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, draw


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def context(width: float) -> SimpleNamespace:
    """La barra superior de una ventana en modo Geoblender de ``width`` px."""
    return SimpleNamespace(
        workspace=SimpleNamespace(geoblender_mode=True, use_filter_by_owner=False),
        screen=SimpleNamespace(show_fullscreen=False, show_statusbar=True),
        area=SimpleNamespace(show_menus=True, type="TOPBAR"),
        region=SimpleNamespace(alignment="LEFT", width=width),
        window=bpy.context.window_manager.windows[0],
        scene=bpy.context.scene,
        space_data=None,
    )


def regions_context(left: float, right: float) -> SimpleNamespace:
    """Como :func:`context`, pero con las regiones de la barra de Blender 5.2 (T42): la de
    ``draw_left`` (cabecera ``TOP`` de ``left`` px) y la del bloque derecho (cabecera
    ``RIGHT`` de ``right`` px)."""
    found = context(left)
    found.region = SimpleNamespace(type="HEADER", alignment="TOP", width=left)
    found.area = SimpleNamespace(show_menus=True, type="TOPBAR", regions=[
        found.region, SimpleNamespace(type="HEADER", alignment="RIGHT", width=right),
        SimpleNamespace(type="WINDOW", alignment="NONE", width=left + right)])
    return found


class TopbarWidthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.width = _module("core.catalog.width")
        cls.i18n = _module("core.i18n")
        cls.compat = _module("bl.compat")
        cls.topbar = _module("bl.ui.topbar")
        cls.k = cls.compat.topbar_width_constants()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def tearDown(self) -> None:
        self.preferences().topbar_titles = "AUTO"
        self.preferences().language = "ES"
        self.i18n.set_language("es")

    def preferences(self) -> object:
        return bpy.context.preferences.addons[module_name()].preferences.ui

    def free(self, level: object, region: float, scale: float, language: str) -> float:
        return self.width.topbar_free_px(level, region_width_px=region, scale=scale,
                                         titles_px=self.topbar.titles_px(language), k=self.k)

    def choose(self, region: float, scale: float, language: str) -> object:
        return self.width.choose_topbar_level(region_width_px=region, scale=scale,
                                              titles_px=self.topbar.titles_px(language),
                                              k=self.k)

    def draw_bar(self, width: float, *, scale: float = 1.0) -> FakeLayout:
        with mock.patch.object(self.compat, "ui_scale", return_value=scale):
            return draw(bpy.types.TOPBAR_HT_upper_bar, context(width), method="draw_left")

    def menus(self, layout: FakeLayout) -> list[object]:
        return [item for item in layout.items
                if item.kind == "menu" and item.target.startswith("GEOBLENDER_MT_ui_")]

    def test_titles_measured_with_blf(self) -> None:
        """RF-003-10 (BS §2.3): los títulos se miden con ``blf`` en cada idioma, también el
        de «Geoblender ▾» (nivel E); en inglés son más cortos que en español."""
        spanish, english = self.topbar.titles_px("es"), self.topbar.titles_px("en")
        expected = {*self.cat.top_menus, self.width.GEOBLENDER_MENU}
        self.assertEqual(set(spanish), expected)
        self.assertEqual(set(english), expected)
        self.assertTrue(all(value > 10 for value in spanish.values()))
        self.assertLess(sum(english.values()), sum(spanish.values()))

    def test_budget_at_1920(self) -> None:
        """RNF-003-01: a 1920 px, B deja ≥ 150 px a 1,0 y C ≥ 24 px a 1,25, en español y
        en inglés; en automático, B (español) o A (inglés) a 1,0 y C a 1,25."""
        Level = self.width.Level
        for language in ("es", "en"):
            with self.subTest(language=language):
                self.assertGreaterEqual(self.free(Level.B, 1920, 1.0, language), 150)
                self.assertGreaterEqual(self.free(Level.C, 1920, 1.25, language), 24)
                self.assertIs(self.choose(1920, 1.25, language), Level.C)
        self.assertIs(self.choose(1920, 1.0, "es"), Level.B)
        self.assertIs(self.choose(1920, 1.0, "en"), Level.A)

    def test_constants_by_version(self) -> None:
        """BS §2.3 (plan 003 DT13): las constantes son las de la versión de Blender en
        ejecución, con la versión y la fecha de su medida."""
        major, minor, _patch = bpy.app.version
        self.assertTrue(self.k.blender_version.startswith(f"{major}.{minor}"))
        self.assertTrue(self.k.measured)

    def test_levels_drawn(self) -> None:
        """RF-003-10: B a 1920 px (13 títulos), C a 1600 px (Herramientas y Ayuda en
        icono), D a 1366 px (los 13 en icono), E a 800 px («Geoblender ▾» sin los 13) y C
        a 1920 px con escala 1,25."""
        tools, help_ = self.width.TOOLS_MENU, self.width.HELP_MENU
        menus = self.menus(self.draw_bar(1920))
        self.assertEqual([item.target for item in menus], list(self.cat.top_menus))
        self.assertTrue(all(item.text for item in menus))
        for width, scale in ((1600, 1.0), (1920, 1.25)):
            with self.subTest(width=width, scale=scale):
                menus = self.menus(self.draw_bar(width, scale=scale))
                icons = [item.target for item in menus if not item.text]
                self.assertEqual(icons, [tools, help_])
        menus = self.menus(self.draw_bar(1366))
        self.assertEqual(len(menus), 13)
        self.assertTrue(all(not item.text and item.icon != "NONE" for item in menus))
        menus = self.menus(self.draw_bar(800))
        self.assertEqual([item.target for item in menus], [self.width.GEOBLENDER_MENU])

    def test_english_level_a(self) -> None:
        """RF-003-10 (BS §3): en inglés a 1920 px y 1,0 cabe A: icono y título en los 11
        del flujo y en Herramientas; Ayuda, solo el título."""
        self.preferences().language = "EN"
        self.i18n.set_language("en")
        menus = self.menus(self.draw_bar(1920))
        with_icon = [item.target for item in menus if item.text and item.icon != "NONE"]
        self.assertEqual(with_icon, list(self.cat.top_menus[:-1]))
        self.assertEqual(menus[0].text, "Project")

    def test_no_clipped_title(self) -> None:
        """RF-003-10, CE-003-03: cada menú de texto lleva ``ui_units_x`` con sitio para su
        título medido y su relleno (y el icono en el nivel A), en los dos idiomas."""
        unit = self.compat.UI_UNIT_PX
        for language, width in (("es", 1920), ("en", 1920), ("es", 1600), ("es", 800)):
            with self.subTest(language=language, width=width):
                self.preferences().language = language.upper()
                self.i18n.set_language(language)
                titles = self.topbar.titles_px(language)
                for item in self.menus(self.draw_bar(width)):
                    if not item.text:
                        continue
                    needed = titles[item.target] + self.k.menu_pad - self.k.menu_gap
                    if item.icon != "NONE":
                        needed += self.k.title_icon
                    self.assertGreaterEqual(item.units_x * unit, needed - 0.01, item.target)

    def test_level_in_blender_regions(self) -> None:
        """RF-003-10, RNF-003-01 (convergencia, T42; hallazgo D2 de la pantalla): la barra
        de Blender 5.2 son dos regiones de cabecera, la de ``draw_left`` (``TOP``) y la del
        bloque derecho (``RIGHT``, de tamaño dinámico), y ``context.region.width`` ya no
        incluye el bloque derecho (medido el 07/10/2026 a 1920 px: 1583 + 337 px con escala
        efectiva 1,0 y 1500 + 420 con 1,25). El automático no lo resta otra vez: con 1,25,
        C en los dos idiomas (antes, D); con 1,0, B en español (antes, C) y A en inglés.
        Sin la región derecha, la anchura es la de la ventana y se resta la constante."""
        Level = self.width.Level
        tools, help_ = self.width.TOOLS_MENU, self.width.HELP_MENU
        cases = (("es", 1.0, 1583, 337, Level.B), ("en", 1.0, 1583, 337, Level.A),
                 ("es", 1.25, 1500, 420, Level.C), ("en", 1.25, 1500, 420, Level.C))
        for language, scale, left, right, expected in cases:
            with self.subTest(language=language, scale=scale):
                self.preferences().language = language.upper()
                self.i18n.set_language(language)
                ctx = regions_context(left, right)
                with mock.patch.object(self.compat, "ui_scale", return_value=scale):
                    self.assertIs(self.topbar.current_level(ctx), expected)
                    layout = draw(bpy.types.TOPBAR_HT_upper_bar, ctx, method="draw_left")
                self.assertEqual(self.compat.topbar_right_block_px(ctx), 0.0)
                menus = self.menus(layout)
                self.assertEqual(len(menus), 13)
                icons = [item.target for item in menus if not item.text]
                self.assertEqual(icons, [tools, help_] if expected is Level.C else [])
        self.assertIsNone(self.compat.topbar_right_block_px(context(1920)))

    def test_forced_level(self) -> None:
        """RF-003-10: «Texto» fija B aunque no quepa (800 px) e «Iconos», D aunque sobre
        sitio (2400 px)."""
        self.preferences().topbar_titles = "TEXT"
        menus = self.menus(self.draw_bar(800))
        self.assertEqual(len(menus), 13)
        self.assertTrue(all(item.text and item.icon == "NONE" for item in menus))
        self.preferences().topbar_titles = "ICONS"
        menus = self.menus(self.draw_bar(2400))
        self.assertEqual(len(menus), 13)
        self.assertTrue(all(not item.text for item in menus))


if __name__ == "__main__":
    unittest.main()
