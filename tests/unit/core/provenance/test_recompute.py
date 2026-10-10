# SPDX-License-Identifier: GPL-3.0-or-later
"""Plan de «Recalcular lo obsoleto» (spec 008, T28; RF-008-25, RF-008-26, RF-008-27; plan 008
§5.4.4).

``core.provenance.recompute.plan_recompute`` decide sobre el grafo de la procedencia y su
obsolescencia deducida qué se recalcula y en qué orden, sin ejecutar ni escribir nada:

- recalcula las operaciones obsoletas sin sustituir que se repiten solas y escribieron el
  contenido actual de un dato vivo o una cifra vigente (lo demás ya lo reescribió otra);
- por **unidades**: una ejecución de un grupo acoplado entera, en el orden de su
  ``CoupledGroupDef`` (RF-008-25), o una operación sola;
- en **orden de dependencia**: lo que produce lo que otra consume (la versión que consumió o el
  contenido actual que leerá al recalcularse) va antes;
- deja fuera, con su motivo, las que esperan revisión a mano y lo que depende de ellas aguas
  abajo (RF-008-27), las de un tipo que no está instalado y las calculadas con una versión del
  algoritmo mayor que la instalada («Calculado con res.step_a 1.9: actualice Geoblender»), y
  las de su grupo;
- en tres ámbitos: todo, lo que tiene una causa y lo que necesita un elemento (un dato o una
  operación) para quedar al día.

(T29) ``recompute_steps`` ejecuta el plan por unidades, en pasos que avanza el temporizador de
``bl``: vuelve a planificar antes de cada unidad (lo que dependía solo de una salida que dio el
mismo contenido deja de estar obsoleto sin recalcularse), comprueba al empezarla que sus
entradas siguen vigentes (si no, no la ejecuta y sigue obsoleta) y llama a la función de
recálculo de cada tipo, que crea operaciones nuevas que sustituyen a las anteriores; cancelar
entre unidades deja lo hecho. ``accept_review`` «da por buena» una operación que espera
revisión a mano (``core.accept_review``), con su motivo, y quita la espera de lo de aguas abajo.

Las pruebas usan el proyecto de ``test_graph`` (``GraphCase``), con tipos que se recalculan de
verdad (``RunCase``), y, para las propiedades del plan, sus grafos aleatorios en memoria
(``RandomProject``).
"""

from __future__ import annotations

import ast
import json
import random
import sqlite3
import unittest
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.core.provenance.test_graph import (
    INPUT_1,
    INPUT_2,
    GraphCase,
    RandomProject,
    _op,
    _replace_table,
    _spec,
)
from tests.unit.core.provenance.test_operations import _insert
from tests.unit.core.provenance.test_schema import input_row

provenance = import_geoblender("core.provenance")
recompute = import_geoblender("core.provenance.recompute")
graph_mod = import_geoblender("core.provenance.graph")
stale_mod = import_geoblender("core.provenance.stale")
operations = import_geoblender("core.provenance.operations")
messages = import_geoblender("core.provenance.messages")
contract = import_geoblender("core.provenance.contract")
inputs = import_geoblender("core.inputs")
dataset_registry = import_geoblender("core.datasets.registry")
events = import_geoblender("core.project.events")
project_model = import_geoblender("core.project.model")

Cause = graph_mod.Cause
CauseKind = graph_mod.CauseKind
SkipReason = recompute.SkipReason
ALL = recompute.SCOPE_ALL
Use = operations.Use
ItemKind = operations.ItemKind
ProvenanceError = messages.ProvenanceError

INSTALLED = {"res.step_a": "1.9", "res.step_b": "1.0", "res.step_c": "1.0", "res.step_d": "1.0",
             "res.pair_first": "1.0", "res.pair_second": "1.0", "res.digitize": "1.0",
             "res.edit": "1.0", "res.import_source": "1.0"}
"""Lo instalado en las pruebas, como lo registra ``GraphCase``."""


class RecomputeCase(GraphCase):
    """``GraphCase`` con el plan del proyecto y su lectura."""

    def plan(self, scope: Any = None, **kw: Any) -> Any:
        """El plan del proyecto en ``scope`` (todo, sin él), comprobando que no escribe nada."""
        before = self.snapshot()
        with self.project.read() as conn:
            loaded = graph_mod.load_graph(conn)
        if scope is not None:
            kw["scope"] = scope
        found = recompute.plan_recompute(loaded, **kw)
        self.assertEqual(self.snapshot(), before)
        return found

    def units(self, plan: Any) -> list[tuple[str, ...]]:
        return [unit.operations for unit in plan.units]

    def reasons(self, plan: Any) -> dict[str, tuple[Any, tuple[str, ...]]]:
        """Lo que se deja fuera: motivo y operaciones por las que espera."""
        return {item.operation_uid: (item.reason, tuple(ref.uid for ref in item.waits_for))
                for item in plan.skipped}

    def text(self, plan: Any, uid: str, *, language: str = "es") -> str:
        (item,) = (item for item in plan.skipped if item.operation_uid == uid)
        return str(item.text(language=language))


class PlanOrderTest(RecomputeCase):
    def test_nothing_stale_nothing_planned(self) -> None:
        """RF-008-26 (D-4): sin nada obsoleto, el plan está vacío; planificar no escribe
        nada ni recalcula nada."""
        self.chain()
        plan = self.plan()
        self.assertEqual((plan.units, plan.skipped, plan.operations), ((), (), ()))
        self.assertEqual(plan.scope, ALL)

    def test_order_of_dependency(self) -> None:
        """RF-008-26: el plan sigue el orden de dependencia: lo que reescribe lo que otra lee
        va antes aunque se registrara después (al recalcularse, la otra lee el contenido
        actual), y lo que lee lo producido por otra, después de ella; lo que se deja fuera, por
        orden de registro."""
        self.run_op("res.step_d", {"res_w": [1.0]})
        x = self.run_op("res.step_b", {"res_x": [2.0]}, reads=["res_w"])
        y = self.run_op("res.step_c", {"res_w": [3.0]}, params=["res.production"])
        z = self.run_op("res.step_a", {"res_z": [4.0]}, reads=["res_x"])
        self.assertEqual(self.units(self.plan()), [(x.uid,), (z.uid,)])  # y está al día

        self.change("res.production", 120000.0)
        plan = self.plan()
        self.assertEqual(self.units(plan), [(y.uid,), (x.uid,), (z.uid,)])
        self.assertEqual(plan.operations, (y.uid, x.uid, z.uid))
        self.assertEqual([unit.op_types for unit in plan.units],
                         [("res.step_c",), ("res.step_b",), ("res.step_a",)])
        self.assertEqual([unit.group_uid for unit in plan.units], [None, None, None])
        self.assertEqual(plan.skipped, ())

        contract.unregister_operation("res.step_c")  # lo que se deja fuera, por registro
        plan = self.plan()
        self.assertEqual(plan.units, ())
        self.assertEqual([(item.operation_uid, item.reason) for item in plan.skipped],
                         [(x.uid, SkipReason.WAITS), (y.uid, SkipReason.UNKNOWN_TYPE),
                          (z.uid, SkipReason.WAITS)])

    def test_coupled_group_in_the_order_of_its_group(self) -> None:
        """RF-008-25: las operaciones de una ejecución de un grupo acoplado son una unidad,
        en el orden de su ``CoupledGroupDef`` (aunque se ejecutaran al revés), que va después
        de lo que consume cualquiera de ellas y antes de lo que consume lo que producen;
        recalcular una de ellas recalcula las dos; otra ejecución del grupo, al día, no."""
        z = self.run_op("res.step_a", {"res_y": [1.0]}, params=["res.density"])
        second = self.run_op("res.pair_second", {"res_x2": [2.0]}, reads=["res_y"])
        first = self.run_op("res.pair_first", {"res_x1": [3.0]}, group_uid=second.group_uid)
        i = self.run_op("res.step_c", {"res_i": [4.0]}, reads=["res_x1"])
        h = self.run_op("res.step_b", {"res_h": [5.0]}, reads=["res_x2"])
        other = self.run_op("res.pair_first", {"res_o1": [6.0]})
        self.run_op("res.pair_second", {"res_o2": [7.0]}, group_uid=other.group_uid)
        self.change("res.density", 2.7)

        plan = self.plan()
        pair = (first.uid, second.uid)
        self.assertEqual(self.units(plan), [(z.uid,), pair, (i.uid,), (h.uid,)])
        unit = plan.units[1]
        self.assertEqual((unit.group_uid, unit.group_name, unit.op_types),
                         (second.group_uid, "res.pair", ("res.pair_first", "res.pair_second")))
        self.assertEqual(self.units(self.plan(first.uid)), [(z.uid,), pair])
        self.assertEqual(self.units(self.plan(self.dataset("res_x2"))), [(z.uid,), pair])
        self.assertEqual(self.units(self.plan(self.dataset("res_i"))),
                         [(z.uid,), pair, (i.uid,)])
        self.assertEqual(self.units(self.plan(Cause(CauseKind.GROUP, second.group_uid))),
                         [pair])


