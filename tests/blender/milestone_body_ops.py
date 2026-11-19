# SPDX-License-Identifier: GPL-3.0-or-later
"""«Cuerpo apoyado…» en Blender (spec 016, T25; HU-016-4; RF-016-20 a RF-016-22, RF-015-02, RF-015-03, RF-015-28, RF-015-29; RNF-016-02 y
05; plan 016 §5.3.3 y §5.5; comprobación manual M2).

:class:`GEOBLENDER_OT_des_create_body` (``geoblender.des_create_body``, interna, de la entrada 016) calcula con ``design.steps.body_run`` la
operación ``des.body`` de la versión activa: un cuerpo de espesor ≥ 0 con su huella, sus datos de espesor, una superficie conocida y su
sentido («sobre una base» o «bajo un techo»). Sigue el patrón de la retirada (T20): su diálogo pide el nombre, la huella (su capa y su
geometría), los datos de espesor (su capa, cómo se leen y su campo), la superficie conocida y su sentido, la partida («sobre una base»), la
distancia máxima (sin valor por defecto: D-9) y «cero en el borde»; Calcular, Crear, Cancelar y Esc son los de las demás órdenes
(``_CalculateAndCreate``): nada se registra hasta Crear. No retira nada ni deja una pared: no pide más confirmación.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, la ladera ``100 + 0,25·y + 0,0625·x``) con una capa
de huellas (un polígono de 48 × 48 m), una capa de puntos con el espesor de seis datos y otra con un espesor negativo. Las pruebas, en el
orden de sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
Spec 016, T43 (RNF-016-06): pasó del «verde» al paso «hito» (P-13), sin cambiar ninguna prueba; antes, ``test_body_ops.py``.
"""

import json
import math
import time
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

CREATE = "geoblender.des_create_body"
CREATE_CLASS = "GEOBLENDER_OT_des_create_body"
BODY_TYPE = "des.body"
DESCRIPTION = ("Create a body from its footprint and its thickness data, resting on a known surface or under a known roof: the "
               "thickness is interpolated and the other surface is derived from it")
