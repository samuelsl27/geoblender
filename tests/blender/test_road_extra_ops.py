# SPDX-License-Identifier: GPL-3.0-or-later
"""«Proponer el trazado…» y «Exportar pista…» en Blender (spec 017, T33 (a); HU-017-1, HU-017-4; RF-017-28, RF-017-29, RF-017-27, RF-017-30, RF-015-28; H-9; plan 017 §5.3.3 y §5.5; comprobación manual M6).

:class:`GEOBLENDER_OT_des_propose_road` (``geoblender.des_propose_road``) calcula con ``design.steps.road_propose_run`` la operación ``des.road_propose`` de la versión activa: **lo mismo que la pista
«trazar» hasta la ruta y la rasante** (sin la sección) y deja **una capa de líneas con Z, editable en QGIS** (``des_rpl_<nombre>``), **sin tocar ninguna superficie** y sin ser una entidad. Su diálogo es el de «Pista…»
en «trazar»; «Calcular» y «Crear» son **por pasos** con el avance y Esc (``_CreatesInSteps`` sin lo que sigue a crear una entidad); la pendiente media por encima de pm solo avisa.
:class:`GEOBLENDER_OT_des_export_road` (``geoblender.des_export_road``) escribe la superficie de una pista o lo que alcanza una accesibilidad como GeoTIFF y la rasante de una pista a CSV **sin escribir nada
en el proyecto** (exportar no es una operación: H-9). El proyecto es el de ``test_road_ops.py`` (60 × 60 m con celdas de 2 m, V01 y V02, el límite legal, el perímetro, un sector con la búsqueda cerrada, los terrenos
``Suave`` y ``A15``, las capas de la pista y los perfiles de referencia de IMGA, **solo de pruebas**): se paga **una vez** por clase (≈ 6 s). Las pruebas, en el orden de sus letras sobre el mismo estado.

- RF-017-29, RF-015-28 (a): las dos órdenes son reales, del catálogo (entrada 017, entregada); sus propiedades tienen nombre y descripción en español; el diálogo propone el nombre, la capa y la partida y dibuja los
  campos de «trazar» con el tipo de cada parámetro de la ruta; el de exportar, qué exportar y de qué pista o accesibilidad.
- RF-017-28, RF-017-02 (b): la petición del diálogo es la ``RoadRequest`` de «trazar», con los decimales con coma y sin cifra en los parámetros vacíos; lo que no se puede armar se dice.
- RF-017-28, RF-015-03, D-19 (c): Calcular deja el cálculo abierto con su resumen (con todos los avisos con su lugar) y **nada en el proyecto**; Crear registra ``des.road_propose`` con la capa de líneas con Z
  **editable**, las dos cifras y **no toca ninguna superficie** (hash de cada una antes y después), ni crea una entidad, un parámetro de entidad, la capa de entidades o la de ejes; la capa propuesta la ofrece
  el modo «eje 3D» de «Pista…».
- RF-017-17, RF-017-28 (d): la pendiente media por encima de pm **solo avisa**: el resumen lo dice en ámbar y se crea sin confirmación ni motivo.
- RF-015-29, RF-017-30 (e): Esc a mitad de «Calcular» y en cada evento de «Crear» no dejan nada (ni operación, dato, parámetro, cifra ni temporal) y descartan el cálculo; Cancelar la confirmación y lo que se rechaza
  (nombre repetido, falta de origen, un parámetro sin valor…) dejan 0 transacciones.
- RF-017-26 (f): «Vista previa» (pasillo y ruta, sin sección); se quita al cancelar, con Esc y al crear.
- RF-017-29, RF-015-28 (h): «Proponer el trazado…» sale desactivada con su motivo con el proyecto en solo lectura, con la versión activa no editable y sin versión activa; «Exportar pista…», activa con el proyecto
  abierto (exportar no es una operación) y desactivada con su motivo sin proyecto.
- RF-017-27, H-9 (i): «Exportar pista…» escribe la superficie de una pista y lo que alcanza una accesibilidad (GeoTIFF) y la rasante (CSV) **sin escribir nada en el proyecto**, dice qué escribió y dónde, y rechaza
  lo que no es una pista calculada, un destino que no cabe y uno que ya existe.
- Principio 8 (z): desactivar Geoblender quita las dos órdenes y no deja nada.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.blender import test_road_ops as road_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

PROPOSE = "geoblender.des_propose_road"
PROPOSE_CLASS = "GEOBLENDER_OT_des_propose_road"
PROPOSE_TYPE = "des.road_propose"
EXPORT = "geoblender.des_export_road"
EXPORT_CLASS = "GEOBLENDER_OT_des_export_road"
ENTRIES = "gis_fea_accesos_extra"
THRESHOLDS = {"walk_slope": "12", "walk_width": "4", "min_berm_area": "100"}
"""Los umbrales de la accesibilidad tecleados como los teclea una persona (**solo de la prueba**: la orden no propone ninguno)."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
SHAPE = "Trazado de la prueba"
STEEP = "PISTA_PM_BAJA"
PLATFORM = "Carga"
HIDDEN = ("confirm", "in_steps", "preview")
CHANGED = {  # lo que cambia respecto a «Pista…»: la propiedad → su nombre y su descripción (msgid en inglés; en español al registrarse)
    "name": ("Name", "Name of the proposed route, unique in the active version: the layer of 3D lines is called after it"),
    "layer": ("Layer", "Layer of points of the project with the origin and the destination of the route"),
    "origin_road": ("Road of the origin", "Road of the active version whose axis the origin is on: the proposal becomes stale if it changes"),
    "destination_to": ("It ends at", "Whether the route ends at a point of the layer, on a platform of the active version or where it reaches an elevation inside a zone"),
    "destination_entity": ("Platform of the destination", "Platform of the active version the route ends at: its destination is the point of the layer that falls on its footprint, at the level of its "
                                                          "surface"),
    "dest_level": ("Elevation of the destination (m)", "Elevation in metres the route has to reach: it ends at the first point of the zone whose start surface differs from it by less than the arrival "
                                                       "tolerance"),
    "start": ("Start surface", "Surface the route is searched on: by default, the exploitation surface of the quarry and, without it, the last of the chain"),
    "start_level": ("Start level (m)", "Elevation of the level profile at the start of the route in metres (empty: the one of the start surface at that point)"),
    "end_level": ("End level (m)", "Elevation of the level profile at the end of the route in metres (empty: the one of the start surface at that point or of the platform of the destination)"),
}
PROPERTIES = {**{prop: texts for prop, texts in road_ops.PROPERTIES.items() if prop not in ("mode", "feature", "support", "mean_reason")}, **CHANGED}
"""Las propiedades del diálogo de «Proponer el trazado…» con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone quien la lanza, no los llevan): las de «Pista…» menos el modo, la línea, el apoyo
y el motivo de la media, y con la descripción de lo que dice otra cosa de una propuesta."""
DEFAULTS: dict[str, Any] = {name: value for name, value in road_ops.DEFAULTS.items() if name not in ("mode", "feature", "support", "mean_reason", "confirm_mean", "confirm_carriageway")}
EXPORT_PROPERTIES = {"what": ("What to export", "The surface of a road (GeoTIFF), its level profile (CSV) or what an accessibility reaches (GeoTIFF)"),
                     "source": ("Road or accessibility", "Code or name of the road or of the accessibility of the active version to export (empty: the one of the object selected in the 3D view)"),
                     "overwrite": ("Replace", "Replace the file if it already exists")}