class PlanLeftOutTest(RecomputeCase):
    def test_review_by_hand_and_what_waits_for_it(self) -> None:
        """RF-008-27: una operación obsoleta que no se repite sola queda fuera («revisar a
        mano», con lo que cambió) y lo que depende de ella aguas abajo, también indirectamente,
        espera; lo demás se recalcula. La que escribió la cifra vigente también se revisa a
        mano; una que no se repite sola y cuyo resultado ya reescribió otra no tiene nada que
        revisar."""
        a = self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        r = self.run_op("res.digitize", {"res_r": [2.0]}, reads=["res_a"])
        x = self.run_op("res.step_b", {"res_x": [3.0]}, reads=["res_r"])
        y = self.run_op("res.step_c", {"res_y": [4.0]}, reads=["res_x"])
        z = self.run_op("res.step_d", {"res_z": [5.0]}, reads=["res_a"])
        q = self.run_op("res.digitize", {"res_q": [6.0]}, reads=["res_a"])
        self.run_op("res.step_d", {"res_q": [7.0]})  # reescribe lo de q, sin leer nada obsoleto
        s = self.run_op("res.digitize", reads=["res_a"], figure=3.0)  # la cifra vigente
        self.change("res.production", 80000.0)
        production = self.changed("res.production")

        plan = self.plan()
        self.assertEqual(self.units(plan), [(a.uid,), (z.uid,)])
        self.assertEqual(self.reasons(plan), {
            r.uid: (SkipReason.REVIEW, ()),
            x.uid: (SkipReason.WAITS, (r.uid,)),
            y.uid: (SkipReason.WAITS, (r.uid,)),
            s.uid: (SkipReason.REVIEW, ()),
        })
        self.assertEqual([item.operation_uid for item in plan.skipped],
                         [r.uid, x.uid, y.uid, s.uid])
        self.assertNotIn(q.uid, {*plan.operations, *self.reasons(plan)})
        (review,) = (item for item in plan.skipped if item.operation_uid == r.uid)
        self.assertEqual((review.op_type, review.causes), ("res.digitize", {production}))
        self.assertEqual(
            self.text(plan, r.uid),
            "Revisar a mano: la operación «res.digitize» no se repite sola; rehágala o dela "
            "por buena.",
        )
        self.assertEqual(
            self.text(plan, r.uid, language="en"),
            "Review by hand: operation «res.digitize» is not repeated on its own; redo it or "
            "accept it as good.",
        )
        self.assertEqual(
            self.text(plan, y.uid),
            "Espera a lo que tiene aguas arriba y no se recalcula ahora: «res.digitize».",
        )
        self.assertEqual(
            self.text(plan, x.uid, language="en"),
            "Waits for what is upstream of it and is not recomputed now: «res.digitize».",
        )
        self.assertEqual(self.units(self.plan(y.uid)), [(a.uid,)])
        self.assertEqual(set(self.reasons(self.plan(y.uid))), {r.uid, x.uid, y.uid})
        self.assertEqual(self.units(self.plan(self.dataset("res_z"))), [(a.uid,), (z.uid,)])

    def test_edit_by_hand_waits_and_is_not_overwritten(self) -> None:
        """RF-008-27: tras una edición a mano del dato que escribió una operación, lo que lo
        lee espera a que se revise la edición (al recalcularse leería lo editado) y la
        operación que lo escribió antes no se recalcula (borraría la edición)."""
        a = self.run_op("res.step_a", {"res_a": [1.0, 2.0]}, params=["res.production"])
        b = self.run_op("res.step_b", {"res_b": [3.0]}, reads=["res_a"])
        e = self.run_op("res.edit", {"res_a": [1.0, 9.0]}, reads=["res_a"])
        self.change("res.production", 90000.0)
        self.assertEqual(self.stale().review, {e.uid})

        plan = self.plan()
        self.assertEqual(plan.units, ())
        self.assertEqual(self.reasons(plan), {e.uid: (SkipReason.REVIEW, ()),
                                              b.uid: (SkipReason.WAITS, (e.uid,))})
        self.assertNotIn(a.uid, self.reasons(plan))
        self.assertEqual(self.text(plan, b.uid),
                         "Espera a lo que tiene aguas arriba y no se recalcula ahora: "
                         "«res.edit».")

    def test_unknown_type_and_newer_algorithm(self) -> None:
        """RF-008-26 (spec §8): una operación de un tipo que no está instalado o calculada con
        una versión del algoritmo mayor que la instalada no se recalcula, con su motivo
        («Calculado con res.step_a 1.9: actualice Geoblender»), y lo que depende de ella
        espera; una acoplada con una de ellas, tampoco (RF-008-25). Con la misma versión o una
        mayor instalada, sí, y sin el grupo registrado, en el orden en que se ejecutó."""
        a = self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        b = self.run_op("res.step_b", {"res_b": [2.0]}, reads=["res_a"])
        c = self.run_op("res.step_c", {"res_c": [3.0]}, params=["res.production"])
        first = self.run_op("res.pair_first", {"res_x1": [4.0]}, params=["res.production"])
        second = self.run_op("res.pair_second", {"res_x2": [5.0]}, group_uid=first.group_uid)
        d = self.run_op("res.step_d", {"res_d": [6.0]}, params=["res.production"])
        self.change("res.production", 70000.0)
        everything = [(a.uid,), (b.uid,), (c.uid,), (first.uid, second.uid), (d.uid,)]
        self.assertEqual(self.units(self.plan()), everything)

        contract.unregister_operation("res.step_a")
        contract.register_operation(_op("res.step_a", "1.8"))  # otro equipo, más antiguo
        contract.unregister_operation("res.step_c")
        contract.unregister_group("res.pair")
        contract.unregister_operation("res.pair_second")
        plan = self.plan()
        self.assertEqual(self.units(plan), [(d.uid,)])
        self.assertEqual(self.reasons(plan), {
            a.uid: (SkipReason.NEWER_ALGORITHM, ()),
            b.uid: (SkipReason.WAITS, (a.uid,)),
            c.uid: (SkipReason.UNKNOWN_TYPE, ()),
            first.uid: (SkipReason.GROUP, (second.uid,)),
            second.uid: (SkipReason.UNKNOWN_TYPE, ()),
        })
        self.assertEqual(self.text(plan, a.uid),
                         "Calculado con res.step_a 1.9: actualice Geoblender")
        self.assertEqual(self.text(plan, a.uid, language="en"),
                         "Computed with res.step_a 1.9: update Geoblender")
        self.assertEqual(self.text(plan, c.uid),
                         "No hay ninguna operación registrada del tipo «res.step_c»: el módulo "
                         "que la declara no está activo o es de otra versión de Geoblender.")
        self.assertEqual(self.text(plan, first.uid),
                         "Está acoplada en el grupo «res.pair» y no se recalcula sin "
                         "«res.pair_second».")
        self.assertEqual(self.text(plan, first.uid, language="en"),
                         "It is coupled in group «res.pair» and is not recomputed without "
                         "«res.pair_second».")
        self.assertEqual(self.text(plan, b.uid),
                         "Espera a lo que tiene aguas arriba y no se recalcula ahora: "
                         "«res.step_a».")

        for installed in ("1.9", "1.10"):
            with self.subTest(installed=installed):
                plan = self.plan(versions={**INSTALLED, "res.step_a": installed})
                self.assertEqual(self.units(plan), everything)
                self.assertEqual(plan.skipped, ())
        plan = self.plan(versions={**INSTALLED, "res.step_c": "0.9"})
        self.assertEqual(self.reasons(plan), {c.uid: (SkipReason.NEWER_ALGORITHM, ())})
        self.assertEqual(self.text(plan, c.uid),
                         "Calculado con res.step_c 1.0: actualice Geoblender")


