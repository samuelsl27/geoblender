# SPDX-License-Identifier: GPL-3.0-or-later
"""Barra de estado minera (spec 003, T27; RF-003-28; plan 003 §5.3, contrato 5, y §5.4,
14; AR §6).

- RF-003-28: en modo Geoblender, con un proyecto (GeoOrigin 736 500, 4 435 900, 0) y el
  cursor 3D en (12,34; −28,98; 212,4) locales, la barra de estado muestra el proyecto, su
  EPSG y «Cursor: X 736 512,34  Y 4 435 871,02  Z 212,40» (absolutas en float64, formato
  español); en inglés, ``X 736512.34  Y 4435871.02  Z 212.40``; sin proyecto, «Sin
  proyecto». También el encaje (prioridad 3) y, si hay recorte en la Vista 3D de destino,
  «Recorte: banda» (prioridad 2).
- RF-003-28 (AR §6): si no caben, se ocultan primero los de prioridad 3 y después los de
  prioridad 2; los de prioridad 1, nunca. A 1920 px se ven todos; a 800 px, el encaje no.
- Contrato 5: en modo Blender solo se dibujan los campos registrados para los dos modos (un
  campo sintético; sin ninguno, nada). Con la preferencia «Barra de estado minera»
  apagada, tampoco los de Geoblender.
- Plan §5.4, 14: un único ``append`` a ``STATUSBAR_HT_header``; la suscripción de
  ``msgbus`` al cursor 3D se renueva en ``load_post`` (una sola) y desregistrar la retira.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout

THIN = " "  # espacio fino sin ruptura
XYZ_ES = f"X 736{THIN}512,34  Y 4{THIN}435{THIN}871,02  Z 212,40"
XYZ_EN = "X 736512.34  Y 4435871.02  Z 212.40"
SYNTHETIC = "gbtest_dos_modos"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class StatusbarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.statusbar = _module("bl.ui.statusbar")
        cls.georef = _module("bl.scene.georef")
        cls.i18n = _module("core.i18n")
        cls.views = _module("bl.ui.views")
        cls.prefs = _module("bl.ui.commands").preferences()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def setUp(self) -> None:
        bpy.context.scene.cursor.location = (12.34, -28.98, 212.4)
        bpy.context.scene.tool_settings.use_snap = False
        self.addCleanup(self.statusbar.unregister_field, SYNTHETIC)

    @contextmanager
    def project(self) -> Iterator[None]:
        fake = self.georef.SceneGeoref("uid", "Cantera sintética", 25830, 0,
                                       (736500, 4435900, 0))
        with mock.patch.object(self.georef, "project_georeference", return_value=fake):
            yield

    def ctx(self, *, geoblender: bool = True, width: float = 1920.0) -> SimpleNamespace:
        window = bpy.context.window_manager.windows[0]
        return SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=geoblender),
                               region=SimpleNamespace(width=width), scene=bpy.context.scene,
                               window=window, screen=window.screen, area=None,
                               preferences=bpy.context.preferences)

    def texts(self, ctx: SimpleNamespace) -> list[str]:
        layout = FakeLayout()
        self.statusbar.draw_statusbar(SimpleNamespace(layout=layout), ctx)
        return layout.texts()

    def synthetic(self, *, width: float = 60.0) -> None:
        def draw(layout: Any, _context: Any) -> None:
            layout.label(text="⟳ 1 · 42 %", translate=False)

        self.statusbar.register_field(SYNTHETIC, priority=1, draw=draw,
                                      width_px=lambda _context: width,
                                      modes=frozenset({"GEOBLENDER", "BLENDER"}))

    def test_cursor_in_absolute_coordinates(self) -> None:
        """RF-003-28: proyecto, EPSG y el cursor 3D en absolutas, en español y en inglés."""
        with self.project():
            texts = self.texts(self.ctx())
            self.assertEqual(texts[:4], ["Cantera sintética", "EPSG:25830", "Cursor:", XYZ_ES])
            self.i18n.set_language("en")
            try:
                self.assertIn(XYZ_EN, self.texts(self.ctx()))
            finally:
                self.i18n.set_language("es")

    def test_without_project(self) -> None:
        """RF-003-28: sin proyecto, «Sin proyecto» y ni EPSG ni coordenadas."""
        texts = self.texts(self.ctx())
        self.assertEqual(texts[0], "Sin proyecto")
        self.assertFalse([text for text in texts if "EPSG" in text or text == "Cursor:"])

    def test_snap_and_clipping(self) -> None:
        """AR §6: el encaje (su elemento) y, con recorte en la vista, su modo."""
        tool_settings = bpy.context.scene.tool_settings
        self.assertIn("Encaje: desactivado", self.texts(self.ctx()))
        tool_settings.use_snap = True
        tool_settings.snap_elements = {"VERTEX"}
        self.assertIn("Encaje: vértice", self.texts(self.ctx()))
        self.assertFalse([text for text in self.texts(self.ctx()) if text.startswith("Recorte")])
        with mock.patch.object(self.views, "clip_mode", return_value="BAND"):
            self.assertIn("Recorte: banda", self.texts(self.ctx()))

    def test_hidden_by_priority(self) -> None:
        """RF-003-28: a 1920 px se ve todo; a 800 px, primero se oculta la prioridad 3; y
        con poco sitio, después la 2; la 1, nunca."""
        with self.project(), mock.patch.object(self.views, "clip_mode", return_value="BAND"):
            wide = self.texts(self.ctx(width=1920.0))
            self.assertTrue([text for text in wide if text.startswith("Encaje")])
            self.assertTrue([text for text in wide if text.startswith("Recorte")])
            narrow = self.texts(self.ctx(width=800.0))
            self.assertFalse([text for text in narrow if text.startswith("Encaje")])
            self.assertIn(XYZ_ES, narrow)
            tiny = self.texts(self.ctx(width=300.0))
            self.assertFalse([text for text in tiny if text.startswith(("Encaje", "Recorte"))])
            self.assertEqual(tiny[:4], ["Cantera sintética", "EPSG:25830", "Cursor:", XYZ_ES])
        fit = self.statusbar.fit
        widths = [(1, 100.0), (3, 50.0), (2, 80.0), (3, 40.0)]
        self.assertEqual(fit(widths, 400.0), [0, 1, 2, 3])
        self.assertEqual(fit(widths, 200.0), [0, 2])
        self.assertEqual(fit(widths, 120.0), [0])
        self.assertEqual(fit(widths, 10.0), [0])

    def test_blender_mode(self) -> None:
        """Contrato 5: en modo Blender, nada; con un campo de los dos modos, solo ese."""
        with self.project():
            self.assertEqual(self.texts(self.ctx(geoblender=False)), [])
            self.synthetic()
            self.assertEqual(self.texts(self.ctx(geoblender=False)), ["⟳ 1 · 42 %"])
            self.assertIn("⟳ 1 · 42 %", self.texts(self.ctx()))

    def test_preference_off(self) -> None:
        """RF-003-28: con la preferencia apagada, nada de lo de Geoblender."""
        self.prefs.show_mining_statusbar = False
        self.addCleanup(setattr, self.prefs, "show_mining_statusbar", True)
        with self.project():
            self.assertEqual(self.texts(self.ctx()), [])

    def test_append_and_subscription(self) -> None:
        """Plan §5.4, 14: un único ``append``; la suscripción al cursor, una sola también
        tras ``load_post``; al quitar la barra, sin suscripción ni ``append``."""
        functions = bpy.types.STATUSBAR_HT_header.draw._draw_funcs
        self.assertEqual(functions.count(self.statusbar.draw_statusbar), 1)
        self.assertTrue(self.statusbar.is_subscribed())
        self.statusbar.on_load_post()
        self.assertTrue(self.statusbar.is_subscribed())
        self.statusbar.uninstall()
        try:
            self.assertFalse(self.statusbar.is_subscribed())
            self.assertNotIn(self.statusbar.draw_statusbar,
                             getattr(bpy.types.STATUSBAR_HT_header.draw, "_draw_funcs", ()))
        finally:
            self.statusbar.install()
        self.statusbar.on_cursor_moved()  # sin ventanas con interfaz, no hace nada


if __name__ == "__main__":
    unittest.main()
