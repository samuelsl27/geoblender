# SPDX-License-Identifier: GPL-3.0-or-later
"""La ventana de verificar con la accesibilidad de las pistas (spec 017, T18b; HU-017-3; RF-012-21, RF-012-22, RF-012-24, RF-017-25; DIFF-012 de la 017, §2 y §4;
plan 017 §5.1, §5.4 A12, §5.7 P-9, §5.8 H-8; RNF-012-02 y 03; comprobación manual M7), **sin proyecto** (el caso con proyecto y la reproducción están en
``tests/unit/reserves/milestone_compliance_store_access.py`` y ``milestone_ref_compliance_access.py``: P-12).

La ventana de «Verificar un diseño por recinto…» (``bl.ui.constraint_panels``, ``bl.ops.res``) dice las **tres respuestas** de una zona «requiere acceso» —«Cumple», «No
cumple» y «Sin comprobar», **sin el «(R-40)»** de antes— y **de qué accesibilidad sale cada una** (la de cada final, con su código y su nombre) **o por qué no usa una**
(obsoleta, con lo que cambió, u hecha sobre otra superficie que la de cualquier final), en la ventana de la verificación y en lo que informa la orden; **sin accesibilidades
no dice nada nuevo**. El texto es el de ``reserves.compliance_store`` (``AccessUse.text`` y ``SkippedAccess.text``): la selección la hace ``select_access``, aquí
sustituida por una hecha a mano.

- RF-012-22, RF-012-24 (``AccessLinesTest``): las accesibilidades que se usan se nombran con su final, su código y su nombre, sin alerta; las que no, en alerta con su causa;
  en los dos idiomas; sin accesibilidades, ninguna línea.
- RF-012-22, RF-012-24 (``AccessWindowTest``): la ventana de la verificación las nombra, de lo guardado, **antes de los avisos de lo demás y de la tabla de las finales**, con
  lo que anotaron los ajustes (el idioma de la interfaz) o, si no lo dicen, con lo que guardó la tabla; sin accesibilidades queda como estaba.
- RF-012-22, H-8 (``ThreeAnswersTest``): la tabla por recinto dice «Cumple», «No cumple» y «Sin comprobar» (y «Complies», «Does not comply» y «Not checked»), la que no cumple
  en alerta y el resumen de la final con ella; ningún texto de la ventana, en ningún idioma, lleva «R-40».
- RF-012-24 (``OperatorTest``): la orden elige la accesibilidad **una vez** y la usa para las entradas de la puerta de la 008 y para verificar; al terminar informa de las que
  usó y de las que no (en alerta), y sin ellas no dice nada nuevo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import contextlib
import importlib
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw, operator_self

PANEL = "GEOBLENDER_PT_res_verification"
VERSION = "0123456789abcdef0123456789abcdef"
USED = "Accesibilidad de «Pozo 1»: ACC-001 «Accesibilidad de la cantera»"
USED_EN = "Accessibility of «Pozo 1»: ACC-001 «Accesibilidad de la cantera»"
USED_2 = "Accesibilidad de «Pozo 2»: ACC-002 «Accesibilidad del tajo»"
STALE = ("La accesibilidad ACC-003 «Del banco» no se usa para «Pozo 3»: está obsoleta (cambió el parámetro «pendiente máxima»); recalcúlela y verifique otra vez. "
         "Las zonas «requiere acceso» quedan sin comprobar.")
OTHER = ("La accesibilidad ACC-004 «Otra» no se usa: se hizo sobre «Levantamiento», que no es ninguna de las superficies finales de la verificación.")
WITH, WITHOUT, BLIND = "zona_con_acceso", "zona_sin_acceso", "zona_sin_dato"


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

    # --- Selecciones hechas a mano ------------------------------------------------------------

    def used(self, final: int = 1, code: str = "ACC-001", name: str = "Accesibilidad de la cantera", shown: str = "Pozo 1") -> Any:
        return self.cstore.AccessUse(final, code, name, "gis_dtm_pozo", "des_acz_acc_001", shown)

    def stale(self) -> Any:
        return self.cstore.SkippedAccess("ACC-003", "Del banco", "stale", "gis_dtm_pozo_3", 3, "Pozo 3", "cambió el parámetro «pendiente máxima»")

    def other(self) -> Any:
        return self.cstore.SkippedAccess("ACC-004", "Otra", "other_surface", "Levantamiento")

    def selection(self) -> Any:
        return self.cstore.AccessSelection((self.used(), self.used(2, "ACC-002", "Accesibilidad del tajo", "Pozo 2")), (self.stale(), self.other()))

    # --- Una verificación guardada, a mano, y la ventana que la enseña ------------------------

    def found(self, **options: Any) -> Any:
        values: dict[str, Any] = {"operation_uid": "op", "name": "Prueba", "stale": False, "surfaces": ("Pozo 1",), "zones": (), "groups": (), "pending": (), "notices": (),
                                  "grids": {}, **options}
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

    def zone(self, code: str, verdict: str, *, cut: float = 0.0, fill: float = 0.0, moved: float = 0.0, final: int = 1) -> Any:
        """Lo que guarda la tabla de un recinto «requiere acceso» (``counts = access``): lo que se mueve en él y su veredicto."""
        return self.cstore.StoredZone(code, final, "access", cut, fill, moved, 0.0, cut + fill, None, None, verdict, None)


class AccessLinesTest(_Case):
    """RF-012-22, RF-012-24: lo que dicen las líneas de la ventana."""

    def test_a_the_accessibilities_that_are_used_are_named_with_their_final_code_and_name(self) -> None:
        """RF-012-22: una línea por accesibilidad usada (la de cada final, con su código y su nombre), sin alerta, en el idioma de la interfaz o en el pedido."""
        selection = self.cstore.AccessSelection((self.used(), self.used(2, "ACC-002", "Accesibilidad del tajo", "Pozo 2")))
        lines = self.panels.access_lines(selection)
        self.assertEqual([line.text for line in lines], [USED, USED_2])
        self.assertFalse(any(line.alert or line.place for line in lines))
        self.i18n.set_language("en")
        self.assertEqual(self.panels.access_lines(selection)[0].text, USED_EN)
        self.assertEqual(self.panels.access_lines(selection, "es")[0].text, USED, "o el idioma que se pida")

    def test_b_an_accessibility_that_is_not_used_says_why_in_an_alert(self) -> None:
        """RF-012-24: la obsoleta (con la final y lo que cambió) y la hecha sobre otra superficie (con ella) se avisan en alerta, nombrando la accesibilidad y diciendo que las
        zonas «requiere acceso» quedan sin comprobar; las usadas, sin alerta, van antes."""
        lines = self.panels.access_lines(self.selection())
        self.assertEqual([(line.text, line.alert) for line in lines], [(USED, False), (USED_2, False), (STALE, True), (OTHER, True)])
        self.i18n.set_language("en")
        english = [line.text for line in self.panels.access_lines(self.selection())]
        self.assertIn("is stale (cambió el parámetro «pendiente máxima»)", english[2])
        self.assertIn("The zones that require access are left unchecked", english[2])
        self.assertIn("«Levantamiento», which is none of the final surfaces of the check", english[3])

    def test_c_without_accessibilities_it_says_nothing(self) -> None:
        """RF-012-22: una selección vacía (sin accesibilidades al día) no da ninguna línea, ni la de una verificación guardada sin ellas."""
        self.assertEqual(self.panels.access_lines(self.cstore.AccessSelection()), [])
        self.assertEqual(self.panels.stored_access_lines(self.found()), [])

    def test_d_the_stored_texts_become_lines_in_the_same_order_and_alert(self) -> None:
        """RF-012-24: lo que guardó la tabla (``StoredVerification.access`` y ``.access_skipped``), si los ajustes de la operación no dicen la selección, se enseña tal cual:
        las usadas, sin alerta, y las que no, en alerta."""
        lines = self.panels.stored_access_lines(self.found(access=((1, USED), (2, USED_2)), access_skipped=((3, STALE), (0, OTHER))))
        self.assertEqual([(line.text, line.alert) for line in lines], [(USED, False), (USED_2, False), (STALE, True), (OTHER, True)])


class AccessWindowTest(_Case):
    """RF-012-22, RF-012-24: la ventana de la verificación, de lo guardado (sin proyecto: se sustituye lo que lee)."""

    def test_e_the_window_names_the_accessibilities_before_the_rest_of_the_notes_and_the_tables(self) -> None:
        """RF-012-22, RF-012-24, M7: la ventana enseña, antes de los avisos de lo demás, la accesibilidad de cada final (sin alerta) y las que no se usaron (en alerta, con su
        causa), tal como las guardó la tabla; el título y la tabla de cada final siguen."""
        notes = self.fill(self.found(access=((1, USED), (2, USED_2)), access_skipped=((3, STALE), (0, OTHER)), pending=("Sector 1",), notices=((1, "Aviso de la final"),)))
        self.assertEqual([(note.text, note.alert) for note in notes],
                         [(USED, False), (USED_2, False), (STALE, True), (OTHER, True), ("Búsqueda de elementos intocables pendiente en: Sector 1", True),
                          ("Pozo 1: Aviso de la final", False)])
        shown = self.texts()
        self.assertIn("Verificación «Prueba» en " + VERSION[:8], shown)
        for wanted in (USED, USED_2):
            self.assertIn(wanted, shown)
        joined = " ".join(shown)
        for wanted in ("ACC-003 «Del banco» no se usa para «Pozo 3»", "está obsoleta (cambió el parámetro «pendiente máxima»)", "ACC-004 «Otra»", "no es ninguna de las superficies finales"):
            self.assertIn(wanted, joined)
        self.assertLess(shown.index(USED), shown.index("«Pozo 1»: cumple"), "antes de la tabla de las finales")

    def test_f_the_window_writes_the_lines_in_the_language_of_the_interface(self) -> None:
        """RF-012-22, RF-012-24: con lo que anotaron los ajustes de la operación (la selección), las líneas se escriben en el idioma de la interfaz, con la misma alerta; la
        tabla las guardó en español."""
        found = self.found(access=((1, USED), (2, USED_2)), access_skipped=((3, STALE), (0, OTHER)), access_selection=self.selection())
        self.assertEqual([(note.text, note.alert) for note in self.fill(found)], [(USED, False), (USED_2, False), (STALE, True), (OTHER, True)])
        self.i18n.set_language("en")
        notes = [(note.text, note.alert) for note in self.fill(found)]
        self.assertEqual([alert for _text, alert in notes], [False, False, True, True])
        self.assertEqual(notes[0][0], USED_EN)
        self.assertEqual(notes[2][0], "The accessibility ACC-003 «Del banco» is not used for «Pozo 3»: it is stale (cambió el parámetro «pendiente máxima»); recompute it and "
                                      "verify again. The zones that require access are left unchecked.")
        self.assertIn(USED_EN, self.texts())
        self.assertNotIn(USED, self.texts())
        self.i18n.set_language("es")
        self.assertEqual([note.text for note in self.fill(found)], [USED, USED_2, STALE, OTHER], "y otra vez en español")

    def test_g_without_accessibilities_the_window_has_nothing_new(self) -> None:
        """RF-012-22, RF-012-24: una verificación sin accesibilidades (sin líneas ni selección guardadas) no añade ninguna nota ni línea: lo de la 012, con las bases de los
        acopios en su sitio si las hay."""
        notes = self.fill(self.found(pending=("Sector 1",)))
        self.assertEqual([note.text for note in notes], ["Búsqueda de elementos intocables pendiente en: Sector 1"])
        joined = " ".join(self.texts())
        self.assertNotIn("ccesibilidad", joined)
        self.assertNotIn("ccessibility", joined)
        self.assertEqual(self.fill(self.found()), [])
        base = "Base de acopios: detección STK-001 «Acopios» (mineral)"
        self.assertEqual([note.text for note in self.fill(self.found(bases=(base,), access=((1, USED),)))], [base, USED], "las bases, antes que las accesibilidades")


class ThreeAnswersTest(_Case):
    """RF-012-22, H-8: lo que dice la tabla de la ventana de cada zona «requiere acceso»."""

    def zones(self) -> tuple[Any, ...]:
        """Las tres respuestas en una final: la zona con acceso «cumple» (lo que se mueve en ella no cambia el veredicto), la sin acceso «no cumple» y la que no tiene
        accesibilidad «sin comprobar»."""
        return (self.zone(WITH, "complies", fill=288.0, moved=72.0), self.zone(WITHOUT, "fails", cut=12.0, moved=4.0), self.zone(BLIND, "unchecked", fill=8.0, moved=2.0))

    def rows(self, found: Any) -> dict[str, tuple[str, bool]]:
        self.fill(found)
        (final,) = self.panels.view().verify_finals
        return {row.code: (row.verdict, bool(row.alert)) for row in final.zones}

    def test_a_the_table_gives_the_three_answers_in_spanish(self) -> None:
        """RF-012-22, H-8, M7: «Cumple», «No cumple» (en alerta) y «Sin comprobar» **sin «(R-40)»**, y la que no cumple primero y el resumen de la final con ella."""
        found = self.found(zones=self.zones(), access=((1, USED),))
        self.assertEqual(self.rows(found), {WITH: ("Cumple", False), WITHOUT: ("No cumple", True), BLIND: ("Sin comprobar", False)})
        (final,) = self.panels.view().verify_finals
        self.assertEqual([row.code for row in final.zones], [WITHOUT, WITH, BLIND], "la que no cumple, primero; luego las que mueven algo")
        self.assertEqual((final.text, final.alert), (f"«Pozo 1»: no cumple ({WITHOUT})", True))
        self.assertEqual(self.panels._verdict_text("unchecked"), "Sin comprobar")

    def test_b_and_in_english(self) -> None:
        """RF-012-22, H-8: los mismos tres textos en el idioma de Blender (``msgid`` y traducción cambiados a la vez: el ``msgid`` es el inglés de la respuesta)."""
        self.i18n.set_language("en")
        self.assertEqual(self.rows(self.found(zones=self.zones())), {WITH: ("Complies", False), WITHOUT: ("Does not comply", True), BLIND: ("Not checked", False)})
        self.assertEqual(self.panels._verdict_text("unchecked"), "Not checked")

    def test_c_the_window_never_says_r_40(self) -> None:
        """H-8: ninguna línea de la ventana (la tabla, las notas ni el resumen), en ningún idioma, dice «R-40»: con las tres respuestas, sin ellas y con una accesibilidad."""
        for language in ("es", "en"):
            self.i18n.set_language(language)
            for options in ({}, {"access": ((1, USED),), "access_selection": self.selection()}):
                with self.subTest(idioma=language, accesibilidad=bool(options)):
                    self.fill(self.found(zones=self.zones(), **options))
                    shown = " ".join(self.texts())
                    self.assertNotIn("R-40", shown)
                    self.assertTrue(any(word in shown for word in ("Sin comprobar", "Not checked")))
        for verdict in ("complies", "fails", "not_judged", "unchecked", "otro"):
            for language in ("es", "en"):
                self.i18n.set_language(language)
                self.assertNotIn("R-40", self.panels._verdict_text(verdict))

    def test_d_without_an_accessibility_the_zone_is_not_checked_as_always(self) -> None:
        """RF-012-22: sin accesibilidad al día de esa final las zonas «requiere acceso» salen «sin comprobar», sin alerta, y la final «cumple» (lo de la 012, sin el «(R-40)»)."""
        self.assertEqual(self.rows(self.found(zones=(self.zone(WITH, "unchecked", fill=288.0, moved=72.0),))), {WITH: ("Sin comprobar", False)})
        (final,) = self.panels.view().verify_finals
        self.assertEqual((final.text, final.alert), ("«Pozo 1»: cumple", False))


class OperatorTest(_Case):
    """RF-012-24: lo que hace la orden real con la accesibilidad (sin proyecto: se sustituye lo que lee y lo que verifica)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.res_ops = _module("bl.ops.res")
        cls.operator = cls.res_ops.GEOBLENDER_OT_res_verify_constraints

    def finished(self, *, access: Any, selection: Any = None) -> list[tuple[set[str], str]]:
        """Lo que informa ``_finished`` de una verificación hecha con ``access`` (y ``selection``, la de los acopios)."""
        said: list[tuple[set[str], str]] = []
        result = SimpleNamespace(fails=(False,), finals=(SimpleNamespace(notices=()),), selection=selection or self.cstore.BaseSelection(), start_name="Retirada", access=access, pending_names=())
        fake = operator_self(self.operator, _project=object(), _name="Prueba", _version=VERSION, in_steps=False, _report=lambda level, text: said.append((level, text)))
        with mock.patch.object(self.res_ops.constraint_panels, "fill_verification", return_value=[]), mock.patch.object(self.res_ops.undo_watch, "record"), \
                mock.patch.object(self.res_ops.scene_versions, "active", return_value=None):
            self.operator._finished(fake, SimpleNamespace(window=None), SimpleNamespace(result=result))
        return said

    def test_a_the_command_tells_which_accessibilities_it_used_and_which_it_did_not(self) -> None:
        """RF-012-24, M7: al terminar, la orden dice las accesibilidades que usó (nivel de información) y las que no (de aviso, con su causa), tras el resumen de las finales;
        en el idioma de la interfaz."""
        said = self.finished(access=self.selection())
        wanted = [({"INFO"}, USED), ({"INFO"}, USED_2), ({"WARNING"}, STALE), ({"WARNING"}, OTHER)]
        self.assertEqual(said[1:], wanted)
        self.assertEqual(said[0][0], {"INFO"}, "el resumen de las finales: todas cumplen")
        self.i18n.set_language("en")
        self.assertEqual(self.finished(access=self.selection())[1], ({"INFO"}, USED_EN))

    def test_b_without_accessibilities_it_says_nothing_new(self) -> None:
        """RF-012-24: sin accesibilidades, la orden dice solo lo de siempre (una línea de resumen)."""
        self.assertEqual(len(self.finished(access=self.cstore.AccessSelection())), 1)

    def test_c_the_accessibility_is_chosen_once_and_used_for_the_gate_and_for_checking(self) -> None:
        """RF-012-24, P-9: ``execute`` elige la accesibilidad de las finales **una vez** (``select_access``, con el proyecto, la versión activa y las finales pedidas) y esa
        misma selección va a las entradas de la puerta de la 008 (``verify_inputs``) y a ``verify_project_steps``, junto a la de las bases de los acopios."""
        project, bases, access = object(), self.cstore.BaseSelection(), self.selection()
        finals = (self.surfaces.SurfaceRef(dataset="gis_dtm_pozo", label="Pozo 1"),)
        request = SimpleNamespace(name="Prueba", start=self.surfaces.SurfaceRef(elevation=100.0), finals=finals)
        fake = operator_self(self.operator, in_steps=False, provenance_dialog=False, report=lambda *_args: None, _report=lambda *_args: None,
                             _version_refusal=lambda: None)
        masks_store = _module("gis.masks.store")
        with mock.patch.object(self.res_ops, "write_unavailable", return_value=None), mock.patch.object(self.res_ops, "SESSION", SimpleNamespace(project=project)), \
                mock.patch.object(self.res_ops.scene_versions, "active_version", return_value=VERSION), \
                mock.patch.object(self.res_ops.res_panels, "surface_items"), mock.patch.object(self.res_ops, "verify_request", return_value=request), \
                mock.patch.object(masks_store, "available_tables", return_value=()), mock.patch.object(self.res_ops.masks_provenance, "compile_inputs", return_value=()), \
                mock.patch.object(self.cstore, "select_bases", return_value=bases) as pick_bases, \
                mock.patch.object(self.cstore, "select_access", return_value=access) as pick_access, \
                mock.patch.object(self.cstore, "verify_inputs", return_value=()) as inputs, \
                mock.patch.object(self.res_ops, "ensure_ready", return_value=None) as gate:
            self.assertEqual(self.operator.execute(fake, SimpleNamespace(window=None)), {"CANCELLED"})  # la puerta dice que no: no se verifica
        pick_bases.assert_called_once_with(project, VERSION, request.start)
        pick_access.assert_called_once_with(project, VERSION, finals)
        self.assertEqual(inputs.call_args.args, (project, VERSION, request.start, finals, bases, access))
        gate.assert_called_once()
        with mock.patch.object(self.res_ops, "write_unavailable", return_value=None), mock.patch.object(self.res_ops, "SESSION", SimpleNamespace(project=project)), \
                mock.patch.object(self.res_ops.scene_versions, "active_version", return_value=VERSION), \
                mock.patch.object(self.res_ops.res_panels, "surface_items"), mock.patch.object(self.res_ops, "verify_request", return_value=request), \
                mock.patch.object(masks_store, "available_tables", return_value=()), mock.patch.object(self.res_ops.masks_provenance, "compile_inputs", return_value=()), \
                mock.patch.object(self.cstore, "select_bases", return_value=bases), mock.patch.object(self.cstore, "select_access", return_value=access) as pick_once, \
                mock.patch.object(self.cstore, "verify_inputs", return_value=()), mock.patch.object(self.res_ops, "ensure_ready", return_value=object()), \
                mock.patch.object(self.cstore, "verify_project_steps", side_effect=ValueError("no se verifica aquí")) as steps:
            self.assertEqual(self.operator.execute(fake, SimpleNamespace(window=None)), {"CANCELLED"})
        pick_once.assert_called_once_with(project, VERSION, finals)  # ni siquiera al verificar: la misma selección, no otra lectura
        self.assertIs(steps.call_args.kwargs["access"], access)
        self.assertIs(steps.call_args.kwargs["bases"], bases)
        self.assertEqual(steps.call_args.kwargs["finals"], finals)


if __name__ == "__main__":
    unittest.main()
