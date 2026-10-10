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

Spec 008, T69 (RF-008-16, RF-008-28, RF-008-58; RF-004-06; RF-003-28; M6 de la 008): con los
campos de la 003, «⚠ 1 entrada», «! 3 obsoletos», «Comprobando el proyecto… 40 %» y un
trabajo de la 004 a la vez, en una barra de 1920 px con escalas efectivas 1,0, 1,25 y 1,5 y
en los dos modos, lo dibujado cabe en lo que deja Blender (la región menos
``STATUSBAR_RESERVED_PX``): se ocultan la prioridad 3 y la 2 y, si aún no cabe, se pliegan los
campos de prioridad 1 que tienen forma plegada, de derecha a izquierda y solo los que hace
falta; el botón de cancelar del trabajo y el de la comprobación siguen a la vista. Lo que
ocupa lo dibujado se mide con el modelo de Blender 5.2.1 medido en las capturas de M6
(:func:`drawn_px`), y cada campo calcula lo mismo que ocupa lo que dibuja, plegado o no.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import blf
import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, Item

THIN = " "  # espacio fino sin ruptura
XYZ_ES = f"X 736{THIN}512,34  Y 4{THIN}435{THIN}871,02  Z 212,40"
XYZ_EN = "X 736512.34  Y 4435871.02  Z 212.40"
SYNTHETIC = "gbtest_dos_modos"

# T69: la barra de estado llena (M6 de la 008).
REGION_PX = 1920.0
SCALES = (1.0, 1.25, 1.5)
RESERVED_PX = 480.0  # bl.compat.STATUSBAR_RESERVED_PX (spec 003)
CANCEL_JOB = "geoblender.jobs_cancel"
CANCEL_CHECKS = "geoblender.core_cancel_checks"
JOB_NAME = "Autodiagnóstico: suma de 10 s"
JOB_MESSAGE = "Trozo 16 de 50"
UNDO_TEXT = "Ctrl+Z no deshace la operación «gis.resample»: sigue en el proyecto"
FULL_008 = ("⚠ 1 entrada", "! 3 obsoletos", "Comprobando el proyecto… 40 %")
FOLDED_008 = ("⚠ 1", "! 3", "40 %")
# Lo que ocupa a escala 1,0 cada elemento de la barra de estado de Blender 5.2.1, además del
# ancho blf de su texto (11 pt), medido en las capturas de M6 (10/10/2026; 1920 px, escalas
# efectivas 1,0 y 1,5): etiqueta +5, etiqueta con icono +35, botón de una orden con texto +30,
# botón solo con icono 20, desplegable con texto +25, separador de línea entre campos con su
# espacio 22; una fila de ancho fijo, sus unidades de 20 px; el separador dentro de una fila
# alineada, 6 (0,3 unidades, del código de Blender).
LABEL_PAD = 5.0
ICON_LABEL_PAD = 35.0
BUTTON_PAD = 30.0
ICON_BUTTON = 20.0
POPOVER_PAD = 25.0
FIELD_SEPARATOR = 22.0
SPACER = 6.0
UNIT = 20.0


def text_width(text: str) -> float:
    """El ancho blf de ``text`` con la fuente de la interfaz a 11 pt (escala 1,0)."""
    blf.size(0, 11)
    return float(blf.dimensions(0, text)[0])


