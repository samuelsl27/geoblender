# SPDX-License-Identifier: GPL-3.0-or-later
"""Descartar una entidad y soltar el apoyo en Blender (spec 015, T25; HU-015-2; RF-015-17, RF-009-12, RF-015-28,
RF-015-29; D-12; plan 015 §5.3.3 y §5.4 A7, P-6; comprobación manual M5 en lo que toca).

:class:`GEOBLENDER_OT_des_entity_discard` (``geoblender.des_entity_discard``) **enseña antes una sola lista** de lo
que se apoya en la entidad y de lo que parte de ella (nombre, tipo y m³) y pide confirmar con el motivo; al aceptar
descarta la entidad sin borrar nada y encadena ``after_entity_change`` por pasos con el avance y Esc.
:class:`GEOBLENDER_OT_des_entity_release_support` (``geoblender.des_entity_release_support``) da por bueno lo que
perdió su apoyo repitiéndolo sin él, con el motivo y el decisor en sus ajustes. Las dos salen desactivadas con su
motivo si el proyecto no está en escritura o la versión activa no es editable (RF-015-28).

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02) con una capa de líneas más:
«Sobre Carga» (el eje y el ancho de «Carga», a 112 m). P1 es «Carga» (del terreno, que corta del todo), P2 «Taller»
(**parte de la superficie de P1**) y P3 «Sobre Carga» (de **otro terreno**, «en corte y relleno»: rellena sobre la huella
de P1, así que se apoya en ella sin partir de su superficie). Las pruebas, en el orden de sus letras sobre el mismo
estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

DISCARD = "geoblender.des_entity_discard"
RELEASE = "geoblender.des_entity_release_support"
DISCARD_CLASS = "GEOBLENDER_OT_des_entity_discard"
RELEASE_CLASS = "GEOBLENDER_OT_des_entity_release_support"
OVER = "Sobre Carga"
WHY = "La propiedad cambia el plan: la carga no se hace"
DESCRIPTIONS = {
    DISCARD: "Discard a design entity: it stays in the project as a record, nothing is deleted, and what rests on it "
             "is left as «support removed»",
    RELEASE: "Give as good what lost its support because an entity was discarded: it is repeated without that "
             "support, with a reason that is recorded",
}
PROPERTIES = {
    DISCARD: {
        "entity": ("Entity", "Code or name of the design entity to discard"),
        "reason": ("Reason", "Why the entity is discarded; it is recorded with the decision"),
    },
    RELEASE: {
        "target": ("Entity or design", "Code or name of the entity, or uid or name of the design, that lost its "
                                       "support"),
        "entity": ("Discarded entity", "Code or name of the discarded entity it no longer rests on (empty: every "
                                       "one it lost)"),
        "reason": ("Reason", "Why it is given as good without that support; it is recorded with the decision"),
    },
}
"""Las propiedades de cada orden con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone quien
la lanza, no los llevan)."""
HIDDEN = ("in_steps",)


class EntityDiscardTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con una capa más y otro
    terreno."""

    ground2: str

    @classmethod
    def setUpClass(cls) -> None:
        extra = (OVER, ((20.0, 30.0), (40.0, 30.0)), 8.0, 112.0, 0.0)
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, extra)):
            super().setUpClass()
        cls.ground2 = cls.write_grid("Ladera 2", platform_ops.ground())
        cls.refresh()

    # --- Ayudas -------------------------------------------------------------------------------

    def command(self, idname: str) -> Any:
        return self.commands.registered_class(idname)

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``)."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def states(self) -> dict[str, str]:
        registry = self.entities.registry(self.project, self.v01.uid)
        return {entry.record.code: str(entry.record.state) for entry in registry}

    def events(self, kind: str) -> list[Any]:
        events = _events()
        with self.project.read() as conn:
            return events.read_events(conn, events.EventKind(kind))

    def fake(self, idname: str, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:
        """El operador de mentira, el contexto con que se abre el diálogo (sin ventana), el diálogo y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {
            "entity": "", "target": "", "reason": "", "in_steps": False, "provenance_dialog": False,
            "report": lambda kind, text: said.append((kind, text)), **values}
        return operator_self(self.command(idname), **fields), context, dialog, said

    def refused(self, idname: str, text: str, **values: Any) -> None:
        """Lanzar la orden desde un guion se rechaza con ``text`` y no escribe nada."""
        before = self.state()
        with self.assertRaises(RuntimeError) as caught:
            getattr(bpy.ops.geoblender, idname.split(".")[1])("EXEC_DEFAULT", **values)
        self.assertIn(text, str(caught.exception))
        self.assertEqual(self.state(), before)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_commands_are_real_internal_commands_with_named_properties(self) -> None:
        """RF-015-17, RF-015-28 (plan §5.3.3): «Descartar…» y «Soltar el apoyo…» son órdenes reales de ``des``, de la
        entrada 015 que entrega la T31, internas y en el menú «Entidad ▾» (T31); con la puerta
        de la procedencia y los pasos con Esc, el ``poll`` común de Diseño y propiedades con nombre y descripción
        (registradas ya en español); su descripción es la del catálogo; la desactivación y el registro simétrico los
        mira la prueba de registro."""
        catalog = self.commands.catalog()
        for idname, class_name, label, label_es in ((DISCARD, DISCARD_CLASS, "Discard…", "Descartar…"),
                                                    (RELEASE, RELEASE_CLASS, "Release the support…",
                                                     "Soltar el apoyo…")):
            with self.subTest(orden=idname):
                cls = self.command(idname)
                self.assertIsNotNone(cls)
                self.assertEqual(cls.__name__, class_name)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertIn(cls, self.des_ops.classes)
                self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
                self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
                self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
                self.assertEqual((cls.bl_idname, cls.bl_label, cls.bl_options),
                                 (idname, label_es, {"REGISTER"}))  # registrada ya en español
                self.assertEqual(cls.STEP_BUDGET_S, 0.05)
                command = catalog.commands[idname]
                self.assertEqual((command.kind, command.entry, command.module, command.label, command.label_es),
                                 ("internal", "015", "des", label, label_es))
                self.assertEqual(command.description, DESCRIPTIONS[idname])
                self.assertEqual(cls.__doc__.strip(), DESCRIPTIONS[idname])
                self.assertNotIn(idname, {name for defn in self.dprov.ENTITY_OPERATION_TYPES for name in defn.commands})
                annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
                self.assertEqual(annotated, set(PROPERTIES[idname]))
                for prop, (name, about) in PROPERTIES[idname].items():
                    keywords = cls.__annotations__[prop].keywords
                    self.assertEqual((keywords["name"], keywords["description"]),
                                     (self.i18n.translate("es", name), self.i18n.translate("es", about)))
                    self.assertEqual(self.i18n.untranslated([name, about]), [])
                for prop in HIDDEN:
                    self.assertNotIn("name", cls.__annotations__[prop].keywords)
                self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(catalog.entries["015"].delivered, "la entrega la T31")

    def test_b_a_platform_that_rests_on_another_without_starting_from_it_and_one_that_starts_from_it(self) -> None:
        """RF-015-15, RF-015-17 (el mundo de estas pruebas): P1 «Carga», P2 «Taller» (de la superficie de P1: solo
        ``surface``) y P3 «Sobre Carga» (de otro terreno, «en corte y relleno» sobre la huella de P1: se apoya en ella
        con sus m³ sin partir de su superficie), todas al día."""
        self.made()
        self.made(name=platform_ops.WORKSHOP, feature=platform_ops.WORKSHOP, start="entity:PLT-001",
                  start_level="107,5", gradient="0", width="5", reach="6")
        self.made(name=OVER, feature=OVER, start=self.ground2, mode="CUT_FILL")
        self.assertEqual(self.states(), {"PLT-001": "current", "PLT-002": "current", "PLT-003": "current"})
        listed = self.entities.dependents(self.project, self.v01.uid, "PLT-001")
        self.assertEqual([(row.name, row.roles) for row in listed],
                         [(platform_ops.WORKSHOP, ("surface",)), (OVER, ("supported_on",))])
        self.assertIsNone(listed[0].volume_m3)
        self.assertGreater(listed[1].volume_m3, 100.0)

    def test_c_the_dialog_shows_the_list_before_discarding_and_asks_for_the_reason(self) -> None:
        """RF-015-17 (RF-015-28): antes de descartar, el diálogo enseña **una sola lista** de lo que se apoya en la entidad y
        de lo que parte de ella —el nombre, el tipo y los m³ de cada uno—, lo que les pasará (quedan en «apoyo retirado»
        y «Recalcular lo obsoleto» no los recalcula) y el campo del motivo; «Descartar» confirma; sin entidad, lo dice;
        no escribe nada."""
        cls = self.command(DISCARD)
        before = self.state()
        fake, context, dialog, said = self.fake(DISCARD, entity="PLT-001")
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Descartar «Carga»")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Descartar")
        self.assertTrue(fake.in_steps)
        self.assertEqual([line.split(":")[0] for line in fake._plan.lines("es")],
                         [f"{platform_ops.WORKSHOP} (Plataforma)", f"{OVER} (Plataforma)"])
        shown = draw(cls, bpy.context, entity="PLT-001", reason="", _plan=fake._plan).texts()
        self.assertEqual(shown[0], "«Carga» (PLT-001) se descartará: queda en el proyecto como registro y no se borra nada")
        self.assertEqual(shown[2], f"{platform_ops.WORKSHOP} (Plataforma): superficie de partida")
        self.assertRegex(shown[3], rf"^{OVER} \(Plataforma\): .+ m³ apoyados$")
        self.assertIn("Quedan como «apoyo retirado».", shown)
        self.assertTrue(any("«Recalcular lo obsoleto» no los recalcula" in text for text in shown))
        self.assertEqual(shown[-1], "Motivo")
        lone, context, _dialog, _said = self.fake(DISCARD, entity="PLT-003")  # sin nada que se apoye en ella
        cls.invoke(lone, context, None)
        self.assertIn("Nada se apoya en la entidad ni parte de ella.",
                      draw(cls, bpy.context, entity="PLT-003", reason="", _plan=lone._plan).texts())
        empty, context, dialog, said = self.fake(DISCARD)
        self.assertEqual(cls.invoke(empty, context, None), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "Elija la entidad que se descarta")])
        dialog.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_d_discarding_leaves_it_as_a_record_with_an_event_and_chains_what_follows(self) -> None:
        """RF-015-17, RF-009-12, RF-015-10, RF-015-29, D-12: aceptar descarta P1 **sin borrar nada** (sus tres datos
        ``discarded``; la operación, las cifras y los ficheros siguen), con un evento (el motivo, quién y la lista de lo
        que se le apoyaba) y encadena lo que sigue (``after_entity_change``: declara de nuevo); dice lo que quedó en
        «apoyo retirado»; P2 y P3 lo están, con su causa."""
        declared = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?", platform_ops.DECLARE_TYPE)
        datasets = self.rows("SELECT count(*) FROM gb_dataset")
        operations = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?", platform_ops.PLATFORM_TYPE)
        fake, _context, _dialog, said = self.fake(DISCARD, entity="PLT-001", reason=WHY)
        self.assertEqual(self.command(DISCARD).execute(fake, bpy.context), {"FINISHED"})
        self.assertEqual(said, [({"INFO"}, "Entidad «Carga» descartada en V01: no se ha borrado nada"),
                                ({"WARNING"}, f"Quedan como «apoyo retirado»: «{platform_ops.WORKSHOP}», «{OVER}»")])
        self.assertEqual(self.states(), {"PLT-001": "discarded", "PLT-002": "support_removed",
                                         "PLT-003": "support_removed"})
        for name in (self.dprov.dataset_name(family, platform_ops.LOADING) for family in ("psf", "epr", "prp")):
            self.assertEqual(self.rows("SELECT status FROM gb_dataset WHERE name = ?", name), [("discarded",)])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset"), datasets, "nada se borra")
        self.assertEqual(self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?",
                                   platform_ops.PLATFORM_TYPE), operations)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?", platform_ops.DECLARE_TYPE),
                         [(declared[0][0] + 1,)], "lo que sigue declara de nuevo")
        (event,) = self.events("entity_discarded")
        self.assertEqual((event.data["entity"], event.data["reason"], event.data["decided_by"]),
                         ("PLT-001", WHY, self.project.session.user_host))
        self.assertEqual([item["name"] for item in event.data["dependents"]], [platform_ops.WORKSHOP, OVER])
        self.assertEqual(self.entities.stale_reason(self.project, self.v01.uid, "PLT-002"),
                         "Apoyo retirado: se descartó la plataforma Carga")
        self.assertEqual(self.entities.stale_reason(self.project, self.v01.uid, OVER),
                         "Apoyo retirado: se descartó la plataforma Carga")
        self.assertEqual(self.layer_state(), self.layer_before, "la capa de origen no se toca")
        access = platform_ops._module("gis.masks.access")  # descartar no deja las máscaras sin poder usarse
        self.assertEqual(access.mask_state(self.project, self.v01.uid)[0], access.MaskState.CURRENT)

    def test_e_what_is_refused_writes_nothing(self) -> None:
        """RF-015-17, RF-009-12: sin motivo, ya descartada o sin entidad se rechaza con su texto y no se escribe
        nada; lo mismo con «Soltar el apoyo…»: sin motivo, lo que parte de la superficie descartada (P2: se rehace sobre
        otra superficie o se descarta), lo que no ha perdido su apoyo (P1) y sin nada que dar por bueno."""
        self.refused(DISCARD, "escriba el motivo", entity="PLT-003", reason=" ")
        self.refused(DISCARD, "ya está descartada", entity="PLT-001", reason=WHY)
        self.refused(DISCARD, "Elija la entidad que se descarta", reason=WHY)
        self.refused(RELEASE, "escriba el motivo", target="PLT-003", reason="")
        self.refused(RELEASE, "parte de la superficie de «Carga»", target="PLT-002", reason=WHY)
        self.refused(RELEASE, "no tiene retirado su apoyo", target="PLT-003", entity="PLT-002", reason=WHY)
        self.refused(RELEASE, "Elija lo que se da por bueno", reason=WHY)
        with self.assertRaises(RuntimeError):  # una entidad que no es de la versión: error del programa, dicho
            bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="PLT-009", reason=WHY)

    def test_f_the_release_dialog_says_what_was_lost_and_refuses_what_cannot_be_given_as_good(self) -> None:
        """RF-015-17, A7: el diálogo de «Soltar el apoyo…» dice qué perdió su apoyo y la causa, que se repite sin él con
        el motivo y que lo que dependía de ello no se recalcula si su resultado no cambia; lo que parte de la superficie
        descartada (P2), lo que no ha perdido su apoyo y sin nada elegido, lo dicen sin abrir nada."""
        cls = self.command(RELEASE)
        fake, context, dialog, said = self.fake(RELEASE, target="PLT-003")
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], f"Soltar el apoyo de «{OVER}»")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Dar por bueno")
        shown = draw(cls, bpy.context, target="PLT-003", reason="", _lost=fake._lost).texts()
        self.assertEqual(shown[0], f"«{OVER}» (Plataforma) perdió su apoyo:")
        self.assertEqual(shown[1], "Apoyo retirado: se descartó la plataforma Carga")
        self.assertIn("Se repite sin ese apoyo, con el motivo que dé.", shown)
        self.assertEqual(shown[-1], "Motivo")
        for target, text in (("PLT-002", "parte de la superficie de una entidad descartada"),
                             ("PLT-001", "no ha perdido su apoyo"), ("", "Elija lo que se da por bueno")):
            refused, context, dialog, said = self.fake(RELEASE, target=target)
            self.assertEqual(cls.invoke(refused, context, None), {"CANCELLED"}, target)
            self.assertIn(text, said[0][1])
            dialog.assert_not_called()

    def test_g_giving_it_as_good_repeats_it_without_the_support_and_its_result_does_not_change(self) -> None:
        """RF-015-17, A7, P-6, RF-008-26: dar por buena a P3 (que se apoyaba en P1, descartada, sin partir de su superficie)
        la repite **sin ese apoyo**, con el motivo y el decisor en sus ajustes y un evento: su salida no cambia (los
        mismos hash), sale de «apoyo retirado» y de la lista de lo que se apoya en P1; P2, que parte de la superficie
        de P1, sigue en «apoyo retirado»."""
        old = self.entities.registry(self.project, self.v01.uid).get("PLT-003").operation_uid
        hashes = self.rows("SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d "
                           "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", old)
        self.assertEqual(bpy.ops.geoblender.des_entity_release_support(
            "EXEC_DEFAULT", target="PLT-003", reason=WHY, in_steps=False), {"FINISHED"})
        new = self.entities.registry(self.project, self.v01.uid).get("PLT-003").operation_uid
        self.assertNotEqual(new, old)
        # P2 (que parte de la superficie de P1) sigue en «apoyo retirado». (Hasta la T26 la declaración consumía la tabla de
        # cada entidad viva y, con P2 así, la declaración, las máscaras y lo que las usó quedaban obsoletos en cascada;
        # ahora solo consume las de las que protegen, que aquí no hay.)
        self.assertNotEqual(self.states()["PLT-003"], "support_removed")
        self.assertEqual(self.states()["PLT-002"], "support_removed")
        self.assertEqual(self.rows("SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d "
                                   "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", new),
                         hashes, "su salida no cambia")
        self.assertEqual(self.rows("SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
                                   "WHERE io.operation_uid = ? AND io.role IN ('supported_on', 'support_footprint')",
                                   new), [])
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE uid = ?", new)
        (released,) = json.loads(settings)["supports_released"]
        self.assertEqual((released["entity"], released["reason"], released["by"]),
                         ("PLT-001", WHY, self.project.session.user_host))
        (event,) = self.events("support_released")
        self.assertEqual((event.entity_uid, event.data["entities"], event.data["reason"]), (new, ["PLT-001"], WHY))
        self.assertEqual([row.name for row in self.entities.dependents(self.project, self.v01.uid, "PLT-001")],
                         [platform_ops.WORKSHOP])
        self.assertEqual([row.name for row in self.entities.retired_supports(self.project, self.v01.uid)],
                         [platform_ops.WORKSHOP])

    def test_h_esc_while_what_follows_runs_leaves_the_entity_discarded_and_nothing_half_done(self) -> None:
        """RF-015-17, RF-015-29, RF-009-12: descartar P2 desde la interfaz corre lo que sigue en el modal, con el avance
        y Esc; cancelar a mitad deja la entidad **descartada** (ya está: nada se deshace) y lo que sigue sin hacer, sin
        nada a medias, y lo dice."""
        self.assertEqual(bpy.ops.geoblender.des_entity_discard(
            "EXEC_DEFAULT", entity="PLT-002", reason=WHY, in_steps=True), {"RUNNING_MODAL"})
        self.assertEqual(self.states()["PLT-002"], "discarded")
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.command(DISCARD)) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1)
        modal = found[0]
        modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
        self.assertEqual(modal.modal(bpy.context, step_modals.TIMER), {"RUNNING_MODAL"})
        self.assertEqual(modal.modal(bpy.context, platform_ops.ESCAPE), {"CANCELLED"})
        self.assertIn("Cancelado: la entidad está descartada; las restricciones declaradas y las máscaras se ponen al "
                      "día antes de la próxima operación que las use", modal.report_log)
        self.assertIsNone(modal._steps)
        self.assertEqual(self.states()["PLT-002"], "discarded")
        self.assertEqual(len(self.events("entity_discarded")), 2)
        self.assertFalse(any(".tmp" in name for name in self.names()))

    def test_i_both_are_disabled_with_their_reason(self) -> None:
        """RF-015-28 (M5): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable
        (V02 SUPERADO), las dos salen desactivadas con su motivo y no se pueden lanzar; con V01 en escritura, activas."""
        classes = (self.command(DISCARD), self.command(RELEASE))
        messages: list[str] = []

        def poll(cls: Any) -> bool:
            messages.clear()
            with mock.patch.object(cls, "poll_message_set", classmethod(
                    lambda _cls, text: messages.append(text)), create=True):
                return bool(cls.poll(bpy.context))

        for cls in classes:
            self.assertTrue(poll(cls))
            self.assertEqual(messages, [])
        before = self.state()
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            for cls in classes:
                self.assertFalse(poll(cls))
                (reason,) = messages
                self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_entity_discard.poll())
            self.assertFalse(bpy.ops.geoblender.des_entity_release_support.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="PLT-003", reason=WHY)
            self.assertEqual(self.state(), before)
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         (platform_ops.REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        not_editable = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        for cls in classes:
            self.assertFalse(poll(cls))
            self.assertEqual(messages, [not_editable])
            self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        for cls in classes:
            self.assertTrue(poll(cls))

    def test_z_disabling_geoblender_removes_the_commands(self) -> None:
        """Principio 8: desactivar Geoblender quita las dos órdenes y no deja ningún temporal."""
        blender_ext.release()
        for name in (DISCARD_CLASS, RELEASE_CLASS):
            self.assertIsNone(getattr(bpy.types, name, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


def _events() -> Any:
    return platform_ops._module("core.project.events")


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(EntityDiscardTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
