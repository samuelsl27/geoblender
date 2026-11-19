# SPDX-License-Identifier: GPL-3.0-or-later
"""La ventana de verificar con la base de los acopios (spec 016, T36; HU-016-2; RF-012-30, RF-012-31, RF-016-09; DIFF-012 §2, D-a; plan 016
§5.5; comprobación manual M7), **sin proyecto** (lo que se hace con ella, con el proyecto de los acopios y las órdenes reales, está en
``milestone_verify_stockpile_ui.py``: P-13).

La ventana de «Verificar un diseño por recinto…» (``bl.ui.constraint_panels``, ``bl.ops.res``) dice **qué base de acopios usa la
verificación** (la detección, con su material) **o por qué no** (obsoleta, o hecha sobre otra partida, con la causa), en el diálogo antes de
verificar y, después, en la ventana de la verificación y en lo que informa la orden; **sin acopios no dice nada nuevo**. El texto es el de
``reserves.compliance_store`` (``StockpileBase.text`` y ``SkippedDetection.text``): la selección la hace ``select_bases``, aquí sustituida
por una hecha a mano.

- RF-012-30 (a): las bases que se usan se nombran con su detección, su nombre y su material, en los dos idiomas y sin alerta.
- RF-012-31 (b): la detección obsoleta y la hecha sobre otra partida no se usan y se avisan en alerta con su causa y la superficie de partida.
- RF-012-30, RF-012-31 (c): sin acopios, nada: ni líneas ni nada de más en la ventana.
- RF-012-30 (d): el diálogo lee la selección **una vez por partida** (no al redibujar) y un fallo de lectura no la tumba.
- RF-012-30, RF-012-31, D-a (e, f): la ventana de la verificación nombra, de lo guardado, la base usada y la detección que no se usó, antes
  de los avisos de lo demás, y sin acopios queda como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import contextlib
import importlib
import sqlite3
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, draw

PANEL = "GEOBLENDER_PT_res_verification"
VERSION = "0123456789abcdef0123456789abcdef"
USED = "Base de acopios: detección STK-001 «Acopios» (mineral)"
USED_EN = "Stockpile base: detection STK-001 «Acopios» (mineral)"
STALE = ("La detección de acopios STK-002 «Montones» no se usa como base: está obsoleta (cambió el parámetro «margen»); recalcúlela y "
         "verifique otra vez. Todo el corte cuenta como corte de terreno.")
OTHER = ("La detección de acopios STK-003 «Otros» no se usa como base: se hizo sobre «Levantamiento», no sobre la superficie de partida "
         "«Retirada». Todo el corte cuenta como corte de terreno.")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.panels = _module("bl.ui.constraint_panels")
        cls.cstore = _module("reserves.compliance_store")
        cls.surfaces = _module("reserves.surfaces")
        cls.i18n = _module("core.i18n")

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.panels.forget_start_bases()
        self.addCleanup(self.panels.forget_start_bases)

    # --- Selecciones hechas a mano ------------------------------------------------------------

    def base(self, material: str = "mineral", detection: str = "STK-001", name: str = "Acopios") -> Any:
        return self.cstore.StockpileBase(detection, name, "project", material, self.surfaces.SurfaceRef(dataset="des_stb_stk_001_mineral"))

    def stale(self) -> Any:
        return self.cstore.SkippedDetection("STK-002", "Montones", "version", "stale", "Levantamiento", "cambió el parámetro «margen»")

    def other(self) -> Any:
        return self.cstore.SkippedDetection("STK-003", "Otros", "project", "other_surface", "Levantamiento")


class BaseLinesTest(_Case):
    """RF-012-30, RF-012-31: lo que dicen las líneas de la ventana."""

    def test_a_the_bases_that_are_used_are_named_with_their_detection_and_material(self) -> None:
        """RF-012-30, D-a: una línea por base (la detección, su nombre y su material), sin alerta, en el idioma de la interfaz."""
        selection = self.cstore.BaseSelection((self.base(), self.base("estéril")))
        lines = self.panels.base_lines(selection, "Levantamiento")
        self.assertEqual([line.text for line in lines], [USED, "Base de acopios: detección STK-001 «Acopios» (estéril)"])
        self.assertFalse(any(line.alert or line.place for line in lines))
        self.i18n.set_language("en")
        self.assertEqual(self.panels.base_lines(selection, "Levantamiento")[0].text, USED_EN)
        self.assertEqual(self.panels.base_lines(selection, "Levantamiento", "es")[0].text, USED, "o el idioma que se pida")

    def test_b_a_detection_that_is_not_used_says_why_in_an_alert(self) -> None:
        """RF-012-31, D-a: la obsoleta (con lo que cambió) y la hecha sobre otra superficie (con ella y la partida) se avisan en alerta,
        nombrando la detección y diciendo que todo el corte cuenta; la usada, sin alerta, va antes."""
        selection = self.cstore.BaseSelection((self.base(),), (self.stale(), self.other()))
        lines = self.panels.base_lines(selection, "Retirada")
        self.assertEqual([(line.text, line.alert) for line in lines], [(USED, False), (STALE, True), (OTHER, True)])
        self.i18n.set_language("en")
        english = [line.text for line in self.panels.base_lines(selection, "Retirada")]
        self.assertIn("is stale (cambió el parámetro «margen»)", english[1])
        self.assertIn("«Levantamiento», not on the start surface «Retirada»", english[2])
        for text in english[1:]:
            self.assertIn("All the cut counts as terrain cut", text)

    def test_c_without_stockpiles_it_says_nothing(self) -> None:
        """RF-012-30, RF-012-31: una selección vacía (sin acopios detectados) no da ninguna línea."""
        self.assertEqual(self.panels.base_lines(self.cstore.BaseSelection(), "Retirada"), [])
        self.assertEqual(self.panels.stored_base_lines(SimpleNamespace(bases=(), skipped=())), [])

    def test_d_the_stored_texts_become_lines_in_the_same_order_and_alert(self) -> None:
        """RF-012-30, RF-012-31: lo que guardó la tabla (``StoredVerification.bases`` y ``.skipped``) se enseña tal cual: las bases, sin
        alerta, y lo que no se usó, en alerta."""
        lines = self.panels.stored_base_lines(SimpleNamespace(bases=(USED,), skipped=(STALE, OTHER)))
        self.assertEqual([(line.text, line.alert) for line in lines], [(USED, False), (STALE, True), (OTHER, True)])


class DialogReadsOncePerStartTest(_Case):
    """RF-012-30: el diálogo no lee del proyecto al redibujar."""

    def lines(self, project: Any, start: Any, **options: Any) -> Any:
        return self.panels.start_base_lines(project, options.pop("version", VERSION), start)

    def test_a_the_selection_is_read_once_per_start_and_forgotten_with_the_dialog(self) -> None:
        """RF-012-30: ``select_bases`` se llama una vez (con el proyecto, la versión y la partida) por más que se redibuje; otra partida, otra
        lectura; y al abrir el diálogo otra vez (``forget_start_bases``) se lee de nuevo."""
        selection = self.cstore.BaseSelection((self.base(),), (self.stale(),))
        project, survey, final = object(), self.surfaces.SurfaceRef(dataset="gis_dtm_a", label="A"), self.surfaces.SurfaceRef(dataset="gis_dtm_b", label="B")
        with mock.patch.object(self.cstore, "select_bases", return_value=selection) as read:
            first = self.lines(project, survey)
            for _ in range(5):
                self.assertEqual(self.lines(project, survey), first)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(read.call_args.args, (project, VERSION, survey))
            self.lines(project, final)
            self.lines(project, final)
            self.assertEqual(read.call_count, 2, "otra partida, otra lectura")
            self.panels.forget_start_bases()
            self.lines(project, final)
            self.assertEqual(read.call_count, 3, "con el diálogo abierto otra vez, se lee de nuevo")
        self.assertEqual([(line.text.startswith("Base de acopios"), line.alert) for line in first], [(True, False), (False, True)])
        self.assertIn("STK-002 «Montones» no se usa como base: está obsoleta", first[1].text)

    def test_b_another_language_is_another_reading(self) -> None:
        """RF-012-30: cambiar el idioma de la interfaz con el diálogo abierto vuelve a escribir las líneas en él."""
        selection = self.cstore.BaseSelection((self.base(),))
        project, start = object(), self.surfaces.SurfaceRef(dataset="gis_dtm_a", label="A")
        with mock.patch.object(self.cstore, "select_bases", return_value=selection):
            self.assertEqual(self.lines(project, start)[0].text, USED)
            self.i18n.set_language("en")
            self.assertEqual(self.lines(project, start)[0].text, USED_EN)

    def test_c_no_project_or_a_failed_reading_gives_no_lines_and_does_not_raise(self) -> None:
        """RF-012-30: sin proyecto, sin versión o con un fallo al leer (SQLite, un valor), el diálogo no dice nada y sigue (verificar lo dirá
        con su error); el fallo no se guarda como lectura buena."""
        start = self.surfaces.SurfaceRef(dataset="gis_dtm_a", label="A")
        with mock.patch.object(self.cstore, "select_bases") as read:
            self.assertEqual(self.lines(None, start), [])
            self.assertEqual(self.lines(object(), start, version=""), [])
            read.assert_not_called()
        for error in (sqlite3.OperationalError("database is locked"), ValueError("lo que sea"), OSError("sin disco")):
            with self.subTest(error=type(error).__name__), mock.patch.object(self.cstore, "select_bases", side_effect=error):
                self.panels.forget_start_bases()
                self.assertEqual(self.lines(object(), start), [])
        with mock.patch.object(self.cstore, "select_bases", return_value=self.cstore.BaseSelection((self.base(),))):
            self.assertEqual([line.text for line in self.lines(object(), start)], [USED])

    def test_d_the_lines_are_drawn_wrapped_to_the_dialog(self) -> None:
        """RF-012-31: las líneas largas (la causa de una detección obsoleta) se parten al ancho del diálogo y las de alerta van con su icono;
        sin líneas no se dibuja nada."""
        drawn = FakeLayout()
        self.panels.draw_base_lines(drawn, [], 520)
        self.assertEqual(drawn.items, [])
        lines = self.panels.base_lines(self.cstore.BaseSelection((self.base(),), (self.stale(),)), "Retirada")
        self.panels.draw_base_lines(drawn, lines, 520)
        labels = drawn.of_kind("label")
        self.assertEqual(labels[0].text, USED)
        self.assertEqual(labels[0].icon, "NONE")
        alert = [item for item in labels if item.alert]
        self.assertGreater(len(alert), 1, "la causa no cabe en una línea de un diálogo de 520 px")
        self.assertEqual(alert[0].icon, "ERROR")
        self.assertEqual(" ".join(item.text for item in alert), STALE)


class VerificationWindowTest(_Case):
    """RF-012-30, RF-012-31, D-a: la ventana de la verificación, de lo guardado (sin proyecto: se sustituye lo que lee)."""

    def found(self, **options: Any) -> Any:
        values: dict[str, Any] = {"operation_uid": "op", "name": "Prueba", "stale": False, "surfaces": ("Retirada",), "zones": (), "groups": (),
                                  "pending": (), "notices": (), "grids": {}, **options}
        return self.cstore.StoredVerification(**values)

    def fill(self, found: Any) -> list[Any]:
        project = SimpleNamespace(read=contextlib.nullcontext)
        with mock.patch.object(self.cstore, "read_verification", return_value=found), \
                mock.patch.object(self.cstore, "verification_names", return_value=(found.name,)), \
                mock.patch.object(self.panels, "shown_names", return_value={}):
            self.panels.fill_verification(project, VERSION, found.name)
        return list(self.panels.view().verify_notes)

    def texts(self) -> list[str]:
        return draw(getattr(bpy.types, PANEL), bpy.context).texts()

    def test_e_the_window_names_the_base_that_was_used_and_the_detection_that_was_not(self) -> None:
        """RF-012-30, RF-012-31, D-a: la ventana de la verificación enseña, antes de los avisos de lo demás, la base que se usó (sin alerta) y
        la detección que no (en alerta, con su causa), tal como las guardó la tabla; el título y la tabla de cada final siguen."""
        notes = self.fill(self.found(bases=(USED,), skipped=(STALE, OTHER), pending=("Sector 1",), notices=((1, "Aviso de la final"),)))
        self.assertEqual([(note.text, note.alert) for note in notes],
                         [(USED, False), (STALE, True), (OTHER, True), ("Búsqueda de elementos intocables pendiente en: Sector 1", True),
                          ("Retirada: Aviso de la final", False)])
        shown = self.texts()
        self.assertIn("Verificación «Prueba» en " + VERSION[:8], shown)
        self.assertIn(USED, shown)
        joined = " ".join(shown)
        for wanted in ("STK-002 «Montones» no se usa como base", "está obsoleta (cambió el parámetro «margen»)", "STK-003 «Otros»",
                       "no sobre la superficie de partida «Retirada»"):
            self.assertIn(wanted, joined)
        self.assertLess(shown.index(USED), shown.index("«Retirada»: cumple"), "antes de la tabla de las finales")

    def test_f_without_stockpiles_the_window_has_nothing_new(self) -> None:
        """RF-012-30, RF-012-31: una verificación sin acopios (sin bases ni avisos guardados) no añade ninguna nota ni línea: lo de la 012."""
        notes = self.fill(self.found(pending=("Sector 1",)))
        self.assertEqual([note.text for note in notes], ["Búsqueda de elementos intocables pendiente en: Sector 1"])
        joined = " ".join(self.texts())
        self.assertNotIn("acopios", joined)
        self.assertNotIn("Base de", joined)
        self.assertEqual(self.fill(self.found()), [])


if __name__ == "__main__":
    unittest.main()
