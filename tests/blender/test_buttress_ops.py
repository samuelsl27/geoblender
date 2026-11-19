# SPDX-License-Identifier: GPL-3.0-or-later
"""«Contrafuerte…» en Blender (spec 016, T27 (b); HU-016-3; RF-016-17, RF-016-18, RF-015-02, RF-015-03, RF-015-10, RF-015-12, RF-015-28,
RF-015-29; RNF-016-05; plan 016 §5.3.3 y §5.5; comprobación manual M3).

:class:`GEOBLENDER_OT_des_add_buttress` (``geoblender.des_add_buttress``, la clave del catálogo, que sigue en la entrada R-36 hasta que la T35
la entregue) calcula con ``design.steps.buttress_run`` la operación ``des.buttress`` de la versión activa: el escalonado en relleno de la
013 desde una semilla en una zona de coronación, con un perfil de banco, **sin cortar ninguna celda**. Sigue el patrón de la retirada (T20) y
del cuerpo (T25): su diálogo pide el nombre, la capa y la zona de coronación, la partida y el apoyo, el perfil, la cota de coronación (sin valor
por defecto: D-21), el alcance, la métrica y si protege (por defecto sí: D-1) con su resguardo (obligatorio: D-19) y su motivo; Calcular, Crear,
Cancelar y Esc son los de las demás órdenes (``_CalculateAndCreate``): nada se registra hasta Crear. **Tras crear, encadena** lo que sigue
(``entity_store.after_entity_change``, como «Plataforma…»): declara «sin corte» sobre la **zona de coronación** y no sobre toda la huella (P-8,
H-6), recompila las máscaras y pone al día la capa de entidades.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, la ladera ``100 + 0,25·y + 0,0625·x``, el límite legal de
(4, 4) a (56, 56) con 2 m hacia dentro) con una capa de zonas de coronación (la «Cima» de 5 × 5 celdas en el centro, otra por encima de la cota de
coronación y una segunda) y el perfil de banco ``EXPL_10_60_6`` (10 m de banco, cara de 60°, berma de 6 m y ancla de 125 m) escrito en el
proyecto. Las pruebas, en el orden de sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import time
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_body_ops as body_ops
from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

ADD = "geoblender.des_add_buttress"
ADD_CLASS = "GEOBLENDER_OT_des_add_buttress"
BUTTRESS_TYPE = "des.buttress"
DESCRIPTION = "Buttress at the toe of a slope"
CROWN_LAYER = "gis_fea_coronaciones"
CROWNS = (("Cima", (22.0, 22.0, 32.0, 32.0)), ("Alta", (50.0, 50.0, 54.0, 54.0)), ("Segunda", (36.0, 36.0, 44.0, 44.0)))
"""Las zonas de coronación de la capa (nombre y caja local): la «Cima», de 5 × 5 celdas, sobre la ladera de 106,9 a 110,0 m; la «Alta», de 2 × 2
celdas, **por encima** de la coronación de 115 m (ninguna celda siembra) y la «Segunda»."""
FIRST, SECOND = "Contrafuerte de la cima", "Contrafuerte de la segunda"
PROFILE = "EXPL_10_60_6"
CROWN_M = 115.0
"""La cota de coronación: el ancla (125 m) menos un banco (10 m)."""
GUARD_M = 5.0
SOURCE = "Plan de la prueba del contrafuerte"
PROPERTIES = {
    "name": ("Name", "Name of the buttress, unique in the active version"),
    "layer": ("Layer of the crown zones", "Layer of polygons of the project the crown zone of the buttress is taken from"),
    "feature": ("Crown zone of the layer", "Name or number (fid) of the polygon of the layer that is the crown zone of the buttress"),
    "start": ("Start surface", "Surface the buttress starts from: the ground, a design surface or the surface of another entity (by "
                               "default, the last of the chain)"),
    "support": ("Support surface", "Surface the buttress rests on, if it is not the start surface: a design surface, the exploitation "
                                   "surface of a quarry or the surface of another entity (none: it rests on the start surface); it does "
                                   "not change the calculation"),
    "profile": ("Bench profile", "Bench profile of the buttress: its height, its face, its berm and its anchor give its slopes and the "
                                 "levels the crown can be at"),
    "crown": ("Crown elevation (m)", "Elevation of the crown of the buttress in metres: it has to be one of the anchor levels of its "
                                     "profile (the anchor plus a whole number of bench heights); it has no default value: you choose it"),
    "reach": ("Reach (m)", "Farthest distance from the crown zone the slopes can reach, in metres (empty: down to the lowest elevation "
                           "of the start surface)"),
    "metric": ("Metric", "How the distance to the crown zone is measured: the 5×5 chamfer (fast, with the scale of the grid) or the exact "
                         "Euclidean distance"),
    "protect": ("Protect", "Declare the crown zone a zone without cut: the other designs do not cut in it (the buttress protects by "
                           "default)"),
    "guard": ("Guard (m)", "Distance around the crown zone that is also protected, in metres; it is required to protect and has no "
                           "default value: you choose it"),
    "reason": ("Reason", "Why the crown zone is protected, recorded with the declared constraint (empty: a reason is generated that you "
                         "can edit later)"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone quien lanza la orden, no los llevan)."""
