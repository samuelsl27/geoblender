# SPDX-License-Identifier: GPL-3.0-or-later
"""Calcular una entidad traída o heredada «sin calcular» desde la interfaz, en Blender (spec 015, T41; HU-015-2; RF-015-18,
RF-015-15, RF-015-28; CE-015-01, última cláusula; hallazgo C-12 de la verificación): «Traer las entidades de…» y la
versión que parte de otra dejan la entidad con sus parámetros y sin resultado, y el diálogo de «Plataforma…» **no podía
calcularla** (``des.entity_name_repeated`` si se repetía su nombre, ``des.entity_start_taken`` con otro: «sin calcular»
ocupa su nombre y su partida) ni el menú «Entidad ▾» tenía con qué; el rodeo —descartarla y crear otra con otro nombre—
pierde sus parámetros y su historial.

:class:`GEOBLENDER_OT_des_entity_calculate` (``geoblender.des_entity_calculate``, «Calcular…» del menú «Entidad ▾») abre una
ventana con las entidades **sin calcular** de la versión activa (una sin calcular no tiene objeto en la vista: se elige por su
nombre) y, al aceptar, lanza «Plataforma…» (``des_create_platform``) **con su código** (la propiedad oculta ``code``): sin
diálogo, calcula con los parámetros que la entidad ya tiene en la versión (``design.entity_store.entity_request``), enseña el
resumen y pide confirmar; «Crear» la registra **con su código y sin tocar ningún parámetro** y la dependencia «se apoya en» se
detecta de nuevo. Sale desactivada con su motivo si el proyecto no está en escritura o la versión activa no es editable.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m y la ladera ``100 + 0,25·y + 0,0625·x``) con una
capa más: «Sobre Carga» (el eje y el ancho de «Carga», a 112 m). V01: P1 «Carga» (corta del todo, a 105 m: su huella son
**10 × 4 = 40 celdas de 4 m²**) y P2 «Sobre Carga» («en corte y relleno», de la superficie de P1: sube 7 m sobre ella,
40 · 7 · 4 = **1.120 m³** a mano); V03 parte de V01 (hereda las dos) y V02 recibe las dos con «Traer las entidades de…». Las
pruebas, en el orden de sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

CALCULATE = "geoblender.des_entity_calculate"
CALCULATE_CLASS = "GEOBLENDER_OT_des_entity_calculate"
PLATFORM = platform_ops.PLATFORM
BRING = "geoblender.des_entity_bring"
DESCRIPTION = ("Calculate a design entity that has no result yet, brought from another version or inherited: with the "
               "parameters it has in the version, and what rests on it is detected again")
PROPERTIES = {
    "entity": ("Entity", "Code or name of the design entity to calculate: one brought from another version or inherited, "
                         "without a result (empty: the one chosen in the window)"),
}
"""Las propiedades de la orden con el ``msgid`` de su nombre y de su descripción (la colección de la ventana no los lleva)."""
HIDDEN = ("candidates",)
OVER = "Sobre Carga"
LOADING, WORKSHOP = platform_ops.LOADING, platform_ops.WORKSHOP
EXTRA = (OVER, ((20.0, 30.0), (40.0, 30.0)), 8.0, 112.0, 0.0)
FILL_M3 = 40 * (112.0 - 105.0) * platform_ops.CELL_M2
"""1.120 m³: P2 sube 7 m sobre la rasante de P1 (105 m) en sus 40 celdas de 4 m², a mano."""
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
MENU = "GEOBLENDER_MT_des_context_entity"


class Rows:
    """Una colección de mentira (``CollectionProperty``): lo que usa la ventana."""

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


def _close(found: float, expected: float, relative: float = 1e-9) -> bool:
    return abs(found - expected) <= relative * abs(expected)


class EntityCalculateTest(platform_ops.CreatePlatformTest):
    """La extensión habilitada una vez y el proyecto de la cantera de plataformas con una capa más y una versión hija."""

    v03: Any

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, EXTRA)):
            super().setUpClass()

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def command(cls) -> Any:
        return cls.commands.registered_class(CALCULATE)

    def activate(self, version: Any) -> None:
        """La versión activa pasa a ser ``version``, con sus máscaras al día (si no, «Calcular» las compila antes)."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=version.uid), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        self.refresh()

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def states(self, version: Any) -> dict[str, str]:
        registry = self.entities.registry(self.project, version.uid)
        return {entry.record.code: str(entry.record.state) for entry in registry}

    def parameters(self, version: Any) -> list[tuple[Any, ...]]:
        """Los parámetros propios de ``version`` con su historial (el valor, la revisión y quién lo decidió): lo que
        calcular **no** puede cambiar."""
        return self.rows("SELECT key, value, rev, decided_by, decided_at FROM gb_parameter WHERE scope = 'version' AND "
                         "scope_uid = ? ORDER BY key", version.uid)

    def history(self, code: str, param: str, version: Any) -> list[tuple[Any, ...]]:
        return self.rows("SELECT h.action, h.reason FROM gb_parameter_history AS h JOIN gb_parameter AS p ON "
                         "p.uid = h.parameter_uid WHERE p.key = ? AND p.scope = 'version' AND p.scope_uid = ? "
                         "ORDER BY h.rev", f"des.platform.{code.lower().replace('-', '_')}.{param}", version.uid)

    def fake(self, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:
        """El operador de mentira, el contexto con que se abre la ventana (sin ventana propia), la ventana y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {
            "entity": "", "candidates": Rows(), "provenance_dialog": False,
            "report": lambda kind, text: said.append((kind, text)), **values}
        return operator_self(self.command(), **fields), context, dialog, said

    def poll(self) -> tuple[bool, list[str]]:
        """El ``poll`` de la orden y lo que dice (``poll_message_set``)."""
        cls = self.command()
        messages: list[str] = []
        with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)),
                               create=True):
            return bool(cls.poll(bpy.context)), messages

    def run_command(self, entity: str) -> Any:
        """«Calcular…» de punta a punta desde un guion: la orden y, en lugar de abrir «Plataforma…» con un temporizador (que
        en ``blender -b`` no corre), la misma llamada con sus valores, ya y **con ``INVOKE_DEFAULT``** (como la abre el
        temporizador: sin diálogo, calcula); si corre en el modal de pasos, se lleva evento a evento hasta el final;
        devuelve el cálculo abierto."""
        calls: list[tuple[str, dict[str, Any]]] = []

        def launch(idname: str, _window: Any, **values: Any) -> None:
            calls.append((idname, values))
            found = bpy.ops.geoblender.des_create_platform("INVOKE_DEFAULT", **values)
            if found == {"RUNNING_MODAL"}:
                modal = self.running()
                modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
                found, _events = step_modals.drive(modal, bpy.context)
            self.assertEqual(found, {"FINISHED"})

        with mock.patch.object(self.des_ops, "_invoke_later", side_effect=launch), \
                mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", entity=entity), {"FINISHED"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], PLATFORM)
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def refused(self, text: str, **values: Any) -> None:
        """Lanzar la orden desde un guion se rechaza con ``text``, no abre «Plataforma…» y no escribe nada."""
        before = self.state()
        with mock.patch.object(self.des_ops, "_invoke_later") as later, self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", **values)
        self.assertIn(text, str(caught.exception))
        later.assert_not_called()
        self.assertEqual(self.state(), before)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_is_a_real_internal_command_with_named_properties(self) -> None:
        """RF-015-18, RF-015-28 (plan §5.3.3): «Calcular…» es una orden real de ``des``, interna, de la entrada 015, con la
        puerta de la procedencia y el ``poll`` común de Diseño, propiedades con nombre y descripción (registradas ya en
        español) y la descripción del catálogo; la propiedad oculta ``code`` de «Plataforma…» (la que pone esta orden) no
        lleva nombre ni descripción y no es un campo del diálogo."""
        cls = self.command()
        self.assertIsNotNone(cls)
        self.assertEqual(cls.__name__, CALCULATE_CLASS)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.bl_idname, cls.bl_label, cls.bl_options, cls.provenance_op_type),
                         (CALCULATE, "Calcular…", {"REGISTER"}, platform_ops.PLATFORM_TYPE))
        catalog = self.commands.catalog()
        command = catalog.commands[CALCULATE]
        self.assertEqual((command.kind, command.entry, command.module, command.label, command.label_es),
                         ("internal", "015", "des", "Calculate…", "Calcular…"))
        self.assertEqual(command.description, DESCRIPTION)
        self.assertEqual(cls.__doc__.strip(), DESCRIPTION)
        self.assertNotIn(CALCULATE, {name for defn in self.dprov.ENTITY_OPERATION_TYPES for name in defn.commands})
        self.assertTrue(self.commands.is_available(CALCULATE))
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, set(PROPERTIES))
        for prop, (name, about) in PROPERTIES.items():
            keywords = cls.__annotations__[prop].keywords
            self.assertEqual((keywords["name"], keywords["description"]),
                             (self.i18n.translate("es", name), self.i18n.translate("es", about)))
            self.assertEqual(self.i18n.untranslated([name, about]), [])
        platform = self.cls
        self.assertNotIn("name", platform.__annotations__["code"].keywords)
        self.assertIn("code", self.des_ops._PLATFORM_HIDDEN)
        self.assertNotIn("code", self.des_ops._platform_fields())
        self.assertEqual(self.i18n.untranslated(["Calculate…", "The active version has no entity without a result: the "
                                                 "ones brought from another version or inherited from the version it "
                                                 "starts from are left without one", "Choose the entity to calculate"]),
                         [])

    def test_b_the_entity_menu_has_it_after_bringing_and_enabled(self) -> None:
        """RF-015-28, C-12: el menú «Entidad ▾» dibuja «Calcular…» justo después de «Traer las entidades de…», activa con el
        proyecto en escritura y la versión editable."""
        shown = draw(getattr(bpy.types, MENU), bpy.context)
        operators = [(item.target, item.enabled, item.text) for item in shown.items if item.kind == "operator"]
        targets = [target for target, _enabled, _text in operators]
        self.assertEqual(targets.index(CALCULATE), targets.index(BRING) + 1)
        self.assertEqual([(enabled, text) for target, enabled, text in operators if target == CALCULATE],
                         [(True, "Calcular…")])

    def test_c_two_platforms_are_made_and_a_version_that_starts_from_the_first_inherits_them(self) -> None:
        """CE-015-01, RF-015-15 (el mundo de estas pruebas): P1 «Carga» y P2 «Sobre Carga» (de la superficie de P1, «en corte y
        relleno») creadas en V01 con las órdenes reales, al día; P2 se apoya en P1 con **1.120 m³ a mano**; V03, que parte de
        V01, las hereda **sin calcular**."""
        self.made()
        self.made(name=OVER, feature=OVER, start="entity:PLT-001", mode="CUT_FILL")
        self.assertEqual(self.states(self.v01), {"PLT-001": "current", "PLT-002": "current"})
        (row,) = self.entities.dependents(self.project, self.v01.uid, "PLT-001")
        self.assertTrue(_close(row.volume_m3, FILL_M3), row.volume_m3)
        store = platform_ops._module("core.versions.store")
        with self.project.write_transaction() as conn:
            type(self).v03, _revision = store.create_version(conn, self.project, feature="hija", title="Hija",
                                                             reason=platform_ops.REASON, parent="V01")
        self.project.refresh_header()
        self.assertEqual(self.states(self.v03), {"PLT-001": "uncalculated", "PLT-002": "uncalculated"})
        self.assertEqual(self.states(self.v02), {})

    def test_d_the_window_offers_the_entities_without_a_result_of_the_active_version(self) -> None:
        """RF-015-18, RF-015-28, C-12: con V02 activa y sin entidades, «Calcular…» lo dice sin abrir la ventana; tras traer las
        de V01 (la orden real: sin calcular), la ventana las ofrece **por su nombre** —una sin calcular no tiene objeto en la
        vista— y propone la primera, dice con qué se calcula y qué hace Calcular; una entidad ya calculada no sale; no escribe
        nada."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        cls = self.command()
        none, context, dialog, said = self.fake()
        self.assertEqual(cls.invoke(none, context, None), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "La versión activa no tiene ninguna entidad sin resultado: quedan así las que "
                                            "se traen de otra versión o se heredan de la versión de la que parte")])
        dialog.assert_not_called()
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01"), {"FINISHED"})
        self.assertEqual(self.states(self.v02), {"PLT-001": "uncalculated", "PLT-002": "uncalculated"})
        before = self.state()
        fake, context, dialog, said = self.fake()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(said, [])
        self.assertEqual(dialog.call_args.kwargs["title"], "Calcular…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertEqual([(row.name, row.label) for row in fake.candidates],
                         [(LOADING, "Carga (PLT-001)"), (OVER, "Sobre Carga (PLT-002)")])
        self.assertEqual(fake.entity, LOADING, "propone la primera")
        given, context, _dialog, _said = self.fake(entity="PLT-002")
        cls.invoke(given, context, None)
        self.assertEqual(given.entity, OVER, "lo dado, por su código, se queda (con su nombre)")
        self.assertEqual(draw(cls, bpy.context, entity=OVER, candidates=fake.candidates).texts(), [
            "Entidad", "Se calcula con los parámetros que ya tiene en la versión; no se elige nada de nuevo.",
            "Calcular enseña su resumen y no registra nada: solo «Crear» lo hace, y entonces se detecta de nuevo lo que se "
            "apoya en ella."])
        self.assertEqual(self.state(), before, "la ventana no escribe nada")
        self.assertEqual(self.poll(), (True, []))
        self.activate(self.v01)  # en V01 las dos están calculadas: nada que ofrecer
        calculated, context, dialog, said = self.fake()
        self.assertEqual(cls.invoke(calculated, context, None), {"CANCELLED"})
        self.assertEqual(len(said), 1)
        dialog.assert_not_called()

    def test_e_calculating_the_first_in_v02_keeps_its_code_and_its_parameters(self) -> None:
        """RF-015-18, RF-015-01, C-12 (la orden real): «Calcular…» P1 en V02 lanza «Plataforma…» **con su código**
        (PLT-001) y sin diálogo: enseña el resumen (la misma huella de **40 celdas** que en V01) y no escribe nada;
        «Crear» la registra **con su código y sin tocar ni un parámetro** (las mismas filas con su historial «Traído
        de V01.r1») y queda al día; antes de esto, con el mismo nombre, «Plataforma…» la rechazaba (hallazgo C-12)."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        parameters = self.parameters(self.v02)
        history = self.history("PLT-001", "name", self.v02)
        self.assertEqual([reason for _action, reason in history], ["Traído de V01.r1"])
        before = self.state()
        # «Plataforma…» lanzada con el código **no abre su diálogo**: ``invoke`` calcula (la ventana del temporizador no existe
        # en ``blender -b``: ``bpy.ops`` ejecuta un diálogo sin abrirlo, así que se mira ``invoke`` a mano, sin ventana).
        fake, _context, dialog = self.fake_dialog(code="PLT-001", preview=False)
        context = SimpleNamespace(window=None, selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        self.assertEqual(self.cls.invoke(fake, context, None), {"FINISHED"})
        dialog.assert_not_called()
        opened = self.des_ops.calculation()
        self.assertEqual((opened.name, opened.entity.code), (LOADING, "PLT-001"))
        self.des_ops.discard_calculation()
        self.assertEqual(self.state()[:4], before[:4], "calcular no registra nada")
        held = self.run_command("Carga")
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), (platform_ops.PLATFORM_TYPE, LOADING,
                                                                                    "V02", "PLT-001"))
        self.assertEqual(held.outcome.footprint.cell_count, platform_ops.LOADING_CELLS)
        after = self.state()
        self.assertEqual(after[1], before[1], "calcular no registra ningún dato")
        self.assertEqual(self.parameters(self.v02), parameters, "ni escribe un parámetro")
        self.assertEqual(self.states(self.v02)["PLT-001"], "uncalculated")
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.states(self.v02), {"PLT-001": "current", "PLT-002": "uncalculated"})
        self.assertEqual(self.parameters(self.v02), parameters, "crear no cambia ningún parámetro")
        self.assertEqual(self.history("PLT-001", "name", self.v02), history)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name LIKE 'des!_psf!_%' ESCAPE '!' AND "
                                   "version_uid = ?", self.v02.uid), [(1,)])

    def test_f_calculating_the_second_detects_the_dependency_again_with_the_same_volume(self) -> None:
        """RF-015-18, RF-015-15, CE-015-01 (D-9), C-12 (la orden real): «Calcular…» P2 «Sobre Carga» en V02, que parte de la
        superficie de P1 (ya calculada) y rellena 7 m sobre su huella, la registra con su código y **se apoya de nuevo en
        P1 con los 1.120 m³ a mano** (≤ 10⁻⁹ relativo), los mismos que en V01; sus parámetros siguen siendo los traídos y
        lo que se apoya en P1 es una sola lista."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v02)
        parameters = self.parameters(self.v02)
        held = self.run_command(OVER)
        self.assertEqual(held.entity.code, "PLT-002")
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(self.states(self.v02), {"PLT-001": "current", "PLT-002": "current"})
        self.assertEqual(self.parameters(self.v02), parameters)
        (row,) = self.entities.dependents(self.project, self.v02.uid, "PLT-001")
        self.assertEqual((row.name, set(row.roles)), (OVER, {"supported_on", "surface"}))
        self.assertTrue(_close(row.volume_m3, FILL_M3), (row.volume_m3, FILL_M3))
        (original,) = self.entities.dependents(self.project, self.v01.uid, "PLT-001")
        self.assertEqual(row.volume_m3, original.volume_m3, "los mismos m³ que en la versión de origen")
        self.assertEqual(self.states(self.v01), {"PLT-001": "current", "PLT-002": "current"}, "V01 no cambia")

    def test_g_a_version_that_starts_from_another_calculates_what_it_inherited_the_same_way(self) -> None:
        """RF-015-18, RF-009-01, CE-015-01, C-12 (la orden real): en V03, que parte de V01 y hereda las dos «sin calcular»,
        «Calcular…» las calcula con su código (P1 y después P2, por el orden de la cadena) sin tocar sus parámetros (su
        historial dice «Heredado de V01.r1») y P2 se apoya en P1 con los mismos 1.120 m³; con P2 antes que P1, lo dice."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v03)
        parameters = self.parameters(self.v03)
        self.assertEqual([reason for _action, reason in self.history("PLT-001", "name", self.v03)], ["Heredado de V01.r1"])
        with self.assertRaises(RuntimeError) as early:  # P2 parte de la superficie de P1, que aún no está calculada
            bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", code="PLT-002", in_steps=False)
        self.assertIn("«des.platform.plt_002.start» = entity:PLT-001 no es la superficie de una entidad calculada",
                      str(early.exception))
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.parameters(self.v03), parameters)
        self.run_command("PLT-001")
        self.assertEqual(self.create(), {"FINISHED"})
        self.run_command("PLT-002")
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(self.states(self.v03), {"PLT-001": "current", "PLT-002": "current"})
        self.assertEqual(self.parameters(self.v03), parameters)
        (row,) = self.entities.dependents(self.project, self.v03.uid, "PLT-001")
        self.assertTrue(_close(row.volume_m3, FILL_M3), row.volume_m3)

    def test_h_what_cannot_be_calculated_says_why_and_writes_nothing(self) -> None:
        """RF-015-18, RF-015-17, C-12: sin elegir entidad, con una que no es de la versión o con una que ya tiene resultado
        (P1 de V03), la orden lo dice con su texto, no abre «Plataforma…» y no escribe nada; con «Plataforma…» lanzada con el
        código de una que ya está calculada, también (la prepara y lo rechaza antes de calcular)."""
        self.addCleanup(self.activate, self.v01)
        self.activate(self.v03)
        self.refused("Elija la entidad que se calcula")
        self.refused("«PLT-099» no es una entidad de V03", entity="PLT-099")
        self.refused("La entidad «Carga» (PLT-001) ya tiene resultado en V03", entity="PLT-001")
        self.refused("«Recalcular lo obsoleto»", entity=LOADING)
        before = self.state()
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", code="PLT-001", in_steps=False)
        self.assertIn("ya tiene resultado", str(caught.exception))
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

    def test_i_it_is_disabled_with_its_reason(self) -> None:
        """RF-015-28 (M5): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable
        (V02 SUPERADO), sale desactivada con su motivo en el menú y no se puede lanzar; con V01 en escritura, activa."""
        self.assertEqual(self.poll(), (True, []))
        before = self.state()
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            found, messages = self.poll()
            self.assertFalse(found)
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_entity_calculate.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", entity="PLT-001")
            self.assertEqual(self.state(), before)
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         (platform_ops.REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        found, messages = self.poll()
        self.assertFalse(found)
        self.assertEqual(messages, [NOT_EDITABLE])
        self.assertIn(NOT_EDITABLE, self.command().description(bpy.context, SimpleNamespace()))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.assertEqual(self.poll(), (True, []))

    def test_z_disabling_geoblender_removes_the_command(self) -> None:
        """Principio 8: desactivar Geoblender quita la orden y no deja ningún temporal."""
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, CALCULATE_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(EntityCalculateTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
