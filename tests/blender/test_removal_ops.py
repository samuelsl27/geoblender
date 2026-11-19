# SPDX-License-Identifier: GPL-3.0-or-later
"""«Retirar un acopio…» en Blender (spec 016, T20 (b); HU-016-2; RF-016-11 a RF-016-15, RF-015-02, RF-015-03, RF-015-28, RF-015-29;
RNF-016-05; plan 016 §5.3.3 y §5.5; comprobación manual M1).

:class:`GEOBLENDER_OT_des_remove_stockpile` (``geoblender.des_remove_stockpile``, interna, de la entrada 016) calcula con
``design.steps.removal_run`` la operación ``des.stockpile_removal`` de la versión activa: la huella de un acopio de una detección en su
base, unida al terreno por una transición. **Es el patrón de la orden que calcula y crea de la 016** (el cuerpo apoyado, T25, y el
contrafuerte, T27): su diálogo pide el nombre, el acopio, la partida, **lo que se apoya en el acopio** (una sola lista, antes de
calcular), el ángulo de transición, el factor de malla, la métrica y el motivo de la pared; Calcular, Crear, Cancelar y Esc son los de las
demás órdenes (``_CalculateAndCreate``): nada se registra hasta Crear y no se crea sin la confirmación expresa de lo apoyado ni de la
pared.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02) con un levantamiento (un plano de 1,8° con dos
montones de pirámide truncada de 12 m de pie y 4 m de altura, a 16 y 44 m), una capa de marcas (una de 20 × 20 m por montón), la
detección de acopios ``Acopios`` (``STK-001``, **del proyecto**: la superficie es del proyecto) y la plataforma «Sobre acopio»
(``PLT-001``, «en corte y relleno» a 108 m: rellena por encima del Acopio 2 y parte del levantamiento). Las retiradas parten de ella y
cada una de la anterior. Las pruebas, en el orden de sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import json
import math
import time
import unittest
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

REMOVE = "geoblender.des_remove_stockpile"
REMOVE_CLASS = "GEOBLENDER_OT_des_remove_stockpile"
REMOVAL_TYPE = "des.stockpile_removal"
DESCRIPTION = ("Remove a stockpile detected in the active version: its footprint goes down to its base, joined with the ground "
               "by a transition, and what rests on it is listed before calculating")
MARKS_LAYER = "gis_fea_marcas"
MARKS = (("Acopio 1", (6.0, 20.0, 26.0, 40.0)), ("Acopio 2", (34.0, 20.0, 54.0, 40.0)))
"""Las marcas de la capa (nombre y caja local): una de 20 × 20 m por montón, a 8 m una de otra."""
MOUNDS = ((16.0, 30.0), (44.0, 30.0))
"""El centro (local) de cada montón: una pirámide truncada de 12 m de pie y 4 m de altura (pendiente 1)."""
OVER = ("Sobre acopio", ((38.0, 30.0), (50.0, 30.0)), 8.0, 108.0, 0.0)
"""La plataforma que rellena por encima del Acopio 2: eje, ancho, cota inicial y pendiente de su capa."""
FIRST, SECOND, THIRD = "Retirada del acopio 1", "Retirada del acopio 2", "Otra retirada"
ANGLE = "30"
DECLARE_TYPE = platform_ops.DECLARE_TYPE
PROPERTIES = {
    "name": ("Name", "Name of the removal, unique in the active version"),
    "stockpile": ("Stockpile", "Stockpile to remove: one of the detections of the active version or of the project; one whose "
                               "detection is out of date is refused, saying what changed"),
    "start": ("Start surface", "Surface the stockpile is removed from: the ground, a design surface or the surface of another entity "
                               "(by default, the last of the chain)"),
    "transition_angle": ("Transition angle (°)", "Angle of the slope that joins the removed footprint with the rest of the surface, "
                                                 "in degrees; it has no default value: you choose it"),
    "mesh_factor": ("Mesh factor", "Factor of the mesh of the transition, or of the edge of the platform (empty: the default value)"),
    "metric": ("Metric", "How the distance to the footprint is measured in the transition or in the edge of the platform: the 5×5 "
                         "chamfer (fast, with the scale of the grid) or the exact Euclidean distance"),
    "wall_reason": ("Reason for the wall", "Why you accept the wall that removing the stockpile may leave at the edge of what is "
                                           "removed: it is needed only if the wall passes the height and the angle that ask for a "
                                           "reason, and it is recorded with the removal"),
    "as_platform": ("As a platform", "Remove the stockpile as a platform: its whole footprint is left in the plane of its base and a "
                                     "platform of the chain is made with it, with its edge, its checks and its constraints; the "
                                     "transition angle and the wall do not apply"),
    "edge_angle": ("Edge angle (°)", "Angle of the slope that joins the platform with the ground, in degrees"),
    "reach": ("Reach of the edge (m)", "Farthest distance from the footprint the edge can reach, in metres"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone quien lanza la orden, no los
llevan)."""
HIDDEN = ("confirm", "in_steps", "confirm_resting", "confirm_wall")
EDGE_ANGLE, REACH = "35", "10"
"""El borde de «como plataforma»: ángulo y alcance (no tienen valor por defecto: D-7 y D-20 de la 015)."""
AS_PLATFORM = "Acopio 1 como plataforma"
OVER_PLATFORM = "Acopio 2 como plataforma"
PLATFORM_TYPE = "des.platform"
CHAIN_CANCELLED_TEXT = ("Cancelado: la retirada está creada; las restricciones declaradas y las máscaras se ponen al día antes de la "
                        "siguiente operación que las use, y la capa de entidades con la siguiente orden de entidades o «Recalcular lo obsoleto»")


def survey() -> np.ndarray:
    """El levantamiento: un plano de 1,8° (``100 + 0,03·y + 0,01·x``) con un montón de pirámide truncada en cada centro de
    :data:`MOUNDS` (``clip(6 − d, 0, 4)`` con ``d`` la distancia de Chebyshev al centro: 12 m de pie, 4 m de cima y 4 m de altura)."""
    x, y = platform_ops.centers()
    found = 100.0 + 0.03 * y + 0.01 * x
    for cx, cy in MOUNDS:
        found = found + np.clip(6.0 - np.maximum(np.abs(x - cx), np.abs(y - cy)), 0.0, 4.0)
    return found


