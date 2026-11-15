# SPDX-License-Identifier: GPL-3.0-or-later
"""Traer las entidades de otra versión en Blender (spec 015, T26; HU-015-2; RF-015-18, RF-009-01, RF-015-28; D-18;
plan 015 §5.3.3).

:class:`GEOBLENDER_OT_des_entity_bring` (``geoblender.des_entity_bring``) abre un diálogo con la versión de origen
—cualquiera de las del proyecto menos la activa— y sus entidades vivas (las descartadas no se traen), una casilla cada
una, todas marcadas; al aceptar copia sus definiciones a la versión activa (``design.entity_store.bring_entities``), **sin
resultados ni cifras**, «sin calcular», y dice lo que hizo. Sale desactivada con su motivo si el proyecto no está en
escritura o la versión activa no es editable (RF-015-28).

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02): P1 es «Carga» (del terreno)
y P2 «Taller» (de la superficie de P1), creadas en V01; se traen a V02. Las pruebas, en el orden de sus letras sobre el
mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext
from tests.support.fake_layout import draw, operator_self

BRING = "geoblender.des_entity_bring"
BRING_CLASS = "GEOBLENDER_OT_des_entity_bring"
ROW_CLASS = "GEOBLENDER_PG_des_bring_row"
DESCRIPTION = ("Bring the entities of another version to the active one, without their results: they are left as "
               "«not calculated»")
PROPERTIES = {
    "source": ("Version", "Code of the version the entities are brought from: any but the active one"),
    "entities": ("Entities", "Codes or names of the entities to bring, separated by commas (empty: the ones chosen "
                             "in the window or, without it, every one that is not discarded)"),
}
"""Las propiedades de la orden con el ``msgid`` de su nombre y de su descripción (las colecciones de filas, que llena el
diálogo, no los llevan)."""
HIDDEN = ("versions", "rows")


class Rows:
    """Una colección de mentira (``CollectionProperty``): lo que usan el diálogo y su ``update``."""

    def __init__(self, *items: Any) -> None:
        self.items = list(items)

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


class EntityBringTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten)."""

    @classmethod
    def command(cls) -> Any:
        return cls.commands.registered_class(BRING)

    # --- Ayudas -------------------------------------------------------------------------------

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def states(self, version: Any) -> dict[str, str]:
        registry = self.entities.registry(self.project, version.uid)
        return {entry.record.code: str(entry.record.state) for entry in registry}

    def activate(self, version: Any) -> None:
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=version.uid), {"FINISHED"})

    def fake(self, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:
        """El operador de mentira, el contexto con que se abre el diálogo (sin ventana), el diálogo y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {
            "source": "", "entities": "", "versions": Rows(), "rows": Rows(), "provenance_dialog": False,
            "report": lambda kind, text: said.append((kind, text)), **values}
        return operator_self(self.command(), **fields), context, dialog, said

    def history(self, code: str, param: str, version: Any) -> list[tuple[Any, ...]]:
        return self.rows("SELECT h.action, h.reason FROM gb_parameter_history AS h JOIN gb_parameter AS p ON "
                         "p.uid = h.parameter_uid WHERE p.key = ? AND p.scope = 'version' AND p.scope_uid = ? "
                         "ORDER BY h.rev", f"des.platform.{code.lower().replace('-', '_')}.{param}", version.uid)

    def results_of(self, version: Any) -> list[Any]:
        """Los datos, las operaciones y las cifras de ``version`` (ninguno si solo tiene definiciones)."""
        return [self.rows("SELECT name FROM gb_dataset WHERE version_uid = ?", version.uid),
                self.rows("SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
                          "WHERE r.version_uid = ?", version.uid),
                self.rows("SELECT f.key FROM gb_figure AS f JOIN gb_operation AS o ON o.uid = f.operation_uid "
                          "JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE r.version_uid = ?", version.uid)]

    def refused(self, text: str, **values: Any) -> None:
        """Lanzar la orden desde un guion se rechaza con ``text`` y no escribe nada."""
        before = self.state()
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", **values)
        self.assertIn(text, str(caught.exception))
        self.assertEqual(self.state(), before)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_is_a_real_internal_command_with_named_properties(self) -> None:
        """RF-015-18, RF-015-28 (plan §5.3.3): «Traer las entidades de…» es una orden real de ``des``, de la entrada
        015 que entrega la T31, interna y en el menú «Entidad ▾» (T31); con la puerta de la
        procedencia y el ``poll`` común de Diseño, propiedades con nombre y descripción (registradas ya en español) y su
        descripción es la del catálogo; la desactivación y el registro simétrico los mira la prueba de registro."""
        cls = self.command()
        self.assertIsNotNone(cls)
        self.assertEqual(cls.__name__, BRING_CLASS)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.bl_idname, cls.bl_label, cls.bl_options),
                         (BRING, "Traer las entidades de…", {"REGISTER"}))  # registrada ya en español
        catalog = self.commands.catalog()
        command = catalog.commands[BRING]
        self.assertEqual((command.kind, command.entry, command.module, command.label, command.label_es),
                         ("internal", "015", "des", "Bring the entities of…", "Traer las entidades de…"))
        self.assertEqual(command.description, DESCRIPTION)
        self.assertEqual(cls.__doc__.strip(), DESCRIPTION)
        self.assertNotIn(BRING, {name for defn in self.dprov.ENTITY_OPERATION_TYPES for name in defn.commands})
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, set(PROPERTIES))
        for prop, (name, about) in PROPERTIES.items():
            keywords = cls.__annotations__[prop].keywords
            self.assertEqual((keywords["name"], keywords["description"]),
                             (self.i18n.translate("es", name), self.i18n.translate("es", about)))
            self.assertEqual(self.i18n.untranslated([name, about]), [])
        self.assertTrue(cls.poll(bpy.context))
        props = platform_ops._module("bl.props.des")
        self.assertIn(props.GEOBLENDER_PG_des_bring_row, props.classes)
        self.assertTrue(props.GEOBLENDER_PG_des_bring_row.is_registered)
        self.assertTrue(catalog.entries["015"].delivered, "la entrega la T31")

    def test_b_two_platforms_of_a_version_are_calculated_and_created(self) -> None:
        """RF-015-18 (el mundo de estas pruebas): P1 «Carga» y P2 «Taller» (de la superficie de P1) creadas en V01, al día;
        V02 no tiene ninguna."""
        self.made()
        self.made(name=platform_ops.WORKSHOP, feature=platform_ops.WORKSHOP, start="entity:PLT-001",
                  start_level="107,5", gradient="0", width="5", reach="6")
        self.assertEqual(self.states(self.v01), {"PLT-001": "current", "PLT-002": "current"})
        self.assertEqual(self.states(self.v02), {})

    def test_c_the_dialog_offers_the_other_versions_and_the_live_entities_of_the_chosen_one(self) -> None:
        """RF-015-18, RF-015-28: con V02 activa, el diálogo ofrece las demás versiones (V01), propone la última y pone sus
        entidades vivas, **todas marcadas**; enseña la versión, una casilla por entidad y lo que pasará (se traen sin
        resultados, «sin calcular», y sus dependencias se detectan de nuevo); sin versión de origen o sin entidades, lo
        dice; no escribe nada."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        cls = self.command()
        before = self.state()
        fake, context, dialog, said = self.fake()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Traer las entidades de…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Traer")
        self.assertEqual([row.name for row in fake.versions], ["V01"])
        self.assertIn("V01", fake.versions.items[0].label)
        self.assertEqual(fake.source, "V01")
        self.assertEqual([(row.name, row.label, row.selected) for row in fake.rows],
                         [("PLT-001", "Carga (PLT-001)", True), ("PLT-002", "Taller (PLT-002)", True)])
        shown = draw(cls, bpy.context, source="V01", versions=fake.versions, rows=fake.rows).texts()
        self.assertEqual(shown, ["Versión", "Entidades que se traen:", "Carga (PLT-001)", "Taller (PLT-002)",
                                 "Se traen sin sus resultados, «sin calcular».",
                                 "Sus dependencias se detectan de nuevo al calcularlas."])
        empty = draw(cls, bpy.context, source="V02", versions=fake.versions, rows=Rows()).texts()
        self.assertEqual(empty, ["Versión", "«V02» no tiene entidades que traer (las descartadas no se traen)"])
        self.assertEqual(draw(cls, bpy.context, source="", versions=Rows(), rows=Rows()).texts(), ["Versión"])
        self.assertEqual(self.state(), before, "el diálogo no escribe nada")

    def test_d_a_project_with_one_version_has_nothing_to_bring_from(self) -> None:
        """RF-015-18: con una sola versión en el proyecto, el diálogo lo dice sin abrirse."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        scene_versions = self.des_ops.scene_versions
        only = tuple(item for item in scene_versions.versions() if item.uid == self.v02.uid)
        fake, context, dialog, said = self.fake()
        with mock.patch.object(scene_versions, "versions", lambda: only):
            self.assertEqual(self.command().invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "El proyecto no tiene otra versión de la que traer entidades")])
        dialog.assert_not_called()

    def test_e_accepting_brings_the_definitions_without_results_and_says_what_it_did(self) -> None:
        """RF-015-18, RF-009-01, D-18: aceptar trae a V02 las dos entidades de V01 **sin resultados ni cifras** (V02 sigue
        sin datos, operaciones ni cifras), «sin calcular», con su historial «Traído de V01.r1»; informa de cuántas y de lo
        que no cambia; V01 no cambia."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        before_v01 = self.states(self.v01)
        rows = self.rows("SELECT key, value, decided_by, decided_at FROM gb_parameter WHERE scope = 'version' AND "
                         "scope_uid = ? ORDER BY key", self.v01.uid)
        fake, _context, _dialog, said = self.fake(source="V01")
        self.assertEqual(self.command().execute(fake, bpy.context), {"FINISHED"})
        self.assertEqual(said, [({"INFO"}, "2 entidades traídas de V01 a V02, sin sus resultados: quedan «sin calcular» "
                                           "y sus dependencias se detectan de nuevo al calcularlas.")])
        self.assertEqual(self.states(self.v02), {"PLT-001": "uncalculated", "PLT-002": "uncalculated"})
        self.assertEqual(self.results_of(self.v02), [[], [], []])
        self.assertEqual(self.history("PLT-002", "start", self.v02), [("create", "Traído de V01.r1")])
        self.assertEqual(self.entities.registry(self.project, self.v02.uid).get("PLT-002").record.start, "entity:PLT-001")
        self.assertEqual(self.states(self.v01), before_v01)
        self.assertEqual(self.rows("SELECT key, value, decided_by, decided_at FROM gb_parameter WHERE scope = "
                                   "'version' AND scope_uid = ? ORDER BY key", self.v01.uid), rows)
        self.assertEqual(self.layer_state(), self.layer_before, "la capa de origen no se toca")

    def test_f_what_is_chosen_in_the_window_or_typed_is_what_is_brought_and_what_changes_is_said(self) -> None:
        """RF-015-18: con una sola entidad marcada en la ventana (o tecleada en ``entities``) solo se trae esa; V02 ya
        tiene PLT-001 y PLT-002: la traída recibe el siguiente código y un nombre con la versión de origen, y la partida
        que era la superficie de una entidad que no se trae queda sin valor, con su aviso (informado como advertencia);
        sin ninguna marcada, se pide elegir; desde un guion, con ``bpy.ops``, igual."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        rows = Rows(SimpleNamespace(name="PLT-001", label="Carga (PLT-001)", selected=False),
                    SimpleNamespace(name="PLT-002", label="Taller (PLT-002)", selected=True))
        fake, _context, _dialog, said = self.fake(source="V01", rows=rows)
        self.assertEqual(self.command().execute(fake, bpy.context), {"FINISHED"})
        self.assertEqual([kind for kind, _text in said], [{"INFO"}, {"INFO"}, {"WARNING"}, {"WARNING"}])
        texts = [text for _kind, text in said]
        self.assertTrue(texts[0].startswith("1 entidad traída de V01 a V02"), texts)
        self.assertIn("«Taller (V01)» era PLT-002 en V01; aquí es PLT-003", texts[1])
        self.assertIn("«Taller» se llama aquí «Taller (V01)»", texts[2])
        self.assertIn("«Taller (V01)»: su superficie de partida «Carga» es un resultado de V01 y no existe en V02",
                      texts[3])
        self.assertEqual(self.states(self.v02), {"PLT-001": "uncalculated", "PLT-002": "uncalculated",
                                                 "PLT-003": "uncalculated"})
        self.assertIsNone(self.entities.registry(self.project, self.v02.uid).get("PLT-003").record.start)
        none = Rows(SimpleNamespace(name="PLT-001", label="Carga (PLT-001)", selected=False))
        refused, _context, _dialog, said = self.fake(source="V01", rows=none)
        self.assertEqual(self.command().execute(refused, bpy.context), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "Elija al menos una entidad que traer")])
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="Carga"),
                         {"FINISHED"})
        self.assertEqual(self.states(self.v02)["PLT-004"], "uncalculated")
        self.assertNotEqual(self.state(), before)

    def test_g_what_is_refused_writes_nothing(self) -> None:
        """RF-015-18, RF-009-21: de la versión activa a ella misma, sin versión de origen, una entidad que la de origen
        no tiene o una versión que no existe se rechazan con su texto y no escriben nada."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        self.refused("es la versión a la que se traen las entidades", source="V02")
        self.refused("Elija la versión de la que se traen las entidades")
        self.refused("no tiene ninguna entidad «Inexistente»", source="V01", entities="Inexistente")
        self.refused("V99", source="V99")

    def test_h_it_is_disabled_with_its_reason(self) -> None:
        """RF-015-28 (M5): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable
        (V02 SUPERADO), sale desactivada con su motivo y no se puede lanzar; con V01 en escritura, activa."""
        cls = self.command()
        messages: list[str] = []

        def poll() -> bool:
            messages.clear()
            with mock.patch.object(cls, "poll_message_set", classmethod(
                    lambda _cls, text: messages.append(text)), create=True):
                return bool(cls.poll(bpy.context))

        self.assertTrue(poll())
        self.assertEqual(messages, [])
        before = self.state()
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(poll())
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_entity_bring.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V02")
            self.assertEqual(self.state(), before)
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         (platform_ops.REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.activate(self.v02)
        not_editable = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertFalse(poll())
        self.assertEqual(messages, [not_editable])
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        self.activate(self.v01)
        self.assertTrue(poll())

    def test_z_disabling_geoblender_removes_the_command_and_its_rows(self) -> None:
        """Principio 8: desactivar Geoblender quita la orden y el grupo de sus filas y no deja ningún temporal."""
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, BRING_CLASS, None))
        self.assertIsNone(getattr(bpy.types, ROW_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(EntityBringTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