class PlanScopeTest(RecomputeCase):
    def test_all_by_cause_and_by_item(self) -> None:
        """RF-008-26: los tres ámbitos de «Recalcular lo obsoleto»: todo; lo que tiene una
        causa («lo que depende de un cambio»: cambió Producción); y lo que necesita un
        elemento (un dato o una operación) para quedar al día, con lo obsoleto aguas arriba,
        en orden. Lo que no está obsoleto o no está en el ámbito no se recalcula."""
        a, b, c, d = self.chain()
        e = self.run_op("res.step_d", {"res_e": [9.0]})
        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        k = self.run_op("res.step_b", {"res_k": [8.0]}, reads=["res_im1", "res_b"])
        self.change("res.production", 120000.0)
        self.change("res.density", 2.6)
        self.write(lambda conn: inputs.discard(conn, self.project, INPUT_1, "entrega anulada"))
        production, density = self.changed("res.production"), self.changed("res.density")
        discarded = Cause(CauseKind.INPUT_DISCARDED, INPUT_1)

        plan = self.plan(ALL)
        self.assertEqual(plan.scope, ALL)
        self.assertEqual(self.units(plan), [(a.uid,), (b.uid,), (c.uid,), (d.uid,), (k.uid,)])
        self.assertEqual(self.units(self.plan()), self.units(plan))

        by_cause = {production: [(a.uid,), (b.uid,), (c.uid,), (k.uid,)],
                    density: [(d.uid,)], discarded: [(k.uid,)],
                    Cause(CauseKind.ALGORITHM, "res.step_a"): []}
        for cause, expected in by_cause.items():
            with self.subTest(cause=cause):
                found = self.plan(cause)
                self.assertEqual(found.scope, cause)
                self.assertEqual(self.units(found), expected)

        by_item = {self.dataset("res_b"): [(a.uid,), (b.uid,)], c.uid: [(a.uid,), (b.uid,),
                                                                         (c.uid,)],
                   self.dataset("res_d"): [(d.uid,)], k.uid: [(a.uid,), (b.uid,), (k.uid,)],
                   e.uid: [], self.dataset("res_e"): [], self.dataset("res_im1"): []}
        for item, expected in by_item.items():
            with self.subTest(item=item):
                found = self.plan(item)
                self.assertEqual(found.scope, item)
                self.assertEqual(self.units(found), expected)

        for wrong in ("00000000-0000-4000-8000-0000000003ff", ""):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.plan(wrong)
        for wrong in (None, 3, CauseKind.ALGORITHM, ("res.step_a",)):
            with self.subTest(wrong=wrong), self.assertRaises(TypeError):
                with self.project.read() as conn:
                    recompute.plan_recompute(graph_mod.load_graph(conn), scope=wrong)

    def test_public_api(self) -> None:
        """RF-008-26 (plan §5.3.1): ``core.provenance`` reexporta el plan al usarlo, sin
        cargarlo al importarse."""
        for name in provenance.RECOMPUTE_API:
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIs(getattr(provenance, name), getattr(recompute, name))
        self.assertLessEqual({"plan_recompute", "RecomputePlan", "RecomputeUnit", "Skipped",
                              "SkipReason", "SCOPE_ALL"}, set(provenance.RECOMPUTE_API))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                with self.subTest(line=node.lineno):
                    self.assertNotIn("recompute", [alias.name for alias in node.names])


# --- Ejecutar el plan (T29) ---------------------------------------------------------------------

_RUNNING: list[Any] = []
"""La prueba en curso de ``RunCase``: la que rehace las operaciones de los tipos ``res.redo_*``
y ``res.duo_*``."""


def _redo(request: Any) -> Any:
    """La función de recálculo de los tipos de prueba que se recalculan: la de la prueba en
    curso (``RunCase.redo``)."""
    if not _RUNNING:
        raise AssertionError("ninguna prueba recalcula ahora")
    return _RUNNING[-1].redo(request)


def _redo_op(op_type: str, *, group: str | None = None) -> Any:
    return provenance.OperationDef(op_type, "1.0", "res", f"Test {op_type}", True, group=group,
                                   recompute=_redo)


RUN_DECLARATIONS = (
    _redo_op("res.redo_a"),
    _redo_op("res.redo_b"),
    _redo_op("res.redo_c"),
    _redo_op("res.duo_first", group="res.duo"),
    _redo_op("res.duo_second", group="res.duo"),
    provenance.CoupledGroupDef("res.duo", ("res.duo_first", "res.duo_second")),
)
RIGHT_REASON = "La digitalización sigue valiendo sobre el terreno nuevo"
INPUT_3 = "00000000-0000-4000-8000-0000000002e3"