def forged_wall(removal: Any, progress: Any, height_m: float, angle_deg: float) -> Any:
    """Una pared de un tramo (como la que deja una superficie sin transición: la de A6 nunca la deja, T19) en lugar de medirla."""

    def walled(job: Any, outcome: Any, project: Any, *, budget_s: float = 0.05) -> Iterator[Any]:
        stretch = removal.WallStretch(1, 6, height_m, angle_deg, 4.0, 100.0, 200.0)
        wall = removal.Wall((stretch,), outcome.transition_deg, 1.0, 0.02, 1.0, 6, 6)
        found = dataclasses.replace(outcome, wall=wall, wall_max_m=wall.height_m,
                                    notices=(*outcome.notices, *removal.wall_notices(outcome.stockpile_name, wall)))
        yield progress("removal_wall", 1, 1, "Pared medida", result=found)

    return mock.patch.object(removal, "wall_steps", walled)


class RemoveStockpileTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con un levantamiento, las marcas, la detección
    de acopios y la plataforma que rellena sobre el Acopio 2."""

    survey_name: str

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, OVER)):
            super().setUpClass()
        cls.survey_name = cls.write_grid("Levantamiento", survey())
        cls.write_marks()
        cls.detect()
        cls.refresh()
        assert len(cls.removable()) == 2, "la detección tiene que dar los dos acopios"
        assert bpy.ops.geoblender.des_create_platform(
            "EXEC_DEFAULT", name=OVER[0], layer=platform_ops.LAYER, feature=OVER[0], start=cls.survey_name, mode="CUT_FILL",
            edge_angle="35", reach="10", in_steps=False) == {"FINISHED"}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False) == {"FINISHED"}
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (también la de los acopios), leídas de nuevo (un guion no abre el diálogo que las lee)."""
        super().refresh()
        if getattr(cls, "survey_name", None) is not None:
            cls.panels.refresh_removal_choices(cls.project)

    @classmethod
    def write_marks(cls) -> None:
        """La capa ``gis_fea_marcas`` de polígonos con las marcas de :data:`MARKS` (``nombre``), como la deja la importación de la 006."""
        gis_store, vector = platform_ops._module("gis.store"), platform_ops._module("gis.vector")
        datasets, builtin = platform_ops._module("core.datasets"), platform_ops._module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),)
        layer = vector.FeatureLayer("polygon", tuple(range(1, len(MARKS) + 1)),
                                    tuple(((platform_ops.ring(box),),) for _name, box in MARKS), columns,
                                    {"nombre": tuple(name for name, _box in MARKS)})
        rows = gis_store.feature_rows(layer, srs)
        handle = platform_ops._module("core.provenance.operations").begin_operation(
            cls.project, platform_ops.LAYERS_TYPE, settings={"name": MARKS_LAYER}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{MARKS_LAYER}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, "nombre" TEXT)')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) "
                         "VALUES (?, 'features', ?, '', ?)", (MARKS_LAYER, MARKS_LAYER, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                         "VALUES (?, 'geom', ?, ?, 0, 0)", (MARKS_LAYER, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{MARKS_LAYER}" VALUES (?, ?, ?)', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                MARKS_LAYER, "gis", "vector", datasets.Store.GPKG, MARKS_LAYER, reader=builtin.GPKG_LAYER.id, role="features",
                crs_epsg=srs, input_uid=None, immutable=False),), message="Capa de marcas de la prueba")

    @classmethod
    def detect(cls) -> None:
        """«Calcula» y «crea» la detección ``Acopios`` (las dos marcas, sin candidatos, con 3 m de margen) sobre el levantamiento: como
        la superficie es del proyecto, la detección también (``des.stockpile_detect_project``, D-15)."""
        steps, model = platform_ops._module("design.steps"), platform_ops._module("design.model")
        request = model.StockpileRequest("Acopios", model.StockpileFields(MARKS_LAYER, name_field="nombre"), cls.survey_name,
                                         candidates=False, margin_m=3.0)
        found = None
        for step in steps.stockpile_run(cls.project, request, version=cls.v01.uid):
            found = step.result or found
        assert found is not None
        found.create()

    @classmethod
    def removable(cls) -> tuple[Any, ...]:
        return platform_ops._module("design.supported_store").removable_stockpiles(cls.project, cls.v01.uid)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(REMOVE)

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo: el Acopio 1 desde la superficie de la plataforma, con la transición a 30°."""
        return {"name": FIRST, "stockpile": "STK-001#Acopio 1", "start": "entity:PLT-001", "transition_angle": ANGLE,
                "in_steps": False, **values}

    def fake_dialog(self, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:  # type: ignore[override]
        """El operador de mentira, el contexto con que se abre el diálogo (sin ventana), el diálogo y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {
            "name": "", "stockpile": "", "start": "", "transition_angle": "", "mesh_factor": "", "metric": "EXACT",
            "wall_reason": "", "as_platform": False, "edge_angle": "", "reach": "", "confirm": False, "in_steps": False,
            "confirm_resting": False, "confirm_wall": False,
            "provenance_dialog": False, "report": lambda kind, text: said.append((kind, text)),
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        return operator_self(self.cls, **fields), context, dialog, said

    def calculate(self, **values: Any) -> Any:  # type: ignore[override]
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.form(**values)), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create(self, **values: Any) -> set[str]:  # type: ignore[override]
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", confirm=True, in_steps=False, **values)

    def operations(self) -> list[tuple[str, str]]:
        return self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ? ORDER BY fid", REMOVAL_TYPE)

    def settings_of(self, name: str) -> dict[str, Any]:
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE op_type = ? AND settings LIKE ? AND status = 'done'",
                                   REMOVAL_TYPE, f"%{name}%")
        return json.loads(settings)

    def parameter_of(self, code: str, param: str) -> tuple[Any, ...]:
        """La fila de la versión del parámetro ``param`` de la entidad ``code`` (``des.removal.rmv_001.*``): valor, origen, tipo y
        decisor."""
        ((value, source, kind, decider),) = self.rows(
            "SELECT value, source, kind, decided_by FROM gb_parameter WHERE key = ? AND scope = 'version' AND scope_uid = ?",
            f"des.removal.{code.lower().replace('-', '_')}.{param}", self.v01.uid)
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

    def platform_form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo «como plataforma»: el Acopio 1 desde la superficie de la plataforma, con el borde a 35° y 10 m."""
        return self.form(**{"name": AS_PLATFORM, "as_platform": True, "edge_angle": EDGE_ANGLE, "reach": REACH, **values})

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_is_a_real_internal_command_with_named_properties(self) -> None:
        """RF-016-11, RF-015-28 (plan §5.3.3): «Retirar un acopio…» es una orden real y **interna** de ``des.stockpile_removal``, de la
        entrada 016 que la entrega, con la puerta de la procedencia, los pasos con Esc (≤ 0,05 s por paso) y el ``poll`` común de Diseño;
        su descripción es la del catálogo; sus propiedades tienen nombre y descripción en español; las que pone quien la lanza, no."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertEqual(cls.__name__, REMOVE_CLASS)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertTrue(issubclass(cls, self.des_ops._CalculateAndCreate))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options, cls.COMMAND),
                         (REMOVE, REMOVAL_TYPE, {"REGISTER"}, REMOVE))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.REMOVAL_COMMAND, REMOVE)
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[REMOVAL_TYPE].commands, (REMOVE,))
        catalog = self.commands.catalog()
        command = catalog.commands[REMOVE]
        self.assertEqual((command.kind, command.entry, command.module, command.label, command.label_es, command.home),
                         ("internal", "016", "des", "Remove a stockpile…", "Retirar un acopio…", ""))
        self.assertEqual(command.description, DESCRIPTION)
        self.assertEqual(cls.__doc__.strip(), DESCRIPTION)
        self.assertTrue(catalog.entries["016"].delivered, "la entrega la T20")
        self.assertEqual(catalog.entries["016"].title_es, "Acopios, contrafuerte y cuerpos apoyados")
        self.assertFalse(catalog.entries["R-36"].delivered, "R-36 sigue como entrada del roadmap, sin entregar (la T35 pasó sus órdenes a la 016)")
        self.assertTrue(self.commands.is_available(REMOVE))
        self.assertEqual(cls.bl_label, "Retirar un acopio…", "registrada ya en español")
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
        self.assertTrue(bpy.ops.geoblender.des_remove_stockpile.poll())

    def test_b_the_dialog_offers_the_stockpiles_proposes_and_lists_what_rests_on_them_before_calculating(self) -> None:
        """RF-016-14 (A7), RF-016-11, M1: el diálogo ofrece los acopios de la detección con su nombre y su detección; propone el primero,
        un nombre que no repite el de ninguna entidad y la partida: **la última de la cadena** (la plataforma); **antes de calcular** y
        sin escribir nada enseña **una sola lista** de lo que se apoya en el acopio elegido sobre la partida —nada en el Acopio 1; la
        plataforma, con su tipo y sus m³, en el Acopio 2— y lo que pasa si se retira; lo que no se puede leer sale en ámbar; sin ninguna
        detección, lo dice."""
        cls = self.cls
        self.refresh()
        items = [(identifier, label) for identifier, label, _about in self.panels.removal_stockpile_items(None, None)]
        self.assertEqual(items, [("STK-001#Acopio 1", "Acopio 1 (STK-001)"), ("STK-001#Acopio 2", "Acopio 2 (STK-001)")])
        about = [about for _identifier, _label, about in self.panels.removal_stockpile_items(None, None)]
        self.assertTrue(about[0].startswith("Acopio de la detección «Acopios» (STK-001) del proyecto: "), about[0])
        before = self.state()
        fake, context, dialog, said = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(said, [])
        self.assertEqual(dialog.call_args.kwargs["title"], "Retirar un acopio…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.stockpile, fake.name, fake.start), ("STK-001#Acopio 1", "Retirada de «Acopio 1»", "entity:PLT-001"))
        self.assertEqual(fake.transition_angle, "", "el ángulo no tiene valor por defecto (D-2): no se propone")
        self.assertEqual(self.panels.resting_lines(), [("Nada se apoya en el acopio", False)])
        given, context, _dialog, _said = self.fake_dialog(
            name="Mía", stockpile="STK-001#Acopio 2", start=self.survey_name,
            properties=SimpleNamespace(is_property_set=lambda name: name in ("stockpile", "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.stockpile, given.start), ("Mía", "STK-001#Acopio 2", self.survey_name), "lo dado no cambia")

        self.des_ops._refresh_resting(given, None)  # el Acopio 2 sobre el levantamiento: nada se le apoya aún
        self.assertEqual(self.panels.resting_lines(), [("Nada se apoya en el acopio", False)])
        given.start = "entity:PLT-001"
        self.des_ops._refresh_resting(given, None)  # sobre la superficie de la plataforma, que lo rellena
        lines = self.panels.resting_lines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0][0], rf"^{OVER[0]} \(Plataforma\): \d+ m³ apoyados$")
        self.assertTrue(lines[0][1], "lo apoyado, en ámbar")
        self.assertEqual(lines[1], ("El acopio no se retira sin su confirmación expresa: el botón que crea la retirada la confirma", False))
        supported = platform_ops._module("design.supported_store")
        (row,) = supported.resting_preview(self.project, self.v01.uid, "STK-001#Acopio 2", "entity:PLT-001")
        self.assertEqual((row.name, row.op_type, row.entity), (OVER[0], "des.platform", "PLT-001"))
        self.assertGreater(row.volume_m3, 100.0)
        shown = draw(cls, bpy.context, name="x", stockpile="STK-001#Acopio 2", start="entity:PLT-001", transition_angle="",
                     mesh_factor="", metric="EXACT", wall_reason="", as_platform=False, edge_angle="", reach="", confirm=False).texts()
        for heading in ("Nombre", "Acopio", "Superficie de partida", "Lo que se apoya en el acopio", lines[0][0], "Como plataforma",
                        "Transición en el borde del acopio", "Ángulo de transición (°)", "Factor de malla", "Métrica",
                        "Motivo de la pared"):
            self.assertIn(heading, shown)
        for gone in ("Borde de la plataforma", "Ángulo del borde (°)", "Alcance del borde (m)"):
            self.assertNotIn(gone, shown, "sin «como plataforma», el diálogo es el de la T20")
        as_platform = draw(cls, bpy.context, name="x", stockpile="STK-001#Acopio 2", start="entity:PLT-001", transition_angle="",
                           mesh_factor="", metric="EXACT", wall_reason="", as_platform=True, edge_angle="", reach="",
                           confirm=False).texts()
        for heading in ("Nombre", "Acopio", "Superficie de partida", "Lo que se apoya en el acopio", lines[0][0], "Como plataforma",
                        "Borde de la plataforma", "Ángulo del borde (°)", "Alcance del borde (m)", "Factor de malla", "Métrica"):
            self.assertIn(heading, as_platform)
        for gone in ("Transición en el borde del acopio", "Ángulo de transición (°)", "Motivo de la pared"):
            self.assertNotIn(gone, as_platform, "«como plataforma» no lleva transición ni pared: el borde es el de la plataforma")
        given.stockpile = "STK-009#Nada"  # un acopio que la detección no tiene: sale como aviso, no como error
        self.des_ops._refresh_resting(given, None)
        ((text, alert),) = self.panels.resting_lines()
        self.assertTrue(alert)
        self.assertIn("STK-009#Nada", text)
        given.stockpile = ""
        self.des_ops._refresh_resting(given, None)
        self.assertEqual(self.panels.resting_lines(), [], "sin acopio, nada que enseñar")
        self.assertEqual(self.state(), before, "el diálogo no escribe nada")

        with mock.patch.object(supported, "removable_stockpiles", return_value=()):  # sin ninguna detección
            empty, context, dialog, said = self.fake_dialog()
            self.assertEqual(cls.invoke(empty, context, None), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "No hay ninguna detección de acopios en el proyecto ni en la versión activa: detecte "
                                            "antes los acopios")])
        self.refresh()

    def test_c_calculate_writes_nothing_and_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-015-03, RF-015-29, RNF-016-05, RF-016-13, M1: «Calcular» desde un guion deja el cálculo abierto con su resumen (lo retirado, lo
        apoyado, la transición y lo no retirado, el ángulo y «sin pared», en los dos idiomas, con su título) y **solo el temporal**; nada en
        el proyecto. Esc **a mitad** (con su temporal ya escrito), cancelar la confirmación y lo que falta o se rechaza (el nombre, el
        ángulo sin valor, fuera de rango o que no es un número, el factor de malla fuera de rango) no dejan nada: ni operación, ni dato,
        ni parámetro, ni cifra, ni temporal; Esc dice que no queda nada a medias."""
        self.refresh()
        before = self.state()
        held = self.calculate()
        self.assertEqual((held.op_type, held.name, held.version), (REMOVAL_TYPE, FIRST, "V01"))
        self.assertEqual(held.entity.code, "RMV-001")
        after = self.state()
        self.assertEqual(after[:4], before[:4], "calcular no registra nada")
        (temporary,) = sorted(set(after[4]) - set(before[4]))
        self.assertIn(".tmp", temporary)
        self.assertEqual(self.view.summary_title, f"Retirada de un acopio «{FIRST}» en V01")
        outcome = held.outcome
        self.assertGreater(outcome.removed_m3, 0.0)
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertTrue(summary[0][0].startswith(f"Retirada «{FIRST}» (RMV-001) del acopio «Acopio 1»: "), summary[0])
        self.assertTrue(summary[0][0].endswith(" m³ retirados"), summary[0])
        self.assertTrue(summary[1][0].startswith("Apoyado en él: 0 m³ · transición: "), summary[1])
        self.assertEqual(summary[2], ("Transición a 30,0° con factor de malla 1,00", False))
        self.assertEqual(summary[3], ("Sin pared en el borde de lo retirado", False))
        self.assertFalse(held.needs_resting_confirmation or held.needs_wall_confirmation)
        self.assertFalse(any(alert for _text, alert in summary), "nada que avisar")
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, f"Removal of a stockpile «{FIRST}» in V01")
        self.assertTrue(self.view.summary[0].name.startswith(f"Removal «{FIRST}» (RMV-001) of the stockpile «Acopio 1»: "))
        self.assertEqual(self.view.summary[3].name, "No wall left at the edge of what is removed")
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before, "descartar borra el temporal")

        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.form(name="Esc", in_steps=True)),
                             {"RUNNING_MODAL"})
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
                ({"name": " "}, "Escriba el nombre de la retirada"),
                ({"transition_angle": ""}, "transition_deg"),
                ({"transition_angle": "abc"}, "«abc» no es un número"),
                ({"transition_angle": "0"}, "transition_deg"),
                ({"transition_angle": "95"}, "transition_deg"),
                ({"mesh_factor": "99"}, "mesh_factor")):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.form(**changes))
                self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)

    def test_c_as_a_platform_calculates_with_the_platform_and_the_removal_figures_and_asks_for_what_rests_on_it(self) -> None:
        """RF-016-16, RF-016-14, RF-015-03, RF-015-17, E3, M1 (T41): con «como plataforma» la orden **calcula una plataforma de la 015 con la huella
        del acopio** (``PlatformRequest.of_stockpile`` + ``platform_run``: una sola operación ``des.platform``, sin ninguna capa) y no escribe
        nada; su resumen enseña **las cifras de la plataforma y las de la retirada** (las mismas que da el dominio, T21), con el título «como
        plataforma»; retirando el Acopio 2 desde la superficie que lo rellena, **lo apoyado** sale en una sola lista, en ámbar, y el botón de
        crear dice «Confirmar lo que se le apoya y crear»; sin la confirmación expresa, Crear se rechaza, no escribe nada y deja el cálculo
        abierto."""
        steps, model = platform_ops._module("design.steps"), platform_ops._module("design.model")
        self.refresh()
        before = self.state()
        form = self.platform_form(name=OVER_PLATFORM, stockpile="STK-001#Acopio 2", start="entity:PLT-001")
        held = self.calculate(**form)
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), (PLATFORM_TYPE, OVER_PLATFORM, "V01", "PLT-002"))
        self.assertIsNotNone(held.entity.removed, "es la plataforma de un acopio")
        self.assertEqual(held.entity.origin.ref, "STK-001#Acopio 2")
        self.assertEqual(self.state()[:4], before[:4], "calcular no registra nada")
        self.assertEqual(sorted(set(self.state()[4]) - set(before[4])), [name for name in self.state()[4] if ".tmp" in name], "solo el temporal")
        self.assertTrue(held.needs_resting_confirmation)
        self.assertFalse(held.needs_wall_confirmation, "su pared es la de su borde: un aviso de la plataforma")
        (row,) = held.entity.resting
        self.assertEqual((row.name, row.op_type, row.entity), (OVER[0], "des.platform", "PLT-001"))
        self.assertEqual(self.view.summary_title, f"Retirada de un acopio «{OVER_PLATFORM}» como plataforma en V01")
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertTrue(summary[0][0].startswith(f"Plataforma «{OVER_PLATFORM}» (PLT-002): huella "), summary[0])
        self.assertTrue(summary[1][0].startswith("Rasante: cota de "), summary[1])
        self.assertTrue(summary[2][0].startswith("Huella: desmonte "), summary[2])
        removal_line = [text for text, _alert in summary if text.startswith("Retirada del acopio «Acopio 2»: ")]
        self.assertEqual(len(removal_line), 1, summary)
        self.assertIn(" m³ retirados · apoyado en él: ", removal_line[0])
        self.assertIn(" · no retirado: ", removal_line[0])
        resting = [(text, alert) for text, alert in summary if text.startswith("Sobre el acopio «Acopio 2» se apoyan ")]
        self.assertEqual(len(resting), 1, "lo apoyado, una sola nota (la de RF-016-14)")
        self.assertTrue(resting[0][1], "lo apoyado, en ámbar")
        self.assertIn(f"«{OVER[0]}»", resting[0][0], "con lo que lo puso")
        self.assertIn("sin su confirmación expresa", resting[0][0])
        self.assertFalse(any("Transición a" in text for text, _alert in summary), "no hay transición: la huella entera queda en su plano")
        figures = sorted((spec.key, spec.value) for spec in held.figures)
        keys = {key for key, _value in figures}
        for wanted in ("des.plat_area_m2", "des.plat_axis_m", "des.plat_cut_m3", "des.edge_cut_m3", "des.rmv_removed_m3",
                       "des.rmv_resting_m3", "des.rmv_transition_m3", "des.rmv_kept_m3", "des.rmv_transition_m2"):
            self.assertIn(wanted, keys)
        self.assertGreater(dict(figures)["des.rmv_resting_m3"], 0.0)
        self.assertEqual((dict(figures)["des.rmv_transition_m3"], dict(figures)["des.rmv_transition_m2"]), (0.0, 0.0))
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        asked = operator_self(self.cls, confirm_resting=False, confirm_wall=False)
        self.cls._confirmation(asked, context)
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Confirmar lo que se le apoya y crear")
        self.assertEqual(dialog.call_args.kwargs["title"], f"Retirada de un acopio «{OVER_PLATFORM}» como plataforma en V01")
        self.assertTrue(asked.confirm_resting and not asked.confirm_wall)
        with self.assertRaises(RuntimeError) as caught:  # sin la confirmación expresa
            self.create()
        self.assertIn("se apoyan en él", str(caught.exception))
        self.assertIn("confirmación expresa", str(caught.exception))
        self.assertIs(self.des_ops.calculation(), held)
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4])
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, f"Removal of a stockpile «{OVER_PLATFORM}» as a platform in V01")
        self.assertTrue(self.view.summary[0].name.startswith(f"Platform «{OVER_PLATFORM}» (PLT-002): footprint "))
        self.assertTrue(any(line.name.startswith("Removal of the stockpile «Acopio 2»: ") for line in self.view.summary))
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before, "descartar borra el temporal")

        direct = None  # lo que calcula el dominio con la misma petición (T21): las mismas cifras, a ≤ 10⁻⁹ relativo
        request = model.PlatformRequest.of_stockpile(OVER_PLATFORM, "STK-001#Acopio 2", "entity:PLT-001", edge_angle_deg=35.0,
                                                     reach_m=10.0, metric="exact")
        for step in steps.platform_run(self.project, request, version=self.v01.uid):
            direct = step.result or direct
        self.assertIsNotNone(direct)
        try:
            expected = sorted((spec.key, spec.value) for spec in direct.figures)
        finally:
            direct.discard()
        self.assertEqual([key for key, _value in figures], [key for key, _value in expected])
        for (key, found), (_key, wanted) in zip(figures, expected, strict=True):
            self.assertAlmostEqual(found, wanted, delta=1e-9 * max(abs(wanted), 1.0), msg=key)
        self.assertEqual(self.state(), before)

    def test_c_as_a_platform_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-016-16, RF-015-03, RF-015-29, RNF-016-05, M1 (T41): con «como plataforma», Esc **a mitad** (con su temporal ya escrito), cancelar la
        confirmación y lo que falta o se rechaza (el ángulo del borde y el alcance, que no tienen valor por defecto; un ángulo que no es un
        número o está fuera de rango; el nombre) no dejan nada: ni operación, ni dato, ni parámetro, ni cifra, ni temporal; el ángulo de
        transición, que aquí no vale, no se pide."""
        self.refresh()
        before = self.state()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.platform_form(name="Esc", in_steps=True)),
                             {"RUNNING_MODAL"})
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

        self.calculate(**self.platform_form(name="Cancelada"))
        self.assertTrue(any(".tmp" in name for name in self.names()))
        self.cls.cancel(operator_self(self.cls, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        for changes, text in (
                ({"edge_angle": ""}, "edge_angle_deg"),
                ({"reach": ""}, "reach_m"),
                ({"edge_angle": "abc"}, "«abc» no es un número"),
                ({"edge_angle": "0"}, "edge_angle_deg"),
                ({"edge_angle": "95"}, "edge_angle_deg"),
                ({"mesh_factor": "99"}, "mesh_factor"),
                ({"name": " "}, "Escriba el nombre de la retirada")):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.platform_form(transition_angle="", **changes))
                self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)

    def test_d_create_registers_the_removal_in_one_transaction_and_chains_what_follows(self) -> None:
        """RF-016-11, RF-016-13, RF-015-02, RF-015-01, RF-015-27, RF-016-24, M1: «Crear» la retirada del Acopio 1 (nada se le apoya) registra
        ``des.stockpile_removal`` hecha en V01 con su superficie, su huella y su informe, las cifras CALCULADO y los parámetros de la
        entidad como filas de la versión (de quien tiene abierto el proyecto; el ángulo con el origen del diálogo), y la entidad al día;
        **encadena lo que sigue** (T41: ``entity_store.after_entity_change``): la capa de entidades (``des_enl_v01``) tiene ya su fila sin
        otra orden; **no declara nada** (D-1: una retirada no protege) y no toca la detección ni el levantamiento."""
        self.refresh()
        declared = self.declared()
        self.assertEqual(list(self.layer_rows()), ["PLT-001"], "la capa de entidades solo tiene la plataforma que la llenó")
        held = self.calculate()
        removed = held.outcome.removed_m3
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.operations()
        self.assertEqual(status, "done")
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual(figures["des.rmv_removed_m3"], removed)
        self.assertEqual(figures["des.rmv_resting_m3"], 0.0)
        for family in ("psf", "epr", "prp"):
            self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND name = ?",
                                       self.dprov.dataset_name(family, FIRST)), [(1,)], family)
        found = self.parameter_of("RMV-001", "transition_deg")
        self.assertEqual(found[0], 30.0)
        self.assertEqual(found[1], f"diálogo de «Retirada de un acopio», entidad «{FIRST}»")
        self.assertEqual((found[2], found[3]), ("ADOPTADO", self.project.session.user_host))
        self.assertEqual(self.parameter_of("RMV-001", "stockpile")[0], "STK-001#Acopio 1")
        self.assertEqual(self.parameter_of("RMV-001", "start")[0], "entity:PLT-001")
        self.assertEqual(self.states(), {"PLT-001": "current", "RMV-001": "current"})
        self.assertEqual(self.declared(), declared, "una retirada no protege: lo que sigue no declara nada nuevo (D-1)")
        rows = self.layer_rows()
        self.assertEqual(sorted(rows), ["PLT-001", "RMV-001"], "la capa de entidades tiene ya la fila de la retirada, sin otra orden")
        row = rows["RMV-001"]
        self.assertEqual((row.name, str(row.kind), str(row.state)), (FIRST, "removal", "current"))
        self.assertTrue(math.isclose(row.volume_m3, figures["des.rmv_removed_m3"], rel_tol=1e-9), "con lo retirado entre sus cifras")
        self.assertNotIn("removal_confirmed", self.settings_of(FIRST), "nada que confirmar")
        self.assertEqual(self.layer_state(), self.layer_before, "la capa de plataformas no se toca")

    def test_e_what_rests_on_the_stockpile_is_not_removed_without_the_express_confirmation(self) -> None:
        """RF-016-14 (error 59), RF-015-17, P-9, M1: retirar el Acopio 2 desde la retirada anterior da **una sola lista** de lo que se le
        apoya (la plataforma «Sobre acopio», con su tipo y sus m³) en el resumen, en ámbar, y su botón de crear dice «Confirmar lo que se le
        apoya y crear»: pulsarlo es la confirmación expresa; sin ella, desde un guion, Crear se rechaza, no escribe nada y el cálculo
        sigue abierto; con ella, se crea y deja en los ajustes de la operación cuánto se apoyaba, quién lo confirmó y cuándo, y la
        retirada no descarta nada. (Con una detección **del proyecto**, D-15, el registro de la versión no ata la plataforma al acopio: lo
        de «apoyo retirado» por una retirada viva —P-9— lo cubre el hito de la T20 (a) con la detección de la versión.)"""
        self.refresh()
        start = "entity:RMV-001"
        self.assertIn(start, [item[0] for item in self.panels.platform_start_items(None, None)])
        self.assertEqual(self.panels.platform_default_start(), start, "la última de la cadena")
        before = self.state()
        held = self.calculate(name=SECOND, stockpile="STK-001#Acopio 2", start=start)
        self.assertTrue(held.needs_resting_confirmation)
        (row,) = held.entity.resting
        self.assertEqual((row.name, row.op_type), (OVER[0], "des.platform"))
        self.assertEqual(self.state()[:4], before[:4])
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertTrue(summary[1][0].startswith("Apoyado en él: "), summary[1])
        self.assertFalse(summary[1][0].startswith("Apoyado en él: 0 m³"), summary[1])
        self.assertEqual(summary[4], (row.text("es"), True))
        self.assertTrue(any("sin su confirmación expresa" in text and alert for text, alert in summary[5:]), summary)
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        asked = operator_self(self.cls, confirm_resting=False, confirm_wall=False)
        self.cls._confirmation(asked, context)
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Confirmar lo que se le apoya y crear")
        self.assertEqual(dialog.call_args.kwargs["title"], f"Retirada de un acopio «{SECOND}» en V01")
        self.assertTrue(asked.confirm_resting)
        self.assertFalse(asked.confirm_wall)

        with self.assertRaises(RuntimeError) as caught:  # sin la confirmación expresa
            self.create()
        self.assertIn("se apoyan en él", str(caught.exception))
        self.assertIn("confirmación expresa", str(caught.exception))
        self.assertIs(self.des_ops.calculation(), held)
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4])

        self.assertEqual(self.create(confirm_resting=True), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        confirmed = self.settings_of(SECOND)["removal_confirmed"]
        self.assertEqual(set(confirmed), {"resting"})
        self.assertAlmostEqual(confirmed["resting"]["volume_m3"], row.volume_m3, delta=1e-9 * row.volume_m3)
        self.assertEqual(confirmed["resting"]["decided_by"], self.project.session.user_host)
        self.assertRegex(confirmed["resting"]["decided_on"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        self.assertEqual({code: state for code, state in self.states().items() if code != "PLT-001"},
                         {"RMV-001": "current", "RMV-002": "current"})
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        self.assertEqual(sorted(self.layer_rows()), ["PLT-001", "RMV-001", "RMV-002"], "la capa de entidades, al día sin otra orden (T41)")

    def test_f_a_wall_is_not_created_without_the_express_confirmation_and_one_over_the_limits_needs_its_reason(self) -> None:
        """RF-016-15 (error 47), CA-9, M1: la pared que dejara la retirada (aquí forzada: la transición de A6 nunca la deja, T19) sale en
        ámbar en el resumen y el botón de crear dice «Confirmar la pared y crear»; sin la confirmación expresa, Crear se rechaza; una
        de más de 45° y 3 m pide además su motivo, que se escribe en el diálogo y va en la petición: sin él se rechaza y lo dice el
        resumen; con los dos, se crea y deja en los ajustes la altura, la inclinación, el motivo, quién lo confirmó y cuándo, y el motivo
        como parámetro de la entidad. Cada negativa deja el cálculo abierto y no escribe nada."""
        removal = platform_ops._module("design.removal")
        progress = platform_ops._module("core.project.model").Progress
        self.refresh()
        start = "entity:RMV-002"
        before = self.state()
        with forged_wall(removal, progress, 2.5, 60.0):  # una pared de 2,5 m a 60°: pide confirmar, no un motivo
            held = self.calculate(name=THIRD, start=start)
        self.assertTrue(held.needs_wall_confirmation and not held.needs_wall_reason)
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertEqual(summary[3], ("Pared en el borde: 2,5 m a 60,0°", True))
        self.assertTrue(any("sin su confirmación expresa" in text and alert for text, alert in summary[4:]), summary)
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        asked = operator_self(self.cls, confirm_resting=False, confirm_wall=False)
        self.cls._confirmation(asked, context)
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Confirmar la pared y crear")
        self.assertTrue(asked.confirm_wall and not asked.confirm_resting)
        with self.assertRaises(RuntimeError) as caught:
            self.create()
        self.assertRegex(str(caught.exception), r"deja una pared de 2[.,]5 m a 60")
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4])
        self.des_ops.discard_calculation()

        with forged_wall(removal, progress, 4.0, 71.0):  # una de 4 m a 71°: pasa de 45° y 3 m (CA-9)
            held = self.calculate(name=THIRD, start=start)
            self.assertTrue(held.needs_wall_confirmation and held.needs_wall_reason)
            alerts = [line.name for line in self.view.summary if line.alert]
            self.assertTrue(any(text.startswith("La pared pasa de 45° y 3 m: pide un motivo") for text in alerts), alerts)
            with self.assertRaises(RuntimeError) as caught:  # confirmada, pero sin el motivo
                self.create(confirm_wall=True)
            self.assertIn("pide un motivo que queda registrado", str(caught.exception))
            self.assertTrue(held.open)
            self.assertEqual(self.state()[:4], before[:4])
            self.des_ops.discard_calculation()
            held = self.calculate(name=THIRD, start=start, wall_reason="El camino de la balsa queda a salvo")
            self.assertEqual([line.name for line in self.view.summary if line.name.startswith("Motivo de la pared")],
                             ["Motivo de la pared: El camino de la balsa queda a salvo"])
            self.assertFalse(any(line.name.startswith("La pared pasa de") for line in self.view.summary))
            self.assertEqual(self.create(confirm_wall=True), {"FINISHED"})
        confirmed = self.settings_of(THIRD)["removal_confirmed"]
        self.assertEqual(set(confirmed), {"wall"})
        self.assertEqual((confirmed["wall"]["height_m"], confirmed["wall"]["angle_deg"], confirmed["wall"]["reason"]),
                         (4.0, 71.0, "El camino de la balsa queda a salvo"))
        self.assertEqual(confirmed["wall"]["decided_by"], self.project.session.user_host)
        self.assertRegex(confirmed["wall"]["decided_on"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        self.assertEqual(self.parameter_of("RMV-003", "wall_reason")[0], "El camino de la balsa queda a salvo")
        self.assertEqual(self.states()["RMV-003"], "current")

    def test_g_the_command_is_disabled_with_its_reason(self) -> None:
        """RF-015-28 (M1): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable (V02 SUPERADO:
        «V02 está en estado SUPERADO: …», que dice también su descripción), la orden sale desactivada con su motivo y no se puede
        lanzar; con V01 en escritura, activa."""
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
            self.assertFalse(bpy.ops.geoblender.des_remove_stockpile.poll())
            before = self.state()
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.form(name="No debe"))
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
        self.assertFalse(bpy.ops.geoblender.des_remove_stockpile.poll())
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.assertTrue(poll())

    def test_h_a_start_that_is_taken_and_a_name_that_is_repeated_are_refused(self) -> None:
        """RF-015-04, RF-015-08 (M1): la superficie que ya es la partida de otra retirada y un nombre repetido se rechazan, nombrando a la
        otra, sin escribir nada y sin dejar un cálculo abierto."""
        self.refresh()
        before = self.state()
        with self.assertRaises(RuntimeError) as taken:  # la superficie de la plataforma ya es la partida de «Retirada del acopio 1»
            bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.form(name="Otra"))
        self.assertIn(FIRST, str(taken.exception))
        with self.assertRaises(RuntimeError) as repeated:
            bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.form(name=FIRST, start="entity:RMV-003"))
        self.assertIn(FIRST, str(repeated.exception))
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

    def platform_param(self, code: str, param: str) -> tuple[Any, ...]:
        """La fila de la versión del parámetro ``param`` de la plataforma ``code`` (``des.platform.plt_002.*``): valor, origen, tipo y decisor."""
        ((value, source, kind, decider),) = self.rows(
            "SELECT value, source, kind, decided_by FROM gb_parameter WHERE key = ? AND scope = 'version' AND scope_uid = ?",
            f"des.platform.{code.lower().replace('-', '_')}.{param}", self.v01.uid)
        return json.loads(value), source, kind, decider

    def test_i_as_a_platform_creates_the_platform_of_the_stockpile_and_chains_what_follows(self) -> None:
        """RF-016-16, RF-015-01, RF-015-02, RF-015-27, A9, E3, M1 (T41): «Crear» con «como plataforma» registra **una sola operación**
        ``des.platform`` (la plataforma de la 015 con la huella del acopio: sin capa de entrada, con las tres entradas ``removed_stockpile``
        de la detección) con las cifras que se calcularon, los parámetros de la entidad (el acopio que retira, el borde elegido en el diálogo,
        de quien tiene abierto el proyecto) y la entidad al día; **encadena lo que sigue** (T41): la capa de entidades tiene ya su fila sin
        otra orden y la declaración no cambia (no protege). Nada se le apoya (el acopio ya se retiró): no pide confirmación."""
        self.refresh()
        declared = self.declared()
        start = self.panels.platform_default_start()
        self.assertEqual(start, "entity:RMV-003", "la última de la cadena")
        held = self.calculate(**self.platform_form(start=start))
        self.assertEqual((held.op_type, held.entity.code, held.name), (PLATFORM_TYPE, "PLT-002", AS_PLATFORM))
        self.assertFalse(held.needs_resting_confirmation, "ya se retiró: nada se le apoya")
        calculated = sorted((spec.key, spec.value) for spec in held.figures)
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        done = [(uid, status) for uid, status in self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ? ORDER BY fid", PLATFORM_TYPE)]
        self.assertEqual([status for _uid, status in done], ["done", "done"], "la plataforma de la 015 y esta")
        uid = done[-1][0]
        self.assertEqual(sorted(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)), calculated,
                         "lo registrado es lo calculado")
        roles = [role for (role,) in self.rows("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'", uid)]
        self.assertEqual(roles.count("removed_stockpile"), 3, roles)
        self.assertFalse([role for role in roles if role in ("entity_layer", "entity_axis_layer")], "no lee ninguna capa de entidades")
        for family in ("psf", "epr", "prp"):
            self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND name = ?",
                                       self.dprov.dataset_name(family, AS_PLATFORM)), [(1,)], family)
        for param, value in (("stockpile", "STK-001#Acopio 1"), ("start", start), ("edge_angle_deg", 35.0), ("reach_m", 10.0)):
            self.assertEqual(self.platform_param("PLT-002", param)[0], value, param)
        found = self.platform_param("PLT-002", "edge_angle_deg")
        self.assertEqual((found[2], found[3]), ("ADOPTADO", self.project.session.user_host))
        self.assertIn(self.states()["PLT-002"], ("current", "stale"), "creada y calculada")
        self.assertEqual(self.declared(), declared, "no protege: lo que sigue no declara nada nuevo")
        rows = self.layer_rows()
        self.assertEqual(sorted(rows), ["PLT-001", "PLT-002", "RMV-001", "RMV-002", "RMV-003"],
                         "la capa de entidades tiene ya la fila de la plataforma, sin otra orden")
        self.assertEqual((rows["PLT-002"].name, str(rows["PLT-002"].kind)), (AS_PLATFORM, "platform"))
        self.assertTrue(math.isclose(rows["PLT-002"].area_m2, dict(calculated)["des.plat_area_m2"], rel_tol=1e-9))

    def test_j_esc_in_what_follows_creating_the_removal_says_it_is_created_and_the_next_order_updates_the_layer(self) -> None:
        """RF-015-10, RF-015-29, RNF-016-05, RF-015-27, M1 (T41): Esc **en lo que sigue a «Crear»** (la declaración, las máscaras y la capa de
        entidades, por pasos con su avance) deja la retirada **creada** —la orden lo dice— y la capa de entidades sin su fila, hasta que lo que
        sigue se hace de nuevo (aquí, ``after_entity_change``, que encadena también la orden siguiente): lo creado no se pierde."""
        self.refresh()
        start = self.panels.platform_default_start()
        self.assertEqual(start, "entity:PLT-002", "la última de la cadena")
        self.calculate(**self.platform_form(name="Otra como plataforma", start=start))
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
            modal = self.running()
            modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
            state, _count = step_modals.drive(modal, bpy.context, stop_after=0)
            self.assertEqual(state, {"RUNNING_MODAL"}, "lo que sigue no debía haber acabado")
            self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertIn(CHAIN_CANCELLED_TEXT, list(modal.report_log))
        self.assertIn(self.states()["PLT-003"], ("current", "stale"), "la plataforma está creada")
        self.assertNotIn("PLT-003", self.layer_rows(), "y la capa aún no tiene su fila")
        self.assertIsNone(self.des_ops.calculation())
        last = None
        for last in platform_ops._module("design.entity_store").after_entity_change(self.project, self.v01.uid):
            pass
        self.assertIsNone(last.result.failure, None if last.result.failure is None else last.result.failure.reason)
        self.assertIsNone(last.result.layer_failure, None if last.result.layer_failure is None else last.result.layer_failure.reason)
        self.assertIn("PLT-003", self.layer_rows(), "ahora sí")

    def test_z_a_stale_detection_is_offered_but_refused_and_disabling_geoblender_removes_the_command(self) -> None:
        """RF-016-12 (M1), principio 8, D-14 de la 013: con la detección **obsoleta** (se cambió un umbral suyo), el diálogo sigue ofreciendo
        sus acopios —marcados— y su lista de lo apoyado dice por qué no se puede, y «Calcular» se rechaza nombrando el acopio y lo que
        cambió, sin registrar nada; con un cálculo abierto, desactivar Geoblender lo descarta (no queda ningún temporal) y quita la orden."""
        self.refresh()
        tail = self.panels.platform_default_start()  # la última de la cadena (las de «como plataforma» la alargan)
        held = self.calculate(name="Al apagar", start=tail)
        self.assertTrue(any(".tmp" in name for name in self.names()))
        self.des_ops.discard_calculation()
        self.assertFalse(any(".tmp" in name for name in self.names()))
        core_params = platform_ops._module("core.params")
        key = platform_ops._module("design.params").entity_key("STK-001", "margin_m")
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(conn, key, value=4.0, reason="Prueba de la T20")
        self.assertEqual(self.entities.project_registry(self.project).get("STK-001").record.state, self.entities.EntityState.STALE)
        before = self.state()
        self.refresh()
        items = [(identifier, label) for identifier, label, _about in self.panels.removal_stockpile_items(None, None)]
        self.assertEqual(items, [("STK-001#Acopio 1", "Acopio 1 (STK-001) · detección obsoleta"),
                                 ("STK-001#Acopio 2", "Acopio 2 (STK-001) · detección obsoleta")])
        fake, context, _dialog, _said = self.fake_dialog()
        self.cls.invoke(fake, context, None)
        ((text, alert),) = self.panels.resting_lines()
        self.assertTrue(alert)
        self.assertIn("está obsoleta", text)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", **self.form(name="De la obsoleta", start=tail))
        self.assertIn("«Acopios» está obsoleta", str(caught.exception))
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)
        self.assertIsNotNone(held)

        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, REMOVE_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test"):
        setattr(RemoveStockpileTest, _name, None)


if __name__ == "__main__":
    unittest.main()
