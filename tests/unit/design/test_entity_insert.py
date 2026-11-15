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

from tests.support.package import import_geoblender
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


if __name__ == "__main__":
    unittest.main()
