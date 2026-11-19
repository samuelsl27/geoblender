# SPDX-License-Identifier: GPL-3.0-or-later
"""El menú, el catálogo y la activación de las órdenes de acopios, contrafuerte y cuerpo apoyado (spec 016, T35; HU-016-1 a 4; RF-016-25,
RF-015-28, RF-015-05; plan 016 §5.3.3 y §5.5; D-8, D-14, D-15; comprobación manual M6), **sin proyecto** (lo que se hace con ellas, con el
proyecto de los acopios, está en ``milestone_stockpile_ops.py``).

- RF-016-25 (a): las tres órdenes nuevas (``des_edit_stockpile``, ``des_detect_stockpiles`` y ``des_stockpile_candidates``) son reales, de la
  entrada 016 (entregada), con sus propiedades nombradas y descritas en los dos idiomas y la vista previa de las marcas conectada
  (``update`` en lo que se dibuja, ``_ClearsEntityPreview`` antes de ``_CalculateAndCreate``).
- RF-016-25 (b): el menú Diseño ▸ Pistas y entidades ▸ Entidades dibuja, en su orden, «Plataforma…», «Acopio (detectar, retirar)…»,
  «Contrafuerte…» y «Cuerpo apoyado…», **activas** con el proyecto en escritura y la versión editable y **desactivadas con su motivo** si no.
- RF-016-25, RF-015-28 (c): las seis órdenes de la 016 se activan y se desactivan con el motivo de ``design_unavailable`` (el proyecto en
  solo lectura, la versión SUPERADO) y la descripción dice el porqué de la versión no editable.
- RF-016-25 (d): «Acopio (detectar, retirar)…» abre la orden de detectar o la de retirar según lo que se elija.
- RF-015-28 (e): las órdenes del menú «Entidad ▾» no toman el objeto de una detección **del proyecto** (su código se repite en cada versión).
- RF-016-23, RF-015-28 (f): la vista previa de una entidad de la versión (plataforma, detección de acopios, contrafuerte); la retirada y el
  cuerpo no la tienen, ni una entidad sin calcular.
- RF-016-08 (g): la barra N «Entidad» de una detección dibuja «Candidatos…» y, por cada candidato pendiente, convertir, descartar e «Ir a»; «Ir
  a» no abre nada.
- Principio 8 (z): desactivar Geoblender quita las tres órdenes.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, draw, operator_self

EDIT = "geoblender.des_edit_stockpile"
DETECT = "geoblender.des_detect_stockpiles"
CANDIDATES = "geoblender.des_stockpile_candidates"
REMOVE = "geoblender.des_remove_stockpile"
BUTTRESS = "geoblender.des_add_buttress"
BODY = "geoblender.des_create_body"
NEW = (EDIT, DETECT, CANDIDATES)
ALL_016 = (EDIT, DETECT, CANDIDATES, REMOVE, BUTTRESS, BODY)
MENU = "GEOBLENDER_MT_des_entities"
ENTITIES_MENU = ("geoblender.des_create_platform", EDIT, BUTTRESS, BODY)
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
READ_ONLY = "Proyecto en solo lectura: prueba"
HIDDEN = {DETECT: {"confirm", "in_steps", "preview"}, CANDIDATES: {"rows"}, EDIT: set()}
PROPERTIES = {
    EDIT: {"mode": ("What to do", "Detect the stockpiles of a layer of marks, or remove one of those already detected in the active version "
                                  "or in the project")},
    DETECT: {
        "name": ("Name", "Name of the detection, unique in its scope (the project or the active version)"),
        "surface": ("Surface", "Surface the stockpiles are detected on: the ground or a survey of the project (the detection is then of the "
                               "project, also without an active version) or a surface of the active version (the detection is then of "
                               "the version)"),
        "layer": ("Layer of the marks", "Layer of polygons of the project with one mark per stockpile: a polygon that says roughly where "
                                        "it is"),
        "name_field": ("Name field", "Field of the layer with the name of each mark (its key; empty: the number of the polygon)"),
        "margin_field": ("Margin field", "Numeric field of the layer with the margin of each mark in metres (empty: the margin of the "
                                         "detection)"),
        "material_field": ("Material field", "Field of the layer with the material of each stockpile (empty: without material)"),
        "base_field": ("Base surface field", "Field of the layer with the name of a surface of the project that is the base of the "
                                             "stockpile instead of a fitted plane (empty: the plane)"),
        "candidates": ("Look for candidates", "Also look for the stockpiles that have no mark: the zones that stand out from the opening "
                                              "of the surface, listed so that you convert each one into a stockpile or discard it with a "
                                              "reason"),
    },
    CANDIDATES: {
        "detection": ("Detection", "Code or name of the detection of stockpiles (empty: the one of the object selected in the 3D view or, "
                                   "without it, the only one that has candidates)"),
        "in_project": ("Of the project", "The detection is of the project and not of the active version (a detection of a surface of the "
                                         "project)"),
        "candidate": ("Candidate", "Key of the candidate the decision is about (c01…): one of those of the list"),
        "action": ("Decision", "What is done with the candidate"),
        "reason": ("Reason", "Why: it is recorded with the decision, who made it and when; it is needed to convert, discard or ask again"),
        "recompute": ("Recompute the detection", "Repeat the detection with the decision as soon as it is made (otherwise it stays out of "
                                                  "date until «Recompute the stale results»)"),
    },
}
"""Las propiedades de cada orden con el ``msgid`` de su nombre y de su descripción (las ocultas y las colecciones, que pone quien la lanza,
no las llevan; los 14 umbrales de la detección, ``THRESHOLDS``, se comprueban aparte)."""
THRESHOLDS = ("margin_m", "crown_inner_m", "crown_outer_m", "crown_slope_deg", "crown_flat_min_m2", "max_residual_m", "fit_rounds", "turns",
              "tilt_max_deg", "support_quantile", "open_diameter_m", "min_height_m", "min_area_m2", "max_area_m2")
DRAWN = ("surface", "layer", "name_field", "margin_field", "material_field", "base_field", "candidates", "margin_m")
"""Lo que cambia lo que dibuja la vista previa de las marcas: su ``update`` redibuja."""


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class StockpileMenuTest(unittest.TestCase):
    """Con la extensión habilitada, sin proyecto: el catálogo, el menú, el ``poll`` y lo que no lee el proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.commands = _module("bl.ui.commands")
        cls.i18n = _module("core.i18n")
        cls.catalog = cls.commands.catalog()

    def registered(self, idname: str) -> Any:
        return self.commands.registered_class(idname)

    # --- (a) Las órdenes ----------------------------------------------------------------------

    def test_a_the_three_new_orders_are_real_delivered_and_named(self) -> None:
        """RF-016-25, RF-016-23, RF-015-28 (M6): ``des_edit_stockpile``, ``des_detect_stockpiles`` y ``des_stockpile_candidates`` son
        órdenes reales (sus nombres y rótulos en español) de la entrada 016, entregada, con la descripción del catálogo; sus propiedades
        llevan nombre y descripción en los dos idiomas; las 14 de umbrales de la detección también; «Vista previa» de las marcas: el botón
        (``preview`` oculta), los ``update`` de lo que se dibuja y ``_ClearsEntityPreview`` antes de ``_CalculateAndCreate``."""
        self.assertTrue(self.catalog.entries["016"].delivered)
        labels = {EDIT: "Acopio (detectar, retirar)…", DETECT: "Detectar acopios…", CANDIDATES: "Candidatos de los acopios…"}
        for idname in NEW:
            with self.subTest(orden=idname):
                cls = self.registered(idname)
                command = self.catalog.commands[idname]
                self.assertEqual((command.entry, command.module), ("016", "des"))
                self.assertEqual(cls.bl_label, labels[idname])
                self.assertEqual(cls.__doc__.strip(), command.description)
                self.assertIn("poll", vars(self.des_ops.DesignCommand))
                self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((self.catalog.commands[EDIT].kind, self.catalog.commands[EDIT].home), ("operator", MENU))
        for idname in (DETECT, CANDIDATES):
            self.assertEqual((self.catalog.commands[idname].kind, self.catalog.commands[idname].home), ("internal", ""))
        for idname, found in PROPERTIES.items():
            cls = self.registered(idname)
            self.assertEqual({name for name in cls.__annotations__ if name not in HIDDEN[idname]}, set(found) | (
                set(THRESHOLDS) if idname == DETECT else set()))
            for prop, (name, about) in found.items():
                with self.subTest(propiedad=f"{idname}.{prop}"):
                    keywords = cls.__annotations__[prop].keywords
                    self.assertEqual((keywords["name"], keywords["description"]),
                                     (self.i18n.translate("es", name), self.i18n.translate("es", about)))
                    self.assertEqual(self.i18n.untranslated([name, about]), [])
        detect = self.registered(DETECT)
        for prop in THRESHOLDS:
            with self.subTest(umbral=prop):
                keywords = detect.__annotations__[prop].keywords
                self.assertTrue(keywords["name"] and keywords["description"])
        for prop in HIDDEN[DETECT]:
            self.assertNotIn("name", detect.__annotations__[prop].keywords, "la oculta no lleva nombre: la pone quien la lanza")
        self.assertEqual(self.des_ops._STOCKPILE_HIDDEN, HIDDEN[DETECT])
        self.assertEqual(set(self.des_ops._stockpile_fields()), set(PROPERTIES[DETECT]) | set(THRESHOLDS))
        self.assertLess(detect.__mro__.index(self.des_ops._ClearsEntityPreview), detect.__mro__.index(self.des_ops._CalculateAndCreate))
        for prop in detect.__annotations__:
            if prop in HIDDEN[DETECT]:
                continue
            with self.subTest(update=prop):
                update = detect.__annotations__[prop].keywords.get("update")
                expected = {"layer": self.des_ops._stockpile_layer_changed}.get(prop, self.des_ops._refresh_stockpile_preview
                                                                                if prop in DRAWN else None)
                self.assertIs(update, expected)
        shown = draw(detect, bpy.context, confirm=False, candidates=True, layer="gis_fea_x", surface="s", **{prop: "" for prop in THRESHOLDS},
                     name="N", name_field="", margin_field="", material_field="", base_field="")
        (button,) = [item for item in shown.of_kind("operator") if item.target == DETECT]
        self.assertEqual((button.text, button.icon, button.operator_context), ("Vista previa", "HIDE_OFF", "EXEC_DEFAULT"))
        self.assertTrue(button.properties.preview)
        self.assertEqual(set(vars(button.properties)), set(PROPERTIES[DETECT]) | set(THRESHOLDS) | {"preview"})

    def test_a_b_the_thresholds_show_their_default_value_and_their_type(self) -> None:
        """RF-016-02, RF-016-07, D-3 (M6): el diálogo enseña, junto a cada umbral, **su valor por defecto y su tipo** (el de su familia:
        ADOPTADO, y HIPÓTESIS la inclinación máxima y el cuantil de apoyo); en español y en inglés; con candidatos, los cuatro de la
        búsqueda más."""
        texts = {param: self.des_ops._threshold_text(param) for param in THRESHOLDS}
        self.assertEqual(texts["margin_m"], "Por defecto: 10 m · ADOPTADO")
        self.assertEqual(texts["crown_slope_deg"], "Por defecto: 12 ° · ADOPTADO")
        self.assertEqual(texts["crown_flat_min_m2"], "Por defecto: 10 m² · ADOPTADO")
        self.assertEqual(texts["turns"], "Por defecto: 6 · ADOPTADO")
        self.assertEqual(texts["tilt_max_deg"], "Por defecto: 4 ° · HIPÓTESIS")
        self.assertEqual(texts["support_quantile"], "Por defecto: 0,60 · HIPÓTESIS")
        self.assertEqual(texts["open_diameter_m"], "Por defecto: 31 m · ADOPTADO")
        self.assertEqual(texts["max_area_m2"], "Por defecto: 20 000 m² · ADOPTADO", texts["max_area_m2"])
        self.i18n.set_language("en")
        try:
            self.assertEqual(self.des_ops._threshold_text("tilt_max_deg"), "By default: 4 ° · ASSUMPTION")
            self.assertEqual(self.des_ops._threshold_text("margin_m"), "By default: 10 m · ADOPTED")
        finally:
            self.i18n.set_language("es")
        detect = self.registered(DETECT)
        base = {"confirm": False, "layer": "gis_fea_x", "surface": "s", "name": "N", "name_field": "", "margin_field": "",
                "material_field": "", "base_field": "", **{prop: "" for prop in THRESHOLDS}}
        for asked, wanted in ((False, 10), (True, 14)):
            with self.subTest(candidatos=asked):
                shown = draw(detect, bpy.context, **{**base, "candidates": asked})
                props = [item.target for item in shown.of_kind("prop")]
                self.assertEqual(sum(prop in THRESHOLDS for prop in props), wanted)
                defaults = [item.text for item in shown.of_kind("label") if item.text.startswith("Por defecto: ")]
                self.assertEqual(len(defaults), wanted, "cada umbral con su valor por defecto y su tipo")

    # --- (b) El menú y (c) la activación ------------------------------------------------------

    def test_b_the_entities_menu_draws_the_four_orders_available_or_disabled_with_their_reason(self) -> None:
        """RF-016-25, RF-015-28 (M6): el menú Entidades dibuja «Plataforma…», «Acopio (detectar, retirar)…», «Contrafuerte…» y «Cuerpo
        apoyado…», en ese orden y **entregadas** (sin la nota «Disponible en R-36»); que se puedan lanzar ahora lo dice el ``poll`` de cada
        una (:meth:`test_c_the_orders_are_active_with_a_writable_project_and_disabled_with_their_reason`)."""
        shown = draw(getattr(bpy.types, MENU), bpy.context)
        operators = [(item.target, item.enabled) for item in shown.items if item.kind == "operator" and item.target in ENTITIES_MENU]
        self.assertEqual(operators, [(target, True) for target in ENTITIES_MENU])
        labels = [item.text for item in shown.items if item.kind in ("operator", "label")]
        for text in ("Plataforma…", "Acopio (detectar, retirar)…", "Contrafuerte…", "Cuerpo apoyado…"):
            self.assertIn(text, labels)
        self.assertFalse([text for text in labels if text.startswith("Disponible en")])
        self.assertNotIn("Unidad por espesor sobre su apoyo…", [item.text for item in draw(
            getattr(bpy.types, "GEOBLENDER_MT_ui_geology"), bpy.context).items])

    def test_c_the_orders_are_active_with_a_writable_project_and_disabled_with_their_reason(self) -> None:
        """RF-016-25, RF-015-28 (M6): las seis órdenes de la 016 se activan con el proyecto en escritura y la versión activa editable (o
        ninguna: la detección sobre una superficie del proyecto, D-15) y se desactivan con el motivo del proyecto en solo lectura o de la
        versión SUPERADO; la descripción de la de una versión no editable dice por qué."""
        for idname in ALL_016:
            cls = self.registered(idname)
            for reason in (None, READ_ONLY, NOT_EDITABLE):
                with self.subTest(orden=idname, motivo=reason), mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                    messages: list[str] = []
                    with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                        self.assertEqual(bool(cls.poll(bpy.context)), reason is None)
                    self.assertEqual(messages, [] if reason is None else [reason])
        with mock.patch.object(self.des_ops.scene_versions, "not_editable_text", return_value=NOT_EDITABLE):
            for idname in ALL_016:
                self.assertIn(NOT_EDITABLE, self.registered(idname).description(bpy.context, SimpleNamespace()), idname)

    def test_d_the_chooser_opens_the_order_that_is_chosen(self) -> None:
        """RF-016-25 (M6): «Acopio (detectar, retirar)…» propone retirar si ya hay acopios que retirar y detectar si no, y al aceptar abre
        **«Detectar acopios…»** o **«Retirar un acopio…»** (cuando acaba ésta: un diálogo no se abre desde otro) sin escribir nada; con el
        proyecto en solo lectura lo dice."""
        cls = self.registered(EDIT)
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=object(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        for has, wanted in ((True, "REMOVE"), (False, "DETECT")):
            fake = operator_self(cls, mode="DETECT", provenance_dialog=False, properties=SimpleNamespace(is_property_set=lambda name: False))
            with self.subTest(acopios=has), mock.patch.object(self.panels, "refresh_removal_choices"), \
                    mock.patch.object(self.panels, "has_removal_stockpiles", return_value=has):
                self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
            self.assertEqual(fake.mode, wanted)
            self.assertEqual(dialog.call_args.kwargs["title"], "Acopio (detectar, retirar)…")
        asked = operator_self(cls, mode="REMOVE", provenance_dialog=False, properties=SimpleNamespace(is_property_set=lambda name: True))
        with mock.patch.object(self.panels, "refresh_removal_choices") as refresh, mock.patch.object(self.panels, "has_removal_stockpiles"):
            cls.invoke(asked, context, None)
        refresh.assert_not_called()
        self.assertEqual(asked.mode, "REMOVE", "lo que dio quien la lanza no se cambia")
        for mode, idname in (("DETECT", DETECT), ("REMOVE", REMOVE)):
            fake = operator_self(cls, mode=mode, report=mock.Mock())
            with self.subTest(modo=mode), mock.patch.object(self.des_ops, "write_unavailable", return_value=None), \
                    mock.patch.object(self.des_ops, "_invoke_later") as later:
                self.assertEqual(cls.execute(fake, context), {"FINISHED"})
            later.assert_called_once_with(idname, context.window)
        blocked = operator_self(cls, mode="DETECT", report=mock.Mock())
        with mock.patch.object(self.des_ops, "write_unavailable", return_value=READ_ONLY), mock.patch.object(self.des_ops, "_invoke_later") as later:
            self.assertEqual(cls.execute(blocked, context), {"CANCELLED"})
        later.assert_not_called()
        blocked.report.assert_called_once_with({"ERROR"}, READ_ONLY)

    # --- (e) y (f) Las órdenes de la 015 con los tipos nuevos ---------------------------------

    def test_e_the_entity_commands_do_not_take_the_detection_of_the_project(self) -> None:
        """RF-015-28, D-15 (M6): el código de una detección **del proyecto** se repite en cada versión (``STK-001``): las órdenes del menú
        «Entidad ▾» no toman la del objeto seleccionado y lo dicen; la de una entidad de la versión activa, sí; la de otra versión, no."""
        context = SimpleNamespace()
        with mock.patch.object(self.des_ops, "_selected_entity", return_value=("STK-001", "")):
            with self.assertRaises(ValueError) as caught:
                self.des_ops._entity_or_selected("", context)
            self.assertIn("es del proyecto, no de una versión", str(caught.exception))
            self.assertEqual(self.des_ops._entity_or_selected("STK-001", context), "STK-001", "lo tecleado manda")
        with mock.patch.object(self.des_ops.scene_versions, "active_version", return_value="uid-1"):
            with mock.patch.object(self.des_ops, "_selected_entity", return_value=("PLT-001", "uid-1")):
                self.assertEqual(self.des_ops._entity_or_selected("", context), "PLT-001")
            with mock.patch.object(self.des_ops, "_selected_entity", return_value=("PLT-001", "uid-2")):
                with self.assertRaises(ValueError):
                    self.des_ops._entity_or_selected("", context)
            with mock.patch.object(self.des_ops, "_selected_entity", return_value=("", "")):
                self.assertEqual(self.des_ops._entity_or_selected("", context), "")

    def test_f_the_preview_of_an_entity_by_kind(self) -> None:
        """RF-016-23, RF-015-26 (M6): la vista previa de una entidad de la versión es la de la plataforma (``EntityPlan(code=…)``) y se
        reconstruye la de una detección (sus marcas) y la de un contrafuerte (su zona de coronación) de lo que recalcularía; una retirada, un
        cuerpo apoyado o una entidad sin calcular **no la tienen** y se dice."""
        entities = _module("design.entities")
        plan = self.des_ops.GEOBLENDER_OT_des_entity_preview._plan
        entity = _module("bl.draw.entity")

        def entry(kind: str, code: str, operation: str | None = "op") -> Any:
            return SimpleNamespace(record=SimpleNamespace(kind=kind, code=code, name=f"N {code}"), operation_uid=operation)

        found = plan(None, None, entry(entities.EntityKind.PLATFORM, "PLT-001", None))
        self.assertEqual((found.kind, found.code), ("entity", "PLT-001"))
        for kind, code in ((entities.EntityKind.REMOVAL, "RMV-001"), (entities.EntityKind.BODY, "BDY-001")):
            with self.subTest(tipo=kind), self.assertRaises(ValueError) as caught:
                plan(None, None, entry(kind, code))
            self.assertIn("no tiene vista previa: solo la tienen una plataforma", str(caught.exception))
        for kind, code in ((entities.EntityKind.STOCKPILE, "STK-001"), (entities.EntityKind.BUTTRESS, "BTR-001")):
            with self.subTest(sin_calcular=kind), self.assertRaises(ValueError) as caught:
                plan(None, None, entry(kind, code, None))
            self.assertIn("no está calculada: no hay nada que previsualizar", str(caught.exception))
        self.assertTrue(entity.EntityPlan(stockpile=object()).kind == "stockpile")

    def test_g_the_sidebar_of_a_detection_draws_the_candidate_buttons(self) -> None:
        """RF-016-08, RF-016-10 (M6): la barra N «Entidad» de una detección dibuja **«Candidatos…»** y, de cada candidato **pendiente**, su
        clave y los botones de **convertir**, **descartar** (que abren la lista con su motivo) e **«Ir a»** (que no abre nada: encuadra la
        vista y no deja su contexto a lo que se dibuja después)."""
        panels, found = self.panels, self.des_ops.STOCKPILE_CANDIDATES
        rows = [SimpleNamespace(kind=panels.ROW_CANDIDATES, name="Candidatos…", uid="", alert=False),
                SimpleNamespace(kind=panels.ROW_DECIDE, name="c01", uid="c01", alert=False),
                SimpleNamespace(kind=panels.ROW_DECIDE, name="c03", uid="c03", alert=False),
                SimpleNamespace(kind=panels.ROW_EXPORT, name="Exportar la base de los acopios de «mineral» a GeoTIFF…", uid="uid-base", alert=False)]
        layout = FakeLayout()
        with mock.patch.object(panels, "view", return_value=SimpleNamespace(item=rows)), \
                mock.patch.object(panels, "_draw_item", return_value=True), mock.patch.object(panels, "_is_detection", return_value=True), \
                mock.patch.object(panels, "entity_wanted", return_value="uid"), mock.patch.object(panels.labels, "sidebar_width", return_value=300), \
                mock.patch.object(panels, "active_object", return_value=object()):
            panels.draw_entity(layout, SimpleNamespace())
        operators = [item for item in layout.items if item.kind == "operator"]
        self.assertEqual([(item.target, item.text) for item in operators], [
            (found, "Candidatos…"),
            (found, "Convertir"), (found, "Descartar"), (found, "Ir a"),
            (found, "Convertir"), (found, "Descartar"), (found, "Ir a"),
            ("geoblender.des_export_design_grid", "Exportar la base de los acopios de «mineral» a GeoTIFF…")])
        actions = [(item.properties.candidate, item.properties.action) for item in operators[1:7]]
        self.assertEqual(actions, [("c01", "CONVERT"), ("c01", "DISCARD"), ("c01", "GO_TO"), ("c03", "CONVERT"), ("c03", "DISCARD"), ("c03", "GO_TO")])
        self.assertEqual([item.operator_context for item in operators], ["INVOKE_DEFAULT"] * 3 + ["EXEC_DEFAULT"] + ["INVOKE_DEFAULT"] * 2
                         + ["EXEC_DEFAULT"] + ["INVOKE_DEFAULT"], "«Ir a» no abre nada y no deja su contexto a los botones que siguen")
        self.assertEqual(operators[-1].properties.source, "uid-base")

    # --- (h) «Crear» por pasos --------------------------------------------------------------

    def test_h_creating_the_detection_runs_by_steps_from_the_interface_and_stopping_it_leaves_nothing(self) -> None:
        """RNF-016-03, RNF-016-05, RF-016-02, RF-015-29 (T44; con el proyecto y los pasos de verdad: ``milestone_stockpile_ops.py`` y
        ``perf_stockpiles.py``): «Crear» la detección desde la interfaz (``in_steps`` con ventana) **empieza el modal de pasos** de
        ``Calculation.create_steps`` con el presupuesto de la interfaz y devuelve ``RUNNING_MODAL``; desde un guion (sin ventana), de una vez,
        como las demás. Sus pasos son los de crear y, al llegar lo guardado, lo registran (informe y vista previa quitada): **la del proyecto
        acaba ahí** y la de una versión sigue en el mismo modal con lo que encadena. Esc o un fallo al crearla descartan el cálculo y vacían su
        resumen; con el proyecto cerrado, se para con sus palabras; y los textos de crear, en los dos idiomas."""
        cls = self.registered(DETECT)
        progress = _module("core.project.model").Progress
        store, entity_store = _module("design.stockpile_store"), _module("design.entity_store")
        provenance = _module("design.provenance")

        class Prepared:  # lo que ``create_steps`` exige de la entidad del cálculo
            pass

        stored = SimpleNamespace(name="guardado")

        def made(op_type: str) -> Any:
            def create_steps(budget_s: float) -> Any:
                yield progress("stockpile_store", 0, 2, "tablas")
                yield progress("stockpile_store", 1, 2, "registrando")
                yield progress("created", 2, 2, "guardada", result=stored)

            return SimpleNamespace(entity=Prepared(), name="Mis acopios", version="V01", op_type=op_type, create=mock.Mock(),
                                   create_steps=mock.Mock(side_effect=create_steps))

        started: list[Any] = []
        log: list[str] = []
        project = object()

        def operator(**values: Any) -> Any:
            return operator_self(cls, **{"in_steps": True, "report": lambda kind, text: log.append(text), "report_log": [],
                                         "_start": lambda context, steps: started.append(steps), **values})

        window = SimpleNamespace(window=object())
        with mock.patch.object(store, "PreparedDetection", Prepared), mock.patch.object(self.des_ops, "SESSION", SimpleNamespace(project=project)), \
                mock.patch.object(self.des_ops, "_entity_preview_off") as preview_off, \
                mock.patch.object(cls, "_registered") as registered:
            for scope, op_type in (("proyecto", provenance.STOCKPILE_DETECT_PROJECT), ("versión", provenance.STOCKPILE_DETECT)):
                started.clear()
                registered.reset_mock()
                preview_off.reset_mock()
                calc = made(op_type)
                chain = [progress("chain", 0, 1, "declarar"), progress("chain", 1, 1, "capa", result="encadenado")]
                fake = operator()
                with mock.patch.object(self.des_ops, "calculation", return_value=calc), \
                        mock.patch.object(entity_store, "after_entity_change", return_value=iter(chain)) as follows:
                    self.assertEqual(cls._create(fake, window), {"RUNNING_MODAL"}, scope)
                    self.assertEqual((fake._creating, fake._project, fake._name), (True, project, "Mis acopios"))
                    calc.create.assert_not_called()
                    registered.assert_not_called()  # nada se registra hasta que los pasos lo hacen
                    (steps,) = started
                    shown = list(steps)
                calc.create_steps.assert_called_once_with(budget_s=cls.STEP_BUDGET_S)
                registered.assert_called_once_with(calc)
                preview_off.assert_called_once_with()
                if op_type == provenance.STOCKPILE_DETECT_PROJECT:
                    self.assertEqual([step.phase for step in shown], ["stockpile_store", "stockpile_store", "created"], scope)
                    self.assertIs(shown[-1].result, stored, "la del proyecto acaba con el paso que lleva lo guardado")
                    follows.assert_not_called()
                    self.assertTrue(fake._creating)
                    self.assertEqual(cls._finished(fake, window, stored), {"FINISHED"})
                    self.assertFalse(fake._creating)
                else:
                    self.assertEqual([step.phase for step in shown], ["stockpile_store", "stockpile_store", "chain", "chain"], scope)
                    self.assertEqual(shown[-1].result, "encadenado")
                    follows.assert_called_once_with(project, "V01", budget_s=cls.STEP_BUDGET_S)
                    self.assertEqual((fake._creating, fake._chain), (False, True), "lo que sigue, en el mismo modal")

            calc = made(provenance.STOCKPILE_DETECT_PROJECT)  # desde un guion o sin ventana: de una vez, como las demás
            started.clear()
            with mock.patch.object(self.des_ops, "calculation", return_value=calc):
                for context, in_steps in ((SimpleNamespace(window=None), True), (window, False)):
                    self.assertEqual(cls._create(operator(in_steps=in_steps), context), {"FINISHED"})
            self.assertEqual((started, calc.create.call_count, calc.create_steps.call_count), ([], 2, 0))

            fake = operator(_creating=True, _project=project, _name="Mis acopios")  # Esc o un fallo al crearla
            with mock.patch.object(self.des_ops, "discard_calculation") as discard, \
                    mock.patch.object(self.panels, "show_summary") as show:
                cls._after_stop(fake, window)
                discard.assert_called_once_with()
                show.assert_called_once_with(None)
                self.assertFalse(fake._creating)
                cls._after_stop(fake, window)  # tras cancelar lo que sigue a crearla, nada: la detección está creada
                discard.assert_called_once_with()
            closed = operator(_creating=True, _project=project, _name="Mis acopios", _fail=mock.Mock(return_value={"CANCELLED"}))
            with mock.patch.object(self.des_ops.project_session, "current", return_value=None):
                self.assertEqual(cls._result(closed, window, progress("stockpile_store", 1, 2, "x")), {"CANCELLED"})
            self.assertEqual(closed._fail.call_args.args[1], "Se cerró el proyecto mientras se guardaba la detección «Mis acopios»: no queda nada a medias")

        step = progress("stockpile_store", 1, 2, "x")
        texts = {"es": ("Guardando la detección… 50 % · Esc: cancelar", "Poniendo al día las restricciones declaradas y las máscaras… 50 % · Esc: cancelar",
                        "Detectando los acopios… 50 % · Esc: cancelar",
                        "Creación cancelada: la detección no se ha creado y el cálculo se ha descartado; no queda nada a medias"),
                 "en": ("Saving the detection… 50 % · Esc: cancel", "Updating the declared constraints and the masks… 50 % · Esc: cancel",
                        "Detecting the stockpiles… 50 % · Esc: cancel",
                        "Creation cancelled: the detection has not been created and the calculation has been discarded; nothing has been left "
                        "half-done")}
        try:
            for language, (saving, chained, detecting, cancelled) in texts.items():
                self.i18n.set_language(language)
                with self.subTest(idioma=language):
                    self.assertEqual(cls._status_text(operator(_creating=True, _chain=False), step), saving)
                    self.assertEqual(cls._status_text(operator(_creating=False, _chain=True), step), chained)
                    self.assertEqual(cls._status_text(operator(_creating=False, _chain=False), step), detecting)
                    self.assertEqual(cls._cancelled_text(operator(_creating=True, _chain=False)), cancelled)
        finally:
            self.i18n.set_language("es")

    def test_z_disabling_geoblender_removes_the_orders(self) -> None:
        """Principio 8: desactivar Geoblender quita las tres órdenes nuevas (y deja el registro de la 013 como estaba)."""
        for idname in NEW:
            self.assertIsNotNone(self.registered(idname))
        blender_ext.release()
        for name in ("GEOBLENDER_OT_des_edit_stockpile", "GEOBLENDER_OT_des_detect_stockpiles", "GEOBLENDER_OT_des_stockpile_candidates"):
            self.assertIsNone(getattr(bpy.types, name, None), name)


if __name__ == "__main__":
    unittest.main()
