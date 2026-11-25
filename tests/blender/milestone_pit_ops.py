# SPDX-License-Identifier: GPL-3.0-or-later
"""«Nueva corta…» en Blender (spec 018, T31; HU-018-1, HU-018-3; RF-018-34, RF-018-35, RF-018-19, RF-018-32, RF-015-28; plan 018 §5.3.3 y §5.5; comprobación manual M1).

:class:`GEOBLENDER_OT_des_create_pit` (``geoblender.des_create_pit``, de ``bl/ops/des_pit.py``) calcula con ``design.steps.pit_run`` la operación ``des.pit`` de la versión activa y, al
confirmar, la crea. Su diálogo pide el nombre y el modo; la capa de origen y sus campos; los perfiles (el base y los de cada sector), la roseta y los bancos por berma; las rampas, las
zonas sin rampa y los bancos fijados; los criterios de parada; la partida y el apoyo; y las tolerancias, cada una con su tipo. Calcular, Crear, Cancelar y Esc son los de las demás
órdenes (``_CalculateAndCreate``): nada se registra hasta «Crear». Con la pendiente media de una rampa por encima de pm no se crea sin la confirmación expresa y su motivo.

El proyecto es el del hito H2 (``milestone_pit_h2.py``: 400 × 400 m con celdas de 2 m, V01 a V03, los perfiles de banco y de pista, la roseta, la espiral y el zig-zag, los sectores y
las capas), al que se le añade un perfil de pista con pm = 5 % y una espiral con él (la media de 8 % la pasa). Las pruebas, en el orden de sus letras sobre el mismo estado.

- RF-018-34, RF-015-28 (a): la orden es real, del catálogo, de ``des.pit``; sus propiedades tienen nombre y descripción en español y los decimales son texto; el diálogo propone el nombre,
  la capa, el perfil y la partida y cabe en 32 filas.
- RF-018-01, RF-018-06 a 09, RF-018-13 (b): lo pedido en el diálogo es lo que arma ``PitRequest``: los perfiles, la roseta, los sectores, las rampas, las capas, los criterios de parada y
  las tolerancias; los textos sin sentido y lo que falta se rechazan con el campo.
- RF-018-03, RF-015-03, RF-015-02 (c): Calcular deja el cálculo abierto con su resumen y nada en el proyecto; Crear registra ``des.pit`` con sus datos y encadena la capa de entidades y las
  capas de la corta.
- RF-018-19 (d): la pendiente media de la rampa por encima de pm no se crea sin la confirmación expresa ni sin su motivo; con ellos se crea y queda en los ajustes.
- RF-015-18, RF-018-34 (j): una corta traída a otra versión se calcula desde «Calcular…» del menú «Entidad ▾» con su código y se crea al día.
- RF-018-35, RF-015-29, RF-018-04 (e): Esc a mitad, Cancelar la confirmación y lo que se rechaza no dejan nada.
- RF-018-32, RF-015-26 (f): «Vista previa» y sus campos; tras calcular, le da lo calculado; se quita al cancelar y al crear.
- RF-018-34, RF-015-28 (h): la orden sale desactivada con su motivo con el proyecto en solo lectura.
- RF-018-35 (i): «Crear» por pasos (la vía de la interfaz) deja la corta y quita la vista previa en cuanto lo guardado llega.
- Principio 8 (z): desactivar Geoblender quita la orden y el cálculo abierto y la vista previa.

Se ejecuta con ``tools/run_blender_tests.py`` (paso «hito» de ``tools/check.py --completo``).
"""

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import milestone_pit_h2 as h2
from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, dialog_height, step_modals
from tests.support.fake_layout import draw, operator_self

PIT = "geoblender.des_create_pit"
PIT_CLASS = "GEOBLENDER_OT_des_create_pit"
PIT_TYPE = "des.pit"
PERSON = h2.PERSON
REASON = "Prueba de la orden «Nueva corta…»"
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
HIDDEN = ("confirm", "in_steps", "preview", "confirm_mean", "code", "show_more")
PROPERTIES = frozenset({
    "name", "mode", "layer", "name_pick", "level_pick", "name_field", "level_field", "start", "support", "profile", "rose", "n_berm", "sector_profiles", "sector_roses", "sector_n_berm", "ramps",
    "noramp", "fixed", "fixed_field", "top_level", "bottom_level", "max_benches", "min_floor_width", "corner", "arc_tol", "simplify", "close_radius", "az_window", "mean_reason"})
STRINGS = ("level_field", "n_berm", "sector_profiles", "sector_roses", "sector_n_berm", "fixed_field", "top_level", "bottom_level", "max_benches", "min_floor_width", "arc_tol",
           "simplify", "close_radius", "az_window")
"""Las propiedades de texto: los decimales (regla 4: nada de float32) y las listas de sector."""
MAX_ROWS = 32
STRONG = "PISTA_MEDIA"
STRONG_RAMP = "Espiral con pm de 5"