HIDDEN = ("confirm", "in_steps", "preview")
CANCELLED_TEXT = ("Cancelado: el contrafuerte está creado; las restricciones declaradas y las máscaras se ponen al día antes de la siguiente "
                  "operación que las use, y la capa de entidades con la siguiente orden de entidades o «Recalcular lo obsoleto»")


def zone_cells(box: tuple[float, float, float, float]) -> np.ndarray:
    """A mano: las celdas con el centro dentro de la caja local ``box``, como máscara de la ventana (un bucle de numpy, no el código)."""
    left, bottom, right, top = box
    x, y = platform_ops.centers()
    return (x > left) & (x < right) & (y > bottom) & (y < top)


class CreateButtressTest(body_ops.CreateBodyTest):
    """Lo de ``CreateBodyTest`` (el proyecto de la cantera de plataformas, sus ayudantes y sus capas; sus pruebas no se repiten) con la capa de
    las zonas de coronación y el perfil de banco ``EXPL_10_60_6`` en el proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_features(CROWN_LAYER, "polygon", tuple(((platform_ops.ring(box),),) for _name, box in CROWNS),
                           tuple(name for name, _box in CROWNS), {})
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=PROFILE, kind="ADOPTADO", source=SOURCE, decided_by=platform_ops.PERSON, reason=platform_ops.REASON, scope="PROJECT",
            height="10", face="60", berm="6", anchor="125") == {"FINISHED"}
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (también las del contrafuerte), leídas de nuevo (un guion no abre el diálogo que las lee)."""
        super().refresh()
        if cls.project.record is not None:
            cls.panels.refresh_buttress_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(ADD)

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo: el contrafuerte de la «Cima» sobre la ladera, con el perfil, la coronación a 115 m y 5 m de resguardo."""
        return {"name": FIRST, "layer": CROWN_LAYER, "feature": CROWNS[0][0], "start": self.ground, "profile": PROFILE,
                "crown": "115", "guard": "5", "in_steps": False, **values}

    def fake_dialog(self, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:  # type: ignore[override]
        """El operador de mentira, el contexto con que se abre el diálogo (sin ventana), el diálogo y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {
            "name": "", "layer": "", "feature": "", "start": "", "support": "none", "profile": "", "crown": "", "reach": "",
            "metric": "EXACT", "protect": True, "guard": "", "reason": "", "confirm": False, "in_steps": False,
            "provenance_dialog": False, "report": lambda kind, text: said.append((kind, text)),
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        return operator_self(self.cls, **fields), context, dialog, said

    def calculate(self, **values: Any) -> Any:  # type: ignore[override]
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form(**values)), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create(self, **values: Any) -> set[str]:  # type: ignore[override]
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", confirm=True, in_steps=False, **values)

    def operations(self) -> list[tuple[str, str]]:
        return self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ? ORDER BY fid", BUTTRESS_TYPE)

    def parameter_of(self, code: str, param: str) -> tuple[Any, ...]:  # type: ignore[override]
        """La fila de la versión del parámetro ``param`` de la entidad ``code`` (``des.buttress.btr_001.*``): valor, origen, tipo y decisor."""
        ((value, source, kind, decider),) = self.rows(
            "SELECT value, source, kind, decided_by FROM gb_parameter WHERE key = ? AND scope = 'version' AND scope_uid = ?",
            f"des.buttress.{code.lower().replace('-', '_')}.{param}", self.v01.uid)
        return json.loads(value), source, kind, decider

    def declared(self) -> tuple[Any, ...]:
        """Las restricciones que declaran las entidades de V01."""
        declared = platform_ops._module("core.constraints.declared")
        with self.project.read() as conn:
            return tuple(declared.read_in_version(conn, self.v01.uid))

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_buttress_command_is_a_real_command_with_named_properties(self) -> None:
        """RF-016-17, RF-015-28 (plan §5.3.3): «Contrafuerte…» es una orden real de ``des.buttress`` con la clave del catálogo
        (``des_add_buttress``), con la puerta de la procedencia, los pasos con Esc (≤ 0,05 s por paso) y el ``poll`` común de Diseño; sigue en
        la entrada R-36, sin entregar, que la entrega la T35; sus propiedades tienen nombre y descripción en español; las que pone quien la
        lanza, no."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertEqual(cls.__name__, ADD_CLASS)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertTrue(issubclass(cls, self.des_ops._CalculateAndCreate))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options, cls.COMMAND), (ADD, BUTTRESS_TYPE, {"REGISTER"}, ADD))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.BUTTRESS_COMMAND, ADD)
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[BUTTRESS_TYPE].commands, (ADD,))
        catalog = self.commands.catalog()
        command = catalog.commands[ADD]
        self.assertEqual((command.entry, command.module, command.label, command.label_es), ("016", "des", "Buttress…", "Contrafuerte…"))
        self.assertEqual(command.description, DESCRIPTION)
        self.assertEqual(cls.__doc__.strip(), DESCRIPTION)
        self.assertTrue(catalog.entries["016"].delivered, "la entregó la T35")
        self.assertTrue(self.commands.is_available(ADD))
        self.assertEqual(cls.bl_label, "Contrafuerte…", "registrada ya en español")
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
        self.assertTrue(bpy.ops.geoblender.des_add_buttress.poll())

    def test_b_the_buttress_dialog_offers_the_layers_proposes_and_draws_what_it_asks(self) -> None:
        """RF-016-17, RF-016-18, M3: el diálogo ofrece las capas de **polígonos** para la zona de coronación y, de apoyo, «sin apoyo» y las
        superficies de partida; propone un nombre que no repite el de ninguna entidad, la primera capa y de partida el terreno; **no propone**
        el perfil, la cota de coronación ni el resguardo (D-21, D-19) y protege por defecto (D-1); dibuja lo que pide, con el resguardo y el motivo
        solo si protege; sin ninguna capa de polígonos, lo dice; y no escribe nada."""
        cls = self.cls
        self.refresh()
        zones = [(identifier, label) for identifier, label, _about in self.panels.buttress_zone_items(None, None)]
        self.assertEqual({identifier for identifier, _label in zones}, {body_ops.FOOTPRINTS, CROWN_LAYER}, "solo capas de polígonos")
        supports = [identifier for identifier, _label, _about in self.panels.buttress_support_items(None, None)]
        self.assertEqual(supports[0], "none")
        self.assertIn(self.ground, supports)
        self.assertEqual([item[1] for item in self.panels.buttress_support_items(None, None)][:1], ["Sin superficie de apoyo"])
        self.assertTrue(self.panels.has_buttress_zones())
        before = self.state()
        fake, context, dialog, said = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(said, [])
        self.assertEqual(dialog.call_args.kwargs["title"], "Contrafuerte…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.name, fake.layer, fake.start), ("Contrafuerte", zones[0][0], self.ground))
        self.assertEqual((fake.profile, fake.crown, fake.guard, fake.reason), ("", "", "", ""), "sin perfil, cota ni resguardo por defecto")
        self.assertTrue(cls.__annotations__["protect"].keywords["default"], "protege por defecto")
        given, context, _dialog, _said = self.fake_dialog(
            name="Mío", layer=CROWN_LAYER, properties=SimpleNamespace(is_property_set=lambda name: name in ("name", "layer")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.layer), ("Mío", CROWN_LAYER), "lo dado no cambia")
        shown = draw(cls, bpy.context, name="x", layer=CROWN_LAYER, feature="Cima", start=self.ground, support="none", profile="", crown="",
                     reach="", metric="EXACT", protect=True, guard="", reason="", confirm=False).texts()
        for heading in ("Nombre", "Zona de coronación", "Capa", "Zona de coronación de la capa", "Superficie de partida",
                        "Superficie de apoyo", "Taludes del contrafuerte", "Cota de coronación (m)", "Alcance (m)", "Métrica", "Proteger",
                        "Resguardo (m)", "Motivo"):
            self.assertIn(heading, shown)
        loose = draw(cls, bpy.context, name="x", layer=CROWN_LAYER, feature="Cima", start=self.ground, support="none", profile="", crown="",
                     reach="", metric="EXACT", protect=False, guard="", reason="", confirm=False).texts()
        self.assertNotIn("Resguardo (m)", loose, "sin proteger no hay resguardo")
        self.assertNotIn("Motivo", loose)
        with mock.patch.object(self.panels, "has_buttress_zones", return_value=False):
            empty, context, dialog, said = self.fake_dialog()
            self.assertEqual(cls.invoke(empty, context, None), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "No hay ninguna capa de polígonos en el proyecto: importe antes las zonas de coronación del "
                                            "contrafuerte")])
        self.assertEqual(self.state(), before, "el diálogo no escribe nada")
        self.refresh()

    def test_c_calculating_a_buttress_writes_nothing_and_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-015-03, RF-015-29, RNF-016-05, RF-016-17, RF-016-18, M3: «Calcular» desde un guion deja el cálculo abierto con su resumen (el
        volumen, el área y la mayor altura con su lugar, la coronación con su perfil y su zona, lo que declarará, en los dos idiomas y con su
        título) y **solo el temporal**; nada en el proyecto. Esc **a mitad** (con su temporal ya escrito), cancelar la confirmación y lo que falta
        o se rechaza (el nombre, la zona, el perfil, la cota sin valor, que no es un número o **fuera del ancla de su perfil con la cota del ancla
        más próxima**, el resguardo sin valor o negativo, una zona que no existe o **por encima de la coronación**) no dejan nada: ni operación,
        ni dato, ni parámetro, ni cifra, ni temporal."""
        self.refresh()
        before = self.state()
        held = self.calculate()
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), (BUTTRESS_TYPE, FIRST, "V01", "BTR-001"))
        after = self.state()
        self.assertEqual(after[:4], before[:4], "calcular no registra nada")
        (temporary,) = sorted(set(after[4]) - set(before[4]))
        self.assertIn(".tmp", temporary, "solo el temporal de la superficie")
        self.assertEqual(self.view.summary_title, f"Contrafuerte «{FIRST}» en V01")
        outcome = held.outcome
        self.assertGreater(outcome.volume_m3, 0.0)
        self.assertEqual(int(outcome.zone.sum()), 25, "la zona de coronación son 5 × 5 celdas")
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertTrue(summary[0][0].startswith(f"Contrafuerte «{FIRST}» (BTR-001): "), summary[0])
        self.assertIn(" m³ sobre ", summary[0][0])
        self.assertIn(" · mayor altura ", summary[0][0])
        self.assertEqual(summary[1], (f"Coronación a 115,00 m · perfil «{PROFILE}» · zona de coronación de «{CROWN_LAYER}»: 25 celdas", False))
        self.assertEqual(summary[2], ("Declarará «sin corte» sobre su zona de coronación, con un resguardo de 5,0 m", False))
        self.assertFalse(any(alert for _text, alert in summary), "nada que avisar")
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, f"Buttress «{FIRST}» in V01")
        self.assertTrue(self.view.summary[0].name.startswith(f"Buttress «{FIRST}» (BTR-001): "))
        self.assertEqual(self.view.summary[2].name, "It will declare «no cut» on its crown zone, with a guard of 5.0 m")
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before, "descartar borra los temporales")

        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form(name="Esc", in_steps=True)), {"RUNNING_MODAL"})
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
                ({"name": " "}, "Escriba el nombre del contrafuerte"),
                ({"feature": " "}, "Escriba el nombre o el número de la zona de coronación en su capa"),
                ({"profile": ""}, "Elija el perfil de banco del contrafuerte"),
                ({"profile": "No existe"}, "«No existe»"),
                ({"crown": ""}, "crown_m"),
                ({"crown": "abc"}, "«abc» no es un número"),
                ({"crown": "118"}, "115"),
                ({"guard": ""}, "guard_m"),
                ({"guard": "-1"}, "guard_m"),
                ({"feature": "No hay"}, "No hay"),
                ({"feature": CROWNS[1][0]}, "por debajo de su apoyo en toda la zona de coronación")):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form(**changes))
                self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)
        with self.assertRaises(RuntimeError) as off:  # la cota fuera del ancla nombra el perfil y la cota del ancla más próxima
            bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form(crown="118"))
        self.assertIn(PROFILE.lower(), str(off.exception))

    def test_d_create_registers_the_buttress_in_one_transaction_and_declares_no_cut_on_its_crown_zone(self) -> None:
        """RF-016-17, RF-016-18, RF-015-01, RF-015-02, RF-015-10, RF-012-06, D-1, D-19, P-8, H-6, M3: «Crear» registra ``des.buttress`` hecha en
        V01 con su superficie entera (ninguna celda baja y la zona de coronación, a 115 m), su huella —entera— con la zona de coronación y su
        informe, las cifras CALCULADO y los parámetros de la entidad como filas de la versión (de quien tiene abierto el proyecto; la cota y el
        resguardo con el origen del diálogo; **protege por su valor por defecto**); y **encadena lo que sigue**: la restricción «sin corte»
        declarada **sobre la zona de coronación** (su polígono es el de la capa, no el de la huella) con su resguardo, las máscaras recompiladas,
        al día y sin corte en la zona; la capa de entrada no se toca."""
        self.refresh()
        layer_before = self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name = ?", CROWN_LAYER)
        held = self.calculate()
        volume, area = held.outcome.volume_m3, held.outcome.area_m2
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.operations()
        self.assertEqual(status, "done")
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual((figures["des.btr_volume_m3"], figures["des.btr_area_m2"]), (volume, area))
        for family in ("psf", "epr", "prp"):
            self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND name = ?",
                                       self.dprov.dataset_name(family, FIRST)), [(1,)], family)
        found = self.parameter_of("BTR-001", "crown_m")
        self.assertEqual(found[0], CROWN_M)
        self.assertEqual(found[1], f"diálogo de «Contrafuerte…», entidad «{FIRST}»")
        self.assertEqual((found[2], found[3]), ("ADOPTADO", self.project.session.user_host))
        self.assertEqual(self.parameter_of("BTR-001", "guard_m")[0], GUARD_M)
        for param, value in (("layer", CROWN_LAYER), ("profile", PROFILE.lower()), ("start", self.ground), ("metric", "exact"),
                             ("protect", True)):
            self.assertEqual(self.parameter_of("BTR-001", param)[0], value, param)
        self.assertEqual(self.states(), {"BTR-001": "stale"}, "como la plataforma que protege: la restricción que declara cambia las máscaras")
        self.assertTrue(self.entities.stale_reason(self.project, self.v01.uid, "BTR-001").startswith("Obsoleto: cambió «gis_msk"))
        surface = self.surfaces.read_surface(self.project, self.dprov.dataset_name("psf", FIRST), version_uid=self.v01.uid).values
        ground = platform_ops.ground()
        self.assertTrue(np.all(surface >= ground), "un contrafuerte no corta ninguna celda")
        zone = zone_cells(CROWNS[0][1])
        np.testing.assert_array_equal(surface, held.outcome.compose(ground), "lo registrado es lo que dio el cálculo, entero")
        self.assertEqual(float(surface[zone].max()), CROWN_M, "la zona de coronación llega a su cota")
        self.assertTrue(np.all(surface[zone] >= CROWN_M - 0.2), "y no baja de ella más que el borde de su escalón")
        self.assertGreater(int(np.count_nonzero(surface > ground)), int(zone.sum()), "el pie sale de la zona dibujada")
        # lo que sigue a crearlo: «sin corte» sobre la zona de coronación y no sobre la huella
        (declared,) = self.declared()
        self.assertEqual((declared.code, declared.entity_code, declared.entity_name, declared.buffer_out_m, declared.active),
                         ("dec__btr_001", "BTR-001", FIRST, GUARD_M, True))
        (ring,) = declared.parts[0]
        left, bottom = float(ring[:, 0].min()) - platform_ops.WEST, float(ring[:, 1].min()) - platform_ops.SOUTH
        right, top = float(ring[:, 0].max()) - platform_ops.WEST, float(ring[:, 1].max()) - platform_ops.SOUTH
        self.assertEqual((left, bottom, right, top), CROWNS[0][1], "el polígono de la restricción es la zona de coronación de la capa")
        self.assertEqual(self.rows("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid", platform_ops.DECLARE_TYPE),
                         [("done",)])
        access = platform_ops._module("gis.masks.access")
        self.assertEqual(access.mask_state(self.project, self.v01.uid)[0], access.MaskState.CURRENT)
        masks = access.load_masks(self.project, self.v01.uid)
        self.assertFalse(masks.cut_allowed()[zone].any(), "sin corte en la zona de coronación")
        footprint = surface > ground
        self.assertTrue(masks.cut_allowed()[footprint & ~masks.zone(declared.code).mask(footprint.shape)].any(),
                        "la huella entera no queda sin corte: solo su zona y el resguardo")
        self.assertEqual(self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name = ?", CROWN_LAYER), layer_before,
                         "la capa de entrada no se toca")

    def states(self) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, self.v01.uid)}

    def test_e_a_second_buttress_starts_from_the_first_rests_on_the_ground_and_does_not_protect(self) -> None:
        """RF-016-17, RF-015-04, RF-015-14, RF-015-10, D-7, M3: un segundo contrafuerte **parte del primero** (la última de la cadena, la que
        propone el diálogo), con un apoyo declarado (no cambia el cálculo), el alcance fijado y la métrica del chaflán; **sin proteger no hace
        falta el resguardo** y no declara nada (el primero sigue declarado); la cadena queda BTR-001 → BTR-002 y la superficie del segundo se
        ofrece como partida."""
        self.refresh()
        fake, context, _dialog, _said = self.fake_dialog()
        self.cls.invoke(fake, context, None)
        self.assertEqual((fake.name, fake.start), ("Contrafuerte", "entity:BTR-001"), "un nombre nuevo y la última de la cadena")
        held = self.calculate(name=SECOND, feature=CROWNS[2][0], start="entity:BTR-001", support=self.ground, crown="125", reach="20",
                              metric="CHAMFER5", protect=False, guard="")
        self.assertEqual((held.entity.code, held.entity.start_surface, held.entity.support_surface),
                         ("BTR-002", self.dprov.dataset_name("psf", FIRST), self.ground))
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(self.states(), {"BTR-001": "stale", "BTR-002": "stale"}, "el segundo, en cascada con el primero (las máscaras)")
        for param, value in (("start", "entity:BTR-001"), ("support", self.ground), ("reach_m", 20.0), ("metric", "chamfer5"),
                             ("protect", False), ("crown_m", 125.0)):
            self.assertEqual(self.parameter_of("BTR-002", param)[0], value, param)
        self.assertEqual([item.entity_code for item in self.declared()], ["BTR-001"], "el segundo no protege: nada nuevo declarado")
        self.refresh()
        self.assertIn("entity:BTR-002", [identifier for identifier, _label, _about in self.panels.platform_start_items(None, None)])
        self.assertEqual(self.panels.platform_default_start(), "entity:BTR-002", "ahora es la última de la cadena")

    def test_f_the_buttress_command_is_disabled_with_its_reason(self) -> None:
        """RF-015-28, RF-016-17: con el proyecto en solo lectura o con la versión activa no editable (V02 SUPERADO) la orden sale
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
            self.assertFalse(bpy.ops.geoblender.des_add_buttress.poll())
            before = self.state()
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form(name="No debe"))
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
        self.assertFalse(bpy.ops.geoblender.des_add_buttress.poll())
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.assertTrue(poll())

    def test_g_esc_in_what_follows_creating_it_says_the_buttress_is_created_and_the_next_operation_declares(self) -> None:
        """RF-015-10, RF-015-29, RNF-016-05, M3: Esc **en lo que sigue a «Crear»** (la declaración y las máscaras, por pasos con su avance) deja
        el contrafuerte **creado** —la orden lo dice— y la restricción sin declarar, con las máscaras que quedan obsoletas por su causa, hasta que
        lo que sigue se hace de nuevo (aquí, ``after_entity_change``, que encadena también la orden siguiente): el contrafuerte no se pierde."""
        self.refresh()
        self.calculate(name="Tercero", feature=CROWNS[2][0], start="entity:BTR-002", crown="125", guard="3", reason="Porque el pie lo pide")
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", confirm=True, in_steps=True), {"RUNNING_MODAL"})
            modal = self.running()
            modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
            state, _count = step_modals.drive(modal, bpy.context, stop_after=0)
            self.assertEqual(state, {"RUNNING_MODAL"}, "lo que sigue no debía haber acabado")
            self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertIn(CANCELLED_TEXT, list(modal.report_log))
        self.assertIn(self.states()["BTR-003"], ("current", "stale"), "el contrafuerte está creado")
        self.assertEqual([status for _uid, status in self.operations()], ["done", "done", "done"])
        self.assertEqual(sorted(item.entity_code for item in self.declared()), ["BTR-001"], "la restricción nueva aún no está declarada")
        self.assertIsNone(self.des_ops.calculation())
        last = None
        for last in platform_ops._module("design.entity_store").after_entity_change(self.project, self.v01.uid):
            pass
        self.assertIsNone(last.result.failure, None if last.result.failure is None else last.result.failure.reason)
        found = {item.entity_code: item for item in self.declared()}
        self.assertEqual(sorted(found), ["BTR-001", "BTR-003"], "ahora sí")
        self.assertEqual(found["BTR-003"].buffer_out_m, 3.0)
        self.assertIn("Porque el pie lo pide", found["BTR-003"].reason, "el motivo que dio la persona")

    def test_z_disabling_geoblender_removes_the_buttress_command_and_leaves_no_temporary(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta (no queda ningún temporal) y quita la orden."""
        self.refresh()
        held = self.calculate(name="Al apagar", feature=CROWNS[0][0], start=self.panels.platform_default_start(), crown="135")
        self.assertTrue(any(".tmp" in name for name in self.names()))
        self.assertIsNotNone(held)
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, ADD_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(body_ops.CreateBodyTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test"):
        setattr(CreateButtressTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
