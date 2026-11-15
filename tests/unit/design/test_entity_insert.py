# SPDX-License-Identifier: GPL-3.0-or-later
"""Insertar una entidad antes o después de otra de su cadena (spec 015, T31; HU-015-2; RF-015-05, RF-015-04,
RF-015-16, RF-015-28, RF-008-24, RF-008-02; D-2, D-14; plan 015 §5.3.1 y §5.3.3).

- **Dónde se inserta** (sin proyecto, ``entities.insertion_point``): dada la entidad de referencia y si se inserta
  antes o después, la superficie de la que parte la nueva (``insertion_start``) y la entidad viva que hoy parte
  de ella, la **sucesora**, que pasará a partir de la nueva; sin sucesora (la de referencia es la última de su
  cadena), nada cambia. Los errores del programa y las cadenas rotas, como los de ``insert_after``.
- **Crear la insertada** (con proyecto, sobre la cantera sintética de la 014 con las capas de plataformas):
  ``Calculation.create`` aplica el cambio de la partida de la sucesora (``ParamChange`` de ``insert_after`` o
  ``insert_before``) **en la misma transacción**, con su motivo y su decisor, también cuando se inserta
  **antes** de la primera de una cadena (lo que la T13 dejó sin hacer); la sucesora y, en cascada, las que la
  siguen quedan **obsoletas** con su causa (RF-008-24); las demás, no; «Recalcular lo obsoleto» las rehace en
  orden con la superficie de la nueva; sin ``insert_before``, la misma plataforma se rechaza (de cada superficie
  parte una sola); un fallo al crear no deja ni la entidad ni el cambio.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter
from tests.unit.design import test_entities_chain as chain
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
messages = import_geoblender("design.messages")
operations = import_geoblender("core.provenance.operations")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")

GROUND, rec, ref, numbers = chain.GROUND, chain.rec, chain.ref, chain.numbers
State = entities.EntityState
LOADING, WORKSHOP = prep.LOADING, prep.WORKSHOP
WITH_AXIS, NO_AXIS = prep.WITH_AXIS, prep.NO_AXIS
START = prep.START
entity_key = design_params.entity_key


# ---------------------------------------------------------------------------------------------
# Dónde se inserta (sin proyecto)
# ---------------------------------------------------------------------------------------------


class InsertionPointTest(unittest.TestCase):
    """RF-015-05, RF-015-04: la partida de la nueva y la sucesora que pasa a partir de ella."""

    def setUp(self) -> None:
        self.records = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(2))]

    def test_after_an_entity_in_the_middle(self) -> None:
        """RF-015-05: después de P1, la nueva parte de la superficie que deja P1 y la sucesora es P2 (la que hoy
        parte de ella); por su código o por su nombre."""
        for wanted in ("PLT-001", "P1"):
            with self.subTest(ref=wanted):
                found = entities.insertion_point(self.records, wanted)
                self.assertEqual((found.reference.code, found.before, found.start, found.successor.code),
                                 ("PLT-001", False, ref(1), "PLT-002"))

    def test_before_the_first_of_the_chain_and_before_one_in_the_middle(self) -> None:
        """RF-015-05: antes de P1 (parte del terreno), la nueva parte del terreno y la sucesora es P1; antes de P2,
        parte de la superficie de P1 y la sucesora es P2 (lo mismo que después de P1)."""
        first = entities.insertion_point(self.records, "P1", before=True)
        self.assertEqual((first.before, first.start, first.successor.code), (True, GROUND, "PLT-001"))
        middle = entities.insertion_point(self.records, "P2", before=True)
        self.assertEqual((middle.start, middle.successor.code), (ref(1), "PLT-002"))
        after = entities.insertion_point(self.records, "P1")
        self.assertEqual((middle.start, middle.successor), (after.start, after.successor))

    def test_after_the_last_of_the_chain_nothing_changes(self) -> None:
        """RF-015-05: después de la última no hay sucesora: la nueva es la cola y ninguna otra cambia."""
        found = entities.insertion_point(self.records, "P3")
        self.assertEqual((found.start, found.successor), (ref(3), None))

    def test_it_is_what_insert_after_and_insert_before_change(self) -> None:
        """RF-015-05 (la misma cuenta que ``insert_after`` e ``insert_before``): la sucesora de
        ``insertion_point`` es la entidad que cambia su partida, de ``successor.start`` a la de la nueva; la
        partida de la nueva es la que pide ``insertion_start``."""
        for wanted, before in (("P1", False), ("P2", False), ("P3", False), ("P1", True), ("P2", True)):
            with self.subTest(ref=wanted, before=before):
                found = entities.insertion_point(self.records, wanted, before=before)
                self.assertEqual(found.start, entities.insertion_start(self.records, wanted, before=before))
                new = rec(9, found.start)
                insert = entities.insert_before if before else entities.insert_after
                changes = insert(self.records, wanted, new)
                if found.successor is None:
                    self.assertEqual(changes, ())
                else:
                    (change,) = changes
                    self.assertEqual((change.code, change.old, change.new),
                                     (found.successor.code, found.successor.start, ref(9)))

    def test_the_start_of_the_new_one_is_taken_by_the_successor_unless_it_is_the_last(self) -> None:
        """RF-015-04, RF-015-05: la partida de la nueva está **ocupada** por la sucesora (``start_conflict``: sin
        ``insert_before`` se rechazaría ``des.entity_start_taken``) salvo después de la última, donde está libre."""
        taken = entities.insertion_point(self.records, "P1")
        self.assertEqual(entities.start_conflict(self.records, taken.start).code, "PLT-002")
        last = entities.insertion_point(self.records, "P3")
        self.assertIsNone(entities.start_conflict(self.records, last.start))

    def test_the_program_errors(self) -> None:
        """RF-015-05: una entidad que no existe, una descartada (no tiene sitio en la cadena), antes de una sin
        partida y una referencia que no es un texto son errores del programa, sin escribir nada."""
        with self.assertRaises(ValueError):
            entities.insertion_point(self.records, "no existe")
        discarded = [rec(1, GROUND, state=State.DISCARDED)]
        with self.assertRaises(ValueError):
            entities.insertion_point(discarded, "P1")
        with self.assertRaises(ValueError):
            entities.insertion_point([rec(1, None)], "P1", before=True)
        with self.assertRaises(TypeError):
            entities.insertion_point(self.records, 5)  # type: ignore[arg-type]

    def test_a_broken_chain_is_refused(self) -> None:
        """RF-015-04: dos entidades desde la misma superficie, o un ciclo, se rechazan (se dice qué falla)."""
        taken = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(1))]
        with self.assertRaises(messages.DesignError) as caught:
            entities.insertion_point(taken, "P1")
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        loop = [rec(1, ref(2)), rec(2, ref(1))]
        with self.assertRaises(messages.DesignError) as caught:
            entities.insertion_point(loop, "P1")
        self.assertEqual(caught.exception.code, "des.entity_chain_cycle")


# ---------------------------------------------------------------------------------------------
# Crear la insertada (con proyecto)
# ---------------------------------------------------------------------------------------------


class InsertCase(ops_test.RecomputeCase):
    """V01 con P1 «Plataforma de carga» (del terreno) y P2 «Plataforma de taller» (de la superficie de P1) y,
    según la clase, P3 (un polígono con su eje, de la de P2): las hechas, con operaciones reales."""

    def records(self) -> tuple[Any, ...]:
        return entities.registry(self.project, self.v1.uid).records

    def starts(self) -> dict[str, str | None]:
        return {item.code: item.start for item in self.records()}

    def states(self) -> dict[str, str]:
        return {item.code: str(item.state) for item in self.records()}

    def parameter(self, code: str, param: str = "start") -> Any:
        found = core_params.ParameterStore(self.project).get(entity_key(code, param), version=self.v1.uid)
        assert found is not None, (code, param)
        return found

    def history(self, code: str) -> list[Any]:
        return list(core_params.ParameterStore(self.project).history(entity_key(code, "start"),
                                                                     version=self.v1.uid))

    def calculate_insertion(self, asked: Any, successor: str | None) -> Any:
        """«Calcular» ``asked`` insertándola antes de la entidad ``successor`` (sin ella, una plataforma de
        siempre); la cuenta, que se descarta al acabar la prueba."""
        self.clock.advance(minutes=1)
        calculation = self.calculate_in(asked, insert_before=successor)
        self.addCleanup(calculation.discard)
        return calculation


class InsertAfterTest(InsertCase):
    """RF-015-05, RF-015-16, RF-008-24 (después de P1 y antes de P2): en el orden de sus letras sobre el mismo
    estado."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))
        cls.made(prep.polygon_request(WITH_AXIS, start="entity:PLT-002"))

    def new(self, **changes: Any) -> Any:
        """La que se inserta: un polígono sin eje enlazado que parte de la superficie de P1."""
        return prep.polygon_request(NO_AXIS, linked=False, start="entity:PLT-001", **changes)

    def test_a_without_insert_before_the_same_surface_is_refused(self) -> None:
        """RF-015-04: sin ``insert_before``, la nueva que parte de la superficie de P1 se rechaza (de cada
        superficie parte una sola) y no se escribe nada."""
        before = self.written()
        with self.assertRaises(messages.DesignError) as caught:
            ops_test.finish(self.run_steps(self.new()))
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        self.assertEqual(self.settled(self.written()), self.settled(before))

    def test_b_the_summary_names_what_becomes_obsolete_and_calculating_writes_nothing(self) -> None:
        """RF-015-03, RF-015-05: el resumen de «Calcular» la que se inserta después de P1 lista la sucesora y las
        que la siguen (P2 y P3) y lleva lo preparado: el cambio de la partida de P2 a la superficie de la nueva,
        con su motivo; nada se escribe."""
        found = entities.insertion_point(self.records(), "PLT-001")
        before = self.written()
        calculation = self.calculate_insertion(self.new(), found.successor.code)
        self.assertEqual([(item.kind, item.name) for item in calculation.summary.obsolete],
                         [(preview.ObsoleteKind.SUCCESSOR, WORKSHOP),
                          (preview.ObsoleteKind.SUCCESSOR, WITH_AXIS)])
        (change,) = calculation.entity.insertion
        self.assertEqual((change.code, change.key, change.old, change.new),
                         ("PLT-002", entity_key("PLT-002", "start"), "entity:PLT-001", "entity:PLT-004"))
        self.assertIn(NO_AXIS, change.reason)
        self.assertIn(WORKSHOP, change.reason)
        self.assertEqual(self.settled(self.written()), self.settled(before), "calcular no escribe")

    def test_c_creating_it_re_points_the_successor_and_makes_it_and_the_next_obsolete(self) -> None:
        """RF-015-05, RF-015-16, RF-008-24, RF-008-02: crear la plataforma insertada deja P1 → N → P2 → P3: la
        partida de P2 pasa a ser la superficie de la nueva (``entity:PLT-004``), con su historial, su motivo (el
        del ``ParamChange``) y su decisor; P2 y, en cascada, P3 quedan **obsoletas** con su causa (el cambio de la
        partida de P2); P1 y la nueva, al día. Todo en una transacción: la entidad y el cambio."""
        found = entities.insertion_point(self.records(), "PLT-001")
        calculation = self.calculate_insertion(self.new(), found.successor.code)
        counter = change_counter(self.root)
        stored = calculation.create()
        self.assertEqual(change_counter(self.root), counter + 1, "una sola transacción")
        self.assertEqual(self.starts(), {"PLT-001": START, "PLT-002": "entity:PLT-004",
                                         "PLT-003": "entity:PLT-002", "PLT-004": "entity:PLT-001"})
        key = entity_key("PLT-002", "start")
        changed = self.parameter("PLT-002")
        self.assertEqual((changed.value, changed.rev, changed.decided_by),
                         ("entity:PLT-004", 2, self.project.session.user_host))
        history = self.history("PLT-002")
        self.assertEqual([item.value for item in history], ["entity:PLT-001", "entity:PLT-004"])
        self.assertEqual(history[-1].reason, calculation.entity.insertion[0].reason)
        self.assertEqual(self.states(), {"PLT-001": "current", "PLT-002": "stale", "PLT-003": "stale",
                                         "PLT-004": "current"})
        self.assertEqual(self.stale_causes(self.current("PLT-002")), {("parameter_changed", key)})
        self.assertIn(("parameter_changed", key), self.stale_causes(self.current("PLT-003")))
        self.assertEqual(self.stale_causes(self.current("PLT-001")), set())
        self.assertEqual(self.stale_causes(stored.handle.uid), set())
        self.assertIn(WORKSHOP, entities.stale_reason(self.project, self.v1.uid, "PLT-002"))
        self.assertEqual(numbers(entities.chain_of(self.records(), "PLT-001")), [1, 4, 2, 3])
        self.assertEqual(numbers(entities.chain_tails(self.records())), [3])
        self.assertEqual(len(self.recompute_plan()), 2)

    def test_d_recomputing_rebuilds_them_in_order_on_the_surface_of_the_new_one(self) -> None:
        """RF-015-05, RF-015-16, RF-008-26: «Recalcular lo obsoleto» repite P2 y después P3 (en ese orden, con la
        partida nueva: P2 lee la superficie de la insertada); al terminar todo está al día y la cadena se
        mantiene."""
        new, old = self.current("PLT-004"), (self.current("PLT-002"), self.current("PLT-003"))
        self.assertEqual(self.plan_units(), [(old[0],), (old[1],)])
        self.clock.advance(minutes=1)
        outcome = ops_test.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 2)
        self.assertEqual(set(self.states().values()), {"current"})
        newest = self.current("PLT-002")
        self.assertNotEqual(newest, old[0])
        used = {row[0] for row in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role = 'surface'", newest)}
        self.assertEqual(used, {provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, NO_AXIS)})
        self.assertEqual(self.current("PLT-004"), new, "la insertada no se recalcula")
        self.assertEqual(self.recompute_plan(), [])

    def test_e_after_the_last_of_the_chain_nothing_is_obsolete_and_nothing_else_changes(self) -> None:
        """RF-015-05: después de la última (P3) no hay sucesora: la nueva parte de su superficie sin
        ``insert_before``, se crea como siempre, no cambia la partida de ninguna otra y no queda nada obsoleto."""
        found = entities.insertion_point(self.records(), "PLT-003")
        self.assertIsNone(found.successor)
        starts = self.starts()
        calculation = self.calculate_insertion(prep.request("Carga bis", feature=LOADING, start=found.start), None)
        self.assertEqual(calculation.summary.obsolete, ())
        self.assertEqual(calculation.entity.insertion, ())
        calculation.create()
        self.assertEqual(self.starts(), {**starts, "PLT-005": "entity:PLT-003"})
        self.assertEqual(set(self.states().values()), {"current"})
        self.assertEqual(numbers(entities.chain_tails(self.records())), [5])