class RoadExtraOpsTest(road_ops.RoadOpsTest):
    """El proyecto de la prueba de la pista con una capa de puntos de entrada y las ayudas de las dos órdenes. Las pruebas de la pista son de ``test_road_ops.py``: aquí solo se aprovecha su proyecto."""

    exported: dict[str, str]
    proposals: int

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_feature_layer(ENTRIES, "point", (("Entrada", (10.0, 30.0)),))
        profiles, dparams = platform_ops._module("design.road_profiles"), platform_ops._module("design.params")
        declared = profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", platform_ops.PERSON, road_ops.REASON, version=cls.v01.code)
        data = road_ops.rd.profile_with(max_mean_gradient_pct=1.0)  # pm 1 %: el terreno ``Suave`` (2 %) la pasa
        values = {param: getattr(data, "class_name" if param.value == "class" else param.value) for param in dparams.RoadProfileParam}
        profiles.edit_road_profiles(cls.project, (profiles.ProfileEdit(name=STEEP, values=values),), declared)
        cls.exported, cls.proposals = {}, 0
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        super().refresh()
        cls.panels.refresh_access_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def propose(self) -> Any:
        return self.commands.registered_class(PROPOSE)

    @property
    def export(self) -> Any:
        return self.commands.registered_class(EXPORT)

    def fresh(self) -> str:
        """Un nombre de propuesta nuevo: el nombre de la capa propuesta es único en la versión, y lo creado en una prueba la ocupa."""
        type(self).proposals += 1
        return f"Trazado {type(self).proposals}"

    def pform(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo para la propuesta de «Origen» a «Destino» sobre el terreno ``Suave`` con el perfil de referencia y la ruta de referencia (el nombre, uno nuevo)."""
        return {"name": values.pop("name", None) or self.fresh(), "layer": road_ops.POINTS, "origin_point": "Origen", "destination_point": "Destino", "profile": "pista_principal",
                "start": self.smooth_surface, **road_ops.ROUTE, "in_steps": False, **values}

    def fake_propose(self, **values: Any) -> Any:
        """El operador de mentira con todas las propiedades del diálogo (los de ``DEFAULTS`` y lo que se dé)."""
        properties = values.pop("properties", SimpleNamespace(is_property_set=lambda name: False))
        return operator_self(self.propose, report=lambda kind, text: None, properties=properties, **{**DEFAULTS, "start": self.smooth_surface, **values})

    def calculate_propose(self, form: dict[str, Any]) -> Any:
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **form), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create_propose(self, **values: Any) -> set[str]:
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", confirm=True, in_steps=False, **values)

    def running_propose(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.propose) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{PROPOSE} no está en marcha")
        found[0].STEP_BUDGET_S = step_modals.ONE_STEP_S  # un paso por evento
        return found[0]

    def temporaries(self) -> list[str]:
        return [name for name in self.names() if ".tmp" in name]

    def surface_state(self) -> tuple[Any, ...]:
        """Todas las superficies del proyecto como están: su registro, su hash y el de sus bytes (nada de lo que hace «Proponer el trazado…» las toca)."""
        files = sorted(Path(self.project.root, "rasters").rglob("*.tif"))
        return (self.rows("SELECT name, status, content_sha256 FROM gb_dataset WHERE store = 'rasters' ORDER BY name"),
                [(item.name, hashlib.sha256(item.read_bytes()).hexdigest()) for item in files])

    def entity_state(self) -> tuple[Any, ...]:
        """Lo que haría una **entidad**: las entidades de la versión, los parámetros de entidad (``des.road.…``) y la capa de entidades y la de ejes."""
        return (sorted(entry.record.code for entry in self.entities.registry(self.project, self.v01.uid)),
                self.rows("SELECT key FROM gb_parameter WHERE key LIKE 'des.road.%' OR key LIKE 'des.platform.%' ORDER BY key"),
                self.rows("SELECT name, status FROM gb_dataset WHERE name IN ('des_enl', 'des_rax', 'des_dcl') ORDER BY name"),
                self.rows("SELECT count(*) FROM gb_operation WHERE op_type IN ('des.entity_layer', 'des.road_layer', 'des.declare_constraints')"))

    def summary(self) -> list[tuple[str, bool]]:
        return [(line.name, bool(line.alert)) for line in self.view.summary]

    def route_layer(self, name: str) -> tuple[Any, ...]:
        """La capa propuesta de ``name`` en V01 (su registro) y sus filas."""
        return (self.rows("SELECT uid, status, qgis_editable FROM gb_dataset WHERE name = ?", self.dprov.dataset_name("rpl", name)),
                self.rows(f'SELECT fid, name FROM "{self.table_of(name)}"'))

    def table_of(self, name: str) -> str:
        """La tabla de la capa propuesta de ``name`` en V01 (``des_rpl_<nombre>_v01``)."""
        return str(self.dprov.dataset_locator(self.dprov.ROUTE_LAYER_TABLE, name, "V01"))

    @staticmethod
    def progress(done: int) -> Any:
        """Un paso de un modal con ``done`` de 1000."""
        return platform_ops._module("core.project.model").Progress("test", done, 1000, "…")

    # --- a: las órdenes, sus diálogos y la propuesta -----------------------------------------------

    def test_a_the_commands_their_dialogs_and_the_proposal(self) -> None:
        """RF-017-29, RF-015-28, RF-017-28, RF-017-10, RF-017-27 (plan §5.3.3, §5.5; M6): «Proponer el trazado…» es una orden real de ``des.road_propose`` con la puerta de la procedencia y los pasos con Esc y
        «Exportar pista…» una de exportar (no es una operación); las dos son de la entrada 017 (entregada por la T33b) y del catálogo, con su casa en Diseño ▸ Pistas y entidades; sus propiedades tienen nombre y descripción en español y los
        decimales son texto; el diálogo de proponer propone el nombre, la capa, el perfil y la partida y dibuja los campos de «trazar» —con **el tipo de cada parámetro de la ruta**, sin modo, línea ni apoyo— y
        «Vista previa»; el de exportar, qué exportar y de qué pista o accesibilidad."""
        cls, export = self.propose, self.export
        self.assertIsNotNone(cls)
        self.assertIsNotNone(export)
        for each in (cls, export):
            self.assertFalse(self.commands.is_provisional(each))
            self.assertIn(each, self.des_ops.classes)
            self.assertTrue(issubclass(each, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertTrue(issubclass(cls, self.des_ops._CreatesInSteps))
        self.assertTrue(issubclass(cls, self.des_ops._ClearsEntityPreview))
        self.assertFalse(issubclass(cls, self.des_ops._ChainsEntityLayer), "una propuesta no es una entidad: no encadena nada")
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options), (PROPOSE, PROPOSE_TYPE, {"REGISTER"}))
        self.assertEqual((export.bl_idname, export.bl_options, getattr(export, "provenance_op_type", None)), (EXPORT, {"REGISTER"}, None))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.PROPOSE_COMMAND, PROPOSE)
        self.assertIn(PROPOSE, self.dprov.OPERATION_TYPES_BY_NAME[PROPOSE_TYPE].commands)
        catalog = self.commands.catalog()
        for idname, label in ((PROPOSE, "Proponer el trazado…"), (EXPORT, "Exportar pista…")):
            command = catalog.commands[idname]
            self.assertEqual((command.label_es, command.entry, command.module, command.kind), (label, "017", "des", "operator"))
            self.assertTrue(self.commands.is_available(idname), "la entrada 017 está entregada (T33b): la orden se dibuja en su menú sin la nota «Disponible en …»")
        self.assertEqual({name for name in cls.__annotations__ if name not in HIDDEN}, set(PROPERTIES))
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]), (self.i18n.translate("es", label), self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        for prop in HIDDEN:  # las pone quien la lanza: sin nombre ni descripción
            self.assertNotIn("name", cls.__annotations__[prop].keywords)
        for prop in ("mesh", "level_step", "max_cut_fill", "lambda_weight", "turn", "margin", "simplify", "arrival_tol", "search_budget", "start_level", "end_level", "dest_level", "dest_tol",
                     "origin_station"):
            self.assertIs(cls.__annotations__[prop].function, bpy.props.StringProperty, f"{prop}: los decimales, en texto (regla 4)")
        self.assertNotIn("mode", cls.__annotations__)
        self.assertEqual({name for name in export.__annotations__ if name not in (*HIDDEN, "filepath", "filter_glob", "check_existing")}, set(EXPORT_PROPERTIES))
        for prop, (label, about) in EXPORT_PROPERTIES.items():
            with self.subTest(exportar=prop):
                keywords = export.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]), (self.i18n.translate("es", label), self.i18n.translate("es", about)))
        self.assertEqual(self.i18n.untranslated([text for _identifier, name, about in self.des_ops.EXPORT_ROAD_ITEMS for text in (name, about)]), [])

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        proposal = self.fake_propose(name="", layer="", profile="", start="")
        self.assertEqual(cls.invoke(proposal, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Proponer el trazado…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(proposal.in_steps)
        self.assertEqual((proposal.name, proposal.layer, proposal.profile), ("Trazado propuesto 1", self.panels.road_layers("TRACE")[0][0], "pista_principal"))
        self.assertEqual([item[0] for item in self.panels.road_layers("TRACE")], [ENTRIES, road_ops.POINTS], "las capas de puntos del proyecto")
        self.assertIn(proposal.start, [identifier for identifier, _label, _about in self.panels.platform_start_items(None, None)])
        given = self.fake_propose(name="Mío", layer=road_ops.POINTS, profile=road_ops.A15_PROFILE.lower(), start=self.a15_surface,
                                  properties=SimpleNamespace(is_property_set=lambda name: name in ("layer", "profile", "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.layer, given.profile, given.start), ("Mío", road_ops.POINTS, road_ops.A15_PROFILE.lower(), self.a15_surface), "lo dado no cambia")

        trace = draw(cls, bpy.context, **{**DEFAULTS, "start": self.smooth_surface}).texts()
        for heading in ("Nombre", "Geometría de la pista", "Capa", "El origen es", "Punto de origen", "Termina en", "Punto de destino", "Perfil de pista", "Superficie de partida", "Cota de inicio (m)",
                        "Cota de fin (m)", "Malla de la ruta (m)", "Paso de cota (m)", "Altura máxima de desmonte y terraplén (m)", "Peso del movimiento de tierras (1/m)", "Penalización de giro (m)",
                        "Holgura del pasillo (m)", "Tolerancia de simplificación (m)", "Tolerancia de llegada de la ruta (m)", "Presupuesto de estados", "Vista previa"):
            self.assertIn(heading, trace)
        for absent in ("Modo", "Línea de la capa", "Superficie de apoyo"):
            self.assertNotIn(absent, trace)
        self.assertEqual(len([text for text in trace if text.startswith("HIPÓTESIS: ")]), 8, "ocho de los nueve parámetros de la ruta son hipótesis sin valor por defecto")
        self.assertEqual(len([text for text in trace if text.startswith("Por defecto: ") and text.endswith("· ADOPTADO")]), 1, "el presupuesto de estados tiene su valor por defecto")
        self.assertIn("Abscisa del origen (m)", draw(cls, bpy.context, **{**DEFAULTS, "origin_from": "ROAD"}).texts())
        for heading in ("Cota del destino (m)", "Tolerancia de llegada a la cota (m)", "Zona del destino", "Polígono de la zona"):
            self.assertIn(heading, draw(cls, bpy.context, **{**DEFAULTS, "destination_to": "LEVEL"}).texts())
        self.assertIn("Plataforma del destino", draw(cls, bpy.context, **{**DEFAULTS, "destination_to": "ENTITY"}).texts())
        shown = draw(cls, bpy.context, **{**DEFAULTS, "confirm": True}).texts()
        self.assertNotIn("Motivo de la pendiente media", shown, "una propuesta no pide el motivo de la media")
        for text in draw(export, bpy.context, what="SURFACE", source="").texts():
            self.assertIn(text, ("Qué exportar", "Pista o accesibilidad"))

    # --- b: la petición ----------------------------------------------------------------------------

    def test_b_the_request_of_the_dialog_is_the_trace_one(self) -> None:
        """RF-017-28, RF-017-02, RF-017-04 (plan §5.2.1, §5.3.3): lo pedido en el diálogo arma la ``RoadRequest`` de «trazar» con el origen y el destino de la capa de puntos, el origen en el eje de otra pista a una
        abscisa, el destino en una plataforma o en una cota con su zona, los decimales con coma y los parámetros de la ruta vacíos **sin cifra** (los rechaza el cálculo, con su nombre); lo que el diálogo no puede
        armar se dice sin tocar nada."""
        model = platform_ops._module("design.road_model")
        asked = self.propose._request(self.fake_propose(name="Mi trazado", **road_ops.ROUTE, start_level="100,5", end_level=" 101 ", search_budget="1000000"))
        self.assertEqual((asked.name, asked.mode, asked.layer, asked.profile, asked.origin, asked.destination, asked.feature, asked.support),
                         ("Mi trazado", model.RoadMode.TRACE, road_ops.POINTS, "pista_principal", "Origen", "Destino", None, None))
        self.assertEqual((asked.mesh_m, asked.level_step_m, asked.max_cut_fill_m, asked.lambda_per_m, asked.turn_m, asked.margin_m, asked.simplify_m, asked.arrival_tol_m),
                         (4.0, 0.28, 14.0, 2.0, 4.0, 60.0, 4.0, 0.28))
        self.assertEqual((asked.start_level_m, asked.end_level_m, asked.search_budget, asked.start), (100.5, 101.0, 1_000_000, self.smooth_surface))
        empty = self.propose._request(self.fake_propose(name="Mi trazado"))
        self.assertEqual((empty.mesh_m, empty.turn_m, empty.search_budget, empty.start_level_m, empty.end_level_m), (None, None, None, None, None), "ningún valor se elige por la persona")
        on_road = self.propose._request(self.fake_propose(name="X", origin_from="ROAD", origin_road="RDW-001", origin_station="100,5", destination_to="ENTITY", destination_entity="PLT-001"))
        self.assertEqual((on_road.origin, on_road.destination), ("RDW-001@100.5", "entity:PLT-001"))
        by_level = self.propose._request(self.fake_propose(name="X", destination_to="LEVEL", dest_level="101,8", dest_tol="0,3", dest_zone=road_ops.ZONES, dest_zone_feature="Zona alta"))
        self.assertEqual((by_level.destination, by_level.dest_level_m, by_level.dest_tol_m, by_level.dest_zone), (None, 101.8, 0.3, f"{road_ops.ZONES}:Zona alta"))
        for changes, text in (({"name": " "}, "Escriba el nombre del trazado propuesto"), ({"layer": "none"}, "Elija la capa del trazado"), ({"layer": ""}, "Elija la capa del trazado"),
                              ({"profile": "none"}, "Elija el perfil de la pista"), ({"start": "none"}, "Elija la superficie de partida del trazado"),
                              ({"origin_from": "ROAD"}, "Elija la pista en cuyo eje está el origen"),
                              ({"origin_from": "ROAD", "origin_road": "RDW-001"}, "Escriba la abscisa del origen"),
                              ({"destination_to": "ENTITY"}, "Elija la plataforma en la que termina la pista"),
                              ({"mesh": "abc"}, "«abc» no es un número (campo «Malla de la ruta (m)»)"),
                              ({"search_budget": "10,5"}, "«10,5» no es un número entero (campo «Presupuesto de estados»)"),
                              ({"start_level": "x"}, "«x» no es un número")):
            with self.subTest(cambios=changes):
                with self.assertRaises(ValueError) as caught:
                    self.propose._request(self.fake_propose(**{"name": "X", **changes}))
                self.assertIn(text, str(caught.exception))

    # --- c: calcular y crear -----------------------------------------------------------------------

    def test_c_calculate_writes_nothing_and_create_leaves_the_editable_layer_and_touches_no_surface(self) -> None:
        """RF-017-28, RF-015-03, RF-015-02, RF-017-27, D-19 (M6): Calcular desde un guion deja el cálculo abierto con su resumen —el trazado, su perfil, la longitud, la pendiente media y la máxima con su abscisa, el
        radio mínimo, que es una capa editable en QGIS y **todos los avisos**, en los dos idiomas y con su título— y **nada en el proyecto**. Crear registra ``des.road_propose`` en V01 con **la capa de líneas con Z**
        (**editable**: ``qgis_editable``) y las dos cifras, **sin cambiar ninguna superficie** (el hash de cada una, antes y después), sin una entidad, un parámetro de entidad, la capa de entidades ni la de ejes; la
        capa propuesta es de las que el modo «eje 3D» de «Pista…» ofrece."""
        self.refresh()
        name = self.fresh()
        before, surfaces, entities = self.state(), self.surface_state(), self.entity_state()
        held = self.calculate_propose(self.pform(name=name))
        self.assertEqual((held.op_type, held.name, held.version, type(held.entity).__name__, type(held.summary).__name__), (PROPOSE_TYPE, name, "V01", "PreparedProposal", "ProposalSummary"))
        self.assertEqual(self.state(), before, "calcular no registra nada ni deja un temporal")
        self.assertEqual(self.view.summary_title, f"Trazado propuesto «{name}» en V01")
        summary, found = self.summary(), held.summary
        self.assertEqual(summary[0][0], f"Trazado propuesto «{name}» · perfil «PISTA_PRINCIPAL»: longitud de {self.i18n.format_number(found.length_m, 1)} m · cota de "
                                        f"{self.i18n.format_number(found.start_level_m, 2)} m al inicio y de {self.i18n.format_number(found.end_level_m, 2)} m al final")
        self.assertTrue(summary[1][0].startswith("Pendiente: media del "), summary[1])
        self.assertAlmostEqual(found.length_m, 40.0, delta=4.0, msg="de (10, 30) a (50, 30)")
        self.assertIn("capa de líneas 3D que puede editar en QGIS", summary[3][0])
        self.assertFalse(any(alert for _text, alert in summary[:4]))
        tail = summary[len(summary) - len(held.notices):]
        self.assertEqual([text for text, _alert in tail], [notice.text("es") for notice in held.notices], "todos los avisos de la propuesta llegan al resumen")
        self.assertTrue(any("holgura del pasillo" in text for text, _alert in tail), "la nota de la ruta lleva la holgura del pasillo")
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, f"Proposed route «{name}» in V01")
        self.assertTrue(self.summary()[0][0].startswith(f"Proposed route «{name}» · profile «PISTA_PRINCIPAL»: length "), self.summary()[0])
        self.i18n.set_language("es")
        self.panels.show_summary(held)

        self.assertEqual(self.create_propose(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ? AND json_extract(settings, '$.name') = ?", PROPOSE_TYPE, name)
        self.assertEqual(status, "done")
        records, lines = self.route_layer(name)
        self.assertEqual([(status, editable) for _uid, status, editable in records], [("current", 1)], "la capa es del usuario desde que se crea: editable en QGIS")
        self.assertEqual(lines, [(1, name)])
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertAlmostEqual(figures["des.road_length_m"], found.length_m, delta=1e-9 * found.length_m)
        self.assertAlmostEqual(figures["des.road_gradient_max_pct"], found.gradient_max_pct, delta=1e-9)
        self.assertEqual(self.surface_state(), surfaces, "ninguna superficie cambia (el hash de cada una, igual)")
        self.assertEqual(self.entity_state(), entities, "una propuesta no es una entidad: ni código, ni parámetros, ni capa de entidades o de ejes, ni declaración")
        self.assertEqual(self.table_state(road_ops.POINTS), self.layers_before[road_ops.POINTS], "la capa de los puntos no se toca")
        self.refresh()
        self.assertIn(self.dprov.dataset_name("rpl", name), [item[0] for item in self.panels.road_layers("AXIS_3D")], "el modo «eje 3D» de «Pista…» ofrece la capa propuesta")

    def test_d_a_mean_gradient_above_pm_only_warns_and_is_created_without_confirmation(self) -> None:
        """RF-017-17, RF-017-28, D-6 (M6): con el perfil de pm = 1 % sobre el terreno del 2 %, el resumen lo dice **en ámbar** con la media y el límite y que se crea sin confirmación (no graba ninguna superficie); la
        ventana de crear dice «Crear» y no «Confirmar y crear», ni pide ningún motivo; se crea sin confirmar y sin motivo, con la capa propuesta."""
        self.refresh()
        name = self.fresh()
        held = self.calculate_propose(self.pform(name=name, profile=STEEP.lower()))
        self.assertTrue(held.outcome.mean_exceeded)
        self.assertFalse(held.needs_mean_confirmation or held.needs_carriageway_confirmation)
        self.assertGreater(held.summary.gradient_mean_pct, held.summary.mean_limit_pct)
        alerts = [text for text, alert in self.summary() if alert and text.startswith("La pendiente media, del ")]
        self.assertTrue(alerts, self.summary())
        self.assertIn("pasa del 1,00 % del perfil: es solo un aviso", alerts[0])
        warned = [text for text, alert in self.summary()[len(self.summary()) - len(held.notices):] if alert and "pendiente media" in text and "perfil" in text]
        self.assertEqual(len(warned), 1, "también como aviso del trazado, con sus tramos")
        self.assertIn("es solo un aviso: la propuesta no cambia ninguna superficie y se crea sin confirmación", warned[0])
        self.assertNotIn("no se crea sin su confirmación", warned[0], "el aviso de la pista pide confirmar; el de la propuesta, no")
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        window = self.fake_propose(confirm=True)
        self.assertEqual(self.propose.invoke(window, context, None), {"RUNNING_MODAL"})
        self.assertTrue(dialog.call_args.kwargs["confirm_text"].startswith("Crear"), dialog.call_args.kwargs["confirm_text"])
        self.assertNotEqual(dialog.call_args.kwargs["confirm_text"], "Confirmar y crear")
        self.assertEqual(self.create_propose(), {"FINISHED"}, "sin confirmación ni motivo")
        records, lines = self.route_layer(name)
        self.assertEqual(([status for _uid, status, _editable in records], lines), (["current"], [(1, name)]))
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE op_type = ? AND json_extract(settings, '$.name') = ?", PROPOSE_TYPE, name)
        self.assertNotIn("road_confirmed", settings, "una propuesta no registra confirmaciones")

    # --- e: Esc, cancelar y lo que se rechaza ---------------------------------------------------

    def test_e_esc_in_calculating_and_in_each_event_of_creating_and_what_is_refused_leave_nothing(self) -> None:
        """RF-015-29, RF-017-30, RF-017-04, RF-015-08, RNF-017-06 (M6, M9): Esc **a mitad** de «Calcular» (antes del primer paso, a mitad y antes del último) y **en cada evento de «Crear»** responde y **no deja nada**: ni operación, ni dato, ni parámetro, ni cifra, ni temporal (0 transacciones); el cálculo se descarta, su resumen se vacía y se quita la vista previa; Cancelar
        la confirmación y lo que se rechaza —el nombre vacío o repetido, el origen que falta o que no está, un punto fuera de la rejilla, un parámetro de la ruta sin valor o que no es múltiplo del paso…— tampoco, y
        cada rechazo dice **la capa, la propuesta, el campo y el valor**."""
        self.refresh()
        before = self.state()
        entity = self.des_ops._entity_preview()
        self.addCleanup(entity.disable)

        def start(form: dict[str, Any]) -> Any:
            with mock.patch.object(self.des_ops, "_ask_confirmation"):
                self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **{**form, "in_steps": True}), {"RUNNING_MODAL"})
            return self.running_propose()

        events = step_modals.drive(start(self.pform(name="Esc de calcular")), bpy.context)[1]
        self.des_ops.discard_calculation()
        self.assertGreaterEqual(events, 3)
        self.assertEqual(self.state(), before)
        for cut in sorted({0, 1, events // 2, events - 1}):
            with self.subTest(calcular=cut):
                modal = start(self.pform(name="Esc de calcular"))
                if step_modals.drive(modal, bpy.context, stop_after=cut)[0] != {"RUNNING_MODAL"}:  # el número de eventos no es exacto de una vez a otra (las unidades casi instantáneas se agrupan por el reloj)
                    self.des_ops.discard_calculation()
                    continue
                self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
                self.assertIsNone(modal._steps)
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)

        self.calculate_propose(self.pform(name="Cancelada"))
        self.propose.cancel(operator_self(self.propose, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        self.calculate_propose(self.pform(name="Esc de crear"))
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
        total = step_modals.drive(self.running_propose(), bpy.context)[1]
        self.assertEqual(self.state()[:4] == before[:4], False, "la última llamada registra la propuesta")
        self.assertGreaterEqual(total, 3, "crear son varios eventos")
        created = "Esc de crear"
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ? AND json_extract(settings, '$.name') = ?", PROPOSE_TYPE, created), [(1,)])
        after_creating = self.state()
        for cut in range(total):  # Esc en cada evento de «Crear», también antes de la transacción final
            with self.subTest(crear=cut):
                name = self.fresh()
                before_cut = self.state()
                self.calculate_propose(self.pform(name=name))
                self.assertEqual(self.state(), before_cut)
                with mock.patch.object(self.des_ops, "_ask_confirmation"):
                    self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
                modal = self.running_propose()
                if step_modals.drive(modal, bpy.context, stop_after=cut)[0] != {"RUNNING_MODAL"}:  # acabó antes: el último evento no es exacto (lo guardado llegó)
                    self.assertEqual(len(self.route_layer_records(name)), 1)
                    continue
                self.assertEqual(self.state()[:4], before_cut[:4], "no escribe en el proyecto antes de la transacción final")
                self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                self.assertIn("Creación cancelada: el trazado no se ha propuesto y el cálculo se ha descartado; no queda nada a medias", modal.report_log)
                self.assertEqual(self.state(), before_cut, "Esc deja el proyecto como estaba, ni un temporal")
                self.assertEqual(self.temporaries(), [])
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.view.summary_title, "", "el resumen, vaciado")
                self.assertFalse(entity.enabled())
        self.assertNotEqual(after_creating, before)

        before = self.state()
        for changes, texts in (
                ({"name": " "}, ("Escriba el nombre del trazado propuesto",)),
                ({"name": "Esc de crear"}, ("«Esc de crear» ya es el nombre de una operación del diseño en V01", "des_rpl_esc_de_crear")),
                ({"origin_point": ""}, (f"Capa «{road_ops.POINTS}»", "no tiene valor")),
                ({"origin_point": "No existe"}, (f"La capa «{road_ops.POINTS}»", "«No existe»")),
                ({"destination_point": "Fuera"}, (f"Capa «{road_ops.POINTS}»", ".destination» = «Fuera»", "cae fuera de la rejilla")),
                ({"mesh": ""}, (f"Capa «{road_ops.POINTS}»", ".mesh_m»", "no tiene valor")),
                ({"mesh": "3"}, (f"Capa «{road_ops.POINTS}»", ".mesh_m» = 3 m", "no es un múltiplo entero del paso del proyecto (2 m)")),
                ({"turn": "-1"}, (f"Capa «{road_ops.POINTS}»", ".turn_m» = -1", "está fuera de su rango")),
                ({"origin_point": "Destino"}, (".destination» = «Destino»", "el origen y el destino son el mismo punto")),
                ({"mesh": "abc"}, ("«abc» no es un número",)),
                ({"search_budget": "10"}, (f"Capa «{road_ops.POINTS}»", "agotó su presupuesto de 10 estados expandidos", "no significa que no haya ruta"))):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(**{"name": "Rechazada", **changes}))
                for text in texts:
                    self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before, "lo rechazado no deja nada: 0 transacciones")
        with self.assertRaises(RuntimeError) as nobody:  # crear sin calcular antes
            self.create_propose()
        self.assertIn("No hay un cálculo abierto: calcule antes", str(nobody.exception))
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **self.form(name="Pista que no es un trazado", start=self.second_surface)), {"FINISHED"})
        road = self.des_ops.calculation()
        with self.assertRaises(RuntimeError) as other:  # el cálculo abierto es de una pista, no el de una propuesta
            self.create_propose()
        self.assertIn("No hay un cálculo abierto: calcule antes", str(other.exception))
        self.assertIs(self.des_ops.calculation(), road, "no toca el cálculo de otra orden")
        self.assertEqual(self.state(), before)
        self.des_ops.discard_calculation()

    # --- f: la vista previa -----------------------------------------------------------------------

    def test_f_the_preview_is_the_one_of_the_road_follows_the_dialog_and_goes_away(self) -> None:
        """RF-017-26, RF-015-26 (T28, M5): el botón «Vista previa» (la misma orden con ``preview``) activa la vista previa de la pista con lo pedido (``EntityPlan(road=RoadAsk(request=…))``: el origen, el destino y
        el pasillo de la ruta, sin sección) sin escribir nada; el ``update`` de cada campo la redibuja con lo que dice ahora el diálogo (y uno a medias no la cambia); se quita al **cancelar** la orden, con **Esc** a
        mitad del cálculo y al **crear**."""
        entity = self.des_ops._entity_preview()
        self.addCleanup(entity.disable)
        self.refresh()
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name="Previa", preview=True)), {"FINISHED"})
        self.assertTrue(entity.enabled())
        plan = entity.plan()
        self.assertEqual((plan.kind, plan.road.request.name, plan.road.request.origin, plan.road.request.mesh_m, str(plan.road.request.mode)), ("road", "Previa", "Origen", 4.0, "trace"))
        self.assertIsNone(plan.road.prepared)
        self.assertEqual(self.state(), before, "la vista previa no escribe")
        self.des_ops._refresh_propose_preview(self.fake_propose(name="Previa 2", **road_ops.ROUTE, origin_point="Origen", destination_point="Destino norte"), None)
        self.assertEqual((entity.plan().road.request.name, entity.plan().road.request.destination), ("Previa 2", "Destino norte"))
        self.des_ops._refresh_propose_preview(self.fake_propose(name="Previa 3", mesh="abc"), None)
        self.assertEqual(entity.plan().road.request.name, "Previa 2", "un diálogo a medias no cambia la vista previa")
        self.des_ops._refresh_propose_preview(self.fake_propose(name=""), None)
        self.assertEqual(entity.plan().road.request.name, "Previa 2")
        with self.assertRaises(RuntimeError) as refused:
            bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name=" ", preview=True))
        self.assertIn("Escriba el nombre del trazado propuesto", str(refused.exception))
        self.assertEqual(entity.plan().road.request.name, "Previa 2", "lo que falta no toca la vista previa")

        self.calculate_propose(self.pform(name="Previa 2", destination_point="Destino norte"))
        self.assertTrue(entity.enabled(), "tras calcular sigue el pasillo")
        self.propose.cancel(operator_self(self.propose, confirm=True, in_steps=False), bpy.context)
        self.assertFalse(entity.enabled(), "se quita al cancelar")
        self.assertIsNone(self.des_ops.calculation())

        self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name="Esc previa", preview=True)), {"FINISHED"})
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name="Esc previa", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running_propose()
        self.assertEqual(modal.modal(bpy.context, step_modals.TIMER), {"RUNNING_MODAL"})
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertFalse(entity.enabled(), "se quita con Esc a mitad del cálculo")

        name = self.fresh()
        self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name=name, preview=True)), {"FINISHED"})
        self.calculate_propose(self.pform(name=name))
        self.assertTrue(entity.enabled())
        self.assertEqual(self.create_propose(), {"FINISHED"})
        self.assertFalse(entity.enabled(), "se quita al crear la propuesta")

    # --- g: crear por pasos y el nombre de la capa -------------------------------------------------

    def test_g_creating_runs_by_steps_with_the_result_of_creating_at_once_and_the_name_of_the_layer_is_unique(self) -> None:
        """RNF-017-06, RF-017-30, RF-017-28, RF-015-02 (M9): «Crear» desde la interfaz son varios eventos con su avance, **no escribe en el proyecto antes de lo guardado** y da lo mismo que de una vez (la misma
        capa, las mismas cifras) **sin encadenar lo que sigue a crear una entidad** (ninguna capa de entidades ni de ejes: una propuesta no lo es); el informe dice la capa; el nombre de la capa propuesta es único en
        la versión (``des.operation_name_repeated``, que dice la capa, con 0 transacciones) y otra propuesta con la misma superficie de partida **sí** se puede: una propuesta no es de ninguna cadena."""
        self.refresh()
        entity = self.des_ops._entity_preview()
        self.addCleanup(entity.disable)
        first, second = self.fresh(), self.fresh()
        self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name=first, preview=True)), {"FINISHED"})
        self.calculate_propose(self.pform(name=first))
        self.assertTrue(entity.enabled())
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
        modal = self.running_propose()
        before, entities = self.state(), self.entity_state()
        self.assertEqual(modal._status_text(self.progress(400)), "Guardando la propuesta del trazado… 40 % · Esc: cancelar")
        state, events = step_modals.drive(modal, bpy.context)
        self.assertEqual(state, {"FINISHED"})
        self.assertGreaterEqual(events, 3)
        self.assertGreaterEqual(len(modal.progress_log), 3)
        self.assertEqual(modal.progress_log[-1][2], modal.progress_log[-1][3], "el avance llega al final")
        self.assertFalse(entity.enabled(), "la vista previa se quita en cuanto lo guardado llega: la propuesta ya existe")
        self.assertEqual(modal.report_log, [f"Trazado «{first}» propuesto en V01: la capa «{self.table_of(first)}» se puede editar en QGIS"])
        self.assertNotEqual(self.state()[:4], before[:4])
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.view.summary_title, "")
        stepped = self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = (SELECT uid FROM gb_operation WHERE op_type = ? AND json_extract(settings, '$.name') = ?) ORDER BY key",
                            PROPOSE_TYPE, first)
        self.calculate_propose(self.pform(name=second))
        self.assertEqual(self.create_propose(), {"FINISHED"})
        at_once = self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = (SELECT uid FROM gb_operation WHERE op_type = ? AND json_extract(settings, '$.name') = ?) ORDER BY key",
                            PROPOSE_TYPE, second)
        self.assertEqual(stepped, at_once, "las mismas cifras de una vez y por pasos")
        self.assertEqual(self.route_layer(first)[1], [(1, first)])
        self.assertEqual(self.route_layer(second)[1], [(1, second)])
        self.assertEqual(self.entity_state(), entities, "ni la capa de entidades ni la de ejes: una propuesta no es una entidad")

        before = self.state()
        with self.assertRaises(RuntimeError) as repeated:
            bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name=first))
        self.assertIn(f"«{first}»", str(repeated.exception))
        self.assertIn("des_rpl_", str(repeated.exception))
        self.assertEqual(self.state(), before, "0 transacciones")
        with self.assertRaises(RuntimeError) as other_case:  # el mismo nombre en ASCII
            bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name=first.upper()))
        self.assertIn("des_rpl_", str(other_case.exception))
        self.assertEqual(self.state(), before)

    # --- h: desactivadas con su motivo --------------------------------------------------------------

    def test_h_the_commands_are_disabled_with_their_reason(self) -> None:
        """RF-017-29, RF-015-28, RF-009-05, RF-009-21, H-9 (M6): «Proponer el trazado…» —con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable (V02 SUPERADO: «V02 está en
        estado SUPERADO: …», que dice también su descripción)— sale desactivada con su motivo y no se puede lanzar; **sin versión activa** el diálogo no abre: dice que hace falta una y la ventana que la pide
        (RF-009-05); con V01 en escritura, activa. «Exportar pista…» **no es una operación**: está activa con el proyecto abierto también en solo lectura y con la versión superada, y desactivada con su motivo sin
        proyecto. Ninguna deja nada."""
        messages: list[str] = []
        cls, export = self.propose, self.export
        self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(bpy.ops.geoblender.des_propose_road.poll())
        self.assertTrue(bpy.ops.geoblender.des_export_road.poll())

        def poll(order: Any = cls) -> bool:
            messages.clear()
            with mock.patch.object(order, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                return bool(order.poll(bpy.context))

        self.assertTrue(poll())
        self.assertEqual(messages, [])
        before = self.state()
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(poll())
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_propose_road.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name="No debe"))
            self.assertEqual(self.state(), before)
            self.assertTrue(poll(export), "exportar no es una operación: vale en solo lectura (fuera del proyecto)")
            self.assertEqual(messages, [])
        self.assertTrue(poll())
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", (road_ops.REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        not_editable = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertFalse(poll())
        self.assertEqual(messages, [not_editable])
        self.assertFalse(bpy.ops.geoblender.des_propose_road.poll())
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        self.assertTrue(poll(export), "con la versión superada también se exporta")
        reported: list[str] = []
        refused = operator_self(cls, report=lambda kind, text: reported.append(text), confirm=False, in_steps=False)
        self.assertEqual(cls.invoke(refused, SimpleNamespace(window=None), None), {"CANCELLED"})
        self.assertEqual(reported, [not_editable])
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.assertTrue(poll())

        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=""), {"FINISHED"})  # sin versión activa
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertTrue(poll(), "sin versión activa la orden está activa: la pide al lanzarla (RF-009-05)")
        with mock.patch.object(self.session, "open_version_dialog") as asked:
            reported.clear()
            nobody = operator_self(cls, report=lambda kind, text: reported.append(text), confirm=False, in_steps=False)
            self.assertEqual(cls.invoke(nobody, SimpleNamespace(window=None), None), {"CANCELLED"})
            asked.assert_called_once()
            self.assertEqual(reported, [], "la ventana que pide la versión es lo que dice")
            asked.reset_mock()
            with self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", name="Sin versión")
            self.assertIn(self.session.version_required_text(), str(caught.exception))
        self.assertEqual(self.state(), before)
        self.assertTrue(poll(export))
        with self.assertRaises(RuntimeError) as without:  # exportar de ninguna versión
            bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", source="RDW-001", filepath=str(Path(tempfile.gettempdir()) / "x.tif"))
        self.assertIn("No hay versión activa", str(without.exception))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        with mock.patch.object(self.session.SESSION, "unavailable", return_value="Abra un proyecto"):
            self.assertFalse(poll(export), "sin proyecto, no está disponible")
            self.assertEqual(messages, ["Abra un proyecto"])

    # --- i: exportar ------------------------------------------------------------------------------

    def a_road_and_an_accessibility(self) -> tuple[str, str]:
        """Una pista calculada («trazar» sobre ``Suave``) y una accesibilidad calculada sobre ella, de V01, reales (las dos órdenes de «Diseño»); una sola vez por clase. Devuelve sus nombres."""
        if not type(self).exported:
            self.refresh()
            self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **self.form(name="Pista que se exporta", start=self.second_surface)), {"FINISHED"})
            self.assertEqual(self.create_road(), {"FINISHED"})
            self.finish_chain()
            self.refresh()
            self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", name="Alcance que se exporta", surface=self.smooth_surface, layer=ENTRIES, **THRESHOLDS, in_steps=False),
                             {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
            self.finish_chain()
            self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **platform_ops.CreatePlatformTest.form(self, name=PLATFORM)), {"FINISHED"})  # lo que no es una pista
            self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
            self.finish_chain()
            type(self).exported = {"road": "Pista que se exporta", "access": "Alcance que se exporta"}
        return type(self).exported["road"], type(self).exported["access"]

    def finish_chain(self) -> None:
        """Lo que sigue a crear una entidad (la declaración, las máscaras y las capas), si quedó en un modal (desde un guion no lo hay)."""
        for modal in [op for op in bpy.context.window.modal_operators if getattr(op, "_steps", None) is not None]:
            for _ in range(step_modals.MAX_EVENTS):
                if modal.modal(bpy.context, step_modals.TIMER) != {"RUNNING_MODAL"}:
                    break

    def test_i_export_road_writes_the_surface_the_gradient_and_the_reach_and_nothing_in_the_project(self) -> None:
        """RF-017-27, H-9, RF-017-29, RF-008-15 (D-29 de la 011; M6): «Exportar pista…» escribe **la superficie de una pista** y **lo que alcanza una accesibilidad** como GeoTIFF (en el CRS del proyecto, con la
        leyenda de lo alcanzable) y **la rasante** a CSV (abscisa, x, y, cota del terreno, cota de la rasante y pendiente, en m y en %) **sin escribir nada en el proyecto** (operaciones, datos, parámetros, cifras y
        ficheros, igual); desde la interfaz, por pasos con el avance y Esc; dice en el informe qué escribió y dónde; propone ``exports/<dato>_V01`` con la extensión de lo que se exporta; sobre un fichero que ya
        existe, solo con «Sustituir» (y, con ventana, lo pregunta); rechaza lo que no es una pista calculada ni la accesibilidad, un destino que no cabe y la carpeta de solo lectura; y con el proyecto en solo
        lectura exporta fuera de él."""
        road, access = self.a_road_and_an_accessibility()
        out = Path(tempfile.mkdtemp(prefix="gb-t33-"))
        self.addCleanup(remove_tree, out)
        reader = platform_ops._module("gis.geotiff.reader")
        before = self.state()
        surfaces = self.surface_state()
        self.assertEqual(self.export.poll(bpy.context), True)

        for what, source, name, expected in (("SURFACE", road, "superficie.tif", f"Superficie de la pista exportada a «superficie.tif»"),
                                             ("REACH", access, "alcance.tif", "Lo que alcanza la accesibilidad, exportado a «alcance.tif»")):
            with self.subTest(exportar=what):
                target = out / name
                self.assertEqual(bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what=what, source=source, filepath=str(target), in_steps=True), {"RUNNING_MODAL"})
                found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.export) and getattr(op, "_steps", None) is not None]
                self.assertEqual(len(found), 1)
                modal = found[0]
                self.assertEqual(modal._status_text(self.progress(400)), f"Exportando «{name}»… 40 % · Esc: cancelar")
                state, events = step_modals.drive(modal, bpy.context)
                self.assertEqual(state, {"FINISHED"})
                self.assertGreaterEqual(events, 1)
                self.assertGreater(len(modal.progress_log), 2, "dice su avance")
                self.assertEqual(modal.progress_log[-1][2:4], (1000, 1000))
                self.assertEqual(modal.report_log, [expected])
                raster = reader.read_geotiff(target, max_cells=10 ** 7)
                self.assertEqual((raster.declared_crs.epsg, raster.source_dtype, raster.nodata_value), (self.project.record.crs_epsg, "float32", -9999.0))
                self.assertTrue(np.isfinite(raster.values).any(), what)
        reach = reader.read_geotiff(out / "alcance.tif", max_cells=10 ** 7)
        codes = set(np.unique(reach.values[np.isfinite(reach.values)]).tolist())
        self.assertEqual((1.0 in codes, codes <= {0.0, 1.0}), (True, True), "lo alcanzable: 1 alcanzable y 0 no")
        target = out / "rasante.csv"
        self.assertEqual(bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="GRADIENT", source=road, filepath=str(target)), {"FINISHED"})
        data = target.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"), "UTF-8 con BOM")
        lines = data.decode("utf-8-sig").split("\r\n")
        self.assertEqual(lines[0], "Abscisa (m);X (m);Y (m);Cota del terreno (m);Cota de la rasante (m);Pendiente (%)")
        self.assertGreater(len(lines), 5)
        first = lines[1].split(";")
        self.assertEqual((len(first), first[0]), (6, "0"), "una fila por estación: la abscisa 0 es la primera")
        self.assertEqual(sorted(item.name for item in out.iterdir()), ["alcance.tif", "rasante.csv", "superficie.tif"])
        self.assertEqual((self.state(), self.surface_state()), (before, surfaces), "no escribe nada en el proyecto: ni una operación, un dato, un parámetro, una cifra ni un fichero")

        # Lo que se exporta se elige por el código o por el nombre de la entidad, y lo alcanzable, también por su dato (el del objeto de la vista).
        domain = platform_ops._module("design.export")
        by_code = domain.stored_road_export(self.project, "surface", "RDW-001", version=self.v01.uid)
        by_name = domain.stored_road_export(self.project, "surface", road, version="V01")
        self.assertEqual((by_code.record.uid, by_code.family), (by_name.record.uid, self.dprov.ENTITY_SURFACE_GRID))
        reached = domain.stored_road_export(self.project, "reach", "ACC-001", version=self.v01.uid)
        self.assertEqual(reached.family, self.dprov.ACCESS_GRID)
        self.assertEqual(domain.stored_road_export(self.project, "reach", reached.record.uid, version=self.v01.uid).record.uid, reached.record.uid)
        self.assertEqual(domain.stored_road_export(self.project, "gradient", "RDW-001", version=self.v01.uid).record.name, self.dprov.dataset_name("rdx", road))
        with self.assertRaises(ValueError):
            domain.stored_road_export(self.project, "everything", road, version=self.v01.uid)
        with self.assertRaises(ValueError):
            domain.stored_road_export(self.project, "surface", road, version="")
        self.assertEqual((self.state(), self.surface_state()), (before, surfaces), "elegirlo no escribe nada")

        # El informe de la orden de un guion, el que ya existe y lo que se rechaza.
        reports: list[str] = []
        exact = operator_self(self.export, report=lambda kind, text: reports.append(text), what="GRADIENT", source=road, filepath=str(out / "otra.csv"), overwrite=False, confirm=False, in_steps=False)
        self.assertEqual(self.export.execute(exact, bpy.context), {"FINISHED"})
        self.assertEqual(exact.report_log, ["Rasante de la pista exportada a «otra.csv»"])
        kept = (out / "rasante.csv").read_bytes()
        with self.assertRaises(RuntimeError) as there:
            bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="GRADIENT", source=road, filepath=str(out / "rasante.csv"))
        self.assertIn("Ya existe «rasante.csv»", str(there.exception))
        self.assertEqual((out / "rasante.csv").read_bytes(), kept)
        self.assertEqual(bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="GRADIENT", source=road, filepath=str(out / "rasante.csv"), overwrite=True), {"FINISHED"})
        self.assertEqual((out / "rasante.csv").read_bytes(), kept, "sustituirlo da lo mismo")
        with mock.patch.object(self.des_ops, "_confirm_later") as later:  # con ventana, lo pregunta
            self.assertEqual(bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="GRADIENT", source=road, filepath=str(out / "rasante.csv"), in_steps=True), {"CANCELLED"})
        later.assert_called_once_with({"what": "GRADIENT", "source": road, "filepath": str(out / "rasante.csv")}, idname=EXPORT)
        for label, values, word in (
                ("sin pista", {"what": "SURFACE", "source": "", "filepath": str(out / "x.tif")}, "Elija la pista o la accesibilidad que exportar"),
                ("sin fichero", {"what": "SURFACE", "source": road, "filepath": ""}, "Elija el fichero"),
                ("una pista que no está", {"what": "SURFACE", "source": "No existe", "filepath": str(out / "x.tif")}, "No existe"),
                ("una plataforma, que no es una pista", {"what": "SURFACE", "source": PLATFORM, "filepath": str(out / "x.tif")}, f"no tiene la pista «{PLATFORM}» calculada"),
                ("la rasante de una accesibilidad", {"what": "GRADIENT", "source": access, "filepath": str(out / "x.csv")}, "no tiene la pista"),
                ("lo alcanzable de una pista", {"what": "REACH", "source": road, "filepath": str(out / "x.tif")}, "no es una rejilla viva del diseño"),
                ("la rasante a un GeoTIFF", {"what": "GRADIENT", "source": road, "filepath": str(out / "x.tif")}, "x.tif"),
                ("la superficie a un CSV", {"what": "SURFACE", "source": road, "filepath": str(out / "x.csv")}, "x.csv"),
                ("dentro del proyecto", {"what": "SURFACE", "source": road, "filepath": str(Path(self.project.root) / "x.tif")}, "x.tif")):
            with self.subTest(rechazo=label):
                with self.assertRaises(RuntimeError) as raised:
                    bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", **values)
                self.assertIn(word, str(raised.exception))
        with mock.patch.dict(os.environ, {"GEOBLENDER_READ_ONLY_DIRS": str(out)}):  # RF-008-15
            with self.assertRaises(RuntimeError) as raised:
                bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="GRADIENT", source=road, filepath=str(out / "protegida.csv"))
        self.assertIn("solo lectura", str(raised.exception))
        self.assertEqual(sorted(item.name for item in out.iterdir()), ["alcance.tif", "otra.csv", "rasante.csv", "superficie.tif"])
        self.assertEqual((self.state(), self.surface_state()), (before, surfaces))

        # Esc a mitad de la escritura de un GeoTIFF: ni el fichero ni su temporal.
        half = out / "a_medias.tif"
        with mock.patch.object(platform_ops._module("gis.geotiff.writer"), "TILE_SIZE", 16), mock.patch.object(self.export, "STEP_BUDGET_S", 1e-9):
            self.assertEqual(bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="SURFACE", source=road, filepath=str(half), in_steps=True), {"RUNNING_MODAL"})
            modal = [op for op in bpy.context.window.modal_operators if isinstance(op, self.export) and getattr(op, "_steps", None) is not None][0]
            self.assertEqual(step_modals.drive(modal, bpy.context, stop_after=3)[0], {"RUNNING_MODAL"})
            self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIsNone(modal._steps)
        self.assertIn("Exportación cancelada: no se ha escrito nada", modal.report_log)
        self.assertFalse(half.exists())
        self.assertEqual([item.name for item in out.iterdir() if ".tmp" in item.name], [])

        # Con el proyecto en solo lectura exporta fuera de él, y dentro no.
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertTrue(self.export.poll(bpy.context))
            self.assertEqual(bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="GRADIENT", source=road, filepath=str(out / "solo_lectura.csv")), {"FINISHED"})
            with self.assertRaises(RuntimeError) as raised:
                bpy.ops.geoblender.des_export_road("EXEC_DEFAULT", what="GRADIENT", source=road, filepath=str(Path(self.project.root, "exports", "x.csv")))
            self.assertIn("solo lectura", str(raised.exception))
        self.assertTrue((out / "solo_lectura.csv").is_file())

    def test_j_the_dialog_of_export_road_proposes_the_file_by_what_is_exported(self) -> None:
        """RF-017-27, RF-017-29 (M6): el diálogo de «Exportar pista…» abre el selector de ficheros con el destino que propone (``exports/<dato>_V01`` y la extensión de lo que se exporta: ``.tif`` la superficie y lo
        alcanzable, ``.csv`` la rasante) y la pista o la accesibilidad que eligió; cambiar qué se exporta con el selector abierto cambia la extensión (``check``); sin pista, lo dice; con ``confirm``, pregunta
        si sustituir el fichero que ya existe."""
        road, access = self.a_road_and_an_accessibility()
        reports: list[str] = []
        manager = SimpleNamespace(fileselect_add=mock.Mock(), invoke_confirm=mock.Mock(return_value={"RUNNING_MODAL"}))
        context = SimpleNamespace(window=platform_ops.window(), window_manager=manager, active_object=None, selected_objects=())
        cls = self.export
        for what, source, stem, suffix in (("SURFACE", road, "des_psf_pista_que_se_exporta", ".tif"), ("GRADIENT", "RDW-001", "des_rdx_pista_que_se_exporta", ".csv"),
                                           ("REACH", access, "des_acc_alcance_que_se_exporta", ".tif")):
            with self.subTest(what=what):
                manager.fileselect_add.reset_mock()
                fake = operator_self(cls, report=lambda kind, text: reports.append(text), what=what, source=source, filepath="", overwrite=False, confirm=False, in_steps=False)
                self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
                manager.fileselect_add.assert_called_once_with(fake)
                self.assertEqual(Path(fake.filepath), Path(self.project.root, "exports", f"{stem}_V01{suffix}"))
                self.assertTrue(fake.in_steps)
        fake = operator_self(cls, report=lambda kind, text: reports.append(text), what="SURFACE", source="", filepath="", overwrite=False, confirm=False, in_steps=False)
        self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(reports, ["Elija la pista o la accesibilidad que exportar: seleccione su objeto en la Vista 3D o dé su código o su nombre"])
        fake = operator_self(cls, report=lambda kind, text: reports.append(text), what="SURFACE", source=road, filepath="C:/x/y.tif", overwrite=False, confirm=True, in_steps=True)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertTrue(fake.overwrite)
        self.assertEqual(manager.invoke_confirm.call_args.kwargs["title"], "Sustituir el fichero")
        changing = operator_self(cls, what="GRADIENT", filepath=str(Path("C:/x/y.tif")))
        self.assertTrue(cls.check(changing, context))
        self.assertEqual(Path(changing.filepath), Path("C:/x/y.csv"), "la rasante es un CSV")
        self.assertFalse(cls.check(changing, context))
        back = operator_self(cls, what="REACH", filepath=str(Path("C:/x/y.csv")))
        self.assertTrue(cls.check(back, context))
        self.assertEqual(Path(back.filepath), Path("C:/x/y.tif"))
        self.assertFalse(cls.check(operator_self(cls, what="SURFACE", filepath=""), context))
        self.assertFalse(cls.check(operator_self(cls, what="SURFACE", filepath=str(Path("C:/x/y.tiff"))), context))

    def test_k_a_value_of_the_profile_that_changes_between_calculating_and_creating_is_refused(self) -> None:
        """RF-013-17, RF-017-28, D-14 de la 013 (M6): el resultado de «Calcular» es de los valores del perfil que leyó (los que anota la operación): si uno cambia **entre calcular y crear**, «Crear» no registra
        nada (``des.input_changed``, con el parámetro) y descarta el cálculo; con el valor de antes, se crea."""
        self.refresh()
        key = "des.roadprofile.pista_principal.max_gradient_pct"

        def change(value: str) -> set[str]:
            return bpy.ops.geoblender.core_set_parameter("EXEC_DEFAULT", key=key, value=value, scope="VERSION", decided_by=platform_ops.PERSON, reason=road_ops.REASON,
                                                         source="Criterio de la prueba")

        name = self.fresh()
        held = self.calculate_propose(self.pform(name=name))
        self.assertIn(key, held._values)
        self.assertEqual(change("9"), {"FINISHED"})
        before = self.state()
        with self.assertRaises(RuntimeError) as caught:
            self.create_propose()
        self.assertIn(key, str(caught.exception))
        self.assertIn("el resultado ya no le corresponde", str(caught.exception))
        self.assertIsNone(self.des_ops.calculation(), "el cálculo se descarta")
        self.assertEqual(self.state(), before, "no registra nada")
        self.assertEqual(self.route_layer_records(name), [])
        self.assertEqual(change("10"), {"FINISHED"})
        self.calculate_propose(self.pform(name=name))
        self.assertEqual(self.create_propose(), {"FINISHED"})
        self.assertEqual(len(self.route_layer_records(name)), 1)

    def route_layer_records(self, name: str) -> list[tuple[Any, ...]]:
        return self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name("rpl", name))

    # --- z: desactivar ---------------------------------------------------------------------------

    def test_z_disabling_geoblender_removes_the_commands_and_the_open_calculation(self) -> None:
        """Principio 8, D-14 de la 013, RF-015-26: con un cálculo abierto y la vista previa activa, desactivar Geoblender los descarta (no queda ningún temporal ni vista previa) y quita las dos órdenes."""
        self.refresh()
        entity = self.des_ops._entity_preview()
        self.assertEqual(bpy.ops.geoblender.des_propose_road("EXEC_DEFAULT", **self.pform(name="Al apagar", preview=True)), {"FINISHED"})
        self.calculate_propose(self.pform(name="Al apagar"))
        self.assertTrue(entity.enabled())
        blender_ext.release()
        for name in (PROPOSE_CLASS, EXPORT_CLASS):
            self.assertIsNone(getattr(bpy.types, name, None))
        self.assertFalse(entity.enabled())
        self.assertFalse(any(".tmp" in name for name in self.names()))


# Las pruebas de la plataforma y las de la pista son de ``test_platform_ops.py`` y ``test_road_ops.py``: aquí solo se aprovecha su proyecto.
for _name in dir(road_ops.RoadOpsTest):
    if _name.startswith("test_") and _name not in RoadExtraOpsTest.__dict__:
        setattr(RoadExtraOpsTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
