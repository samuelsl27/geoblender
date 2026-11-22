# SPDX-License-Identifier: GPL-3.0-or-later
"""«Pista…» en Blender (spec 017, T29b; HU-017-1, HU-017-2, HU-017-4; RF-017-29, RF-017-17, RF-017-22, RF-017-02, RF-015-28; plan 017 §5.3.3 y §5.5; comprobación manual M1).

:class:`GEOBLENDER_OT_des_create_road` (``geoblender.des_create_road``) calcula con ``design.steps.road_run`` la operación ``des.road`` de la versión activa: el eje, la rasante y
la sección grabada en su superficie de partida, de un origen a un destino («trazar»), sobre un eje o sobre un eje 3D. Su diálogo pide el nombre y el modo; la capa, el origen y el
destino (un punto, el eje de otra pista a una abscisa, una plataforma o una cota con su zona y su tolerancia); el perfil; la partida y el apoyo; las cotas de inicio y de fin y los
parámetros de la ruta, cada uno con su tipo. Calcular, Crear, Cancelar y Esc son los de las demás órdenes (``_CalculateAndCreate``): nada se registra hasta Crear. Con la pendiente
media por encima de la del perfil o la calzada fuera de su rasante no se crea sin la confirmación expresa (y, la media, sin su motivo). Es el modelo de ``CreateTransitionsTest`` y de
``test_platform_ops.py``: aprovecha su proyecto (60 × 60 m con celdas de 2 m, V01 y V02, el límite legal, el perímetro y un sector con la búsqueda cerrada) y le añade dos terrenos
(``Suave``, de ``100 + 0,02·(x + y)``, y ``A15``, de ``100 + 0,105·x``), las capas de la pista (puntos, ejes y zonas) y los perfiles de referencia de IMGA (**solo para pruebas**:
``tests.support.road_data.PROFILE``; los parámetros de la ruta de ``ROUTE``, con la penalización de giro, la holgura, la simplificación y la llegada como HIPÓTESIS de la prueba).
Las pruebas, en el orden de sus letras sobre el mismo estado.

- RF-017-29, RF-015-28 (a): la orden es real, del catálogo (entrada 017, entregada); sus propiedades tienen nombre y descripción; el diálogo propone el nombre, la capa del modo, el perfil
  y la partida; dibuja los campos de cada modo, con el tipo de cada parámetro de la ruta.
- RF-017-02 (b): la petición del diálogo —el origen, el destino y la cota con su zona— es la que arma ``RoadRequest``, en los tres modos.
- RF-017-01, RF-017-23, RF-015-03 (c): Calcular deja el cálculo abierto, con su resumen (con todos los avisos) y nada en el proyecto; Crear registra ``des.road`` con su eje, su huella
  y su informe, la capa de entidades y la de ejes; las cotas que da la persona quedan como suyas y las demás con su origen.
- RF-017-17, RF-017-22 (d): la pendiente media por encima de la del perfil no se crea sin su confirmación expresa ni, sin su motivo, con ella; con él se crea y queda en los ajustes.
- RF-015-29, RF-017-30, RF-017-04 (e): Esc a mitad, Cancelar la confirmación y lo que se rechaza no dejan nada (0 transacciones).
- RF-017-26, RF-015-26 (f): «Vista previa» y sus campos; tras calcular, le da lo calculado; se quita al cancelar, con Esc y al crear.
- RF-017-03 (g): un ramal parte del eje de otra pista a una abscisa; la pista a una cota y su zona (la rampa).
- RF-015-08, RF-015-01, RF-017-27, RF-017-03, D-13 (g·b, T29c): «Cambiar parámetro…» de una pista: renombrarla funciona, no la deja obsoleta y la capa de ejes dice el nombre nuevo; el nombre vacío o repetido
  se rechaza sin escribir; la cota que da a mano la persona queda suya.
- RF-017-04, RF-017-07, RF-015-15, RF-017-03 (g·c y g·d, T40 y T49): «Cambiar parámetro…» de un valor del perfil (con el ámbito de la versión **y el del proyecto**), del origen y de las dependencias
  declaradas de una pista rechaza lo que rechazaría crearla, sin escribir; el gancho del núcleo llama sin versión solo a la comprobación que lo pidió (``project_scope``).
- RF-017-29, RF-015-28 (h): la orden sale desactivada con su motivo con el proyecto en solo lectura, con la versión activa no editable y sin versión activa.
- RF-017-26, RF-017-30 (i, T45; D-3): «Crear» **por pasos** desde la interfaz (la vía real) quita la vista previa en cuanto lo guardado llega.
- Principio 8 (z): desactivar Geoblender quita la orden y no deja nada.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import functools
import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support import road_data as rd
from tests.support.fake_layout import draw, operator_self

ROAD = "geoblender.des_create_road"
ROAD_CLASS = "GEOBLENDER_OT_des_create_road"
ROAD_TYPE = "des.road"
PERSON = platform_ops.PERSON
REASON = "Prueba de la orden «Pista…»"
POINTS = "gis_fea_pistas_puntos"
AXES = "gis_fea_pistas_ejes"
ZONES = "gis_fea_pistas_zonas"
POINT_LAYER_ROWS = (("Origen", (10.0, 30.0)), ("Destino", (50.0, 30.0)), ("Destino norte", (30.0, 50.0)), ("Origen sur", (10.0, 12.0)), ("Fuera", (-20.0, 30.0)))
"""Los puntos de las pistas (local): el origen y el destino de la primera, el destino del ramal, el origen de la rampa y uno fuera de la rejilla."""
AXIS_ROWS = (("Eje A15", ((10.0, 30.0), (50.0, 30.0))), ("Eje al borde", ((10.0, 50.0), (50.0, 50.0))))
ZONE_ROWS = (("Zona alta", (40.0, 40.0, 52.0, 52.0)),)
MAIN = "PISTA_PRINCIPAL"
A15_PROFILE = "ACCESO_A15"
FIRST = "Pista de la carga"
BRANCH = "Ramal al norte"
RAMP = "Rampa a la cota"
A15_ROAD = "Pista A15"
EDGE_ROAD = "Pista al borde"
ROUTE = {"mesh": "4", "level_step": "0,28", "max_cut_fill": "14", "lambda_weight": "2", "turn": "4", "margin": "60", "simplify": "4", "arrival_tol": "0,28"}
"""Los parámetros de la ruta de la referencia de IMGA tecleados como los teclea una persona (``tests.support.road_data.ROUTE``: solo pruebas)."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
HIDDEN = ("confirm", "in_steps", "preview", "confirm_mean", "confirm_carriageway", "code")
PROPERTIES = {  # la propiedad → su nombre y su descripción (msgid en inglés; en español al registrarse)
    "name": ("Name", "Name of the road, unique in the active version"),
    "mode": ("Mode", "Trace it from an origin to a destination, give it an axis in plan to fit the curves to, or give it a line with its Z whose Z is the level profile"),
    "layer": ("Layer", "Layer of the project the road is taken from: of points (trace), of lines (over an axis) or of 3D lines (3D axis: the breaklines of the project and the "
                       "proposed routes of the active version)"),
    "name_field": ("Name field", "Field of the layer with the name of each geometry (empty: the field «nombre» or «name» or, without it, the number (fid))"),
    "feature": ("Line of the layer", "Name or number (fid) of the line of the layer that is the axis of the road (over an axis and 3D axis)"),
    "origin_from": ("The origin is", "Whether the origin is a point of the layer or a point of the axis of another road, at an abscissa"),
    "origin_point": ("Origin point", "Name or number (fid) of the point of the layer that is the origin of the road"),
    "origin_road": ("Road of the origin", "Road of the active version whose axis the origin is on: the new road rests on it and becomes stale if it changes"),
    "origin_station": ("Abscissa of the origin (m)", "Distance along the axis of the other road, from its start, of the point where the new road starts, in metres"),
    "destination_to": ("It ends at", "Whether the road ends at a point of the layer, on a platform of the active version or where it reaches an elevation inside a zone"),
    "destination_point": ("Destination point", "Name or number (fid) of the point of the layer that is the destination of the road"),
    "destination_entity": ("Platform of the destination", "Platform of the active version the road ends at: its destination is the point of the layer that falls on its "
                                                          "footprint, at the level of its surface; the road rests on it"),
    "dest_level": ("Elevation of the destination (m)", "Elevation in metres the road has to reach: it ends at the first point of the zone whose start surface differs from it "
                                                       "by less than the arrival tolerance"),
    "dest_tol": ("Arrival tolerance of the elevation (m)", "How much the start surface may differ from the elevation of the destination where the road ends, in metres"),
    "dest_zone": ("Zone of the destination", "Layer of polygons of the project with the zone where the elevation has to be reached"),
    "dest_zone_feature": ("Polygon of the zone", "Name or number (fid) of the polygon of the layer that is the zone (empty: all the polygons of the layer)"),
    "profile": ("Road profile", "Profile of the road: its vehicle, its carriageway, its gradients, its radii and its slopes; create or complete them with «Road profile…»"),
    "start": ("Start surface", "Surface the road starts from: by default, the exploitation surface of the quarry and, without it, the last of the chain"),
    "support": ("Support surface", "Surface the road rests on, if it rests on one (none: it rests on no other surface)"),
    "start_level": ("Start level (m)", "Elevation of the level profile at the start of the road in metres (empty: the one of the start surface at that point, recorded with "
                                       "its origin; what you write is recorded as decided by you)"),
    "end_level": ("End level (m)", "Elevation of the level profile at the end of the road in metres (empty: the one of the start surface at that point or of the platform of the "
                                   "destination, recorded with its origin; what you write is recorded as decided by you)"),
    "mesh": ("Mesh of the route (m)", "Side of the blocks of the grid in which the route is searched, in metres: a whole multiple of the step of the project; a hypothesis "
                                      "without default value"),
    "level_step": ("Elevation step (m)", "Step of the elevations the route can take above or below the ground, in metres; a hypothesis without default value"),
    "max_cut_fill": ("Maximum cut and fill height (m)", "Most the level profile of the route may be above or below the ground, in metres; a hypothesis without default value"),
    "lambda_weight": ("Weight of the earthworks (1/m)", "How much the cost of the route grows with the height of cut and fill, in 1/m; a hypothesis without default value"),
    "turn": ("Turn penalty (m)", "Length added to the cost of the route for each change of heading, in metres; a hypothesis without default value"),
    "margin": ("Margin of the corridor (m)", "How much longer than the shortest route the routes inside the corridor can be, in metres: the route changes with it; a "
                                              "hypothesis without default value"),
    "simplify": ("Simplification tolerance (m)", "Most the simplified axis may separate from the route, in metres; a hypothesis without default value"),
    "arrival_tol": ("Arrival tolerance of the route (m)", "How far from the destination elevation the route may end, in metres; a hypothesis without default value"),
    "search_budget": ("Budget of states", "Most states the search of the route may expand before it stops saying so: a whole number (empty: the default value, shown)"),
    "mean_reason": ("Reason for the mean gradient", "Why you accept a mean gradient above the maximum of the profile: it stays recorded with who and when; it is needed only if "
                                                    "the mean gradient passes it"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone quien lanza la orden, no los llevan)."""
DEFAULTS: dict[str, Any] = {  # lo que dibuja el diálogo con un valor de cada propiedad (para los ``draw`` simulados)
    "name": FIRST, "mode": "TRACE", "layer": POINTS, "name_field": "", "feature": "", "origin_from": "POINT", "origin_point": "Origen", "origin_road": "none",
    "origin_station": "", "destination_to": "POINT", "destination_point": "Destino", "destination_entity": "none", "dest_level": "", "dest_tol": "", "dest_zone": "none",
    "dest_zone_feature": "", "profile": "pista_principal", "start": "", "support": "none", "start_level": "", "end_level": "", "mesh": "", "level_step": "",
    "max_cut_fill": "", "lambda_weight": "", "turn": "", "margin": "", "simplify": "", "arrival_tol": "", "search_budget": "", "mean_reason": "", "confirm": False,
    "in_steps": False, "preview": False, "confirm_mean": False, "confirm_carriageway": False, "code": ""}


def smooth() -> np.ndarray:
    """El terreno ``Suave``: ``100 + 0,02·(x + y)`` en los centros de celda (la pista se traza sin pasar de la pendiente de diseño)."""
    x, y = platform_ops.centers()
    return 100.0 + 0.02 * (x + y)


def a15() -> np.ndarray:
    """El terreno ``A15``: ``100 + 0,105·x`` (el 10,5 % a lo largo del eje: por encima de la pendiente media del perfil y por debajo de su pendiente de diseño)."""
    x, _y = platform_ops.centers()
    return 100.0 + 0.105 * x


class RoadOpsTest(platform_ops.CreatePlatformTest):
    """El proyecto de la prueba de la plataforma, con lo que necesita la pista (los terrenos, las capas y los perfiles). Las pruebas de la plataforma no se repiten."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smooth_surface = cls.write_grid("Suave", smooth())
        cls.a15_surface = cls.write_grid("A15", a15())
        cls.second_surface = cls.write_grid("Suave 2", smooth())
        for name, kind, rows in ((POINTS, "point", POINT_LAYER_ROWS), (AXES, "line", AXIS_ROWS), (ZONES, "polygon", ZONE_ROWS)):
            cls.write_feature_layer(name, kind, rows)
        cls.write_profiles()
        cls.layers_before = {name: cls.table_state(name) for name in (POINTS, AXES, ZONES)}
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        super().refresh()
        cls.panels.refresh_road_choices(cls.project)

    @classmethod
    def write_feature_layer(cls, name: str, kind: str, rows: tuple[Any, ...]) -> None:
        """La capa ``name`` de geometría ``kind`` (``point``, ``line`` o ``polygon``) con su campo ``nombre``, como la deja la importación de la 006."""
        gis_store, vector = platform_ops._module("gis.store"), platform_ops._module("gis.vector")
        datasets, builtin = platform_ops._module("core.datasets"), platform_ops._module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),)
        if kind == "point":
            parts = tuple(((platform_ops.path((point,)),),) for _name, point in rows)
        elif kind == "line":
            parts = tuple(((platform_ops.path(line),),) for _name, line in rows)
        else:
            parts = tuple(((platform_ops.ring(box),),) for _name, box in rows)
        layer = vector.FeatureLayer(kind, tuple(range(1, len(rows) + 1)), parts, columns, {"nombre": tuple(row[0] for row in rows)})
        records = gis_store.feature_rows(layer, srs)
        handle = platform_ops._module("core.provenance.operations").begin_operation(cls.project, platform_ops.LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, "nombre" TEXT)')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" VALUES (?, ?, ?)', records)
            handle.complete(conn, outputs=(datasets.DatasetSpec(name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
                                                                input_uid=None, immutable=False),), message="Capa de la pista de la prueba")

    @classmethod
    def table_state(cls, name: str) -> tuple[Any, ...]:
        """Una capa como está: su registro y todo el contenido de su tabla."""
        with cls.project.read() as conn:
            record = conn.execute("SELECT uid, status, content_sha256 FROM gb_dataset WHERE name = ?", (name,)).fetchall()
            table = conn.execute(f'SELECT * FROM "{name}" ORDER BY fid').fetchall()
        return record, table

    @classmethod
    def write_profiles(cls) -> None:
        """El perfil de referencia de IMGA (**solo de las pruebas**) y el de la «opción A15» (pd = 12 %, pm = 10 %) en V01."""
        profiles, dparams = platform_ops._module("design.road_profiles"), platform_ops._module("design.params")
        declared = profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", PERSON, REASON, version=cls.v01.code)
        for name, data in ((MAIN, rd.PROFILE), (A15_PROFILE, rd.profile_with(max_gradient_pct=12.0))):
            values = {param: getattr(data, "class_name" if param.value == "class" else param.value) for param in dparams.RoadProfileParam}
            profiles.edit_road_profiles(cls.project, (profiles.ProfileEdit(name=name, values=values),), declared)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def road(self) -> Any:
        return self.commands.registered_class(ROAD)

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo para la pista «trazar» de «Origen» a «Destino» sobre el terreno ``Suave`` con el perfil de referencia y la ruta de referencia."""
        return {"name": FIRST, "mode": "TRACE", "layer": POINTS, "origin_point": "Origen", "destination_point": "Destino", "profile": "pista_principal",
                "start": self.smooth_surface, **ROUTE, "in_steps": False, **values}

    def axis_form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido para la pista «sobre un eje» al 10,5 % con el perfil de pd = 12 % y pm = 10 %: lo que obliga a confirmar la media."""
        return {"name": A15_ROAD, "mode": "ON_AXIS", "layer": AXES, "feature": "Eje A15", "profile": A15_PROFILE.lower(), "start": self.a15_surface, "in_steps": False,
                **values}

    def calculate_road(self, form: dict[str, Any]) -> Any:
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **form), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create_road(self, **values: Any) -> set[str]:
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", confirm=True, in_steps=False, **values)

    def fake(self, **values: Any) -> Any:
        """El operador de mentira con todas las propiedades del diálogo (los de ``DEFAULTS`` y lo que se dé)."""
        properties = values.pop("properties", SimpleNamespace(is_property_set=lambda name: False))
        shown = {**DEFAULTS, "start": self.smooth_surface, **values}
        return operator_self(self.road, report=lambda kind, text: None, properties=properties, **shown)

    def parameter_row(self, code: str, param: str) -> tuple[Any, ...]:
        """La fila de la versión del parámetro ``param`` de la pista ``code``: valor, origen, tipo del origen y decisor."""
        ((value, source, kind, decider),) = self.rows(
            "SELECT value, source, source_kind, decided_by FROM gb_parameter WHERE key = ? AND scope = 'version' AND scope_uid = ?",
            f"des.road.{code.lower().replace('-', '_')}.{param}", self.v01.uid)
        return json.loads(value), source, kind, decider

    def code_of(self, name: str) -> str:
        """El código de la entidad de la versión activa que se llama ``name`` (las pistas que crea cada prueba se numeran en el orden de las pruebas)."""
        (found,) = [entry.record.code for entry in self.entities.registry(self.project, self.v01.uid) if entry.record.name == name]
        return str(found)

    def running_road(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.road) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{ROAD} no está en marcha")
        return found[0]

    def summary(self) -> list[tuple[str, bool]]:
        return [(line.name, bool(line.alert)) for line in self.view.summary]

    # --- a: la orden, el diálogo y la propuesta --------------------------------------------------

    def test_a_the_command_its_dialog_and_the_proposal(self) -> None:
        """RF-017-29, RF-015-28, RF-017-02, RF-017-10 (plan §5.3.3, §5.5; M1): «Pista…» es una orden real de ``des.road`` con la puerta de la procedencia y los pasos con Esc; es de
        la entrada 017 (entregada por la T33b) y del catálogo, con su casa en Diseño ▸ Pistas y entidades; sus propiedades tienen nombre y descripción en español y los decimales son texto; su diálogo propone el
        nombre, la capa del modo, el perfil y la partida; dibuja los campos de cada modo y, en «trazar», **el tipo de cada parámetro de la ruta**."""
        cls = self.road
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertTrue(issubclass(cls, self.des_ops._ChainsEntityLayer))
        self.assertTrue(issubclass(cls, self.des_ops._ClearsEntityPreview))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options), (ROAD, ROAD_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.ROAD_COMMAND, ROAD)
        self.assertIn(ROAD, self.dprov.OPERATION_TYPES_BY_NAME[ROAD_TYPE].commands)
        command = self.commands.catalog().commands[ROAD]
        self.assertEqual((command.label_es, command.entry, command.module, command.kind), ("Pista…", "017", "des", "operator"))
        self.assertTrue(self.commands.is_available(ROAD), "la entrada 017 está entregada (T33b): la orden se dibuja en su menú sin la nota «Disponible en …»")
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, set(PROPERTIES))
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]), (self.i18n.translate("es", label), self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        for prop in HIDDEN:  # las pone quien la lanza: sin nombre ni descripción
            self.assertNotIn("name", cls.__annotations__[prop].keywords)
        for items in (self.des_ops.ROAD_MODE_ITEMS, self.des_ops.ROAD_ORIGIN_ITEMS, self.des_ops.ROAD_DESTINATION_ITEMS):
            self.assertEqual(self.i18n.untranslated([text for _identifier, name, about in items for text in (name, about)]), [])
        for kind in ("string",):  # los decimales, en texto (regla 4: nada de float32)
            for prop in ("mesh", "level_step", "max_cut_fill", "lambda_weight", "turn", "margin", "simplify", "arrival_tol", "search_budget", "start_level", "end_level", "dest_level",
                         "dest_tol", "origin_station"):
                self.assertIs(cls.__annotations__[prop].function, bpy.props.StringProperty, f"{prop} es {kind}")

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        proposal = self.fake(name="", layer="", profile="", start="")
        self.assertEqual(cls.invoke(proposal, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Pista…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(proposal.in_steps)
        offered = [identifier for identifier, _label, _about in self.panels.platform_start_items(None, None)]
        self.assertEqual((proposal.name, proposal.layer, proposal.profile), ("Pista 1", POINTS, "pista_principal"))
        self.assertIn(proposal.start, offered)
        self.assertFalse(proposal.start.startswith("entity:"), "sin entidades ni cantera, el terreno")
        self.assertEqual(self.panels.road_default_start(), None, "sin cantera de la 014 ni cadena no hay partida por defecto")
        given = self.fake(name="Mía", layer=POINTS, profile=A15_PROFILE.lower(), start=self.a15_surface,
                          properties=SimpleNamespace(is_property_set=lambda name: name in ("layer", "profile", "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.layer, given.profile, given.start), ("Mía", POINTS, A15_PROFILE.lower(), self.a15_surface), "lo dado no cambia")
        self.assertEqual([item[0] for item in self.panels.road_layers("TRACE")], [POINTS])
        self.assertEqual([item[0] for item in self.panels.road_layers("ON_AXIS")], [AXES, platform_ops.LAYER], "las capas de líneas: sus ejes y las plataformas")
        self.assertEqual([item[0] for item in self.panels.road_layers("AXIS_3D")], ["none"], "sin líneas de rotura ni rutas propuestas, «—»")
        original = self.panels.gis_store.list_gis_datasets

        def listed(project: Any, **kwargs: Any) -> Any:  # una línea de rotura del proyecto, sin escribir su tabla
            if self.panels.gis_provenance.BREAKLINES in kwargs.get("families", ()):
                return [SimpleNamespace(name="gis_brk_pistas_eje3d")]
            return original(project, **kwargs)

        with mock.patch.object(self.panels.gis_store, "list_gis_datasets", listed), mock.patch.object(self.panels, "_proposed_routes", return_value=["des_rpl_ruta_norte"]):
            self.panels.refresh_road_choices(self.project)
            self.assertEqual([item[0] for item in self.panels.road_layers("AXIS_3D")], ["gis_brk_pistas_eje3d", "des_rpl_ruta_norte"],
                             "«eje 3D»: las líneas de rotura del proyecto y las rutas propuestas de la versión")
            self.assertEqual([item[0] for item in self.panels.road_layers("TRACE")], [POINTS], "las demás capas siguen")
        self.panels.refresh_road_choices(self.project)
        self.assertEqual([item[0] for item in self.panels.road_profile_items(None, None)], ["pista_principal", "acceso_a15"])
        self.assertEqual([item[0] for item in self.panels.road_zone_items(None, None)], [ZONES])

        trace = draw(cls, bpy.context, **{**DEFAULTS, "start": self.smooth_surface}).texts()
        for heading in ("Nombre", "Modo", "Geometría de la pista", "Capa", "El origen es", "Punto de origen", "Termina en", "Punto de destino", "Perfil de pista", "Superficie de partida",
                        "Superficie de apoyo", "Cota de inicio (m)", "Cota de fin (m)", "Malla de la ruta (m)", "Paso de cota (m)", "Altura máxima de desmonte y terraplén (m)",
                        "Peso del movimiento de tierras (1/m)", "Penalización de giro (m)", "Holgura del pasillo (m)", "Tolerancia de simplificación (m)",
                        "Tolerancia de llegada de la ruta (m)", "Presupuesto de estados", "Vista previa"):
            self.assertIn(heading, trace)
        self.assertNotIn("Línea de la capa", trace)
        self.assertIn("HIPÓTESIS: sin valor por defecto, lo elige usted", trace)
        budget = [text for text in trace if text.startswith("Por defecto: ")]
        self.assertEqual(len(budget), 1)
        self.assertTrue(budget[0].endswith("· ADOPTADO"), budget)
        self.assertEqual(len([text for text in trace if text.startswith("HIPÓTESIS: ")]), 8, "ocho de los nueve parámetros de la ruta son hipótesis sin valor por defecto")
        self.assertIn("Abscisa del origen (m)", draw(cls, bpy.context, **{**DEFAULTS, "origin_from": "ROAD"}).texts())
        by_level = draw(cls, bpy.context, **{**DEFAULTS, "destination_to": "LEVEL"}).texts()
        for heading in ("Cota del destino (m)", "Tolerancia de llegada a la cota (m)", "Zona del destino", "Polígono de la zona"):
            self.assertIn(heading, by_level)
        on_platform = draw(cls, bpy.context, **{**DEFAULTS, "destination_to": "ENTITY"}).texts()
        self.assertIn("Plataforma del destino", on_platform)
        self.assertNotIn("Punto de destino", on_platform, "el destino es el punto de la capa que cae en la huella de la plataforma")
        on_axis = draw(cls, bpy.context, **{**DEFAULTS, "mode": "ON_AXIS", "layer": AXES}).texts()
        self.assertIn("Línea de la capa", on_axis)
        for absent in ("Punto de origen", "Malla de la ruta (m)", "Termina en"):
            self.assertNotIn(absent, on_axis)
        axis_3d = draw(cls, bpy.context, **{**DEFAULTS, "mode": "AXIS_3D"}).texts()
        self.assertNotIn("Cota de inicio (m)", axis_3d, "en «eje 3D» la Z de la línea es la rasante")
        self.assertIn("Línea de la capa", axis_3d)

    # --- b: la petición ----------------------------------------------------------------------------

    def test_b_the_request_of_the_dialog_in_each_mode(self) -> None:
        """RF-017-02, RF-017-03, RF-017-04 (plan §5.2.1, §5.3.3): lo pedido en el diálogo arma ``RoadRequest`` —«trazar» con el origen y el destino en la capa, el origen en el eje de
        otra pista a una abscisa (con coma o punto), el destino en una plataforma y la rampa con su cota, su tolerancia y su zona (con su polígono); «sobre un eje» y «eje 3D» con su
        línea y, el 3D, sin cotas— con los decimales tecleados con coma y los parámetros de la ruta vacíos sin cifra (los rechaza el cálculo, con su nombre); lo que el diálogo no
        puede armar se dice sin tocar nada."""
        model = platform_ops._module("design.road_model")
        asked = self.road._request(self.fake(**ROUTE, start_level="100,5", end_level=" 101 ", search_budget="1000000"))
        self.assertEqual((asked.name, asked.mode, asked.layer, asked.profile, asked.origin, asked.destination, asked.feature, asked.support),
                         (FIRST, model.RoadMode.TRACE, POINTS, "pista_principal", "Origen", "Destino", None, None))
        self.assertEqual((asked.mesh_m, asked.level_step_m, asked.max_cut_fill_m, asked.lambda_per_m, asked.turn_m, asked.margin_m, asked.simplify_m, asked.arrival_tol_m),
                         (4.0, 0.28, 14.0, 2.0, 4.0, 60.0, 4.0, 0.28))
        self.assertEqual((asked.start_level_m, asked.end_level_m, asked.search_budget), (100.5, 101.0, 1_000_000))
        self.assertEqual(asked.start, self.smooth_surface)
        empty = self.road._request(self.fake())
        self.assertEqual((empty.mesh_m, empty.turn_m, empty.search_budget, empty.start_level_m, empty.end_level_m), (None, None, None, None, None), "ningún valor se elige por la persona")
        on_road = self.road._request(self.fake(origin_from="ROAD", origin_road="RDW-001", origin_station="100,5", destination_to="ENTITY", destination_entity="PLT-001"))
        self.assertEqual((on_road.origin, on_road.destination), ("RDW-001@100.5", "entity:PLT-001"))
        by_level = self.road._request(self.fake(destination_to="LEVEL", dest_level="101,8", dest_tol="0,3", dest_zone=ZONES, dest_zone_feature="Zona alta"))
        self.assertEqual((by_level.destination, by_level.dest_level_m, by_level.dest_tol_m, by_level.dest_zone), (None, 101.8, 0.3, f"{ZONES}:Zona alta"))
        self.assertEqual(self.road._request(self.fake(destination_to="LEVEL", dest_level="101,8", dest_tol="0,3", dest_zone=ZONES)).dest_zone, ZONES)
        axis = self.road._request(self.fake(mode="ON_AXIS", layer=AXES, feature="Eje A15", origin_point="ignorado", destination_to="ENTITY"))
        self.assertEqual((axis.mode, axis.feature, axis.origin, axis.destination, axis.mesh_m), (model.RoadMode.ON_AXIS, "Eje A15", None, None, None))
        axis_3d = self.road._request(self.fake(mode="AXIS_3D", layer="gis_brk_pistas", feature="Línea 1", start_level="5", end_level="6"))
        self.assertEqual((axis_3d.mode, axis_3d.feature, axis_3d.start_level_m, axis_3d.end_level_m), (model.RoadMode.AXIS_3D, "Línea 1", None, None), "la Z de la línea es la rasante")
        for changes, text in (({"name": " "}, "Escriba el nombre de la pista"), ({"layer": "none"}, "Elija la capa de la pista"), ({"layer": ""}, "Elija la capa de la pista"),
                              ({"profile": "none"}, "Elija el perfil de la pista"), ({"start": "none"}, "Elija la superficie de partida"),
                              ({"origin_from": "ROAD"}, "Elija la pista en cuyo eje está el origen"),
                              ({"origin_from": "ROAD", "origin_road": "RDW-001"}, "Escriba la abscisa del origen"),
                              ({"destination_to": "ENTITY"}, "Elija la plataforma en la que termina la pista"),
                              ({"destination_to": "LEVEL", "dest_zone": "none"}, "Escriba la cota del destino"),
                              ({"mesh": "abc"}, "«abc» no es un número (campo «Malla de la ruta (m)»)"),
                              ({"search_budget": "10,5"}, "«10,5» no es un número entero (campo «Presupuesto de estados»)"),
                              ({"start_level": "x"}, "«x» no es un número")):
            with self.subTest(cambios=changes):
                with self.assertRaises(ValueError) as caught:
                    self.road._request(self.fake(**changes))
                self.assertIn(text, str(caught.exception))

    # --- c: calcular y crear -----------------------------------------------------------------------

    def test_c_calculate_writes_nothing_and_create_registers_the_road_with_its_layers(self) -> None:
        """RF-017-01, RF-017-23, RF-015-03, RF-015-02, RF-017-02, RF-017-05 (M1): Calcular desde un guion deja el cálculo abierto con su resumen —la pista, su modo y su perfil, la
        longitud, la pendiente media y la máxima, el radio mínimo, el corte y el relleno y **todos los avisos con su lugar**, en los dos idiomas y con su título— y nada en el
        proyecto. Crear registra ``des.road`` en V01 con su superficie, su huella, su eje y su informe, **encadena la capa de entidades y la de ejes** y deja los parámetros de la
        entidad: la cota de inicio que escribió la persona queda como suya (``person``) y la de fin, que dejó vacía, con el origen que dio el algoritmo; la capa de puntos no se toca."""
        self.refresh()
        before = self.state()
        held = self.calculate_road(self.form(start_level="100,5"))
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), (ROAD_TYPE, FIRST, "V01", "RDW-001"))
        self.assertEqual(self.state()[:4], before[:4], "calcular no registra nada")
        self.assertEqual(self.state()[4], before[4], "calcular no deja ni un temporal")
        self.assertEqual(self.view.summary_title, f"Pista «{FIRST}» en V01")
        summary, outcome = self.summary(), held.summary
        self.assertEqual(summary[0][0], f"Pista «{FIRST}» (RDW-001) · modo «Trazar» · perfil «PISTA_PRINCIPAL»: longitud de "
                                        f"{self.length_text(outcome.length_m)} m · cota de {self.level_text(outcome.start_level_m)} m al inicio y de "
                                        f"{self.level_text(outcome.end_level_m)} m al final")
        self.assertTrue(summary[1][0].startswith("Pendiente: media del "), summary[1])
        self.assertEqual(outcome.start_level_m, 100.5, "la cota de inicio es la que escribió la persona")
        self.assertAlmostEqual(outcome.length_m, 40.0, delta=4.0, msg="de (10, 30) a (50, 30)")
        self.assertFalse(held.needs_mean_confirmation or held.needs_carriageway_confirmation)
        self.assertFalse(any(alert for _text, alert in summary[:4]))
        number = self.i18n.format_number
        self.assertEqual([text for text, _alert in summary[3:7]], [
            f"Desviación máxima del eje respecto a la ruta: {number(outcome.axis_deviation_m, 2)} m",
            f"Sección: desmonte {number(outcome.section_cut_m3, 0)} m³ · relleno {number(outcome.section_fill_m3, 0)} m³",
            f"Borde: desmonte {number(outcome.edge_cut_m3, 0)} m³ · relleno {number(outcome.edge_fill_m3, 0)} m³",
            f"Neto de la sección y el borde: {number(outcome.net_m3, 0)} m³ (desmonte {number(outcome.cut_m3, 0)} m³ − relleno {number(outcome.fill_m3, 0)} m³)"],
            "RF-017-21, RF-017-23, RF-017-13 (T44: S-1, S-3): la sección y el borde en líneas distintas, el neto y la desviación máxima del eje")
        self.assertEqual((outcome.section_cut_m3 + outcome.edge_cut_m3, outcome.section_fill_m3 + outcome.edge_fill_m3), (outcome.cut_m3, outcome.fill_m3))
        self.assertEqual(outcome.axis_deviation_m, held.outcome.axis.deviation_m)
        self.assertFalse([text for text, _alert in summary if text.startswith("Sección y borde")])
        tail = summary[len(summary) - len(held.notices):]
        self.assertEqual([text for text, _alert in tail], [notice.text("es") for notice in held.notices], "todos los avisos de la pista llegan al resumen")
        self.assertTrue(any("holgura del pasillo" in text for text, _alert in tail), "la nota de la ruta lleva la holgura del pasillo")
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, f"Road «{FIRST}» in V01")
        self.assertTrue(self.summary()[0][0].startswith(f"Road «{FIRST}» (RDW-001) · mode «Trace» · profile «PISTA_PRINCIPAL»: length "), self.summary()[0])
        self.i18n.set_language("es")
        self.panels.show_summary(held)

        self.assertEqual(self.create_road(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?", ROAD_TYPE)
        self.assertEqual(status, "done")
        for family in ("psf", "epr", "rdx", "prp"):
            self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND name = ?", self.dprov.dataset_name(family, FIRST)), [(1,)], family)
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertAlmostEqual(figures["des.road_length_m"], outcome.length_m, delta=1e-9 * outcome.length_m)
        entry = self.entities.registry(self.project, self.v01.uid).get("RDW-001")
        self.assertEqual((entry.record.name, str(entry.record.state)), (FIRST, "current"))
        self.assertEqual(self.parameter_row("RDW-001", "mode")[0], "trace")
        self.assertEqual(self.parameter_row("RDW-001", "origin")[0:1], ("Origen",))
        value, source, kind, decider = self.parameter_row("RDW-001", "start_level_m")
        self.assertEqual((value, kind, decider), (100.5, "person", self.project.session.user_host))
        self.assertEqual(source, f"diálogo de «Pista…», entidad «{FIRST}»")
        value, source, kind, _decider = self.parameter_row("RDW-001", "end_level_m")
        self.assertEqual((value, kind), (outcome.end_level_m, "algorithm"), "la cota de fin que no se escribió se anota con su origen: el del algoritmo")
        self.assertIn("superficie de partida", source)
        self.assertEqual(self.parameter_row("RDW-001", "mesh_m")[:3:2], (4.0, "person"))
        value, source, kind, _decider = self.parameter_row("RDW-001", "search_budget")
        self.assertEqual((value, kind), (5_000_000, "algorithm"), "el presupuesto vacío es su valor por defecto, con el origen de su definición")
        self.assertNotIn("diálogo", source)
        layers = [name for (name,) in self.rows("SELECT name FROM gb_dataset WHERE status = 'current' AND name IN ('des_enl', 'des_rax') ORDER BY name")]
        self.assertEqual(layers, ["des_enl", "des_rax"], "la capa de entidades y la de ejes, tras crear")
        for table in ("des_enl_v01", "des_rax_v01"):
            self.assertIn("RDW-001", repr(self.rows(f'SELECT * FROM "{table}"')), table)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.declare_constraints'"), [(1,)], "tras crear se declara de nuevo (la pista no declara nada)")
        self.assertEqual(self.table_state(POINTS), self.layers_before[POINTS], "la capa de origen no se toca")

    def length_text(self, value: float) -> str:
        return self.i18n.format_number(value, 1)

    def level_text(self, value: float) -> str:
        return self.i18n.format_number(value, 2)

    # --- d: la pendiente media por encima de pm --------------------------------------------------

    def test_d_a_mean_gradient_above_pm_is_not_created_without_the_confirmation_and_its_reason(self) -> None:
        """RF-017-17, RF-017-22, D-6 (la «opción A15»: 10,5 % de media con pm = 10 %; M1): «sobre un eje» al 10,5 % calcula y su resumen lo dice **en ámbar** con la media, el límite y
        que se confirma con un motivo; la ventana de crear pone «Confirmar y crear» y el campo del motivo (el resumen y el botón); **sin la confirmación** no se crea
        (``des.road_mean_unconfirmed``), **confirmada sin motivo** tampoco (``des.road_mean_reason``) y el cálculo sigue abierto; con la confirmación y su motivo se crea
        (no bloquea) y el motivo queda en los ajustes de la operación con quién y cuándo."""
        self.refresh()
        before = self.state()
        held = self.calculate_road(self.axis_form())
        self.assertTrue(held.needs_mean_confirmation)
        self.assertFalse(held.needs_carriageway_confirmation)
        self.assertGreater(held.summary.gradient_mean_pct, held.summary.mean_limit_pct)
        alerts = [text for text, alert in self.summary() if alert and text.startswith("La pendiente media, del ")]
        self.assertEqual(len(alerts), 1, self.summary())
        self.assertIn("pasa del 10,00 % del perfil", alerts[0])
        self.assertIn("el botón que la crea lo confirma", alerts[0])
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        window = self.fake(confirm=True)
        self.assertEqual(self.road.invoke(window, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Confirmar y crear")
        self.assertTrue(window.confirm_mean)
        self.assertFalse(window.confirm_carriageway)
        drawn = draw(self.road, bpy.context, **{**DEFAULTS, "confirm": True, "confirm_mean": True}).texts()
        self.assertIn("Motivo de la pendiente media", [item for item in drawn])
        self.assertNotIn("Motivo de la pendiente media", draw(self.road, bpy.context, **{**DEFAULTS, "confirm": True}).texts())

        with self.assertRaises(RuntimeError) as unconfirmed:
            self.create_road()
        self.assertIn("pasa de la pendiente media máxima de su perfil", str(unconfirmed.exception))
        self.assertIn("confirmación expresa", str(unconfirmed.exception))
        self.assertIs(self.des_ops.calculation(), held, "el cálculo sigue abierto")
        self.assertTrue(held.open)
        with self.assertRaises(RuntimeError) as no_reason:
            self.create_road(confirm_mean=True, mean_reason="   ")
        self.assertIn("confirmarla pide un motivo", str(no_reason.exception))
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4], "lo rechazado no deja nada")
        self.assertEqual(self.create_road(confirm_mean=True, mean_reason="Opción A15 de la propiedad (N-15)"), {"FINISHED"})
        ((settings, status),) = self.rows("SELECT settings, status FROM gb_operation WHERE op_type = ? AND json_extract(settings, '$.name') = ?", ROAD_TYPE, A15_ROAD)
        self.assertEqual(status, "done")
        recorded = json.loads(settings)["road_confirmed"]["mean_gradient"]
        self.assertEqual(recorded["reason"], "Opción A15 de la propiedad (N-15)")
        self.assertEqual(recorded["decided_by"], self.project.session.user_host)
        self.assertRegex(recorded["decided_on"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        self.assertAlmostEqual(recorded["mean_pct"], held.summary.gradient_mean_pct, delta=0.01)
        self.assertEqual(recorded["limit_pct"], 10.0)
        entry = self.entities.registry(self.project, self.v01.uid).get("RDW-002")
        self.assertEqual((entry.record.name, str(entry.record.state)), (A15_ROAD, "current"))
        self.assertEqual(self.parameter_row("RDW-002", "feature")[0], "Eje A15")
        self.assertEqual(self.table_state(AXES), self.layers_before[AXES], "la capa del eje no se toca")

    def test_d_b_a_carriageway_off_its_level_is_not_created_without_the_confirmation(self) -> None:
        """RF-017-22, RF-017-17 (M1): «sobre un eje» pegado al límite legal de la ladera —la banda de 2 m hacia dentro no admite corte y el terreno sube hacia ella— deja **calzada que no
        queda en su rasante**: el resumen lo dice en ámbar con su área, la ventana de crear pone «Confirmar y crear» **sin** campo de motivo (no hay media que confirmar), sin la
        confirmación no se crea (``des.road_carriageway_unconfirmed``, y el cálculo sigue abierto) y con ella se crea y la confirmación queda en los ajustes con su área, quién y
        cuándo."""
        self.refresh()
        held = self.calculate_road({"name": EDGE_ROAD, "mode": "ON_AXIS", "layer": AXES, "feature": "Eje al borde", "profile": "pista_principal", "start": self.ground,
                                    "in_steps": False})
        self.assertTrue(held.needs_carriageway_confirmation)
        self.assertFalse(held.needs_mean_confirmation)
        alerts = [text for text, alert in self.summary() if alert and " de la calzada no quedan en su rasante (véanse los avisos)" in text]
        self.assertEqual(len(alerts), 1, self.summary())
        self.assertTrue(alerts[0].startswith(f"{self.i18n.format_number(held.summary.carriageway_area_m2, 0)} m² de la calzada"), alerts)
        self.assertTrue(any(alert and "no quedan en su rasante" in text and "Concesión" in text for text, alert in self.summary()), "el aviso con la restricción que lo impide y su lugar")
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        window = self.fake(confirm=True)
        self.assertEqual(self.road.invoke(window, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Confirmar y crear")
        self.assertTrue(window.confirm_carriageway)
        self.assertFalse(window.confirm_mean)
        self.assertNotIn("Motivo de la pendiente media", draw(self.road, bpy.context, **{**DEFAULTS, "confirm": True, "confirm_carriageway": True}).texts())
        with self.assertRaises(RuntimeError) as unconfirmed:
            self.create_road()
        self.assertIn("de su calzada no quedan en su rasante", str(unconfirmed.exception))
        self.assertIn("confirmación expresa", str(unconfirmed.exception))
        self.assertTrue(held.open, "el cálculo sigue abierto")
        self.assertEqual(self.create_road(confirm_carriageway=True), {"FINISHED"})
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE op_type = ? AND json_extract(settings, '$.name') = ?", ROAD_TYPE, EDGE_ROAD)
        recorded = json.loads(settings)["road_confirmed"]
        self.assertNotIn("mean_gradient", recorded)
        self.assertAlmostEqual(recorded["carriageway"]["area_m2"], held.summary.carriageway_area_m2, delta=1e-9)
        self.assertEqual(recorded["carriageway"]["decided_by"], self.project.session.user_host)
        self.assertRegex(recorded["carriageway"]["decided_on"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    # --- e: Esc, cancelar y lo que se rechaza ---------------------------------------------------

    def test_e_esc_cancel_and_what_is_refused_leave_nothing(self) -> None:
        """RF-015-29, RF-017-30, RF-017-04, RF-015-08 (M1, M9): Esc **a mitad** del cálculo, Cancelar la confirmación y lo que se rechaza —el nombre vacío o repetido, el origen que
        falta o que no está, un punto fuera de la rejilla, un parámetro de la ruta sin valor o que no es múltiplo del paso, un perfil que no está— no dejan nada: ni operación, ni
        dato, ni parámetro, ni cifra, ni temporal (0 transacciones); cada rechazo dice **la capa, la pista, el campo y el valor**; Esc dice que no queda nada a medias."""
        self.refresh()
        free = functools.partial(self.form, start=self.second_surface)  # de cada superficie parte una sola entidad: la del terreno ya la usa la primera
        before = self.state()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **free(name="Esc", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running_road()
        modal.STEP_BUDGET_S = step_modals.ONE_STEP_S  # un paso por evento
        for _ in range(3):
            self.assertEqual(modal.modal(bpy.context, step_modals.TIMER), {"RUNNING_MODAL"})
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
        self.assertIsNone(modal._steps)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        self.calculate_road(free(name="Cancelada"))
        self.road.cancel(operator_self(self.road, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        for changes, texts in (
                ({"name": " "}, ("Escriba el nombre de la pista",)),
                ({"name": FIRST}, ("El nombre «Pista de la carga» ya lo tiene la entidad «Pista de la carga» en V01",)),
                ({"origin_point": ""}, (f"Capa «{POINTS}»", "entidad «Rechazada»", ".origin»", "no tiene valor")),
                ({"origin_point": "No existe"}, (f"La capa «{POINTS}»", "«No existe»")),
                ({"destination_point": "Fuera"}, (f"Capa «{POINTS}»", "pista «Rechazada»", ".destination» = «Fuera»", "cae fuera de la rejilla")),
                ({"mesh": ""}, (f"Capa «{POINTS}»", ".mesh_m»", "no tiene valor")),
                ({"mesh": "3"}, (f"Capa «{POINTS}»", ".mesh_m» = 3 m", "no es un múltiplo entero del paso del proyecto (2 m)")),
                ({"turn": "-1"}, (f"Capa «{POINTS}»", ".turn_m» = -1", "está fuera de su rango")),
                ({"origin_point": "Destino"}, (".destination» = «Destino»", "el origen y el destino son el mismo punto")),
                ({"mesh": "abc"}, ("«abc» no es un número",)),
                ({"search_budget": "10"}, (f"Capa «{POINTS}»", "pista «Rechazada»", "agotó su presupuesto de 10 estados expandidos", "no significa que no haya ruta")),
                ({"start": self.smooth_surface}, ("no puede partir de", "ya parte la entidad «Pista de la carga»"))):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **free(**{"name": "Rechazada", **changes}))
                for text in texts:
                    self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)

    # --- f: la vista previa -----------------------------------------------------------------------

    def test_f_the_preview_follows_the_dialog_gets_the_calculation_and_goes_away(self) -> None:
        """RF-017-26, RF-015-26 (T28, M1, M5): el botón «Vista previa» (la misma orden con ``preview``) activa la vista previa de **esa** pista con lo pedido
        (``EntityPlan(road=RoadAsk(request=…))``) sin escribir nada; el ``update`` de cada campo la redibuja con lo que dice ahora el diálogo (y uno a medias no la cambia); tras
        Calcular le da **lo calculado** (``prepared`` y ``outcome``, sin repetir la preparación); se quita al **cancelar** la orden, con **Esc** a mitad del cálculo y al **crear**."""
        second = functools.partial(self.form, start=self.second_surface)  # de cada superficie parte una sola entidad: esta prueba crea desde la suya
        entity = self.des_ops._entity_preview()
        self.addCleanup(entity.disable)
        self.refresh()
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **second(name="Previa", preview=True)), {"FINISHED"})
        self.assertTrue(entity.enabled())
        plan = entity.plan()
        self.assertEqual((plan.kind, plan.road.request.name, plan.road.request.origin, plan.road.request.mesh_m), ("road", "Previa", "Origen", 4.0))
        self.assertIsNone(plan.road.prepared)
        self.assertEqual(self.state(), before, "la vista previa no escribe")
        changed = self.fake(name="Previa 2", **ROUTE, origin_point="Origen", destination_point="Destino norte")
        self.des_ops._refresh_road_preview(changed, None)
        self.assertEqual((entity.plan().road.request.name, entity.plan().road.request.destination), ("Previa 2", "Destino norte"))
        unfinished = self.fake(name="Previa 3", mesh="abc")
        self.des_ops._refresh_road_preview(unfinished, None)
        self.assertEqual(entity.plan().road.request.name, "Previa 2", "un diálogo a medias no cambia la vista previa")
        no_name = self.fake(name="")
        self.des_ops._refresh_road_preview(no_name, None)
        self.assertEqual(entity.plan().road.request.name, "Previa 2")
        with self.assertRaises(RuntimeError) as refused:
            bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **second(name=" ", preview=True))
        self.assertIn("Escriba el nombre de la pista", str(refused.exception))
        self.assertEqual(entity.plan().road.request.name, "Previa 2", "lo que falta no toca la vista previa")

        held = self.calculate_road(second(name="Previa 2", destination_point="Destino norte"))
        self.assertTrue(entity.enabled())
        calculated = entity.plan().road
        self.assertIs(calculated.prepared, held.entity)
        self.assertIs(calculated.outcome, held.outcome)
        self.road.cancel(operator_self(self.road, confirm=True, in_steps=False), bpy.context)
        self.assertFalse(entity.enabled(), "se quita al cancelar")
        self.assertIsNone(self.des_ops.calculation())

        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **second(name="Esc previa", preview=True)), {"FINISHED"})
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **second(name="Esc previa", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running_road()
        modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
        self.assertEqual(modal.modal(bpy.context, step_modals.TIMER), {"RUNNING_MODAL"})
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertFalse(entity.enabled(), "se quita con Esc a mitad del cálculo")

        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **second(name="Creada", destination_point="Destino norte", preview=True)), {"FINISHED"})
        self.calculate_road(second(name="Creada", destination_point="Destino norte"))
        self.assertTrue(entity.enabled())
        self.assertEqual(self.create_road(), {"FINISHED"})
        self.assertFalse(entity.enabled(), "se quita al crear la pista")
        self.assertEqual(self.entities.registry(self.project, self.v01.uid).get(self.code_of("Creada")).record.name, "Creada")

    # --- g: un ramal y la rampa --------------------------------------------------------------------

    def test_g_a_branch_starts_on_the_axis_of_another_road_and_a_ramp_ends_at_an_elevation_in_its_zone(self) -> None:
        """RF-017-03, RF-017-02, RF-017-05, RF-015-15, D-4 (E1, E4): el diálogo pide el origen de un **ramal** en el eje de otra pista a una abscisa (``RDW-001@20``) y la pista **se
        apoya en ella** (registra su dependencia declarada y parte de su superficie, la última de la cadena: la que propone el diálogo); y una **rampa**, con la cota, su tolerancia
        y la zona de una capa, termina donde la alcanza, con su cota anotada con el origen del destino por cota."""
        self.refresh()
        first = self.code_of(FIRST)
        roads = [entry.record.code for entry in self.entities.registry(self.project, self.v01.uid) if entry.record.kind == self.entities.EntityKind.ROAD]
        proposal = self.fake(name="", layer="", profile="", start="")
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        self.road.invoke(proposal, context, None)
        self.assertEqual(self.panels.road_default_start(), None, "varias cadenas: ninguna es la última")
        self.assertEqual([item[0] for item in self.panels.road_road_items(None, None)], roads)
        self.assertEqual(proposal.origin_road, roads[0], "la primera pista que ofrece")
        branch = self.form(name=BRANCH, origin_from="ROAD", origin_road=first, origin_station="20", destination_point="Destino norte", start=f"entity:{first}")
        branch.pop("origin_point")
        self.assertIn(f"entity:{first}", [item[0] for item in self.panels.platform_start_items(None, None)])
        held = self.calculate_road(branch)
        branch_code = held.entity.code
        self.assertEqual((held.entity.supports, held.entity.start_surface), ((first,), self.dprov.dataset_name("psf", FIRST)))
        self.assertEqual(self.create_road(), {"FINISHED"})
        self.refresh()  # el diálogo vuelve a leer las listas al abrirse: la pista nueva ya es una partida
        self.assertEqual(self.parameter_row(branch_code, "origin")[0], f"{first}@20.0")
        self.assertEqual(self.parameter_row(branch_code, "supports")[0], first)
        dependents = [row.name for row in self.entities.dependents(self.project, self.v01.uid, first)]
        self.assertEqual(dependents, [BRANCH], "lo que se apoya en la pista: una sola lista")

        ramp = self.form(name=RAMP, origin_point="Origen sur", destination_to="LEVEL", dest_level="101,8", dest_tol="0,3", dest_zone=ZONES, start=f"entity:{branch_code}")
        ramp.pop("destination_point")
        held = self.calculate_road(ramp)
        ramp_code = held.entity.code
        self.assertEqual(held.entity.supports, ())
        reached = held.summary.end_level_m
        self.assertEqual(self.create_road(), {"FINISHED"})
        self.assertAlmostEqual(reached, 101.8, delta=0.3, msg="la rasante llega a la cota pedida dentro de la tolerancia de llegada")
        self.assertEqual(self.parameter_row(ramp_code, "dest_zone")[0], ZONES)
        self.assertEqual(self.parameter_row(ramp_code, "dest_level_m")[0], 101.8)
        self.assertEqual(self.parameter_row(ramp_code, "dest_tol_m")[0], 0.3)
        self.assertEqual(self.table_state(ZONES), self.layers_before[ZONES], "la capa de la zona no se toca")

    # --- g·b: «Cambiar parámetro…» de una pista ------------------------------------------------------

    def test_g_b_changing_a_parameter_of_a_road_renames_it_and_the_level_the_person_gives_is_theirs(self) -> None:
        """RF-015-08, RF-015-01, RF-017-01, RF-017-27, RF-015-27, RF-017-03, D-13 (T29c): «Cambiar parámetro…» (``core_set_parameter``, la orden real) de una **pista**. **Renombrarla** funciona
        (la orden pide la fila del proyecto de su nombre, que la pista crea al crearse como la plataforma: antes, «El parámetro … no está registrado en el proyecto»), no la deja obsoleta y la
        capa de ejes dice el nombre nuevo al terminar lo que sigue al cambio; el nombre vacío o repetido se rechaza con su texto y **sin escribir nada**. La cota de fin que había derivado el algoritmo y
        la persona **cambia a mano** queda **suya** (``person``, con su origen), también si da la de inicio; la que ya era de otra clase de origen, no se toca."""
        self.refresh()
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        first = self.code_of(FIRST)
        prefix = f"des.road.{first.lower().replace('-', '_')}"
        self.assertEqual(self.rows("SELECT unconfirmed FROM gb_parameter WHERE key = ? AND scope = 'project'", f"{prefix}.name"), [(1,)], "la pista creó la fila de su nombre")

        def change(param: str, value: str, **extra: Any) -> set[str]:
            return bpy.ops.geoblender.core_set_parameter("EXEC_DEFAULT", key=f"{prefix}.{param}", value=value, scope="VERSION", decided_by=PERSON, reason=REASON, **extra)

        before = self.state()
        for value, text in (("", "no tiene valor"), (BRANCH, f"ya lo tiene la entidad «{BRANCH}»"), (BRANCH.upper(), f"ya lo tiene la entidad «{BRANCH}»")):
            with self.subTest(value=value), self.assertRaises(RuntimeError) as caught:
                change("name", value, source="Criterio de la prueba")
            self.assertIn(text, str(caught.exception))
            self.assertNotIn("Traceback", str(caught.exception))
            self.assertEqual(self.state(), before, "el rechazo no escribe nada")
        old_operation = self.rows("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by IS NULL ORDER BY fid", ROAD_TYPE)
        self.assertEqual(change("name", "Pista de la carga norte", source="Criterio de la prueba"), {"FINISHED"})
        self.assertEqual(self.parameter_row(first, "name")[0], "Pista de la carga norte")
        self.finish_refresh()  # lo que sigue al cambio, por pasos (los temporizadores no corren en ``blender -b``)
        entry = self.entities.registry(self.project, self.v01.uid).get(first)
        self.assertEqual((entry.record.name, str(entry.record.state)), ("Pista de la carga norte", "current"), "renombrarla no la deja obsoleta")
        self.assertEqual(self.rows("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by IS NULL ORDER BY fid", ROAD_TYPE), old_operation)
        shown = {code: (name, state) for code, name, state in self.rows('SELECT code, name, state FROM "des_rax_v01"')}
        self.assertEqual(shown[first], ("Pista de la carga norte", "current"), "la capa de ejes dice el nombre nuevo")
        self.assertEqual(shown[self.code_of(BRANCH)][0], BRANCH)

        derived = self.parameter_row(first, "end_level_m")
        self.assertEqual(derived[2], "algorithm", "la cota de fin que no escribió la persona la derivó el algoritmo")
        self.assertEqual(change("end_level_m", "101,5"), {"FINISHED"})
        value, source, kind, decider = self.parameter_row(first, "end_level_m")
        self.assertEqual((value, kind, decider), (101.5, "person", PERSON))
        self.assertEqual(source, "orden «Cambiar parámetro…», pista «Pista de la carga norte»")
        self.finish_refresh()
        entry = self.entities.registry(self.project, self.v01.uid).get(first)
        self.assertEqual(str(entry.record.state), "stale", "la pista lee la cota: queda obsoleta con ella")
        start = self.parameter_row(first, "start_level_m")
        self.assertEqual(start[2], "person", "la de inicio la escribió la persona al crear la pista")
        self.assertEqual(change("start_level_m", "100,6", source="Proyecto de la pista", source_kind="DOCUMENT"), {"FINISHED"})
        self.assertEqual(self.parameter_row(first, "start_level_m")[:3], (100.6, "Proyecto de la pista", "document"), "lo que dice la persona manda")
        self.finish_refresh()
        self.assertEqual(change("start_level_m", "100,7"), {"FINISHED"})
        value, _source, kind, _decider = self.parameter_row(first, "start_level_m")
        self.assertEqual((value, kind), (100.7, "document"), "lo anotado por un documento se conserva")
        self.finish_refresh()

    # --- g·c: «Cambiar parámetro…» de un valor del perfil y del origen de una pista (T40) ---------------

    def test_g_c_changing_a_value_of_the_profile_or_the_origin_of_a_road_is_refused_when_creating_it_would_be(self) -> None:
        """RF-017-04, RF-017-07, RF-015-15, RF-017-03, RF-015-08 (T40; hallazgos A-1 y A-2): «Cambiar parámetro…» (``core_set_parameter``, la orden real) de un valor del **perfil de pista**
        (``des.roadprofile.{p}.*``) rechaza lo que rechaza «Perfil de pista…» —el radio mínimo menor que la semianchura de la sección (3 m con 5,75 m), mayor que el radio de las curvas (R = 5 m con
        Rmín = 12 m) y el ángulo de desmonte de 90°, que la definición admite y RF-017-04 excluye— y el **origen de una pista en el eje de otra que ya se apoya en ella** (el ciclo: el ramal sale de la
        pista principal y esta no puede salir del ramal), cada uno con su texto, el perfil o la pista, el campo y el valor, y **sin escribir nada** (antes se escribían y «Recalcular lo obsoleto»
        daba ``FAILED`` hasta corregirlos). **T49 (hallazgos T47-1 y T47-2):** lo mismo con el **ámbito proyecto** (el que propone el diálogo cuando la versión no tiene valor propio: un valor del
        proyecto llega a las versiones que no tienen el suyo) con los valores del proyecto del perfil —antes se aceptaban los cuatro: ``min_radius_m = 3``, ``curve_radius_m = 5``, ``berm_m = 20``
        y ``cut_angle_deg = 90``—, y las **dependencias declaradas a mano** (``supports``) de una pista que cierran el ciclo."""
        self.refresh()
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        branch = self.code_of(BRANCH)
        first = str(self.parameter_row(branch, "origin")[0]).partition("@")[0]  # la pista principal: de la que sale el ramal (el nombre de la primera lo cambió la prueba anterior)
        profile = "des.roadprofile.pista_principal"

        def change(key: str, value: str, scope: str = "VERSION") -> set[str]:
            return bpy.ops.geoblender.core_set_parameter("EXEC_DEFAULT", key=key, value=value, scope=scope, decided_by=PERSON, reason=REASON, source="Criterio de la prueba")

        before = self.state()
        origin = f"des.road.{first.lower().replace('-', '_')}.origin"
        supports = f"des.road.{branch.lower().replace('-', '_')}.supports"  # la fila de las dependencias la tiene el ramal (apoyado en la principal), no la principal
        for key, value, text, field in ((f"{profile}.min_radius_m", "3", "es menor que la semianchura de su sección", f"{profile}.min_radius_m"),
                                        (f"{profile}.curve_radius_m", "5", "es mayor que el radio de sus curvas", f"{profile}.min_radius_m"),  # el rechazo nombra el radio mínimo, como «Perfil de pista…»
                                        (f"{profile}.cut_angle_deg", "90", "está fuera de su rango", f"{profile}.cut_angle_deg"),
                                        (origin, f"{branch}@5", f"declara que se apoya en {branch}", origin),
                                        (supports, branch, f"declara que se apoya en {branch}", supports)):  # T49 (T47-2): lo que declara a mano (aquí, en sí mismo), igual que su origen
            with self.subTest(key=key), self.assertRaises(RuntimeError) as caught:
                change(key, value)
            self.assertIn(text, str(caught.exception))
            self.assertIn(field, str(caught.exception))
            self.assertNotIn("Traceback", str(caught.exception))
            self.assertEqual(self.state(), before, "el rechazo no escribe nada")
        # T49 (T47-1): lo mismo con el ámbito PROYECTO (el que propone el diálogo cuando la versión no tiene valor propio: lo del proyecto llega a las versiones que no tienen el suyo), con los valores del
        # PROYECTO del perfil (los de V01 son de V01 y no se leen). Hasta la T49 se aceptaban los cuatro (``FINISHED``) y «Recalcular lo obsoleto» daba ``FAILED``.
        profiles, dparams = platform_ops._module("design.road_profiles"), platform_ops._module("design.params")
        reference = {param: getattr(rd.PROFILE, "class_name" if param.value == "class" else param.value) for param in dparams.RoadProfileParam
                     if param.value not in ("mesh_factor", "metric")}  # los trece que se declaran siempre: el factor de malla y la métrica ya tienen su valor por defecto en el proyecto
        profiles.edit_road_profiles(self.project, (profiles.ProfileEdit(code="pista_principal", values=reference),), profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", PERSON, REASON))
        before = self.state()
        for key, value, text, field in ((f"{profile}.min_radius_m", "3", "es menor que la semianchura de su sección", f"{profile}.min_radius_m"),
                                        (f"{profile}.curve_radius_m", "5", "es mayor que el radio de sus curvas", f"{profile}.min_radius_m"),
                                        (f"{profile}.berm_m", "20", "es menor que la semianchura de su sección", f"{profile}.min_radius_m"),
                                        (f"{profile}.cut_angle_deg", "90", "está fuera de su rango", f"{profile}.cut_angle_deg")):
            with self.subTest(scope="PROJECT", key=key):
                with self.assertRaises(RuntimeError) as caught:
                    change(key, value, "PROJECT")
                self.assertIn(text, str(caught.exception))
                self.assertIn(field, str(caught.exception))
                self.assertNotIn("Traceback", str(caught.exception))
                self.assertEqual(self.state(), before, "el rechazo no escribe nada")
        self.assertEqual(change(f"{profile}.min_radius_m", "6", "PROJECT"), {"FINISHED"}, "un valor bueno se admite en el ámbito proyecto")
        ((stored,),) = self.rows("SELECT value FROM gb_parameter WHERE key = ? AND scope = 'project'", f"{profile}.min_radius_m")
        self.assertEqual(json.loads(stored), 6.0)

    # --- g·d: el gancho de «Cambiar parámetro…» sin versión (T49) ------------------------------------

    def test_g_d_a_check_is_called_without_a_version_only_if_it_asked_for_it(self) -> None:
        """RF-015-08, RF-017-04, RF-017-07 (T49; hallazgo T47-1): ``core_provenance.check_parameter_change`` sigue sin llamar a ninguna comprobación con el cambio **del proyecto** (sin versión)
        —las reglas de las entidades de la 015 y la 016 son de una versión: sin cambio—, **salvo a la que se registró con ``project_scope=True``**, que recibe ``None`` por versión; con versión,
        a todas las de su principio. ``des`` la pide solo para los valores del perfil de pista (``des.roadprofile.``): ningún principio de entidad la lleva. Volver a registrar un principio sin
        ``project_scope`` se la quita y desregistrar quita la comprobación y el aviso."""
        core, des_ops = platform_ops._module("bl.ops.core_provenance"), platform_ops._module("bl.ops.des")
        self.assertEqual(core._PROJECT_SCOPE_CHECKS, {des_ops.ROAD_PROFILE_PARAMETER_PREFIX})  # noqa: SLF001
        self.assertIs(core._PARAMETER_CHECKS[des_ops.ROAD_PROFILE_PARAMETER_PREFIX], des_ops._check_road_profile_parameter)  # noqa: SLF001
        calls: list[tuple[str, str | None]] = []

        def only_with_a_version(_project: Any, key: str, _value: Any, version: str | None) -> None:
            calls.append(("versión", version))

        def also_for_the_project(_project: Any, key: str, _value: Any, version: str | None) -> None:
            calls.append(("proyecto", version))

        core.register_parameter_check("des.zzt49a.", only_with_a_version)
        self.addCleanup(core.unregister_parameter_check, "des.zzt49a.", only_with_a_version)
        core.register_parameter_check("des.zzt49b.", also_for_the_project, project_scope=True)
        self.addCleanup(core.unregister_parameter_check, "des.zzt49b.", also_for_the_project)
        core.check_parameter_change("proyecto", "des.zzt49a.x.y", 1, None)
        core.check_parameter_change("proyecto", "des.zzt49b.x.y", 1, None)
        core.check_parameter_change("proyecto", "des.otro.x.y", 1, None)
        self.assertEqual(calls, [("proyecto", None)])
        calls.clear()
        core.check_parameter_change("proyecto", "des.zzt49a.x.y", 1, "uid-v01")
        core.check_parameter_change("proyecto", "des.zzt49b.x.y", 1, "uid-v01")
        self.assertEqual(calls, [("versión", "uid-v01"), ("proyecto", "uid-v01")])
        core.register_parameter_check("des.zzt49b.", also_for_the_project)  # sin la petición, vuelve a ser de una versión
        self.assertNotIn("des.zzt49b.", core._PROJECT_SCOPE_CHECKS)  # noqa: SLF001
        calls.clear()
        core.check_parameter_change("proyecto", "des.zzt49b.x.y", 1, None)
        self.assertEqual(calls, [])
        core.register_parameter_check("des.zzt49b.", also_for_the_project, project_scope=True)
        core.unregister_parameter_check("des.zzt49b.", lambda *_args: None)  # lo que otro registró es suyo: no se quita
        self.assertIn("des.zzt49b.", core._PROJECT_SCOPE_CHECKS)  # noqa: SLF001
        core.unregister_parameter_check("des.zzt49b.", also_for_the_project)
        core.unregister_parameter_check("des.zzt49b.", also_for_the_project)  # idempotente
        self.assertNotIn("des.zzt49b.", core._PARAMETER_CHECKS)  # noqa: SLF001
        self.assertNotIn("des.zzt49b.", core._PROJECT_SCOPE_CHECKS)  # noqa: SLF001
        for prefix in des_ops.PARAMETER_PREFIXES:
            self.assertNotIn(prefix, core._PROJECT_SCOPE_CHECKS, prefix)  # noqa: SLF001

    # --- h: desactivada con su motivo ---------------------------------------------------------------

    def test_h_the_command_is_disabled_with_its_reason(self) -> None:
        """RF-017-29, RF-015-28, RF-009-05, RF-009-21 (M1): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable (V02 SUPERADO: «V02 está en
        estado SUPERADO: …», que dice también su descripción) la orden sale desactivada con su motivo y no se puede lanzar; **sin versión activa**, el diálogo no abre: dice que hace
        falta una y la ventana que la pide (RF-009-05); con V01 en escritura, activa. Ninguna deja nada."""
        messages: list[str] = []
        cls = self.road
        self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(bpy.ops.geoblender.des_create_road.poll())

        def poll() -> bool:
            messages.clear()
            with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                return bool(cls.poll(bpy.context))

        self.assertTrue(poll())
        self.assertEqual(messages, [])
        before = self.state()
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(poll())
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_create_road.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **self.form(name="No debe"))
            self.assertEqual(self.state(), before)
        self.assertTrue(poll())
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", (REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        not_editable = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertFalse(poll())
        self.assertEqual(messages, [not_editable])
        self.assertFalse(bpy.ops.geoblender.des_create_road.poll())
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
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
                bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", name="Sin versión")
            self.assertIn(self.session.version_required_text(), str(caught.exception))
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})

    # --- i: crear por pasos y la vista previa -------------------------------------------------

    def test_i_creating_by_steps_from_the_interface_removes_the_preview(self) -> None:
        """RF-017-26, RF-017-30 (D-3 de la verificación única, T45; mutante M4: ``_after_registered`` de «Pista…» no quita la vista previa): «Crear» **por pasos** —la vía real de la interfaz
        (``_CreatesInSteps._creation_steps`` → ``_after_registered``), con ventana— quita la vista previa en cuanto lo guardado llega: la pista ya existe, ya no se prepara; antes, con el cálculo
        abierto, sigue encendida. (La de «Crear» de una vez, la de ``test_f``, es otra rama.) Va después de la «g»: crea una pista más, que cambia la cadena que esas miran."""
        entity = self.des_ops._entity_preview()
        self.addCleanup(entity.disable)
        form = self.form(name="Creada por pasos", start=self.write_grid("Suave 3", smooth()))
        self.refresh()
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", preview=True, **form), {"FINISHED"})
        self.assertTrue(entity.enabled())
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **{**form, "in_steps": True}), {"RUNNING_MODAL"})
            self.assertEqual(step_modals.drive(self.running_road(), bpy.context)[0], {"FINISHED"})
            self.assertTrue(entity.enabled(), "calculada y sin crear, la vista previa sigue")
            self.assertIsNotNone(self.des_ops.calculation())
            self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
            self.assertEqual(step_modals.drive(self.running_road(), bpy.context)[0], {"FINISHED"})
        self.assertFalse(entity.enabled(), "se quita al crear la pista por pasos")
        self.assertEqual(self.entities.registry(self.project, self.v01.uid).get(self.code_of("Creada por pasos")).record.name, "Creada por pasos")

    # --- z: desactivar ---------------------------------------------------------------------------

    def test_z_disabling_geoblender_removes_the_command_and_the_open_calculation(self) -> None:
        """Principio 8, D-14 de la 013, RF-015-26: con un cálculo abierto y la vista previa activa, desactivar Geoblender los descarta (no queda ningún temporal ni vista previa) y
        quita la orden y sus listas."""
        self.refresh()
        entity = self.des_ops._entity_preview()
        apart = {"name": "Al apagar", "destination_point": "Destino norte", "start": f"entity:{self.code_of('Creada')}"}
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **self.form(**apart, preview=True)), {"FINISHED"})
        self.calculate_road(self.form(**apart))
        self.assertTrue(entity.enabled())
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, ROAD_CLASS, None))
        self.assertFalse(entity.enabled())
        self.assertFalse(any(".tmp" in name for name in self.names()))


# Las pruebas de la plataforma son de ``test_platform_ops.py``: aquí solo se aprovecha su proyecto.
for _name in dir(platform_ops.CreatePlatformTest):
    if _name.startswith("test_") and not hasattr(RoadOpsTest.__dict__.get(_name, None), "__call__"):
        setattr(RoadOpsTest, _name, None)


if __name__ == "__main__":
    unittest.main()