def drawn_px(items: Sequence[Item]) -> float:
    """Lo que ocupan a escala 1,0 los elementos dibujados en la barra de estado, con el
    modelo medido de Blender 5.2.1 (T69)."""
    total = 0.0
    for item in items:
        if item.units_x:  # una fila de ancho fijo (la barra de avance, un aviso cortado)
            total += item.units_x * UNIT
        elif item.kind == "separator":
            total += FIELD_SEPARATOR if item.options.get("type") == "LINE" else SPACER
        elif item.kind == "label":
            pad = LABEL_PAD if item.icon == "NONE" else ICON_LABEL_PAD
            total += text_width(item.text) + pad if item.text else ICON_BUTTON
        elif item.kind == "operator":
            total += text_width(item.text) + BUTTON_PAD if item.text else ICON_BUTTON
        elif item.kind == "popover":
            total += text_width(item.text) + POPOVER_PAD
        else:
            raise AssertionError(f"sin medida para «{item.kind}» ({item.text!r})")
    return total


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
        cls.compat = _module("bl.compat")
        cls.provenance = _module("bl.ui.provenance")
        cls.provenance_ops = _module("bl.ops.core_provenance")
        cls.jobs = _module("bl.ui.jobs")
        cls.stale = _module("core.provenance.stale")

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

    @contextmanager
    def crowded(self, *, undo: bool = False, notice: bool = False) -> Iterator[None]:
        """T69: la barra de M6: el proyecto de la demostración («M2_limite», GeoOrigin
        700 000, 4 400 000, 0, con el cursor 3D en el origen), 1 entrada cambiada sin decidir,
        3 obsoletos, la comprobación de apertura al 40 % y dos trabajos activos, el más antiguo
        al 40 % con su último mensaje; con ``undo``, el aviso de Ctrl+Z, y con ``notice``, el
        de un trabajo terminado."""
        fake = self.georef.SceneGeoref("uid", "M2_limite", 25830, 0, (700000, 4400000, 0))
        counts = self.stale.Counts(stale=3, figures=0, review=0, inputs_changed=1)
        session = SimpleNamespace(percent=40, status_text=lambda: FULL_008[2])
        current = SimpleNamespace(name=JOB_NAME, state="running", message=JOB_MESSAGE)
        finished = SimpleNamespace(name=JOB_NAME, state="succeeded", duration_s=10.0,
                                   error=None)
        view = SimpleNamespace(visible=True, active=2, current=current, percent=40,
                               notice=finished if notice else None)
        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
        with mock.patch.object(self.georef, "project_georeference", return_value=fake), \
                mock.patch.object(self.provenance._STATE, "counts", counts), \
                mock.patch.object(self.provenance_ops, "SESSION", session), \
                mock.patch.object(self.provenance, "undo_notice",
                                  return_value=UNDO_TEXT if undo else ""), \
                mock.patch.object(self.jobs, "current_view", return_value=view):
            yield

    def draw(self, ctx: SimpleNamespace) -> FakeLayout:
        layout = FakeLayout()
        self.statusbar.draw_statusbar(SimpleNamespace(layout=layout), ctx)
        return layout

    def check_folding(self, ctx: SimpleNamespace, layout: FakeLayout, available: float) -> None:
        """T69: si algo se pliega, es después de ocultar las prioridades 3 y 2, de derecha a
        izquierda entre los que se pueden plegar y solo lo que hace falta (sin plegar el
        primero, lo dibujado no cabría)."""
        arranged = self.statusbar.arrange(ctx)
        flags = [folded for _field, folded in arranged]
        if not any(flags):
            return
        self.assertEqual({field.priority for field, _folded in arranged}, {1})
        first = flags.index(True)
        foldable = [index for index, (field, _folded) in enumerate(arranged)
                    if field.folded_draw is not None]
        self.assertEqual([index for index in foldable if index >= first],
                         [index for index, folded in enumerate(flags) if folded])
        field = arranged[first][0]
        full, narrow = FakeLayout(), FakeLayout()
        field.draw(full, ctx)
        field.folded_draw(narrow, ctx)
        unfolded = drawn_px(layout.items) - drawn_px(narrow.items) + drawn_px(full.items)
        self.assertGreater(unfolded, available, field.key)

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
        self.assertEqual(fit(widths, 210.0), [0, 2])
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
            self.jobs.install()  # los campos de la 004 y de la 008, como «Reparar la interfaz»
            self.provenance.install()
        self.statusbar.on_cursor_moved()  # sin ventanas con interfaz, no hace nada

    def test_crowded_bar_fits_folding_by_priority(self) -> None:
        """T69 (RF-008-16, RF-008-28, RF-008-58; RF-004-06; RF-003-28; M6): con todo a la
        vez, a 1920 px con escalas efectivas 1,0, 1,25 y 1,5 y en los dos modos, lo dibujado
        cabe en la región menos lo que reserva Blender; se oculta primero el encaje (prioridad
        3) y después se pliegan los campos de la 008 y el del trabajo, de derecha a izquierda y
        solo los que hace falta; los de la 003 no se pliegan; el botón de cancelar del trabajo
        y el de la comprobación siguen a la vista. A 1,0 nada se pliega; a 1,5, en modo
        Geoblender, «⚠ 1», «! 3», «40 %» y el trabajo sin su mensaje."""
        xyz = f"X 700{THIN}000,00  Y 4{THIN}400{THIN}000,00  Z 0,00"
        seen: dict[tuple[bool, float], list[str]] = {}
        with self.crowded():
            for geoblender in (True, False):
                for scale in SCALES:
                    with self.subTest(geoblender=geoblender, scale=scale), \
                            mock.patch.object(self.compat, "ui_scale", return_value=scale):
                        ctx = self.ctx(geoblender=geoblender, width=REGION_PX)
                        layout = self.draw(ctx)
                        available = REGION_PX / scale - RESERVED_PX
                        self.assertLessEqual(drawn_px(layout.items), available)
                        targets = [item.target for item in layout.of_kind("operator")]
                        self.assertIn(CANCEL_JOB, targets)
                        self.assertIn(CANCEL_CHECKS, targets)
                        self.check_folding(ctx, layout, available)
                        seen[geoblender, scale] = layout.texts()
        for geoblender in (True, False):
            for text in (*FULL_008, JOB_MESSAGE):
                self.assertIn(text, seen[geoblender, 1.0])
        self.assertFalse([text for text in seen[True, 1.25] if text.startswith("Encaje")])
        crowded = seen[True, 1.5]
        self.assertEqual(crowded[:4], ["M2_limite", "EPSG:25830", "Cursor:", xyz])
        for text in FOLDED_008:
            self.assertIn(text, crowded)
        for text in (*FULL_008, JOB_MESSAGE):
            self.assertNotIn(text, crowded)
        fold = self.statusbar.fold  # (ancho, plegado); 22 px entre cada dos
        widths = [(100.0, 50.0), (100.0, None), (60.0, 70.0), (100.0, 40.0)]
        self.assertEqual(fold(widths, 430.0), [False, False, False, False])
        self.assertEqual(fold(widths, 380.0), [False, False, False, True])
        self.assertEqual(fold(widths, 320.0), [True, False, False, True])
        self.assertEqual(fold(widths, 100.0), [True, False, False, True])

    def test_each_field_measures_what_it_draws(self) -> None:
        """T69: las medidas de Blender 5.2.1 del modelo de anchura (``bl.compat``) son las de
        M6, y cada campo de la barra de estado (los de la 003, los de la 008 con el aviso de
        Ctrl+Z y el del trabajo con su aviso de terminado) calcula lo que ocupa lo que dibuja,
        con sus botones y sus iconos, plegado o no; los de la 008 y el del trabajo se pueden
        plegar."""
        foldable = {"provenance_inputs", "provenance_stale", "provenance_checking",
                    "provenance_undo", "jobs"}
        checked: set[str] = set()
        with self.crowded(undo=True, notice=True):
            ctx = self.ctx(width=REGION_PX)
            for field in self.statusbar.fields():
                forms = [(field.draw, field.width_px)]
                if getattr(field, "folded_draw", None) is not None:
                    forms.append((field.folded_draw, field.folded_width_px))
                for draw, width in forms:
                    computed = width(ctx)
                    if computed <= 0:
                        continue  # nada que mostrar (el recorte)
                    layout = FakeLayout()
                    draw(layout, ctx)
                    with self.subTest(field=field.key, folded=draw is not field.draw):
                        self.assertAlmostEqual(computed, drawn_px(layout.items), delta=0.5)
                    checked.add(field.key)
            self.assertEqual({field.key for field in self.statusbar.fields()
                              if getattr(field, "folded_draw", None) is not None}, foldable)
        self.assertLessEqual({"project", "epsg", "cursor", "snap", *foldable}, checked)
        widths = self.compat.statusbar_widths()
        self.assertEqual((widths.label, widths.icon_label, widths.button, widths.icon_button,
                          widths.popover, widths.separator, widths.spacer),
                         (LABEL_PAD, ICON_LABEL_PAD, BUTTON_PAD, ICON_BUTTON, POPOVER_PAD,
                          FIELD_SEPARATOR, SPACER))


if __name__ == "__main__":
    unittest.main()
