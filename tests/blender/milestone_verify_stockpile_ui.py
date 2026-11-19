# SPDX-License-Identifier: GPL-3.0-or-later
"""La ventana de verificar con la detección de los acopios, con el proyecto y las órdenes reales (spec 016, T36; HU-016-2; RF-012-30,
RF-012-31, RF-016-09; DIFF-012 §2, D-a; plan 016 §5.5; comprobación manual M7), en ``blender -b`` y sin pantalla. Es un hito (P-13: proyecto en la
rejilla de 2 m); el «verde» tiene ``test_verify_stockpile_ui.py`` (las líneas, la lectura una vez por partida y la ventana de lo guardado).

El proyecto de ``test_removal_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, el levantamiento con **dos** montones, las marcas
y la detección ``STK-001`` «Acopios», **del proyecto**, hecha sobre el levantamiento) con una rejilla más, la **retirada** (el plano sin los
montones). Con «Verificar un diseño por recinto…» (``geoblender.res_verify_constraints``) real, las pruebas, en el orden de sus letras sobre el
mismo estado:

- RF-012-30, D-a (a): el diálogo, con el levantamiento como partida, dice qué base usa (la detección y su material); con otra partida, o con una
  cota constante, dice que no la usa y por qué (en alerta, con la superficie sobre la que se hizo); lo mismo en inglés; cambiar la partida
  del diálogo cambia lo que dice; sin escribir nada.
- RF-012-30, D-a (b): verificar con la detección: la base es una **entrada** de la operación, la orden la informa y la ventana de la
  verificación la nombra (de lo que guardó la tabla), antes de la tabla de las finales; lo que dijo el diálogo es lo que usó la orden.
- RF-012-31, D-a (c): verificar con otra partida: la detección no se usa, se avisa en alerta con la superficie sobre la que se hizo y la
  ventana lo nombra; todo el corte cuenta (sin base).
- RF-012-31, D-a (d): la detección **obsoleta** (se cambió su margen) no se usa: el diálogo, lo que informa la orden y la ventana dicen que
  está obsoleta y qué cambió; la verificación se hace igual, sin base.
- RF-012-31, RF-011-03 (e): una base en **otra rejilla** se rechaza como el de una superficie (el error nombra la base y no se registra nada).
- RF-012-30, RF-012-31 (T42, en (b) y (c)): la ventana de la verificación escribe las líneas de la base en el idioma de la interfaz, de lo
  que anotaron los ajustes de la operación (``StoredVerification.selection`` y ``.start_name``).

Se ejecuta con ``tools/run_blender_tests.py`` (es un hito: ``check.py --completo``).
"""

import json
import re
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.blender import test_removal_ops as rem_ops
from tests.support.fake_layout import FakeLayout, operator_self

VERIFY = "geoblender.res_verify_constraints"
PANEL = "GEOBLENDER_PT_res_verification"
FINAL = "Retirada de los acopios"
USED = "Base de acopios: detección STK-001 «Acopios» (sin material)"
USED_EN = "Stockpile base: detection STK-001 «Acopios» (sin material)"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_EVENTS = 20_000


def plane() -> np.ndarray:
    """El levantamiento sin los montones (``100 + 0,03·y + 0,01·x``): lo que deja retirarlos."""
    x, y = platform_ops.centers()
    return 100.0 + 0.03 * y + 0.01 * x