class PitOpsTest(unittest.TestCase):
    """El proyecto del hito H2 con la extensión habilitada, para toda la clase."""

    names = platform_ops.CreatePlatformTest.names
    state = platform_ops.CreatePlatformTest.state

    @classmethod
    def setUpClass(cls) -> None:
        h2.PitH2Test.setUpClass.__func__(cls)  # type: ignore[attr-defined]
        cls.commands = h2._module("bl.ui.commands")
        cls.panels = h2._module("bl.ui.des_panels")
        cls.core_ops = h2._module("bl.ops.core")
        cls.des_pit = h2._module("bl.ops.des_pit")
        cls.view = cls.panels.view()
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        by_hand = {"source": h2.SOURCE, "decided_by": PERSON, "reason": REASON}
        profiles = cls.road_profiles
        profiles.edit_road_profiles(cls.project, (profiles.ProfileEdit(name="PISTA MEDIA", values={**h2.ROAD_PROFILE_VALUES, "min_radius_m": 7.0, "max_mean_gradient_pct": 5.0}),),
                                    profiles.ProfileDeclaration(**by_hand))
        spiral = {"type": "spiral", "sense": "ccw", "start": "fondo", "gradient_pct": 8.0, "road_profile": "pista_media", "transition_m": 0.0}
        cls.strong = cls.pit_ramp_def.edit_pit_ramps(cls.project, [cls.pit_ramp_def.RampEdit(name=STRONG_RAMP, values=spiral)], cls.pit_rose.Declaration(**by_hand)).created[0]
        cls.close_search("sector_3")  # el de la franja sur: sin su búsqueda ninguna corta que lo toque se calcula (CE-018-08, ya cubierto por el hito H2)
        cls.compile_masks()
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        """Las listas del diálogo, leídas de nuevo del proyecto (lo que hace ``invoke``)."""
        cls.panels.refresh_choices(cls.project)
        cls.panels.refresh_platform_choices(cls.project)
        cls.des_pit.refresh_pit_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    @property
    def pit(self) -> Any:
        return self.commands.registered_class(PIT)

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo para la corta circular ascendente sobre el terreno ``llano``: el fondo circular, el perfil ``EXPL_10_60_6`` y las tolerancias de la prueba."""
        return {"name": "Corta de la orden", "mode": "UP", "layer": h2.FLOORS, "name_field": "nombre", "level_field": "cota_m", "profile": h2.EXPL.lower(),
                "start": self.terrain["llano"], "arc_tol": "0,05", "simplify": "0,05", "in_steps": False, **values}

    def calculate_pit(self, form: dict[str, Any]) -> Any:
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **form), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create_pit(self, **values: Any) -> set[str]:
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", confirm=True, in_steps=False, **values)

    def fake(self, **values: Any) -> Any:
        """El operador de mentira con todas las propiedades del diálogo en su valor por defecto y lo que se dé."""
        shown: dict[str, Any] = {"name": "Corta", "mode": "UP", "layer": h2.FLOORS, "name_pick": "none", "level_pick": "none", "name_field": "", "level_field": "", "start": self.terrain["llano"], "support": "none",
                                 "profile": "none", "rose": "none", "n_berm": "", "sector_profiles": "", "sector_roses": "", "sector_n_berm": "", "ramps": set(),
                                 "noramp": "none", "fixed": "none", "fixed_field": "", "top_level": "", "bottom_level": "", "max_benches": "", "min_floor_width": "",
                                 "corner": "DEFAULT", "arc_tol": "", "simplify": "", "close_radius": "", "az_window": "", "mean_reason": "", "confirm": False,
                                 "in_steps": False, "preview": False, "confirm_mean": False, "code": "", "show_more": False}
        properties = values.pop("properties", SimpleNamespace(is_property_set=lambda name: False))
        return operator_self(self.pit, report=lambda kind, text: None, properties=properties, **{**shown, **values})

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.pit) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{PIT} no está en marcha")
        return found[0]

    def summary(self) -> list[tuple[str, bool]]:
        return [(line.name, bool(line.alert)) for line in self.view.summary]

    # --- a: la orden, el diálogo y la propuesta -----------------------------------------------

    def test_a_the_command_its_dialog_and_the_proposal(self) -> None:
        """RF-018-34, RF-015-28, RF-018-01 (plan §5.3.3, §5.5; M1): «Nueva corta…» es una orden real de ``des.pit`` con la puerta de la procedencia y los pasos con Esc; es del catálogo,
        con su casa en Diseño ▸ Corta por bancos; sus propiedades tienen nombre y descripción en español y los decimales son texto; su diálogo propone el nombre, la capa, el perfil y la
        partida y dibuja todos los campos en **≤ 32 filas**."""
        cls = self.pit
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_pit.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertTrue(issubclass(cls, self.des_ops._ChainsEntityLayer))
        self.assertTrue(issubclass(cls, self.des_ops._ClearsEntityPreview))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options), (PIT, PIT_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.PIT_COMMAND, PIT)
        self.assertIn(PIT, self.dprov.OPERATION_TYPES_BY_NAME[PIT_TYPE].commands)
        command = self.commands.catalog().commands[PIT]
        self.assertEqual((command.label_es, command.module, command.kind), ("Nueva corta…", "des", "operator"))
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, PROPERTIES)
        for prop in sorted(PROPERTIES):  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertTrue(keywords["name"] and keywords["description"])
                self.assertNotEqual(keywords["name"], "")
        for prop in HIDDEN:  # las pone quien la lanza: sin nombre ni descripción (salvo «Más opciones», que se ve y tiene su tooltip: T40f)
            if prop == "show_more":
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual(keywords["name"], "Más opciones")
                self.assertTrue(keywords["description"] and "show_more" not in keywords["description"])
                continue
            self.assertNotIn("name", cls.__annotations__[prop].keywords)
        for prop in STRINGS:
            self.assertIs(cls.__annotations__[prop].function, bpy.props.StringProperty, prop)

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        proposal = self.fake(name="", layer="", profile="none", start="")
        self.assertEqual(cls.invoke(proposal, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Nueva corta…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(proposal.in_steps)
        offered = [identifier for identifier, _label, _about in self.panels.platform_start_items(None, None)]
        self.assertEqual(proposal.name, "Corta 1")
        self.assertTrue(proposal.layer.startswith("gis_fea_h2_"))
        self.assertNotEqual(proposal.profile, "none", "propone el primer perfil de banco")
        self.assertIn(proposal.start, offered)
        self.assertFalse(proposal.start.startswith("entity:"), "sin entidades ni cantera, el terreno")
        given = self.fake(name="Mía", layer=h2.FLOORS_SQUARE, start=self.terrain["cuadrado"],
                          properties=SimpleNamespace(is_property_set=lambda name: name in ("layer", "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.layer, given.start), ("Mía", h2.FLOORS_SQUARE, self.terrain["cuadrado"]), "lo dado no cambia")

        shown = draw(cls, bpy.context, **{**self.fake().__dict__, "mode": "UP"})
        texts = draw(cls, bpy.context, **{**self.fake().__dict__, "mode": "UP", "show_more": True}).texts()  # los campos plegados, desplegados (test_a2)
        for heading in ("Nombre", "Modo", "Capa de origen", "Campo del nombre", "Campo de cota", "Perfil de banco", "Roseta de taludes", "Bancos por berma", "Perfiles por sector",
                        "Rosetas por sector", "Rampas", "Zonas sin rampa", "Bancos fijados", "Superficie de partida", "Superficie de apoyo", "Vista previa",
                        "Tolerancia del arco (m)", "Tolerancia de simplificación (m)"):
            self.assertIn(heading, texts)
        self.assertLessEqual(len(shown.items), MAX_ROWS + 6, "el diálogo cabe en la ventana")
        rows = [item for item in shown.items if item.kind in ("prop", "label", "operator", "prop_search")]
        self.assertLessEqual(len(rows), MAX_ROWS, f"{len(rows)} filas")
        hypothesis = [text for text in texts if text.startswith("HIPÓTESIS: ")]
        # Spec 019 T23 (UI-09, RF-019-19): el tipo que comparten las cuatro tolerancias se dice **una vez** bajo el cuadro, no bajo cada campo. Lo que dice sigue siendo lo mismo:
        # las cuatro son HIPÓTESIS sin valor por defecto.
        kinds = {self.des_pit._pit_param_text(param) for _prop, param in self.des_pit._tolerance_rows()}
        self.assertEqual(len(kinds), 1, "las cuatro tolerancias del desfase comparten el tipo")
        self.assertTrue(next(iter(kinds)).startswith("HIPÓTESIS: "), "HIPÓTESIS, sin valor por defecto")
        self.assertEqual(len(hypothesis), 1, "las tolerancias del desfase dicen su tipo una vez: sin valor por defecto")
        self.assertEqual(hypothesis[0], next(iter(kinds)))
        down = draw(cls, bpy.context, **{**self.fake().__dict__, "mode": "DOWN", "show_more": True}).texts()
        self.assertIn("Cota de fondo (m)", down)
        self.assertNotIn("Campo de cota", down)

    WINDOW_PX = dialog_height.WINDOW_PX
    """El modelo del diálogo a 1920 × 1001 es el compartido (``tests/support/dialog_height.py``, spec 019 T26): 25 px por campo, 20 por etiqueta,
    30 por botón, 10 de margen por caja, 100 de título y botones, calibrado con el diálogo de antes (≈ 1.000 px, hallazgo H3-3)."""

    def height(self, shown: Any) -> int:
        """Lo que mide el diálogo dibujado en ``shown`` según el modelo."""
        return dialog_height.height(shown)

    def test_a2_the_dialog_fits_the_window_and_folds_what_is_rarely_touched(self) -> None:
        """RF-018-34, H3-3 (M1): «Nueva corta…», en cualquiera de los dos modos, mide menos de 1001 px (los botones «Calcular» y «Cancelar» a la vista) con **lo que casi nunca se toca
        plegado** (los valores por sector y las tolerancias del desfase con su ventana del azimut y su radio de cierre); al desplegarlo vuelve todo; si algún campo plegado ya tiene valor,
        se enseña (no se esconde lo escrito)."""
        cls = self.pit
        for mode in ("UP", "DOWN"):
            with self.subTest(modo=mode):
                folded = draw(cls, bpy.context, **{**self.fake().__dict__, "mode": mode, "show_more": False})
                self.assertLessEqual(self.height(folded), self.WINDOW_PX, f"{self.height(folded)} px")
                texts = folded.texts()
                for hidden in ("Perfiles por sector", "Rosetas por sector", "Bancos por berma por sector", "Tolerancia del arco (m)", "Radio de cierre (m)", "Ventana del azimut (m)"):
                    self.assertNotIn(hidden, texts)
                self.assertIn("Más opciones", texts)
                self.assertTrue([item for item in folded.items if item.target == "show_more"])
                opened = draw(cls, bpy.context, **{**self.fake().__dict__, "mode": mode, "show_more": True})
                for shown in ("Perfiles por sector", "Rosetas por sector", "Bancos por berma por sector", "Tolerancia del arco (m)", "Radio de cierre (m)", "Ventana del azimut (m)"):
                    self.assertIn(shown, opened.texts())
        for field, value in (("sector_profiles", "sector_1=a"), ("arc_tol", "0,1"), ("corner", "MITER"), ("az_window", "5")):
            with self.subTest(campo=field):
                held = draw(cls, bpy.context, **{**self.fake().__dict__, "show_more": False, field: value})
                self.assertIn("Tolerancia del arco (m)", held.texts(), "lo escrito en un campo plegado se enseña")

    def test_a3_the_dialog_says_which_surface_it_starts_from(self) -> None:
        """RF-018-03, T40h (ensayo de CE-018-13): si la partida es una entidad (por defecto, la última de la cadena: otra corta), el diálogo lo **avisa antes de calcular** con su nombre
        legible y dice cómo elegir el terreno; con una superficie no hay aviso; y el diálogo sigue cabiendo en 1001 px."""
        cls = self.pit
        listed = [("entity:PIT-002", "Corta «Corta 2» (PIT-002)", "x"), (self.terrain["llano"], "llano", "y")]
        with mock.patch.object(self.panels, "platform_start_items", return_value=listed):
            self.assertIsNone(self.des_pit._start_notice(self.terrain["llano"]))
            text = self.des_pit._start_notice("entity:PIT-002")
            self.assertIn("Corta «Corta 2» (PIT-002)", text)
            self.assertIn("Superficie de partida", text)
            self.assertNotIn("entity:", text, "UI-08")
            for mode in ("UP", "DOWN"):
                shown = draw(cls, bpy.context, **{**self.fake().__dict__, "mode": mode, "start": "entity:PIT-002"})
                self.assertTrue([t for t in shown.texts() if "Corta 2" in t], "el aviso se dibuja")
                self.assertLessEqual(self.height(shown), self.WINDOW_PX, f"{mode}: {self.height(shown)} px")
            plain = draw(cls, bpy.context, **{**self.fake().__dict__, "start": self.terrain["llano"]})
            self.assertFalse([t for t in plain.texts() if "Corta 2" in t])

    # --- b: la petición -----------------------------------------------------------------------

    def test_b_the_request_of_the_dialog(self) -> None:
        """RF-018-01, RF-018-06 a 09, RF-018-13, RF-018-14 (M1): lo pedido en el diálogo es la ``PitRequest`` que arma el dominio, sin calcular nada: la capa con sus campos, el modo, los
        perfiles (el base y los de cada sector), la roseta, los bancos por berma, las rampas, las capas de zonas sin rampa y de bancos fijados, los criterios de parada y las tolerancias, tecleados
        con coma o con punto; lo que falta o no es un número se rechaza con el campo y lo tecleado."""
        cls, model = self.pit, self.pit_model
        asked = cls._request(self.fake(name=" Mi corta ", name_field="nombre", level_field="cota_m", profile="expl_10_60_6", rose=self.rose, n_berm="2",
                                       sector_profiles="sector_1=expl_10_45_6; sector_2=expl_10_60_6", sector_roses="sector_1=roseta_del_tajo", sector_n_berm="sector_1=2",
                                       ramps={self.ramps["Espiral"]}, noramp=h2.NO_RAMP, fixed=h2.FIXED_LAYER, fixed_field="banco", top_level="175", bottom_level="70,5",
                                       max_benches="12", min_floor_width="20", corner="MITER", arc_tol="0,05", simplify="0.05", close_radius="1", az_window="5"))
        self.assertIsInstance(asked, model.PitRequest)
        self.assertEqual((asked.name, asked.mode, asked.layer, asked.fields.name_field, asked.level_field), ("Mi corta", model.PitMode.UP, h2.FLOORS, "nombre", "cota_m"))
        self.assertEqual((asked.start, asked.profile, asked.rose, asked.n_berm), (self.terrain["llano"], "expl_10_60_6", self.rose, 2))
        self.assertEqual(asked.sector_profiles, (("sector_1", "expl_10_45_6"), ("sector_2", "expl_10_60_6")))
        self.assertEqual((asked.sector_roses, asked.sector_n_berm), ((("sector_1", "roseta_del_tajo"),), (("sector_1", 2),)))
        self.assertEqual(asked.ramps, (self.ramps["Espiral"],))
        self.assertEqual((asked.noramp.layer, asked.fixed.layer, asked.fixed_field), (h2.NO_RAMP, h2.FIXED_LAYER, "banco"))
        self.assertEqual((asked.top_level_m, asked.bottom_level_m, asked.max_benches, asked.min_floor_width_m), (175.0, 70.5, 12, 20.0))
        self.assertEqual((asked.corner, asked.arc_tol_m, asked.simplify_m, asked.close_radius_m, asked.az_window_m), ("miter", 0.05, 0.05, 1.0, 5.0))
        plain = cls._request(self.fake(profile="expl_10_60_6", support=self.terrain["cadena"]))
        self.assertEqual((plain.support, plain.rose, plain.fixed, plain.noramp, plain.ramps, plain.corner, plain.n_berm, plain.sector_profiles),
                         (self.terrain["cadena"], None, None, None, (), None, None, ()), "lo que no se pide es ``None``: lo resuelve el dominio")
        down = cls._request(self.fake(mode="DOWN", level_field="cota_m", bottom_level="70"))
        self.assertEqual((down.mode, down.level_field, down.bottom_level_m), (model.PitMode.DOWN, None, 70.0), "la cota del campo es de la ascendente")
        for changes, text in (({"name": "  "}, "Escriba el nombre de la corta"), ({"layer": "none"}, "Elija la capa de origen"), ({"start": "none"}, "Elija la superficie de partida"),
                              ({"arc_tol": "abc"}, "«abc» no es un número"), ({"n_berm": "1,5"}, "no es un número entero"), ({"max_benches": "2,5"}, "no es un número entero"),
                              ({"sector_profiles": "sector_1"}, "sector=valor"), ({"sector_n_berm": "sector_1=x"}, "no es un número")):
            with self.subTest(cambios=changes):
                with self.assertRaises(self.des_ops.ProfileFormError) as caught:
                    cls._request(self.fake(**changes))
                self.assertIn(text, str(caught.exception))

    # --- c: calcular y crear ------------------------------------------------------------------

    def test_c_calculate_writes_nothing_and_create_registers_the_pit_with_its_layers(self) -> None:
        """RF-018-03, RF-015-03, RF-015-02, RF-018-01, RF-018-34 (M1): Calcular desde un guion deja el cálculo abierto con su resumen (la corta, el modo, los bancos, las cotas, el volumen
        y el área, y todos los avisos) y nada en el proyecto. Crear registra ``des.pit`` en V01 con su superficie y sus polilíneas, encadena la capa de entidades y deja los parámetros de la
        entidad; la capa de origen no se toca."""
        self.refresh()
        before, layer = self.state(), self.rows(f'SELECT * FROM "{h2.FLOORS}" ORDER BY fid')
        held = self.calculate_pit(self.form())
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), (PIT_TYPE, "Corta de la orden", "V01", "PIT-001"))
        self.assertEqual(self.state(), before, "calcular no registra nada ni deja un temporal")
        self.assertEqual(self.view.summary_title, "Corta «Corta de la orden» en V01")
        summary = self.summary()
        self.assertTrue(summary[0][0].startswith("Corta «Corta de la orden» (PIT-001) · modo «ascendente»"), summary[0])
        self.assertIn("5 bancos", summary[0][0])
        self.assertFalse(held.needs_mean_confirmation)
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, "Pit «Corta de la orden» in V01")
        self.assertTrue(self.summary()[0][0].startswith("Pit «Corta de la orden» (PIT-001) · mode «ascending»"), self.summary()[0])
        self.i18n.set_language("es")
        self.panels.show_summary(held)

        self.assertEqual(self.create_pit(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.view.summary_title, "")
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?", PIT_TYPE)
        self.assertEqual(status, "done")
        figures = self.figures_of(uid)
        self.assertEqual(figures["des.pit_benches"], 5.0)
        self.assertEqual(self.states(self.v01), {"PIT-001": self.entities.EntityState.CURRENT})
        for table in ("des_enl_v01",):
            self.assertIn("PIT-001", repr(self.rows(f'SELECT * FROM "{table}"')), table)
        self.assertEqual(self.rows(f'SELECT * FROM "{h2.FLOORS}" ORDER BY fid'), layer, "la capa de origen no se toca")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.declare_constraints'"), [(1,)], "tras crear se declara de nuevo (la corta no declara nada)")

    # --- d: la pendiente media por encima de pm -------------------------------------------------

    def test_d_a_mean_gradient_above_pm_is_not_created_without_the_confirmation_and_its_reason(self) -> None:
        """RF-018-19, RF-017-17 (M1): una espiral al 8 % con un perfil de pista de pm = 5 % calcula y su resumen lo dice **en ámbar**; «Crear» se llama «Confirmar y crear»; no se crea sin
        la confirmación expresa ni, confirmada, sin su motivo (el cálculo sigue abierto); con ambas se crea y la confirmación queda en los ajustes con su motivo, quién y cuándo."""
        self.refresh()
        held = self.calculate_pit(self.form(name="Corta con pm", start=self.terrain["rampa"], ramps={self.strong}, simplify="1e-6"))
        self.assertTrue(held.needs_mean_confirmation)
        alerts = [text for text, alert in self.summary() if alert and "pendiente media" in text]
        self.assertTrue(alerts, self.summary())
        self.assertEqual(self.pit._confirm_text(self.fake(), held), "Confirmar y crear")
        before = self.state()
        for values, text in (({}, "confírmela con un motivo para crear la corta"), ({"confirm_mean": True}, "Escriba el motivo de aceptar una pendiente media"),
                             ({"confirm_mean": True, "mean_reason": "  "}, "Escriba el motivo de aceptar una pendiente media")):
            with self.subTest(values=values):
                with self.assertRaises(RuntimeError) as caught:  # una orden que se queja con un error de informe sale de ``bpy.ops`` como excepción
                    self.create_pit(**values)
                self.assertIn(text, str(caught.exception))
                self.assertIsNotNone(self.des_ops.calculation(), "el cálculo sigue abierto")
                self.assertEqual(self.state(), before)
        self.assertEqual(self.create_pit(confirm_mean=True, mean_reason="Hay que cruzar el cauce"), {"FINISHED"})
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE op_type = ? AND status = 'done' ORDER BY fid DESC LIMIT 1", PIT_TYPE)
        found = self.dprov.ramp_confirmed(json.loads(settings))
        self.assertEqual([(item.ramp, item.reason, item.decided_by) for item in found], [(self.strong, "Hay que cruzar el cauce", self.project.session.user_host)])

    # --- e: Esc, cancelar y lo rechazado --------------------------------------------------------

    def test_e_esc_cancel_and_what_is_refused_leave_nothing(self) -> None:
        """RF-018-35, RF-015-29, RF-018-04, RF-015-08 (M1): Esc **a mitad** del cálculo, Cancelar la confirmación y lo que se rechaza —el nombre repetido, la capa que no está, el perfil que
        falta, una tolerancia sin valor o fuera de rango— no dejan nada (0 escrituras); cada rechazo dice la capa, la corta, el campo y el valor; Esc dice que no queda nada a medias."""
        self.refresh()
        free = lambda **values: {**self.form(start=self.terrain["cuadrado"]), **values}  # noqa: E731 - de cada superficie parte una sola entidad
        before = self.state()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **free(name="Esc", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running()
        modal.STEP_BUDGET_S = step_modals.ONE_STEP_S  # un paso por evento
        for _ in range(3):
            self.assertEqual(modal.modal(bpy.context, step_modals.TIMER), {"RUNNING_MODAL"})
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
        self.assertIsNone(modal._steps)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        self.calculate_pit(free(name="Cancelada"))
        self.pit.cancel(operator_self(self.pit, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        for changes, texts in (({"name": " "}, ("Escriba el nombre de la corta",)),
                               ({"name": "Corta de la orden"}, ("El nombre «Corta de la orden» ya lo tiene la entidad «Corta de la orden» en V01",)),
                               ({"profile": "none"}, ("entidad «Rechazada»", "«Perfil de banco base de la corta»", "no tiene valor")),
                               ({"arc_tol": ""}, (f"Capa «{h2.FLOORS}»", "«Tolerancia de los arcos del desfase»", "no tiene valor")),
                               ({"simplify": "-1"}, (f"Capa «{h2.FLOORS}»", "«Tolerancia de simplificación de las polilíneas» = -1", "está fuera de su rango")),
                               ({"start": self.terrain["llano"]}, ("no puede partir de", "ya parte la entidad «Corta de la orden»"))):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **free(**{"name": "Rechazada", **changes}))
                for text in texts:
                    self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)

    # --- f: la vista previa ---------------------------------------------------------------------

    def test_f_the_preview_follows_the_dialog_gets_the_calculation_and_goes_away(self) -> None:
        """RF-018-32, RF-015-26 (T29, M1, M3): el botón «Vista previa» (la misma orden con ``preview``) activa la vista previa de **esa** corta con lo pedido (sin calcular ni escribir);
        tras calcular, le da lo calculado; se quita al cancelar el diálogo, con Esc y al crear."""
        entity = self.des_ops._entity_preview()
        self.addCleanup(entity.disable)
        self.refresh()
        before = self.state()
        form = self.form(name="Vista previa", start=self.terrain["fijado"])
        self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", preview=True, **form), {"FINISHED"})
        self.assertTrue(entity.enabled())
        pit = entity.plan().pit
        self.assertEqual((pit.request.name, pit.request.layer, pit.prepared, pit.outcome), ("Vista previa", h2.FLOORS, None, None))
        self.assertEqual(self.state(), before, "la vista previa no escribe")
        held = self.calculate_pit(form)
        self.assertTrue(entity.enabled())
        self.assertIs(entity.plan().pit.outcome, held.outcome, "tras calcular, la vista previa es la de lo calculado")
        self.pit.cancel(operator_self(self.pit, confirm=True, in_steps=False), bpy.context)
        self.assertFalse(entity.enabled(), "cancelar la ventana de crear la quita")
        self.assertEqual(self.state(), before)
        bad = {**form, "arc_tol": "abc"}
        with self.assertRaises(RuntimeError):
            bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", preview=True, **bad)
        self.assertFalse(entity.enabled(), "un diálogo a medias no activa nada")

    # --- h: la orden desactivada ----------------------------------------------------------------

    def test_h_the_command_is_disabled_with_its_reason(self) -> None:
        """RF-018-34, RF-015-28, RF-009-21 (M1): con el proyecto en solo lectura la orden sale desactivada con su motivo y no se puede lanzar; ni deja nada."""
        messages: list[str] = []
        cls = self.pit
        self.assertTrue(cls.poll(bpy.context))
        before = self.state()
        with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True), \
                mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(cls.poll(bpy.context))
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_create_pit.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **self.form(name="No debe"))
            self.assertEqual(self.state(), before)
        self.assertTrue(cls.poll(bpy.context))

    # --- i: crear por pasos y la vista previa -----------------------------------------------------

    def test_i_creating_by_steps_from_the_interface_removes_the_preview(self) -> None:
        """RF-018-35, RF-018-32 (la vía real de la interfaz: ``_CreatesInSteps._creation_steps`` → ``_after_registered``): «Crear» **por pasos**, con ventana, deja la corta y quita la vista
        previa en cuanto lo guardado llega; antes, con el cálculo abierto, sigue encendida."""
        entity = self.des_ops._entity_preview()
        self.addCleanup(entity.disable)
        self.refresh()
        form = self.form(name="Creada por pasos", start=self.terrain["sur"])
        self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", preview=True, **form), {"FINISHED"})
        self.assertTrue(entity.enabled())
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **{**form, "in_steps": True}), {"RUNNING_MODAL"})
            self.assertEqual(step_modals.drive(self.running(), bpy.context)[0], {"FINISHED"})
            self.assertTrue(entity.enabled(), "calculada y sin crear, la vista previa sigue")
            self.assertIsNotNone(self.des_ops.calculation())
            self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
            self.assertEqual(step_modals.drive(self.running(), bpy.context)[0], {"FINISHED"})
        self.assertFalse(entity.enabled(), "se quita al crear la corta por pasos")
        self.assertIn("Creada por pasos", [entry.record.name for entry in self.entities.registry(self.project, self.v01.uid)])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ? AND status = 'done'", PIT_TYPE)[0][0], 3)

    # --- j: «Calcular…» de una corta traída ---------------------------------------------------------

    def test_j_calculate_from_the_entity_menu_opens_a_brought_pit_and_creates_it_with_its_code(self) -> None:
        """RF-015-18, RF-018-34, RF-018-35 (T35; M6): una corta traída a otra versión queda **sin calcular**; «Calcular…» del menú «Entidad ▾» la ofrece, abre «Nueva corta…» **con su código** y,
        sin diálogo, la calcula con los parámetros que ya tiene (nada escrito hasta «Crear»); «Crear» la deja **al día con el mismo código** y sin otra entidad. La accesibilidad no se ofrece."""
        self.addCleanup(lambda: bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid))
        self.entity_store.bring_entities(self.project, self.v01, self.v03, codes=["PIT-001"])
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v03.uid), {"FINISHED"})
        record = lambda: self.entities.registry(self.project, self.v03.uid).get("PIT-001").record  # noqa: E731
        self.assertEqual(record().state, self.entities.EntityState.UNCALCULATED)
        before = self.counts()
        opened: list[tuple[str, dict[str, Any]]] = []
        with mock.patch.object(self.des_ops, "_invoke_later", lambda idname, _window, **kwargs: opened.append((idname, kwargs))):
            self.assertEqual(bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", entity="PIT-001"), {"FINISHED"})
        self.assertEqual(opened, [(PIT, {"code": "PIT-001"})])
        self.assertEqual(self.counts(), before, "abrir el cálculo no escribe nada")
        self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", code="PIT-001", in_steps=False), {"FINISHED"})
        self.assertIsNotNone(self.des_ops.calculation())
        self.assertEqual(self.counts(), before, "calcular no escribe nada")
        self.assertEqual(self.create_pit(), {"FINISHED"})
        self.assertEqual(record().state, self.entities.EntityState.CURRENT)
        self.assertEqual([entry.record.code for entry in self.entities.registry(self.project, self.v03.uid) if entry.record.kind == self.entities.EntityKind.PIT], ["PIT-001"])
        with mock.patch.object(self.des_ops, "_invoke_later") as later:  # ya con resultado: se rehúsa y no abre nada
            with self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", entity="PIT-001")
            self.assertIn("ya tiene resultado", str(caught.exception))
            later.assert_not_called()

    def test_k_a_pit_with_a_rose_after_another_pit_calculates_choosing_the_ground(self) -> None:
        """RF-018-03, RF-018-07, T40h (el ensayo de CE-018-13 no pudo calcular con roseta porque la partida por defecto era la corta anterior): con otra corta ya en la cadena, la corta con roseta
        se calcula partiendo del terreno elegido en la lista (el rechazo que nombra la superficie de partida está en ``milestone_pit_prepare_checks`` y ``test_pit_params``)."""
        self.refresh()
        before = self.state()
        stale = self.des_ops.calculation()
        self.assertIsNone(stale)
        held = self.calculate_pit(self.form(name="Con roseta", rose=self.rose, n_berm="2", start=self.terrain["roseta"]))
        self.assertEqual(held.name, "Con roseta")
        self.assertEqual(self.state(), before, "calcular no escribe nada")
        self.des_ops.discard_calculation()

    def test_l_the_missing_tolerance_speaks_in_readable_words(self) -> None:
        """UI-07, UI-08, UI-09, T40i (ensayo de CE-018-13): el rechazo por una tolerancia sin valor nombra la entidad y **el valor por su nombre** («Tolerancia de los arcos del desfase»), nunca la
        clave interna ``des.pit.pit_003.arc_tol_m``, y dice qué hacer (desplegar «Más opciones»); un valor fuera de rango, también con su nombre; en inglés, igual."""
        params = h2._module("design.params")
        missing = self.messages.DesignError
        for param, value, code in (("arc_tol_m", None, "des.entity_param_missing"), ("simplify_m", -1.0, "des.entity_param_range")):
            with self.assertRaises(missing) as caught:
                params.check_entity_param("Rechazada", "PIT-003", param, value, layer="gis_fea_h2_fondos")
            self.assertEqual(caught.exception.code, code)
            text = self.des_pit.pit_error_text(caught.exception)
            self.assertNotIn("des.pit.", text)
            self.assertIn("«Rechazada»", text)
            self.assertNotIn("pit_003", text)
            if param == "arc_tol_m":
                self.assertIn("«Tolerancia de los arcos del desfase»", text)
                self.assertIn("Más opciones", text)
            else:
                self.assertIn("«Tolerancia de simplificación de las polilíneas»", text)
        self.i18n.set_language("en")
        with self.assertRaises(missing) as caught:
            params.check_entity_param("Rejected", "PIT-003", "arc_tol_m", None, layer="gis_fea_h2_fondos")
        text = self.des_pit.pit_error_text(caught.exception)
        self.assertIn("«Tolerance of the arcs of the offset»", text)
        self.assertNotIn("des.pit.", text)
        self.assertIn("More options", text)

    def test_m_a_failed_calculate_keeps_what_was_typed_for_the_next_time_without_writing(self) -> None:
        """UI-14, T40i (ensayo de CE-018-13: un «Calcular» fallido obligaba a rellenar todo otra vez, ≈ 12 clics): lo escrito en el diálogo se recuerda **en memoria** (nada en el proyecto) si el
        cálculo falla o se cancela, se pone de nuevo al reabrir, solo una vez, y se olvida si el cálculo sale bien, si cambia el proyecto o la versión o si quien lanza la orden da sus valores."""
        self.refresh()
        before = self.state()
        failing = self.form(name="Mal hecha", arc_tol="", simplify="0,05", max_benches="3", n_berm="1")
        with self.assertRaises(RuntimeError):
            bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **failing)
        self.assertEqual(self.state(), before, "recordarlo no escribe nada en el proyecto")
        reopened = self.fake(name="", max_benches="", simplify="", arc_tol="", n_berm="")
        reopened.properties = SimpleNamespace(is_property_set=lambda name: False)
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"})))
        self.pit.invoke(reopened, context, None)
        self.assertEqual((reopened.name, reopened.max_benches, reopened.simplify, reopened.n_berm), ("Mal hecha", "3", "0,05", "1"), "lo escrito vuelve")
        again = self.fake(name="", max_benches="", simplify="")
        self.pit.invoke(again, context, None)
        self.assertEqual(again.max_benches, "", "solo una vez")
        # un cálculo que sale bien lo olvida
        self.des_pit.remember_typed(self.fake(name="Vieja", max_benches="9"))
        self.calculate_pit(self.form(name="Buena", start=self.terrain["roseta"]))
        self.des_ops.discard_calculation()
        fresh = self.fake(name="", max_benches="")
        self.pit.invoke(fresh, context, None)
        self.assertEqual(fresh.max_benches, "")
        # lo que da quien lanza la orden manda sobre lo recordado
        self.des_pit.remember_typed(self.fake(name="Vieja", max_benches="9"))
        given = self.fake(name="Mía", max_benches="2", properties=SimpleNamespace(is_property_set=lambda name: name in ("name", "max_benches")))
        self.pit.invoke(given, context, None)
        self.assertEqual((given.name, given.max_benches), ("Mía", "2"))
        # otra versión: no se aplica
        self.des_pit.remember_typed(self.fake(name="Vieja", max_benches="9"))
        with mock.patch.object(self.des_pit.scene_versions, "active_version", return_value="otra-version"):
            other = self.fake(name="", max_benches="")
            self.pit.invoke(other, context, None)
            self.assertEqual(other.max_benches, "")

    # --- z: desactivar -----------------------------------------------------------------------------

    def test_z_disabling_geoblender_removes_the_command_and_the_open_calculation(self) -> None:
        """Principio 8, D-14 de la 013, RF-015-26: con un cálculo abierto y la vista previa activa, desactivar Geoblender los descarta (ni un temporal ni la vista previa) y quita la orden."""
        self.refresh()
        entity = self.des_ops._entity_preview()
        apart = self.form(name="Al apagar", start=self.terrain["esquina"])
        self.assertEqual(bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **apart, preview=True), {"FINISHED"})
        self.calculate_pit(apart)
        self.assertTrue(entity.enabled())
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, PIT_CLASS, None))
        self.assertFalse(entity.enabled())
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name, _value in vars(h2.PitH2Test).items():  # el proyecto y las ayudas del hito H2, sin sus pruebas (que no se repiten)
    if not _name.startswith(("test_", "__")) and _name not in vars(PitOpsTest) and _name not in ("setUp", "_abc_impl"):
        setattr(PitOpsTest, _name, _value)


if __name__ == "__main__":
    unittest.main()
