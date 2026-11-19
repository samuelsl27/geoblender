# SPDX-License-Identifier: GPL-3.0-or-later
"""Las órdenes de acopios con el proyecto de los acopios (spec 016, T35; HU-016-1, HU-016-4; RF-016-02, RF-016-08, RF-016-10, RF-016-23,
RF-016-25, RF-015-03, RF-015-05, RF-015-10, RF-015-18, RF-015-26, RF-015-28, RF-015-29; RNF-016-05; D-1, D-15; plan 016 §5.3.3; comprobación
manual M6), en ``blender -b`` y sin pantalla. Es un hito (P-13: proyecto en la rejilla de 2 m); el «verde» tiene
``test_stockpile_menu.py`` (el catálogo, el menú, el ``poll``) y ``tests/unit/design/test_declaring_operation.py``.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02) con el levantamiento de los acopios de
``milestone_stockpile_views`` (**tres** montones de 12 m de pie y 4 m de altura, a (16, 30), (44, 30) y (30, 46)), la capa de marcas de los dos
primeros (``nombre``), otra con ``nombre``, ``margen`` y ``material``, la de las zonas de coronación, el perfil ``EXPL_10_60_6`` y, en V01, una
plataforma «en corte» (``Terreno de V01``) cuya superficie es de la versión. Las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-016-25, D-3 (a): el diálogo de «Detectar acopios…» propone el nombre, la capa con sus campos y el terreno; sus umbrales vacíos son el valor
  por defecto y la petición no lleva ninguna cifra; los tecleados, sí; los enteros lo son.
- RF-016-02, RF-016-23, D-15 (b): **sin versión activa**, detectar sobre una superficie del proyecto: la vista previa de las marcas (se redibuja
  al cambiar un campo y se quita al cancelar y con Esc a mitad), «Calcular» no escribe nada, Esc responde en ≤ 2 s, «Crear» deja una detección
  **del proyecto** que no encadena nada.
- RF-016-02, RF-016-08, RF-015-10 (c): detectar sobre la superficie de una versión: la detección es de la versión y, tras crearla, **encadena**
  la declaración, las máscaras y la capa de entidades (una fila por acopio).
- RF-016-08, RF-016-10 (d): la lista de candidatos (huella, área y volumen; «Ir a»), convertir y descartar **con motivo**, que dejan la detección
  obsoleta y la recalculan; sin motivo, un candidato que no está, varias detecciones sin decir cuál y el proyecto en solo lectura no escriben nada.
- RF-015-28, RF-015-18, RF-016-23 (e): las órdenes de la 015 con la detección: vista previa, lo que se apoya en ella, la detección del proyecto
  seleccionada no se toma, no se inserta junto a ella, se trae a otra versión «sin calcular» y se descarta.
- RF-015-10, RF-015-29, D-1 (f): el contrafuerte que protege, en una versión **sin plataforma**, creado sin que corra lo que sigue (un Esc entre
  crear y declarar): el gancho de la declaración lo ve pendiente, las máscaras no están al día y lo que sigue lo recupera; su vista previa por entidad.
- RNF-016-03, RNF-016-05, RF-016-02 (g, h, i; T44): **«Crear» la detección corre por pasos** (``create_steps``: cada llamada del hilo de Blender, un paso
  del modal; la transacción final, la última) con **el mismo resultado, bit a bit**, que de una vez; **nada se escribe en el proyecto antes del último
  paso**; **Esc entre pasos no deja nada a medias** (ni operación, ni dato, ni temporal) y descarta el cálculo; y, en una versión, lo que sigue a crearla
  corre en el mismo modal, y un Esc ahí deja la detección creada y lo dice.

Se ejecuta con ``tools/run_blender_tests.py`` (es un hito: ``check.py --completo``).
"""

import json
import time
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import milestone_removal_ops as rem_ops
from tests.blender import milestone_stockpile_ce as ce
from tests.blender import milestone_stockpile_preview as sp_tests
from tests.blender import milestone_stockpile_views as views_tests
from tests.blender import test_platform_ops as platform_ops
from tests.support import step_modals
from tests.support.fake_layout import draw, operator_self

DETECT = "geoblender.des_detect_stockpiles"
CANDIDATES = "geoblender.des_stockpile_candidates"
FIELDS_LAYER = "gis_fea_marcas_con_campos"
FIELDS_MARKS = (("Acopio 1", (6.0, 20.0, 26.0, 40.0), 4.0, "mineral"), ("Acopio 2", (34.0, 20.0, 54.0, 40.0), None, "estéril"))
PROJECT_NAME, VERSION_NAME = "Acopios del proyecto", "Acopios de V01"
REASON = "Es un acopio de mineral que no estaba marcado"
MAX_TICKS = 600
TIMER = ce.TIMER
CREATED_PROJECT_TEXT = "Detección de acopios «{name}» creada en el proyecto"
CREATION_CANCELLED_TEXT = "Creación cancelada: la detección no se ha creado y el cálculo se ha descartado; no queda nada a medias"
CHAIN_CANCELLED_TEXT = ("Cancelado: la detección está creada; las restricciones declaradas y las máscaras se ponen al día antes de la siguiente "
                        "operación que las use, y la capa de entidades con la siguiente orden de entidades o «Recalcular lo obsoleto»")


class Rows:
    """Una colección de mentira (``CollectionProperty``): lo que llena el diálogo."""

    def __init__(self) -> None:
        self.items: list[Any] = []

    def clear(self) -> None:
        self.items.clear()

    def add(self) -> Any:
        row = SimpleNamespace(name="", label="", selected=True)
        self.items.append(row)
        return row

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Any:
        return iter(self.items)


class StockpileOpsTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con el mundo de los acopios."""

    survey_name: str
    surface_v01: str

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, ce.TERRAIN)):
            super().setUpClass()
        cls.survey_name = cls.write_grid("Levantamiento", views_tests.survey())
        cls.write_marks()
        cls.write_polygons(FIELDS_LAYER, tuple(box for _name, box, _margin, _material in FIELDS_MARKS),
                           tuple(name for name, *_rest in FIELDS_MARKS),
                           doubles={"margen": tuple(margin for _name, _box, margin, _material in FIELDS_MARKS)},
                           texts={"material": tuple(material for _name, _box, _margin, material in FIELDS_MARKS)})
        cls.write_polygons(sp_tests.CROWN_LAYER, tuple(box for _name, box in sp_tests.buttress_ops.CROWNS),
                           tuple(name for name, _box in sp_tests.buttress_ops.CROWNS))
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=sp_tests.buttress_ops.PROFILE, kind="ADOPTADO", source=sp_tests.buttress_ops.SOURCE, decided_by=platform_ops.PERSON,
            reason=platform_ops.REASON, scope="PROJECT", height="10", face="60", berm="6", anchor="125") == {"FINISHED"}
        cls.platform(name=ce.TERRAIN_NAME, feature=ce.TERRAIN[0], start=cls.survey_name, mode="CUT", reach="4")
        cls.surface_v01 = cls.dprov.dataset_name("psf", ce.TERRAIN_NAME)
        cls.refresh()
        cls.entity = platform_ops._module("bl.draw.entity")
        cls.scene_versions = platform_ops._module("bl.scene.versions")
        cls.stockpile_store = platform_ops._module("design.stockpile_store")
        cls.entity_store = platform_ops._module("design.entity_store")
        cls.dprovenance = platform_ops._module("design.provenance")
        cls.masks_access = platform_ops._module("gis.masks.access")
        cls.addClassCleanup(cls.entity.disable)

    write_marks = classmethod(rem_ops.RemoveStockpileTest.write_marks.__func__)  # type: ignore[attr-defined]
    write_polygons = classmethod(sp_tests.StockpilePreviewTest.write_polygons.__func__)  # type: ignore[attr-defined]
    platform = classmethod(ce.StockpileCETest.platform.__func__)  # type: ignore[attr-defined]
    tick = ce.StockpileCETest.tick

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (también las de los acopios y las del contrafuerte), leídas de nuevo (un guion no abre el diálogo)."""
        super().refresh()
        if cls.project.record is not None:
            cls.panels.refresh_removal_choices(cls.project)
            cls.panels.refresh_buttress_choices(cls.project)

    def tearDown(self) -> None:
        if self.entity.enabled():  # lo que deja una prueba que falla no pasa a la siguiente
            self.entity.disable()
        super().tearDown()

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(DETECT)

    @property
    def candidates_cls(self) -> Any:
        return self.commands.registered_class(CANDIDATES)

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo de «Detectar acopios…»: las dos marcas del levantamiento, con los candidatos (0,5 m de altura y 100 m² de
        área mínimos) y 3 m de margen; el montón sin marca sale como candidato."""
        return {"name": PROJECT_NAME, "surface": self.survey_name, "layer": rem_ops.MARKS_LAYER, "name_field": "nombre", "candidates": True,
                "margin_m": "3", "min_height_m": "0,5", "min_area_m2": "100", "in_steps": False, **values}

    def fake_dialog(self, **values: Any) -> Any:  # type: ignore[override]
        """El operador de mentira de «Detectar acopios…» con lo pedido (para ``invoke``, ``cancel`` y los ``update`` de sus campos)."""
        fields: dict[str, Any] = {
            "name": "", "surface": "", "layer": "", "name_field": "", "margin_field": "", "material_field": "", "base_field": "",
            "candidates": False, **{prop: "" for prop in self.des_ops._stockpile_fields() if prop.endswith(("_m", "_deg", "_m2", "rounds", "turns",
                                                                                                            "quantile"))},
            "confirm": False, "in_steps": False, "preview": False, "provenance_dialog": False, "report": lambda kind, text: None,
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        return operator_self(self.cls, **fields)

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{DETECT} no está en marcha")
        return found[0]

    def set_version(self, uid: str) -> None:
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=uid), {"FINISHED"})

    def detection_row(self, code: str, version: Any) -> Any:
        registry = (self.entities.project_registry(self.project) if version is None
                    else self.entities.registry(self.project, version.uid))
        return registry.get(code)

    def stored(self, family: str, name: str, version: Any) -> list[dict[str, Any]]:
        return list(self.stockpile_store.read_detection_table(self.project, family, name, version_uid="" if version is None else version.uid))

    def drive_recompute(self) -> Any:
        """Lleva hasta el final el «Recalcular lo obsoleto» que lanzó la orden (su modal y la cola de ``des``, avanzados a mano)."""
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "la orden no lanzó el recálculo")
        operator = found[0]
        self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
        with mock.patch.object(self.des_ops, "_ask_confirmation"), mock.patch.object(platform_ops._module("bl.ops.incorporation"), "status_text"):
            for _ in range(MAX_TICKS):
                state = operator.modal(bpy.context, TIMER)
                self.tick()
                if state != {"RUNNING_MODAL"}:
                    return operator
        self.fail("el recálculo no termina")

    # --- (a) El diálogo y la petición ---------------------------------------------------------

    def test_a_the_dialog_proposes_and_the_request_carries_no_mining_figure(self) -> None:
        """RF-016-25, RF-016-02, D-3 (M6): el diálogo propone un nombre que no repite el de ninguna entidad, la primera capa con **los campos que
        tiene** (``nombre``, ``margen``, ``material``; ``base``, no: no existe) y una superficie; **los umbrales vacíos no llevan ninguna cifra**
        (son su valor por defecto, que el dominio resuelve con su procedencia); los tecleados (con coma decimal) llegan tal cual y los enteros
        lo son; un entero que no lo es, un número que no lo es o una capa sin elegir, se rechazan nombrando el campo."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fake = self.fake_dialog()
        self.assertEqual(self.cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(fake.name, "Acopios")
        self.assertIn(fake.layer, [item[0] for item in self.panels.layer_items(None, None)])
        self.assertIn(fake.surface, [item[0] for item in self.panels.surface_items(None, None)])
        self.assertEqual(dialog.call_args.kwargs["title"], "Detectar acopios…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        for layer, wanted in ((FIELDS_LAYER, ("nombre", "margen", "material", "")), (rem_ops.MARKS_LAYER, ("nombre", "", "", ""))):
            with self.subTest(capa=layer):
                fake = self.fake_dialog(layer=layer, name_field="x", margin_field="x", material_field="x", base_field="x")
                self.des_ops._propose_mark_fields(fake, None)
                self.assertEqual((fake.name_field, fake.margin_field, fake.material_field, fake.base_field), wanted)
        request = self.cls._request(self.fake_dialog(name=" Mis acopios ", layer=FIELDS_LAYER, surface=self.survey_name, name_field="nombre"))
        self.assertEqual((request.name, request.surface, request.fields.layer, request.fields.name_field, request.candidates),
                         ("Mis acopios", self.survey_name, FIELDS_LAYER, "nombre", False))
        for name in ("margin_m", "crown_inner_m", "crown_outer_m", "crown_slope_deg", "crown_flat_min_m2", "max_residual_m", "fit_rounds",
                     "turns", "tilt_max_deg", "support_quantile", "open_diameter_m", "min_height_m", "min_area_m2", "max_area_m2"):
            self.assertIsNone(getattr(request, name), f"{name}: vacío es su valor por defecto, no una cifra de la orden")
        typed = self.cls._request(self.fake_dialog(layer=FIELDS_LAYER, surface=self.survey_name, name="N", margin_m="2,5", turns="3",
                                                    tilt_max_deg="5", candidates=True, min_area_m2=" 120 "))
        self.assertEqual((typed.margin_m, typed.turns, typed.tilt_max_deg, typed.min_area_m2, typed.candidates), (2.5, 3, 5.0, 120.0, True))
        for changes, text in (({"turns": "2,5"}, "no es un número entero"), ({"margin_m": "abc"}, "«abc» no es un número"),
                              ({"layer": "none"}, "Elija la capa de las marcas"), ({"name": " "}, "Escriba el nombre de la detección"),
                              ({"surface": "none"}, "Elija la superficie")):
            with self.subTest(cambios=changes), self.assertRaises(self.des_ops.ProfileFormError) as caught:
                self.cls._request(self.fake_dialog(**{"layer": FIELDS_LAYER, "surface": self.survey_name, "name": "N", **changes}))
            self.assertIn(text, str(caught.exception))

    # --- (b) Sobre una superficie del proyecto, sin versión activa -----------------------------

    def test_b_detecting_on_a_surface_of_the_project_without_an_active_version(self) -> None:
        """RF-016-02, RF-016-08, RF-016-23, RF-016-25, RF-015-29, RNF-016-05, D-15 (M6): **sin versión activa** la orden está activa y detecta
        sobre el levantamiento (del proyecto): «Vista previa» de las marcas (sin escribir nada ni crear objetos, se redibuja al cambiar un
        campo, se quita al cancelar), «Calcular» no escribe nada y deja el cálculo de ``des.stockpile_detect_project`` con los dos acopios y
        **un candidato**; Esc a mitad responde en ≤ 2 s, quita la vista previa y no deja nada; «Crear» deja una detección **del proyecto**
        (``STK-001``) y **no encadena** nada (no sale en ninguna capa de versión ni declara nada)."""
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.set_version("")
        self.assertIsNone(self.scene_versions.active_version())
        self.assertTrue(bpy.ops.geoblender.des_detect_stockpiles.poll())
        before, objects = self.state(), len(bpy.data.objects)

        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", preview=True, **self.form()), {"FINISHED"})
        self.assertTrue(self.entity.enabled())
        self.assertEqual((self.entity.plan().kind, self.entity.plan().stockpile.name), ("stockpile", PROJECT_NAME))
        self.assertEqual((self.state(), len(bpy.data.objects)), (before, objects), "la vista previa no escribe ni crea objetos")
        fake = self.fake_dialog(**self.form(margin_m="5"))
        self.des_ops._refresh_stockpile_preview(fake, None)
        self.assertEqual(self.entity.plan().stockpile.margin_m, 5.0, "cambiar un campo del diálogo la redibuja")
        fake.margin_m = "abc"
        self.des_ops._refresh_stockpile_preview(fake, None)
        self.assertEqual(self.entity.plan().stockpile.margin_m, 5.0, "un diálogo a medias no la cambia")
        self.cls.cancel(self.fake_dialog(), bpy.context)
        self.assertFalse(self.entity.enabled(), "cancelar la orden quita la vista previa")

        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", preview=True, **self.form()), {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", **self.form(in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running()  # en marcha (en este mundo de 2 m el cálculo cabe en un evento: Esc llega antes del primero)
        stopped = time.perf_counter()
        self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertLessEqual(time.perf_counter() - stopped, 2.0, "Esc responde en ≤ 2 s (RNF-016-05)")
        self.assertIsNone(modal._steps)
        self.assertIsNone(self.des_ops.calculation())
        self.assertFalse(self.entity.enabled(), "Esc a mitad quita la vista previa")
        self.assertEqual(self.state(), before, "Esc no deja nada")

        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", **self.form()), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertEqual(held.op_type, "des.stockpile_detect_project")
        self.assertEqual([item.key for item in held.outcome.stockpiles], ["Acopio 1", "Acopio 2"])
        self.assertEqual(len(held.outcome.states), 1, "el montón sin marca sale como candidato")
        self.assertEqual(self.state()[:4], before[:4], "calcular no escribe")
        operations = [row[0] for row in self.rows("SELECT op_type FROM gb_operation ORDER BY fid")]
        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        after = [row[0] for row in self.rows("SELECT op_type FROM gb_operation ORDER BY fid")]
        self.assertEqual(after, [*operations, "des.stockpile_detect_project"], "la del proyecto no encadena la declaración ni la capa")
        entry = self.detection_row("STK-001", None)
        self.assertEqual((entry.record.name, entry.record.state.value), (PROJECT_NAME, "current"))
        self.assertEqual([row["key"] for row in self.stored("stc", PROJECT_NAME, None)], ["c01"])
        self.assertIsNone(self.des_ops.calculation())

    # --- (c) Sobre la superficie de una versión -----------------------------------------------

    def test_c_detecting_on_a_surface_of_the_version_chains_what_follows(self) -> None:
        """RF-016-02, RF-016-08, RF-015-10, RF-016-25 (M6): con V01 activa y la superficie de la plataforma de V01, la detección es **de la
        versión** (``des.stockpile_detect``, ``STK-001`` de V01: el código es correlativo por ámbito) y, tras crearla, **encadena** la
        declaración de las restricciones, las máscaras y la capa de entidades, que lleva **una fila por acopio**."""
        self.set_version(self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles(
            "EXEC_DEFAULT", **self.form(name=VERSION_NAME, surface=self.surface_v01)), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertEqual(held.op_type, "des.stockpile_detect")
        operations = [row[0] for row in self.rows("SELECT op_type FROM gb_operation ORDER BY fid")]
        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        after = [row[0] for row in self.rows("SELECT op_type FROM gb_operation ORDER BY fid")]
        self.assertEqual(after[len(operations):][0], "des.stockpile_detect")
        self.assertIn("des.declare_constraints", after[len(operations):], "tras crearla, la declaración de las restricciones")
        self.assertEqual(after[-1], "des.entity_layer", "y la capa de entidades, la última")
        entry = self.detection_row("STK-001", self.v01)
        self.assertEqual((entry.record.name, entry.record.state.value), (VERSION_NAME, "current"))
        layer = [row[0] for row in self.rows("SELECT code FROM des_enl_v01 ORDER BY code")]
        self.assertEqual(layer, ["PLT-001", "STK-001#Acopio 1", "STK-001#Acopio 2"], "la capa de entidades, una fila por acopio")
        self.assertEqual(self.detection_row("STK-001", None).record.name, PROJECT_NAME, "la del proyecto sigue siendo otra")

    # --- (d) Los candidatos -------------------------------------------------------------------

    def test_d_the_candidates_are_listed_converted_and_discarded_with_a_reason(self) -> None:
        """RF-016-08, RF-016-10, RF-015-16 (M6): la lista de candidatos de la detección de V01 (con el estado de cada uno y «Ir a» con su
        lugar), convertirlo en acopio con su motivo deja la detección **obsoleta** y la repite: la decisión queda en el parámetro (con su
        decisor y su fecha) y el candidato sale como un acopio más; descartar el de la del proyecto, con el recálculo que lanza la orden;
        sin motivo, un candidato que no está, sin decir cuál de varias detecciones y en solo lectura, no se escribe nada."""
        cls = self.candidates_cls
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))

        def fake(**values: Any) -> Any:
            fields = {"detection": "STK-001", "in_project": False, "candidate": "", "action": "CONVERT", "reason": "", "recompute": False,
                      "rows": Rows(), "provenance_dialog": False, "report": lambda kind, text: said.append((kind, text))}
            return operator_self(cls, **{**fields, **values})

        said: list[tuple[Any, str]] = []
        before = self.state()
        with mock.patch.object(self.des_ops, "_selected_entity", return_value=("", "")):
            ambiguous = fake(detection="")
            self.assertEqual(cls.invoke(ambiguous, context, None), {"CANCELLED"})
            self.assertIn("más de una detección con candidatos", said[-1][1])
            dialog.assert_not_called()
        opened = fake()
        self.assertEqual(cls.invoke(opened, context, None), {"RUNNING_MODAL"})
        self.assertEqual((opened.detection, opened.in_project, opened.candidate), ("STK-001", False, "c01"))
        (row,) = self.stored("stc", VERSION_NAME, self.v01)
        self.assertEqual([(item.name, item.label.startswith("Candidato c01: huella de ")) for item in opened.rows], [("c01", True)])
        self.assertTrue(opened.rows.items[0].label.endswith("Pendiente"))
        self.assertEqual(dialog.call_args.kwargs["title"], f"Candidatos de «{VERSION_NAME}»")
        shown = draw(cls, bpy.context, detection="STK-001", in_project=False, candidate="c01", action="CONVERT", reason="", recompute=False,
                     rows=opened.rows, _listed=opened._listed)
        (place,) = [item for item in shown.of_kind("operator") if item.target == "geoblender.core_go_to_place"]
        self.assertEqual((float(place.properties.x), float(place.properties.y)), (row["x"], row["y"]), "«Ir a» lleva al centro del candidato")
        self.assertGreater(float(place.properties.radius), 0.0)
        self.assertEqual(self.state(), before, "abrir la lista no escribe")

        views = platform_ops._module("bl.ui.views")
        with mock.patch.object(views, "target_view3d", return_value=object()), mock.patch.object(views, "go_to", return_value=True) as go:
            self.assertEqual(bpy.ops.geoblender.des_stockpile_candidates("EXEC_DEFAULT", detection="STK-001", candidate="c01", action="GO_TO"),
                             {"FINISHED"})
        self.assertEqual((go.call_args.args[2], go.call_args.args[3]), (row["x"], row["y"]))
        self.assertEqual(self.state(), before, "«Ir a» no cambia nada")

        for changes, text in (({"reason": ""}, "Escriba el motivo"), ({"reason": " ", "candidate": "c01"}, "Escriba el motivo"),
                              ({"reason": REASON, "candidate": "c99"}, "«c99» no es un candidato"), ({"reason": REASON, "candidate": ""}, "Elija el candidato"),
                              ({"reason": REASON, "candidate": "c01", "detection": "NO-EXISTE"}, "no es una detección de acopios")):
            with self.subTest(cambios=changes), self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.des_stockpile_candidates("EXEC_DEFAULT", **{"detection": "STK-001", "candidate": "c01", "action": "CONVERT",
                                                                              "recompute": False, **changes})
            self.assertIn(text, str(caught.exception))
        self.assertEqual(self.state(), before, "los rechazos no escriben nada")
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(bpy.ops.geoblender.des_stockpile_candidates.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_stockpile_candidates("EXEC_DEFAULT", detection="STK-001", candidate="c01", action="CONVERT", reason=REASON)
        self.assertEqual(self.state(), before)

        self.assertEqual(bpy.ops.geoblender.des_stockpile_candidates(
            "EXEC_DEFAULT", detection="STK-001", candidate="c01", action="CONVERT", reason=REASON, recompute=False), {"FINISHED"})
        self.assertEqual(self.detection_row("STK-001", self.v01).record.state.value, "stale", "decidir deja la detección obsoleta")
        key = self.entity_store.entity_key("STK-001", "decisions") if hasattr(self.entity_store, "entity_key") else "des.stockpile.stk_001.decisions"
        stored = self.entity_store.entity_parameters(self.project, "STK-001", version=self.scene_versions.active())
        decisions = json.loads(stored["decisions"])["decisions"]
        self.assertEqual([(item["key"], item["state"], item["reason"], item["decided_by"]) for item in decisions],
                         [("c01", "converted", REASON, self.project.session.user_host)], key)
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_stockpile_candidates(
                "EXEC_DEFAULT", detection="STK-001", candidate="c01", action="ASK", reason="Se vuelve a preguntar", recompute=False),
                {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.des_stockpile_candidates(
                "EXEC_DEFAULT", detection="STK-001", candidate="c01", action="CONVERT", reason=REASON, recompute=True), {"FINISHED"})
            self.drive_recompute()
        self.assertEqual(self.detection_row("STK-001", self.v01).record.state.value, "current", "la orden recalcula la detección")
        self.assertEqual([item["key"] for item in self.stored("stk", VERSION_NAME, self.v01)], ["Acopio 1", "Acopio 2", "c01"],
                         "el candidato convertido sale como un acopio más")
        self.assertEqual([(item["key"], item["state"], item["reason"]) for item in self.stored("stc", VERSION_NAME, self.v01)],
                         [("c01", "converted", REASON)])

        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_stockpile_candidates(
                "EXEC_DEFAULT", detection="STK-001", in_project=True, candidate="c01", action="DISCARD", reason="Es una escombrera antigua",
                recompute=True), {"FINISHED"})
            self.drive_recompute()
        self.assertEqual([(item["key"], item["state"], item["reason"]) for item in self.stored("stc", PROJECT_NAME, None)],
                         [("c01", "discarded", "Es una escombrera antigua")], "la del proyecto, aparte de la de V01")
        self.assertEqual([item["key"] for item in self.stored("stk", PROJECT_NAME, None)], ["Acopio 1", "Acopio 2"])
        self.assertEqual(self.detection_row("STK-001", None).record.state.value, "current")

    # --- (e) Las órdenes de la 015 con la detección -------------------------------------------

    def test_e_the_entity_commands_work_with_a_detection(self) -> None:
        """RF-015-28, RF-015-18, RF-015-05, RF-016-23 (M6): con la detección de V01, «Vista previa» (por su código) reconstruye las marcas de
        sus ajustes, «Lo que se apoya en ella» la lista, la detección **del proyecto** seleccionada no se toma, «Insertar antes o después
        de…» no ofrece la detección (no tiene cadena), «Traer las entidades de…» la trae a V02 **sin calcular** (sus parámetros de su familia,
        sin ``start``), «Calcular…» no ofrece lo que no es una plataforma y «Descartar…» la descarta."""
        self.set_version(self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="STK-001"), {"FINISHED"})
        self.assertEqual((self.entity.plan().kind, self.entity.plan().stockpile.name, self.entity.plan().stockpile.fields.layer),
                         ("stockpile", VERSION_NAME, rem_ops.MARKS_LAYER))
        self.assertEqual(self.entity.plan().stockpile.fields.name_field, "nombre")
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT"), {"FINISHED"}, "el mismo control la quita")
        self.assertFalse(self.entity.enabled())

        said: list[tuple[Any, str]] = []
        dependents = operator_self(platform_ops._module("bl.ops.des").GEOBLENDER_OT_des_entity_dependents, entity="STK-001",
                                   report=lambda kind, text: said.append((kind, text)))
        self.assertEqual(self.des_ops.GEOBLENDER_OT_des_entity_dependents.execute(dependents, bpy.context), {"FINISHED"})
        self.assertTrue(any("Acopios de V01" in text for _kind, text in said), said)

        with mock.patch.object(self.des_ops, "_selected_entity", return_value=("STK-001", "")):
            for idname in ("des_entity_dependents", "des_entity_preview"):
                with self.subTest(orden=idname), self.assertRaises(RuntimeError) as caught:
                    getattr(bpy.ops.geoblender, idname)("EXEC_DEFAULT")
                self.assertIn("es del proyecto, no de una versión", str(caught.exception))
            discard = operator_self(self.des_ops.GEOBLENDER_OT_des_entity_discard, entity="", reason="", provenance_dialog=False, in_steps=False,
                                    report=lambda kind, text: said.append((kind, text)))
            self.assertEqual(self.des_ops.GEOBLENDER_OT_des_entity_discard.invoke(discard, SimpleNamespace(window=None), None), {"CANCELLED"})
            self.assertIn("es del proyecto, no de una versión", said[-1][1])
        self.assertEqual(self.detection_row("STK-001", None).record.state.value, "current", "la del proyecto no se tocó")

        insert = operator_self(self.des_ops.GEOBLENDER_OT_des_entity_insert, reference="", placement="AFTER", references=Rows(),
                               provenance_dialog=False, report=lambda kind, text: said.append((kind, text)))
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        self.assertEqual(self.des_ops.GEOBLENDER_OT_des_entity_insert.invoke(
            insert, SimpleNamespace(window=platform_ops.window(), window_manager=SimpleNamespace(invoke_props_dialog=dialog)), None),
            {"RUNNING_MODAL"})
        self.assertEqual([item.name for item in insert.references], [ce.TERRAIN_NAME], "la detección no tiene cadena: no se ofrece")

        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.set_version(self.v02.uid)
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="STK-001"), {"FINISHED"})
        brought = self.detection_row("STK-001", self.v02)
        self.assertEqual((brought.record.name, brought.record.kind, brought.record.state.value, brought.operation_uid),
                         (VERSION_NAME, "stockpile", "uncalculated", None), "traída sin calcular")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' ESCAPE '!'", self.v02.uid), [(0,)])
        calculate = operator_self(self.des_ops.GEOBLENDER_OT_des_entity_calculate, entity="", candidates=Rows(), provenance_dialog=False,
                                  report=lambda kind, text: said.append((kind, text)))
        self.assertEqual(self.des_ops.GEOBLENDER_OT_des_entity_calculate.invoke(
            calculate, SimpleNamespace(window=platform_ops.window(), window_manager=SimpleNamespace(invoke_props_dialog=dialog)), None),
            {"CANCELLED"})
        self.assertIn("no tiene ninguna entidad sin resultado", said[-1][1], "solo una plataforma se calcula desde «Calcular…»")
        self.assertEqual(bpy.ops.geoblender.des_entity_discard(
            "EXEC_DEFAULT", entity="STK-001", reason="Se trajo por error", in_steps=False), {"FINISHED"})
        self.assertEqual(self.detection_row("STK-001", self.v02).record.state.value, "discarded")
        self.assertEqual(self.detection_row("STK-001", self.v01).record.state.value, "current", "la de V01 no se tocó")

    # --- (f) El contrafuerte que protege, en una versión sin plataforma -----------------------

    def test_f_a_buttress_alone_in_a_version_is_recovered_by_the_declaration_hook(self) -> None:
        """RF-015-10, RF-015-29, D-1 (decisión del 19/11/2026): en V02, que **no tiene ninguna plataforma**, un contrafuerte que protege creado
        **sin que corra lo que sigue** (lo que deja un Esc entre crearlo y declararlo) deja su restricción **por declarar**: el gancho de la
        declaración lo ve pendiente (``entity_store`` y ``bl``), las máscaras no están al día y **lo que sigue lo recupera**; antes de generalizar el
        gancho, la versión sin plataforma daba las máscaras por buenas sin la restricción «sin corte». Su vista previa por entidad reconstruye la
        zona de coronación."""
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.set_version(self.v02.uid)
        self.refresh()
        form = {**sp_tests.FIELDS, "name": "Contrafuerte de V02", "start": self.ground, "in_steps": False}
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **form), {"FINISHED"})
        with mock.patch.object(self.des_ops.GEOBLENDER_OT_des_add_buttress, "_update_declared", return_value={"FINISHED"}):  # el Esc
            self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        with self.project.read() as conn:
            self.assertFalse(self.dprovenance.has_platform_operation(conn, self.v02.uid), "V02 no tiene ninguna plataforma")
            self.assertTrue(self.dprovenance.has_declaring_operation(conn, self.v02.uid))
            self.assertTrue(self.entity_store.declaration_pending(self.project, conn, self.v02.uid), "la restricción está por declarar")
            self.assertTrue(self.des_ops._declaration_pending(self.project, conn, self.v02.uid), "el gancho de bl, también")
        state, _causes = self.masks_access.mask_state(self.project, self.v02.uid)
        self.assertNotEqual(state, self.masks_access.MaskState.CURRENT, "las máscaras no están al día sin su restricción")
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="BTR-001"), {"FINISHED"})
        self.assertEqual((self.entity.plan().kind, self.entity.plan().buttress.name, self.entity.plan().buttress.crown_m),
                         ("buttress", "Contrafuerte de V02", 115.0), "la zona de coronación, de sus ajustes y sus parámetros vigentes")
        self.entity.disable()
        for _step in self.entity_store.after_entity_change(self.project, self.v02.uid):
            pass
        with self.project.read() as conn:
            self.assertFalse(self.entity_store.declaration_pending(self.project, conn, self.v02.uid), "lo que sigue la recupera")
        state, _causes = self.masks_access.mask_state(self.project, self.v02.uid)
        self.assertEqual(state, self.masks_access.MaskState.CURRENT)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.declare_constraints' AND status = 'done' "
                                   "AND superseded_by IS NULL AND uid IN (SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r "
                                   "ON r.uid = o.revision_uid WHERE r.version_uid = ?)", self.v02.uid), [(1,)])

    # --- (g, h, i) «Crear» por pasos (T44) ---------------------------------------------------

    def calculate_detection(self, name: str, **values: Any) -> Any:
        """«Calcular» una detección sin candidatos (desde un guion: de una vez) y su cálculo abierto."""
        form = self.form(name=name, candidates=False, **values)
        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", **form), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def start_creating(self) -> Any:
        """«Crear» el cálculo abierto desde la interfaz (``confirm`` con la ventana): empieza el modal de pasos, con un paso por evento."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
        modal = self.running()
        modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
        self.addCleanup(lambda: modal._steps is None or modal.cancel(bpy.context))
        return modal

    def code_of(self, name: str, version: Any) -> str:
        """El código de la detección ``name`` de la versión ``version`` (``None``: del proyecto)."""
        registry = (self.entities.project_registry(self.project) if version is None else self.entities.registry(self.project, version.uid))
        (found,) = [entry.record.code for entry in registry if entry.record.name == name]
        return found

    def outputs(self, name: str, version: Any) -> list[tuple[str, str]]:
        """Lo que escribió la operación vigente de la detección ``name``: ``(papel, hash del contenido)`` de cada salida, en su orden."""
        uid = self.detection_row(self.code_of(name, version), version).operation_uid
        return [(role, sha) for role, sha in self.rows(
            "SELECT io.role, d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def figures_of(self, name: str, version: Any) -> list[float]:
        """Las cifras de la operación vigente de la detección ``name``, ordenadas."""
        uid = self.detection_row(self.code_of(name, version), version).operation_uid
        return sorted(value for (value,) in self.rows("SELECT value FROM gb_figure WHERE operation_uid = ?", uid))

    def test_g_creating_runs_by_steps_with_the_result_of_creating_at_once_and_writes_nothing_before_the_last_step(self) -> None:
        """RNF-016-03, RF-016-02, RF-015-02, RF-015-29 (T44): «Crear» la detección **del proyecto** desde la interfaz (``confirm`` con
        ventana) ya no es una sola llamada: la orden empieza el modal de pasos de ``Calculation.create_steps`` (**más de 10 eventos** con un
        paso por evento, cada uno **≤ 0,2 s** de CPU) y **no escribe nada en el proyecto antes del último** (solo ficheros temporales); el último
        registra la detección (una transacción), el informe lo dice y el cálculo deja de estar abierto. **El resultado es el de crear de una vez
        desde un guion** (``in_steps=False``): los mismos papeles y hashes de contenido de cada salida, las mismas cifras y las mismas filas de
        la tabla de acopios (salvo el código de la entidad)."""
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.set_version("")
        self.calculate_detection("Acopios de una vez")
        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())

        self.calculate_detection("Acopios por pasos")
        before = self.state()
        modal = self.start_creating()
        self.assertTrue(self.des_ops.calculation().open, "mientras crea, el cálculo sigue abierto")
        events, longest = 0, 0.0
        for events in range(1, step_modals.MAX_EVENTS):
            started = time.process_time()
            state = modal.modal(bpy.context, TIMER)
            longest = max(longest, time.process_time() - started)
            if state != {"RUNNING_MODAL"}:
                break
            self.assertEqual(self.state()[:4], before[:4], f"el evento {events} escribió en el proyecto antes del último paso")
        self.assertEqual(state, {"FINISHED"})
        self.assertGreater(events, 10, "por pasos: más de 10 eventos")
        self.assertLessEqual(longest, 0.2, f"la llamada más larga, {longest:.3f} s de CPU, de {events}")
        self.assertIn(CREATED_PROJECT_TEXT.format(name="Acopios por pasos"), list(modal.report_log))
        self.assertIsNone(self.des_ops.calculation())
        self.assertIsNone(modal._steps)
        self.assertEqual(self.panels.view().summary_title, "", "el resumen se vacía al crearla")
        self.assertEqual(self.detection_row(self.code_of("Acopios por pasos", None), None).record.state.value, "current")
        self.assertEqual([name for name in self.names() if ".tmp" in name], [], "ningún temporal")

        once, steps = self.outputs("Acopios de una vez", None), self.outputs("Acopios por pasos", None)
        self.assertEqual([role for role, _sha in steps], [role for role, _sha in once])
        self.assertGreaterEqual(len(steps), 6, "la tabla de acopios, la de candidatos, las cuatro rejillas dispersas y el informe")
        rasters = {"stockpile_base", "stockpile_thickness", "stockpile_ground", "stockpile_surface"}
        self.assertEqual({role for role, _sha in steps} & rasters, rasters)
        self.assertEqual([item for item in steps if item[0] in rasters], [item for item in once if item[0] in rasters],
                         "las rejillas dispersas, con los mismos hashes de contenido: bit a bit")
        self.assertEqual(self.figures_of("Acopios por pasos", None), self.figures_of("Acopios de una vez", None))
        for family in ("stk", "stc", "prp"):  # las tablas llevan el código de su entidad: lo demás, igual
            got = [{key: value for key, value in row.items() if key != "code"} for row in self.stored(family, "Acopios por pasos", None)]
            wanted = [{key: value for key, value in row.items() if key != "code"} for row in self.stored(family, "Acopios de una vez", None)]
            self.assertEqual(got, wanted, family)
        self.assertEqual([row["key"] for row in self.stored("stk", "Acopios por pasos", None)], ["Acopio 1", "Acopio 2"])

    def test_h_esc_between_the_steps_of_creating_leaves_nothing_half_done_and_discards_the_calculation(self) -> None:
        """RNF-016-05, RF-015-29, RF-016-02 (T44): Esc **entre los pasos de «Crear»** —cuando ya hay ficheros temporales— responde en ≤ 2 s, deja
        el proyecto **como estaba** (ni operación, ni dato, ni parámetro, ni cifra, ni temporal), descarta el cálculo (el resumen se vacía y se
        dice: hay que volver a calcular) y se puede calcular y crear de nuevo."""
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.set_version("")
        self.calculate_detection("Acopios cancelados")
        before = self.state()
        modal = self.start_creating()
        for _ in range(step_modals.MAX_EVENTS):
            self.assertEqual(modal.modal(bpy.context, TIMER), {"RUNNING_MODAL"}, "acabó antes de Esc")
            if any(".tmp" in name for name in self.names()):
                break
        else:
            self.fail("«Crear» no llegó a escribir un temporal")
        self.assertEqual(self.state()[:4], before[:4])
        stopped = time.perf_counter()
        self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertLessEqual(time.perf_counter() - stopped, 2.0, "Esc responde en ≤ 2 s (RNF-016-05)")
        self.assertIn(CREATION_CANCELLED_TEXT, list(modal.report_log))
        self.assertIsNone(modal._steps)
        self.assertIsNone(self.des_ops.calculation(), "el cálculo está descartado")
        self.assertEqual(self.panels.view().summary_title, "", "y su resumen, vaciado")
        self.assertEqual(self.state(), before, "Esc no deja nada: ni operación, ni dato, ni temporal")
        self.assertFalse(self.entity.enabled())
        self.calculate_detection("Acopios cancelados")
        self.assertEqual(bpy.ops.geoblender.des_detect_stockpiles("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertEqual(self.detection_row(self.code_of("Acopios cancelados", None), None).record.state.value, "current")

    def test_i_in_a_version_what_follows_creating_runs_in_the_same_modal_and_an_esc_there_keeps_the_detection(self) -> None:
        """RNF-016-03, RNF-016-05, RF-015-10, RF-015-29 (T44): la detección **de una versión** creada por pasos encadena lo que sigue (la
        declaración, las máscaras y la capa de entidades) **en el mismo modal**: sus fases son primero las de guardar y después las de
        ponerla al día, y al acabar la capa tiene una fila por acopio. Un Esc **ya creada** —en lo que sigue— deja la detección creada, dice
        que lo está y la capa sin sus filas hasta que lo que sigue se hace de nuevo."""
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.set_version(self.v01.uid)
        self.calculate_detection("Acopios por pasos en V01", surface=self.surface_v01)
        self.assertEqual(self.des_ops.calculation().op_type, "des.stockpile_detect")
        modal = self.start_creating()
        state, events = step_modals.drive(modal, bpy.context)
        self.assertEqual(state, {"FINISHED"})
        self.assertGreater(events, 10)
        phases = [phase for _clock, phase, _done, _total, _message in modal.progress_log]
        saved = [index for index, phase in enumerate(phases) if phase == "stockpile_store"]
        self.assertTrue(saved and saved[-1] < len(phases) - 1, "primero guardar y después lo que sigue")
        self.assertEqual([row[0] for row in self.rows("SELECT op_type FROM gb_operation ORDER BY fid")][-1], "des.entity_layer")
        code = self.code_of("Acopios por pasos en V01", self.v01)
        layer = [row[0] for row in self.rows("SELECT code FROM des_enl_v01 ORDER BY code") if row[0].startswith(f"{code}#")]
        self.assertEqual(layer, [f"{code}#Acopio 1", f"{code}#Acopio 2"], "la capa de entidades, una fila por acopio")

        self.calculate_detection("Acopios cortados en V01", surface=self.surface_v01)
        done = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.stockpile_detect' AND status = 'done'")[0][0]
        modal = self.start_creating()
        for _ in range(step_modals.MAX_EVENTS):
            self.assertEqual(modal.modal(bpy.context, TIMER), {"RUNNING_MODAL"}, "acabó antes de Esc")
            if self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.stockpile_detect' AND status = 'done'")[0][0] > done:
                break
        else:
            self.fail("«Crear» no llegó a registrar la detección")
        code = self.code_of("Acopios cortados en V01", self.v01)
        self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertIn(CHAIN_CANCELLED_TEXT, list(modal.report_log))
        self.assertEqual(self.detection_row(code, self.v01).record.state.value, "current", "la detección está creada")
        self.assertNotIn(f"{code}#Acopio 1", [row[0] for row in self.rows("SELECT code FROM des_enl_v01")], "y la capa aún no tiene sus filas")
        self.assertIsNone(self.des_ops.calculation())
        for _step in self.entity_store.after_entity_change(self.project, self.v01.uid):
            pass
        self.assertIn(f"{code}#Acopio 1", [row[0] for row in self.rows("SELECT code FROM des_enl_v01")], "lo que sigue la recupera")


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(StockpileOpsTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