class VerifyStockpileUiTest(rem_ops.RemoveStockpileTest):
    """Lo de ``RemoveStockpileTest`` (el proyecto de los acopios y sus ayudantes; sus pruebas no se repiten) con la retirada como rejilla."""

    final_name: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.res_ops = platform_ops._module("bl.ops.res")
        cls.cpanels = platform_ops._module("bl.ui.constraint_panels")
        cls.cstore = platform_ops._module("reserves.compliance_store")
        cls.rsurfaces = platform_ops._module("reserves.surfaces")
        cls.final_name = cls.write_grid(FINAL, plane())

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def verify_cls(self) -> Any:
        return self.commands.registered_class(VERIFY)

    @property
    def cview(self) -> Any:
        return bpy.context.window_manager.geoblender_constraints

    def dialog(self, **values: Any) -> Any:
        """El operador de mentira de «Verificar un diseño por recinto…» con el diálogo abierto (``invoke``, sin ventana)."""
        context = SimpleNamespace(window=None, selected_objects=[], window_manager=SimpleNamespace(
            invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"})))
        fields: dict[str, Any] = {"name": "", "start": "", "finals": "", "start_elevation": "", "final_elevation": "", "in_steps": False,
                                  "properties": SimpleNamespace(is_property_set=lambda name: name in values), **values}
        fake = operator_self(self.verify_cls, report=lambda kind, text: None, **fields)
        self.assertEqual(self.verify_cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        return fake

    def said(self, fake: Any, **values: Any) -> str:
        """Lo que dice el diálogo de ``fake`` con ``values`` cambiados (la partida, su cota): sus etiquetas, unidas."""
        for name, value in values.items():
            setattr(fake, name, value)
        fake.layout = FakeLayout()
        self.verify_cls.draw(fake, bpy.context)
        return " ".join(fake.layout.texts())

    def verify(self, name: str, start: str, finals: str | None = None, **values: Any) -> list[tuple[set[str], str]]:
        """Verifica con la orden real (de una vez, sin pasos) y da lo que informó, por nivel."""
        said: list[tuple[set[str], str]] = []
        cls = self.verify_cls
        with mock.patch.object(cls, "_report", lambda self, level, text: said.append((level, text))), \
                mock.patch.object(self.res_ops, "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.res_verify_constraints(
                "EXEC_DEFAULT", name=name, start=start, finals=self.final_name if finals is None else finals, in_steps=False, **values),
                {"FINISHED"})
        return said

    def stored(self, name: str) -> Any:
        with self.project.read() as conn:
            return self.cstore.read_verification(conn, self.v01.uid, name)

    def inputs(self, name: str) -> dict[str, str]:
        """Lo que consumió la verificación ``name``: papel → nombre del dato."""
        (uid,) = [row[0] for row in self.rows("SELECT uid, settings FROM gb_operation WHERE op_type = 'res.verify_constraints' AND "
                                              "status = 'done' AND superseded_by IS NULL") if json.loads(row[1])["name"] == name]
        return dict(self.rows("SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
                              "WHERE io.operation_uid = ? AND io.direction = 'in'", uid))

    def window_texts(self) -> str:
        from tests.support.fake_layout import draw

        return " ".join(draw(getattr(bpy.types, PANEL), bpy.context).texts())

    def write_fine_grid(self, name: str) -> str:
        """Una rejilla del proyecto con **otra** rejilla (el doble de celdas por lado): lo que una base en otra rejilla rechaza."""
        gis_store, grid_mod = platform_ops._module("gis.store"), platform_ops._module("gis.grid")
        record = self.project.record
        grid = grid_mod.project_grid(record.window, float(record.grid_step_m))
        fine = grid_mod.Grid(grid.west, grid.north, grid.dx / 2.0, grid.dy / 2.0, grid.ncols * 2, grid.nrows * 2)
        crs, vertical = gis_store.project_references(self.project)
        handle = platform_ops._module("core.provenance.operations").begin_operation(
            self.project, platform_ops._module("gis.provenance").RESAMPLE, settings={"nombre": name}, executor="blender")
        library, library_version = platform_ops._module("gis.crs").crs_library()
        with gis_store.ResultWriter(self.project, handle) as out:
            out.raster(name, platform_ops._module("gis.raster").Raster(fine, np.full(fine.shape, 100.0), crs, vertical))
            records = out.commit(software={library: library_version}, message=platform_ops.REASON)
        return str(records[0].name)

    # --- (a) El diálogo ------------------------------------------------------------------------

    def test_a_the_dialog_says_which_base_it_uses_or_why_not_without_writing_anything(self) -> None:
        """RF-012-30, RF-012-31, D-a (M7): con el levantamiento como partida (sobre el que se hizo la detección), el diálogo dice qué base
        usa (la detección, su nombre y su material, sin alerta); con otra superficie, o con una cota constante, dice que no la usa, con la
        superficie sobre la que se hizo y la de partida, en alerta; cambiar la partida cambia lo que dice, y en inglés, también; no escribe."""
        before = self.state()
        fake = self.dialog()
        identifiers = [item[0] for item in self.cpanels.start_items(None, None)]
        self.assertIn(self.survey_name, identifiers)
        self.assertIn(self.final_name, identifiers)
        survey = self.said(fake, start=self.survey_name)
        self.assertIn(USED, survey)
        self.assertNotIn("no se usa como base", survey)
        other = self.said(fake, start=self.final_name)
        self.assertNotIn("Base de acopios", other)
        self.assertIn("La detección de acopios STK-001 «Acopios» no se usa como base: se hizo sobre «" + self.survey_name, other)
        self.assertIn("no sobre la superficie de partida «" + self.final_name + "»", other)
        self.assertIn("Todo el corte cuenta como corte de terreno", other)
        constant = self.said(fake, start=self.res_ops.res_panels.ELEVATION, start_elevation="100")
        self.assertIn("STK-001 «Acopios» no se usa como base: se hizo sobre «" + self.survey_name, constant)
        self.assertEqual(self.said(fake, start=self.survey_name), survey, "volver a la partida da lo mismo")
        self.assertEqual([item for item in fake.layout.of_kind("label") if item.alert], [], "lo que se usa no va en alerta")
        self.said(fake, start=self.final_name)
        self.assertTrue(any(item.alert and item.icon == "ERROR" for item in fake.layout.of_kind("label")), "lo que no se usa, sí")
        self.i18n.set_language("en")
        english = self.said(self.dialog(start=self.survey_name))
        self.assertIn(USED_EN, english)
        self.assertIn("is not used as a base", self.said(fake, start=self.final_name).replace("\n", " "))
        self.assertEqual(self.state(), before, "el diálogo no escribe nada")

    # --- (b) Verificar con la detección --------------------------------------------------------

    def test_b_verifying_on_the_surface_of_the_detection_uses_its_base_and_the_window_and_the_command_name_it(self) -> None:
        """RF-012-30, RF-012-24, D-a (M7): verificar con el levantamiento como partida usa la base de la detección (una **entrada** de la
        operación, ``stockpile_base_1``), la orden lo informa (sin alerta), la tabla lo guarda y la ventana de la verificación lo nombra
        —antes de la tabla de las finales—; es lo que dijo el diálogo."""
        fake = self.dialog(start=self.survey_name)
        shown = self.said(fake)
        self.assertIn(USED, shown)
        with mock.patch.object(self.cstore, "select_bases", wraps=self.cstore.select_bases) as chosen:
            said = self.verify("Con acopios", self.survey_name)
        self.assertEqual(chosen.call_count, 1, "la base se elige una vez: la misma para las entradas de la puerta y para verificar")
        self.assertIn(({"INFO"}, USED), said)
        self.assertFalse([text for level, text in said if "no se usa como base" in text])
        roles = self.inputs("Con acopios")
        self.assertIn("stockpile_base_1", roles)
        self.assertTrue(roles["stockpile_base_1"].startswith("des_stb_acopios"), roles)
        stored = self.stored("Con acopios")
        self.assertEqual((stored.bases, stored.skipped), ((USED,), ()))
        self.assertEqual([(note.text, note.alert) for note in self.cview.verify_notes][:1], [(USED, False)])
        window = self.window_texts()
        self.assertIn(USED, window)
        self.assertLess(window.index(USED), window.index("«" + self.final_name + "»"), "antes de la tabla de las finales")
        self.assertNotIn("no se usa como base", window)
        # T42 (RF-012-30): la ventana escribe de lo que anotaron los ajustes de la operación (``StoredVerification.selection``), no del texto en
        # español de la tabla: en inglés, las líneas de la base en inglés.
        self.assertEqual([(item.detection, item.name) for item in stored.selection.bases], [("STK-001", "Acopios")])
        self.i18n.set_language("en")
        self.cpanels.fill_verification(self.project, self.v01.uid, "Con acopios")
        self.assertEqual([(note.text, note.alert) for note in self.cview.verify_notes][:1], [(USED_EN, False)])
        self.assertIn(USED_EN, self.window_texts())
        self.assertNotIn(USED, self.window_texts())
        self.i18n.set_language("es")
        self.cpanels.fill_verification(self.project, self.v01.uid, "Con acopios")
        self.assertEqual([(note.text, note.alert) for note in self.cview.verify_notes][:1], [(USED, False)])

    # --- (c) Otra partida ----------------------------------------------------------------------

    def test_c_verifying_on_another_surface_does_not_use_the_detection_and_says_so(self) -> None:
        """RF-012-31, D-a (M7): con otra superficie como partida, la detección no se usa (sin entrada de base: todo el corte cuenta), la
        orden lo avisa y la ventana lo nombra en alerta con la superficie sobre la que se hizo."""
        said = self.verify("Otra partida", self.final_name, finals=self.survey_name)
        warnings = [text for level, text in said if level == {"WARNING"} and "no se usa como base" in text]
        self.assertEqual(len(warnings), 1, said)
        self.assertIn("se hizo sobre «" + self.survey_name, warnings[0])
        self.assertIn("no sobre la superficie de partida «" + self.final_name + "»", warnings[0])
        self.assertFalse([role for role in self.inputs("Otra partida") if "base" in role])
        stored = self.stored("Otra partida")
        self.assertEqual((stored.bases, stored.skipped), ((), (warnings[0],)))
        notes = [(note.text, note.alert) for note in self.cview.verify_notes]
        self.assertEqual(notes[:1], [(warnings[0], True)])
        self.assertIn("no se usa como base", self.window_texts())
        self.assertNotIn("Base de acopios", self.window_texts())
        # T42 (RF-012-31): en inglés, el aviso de la ventana, en inglés, con la superficie de la detección y la de partida
        self.assertEqual(stored.start_name, self.final_name)
        self.i18n.set_language("en")
        self.cpanels.fill_verification(self.project, self.v01.uid, "Otra partida")
        (english,) = [note for note in self.cview.verify_notes if note.alert]
        self.assertIn("is not used as a base: it was made on «" + self.survey_name, english.text)
        self.assertIn("not on the start surface «" + self.final_name + "»", english.text)
        self.assertNotIn("no se usa como base", self.window_texts())
        self.i18n.set_language("es")

    # --- (d) Obsoleta --------------------------------------------------------------------------

    def test_d_a_stale_detection_is_not_used_and_everything_says_why(self) -> None:
        """RF-012-31, D-a (M7): con la detección **obsoleta** (se cambió su margen), el diálogo, lo que informa la orden y la ventana de la
        verificación dicen que no se usa, que está obsoleta y qué cambió; la verificación se hace igual, sin base; y, en inglés, el diálogo
        y lo informado también."""
        core_params = platform_ops._module("core.params")
        key = platform_ops._module("design.params").entity_key("STK-001", "margin_m")
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(conn, key, value=4.5, reason="Prueba de la T36")
        self.assertEqual(self.entities.project_registry(self.project).get("STK-001").record.state, self.entities.EntityState.STALE)
        pattern = re.compile(r"La detección de acopios STK-001 «Acopios» no se usa como base: está obsoleta \((.+)\); recalcúlela y verifique "
                             r"otra vez\. Todo el corte cuenta como corte de terreno\.")
        fake = self.dialog(start=self.survey_name)
        found = pattern.search(self.said(fake))
        self.assertIsNotNone(found, self.said(fake))
        cause = found.group(1)  # type: ignore[union-attr]
        self.assertTrue(cause.strip(), "dice qué cambió")
        self.assertNotIn("Base de acopios", self.said(fake))
        said = self.verify("Con la obsoleta", self.survey_name)
        warnings = [text for level, text in said if level == {"WARNING"} and "está obsoleta" in text]
        self.assertEqual(len(warnings), 1, said)
        self.assertEqual(pattern.search(warnings[0]).group(1), cause)  # type: ignore[union-attr]
        self.assertFalse([role for role in self.inputs("Con la obsoleta") if "base" in role])
        stored = self.stored("Con la obsoleta")
        self.assertEqual((stored.bases, stored.skipped), ((), (warnings[0],)))
        self.assertEqual([(note.text, note.alert) for note in self.cview.verify_notes][:1], [(warnings[0], True)])
        self.assertIn("está obsoleta (" + cause + ")", self.window_texts().replace("  ", " "))
        self.i18n.set_language("en")
        self.assertIn("is stale", self.said(self.dialog(start=self.survey_name)))

    # --- (e) Otra rejilla ----------------------------------------------------------------------

    def test_e_a_base_in_another_grid_is_rejected_like_a_surface_and_nothing_is_registered(self) -> None:
        """RF-012-31, RF-011-03 (M7): si la base de la detección está en otra rejilla que las máscaras, la orden rechaza la verificación como
        el de una superficie en otra rejilla —el error nombra la base— sin registrar nada."""
        fine = self.write_fine_grid("Base fina")
        selection = self.cstore.BaseSelection((self.cstore.StockpileBase(
            "STK-009", "Fina", "project", None, self.rsurfaces.SurfaceRef(dataset=fine, label="Base fina de STK-009")),))
        before = self.state()
        with mock.patch.object(self.cstore, "select_bases", return_value=selection):
            with self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.res_verify_constraints("EXEC_DEFAULT", name="Rechazada", start=self.survey_name,
                                                          finals=self.final_name, in_steps=False)
        self.assertIn("Base fina de STK-009", str(caught.exception))
        after = self.state()
        self.assertEqual(after[0], before[0], "ninguna operación registrada")
        self.assertEqual(after[3:], before[3:], "ni cifras ni ficheros")


for _name in dir(rem_ops.RemoveStockpileTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test") and _name not in vars(VerifyStockpileUiTest):
        setattr(VerifyStockpileUiTest, _name, None)


if __name__ == "__main__":
    unittest.main()