class InsertBeforeTest(InsertCase):
    """RF-015-05 (antes de la primera de la cadena, el caso que la T13 dejó sin hacer): P1 del terreno y P2 de su
    superficie, y se inserta N antes de P1."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))

    def test_a_before_the_first_the_new_one_starts_from_the_ground_and_the_first_from_it(self) -> None:
        """RF-015-05: antes de P1, la nueva parte del terreno y P1 pasa a partir de la superficie de la nueva (con
        su motivo); P1 y P2 quedan obsoletas por ello y la cadena es N → P1 → P2, con P2 de cola."""
        found = entities.insertion_point(self.records(), "PLT-001", before=True)
        self.assertEqual((found.start, found.successor.code), (START, "PLT-001"))
        calculation = self.calculate_insertion(
            prep.polygon_request(NO_AXIS, linked=False, start=found.start), found.successor.code)
        self.assertEqual([(item.kind, item.name) for item in calculation.summary.obsolete],
                         [(preview.ObsoleteKind.SUCCESSOR, LOADING),
                          (preview.ObsoleteKind.SUCCESSOR, WORKSHOP)])
        calculation.create()
        self.assertEqual(self.starts(), {"PLT-001": "entity:PLT-003", "PLT-002": "entity:PLT-001",
                                         "PLT-003": START})
        moved = self.parameter("PLT-001")
        self.assertEqual((moved.value, moved.rev), ("entity:PLT-003", 2))
        history = self.history("PLT-001")
        self.assertEqual([item.value for item in history], [START, "entity:PLT-003"])
        self.assertEqual(history[-1].reason, calculation.entity.insertion[0].reason)
        self.assertIn(NO_AXIS, history[-1].reason)
        self.assertIn(LOADING, history[-1].reason)
        self.assertEqual(self.states(), {"PLT-001": "stale", "PLT-002": "stale", "PLT-003": "current"})
        self.assertEqual(numbers(entities.chain_of(self.records(), "PLT-003")), [3, 1, 2])
        self.assertEqual(numbers(entities.chain_tails(self.records())), [2])
        self.assertEqual(self.recompute_plan(), [("des.platform",), ("des.platform",)])

    def test_b_recomputing_gives_the_chain_on_the_new_surface(self) -> None:
        """RF-015-05, RF-015-16: «Recalcular lo obsoleto» rehace P1 sobre la superficie de la nueva y después P2;
        todo al día."""
        self.clock.advance(minutes=1)
        outcome = ops_test.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 2)
        self.assertEqual(set(self.states().values()), {"current"})
        self.assertEqual(self.recompute_plan(), [])


class AtomicInsertTest(InsertCase):
    """RF-015-05, RF-015-02: un fallo al crear la insertada no deja ni la entidad ni el cambio de la partida."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))

    def test_a_a_failure_midway_leaves_the_successor_as_it_was(self) -> None:
        """RF-015-05: con el cambio de la partida ya escrito en la transacción, un fallo al abrir la operación o al
        completarla lo deshace todo: ni la entidad nueva, ni el parámetro cambiado, ni la marca de obsoleto."""
        clean = self.written()
        starts = self.starts()
        for step, patched in (
                ("abrir la operación", mock.patch.object(design_store.OperationStart, "begin",
                                                         side_effect=RuntimeError("fallo de prueba"))),
                ("completar", mock.patch.object(operations.OperationHandle, "complete",
                                                side_effect=RuntimeError("fallo de prueba")))):
            with self.subTest(step=step):
                calculation = self.calculate_insertion(
                    prep.polygon_request(NO_AXIS, linked=False, start="entity:PLT-001"), "PLT-002")
                with patched, self.assertRaises(RuntimeError):
                    calculation.create()
                self.assertEqual(self.written(), clean)
                self.assertEqual(self.starts(), starts)
                self.assertEqual(set(self.states().values()), {"current"})
        self.assertEqual(self.recompute_plan(), [])


if __name__ == "__main__":
    unittest.main()
