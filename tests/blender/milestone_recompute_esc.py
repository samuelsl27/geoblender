# SPDX-License-Identifier: GPL-3.0-or-later
"""Esc en «Recalcular lo obsoleto» con entidades de diseño (spec 015, T49; RF-015-29, RNF-015-05, RF-015-27, RF-008-26;
la regresión que la T43 dejó en ``perf_entities.py::test_d_esc``): el modal real (``geoblender.core_recompute_stale``) de
un proyecto con dos entidades encadenadas (P1 «Carga», que protege, y P2 «Taller», que parte de la superficie de P1), con las colas
de pasos de ``des``, las máscaras y la verificación avanzadas a mano (en ``blender -b`` no corren los temporizadores).

Esc se atiende **en cualquier momento del cálculo**, también en lo que «Recalcular lo obsoleto» hace **tras** el
recálculo (la capa de entidades que ``des`` pone al día, ``core_provenance.register_recompute_after``), no solo mientras
se recalcula una unidad:

- **En una unidad** (la prueba a): acaba la unidad en curso (lo hecho queda, cada operación es completa), el modal acaba
  ``CANCELLED`` con el resultado cancelado, **lo demás sigue obsoleto y sin tocar** y no corre lo que sigue al
  recálculo; ninguna operación en curso, ningún temporal.
- **En lo que sigue** (la prueba b; antes de la T49 se ignoraba y acababa ``FINISHED`` después de escribir la capa
  entera): el modal acaba **en el mismo evento** de Esc, ``CANCELLED`` con el resultado cancelado, **sin escribir más**:
  el proyecto queda como estaba antes de empezar lo que sigue, salvo la operación de la capa, que queda **cancelada**
  (RF-008-19), sin operación en curso ni temporal; la capa queda **marcada** (``entity_store.layer_pending``) y la
  próxima orden de entidades o «Recalcular lo obsoleto» la pone al día.

Un proyecto pequeño (el de ``test_platform_ops``: 60 × 60 m con celdas de 2 m). Se ejecuta con
``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any
from unittest import mock

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.support import step_modals

TIMER = step_modals.TIMER
ESCAPE = platform_ops.ESCAPE
MAX_EVENTS = 600
START_LEVEL = "des.platform.plt_001.start_level_m"
LAYER_TYPE = "des.entity_layer"


def _module(name: str) -> Any:
    return platform_ops._module(name)


class RecomputeEscTest(platform_ops.CreatePlatformTest):
    """El proyecto de ``CreatePlatformTest`` con P1 «Carga» (que protege, con 4 m) y P2 «Taller» (de la superficie de P1) en V01; sus pruebas no se
    repiten (más abajo)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.refresh()
        cls.made(protect=True, guard="4")
        cls.made(name=platform_ops.WORKSHOP, feature=platform_ops.WORKSHOP, start="entity:PLT-001")
        cls.entity_store = _module("design.entity_store")
        cls.recompute_module = _module("core.provenance.recompute")

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def made(cls, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        cls.refresh()
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **cls.form_of(**values)) == {"FINISHED"}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False) == {"FINISHED"}

    @classmethod
    def form_of(cls, **values: Any) -> dict[str, Any]:
        return {"name": platform_ops.LOADING, "layer": platform_ops.LAYER, "feature": platform_ops.LOADING,
                "start": cls.ground, "edge_angle": "35", "reach": "10", "in_steps": False, **values}

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(mock.patch.object(self.des_ops, "_ask_confirmation"))
        self.enterContext(mock.patch.object(_module("bl.ops.incorporation"), "status_text"))

    def change_level(self, delta: float) -> None:
        """Cambia la cota inicial de P1 en V01 en ``delta`` m (P1, P2, lo que declara P1 y la capa quedan obsoletas)."""
        params = _module("core.params")
        store = params.ParameterStore(self.project)
        with self.project.read() as conn:
            current = float(store.get(START_LEVEL, version=self.v01.uid, conn=conn).value)
        with self.project.write_transaction() as conn:
            store.change(conn, START_LEVEL, value=current + delta, version=self.v01.uid,
                         reason="Prueba de Esc en «Recalcular lo obsoleto»")
        self.assertTrue(self.stale_operations(), "cambiar la cota deja obsoleta la cadena")

    def stale_operations(self) -> list[str]:
        """Los tipos de las operaciones vigentes de V01 que están obsoletas ahora."""
        return [op_type for (op_type,) in self.rows(
            "SELECT o.op_type FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE r.version_uid = ? AND o.status = 'done' AND o.superseded_by IS NULL AND EXISTS "
            "(SELECT 1 FROM gb_stale AS s WHERE s.item_kind = 'operation' AND s.item_uid = o.uid) ORDER BY o.fid",
            self.v01.uid)]

    def operations(self) -> list[tuple[str, str, str]]:
        return self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid")

    def tick(self) -> None:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``)."""
        gis_ops, res_ops = _module("bl.ops.gis"), _module("bl.ops.res")
        self.des_ops.des_tick()
        gis_ops.masks_tick()
        res_ops.res_tick()

    def start(self) -> tuple[Any, list[str]]:
        """Lanza «Recalcular lo obsoleto» (el modal real): el operador en marcha y las fases de lo que va mostrando (``Progress.
        phase``: la del recálculo o la de lo que sigue)."""
        phases: list[str] = []
        original = self.session._RecomputeModal._show  # noqa: SLF001 - se mira lo que enseña el modal

        def spy(operator: Any, context: Any, step: Any) -> None:
            phases.append(step.phase)
            return original(operator, context, step)

        self.enterContext(mock.patch.object(self.session._RecomputeModal, "_show", spy))  # noqa: SLF001
        self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"), {"RUNNING_MODAL"})
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale)
                 and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1)
        operator = found[0]
        self.addCleanup(lambda: getattr(operator, "_steps", None) is None or operator.cancel(bpy.context))
        return operator, phases

    def event(self, operator: Any) -> set[str]:
        """Un evento del temporizador del modal y un paso de cada cola."""
        state = operator.modal(bpy.context, TIMER)
        self.tick()
        return state

    def until_end(self, operator: Any, state: set[str]) -> set[str]:
        """Eventos hasta que el modal acaba (con las colas), desde ``state``."""
        for _ in range(MAX_EVENTS):
            if state != {"RUNNING_MODAL"}:
                return state
            state = self.event(operator)
        self.fail("el modal no acaba")
        return state

    def finish(self) -> None:
        """«Recalcular lo obsoleto», pasada tras pasada, hasta que no queda nada obsoleto y la capa dice lo que el
        registro (deja el estado al día para la prueba siguiente)."""
        for _ in range(8):
            operator, _phases = self.start()
            self.assertEqual(self.until_end(operator, {"RUNNING_MODAL"}), {"FINISHED"})
            if not self.stale_operations():
                break
        self.assertEqual(self.stale_operations(), [])
        self.assertFalse(self.layer_pending())

    def layer_pending(self) -> bool:
        with self.project.read() as conn:
            return self.entity_store.layer_pending(self.project, conn, self.v01.uid)

    def layer_states(self) -> dict[str, str]:
        """Lo que dice la capa de entidades de V01 de cada entidad."""
        return dict(self.rows("SELECT code, state FROM des_enl_v01"))

    def assert_nothing_half_done(self, where: str) -> None:
        """Ninguna operación «en curso» y ningún temporal en el proyecto."""
        self.assertEqual(self.rows("SELECT uid FROM gb_operation WHERE status = 'running'"), [], f"{where}: una operación en curso")
        self.assertEqual([name for name in self.names() if ".tmp" in name], [], f"{where}: un temporal")
        self.assertIsNone(self.des_ops.pending_runs() or None, f"{where}: pasos esperando en la cola de des")

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_esc_in_a_unit_finishes_it_and_the_rest_stays_stale_and_untouched(self) -> None:
        """RF-015-29, RNF-015-05, RF-008-26 (T49; la unidad de P1 en curso): Esc tras el primer evento acaba la unidad en curso
        (lo hecho queda), el modal acaba ``CANCELLED`` con el resultado cancelado, P2 y la capa siguen obsoletas y **sin
        tocar** (la misma operación, ninguna operación de la capa nueva: lo que sigue al recálculo no corre) y no queda ninguna
        operación en curso ni temporal; «Recalcular lo obsoleto», después, deja todo al día."""
        self.change_level(0.5)
        before = {uid: (op_type, status) for uid, op_type, status in self.operations()}
        self.assertEqual(self.stale_operations().count("des.platform"), 2, "P1 y P2 obsoletas")
        self.assertIn(LAYER_TYPE, self.stale_operations())
        operator, phases = self.start()
        for _ in range(MAX_EVENTS):  # hasta que la unidad de P1 ha empezado y espera a su cola
            self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
            if self.rows("SELECT count(*) FROM gb_operation WHERE status = 'running'") == [(1,)]:
                break
            self.tick()
        else:
            self.fail("la unidad de P1 no empieza")
        state = self.until_end(operator, operator.modal(bpy.context, ESCAPE))
        self.assertEqual(state, {"CANCELLED"})
        self.assertTrue(operator.result.cancelled)
        self.assertEqual(len([r for r in operator.result.results if str(r.status) == "done"]), 1, "la unidad en curso acabó")
        self.assertGreater(len(operator.result.remaining.units), 0, "lo demás sigue en el plan")
        self.assertEqual(set(phases), {self.recompute_module.RECOMPUTE_PHASE}, "no llegó a correr lo que sigue al recálculo")
        self.assert_nothing_half_done("Esc en la unidad de P1")
        after = {uid: (op_type, status) for uid, op_type, status in self.operations()}
        new = {uid: row for uid, row in after.items() if uid not in before}
        self.assertEqual(sorted(op_type for op_type, _status in new.values()), ["des.platform"],
                         "solo la operación nueva de P1 (la de P2 y la capa, sin tocar)")
        self.assertEqual(sorted(self.stale_operations()), sorted(["des.platform", LAYER_TYPE]))
        self.assertTrue(self.layer_pending(), "la capa dice lo de antes de cambiar la cota: marcada")
        self.finish()

    def leave_the_layer_behind(self) -> None:
        """Crea «Rampa» (de la superficie de P2) con lo que sigue a «Crear» por pasos de un evento y manda Esc en el primero,
        antes de que llegue a la capa de entidades: la entidad está creada y la capa no tiene su fila (marcada). Es lo
        que **«Recalcular lo obsoleto» pone al día tras recalcular** (``des``), sin que el grafo de la 008 tenga nada obsoleto
        que lo haga por la capa (la entidad nueva no es entrada de la capa de antes)."""
        self.refresh()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_platform(
                "EXEC_DEFAULT", **self.form_of(name=platform_ops.RAMP, feature=platform_ops.RAMP, start="entity:PLT-002")),
                {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=True),
                             {"RUNNING_MODAL"})
            modal = self.running()
            modal.STEP_BUDGET_S = step_modals.ONE_STEP_S
            state, _count = step_modals.drive(modal, bpy.context, stop_after=0)
            self.assertEqual(state, {"RUNNING_MODAL"}, "la cadena no debía haber acabado")
            self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.des_ops.discard_calculation()
        self.assertTrue(self.layer_pending(), "la capa no tiene la entidad nueva: marcada")

    def test_b_esc_while_what_follows_the_recompute_runs_stops_it_at_once_and_writes_nothing_more(self) -> None:
        """RF-015-29, RNF-015-05, RF-015-27, RF-008-19 (T49; la regresión de la T43, ``perf_entities.py::test_d_esc``): la
        capa de entidades de V01 está atrasada (Esc cortó lo que sigue a crear «Rampa» antes de la capa) y **al terminar el
        recálculo, la capa de entidades se pone al día** (lo que registra ``des`` para después: con la 015, T51, «Recalcular lo
        obsoleto» rehace de una vez todo lo que el grafo da por obsoleto, también la capa, así que lo de después solo tiene
        trabajo si el grafo no lo marcó). Con Esc **mientras la capa se pone al día**, el
        modal acaba **en el mismo evento**, ``CANCELLED``, con el resultado cancelado; no se escribe nada
        más: el proyecto queda como antes de empezar la capa salvo la operación de la capa, **cancelada**, sin operación en
        curso ni temporal (antes de la T49 Esc se ignoraba: la capa se escribía entera y el modal acababa ``FINISHED``). La
        capa queda marcada y «Recalcular lo obsoleto», después, la deja al día."""
        self.leave_the_layer_behind()
        operator, phases = self.start()
        state: set[str] = {"RUNNING_MODAL"}
        before: tuple[Any, ...] = ()
        for _ in range(MAX_EVENTS):
            if state != {"RUNNING_MODAL"} or phases and phases[-1] != self.recompute_module.RECOMPUTE_PHASE:
                break
            before = (self.operations(), self.state()[1:])  # el proyecto antes de que empiece lo que sigue
            state = self.event(operator)
        self.assertEqual(state, {"RUNNING_MODAL"}, "el recálculo no acabó: lo que sigue está en curso")
        self.assertNotEqual(phases[-1], self.recompute_module.RECOMPUTE_PHASE, "lo que sigue ha empezado")
        shown = len(phases)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE status = 'running' AND op_type = ?", LAYER_TYPE),
                         [(1,)], "la capa está a mitad cuando llega Esc")
        started = self.operations()
        self.assertEqual(operator.modal(bpy.context, ESCAPE), {"CANCELLED"}, "Esc acaba el modal en el mismo evento")
        self.assertEqual(len(phases), shown, "Esc no enseña un paso más de lo que sigue")
        self.assertTrue(operator.result.cancelled)
        self.assertEqual([r for r in operator.result.results if str(r.status) != "done"], [], "nada rechazado ni fallado")
        self.assertIsNone(operator._steps)  # noqa: SLF001
        self.assert_nothing_half_done("Esc en lo que sigue al recálculo")
        ended = self.operations()
        layer = [uid for uid, op_type, status in started if op_type == LAYER_TYPE and status == "running"]
        self.assertEqual(len(layer), 1)
        self.assertEqual([row for row in ended if row not in before[0]], [(layer[0], LAYER_TYPE, "cancelled")],
                         "lo único que cambió desde antes de empezar la capa es su operación, cancelada")
        self.assertEqual(self.state()[1:], before[1], "los datos, los parámetros, las cifras y los ficheros, como antes")
        self.assertTrue(self.layer_pending(), "la capa queda marcada")
        self.finish()


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(RecomputeEscTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