FOOTPRINTS = "gis_fea_huellas"
THICKNESS = "gis_fea_espesores"
NEGATIVE = "gis_fea_malos_espesores"
BODY = "Cuerpo"
FOOTPRINT_BOX = (6.0, 6.0, 54.0, 54.0)
"""La huella (local): 48 × 48 m = 24 × 24 celdas de 2 m."""
DATA = ((14.0, 14.0, 1.0), (46.0, 14.0, 2.0), (14.0, 46.0, 2.0), (46.0, 46.0, 3.0), (30.0, 30.0, 1.5), (30.0, 14.0, 1.0))
"""Los seis datos de espesor (local: x, y y el espesor en m), uno por celda."""
ROOF, BASE = "Bajo la ladera", "Sobre la ladera"
PROPERTIES = {
    "name": ("Name", "Name of the body, unique in the active version"),
    "layer": ("Layer of the footprints", "Layer of polygons of the project the footprint of the body is taken from"),
    "feature": ("Footprint of the layer", "Name or number (fid) of the polygon of the layer that is the footprint of the body"),
    "data_layer": ("Layer of the thickness data", "Layer of the project with the thickness of the body: points or polygons with a "
                                                  "field, or 3D lines with the thickness in the Z of their vertices"),
    "data_from": ("Thickness from", "Where the thickness is read from: a field of the points or of the polygons (constant in each "
                                    "polygon), or the Z of the vertices of the 3D lines; it is not assumed"),
    "data_field": ("Thickness field", "Numeric field of the layer with the thickness in metres; it cannot be negative"),
    "sense": ("Sense", "On a base: the known surface is its support and the surface of the chain rises to the roof; under a roof: the "
                       "known surface is its roof, as the existing waste, and the surface does not change"),
    "surface": ("Known surface", "The surface the body rests on (on a base) or hangs under (under a roof): the ground, a design "
                                 "surface or the surface of an entity that changes the surface"),
    "start": ("Start surface", "Surface the body starts from (only on a base): the surface that rises to the roof of the body (by "
                               "default, the last of the chain)"),
    "max_distance": ("Maximum distance to the data (m)", "Farthest distance from a thickness datum, in metres: what is farther is "
                                                         "warned and triangles longer than twice this are not interpolated; it has "
                                                         "no default value: you choose it"),
    "zero_at_edge": ("Zero at the edge", "The thickness is zero at the edge of the footprint"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone quien lanza la orden, no los
llevan)."""
HIDDEN = ("confirm", "in_steps")
CHAIN_CANCELLED_TEXT = ("Cancelado: el cuerpo apoyado está creado; las restricciones declaradas y las máscaras se ponen al día antes de la "
                        "siguiente operación que las use, y la capa de entidades con la siguiente orden de entidades o «Recalcular lo obsoleto»")


class CreateBodyTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con las capas de la huella y de los datos."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_features(FOOTPRINTS, "polygon", (((platform_ops.ring(FOOTPRINT_BOX),),),), (BODY,), {})
        cls.write_features(THICKNESS, "point", tuple(((platform_ops.path(((x, y),)),),) for x, y, _t in DATA),
                           tuple(f"D{number}" for number in range(1, len(DATA) + 1)), {"espesor": tuple(t for _x, _y, t in DATA)})
        cls.write_features(NEGATIVE, "point", tuple(((platform_ops.path(((x, y),)),),) for x, y, _t in DATA[:3]),
                           ("N1", "N2", "N3"), {"espesor": (1.0, -0.5, 2.0)})
        cls.refresh()

    @classmethod
    def write_features(cls, name: str, kind: str, parts: tuple[Any, ...], names: tuple[str, ...], fields: dict[str, Any]) -> None:
        """La capa ``name`` de entidades (``nombre`` y sus campos numéricos), como la deja la importación de la 006."""
        gis_store, vector = platform_ops._module("gis.store"), platform_ops._module("gis.vector")
        datasets, builtin = platform_ops._module("core.datasets"), platform_ops._module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"), *(vector.FieldColumn(f, f, "DOUBLE") for f in fields))
        layer = vector.FeatureLayer(kind, tuple(range(1, len(parts) + 1)), parts, columns, {"nombre": names, **fields})
        rows = gis_store.feature_rows(layer, srs)
        defined = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
        marks = ", ".join("?" for _ in range(len(columns) + 2))
        handle = platform_ops._module("core.provenance.operations").begin_operation(
            cls.project, platform_ops.LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, {defined})')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) "
                         "VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                         "VALUES (?, 'geom', ?, ?, 0, 0)", (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
                input_uid=None, immutable=False),), message="Capa de la prueba del cuerpo apoyado")

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (también las de las capas del cuerpo), leídas de nuevo (un guion no abre el diálogo que las lee)."""
        super().refresh()
        if cls.project.record is not None:
            cls.panels.refresh_body_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(CREATE)

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo: el cuerpo «bajo la ladera» de la huella con los seis datos de la capa de espesores."""
        return {"name": ROOF, "layer": FOOTPRINTS, "feature": BODY, "data_layer": THICKNESS, "data_from": "FIELD",
                "data_field": "espesor", "sense": "UNDER_ROOF", "surface": self.ground, "max_distance": "100", "in_steps": False,
                **values}

    def fake_dialog(self, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:  # type: ignore[override]
        """El operador de mentira, el contexto con que se abre el diálogo (sin ventana), el diálogo y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {
            "name": "", "layer": "", "feature": "", "data_layer": "", "data_from": "FIELD", "data_field": "", "sense": "UNDER_ROOF",
            "surface": "", "start": "", "max_distance": "", "zero_at_edge": False, "confirm": False, "in_steps": False,
            "provenance_dialog": False, "report": lambda kind, text: said.append((kind, text)),
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        return operator_self(self.cls, **fields), context, dialog, said

    def calculate(self, **values: Any) -> Any:  # type: ignore[override]
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", **self.form(**values)), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create(self, **values: Any) -> set[str]:  # type: ignore[override]
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", confirm=True, in_steps=False, **values)

    def operations(self) -> list[tuple[str, str]]:
        return self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ? ORDER BY fid", BODY_TYPE)

    def parameter_of(self, code: str, param: str) -> tuple[Any, ...]:
        """La fila de la versión del parámetro ``param`` de la entidad ``code`` (``des.body.bdy_001.*``): valor, origen, tipo y decisor."""
        ((value, source, kind, decider),) = self.rows(
            "SELECT value, source, kind, decided_by FROM gb_parameter WHERE key = ? AND scope = 'version' AND scope_uid = ?",
            f"des.body.{code.lower().replace('-', '_')}.{param}", self.v01.uid)
        return json.loads(value), source, kind, decider

    def states(self) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, self.v01.uid)}

    def layer_rows(self) -> dict[str, Any]:
        """Las filas de la capa de entidades de V01 (``des_enl_v01``), por código; ninguna si aún no se escribió (T34, T41)."""
        layer = platform_ops._module("design.entity_layer")
        table = layer.entity_layer_table(self.v01.code)
        with self.project.read() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone():
                return {}
            return {item.code: item for item in layer.read_entity_layer(conn, table)}

    def declared(self) -> tuple[Any, ...]:
        """Las restricciones que declaran las entidades de V01."""
        declared = platform_ops._module("core.constraints.declared")
        with self.project.read() as conn:
            return tuple(declared.read_in_version(conn, self.v01.uid))

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_is_a_real_internal_command_with_named_properties(self) -> None:
        """RF-016-20, RF-015-28 (plan §5.3.3): «Cuerpo apoyado…» es una orden real y **interna** de ``des.body``, de la entrada 016 que la
        entrega, con la puerta de la procedencia, los pasos con Esc (≤ 0,05 s por paso) y el ``poll`` común de Diseño; su descripción es la
        del catálogo; sus propiedades tienen nombre y descripción en español; las que pone quien la lanza, no."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertEqual(cls.__name__, CREATE_CLASS)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertTrue(issubclass(cls, self.des_ops._CalculateAndCreate))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options, cls.COMMAND), (CREATE, BODY_TYPE, {"REGISTER"}, CREATE))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.BODY_COMMAND, CREATE)
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[BODY_TYPE].commands, (CREATE,))
        catalog = self.commands.catalog()
        command = catalog.commands[CREATE]
        self.assertEqual((command.kind, command.entry, command.module, command.label, command.label_es, command.home),
                         ("operator", "016", "des", "Supported body…", "Cuerpo apoyado…", "GEOBLENDER_MT_des_entities"))  # T35: en el menú Entidades
        self.assertEqual(command.description, DESCRIPTION)
        self.assertEqual(cls.__doc__.strip(), DESCRIPTION)
        self.assertTrue(catalog.entries["016"].delivered)
        self.assertTrue(self.commands.is_available(CREATE))
        self.assertEqual(cls.bl_label, "Cuerpo apoyado…", "registrada ya en español")
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, set(PROPERTIES))
        for prop, (label, about) in PROPERTIES.items():
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label), self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        for prop in HIDDEN:
            self.assertNotIn("name", cls.__annotations__[prop].keywords)
        self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(bpy.ops.geoblender.des_create_body.poll())

    def test_b_the_dialog_offers_the_layers_proposes_and_draws_what_it_asks(self) -> None:
        """RF-016-20, M2: el diálogo ofrece las capas de **polígonos** para la huella y las de puntos, de polígonos y de líneas 3D para los
        datos (con su geometría); propone un nombre que no repite el de ninguna entidad, la primera capa de huellas y de datos, cómo se lee
        su espesor y las superficies; **no propone** la distancia máxima (D-9); dibuja lo que pide, con su sentido; sin ninguna capa de
        polígonos, lo dice; y no escribe nada."""
        cls = self.cls
        self.refresh()
        footprints = [(identifier, label) for identifier, label, _about in self.panels.body_footprint_items(None, None)]
        self.assertEqual(footprints, [(FOOTPRINTS, FOOTPRINTS.removeprefix("gis_fea_"))], "solo la capa de polígonos de las huellas")
        data = {identifier: about for identifier, _label, about in self.panels.body_data_items(None, None)}
        self.assertEqual(set(data), {FOOTPRINTS, THICKNESS, NEGATIVE}, "puntos y polígonos (las líneas, de la plataforma, no)")
        self.assertEqual((self.panels.body_data_kind(THICKNESS), self.panels.body_data_kind(FOOTPRINTS)), ("point", "polygon"))
        before = self.state()
        fake, context, dialog, said = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(said, [])
        self.assertEqual(dialog.call_args.kwargs["title"], "Cuerpo apoyado…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.name, fake.layer, fake.data_from), ("Cuerpo apoyado", FOOTPRINTS, "FIELD"))
        self.assertIn(fake.data_layer, data)
        self.assertEqual(fake.surface, self.ground, "el terreno")
        self.assertEqual(fake.max_distance, "", "la distancia máxima no tiene valor por defecto (D-9): no se propone")
        given, context, _dialog, _said = self.fake_dialog(
            name="Mío", layer=FOOTPRINTS, data_layer=NEGATIVE, properties=SimpleNamespace(is_property_set=lambda name: name in (
                "name", "layer", "data_layer")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.layer, given.data_layer), ("Mío", FOOTPRINTS, NEGATIVE), "lo dado no cambia")
        shown = draw(cls, bpy.context, name="x", layer=FOOTPRINTS, feature=BODY, data_layer=THICKNESS, data_from="FIELD",
                     data_field="espesor", sense="ON_BASE", surface=self.ground, start=self.ground, max_distance="", zero_at_edge=False,
                     confirm=False).texts()
        for heading in ("Nombre", "Huella del cuerpo", "Capa", "Huella de la capa", "Datos de espesor", "Espesor desde", "Campo del espesor",
                        "Superficie conocida", "Sentido", "Superficie de partida", "Distancia máxima a los datos (m)", "Cero en el borde"):
            self.assertIn(heading, shown)
        under = draw(cls, bpy.context, name="x", layer=FOOTPRINTS, feature=BODY, data_layer=THICKNESS, data_from="Z", data_field="",
                     sense="UNDER_ROOF", surface=self.ground, start="", max_distance="", zero_at_edge=False, confirm=False).texts()
        self.assertNotIn("Campo del espesor", under, "de la Z de los vértices no hay campo")
        self.assertNotIn("Superficie de partida", under, "bajo un techo no hay partida")
        with mock.patch.object(self.panels, "has_body_footprints", return_value=False):
            empty, context, dialog, said = self.fake_dialog()
            self.assertEqual(cls.invoke(empty, context, None), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "No hay ninguna capa de polígonos en el proyecto: importe antes las huellas de los cuerpos")])
        self.assertEqual(self.state(), before, "el diálogo no escribe nada")
        self.refresh()

    def test_c_calculate_writes_nothing_and_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-015-03, RF-015-29, RNF-016-05, RF-016-20, RF-016-21, M2: «Calcular» desde un guion deja el cálculo abierto con su resumen
        (el volumen, el espesor máximo con su lugar, de dónde sale el espesor y que no cambia la superficie, en los dos idiomas, con su
        título) y **solo los temporales**; nada en el proyecto. Esc **a mitad** (con su temporal ya escrito), cancelar la confirmación y lo
        que falta o se rechaza (el nombre, la huella, la distancia máxima sin valor, fuera de rango o que no es un número, un espesor
        negativo, una huella que no existe) no dejan nada: ni operación, ni dato, ni parámetro, ni cifra, ni temporal."""
        self.refresh()
        before = self.state()
        held = self.calculate()
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), (BODY_TYPE, ROOF, "V01", "BDY-001"))
        after = self.state()
        self.assertEqual(after[:4], before[:4], "calcular no registra nada")
        self.assertEqual(len(sorted(set(after[4]) - set(before[4]))), 2, "los temporales del espesor y de la base")
        self.assertTrue(all(".tmp" in name for name in sorted(set(after[4]) - set(before[4]))))
        self.assertEqual(self.view.summary_title, f"Cuerpo apoyado «{ROOF}» en V01")
        outcome = held.outcome
        self.assertGreater(outcome.volume_m3, 0.0)
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertTrue(summary[0][0].startswith(f"Cuerpo apoyado «{ROOF}» (BDY-001) bajo un techo: "), summary[0])
        self.assertIn(" m³ · mayor espesor ", summary[0][0])
        self.assertTrue(summary[1][0].startswith(f"Espesor de «{THICKNESS}»: 6 celdas con dato · "), summary[1])
        self.assertEqual(summary[2], ("Deja su base y su espesor: la superficie conocida es su techo y no cambia", False))
        self.assertFalse(any(alert for _text, alert in summary), "nada que avisar con los seis datos y 100 m")
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, f"Supported body «{ROOF}» in V01")
        self.assertTrue(self.view.summary[0].name.startswith(f"Supported body «{ROOF}» (BDY-001) under a roof: "))
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before, "descartar borra los temporales")

        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", **self.form(name="Esc", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running()
        modal.STEP_BUDGET_S = step_modals.ONE_STEP_S  # un paso por evento
        for _ in range(step_modals.MAX_EVENTS):
            self.assertEqual(modal.modal(bpy.context, step_modals.TIMER), {"RUNNING_MODAL"})
            if any(".tmp" in name for name in self.names()):
                break
        else:
            self.fail("el cálculo no llegó a escribir su temporal")
        stopped = time.perf_counter()
        self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertLessEqual(time.perf_counter() - stopped, 2.0, "Esc responde en ≤ 2 s (RNF-016-05)")
        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
        self.assertIsNone(modal._steps)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        self.calculate(name="Cancelada")
        self.assertTrue(any(".tmp" in name for name in self.names()))
        self.cls.cancel(operator_self(self.cls, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        for changes, text in (
                ({"name": " "}, "Escriba el nombre del cuerpo"),
                ({"feature": " "}, "Escriba el nombre o el número de la huella en su capa"),
                ({"data_field": " "}, "Escriba el campo de la capa con el espesor"),
                ({"max_distance": ""}, "max_distance_m"),
                ({"max_distance": "abc"}, "«abc» no es un número"),
                ({"max_distance": "0"}, "max_distance_m"),
                ({"data_layer": NEGATIVE}, "-0,5"),
                ({"feature": "No hay"}, "No hay"),
                ({"data_from": "Z"}, "«z»")):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", **self.form(**changes))
                self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)

    def test_d_create_registers_the_body_under_a_roof_in_one_transaction_and_chains_what_follows(self) -> None:
        """RF-016-20, RF-016-01, RF-015-02, RF-015-01, RF-015-27, RF-016-24, RNF-016-07, M2: «Crear» el cuerpo «bajo la ladera» registra
        ``des.body`` hecho en V01 con su espesor y su base **dispersos** (ninguna superficie: no cambia la de nadie), su huella y su informe,
        las cifras CALCULADO y los parámetros de la entidad como filas de la versión (de quien tiene abierto el proyecto; la distancia con el
        origen del diálogo), y la entidad al día **sin cadena**; **encadena lo que sigue** (T41: ``entity_store.after_entity_change``): la
        capa de entidades (``des_enl_v01``) tiene ya su fila sin otra orden; **no declara restricciones** (el cuerpo no declara) ni toca las
        capas ni la ladera."""
        self.refresh()
        ground_before = self.rows("SELECT content_sha256 FROM gb_dataset WHERE name = ?", self.ground)
        layers_before = self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name IN (?, ?)", FOOTPRINTS, THICKNESS)
        declared = self.declared()
        self.assertEqual(self.layer_rows(), {}, "aún no hay capa de entidades")
        held = self.calculate()
        volume = held.outcome.volume_m3
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.operations()
        self.assertEqual(status, "done")
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual(figures["des.bdy_volume_m3"], volume)
        self.assertEqual((figures["des.bdy_ignored"], figures["des.bdy_far_m2"]), (0.0, 0.0))
        for family in ("bdt", "bds", "epr", "prp"):
            self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND name = ?",
                                       self.dprov.dataset_name(family, ROOF)), [(1,)], family)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name = ?", self.dprov.dataset_name("psf", ROOF)), [(0,)],
                         "bajo un techo no cambia la superficie")
        found = self.parameter_of("BDY-001", "max_distance_m")
        self.assertEqual(found[0], 100.0)
        self.assertEqual(found[1], f"diálogo de «Cuerpo apoyado…», entidad «{ROOF}»")
        self.assertEqual((found[2], found[3]), ("ADOPTADO", self.project.session.user_host))
        for param, value in (("layer", FOOTPRINTS), ("data_layer", THICKNESS), ("data_field", "espesor"), ("data_from", "field"),
                             ("surface", self.ground), ("sense", "under_roof"), ("zero_at_edge", False)):
            self.assertEqual(self.parameter_of("BDY-001", param)[0], value, param)
        self.assertEqual(self.states(), {"BDY-001": "current"})
        entry = self.entities.registry(self.project, self.v01.uid).get("BDY-001")
        self.assertEqual((str(entry.record.kind), entry.record.start), ("body", None))
        self.assertEqual(self.declared(), declared, "un cuerpo no declara restricciones: lo que sigue no declara nada")
        rows = self.layer_rows()
        self.assertEqual(sorted(rows), ["BDY-001"], "la capa de entidades tiene ya la fila del cuerpo, sin otra orden")
        row = rows["BDY-001"]
        self.assertEqual((row.name, str(row.kind), str(row.state), row.start), (ROOF, "body", "current", None))
        self.assertTrue(math.isclose(row.volume_m3, volume, rel_tol=1e-9), "con su volumen")
        self.assertEqual(self.rows("SELECT content_sha256 FROM gb_dataset WHERE name = ?", self.ground), ground_before)
        self.assertEqual(self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name IN (?, ?)", FOOTPRINTS, THICKNESS),
                         layers_before, "las capas de entrada no se tocan")
        self.refresh()
        self.assertNotIn("entity:BDY-001", [identifier for identifier, _label, _about in self.panels.platform_start_items(None, None)],
                         "nadie parte de la superficie de un cuerpo bajo un techo: no se ofrece")

    def test_e0_the_summary_tells_the_step_at_the_edge_as_an_informative_line(self) -> None:
        """RF-015-13, RF-016-20, M2 (T46, hallazgo C-1; decisión de la sesión principal, 19/11/2026): un cuerpo «sobre una base» cuyo espesor en
        el borde de la huella no es 0 termina en un escalón: el resumen de «Calcular» lo dice con **un renglón informativo** (en los dos idiomas,
        **sin ámbar**: es una nota, no un aviso); con «cero en el borde» no sale; calcular y descartar lo deja todo como estaba."""
        self.refresh()
        before = self.state()
        held = self.calculate(name="Con escalón", sense="ON_BASE", start=self.ground)
        (notice,) = [item for item in held.summary.notices if item.code == "des.body_edge_step"]
        self.assertEqual(notice.severity, "note")
        self.assertGreaterEqual(float(notice.values["step"]), 1.0, "el espesor del borde es de 1 a 3 m")
        for language, words in (("es", "escalón de hasta"), ("en", "step of up to")):
            self.i18n.set_language(language)
            self.panels.show_summary(held)
            found = [line for line in self.view.summary if words in line.name]
            self.assertEqual(len(found), 1, (language, [line.name for line in self.view.summary]))
            self.assertFalse(found[0].alert, "un renglón informativo no va en ámbar")
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before, "descartar borra los temporales")
        calm = self.calculate(name="Sin escalón", sense="ON_BASE", start=self.ground, zero_at_edge=True)
        self.assertEqual([item for item in calm.summary.notices if item.code == "des.body_edge_step"], [])
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before)

    def test_e_a_body_on_a_base_leaves_the_surface_and_nobody_starts_from_the_one_under_a_roof(self) -> None:
        """RF-016-20, H-9, RF-015-04, M2: «Sobre una base» (la ladera es el apoyo y la partida) deja la superficie con el techo
        (``des_psf_``), su espesor, su huella y su informe, y **encadena**: la entidad parte de su partida y su superficie se ofrece como
        partida; la superficie del cuerpo «bajo la ladera» **no se ofrece como partida** (el dominio la rechaza con ``des.chainless_start``, de
        lo que se encarga ``milestone_body_operation``) y Blender no admite una opción que no está en la lista: no se escribe nada y no queda un
        cálculo abierto; la superficie del cuerpo sobre la base crece sobre la ladera donde hay espesor."""
        self.refresh()
        before = self.state()
        with self.assertRaises(TypeError) as caught:  # el diálogo no la ofrece: Blender no admite una opción que no está en su lista
            bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", **self.form(name="Otro", sense="ON_BASE", start="entity:BDY-001"))
        self.assertIn("entity:BDY-001", str(caught.exception))
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)
        held = self.calculate(name=BASE, sense="ON_BASE", start=self.ground)
        self.assertEqual((held.entity.code, held.entity.start_surface), ("BDY-002", self.ground))
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(self.states(), {"BDY-001": "current", "BDY-002": "current"})
        self.assertEqual(sorted(self.layer_rows()), ["BDY-001", "BDY-002"], "la capa de entidades, al día sin otra orden (T41)")
        for family in ("bdt", "psf", "epr", "prp"):
            self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND name = ?",
                                       self.dprov.dataset_name(family, BASE)), [(1,)], family)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name = ?", self.dprov.dataset_name("bds", BASE)), [(0,)])
        self.assertEqual(self.parameter_of("BDY-002", "start")[0], self.ground)
        self.assertEqual(self.parameter_of("BDY-002", "sense")[0], "on_base")
        self.refresh()
        self.assertIn("entity:BDY-002", [identifier for identifier, _label, _about in self.panels.platform_start_items(None, None)])
        locator = self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'",
                            self.dprov.dataset_name("psf", BASE))[0][0]
        surface = platform_ops._module("gis.geotiff.reader").read_geotiff(self.project.root / locator).values
        ground = platform_ops.ground()
        self.assertTrue(np.all(surface >= ground - 1e-9), "el techo nunca queda bajo la partida")
        self.assertGreater(float((surface - ground).max()), 0.5, "sube hasta el techo donde hay espesor")

    def test_f_the_body_command_is_disabled_with_its_reason(self) -> None:
        """RF-015-28, RF-016-20: con el proyecto en solo lectura o con la versión activa no editable (V02 SUPERADO) la orden sale
        desactivada con su motivo y no se puede lanzar; con V01 en escritura, activa."""
        messages: list[str] = []
        cls = self.cls

        def poll() -> bool:
            messages.clear()
            with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                return bool(cls.poll(bpy.context))

        self.assertTrue(poll())
        self.assertEqual(messages, [])
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(poll())
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_create_body.poll())
            before = self.state()
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", **self.form(name="No debe"))
            self.assertEqual(self.state(), before)
        self.assertTrue(poll())
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", (platform_ops.REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        not_editable = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertFalse(poll())
        self.assertEqual(messages, [not_editable])
        self.assertFalse(bpy.ops.geoblender.des_create_body.poll())
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.assertTrue(poll())

    def test_g_esc_in_what_follows_creating_the_body_says_it_is_created_and_the_next_order_updates_the_layer(self) -> None:
        """RF-015-10, RF-015-29, RNF-016-05, RF-015-27, M2 (T41): Esc **en lo que sigue a «Crear»** (la declaración, las máscaras y la capa de
        entidades, por pasos con su avance) deja el cuerpo **creado** —la orden lo dice— y la capa de entidades sin su fila, hasta que lo que
        sigue se hace de nuevo (aquí, ``after_entity_change``, que encadena también la orden siguiente): lo creado no se pierde."""
        self.refresh()
        self.calculate(name="Bajo otro techo")
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
            modal = self.running()
            modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
            state, _count = step_modals.drive(modal, bpy.context, stop_after=0)
            self.assertEqual(state, {"RUNNING_MODAL"}, "lo que sigue no debía haber acabado")
            self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertIn(CHAIN_CANCELLED_TEXT, list(modal.report_log))
        self.assertEqual(self.states()["BDY-003"], "current", "el cuerpo está creado")
        self.assertNotIn("BDY-003", self.layer_rows(), "y la capa aún no tiene su fila")
        self.assertIsNone(self.des_ops.calculation())
        last = None
        for last in platform_ops._module("design.entity_store").after_entity_change(self.project, self.v01.uid):
            pass
        self.assertIsNone(last.result.failure, None if last.result.failure is None else last.result.failure.reason)
        self.assertIsNone(last.result.layer_failure, None if last.result.layer_failure is None else last.result.layer_failure.reason)
        self.assertIn("BDY-003", self.layer_rows(), "ahora sí")

    def test_z_disabling_geoblender_removes_the_body_command_and_leaves_no_temporary(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta (no queda ningún temporal) y quita la
        orden."""
        self.refresh()
        held = self.calculate(name="Al apagar", feature=BODY, surface=self.ground, sense="UNDER_ROOF")
        self.assertTrue(any(".tmp" in name for name in self.names()))
        self.assertIsNotNone(held)
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, CREATE_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test"):
        setattr(CreateBodyTest, _name, None)


if __name__ == "__main__":
    unittest.main()