class RunCase(RecomputeCase):
    """``RecomputeCase`` con tipos que se recalculan de verdad (``res.redo_a``, ``_b`` y ``_c``
    y el grupo ``res.duo``): su recálculo rehace las tablas que escribió la operación con los
    valores de ``self.values`` (sin ellos, las deja como están: el mismo contenido), antes de
    lo cual ejecuta el gancho de ``self.hooks``; falla con las de ``self.broken``, deja «en
    curso», como un trabajo, las de ``self.deferred`` (que guarda cómo terminarlas; su
    operación, en ``self.jobs``) y hace lo que dice ``self.misbehave`` («nothing»: no devuelve
    la operación; «unrelated»: una que no sustituye a la antigua)."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(*RUN_DECLARATIONS, *contract.CORE_OPERATIONS))
        _RUNNING.append(self)
        self.addCleanup(_RUNNING.remove, self)
        self.values: dict[str, list[float]] = {}
        self.requests: list[Any] = []
        self.hooks: dict[str, Callable[[], None]] = {}
        self.broken: set[str] = set()
        self.deferred: dict[str, Callable[[], None] | None] = {}
        self.jobs: dict[str, Any] = {}
        self.misbehave: dict[str, str] = {}

    def written(self, op_uid: str) -> list[str]:
        """Los nombres de los datos que escribió la operación ``op_uid``."""
        rows = self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' ORDER BY io.fid", (op_uid,))
        return [str(row[0]) for row in rows]

    def redo(self, request: Any) -> Any:
        self.requests.append(request)
        hook = self.hooks.pop(request.operation_uid, None)
        if hook is not None:
            hook()
        names = self.written(request.operation_uid)
        wrong = self.misbehave.get(request.operation_uid)
        if wrong == "nothing":
            return None
        if wrong == "unrelated":
            handle = operations.begin_operation(self.project, request.op_type, settings={},
                                                executor="blender")
            self.finish(handle, [])
            return handle
        if request.operation_uid in self.deferred:  # un trabajo de la 004: termina después
            handle = request.begin()
            self.deferred[request.operation_uid] = lambda: self.finish(handle, names)
            self.jobs[request.operation_uid] = handle
            return handle
        with request.operation() as handle:
            if request.operation_uid in self.broken:
                raise RuntimeError("fallo de prueba al recalcular")
            self.finish(handle, names)
        return handle

    def finish(self, handle: Any, names: list[str]) -> None:
        def work(conn: sqlite3.Connection) -> None:
            for name in names:
                if name in self.values:
                    _replace_table(conn, name, self.values[name])
            handle.complete(conn, outputs=[_spec(name) for name in names])

        self.write(work)
        self.tick()

    def steps(self, **kw: Any) -> Iterator[Any]:
        return recompute.recompute_steps(self.project, **kw)

    def run_all(self, **kw: Any) -> tuple[Any, list[Any]]:
        """Todo el recálculo de una vez: su resultado y sus pasos."""
        progress = list(self.steps(**kw))
        outcome = progress[-1].result
        self.assertIsInstance(outcome, recompute.RecomputeOutcome)
        self.assertTrue(all(step.result is None for step in progress[:-1]))
        return outcome, progress

    def results(self, outcome: Any) -> list[tuple[tuple[str, ...], Any]]:
        return [(result.unit.operations, result.status) for result in outcome.results]

    def replaced(self, outcome: Any) -> dict[str, str]:
        """La operación nueva de cada antigua recalculada."""
        return {old: new for result in outcome.results
                for old, new in zip(result.unit.operations, result.operations, strict=False)}

    def column(self, sql: str, *args: Any) -> list[Any]:
        return [row[0] for row in self.query(sql, args)]

    def accept(self, uid: str, reason: str = RIGHT_REASON) -> str:
        return recompute.accept_review(self.project, uid, reason)


DONE = recompute.UnitStatus.DONE
REFUSED = recompute.UnitStatus.REFUSED
FAILED = recompute.UnitStatus.FAILED


class RunTest(RunCase):
    def test_recompute_supersedes_with_new_operations(self) -> None:
        """RF-008-26, RF-008-25 (plan §5.4.4): «Recalcular lo obsoleto» ejecuta las unidades
        del plan en orden de dependencia con la función de recálculo de su tipo, con las
        entradas y los parámetros vigentes y los mismos ajustes: operaciones nuevas que
        sustituyen a las anteriores, que quedan hechas, como historia; las de un grupo
        acoplado, juntas, en el orden del grupo y en otra ejecución del grupo. Al acabar no
        queda nada obsoleto (la caché coincide con lo deducido) y el progreso cuenta las
        unidades."""
        a = self.run_op("res.redo_a", {"res_a": [1.0, 2.0]}, params=["res.production"],
                        settings={"metodo": "media"})
        b = self.run_op("res.redo_b", {"res_b": [3.0]}, reads=["res_a"])
        c = self.run_op("res.redo_c", {"res_c": [4.0]}, reads=["res_b"])
        second = self.run_op("res.duo_second", {"res_d2": [5.0]}, params=["res.density"])
        first = self.run_op("res.duo_first", {"res_d1": [6.0]}, reads=["res_c"],
                            group_uid=second.group_uid)
        before_b = self.column("SELECT content_sha256 FROM gb_operation_io WHERE "
                               "operation_uid = ? AND direction = 'in'", b.uid)
        self.change("res.production", 120000.0)
        self.change("res.density", 2.7)
        self.values = {"res_a": [1.2, 2.4], "res_b": [3.6], "res_c": [4.8], "res_d1": [7.2],
                       "res_d2": [6.0]}

        outcome, progress = self.run_all()
        pair = (first.uid, second.uid)
        self.assertEqual(self.results(outcome), [((a.uid,), DONE), ((b.uid,), DONE),
                                                 ((c.uid,), DONE), (pair, DONE)])
        self.assertEqual([result.reason for result in outcome.results], [None] * 4)
        self.assertFalse(outcome.cancelled)
        self.assertEqual((outcome.remaining.units, outcome.remaining.skipped), ((), ()))
        self.assertNothingStale(self.stale())
        self.assertEqual(stale_mod.counts(self.project).obsolete, 0)
        new = self.replaced(outcome)
        self.assertEqual(set(new), {a.uid, b.uid, c.uid, *pair})
        for old, fresh in new.items():
            with self.subTest(old=old):
                old_row, new_row = self.row(old), self.row(fresh)
                self.assertEqual((old_row["status"], old_row["superseded_by"]), ("done", fresh))
                self.assertEqual(
                    (new_row["status"], new_row["supersedes_uid"], new_row["superseded_by"],
                     new_row["op_type"], new_row["settings"]),
                    ("done", old, None, old_row["op_type"], old_row["settings"]),
                )
        self.assertEqual(self.row(new[a.uid])["settings"], '{"metodo":"media"}')
        # Con las entradas y los parámetros vigentes (lo pide cada función por su petición).
        by_old = {request.operation_uid: request for request in self.requests}
        self.assertEqual((by_old[a.uid].op_type, by_old[a.uid].params, by_old[a.uid].inputs,
                          dict(by_old[a.uid].settings)),
                         ("res.redo_a", ("res.production",), (), {"metodo": "media"}))
        self.assertEqual(by_old[b.uid].inputs, (Use(self.dataset("res_a"), "source"),))
        self.assertEqual(
            self.column("SELECT value FROM gb_operation_param WHERE operation_uid = ?",
                        new[a.uid]),
            self.column("SELECT value FROM gb_parameter WHERE key = 'res.production'"),
        )
        consumed = self.column("SELECT content_sha256 FROM gb_operation_io WHERE "
                               "operation_uid = ? AND direction = 'in'", new[b.uid])
        self.assertEqual(consumed, [self.content_of("res_a")[0]])
        self.assertNotEqual(consumed, before_b)
        # El grupo, junto y en su orden, en otra ejecución.
        one, two = self.row(new[first.uid]), self.row(new[second.uid])
        self.assertEqual(one["group_uid"], two["group_uid"])
        self.assertNotEqual(one["group_uid"], second.group_uid)
        self.assertLess(one["fid"], two["fid"])
        self.assertEqual(by_old[first.uid].group_uid, one["group_uid"])
        self.assertEqual([(step.done, step.total) for step in progress],
                         [(0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (4, 4)])
        self.assertEqual({step.phase for step in progress}, {recompute.RECOMPUTE_PHASE})
        # Ya no hay nada que recalcular.
        again, steps = self.run_all()
        self.assertEqual((again.results, again.remaining.units), ((), ()))
        self.assertEqual([(step.done, step.total) for step in steps], [(0, 0), (0, 0)])

    def test_same_content_clears_what_depended_only_on_it(self) -> None:
        """RF-008-26 (spec §8): el recálculo que da el mismo contenido quita la marca de lo que
        dependía solo de él sin recalcularlo; lo que además depende de otro cambio se
        recalcula. Por elemento, solo lo que el elemento necesita."""
        a = self.run_op("res.redo_a", {"res_a": [1.0]}, params=["res.production"])
        b = self.run_op("res.redo_b", {"res_b": [2.0]}, reads=["res_a"])
        c = self.run_op("res.redo_c", {"res_c": [3.0]}, reads=["res_b"])
        e = self.run_op("res.redo_c", {"res_e": [4.0]}, reads=["res_a"],
                        params=["res.density"])
        self.change("res.production", 90000.0)
        self.change("res.density", 2.4)
        self.assertEqual(self.units(self.plan()), [(a.uid,), (b.uid,), (c.uid,), (e.uid,)])

        outcome, progress = self.run_all(scope=self.dataset("res_b"))  # a y b, no e
        self.assertEqual(self.results(outcome), [((a.uid,), DONE)])  # b ya no lo necesita
        self.assertEqual([request.operation_uid for request in self.requests], [a.uid])
        self.assertIsNone(self.row(b.uid)["superseded_by"])
        self.assertIsNone(self.row(c.uid)["superseded_by"])
        self.assertEqual([(step.done, step.total) for step in progress],
                         [(0, 2), (1, 2), (1, 1)])
        self.assertEqual(self.units(outcome.remaining), [])
        self.assertStale(self.stale(), {e: {self.changed("res.density")}},
                         {"res_e": {self.changed("res.density")}})

        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((e.uid,), DONE)])
        self.assertNothingStale(self.stale())

    def test_cancel_between_units_keeps_what_is_done(self) -> None:
        """RF-008-26 (spec §8): cancelar a mitad para al acabar la unidad en curso (la que
        espera a su trabajo no se interrumpe) y deja lo ya recalculado; lo demás sigue
        obsoleto, en lo que queda por recalcular."""
        a = self.run_op("res.redo_a", {"res_a": [1.0]}, params=["res.production"])
        b = self.run_op("res.redo_b", {"res_b": [2.0]}, reads=["res_a"])
        c = self.run_op("res.redo_c", {"res_c": [3.0]}, reads=["res_b"])
        self.change("res.production", 110000.0)
        self.values = {"res_a": [1.1], "res_b": [2.2], "res_c": [3.3]}
        cancel: list[bool] = []
        self.deferred[a.uid] = None
        steps = self.steps(cancelled=lambda: bool(cancel))
        start = next(steps)
        self.assertEqual((start.done, start.total, start.result), (0, 3, None))
        waiting = next(steps)  # el trabajo de a sigue en curso
        (running,) = self.column("SELECT uid FROM gb_operation WHERE supersedes_uid = ?", a.uid)
        self.assertEqual(self.status(running), "running")
        self.assertEqual((waiting.done, waiting.total, waiting.result), (0, 3, None))
        self.assertIn("res.redo_a", waiting.message)
        cancel.append(True)
        self.assertIsNone(next(steps).result)  # sigue esperando: no se interrumpe
        finish = self.deferred[a.uid]
        assert finish is not None
        finish()
        rest = list(steps)
        outcome = rest[-1].result
        self.assertTrue(outcome.cancelled)
        self.assertEqual(self.results(outcome), [((a.uid,), DONE)])
        self.assertEqual(self.replaced(outcome), {a.uid: running})
        self.assertEqual(self.row(a.uid)["superseded_by"], running)
        self.assertEqual(self.units(outcome.remaining), [(b.uid,), (c.uid,)])
        self.assertEqual(stale_mod.counts(self.project).obsolete, 2)  # res_b y res_c
        self.stale()  # la caché, al día

        cancel.clear()
        steps = self.steps(cancelled=lambda: bool(cancel))
        self.assertEqual(next(steps).total, 2)
        self.assertEqual((next(steps).done, len(self.requests)), (1, 2))  # b, ya hecha
        cancel.append(True)
        (last,) = list(steps)
        self.assertTrue(last.result.cancelled)
        self.assertEqual(self.results(last.result), [((b.uid,), DONE)])
        self.assertIsNotNone(self.row(b.uid)["superseded_by"])
        self.assertIsNone(self.row(c.uid)["superseded_by"])
        self.assertEqual(self.units(last.result.remaining), [(c.uid,)])

        # Un trabajo cancelado (o fallido) deja la unidad fallida, con su motivo.
        self.deferred[c.uid] = None
        steps = self.steps()
        self.assertEqual([next(steps).done, next(steps).done], [0, 0])  # empieza y espera
        self.jobs[c.uid].cancel("la persona canceló el trabajo")
        outcome = list(steps)[-1].result
        self.assertFalse(outcome.cancelled)
        self.assertEqual(self.results(outcome), [((c.uid,), FAILED)])
        self.assertEqual(outcome.results[0].reason, "No se pudo recalcular la operación "
                                                    "«res.redo_c»: la persona canceló el trabajo")
        self.assertIsNone(self.row(c.uid)["superseded_by"])
        self.assertEqual(self.units(outcome.remaining), [(c.uid,)])

    def test_parameter_changed_while_running(self) -> None:
        """RF-008-26 (spec §8): un parámetro que cambia mientras corre «Recalcular lo
        obsoleto» deja obsoleto otra vez lo ya recalculado que lo leía, que queda (cada
        operación es completa) y no se vuelve a recalcular en la misma ejecución, ni lo de
        aguas abajo; pedirlo otra vez lo recalcula."""
        a = self.run_op("res.redo_a", {"res_a": [1.0]}, params=["res.production"])
        b = self.run_op("res.redo_b", {"res_b": [2.0]}, reads=["res_a"])
        self.change("res.production", 120000.0)
        self.values = {"res_a": [1.2], "res_b": [2.4]}
        self.hooks[b.uid] = lambda: self.change("res.production", 130000.0)
        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((a.uid,), DONE), ((b.uid,), DONE)])
        new = self.replaced(outcome)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.units(outcome.remaining), [(new[a.uid],), (new[b.uid],)])
        self.assertEqual(set(self.stale().operations), {new[a.uid], new[b.uid]})
        outcome, _progress = self.run_all()  # a da el mismo contenido: b queda al día
        self.assertEqual(self.results(outcome), [((new[a.uid],), DONE)])
        self.assertNothingStale(self.stale())

    def test_recompute_function_contract(self) -> None:
        """RF-008-26 (plan §5.4.4): la función de recálculo devuelve la operación nueva, que
        sustituye a la que se recalcula; si no, es un error del programa."""
        a = self.run_op("res.redo_a", {"res_a": [1.0]}, params=["res.production"])
        self.change("res.production", 120000.0)
        self.misbehave[a.uid] = "nothing"
        with self.assertRaises(TypeError):
            self.run_all()
        self.misbehave[a.uid] = "unrelated"
        with self.assertRaises(ValueError):
            self.run_all()
        del self.misbehave[a.uid]
        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((a.uid,), DONE)])

    def test_unit_whose_input_changed_at_start_is_not_run(self) -> None:
        """RF-008-26, RF-008-10 (spec §8): al empezar cada unidad se comprueba que sus entradas
        siguen vigentes: la que encuentra cambiada una entrada aguas arriba no se ejecuta y
        sigue obsoleta, con el motivo, y lo que depende de ella espera; las demás siguen, con
        el parámetro que cambió mientras corría. Una que falla queda fallida, con su motivo, y
        la anterior sigue vigente y obsoleta."""
        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        d = self.run_op("res.redo_c", {"res_d": [5.0]}, params=["res.density"])
        a = self.run_op("res.redo_a", {"res_a": [1.0]}, reads=["res_im1"],
                        params=["res.production"])
        b = self.run_op("res.redo_b", {"res_b": [2.0]}, reads=["res_a"])
        f = self.run_op("res.redo_b", {"res_f": [3.0]}, params=["res.production"])
        g = self.run_op("res.redo_c", {"res_g": [4.0]}, params=["res.density"])
        self.run_op("res.redo_c", {"res_m": [6.0]}, reads=["res_im1"])  # al día
        w = self.run_op("res.redo_a", {"res_w": [7.0]}, reads=["res_m"], params=["res.density"])
        p = self.run_op("res.redo_b", {"res_p": [8.0]}, params=["res.density"],
                        reads=[Use("Entrada_1", "delivery", kind=ItemKind.INPUT)])
        self.change("res.production", 120000.0)
        self.change("res.density", 2.6)
        self.values = {"res_d": [5.5], "res_a": [1.5], "res_b": [2.5], "res_f": [3.5],
                       "res_g": [4.5], "res_w": [7.5], "res_p": [8.5]}

        def meanwhile() -> None:  # mientras se recalcula d
            self.mark_changed(INPUT_1)
            self.change("res.production", 130000.0)

        self.hooks[d.uid] = meanwhile
        self.broken = {g.uid}
        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((d.uid,), DONE), ((a.uid,), REFUSED),
                                                 ((f.uid,), DONE), ((g.uid,), FAILED),
                                                 ((w.uid,), REFUSED), ((p.uid,), REFUSED)])
        self.assertEqual({result.reason for result in outcome.results[4:]},
                         {outcome.results[1].reason})
        refused, failed = outcome.results[1], outcome.results[3]
        self.assertEqual(refused.operations, ())
        self.assertEqual(
            refused.reason,
            "No se recalcula: la entrada «Entrada_1» ha cambiado y no se ha decidido si "
            "actualizarla o mantener la copia.",
        )
        self.assertEqual(
            refused.text(language="en"),
            "Not recomputed: input «Entrada_1» has changed and it has not been decided whether "
            "to update it or keep the copy.",
        )
        self.assertEqual(failed.operations, ())
        self.assertEqual(failed.reason, "No se pudo recalcular la operación «res.redo_c»: "
                                         "RuntimeError: fallo de prueba al recalcular")
        self.assertEqual(self.column("SELECT status FROM gb_operation WHERE supersedes_uid = ?",
                                     g.uid), ["failed"])
        self.assertEqual([request.operation_uid for request in self.requests],
                         [d.uid, f.uid, g.uid])
        for old in (a.uid, b.uid, g.uid):
            self.assertIsNone(self.row(old)["superseded_by"])
        new_f = self.replaced(outcome)[f.uid]
        self.assertEqual(
            self.column("SELECT value FROM gb_operation_param WHERE operation_uid = ?", new_f),
            self.column("SELECT value FROM gb_parameter WHERE key = 'res.production'"),
        )
        self.assertEqual(self.store.get("res.production").value, 130000.0)
        self.assertEqual(self.units(outcome.remaining),
                         [(a.uid,), (b.uid,), (g.uid,), (w.uid,), (p.uid,)])
        state = self.stale()
        self.assertLessEqual({a.uid, b.uid, g.uid, w.uid, p.uid}, set(state.operations))
        self.assertNotIn(d.uid, state.operations)

        # Decidido mantener la copia, la entrada ya no impide recalcular.
        self.write(lambda conn: inputs.keep_copy(conn, self.project, INPUT_1,
                                                 reason="Seguimos con la copia"))
        self.broken.clear()
        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((a.uid,), DONE), ((b.uid,), DONE),
                                                 ((g.uid,), DONE), ((w.uid,), DONE),
                                                 ((p.uid,), DONE)])
        self.assertNothingStale(self.stale())

    def test_dataset_unusable_or_without_successor(self) -> None:
        """RF-008-26, RF-008-57 (spec §8): una unidad que consume un dato que falta, bloqueado
        o dañado, o uno descartado sin sucesor, no se ejecuta y sigue obsoleta; un dato o una
        entrada sustituidos se consumen en su sucesor."""
        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        source = self.import_input(INPUT_2, "Entrada_2", "res_im2")
        self.run_op("res.redo_a", {"res_a": [1.0]})
        self.run_op("res.redo_a", {"res_a2": [1.5]})
        self.run_op("res.redo_a", {"res_m": [2.0]})
        b = self.run_op("res.redo_b", {"res_b": [2.0]}, reads=["res_a"],
                        params=["res.density"])
        n = self.run_op("res.redo_b", {"res_n": [3.0]}, reads=["res_m"],
                        params=["res.density"])
        k = self.run_op("res.redo_c", {"res_k": [4.0]}, reads=["res_im1"],
                        params=["res.density"])
        q = self.run_op("res.redo_c", {"res_q": [5.0]},
                        reads=[Use("Entrada_2", "delivery", kind=ItemKind.INPUT)])
        self.change("res.density", 2.8)
        old_a, new_a = self.dataset("res_a"), self.dataset("res_a2")
        self.write(lambda conn: dataset_registry.supersede(conn, self.project, old_a,
                                                           by=new_a))
        self.set_status("res_m", "missing")
        self.write(lambda conn: inputs.discard(conn, self.project, INPUT_1, "entrega anulada"))

        def update(conn: sqlite3.Connection) -> None:  # la entrega nueva sustituye a la 2
            conn.execute("UPDATE gb_input SET status = 'superseded' WHERE uid = ?", (INPUT_2,))
            _insert(conn, "gb_input", input_row(uid=INPUT_3, name="Entrada_2",
                                                operation_uid=source.uid, previous_uid=INPUT_2))

        self.write(update)
        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((b.uid,), DONE), ((n.uid,), REFUSED),
                                                 ((k.uid,), REFUSED), ((q.uid,), DONE)])
        self.assertEqual([result.reason for result in outcome.results], [
            None,
            "No se recalcula: el dato «res_m» que consume falta, está bloqueado o dañado.",
            "No se recalcula: «res_im1», que consumía, se descartó y no tiene sucesor.",
            None,
        ])
        self.assertEqual([request.inputs for request in self.requests],
                         [(Use(new_a, "source"),),
                          (Use(INPUT_3, "delivery", kind=ItemKind.INPUT),)])
        self.assertEqual(self.units(outcome.remaining), [(n.uid,), (k.uid,)])


class AcceptReviewTest(RunCase):
    def test_accept_review_lifts_the_wait_downstream(self) -> None:
        """RF-008-27 (D-12; plan §5.4.4, D8): «dar por buena» con motivo una operación que
        espera revisión a mano es una operación nueva ``core.accept_review`` que consume lo
        vigente de lo que consumía, «produce» las mismas versiones (el mismo contenido y la
        cifra vigente) y la sustituye, con su evento; lo de aguas abajo deja de esperar.
        Mientras lo que consume siga obsoleto, no se puede."""
        a = self.run_op("res.redo_a", {"res_a": [1.0]}, params=["res.production"])
        r = self.run_op("res.digitize", {"res_r": [2.0]}, reads=["res_a"], figure=1.0)
        x = self.run_op("res.redo_b", {"res_x": [3.0]}, reads=["res_r"],
                        params=["res.density"])
        y = self.run_op("res.redo_c", {"res_y": [4.0]}, reads=["res_x"])
        s = self.run_op("res.digitize", reads=["res_a"], figure=3.0)
        self.change("res.production", 80000.0)
        self.change("res.density", 2.4)
        self.values = {"res_a": [0.8], "res_x": [3.5], "res_y": [4.5]}
        error = self.assertRejected(ProvenanceError, "core.accept_review_upstream",
                                    lambda: self.accept(r.uid))
        self.assertEqual(str(error), "La operación «res.digitize» aún no se puede dar por "
                                     "buena: lo que consume sigue obsoleto («res_a»); "
                                     "recalcúlelo o revíselo antes.")

        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((a.uid,), DONE)])
        self.assertEqual(self.reasons(outcome.remaining), {
            r.uid: (SkipReason.REVIEW, ()), x.uid: (SkipReason.WAITS, (r.uid,)),
            y.uid: (SkipReason.WAITS, (r.uid,)), s.uid: (SkipReason.REVIEW, ()),
        })
        produced = self.content_of("res_r")[0]
        uid = self.accept(r.uid, f"  {RIGHT_REASON}  ")
        row = self.row(uid)
        self.assertEqual((row["op_type"], row["status"], row["supersedes_uid"], row["repeatable"]),
                         ("core.accept_review", "done", r.uid, 0))
        self.assertEqual(json.loads(row["settings"]), {"accepted": r.uid,
                                                      "reason": RIGHT_REASON})
        self.assertEqual(self.row(r.uid)["superseded_by"], uid)
        self.assertEqual(
            self.query("SELECT direction, item_uid, content_sha256 FROM gb_operation_io "
                       "WHERE operation_uid = ? ORDER BY fid", (uid,)),
            [("in", self.dataset("res_a"), self.content_of("res_a")[0]),
             ("out", self.dataset("res_r"), produced)],
        )
        self.assertEqual(self.content_of("res_r")[0], produced)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_figure WHERE operation_uid = ?",
                                    (uid,)), [(0,)])  # su cifra ya no es la vigente: la de s
        (event,) = self.logged(events.EventKind.REVIEW_ACCEPTED)
        self.assertEqual((event.entity_uid, event.data["accepted_by"], event.data["reason"],
                          event.data["op_type"]),
                         (r.uid, uid, RIGHT_REASON, "res.digitize"))
        self.assertIn(RIGHT_REASON, event.message)
        # Lo de aguas abajo ya no espera: se recalcula.
        plan = self.plan()
        self.assertEqual(self.units(plan), [(x.uid,), (y.uid,)])
        self.assertEqual(self.reasons(plan), {s.uid: (SkipReason.REVIEW, ())})
        figure = self.accept(s.uid)
        self.assertEqual(self.query("SELECT key, value FROM gb_figure WHERE operation_uid = ?",
                                    (figure,)), [("res.marks", 3.0)])
        state = self.stale()
        self.assertIn(("res.marks", ""), state.current_figures)
        (current,) = self.column("SELECT operation_uid FROM gb_figure WHERE uid = ?",
                                 state.current_figures[("res.marks", "")])
        self.assertEqual(current, figure)
        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((x.uid,), DONE), ((y.uid,), DONE)])
        self.assertNothingStale(self.stale())
        self.assertEqual(stale_mod.counts(self.project).obsolete, 0)

    def test_accept_own_edit_and_refusals(self) -> None:
        """RF-008-27: una edición a mano dada por buena no consume lo que editó (es lo que se
        da por bueno) y lo que la leía deja de esperar. No se da por buena, sin escribir nada,
        una operación que no espera revisión, sin motivo, una que escribió lo importado de
        una entrada (se reimporta), una cuyo dato falta o cuyo contenido ya no es el que
        escribió; ni en solo lectura."""
        a = self.run_op("res.redo_a", {"res_a": [1.0, 2.0]}, params=["res.production"])
        b = self.run_op("res.redo_b", {"res_b": [3.0]}, reads=["res_a"])
        e = self.run_op("res.edit", {"res_a": [1.0, 9.0]}, reads=["res_a"])
        self.change("res.production", 90000.0)
        self.assertEqual(self.reasons(self.plan()), {e.uid: (SkipReason.REVIEW, ()),
                                                     b.uid: (SkipReason.WAITS, (e.uid,))})
        for wrong, code in ((b.uid, "core.accept_review_not_review"),
                            (a.uid, "core.accept_review_not_review"),
                            ("00000000-0000-4000-8000-0000000003ff", "core.operation_unknown")):
            with self.subTest(wrong=wrong):
                self.assertRejected(ProvenanceError, code, lambda wrong=wrong: self.accept(wrong))
        error = self.assertRejected(ProvenanceError, "core.accept_review_reason_missing",
                                    lambda: self.accept(e.uid, "  "))
        self.assertEqual(str(error), "Falta el motivo: dar por buena la operación «res.edit» "
                                     "queda registrado con él.")
        self.assertRejected(TypeError, None, lambda: self.accept(e.uid, None))  # type: ignore
        edited = self.content_of("res_a")[0]
        uid = self.accept(e.uid)
        self.assertEqual(
            self.query("SELECT direction, item_uid, content_sha256 FROM gb_operation_io "
                       "WHERE operation_uid = ?", (uid,)),
            [("out", self.dataset("res_a"), edited)],
        )
        self.assertEqual(self.units(self.plan()), [(b.uid,)])
        outcome, _progress = self.run_all()
        self.assertEqual(self.results(outcome), [((b.uid,), DONE)])

        # Una que no se da por buena: sus datos faltan o cambiaron, o es lo importado.
        self.run_op("res.redo_c", {"res_o": [1.0]})
        self.run_op("res.redo_c", {"res_o2": [2.0]})
        r = self.run_op("res.digitize", {"res_r": [5.0]}, reads=["res_o"],
                        params=["res.density"])
        self.change("res.density", 2.2)
        old_o, new_o = self.dataset("res_o"), self.dataset("res_o2")
        self.write(lambda conn: dataset_registry.supersede(conn, self.project, old_o,
                                                           by=new_o))
        self.assertEqual(self.reasons(self.plan(r.uid)), {r.uid: (SkipReason.REVIEW, ())})
        self.write(lambda conn: conn.execute("UPDATE res_r SET valor = 6.0"))
        error = self.assertRejected(ProvenanceError, "core.accept_review_changed",
                                    lambda: self.accept(r.uid))
        self.assertEqual(str(error), "El dato «res_r» ya no es el que escribió la operación "
                                     "«res.digitize»: compruebe los datos del proyecto antes de "
                                     "darla por buena.")
        self.write(lambda conn: conn.execute("UPDATE res_r SET valor = 5.0"))
        self.set_status("res_r", "missing")
        self.assertRejected(ProvenanceError, "core.accept_review_output",
                            lambda: self.accept(r.uid))
        self.set_status("res_r", "current")
        imported = self.import_input(INPUT_1, "Entrada_1", "res_im1").uid
        contract.unregister_operation("res.import_source")
        contract.register_operation(_op("res.import_source", "1.1", repeatable=False))
        error = self.assertRejected(ProvenanceError, "core.accept_review_imported",
                                    lambda: self.accept(imported))
        self.assertEqual(str(error), "La operación «res.import_source» escribió lo importado de "
                                     "la entrada «Entrada_1»: no se da por buena; actualice o "
                                     "reimporte la entrada.")
        uid = self.accept(r.uid)
        self.assertEqual(self.row(r.uid)["superseded_by"], uid)
        self.assertEqual(self.column("SELECT item_uid FROM gb_operation_io WHERE "
                                     "operation_uid = ? AND direction = 'in'", uid), [new_o])
        self.assertEqual(self.column("SELECT key FROM gb_operation_param WHERE "
                                     "operation_uid = ?", uid), ["res.density"])

        self.project.set_read_only(project_model.ReadOnlyCode.LOCK_LOST, "prueba")
        for work in (lambda: self.accept(e.uid), lambda: self.steps()):
            with self.assertRaises(ProvenanceError) as caught:
                work()
            self.assertEqual(caught.exception.code, "core.read_only")

    def test_public_api(self) -> None:
        """RF-008-26, RF-008-27 (plan §5.3.1): ``core.provenance`` reexporta al usarlo la
        ejecución del plan y «dar por buena»; ``begin_in_transaction`` registra una operación
        en la transacción de quien llama."""
        self.assertLessEqual({"recompute_steps", "accept_review", "RecomputeRequest",
                              "RecomputeOutcome", "UnitResult", "UnitStatus",
                              "RECOMPUTE_PHASE"}, set(provenance.RECOMPUTE_API))
        for name in (*provenance.RECOMPUTE_API, *provenance.OPERATIONS_API):
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
        self.assertIs(provenance.accept_review, recompute.accept_review)
        self.assertIs(provenance.begin_in_transaction, operations.begin_in_transaction)
        self.assertEqual(events.EventKind.REVIEW_ACCEPTED.value, "review_accepted")
        with self.project.read() as conn, self.assertRaises(ValueError):
            operations.begin_in_transaction(conn, self.project, "res.redo_a", settings={},
                                            executor="blender")

# --- Grafos aleatorios ----------------------------------------------------------------------------

_INSTALLED_CASES = (
    {"res.t0": "1.1", "res.t1": "1.0", "res.t2": "1.0", "res.manual": "1.0"},  # todo instalado
    {"res.t0": "1.0", "res.t1": "1.0", "res.manual": "1.0"},  # t2 no; t0 1.1, más nueva
)
_BLOCKERS = (SkipReason.REVIEW, SkipReason.UNKNOWN_TYPE, SkipReason.NEWER_ALGORITHM)


def _depends(graph: Any, uid: str) -> set[str]:
    """Lo que necesita la operación ``uid`` antes de recalcularse: quien escribió las versiones
    que consumió y quien escribió el contenido actual de esos datos (sin ella)."""
    node = graph.operations[uid]
    found = set(graph.upstream(uid))
    for version in node.consumed:
        dataset = graph.datasets.get(version.uid) if version.item_kind == "dataset" else None
        if dataset is not None and dataset.operation_uid in graph.operations:
            found.add(dataset.operation_uid)
    found.discard(uid)
    return found


def _closure(graph: Any, stale: Mapping[str, Any], start: Iterable[str]) -> set[str]:
    """``start`` y lo obsoleto que necesitan aguas arriba, con sus ejecuciones de grupo."""
    pending = [uid for uid in start if uid in stale]
    seen: set[str] = set()
    while pending:
        uid = pending.pop()
        if uid in seen:
            continue
        seen.add(uid)
        pending.extend(dep for dep in _depends(graph, uid) if dep in stale)
        group_uid = graph.operations[uid].group_uid
        if group_uid is not None:
            pending.extend(other for other in graph.group(group_uid) if other in stale)
    return seen


def _reach(graph: Any, stale: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """La unidad de cada operación obsoleta y lo que necesita cada unidad, directa o
    indirectamente (dos unidades que se necesitan una a otra están en un ciclo)."""
    unit = {uid: graph.operations[uid].group_uid or uid for uid in stale}
    edges: dict[str, set[str]] = {key: set() for key in unit.values()}
    for uid in stale:
        edges[unit[uid]] |= {unit[dep] for dep in _depends(graph, uid) if dep in stale}
    reach: dict[str, set[str]] = {}
    for key in edges:
        found: set[str] = set()
        pending = list(edges[key])
        while pending:
            other = pending.pop()
            if other not in found:
                found.add(other)
                pending.extend(edges[other])
        reach[key] = found
    return unit, reach


class PlanPropertyTest(unittest.TestCase):
    def check_plan(self, graph: Any, versions: Mapping[str, str], case: int,
                   seen: dict[Any, int]) -> None:
        state = graph_mod.deduce(graph, versions=versions)
        stale = state.operations
        live = {d.operation_uid for d in graph.datasets.values() if d.live}
        relevant = {uid for uid in stale if uid in live}
        plan = recompute.plan_recompute(graph, versions=versions)
        planned = plan.operations
        skipped = {item.operation_uid: item for item in plan.skipped}
        where = f"caso {case}"

        # Cada operación una sola vez; todo lo que hay que rehacer, recalculado o con motivo.
        self.assertEqual(len(planned), len(set(planned)), where)
        self.assertFalse(set(planned) & set(skipped), where)
        self.assertLessEqual(relevant, set(planned) | set(skipped), where)
        self.assertLessEqual(set(planned) | set(skipped), set(stale), where)
        for uid in planned:
            node = graph.operations[uid]
            self.assertTrue(node.repeatable, where)
            self.assertIn(node.op_type, versions, where)
            self.assertGreaterEqual(contract.parse_version(versions[node.op_type]),
                                    contract.parse_version(node.op_version), where)
        blockers = {uid for uid, item in skipped.items() if item.reason in _BLOCKERS}
        self.assertEqual({uid for uid, item in skipped.items()
                          if item.reason is SkipReason.REVIEW}, set(state.review), where)
        for uid, item in skipped.items():
            seen[item.reason] = seen.get(item.reason, 0) + 1
            refs = {ref.uid for ref in item.waits_for}
            node = graph.operations[uid]
            if item.reason is SkipReason.UNKNOWN_TYPE:
                self.assertNotIn(node.op_type, versions, where)
            elif item.reason is SkipReason.NEWER_ALGORITHM:
                self.assertLess(contract.parse_version(versions[node.op_type]),
                                contract.parse_version(node.op_version), where)
            elif item.reason is SkipReason.GROUP:
                self.assertTrue(refs, where)
                self.assertLessEqual(refs, set(graph.group(node.group_uid)) - {uid}, where)
            elif item.reason is SkipReason.WAITS:
                self.assertTrue(refs, where)
                self.assertLessEqual(refs, blockers, where)
                self.assertLessEqual(refs, _closure(graph, stale, [uid]), where)
            self.assertEqual(item.causes, stale[uid], where)
            self.assertTrue(item.text(), where)
        # Nada de lo recalculado necesita algo que espera revisión o no se recalcula.
        for uid in planned:
            self.assertFalse(_closure(graph, stale, [uid]) & blockers, where)
        # Las ejecuciones de grupo, enteras; lo demás, de una en una.
        for unit in plan.units:
            if unit.group_uid is None:
                self.assertEqual(len(unit.operations), 1, where)
            else:
                members = {uid for uid in graph.group(unit.group_uid) if uid in stale}
                self.assertEqual(set(unit.operations), members, where)
        # Orden de dependencia; dentro de un ciclo, el de registro.
        unit, reach = _reach(graph, stale)
        position = {uid: n for n, found in enumerate(plan.units) for uid in found.operations}

        def first(key: str) -> int:
            return min(graph.operations[uid].fid for uid in stale if unit[uid] == key)

        for uid, n in position.items():
            for dep in _depends(graph, uid) & position.keys():
                mine, theirs = unit[uid], unit[dep]
                if mine == theirs:
                    continue
                if mine in reach[theirs]:  # se necesitan una a otra: un ciclo
                    seen["cycle"] = seen.get("cycle", 0) + 1
                    self.assertEqual(position[dep] < n, first(theirs) < first(mine), where)
                else:
                    seen["ordered"] = seen.get("ordered", 0) + 1
                    self.assertLess(position[dep], n, where)

        def kept(found: Any, wanted: set[str]) -> None:
            self.assertEqual(found.operations,
                             tuple(uid for uid in planned if uid in wanted), where)
            self.assertEqual({(item.operation_uid, item.reason) for item in found.skipped},
                             {(uid, item.reason) for uid, item in skipped.items()
                              if uid in wanted}, where)

        # Por causa: lo de todo que tiene esa causa, en el mismo orden; entre todas, todo.
        union: set[str] = set()
        for cause in {cause for causes in stale.values() for cause in causes}:
            found = recompute.plan_recompute(graph, scope=cause, versions=versions)
            kept(found, {uid for uid, causes in stale.items() if cause in causes})
            union |= set(found.operations)
        self.assertEqual(union, set(planned), where)
        # Por elemento: lo de todo que el elemento necesita aguas arriba, en el mismo orden.
        for uid in sorted(relevant)[:6]:
            kept(recompute.plan_recompute(graph, scope=uid, versions=versions),
                 _closure(graph, stale, [uid]))

    def test_plan_on_random_graphs(self) -> None:
        """RF-008-25, RF-008-26, RF-008-27 (plan §5.4.4): en 150 grafos aleatorios —operaciones
        repetibles y no, grupos acoplados mezclados, sustituidas, ediciones propias, versiones
        anteriores consumidas, entradas y datos que cambian de estado, tipos sin instalar y
        algoritmos más nuevos que el instalado—, cada operación que hay que rehacer está una
        vez en el plan o fuera con su motivo; lo planificado se repite solo, con un algoritmo
        instalado igual o mayor, sin nada aguas arriba que espere revisión o no se recalcule;
        las ejecuciones de grupo van enteras; el orden es el de dependencia (dentro de un
        ciclo, el de registro); y los ámbitos por causa y por elemento son la parte de «todo»
        que les toca, en el mismo orden."""
        seeds = random.Random(20261009)
        seen: dict[Any, int] = {}
        for case in range(150):
            world = RandomProject(random.Random(seeds.getrandbits(64)))
            try:
                for _ in range(world.rng.randint(6, 18)):
                    world.step()
                loaded = graph_mod.load_graph(world.conn)
            finally:
                world.conn.close()
            self.check_plan(loaded, _INSTALLED_CASES[case % 2], case, seen)
        for reason in (*SkipReason, "ordered", "cycle"):
            with self.subTest(reason=reason):
                self.assertGreater(seen.get(reason, 0), 0)


if __name__ == "__main__":
    unittest.main()
