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

Las pruebas usan el proyecto de ``test_graph`` (``GraphCase``) y, para las propiedades, sus
grafos aleatorios en memoria (``RandomProject``).
"""

from __future__ import annotations

import ast
import random
import unittest
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender
from tests.unit.core.provenance.test_graph import (
    INPUT_1,
    GraphCase,
    RandomProject,
    _op,
)

provenance = import_geoblender("core.provenance")
recompute = import_geoblender("core.provenance.recompute")
graph_mod = import_geoblender("core.provenance.graph")
contract = import_geoblender("core.provenance.contract")
inputs = import_geoblender("core.inputs")

Cause = graph_mod.Cause
CauseKind = graph_mod.CauseKind
SkipReason = recompute.SkipReason
ALL = recompute.SCOPE_ALL

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
