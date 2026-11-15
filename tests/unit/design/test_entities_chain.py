# SPDX-License-Identifier: GPL-3.0-or-later
"""La cadena de las entidades de diseño y su registro (spec 015, T03; HU-015-2; RF-015-04,
RF-015-05; plan 015 §5.2.3 «Estados», §5.3.1 y §5.4; D-2; ADR-0025 §5 y ADR-0030).

- **La cadena** (sin proyecto): de cada superficie parte como mucho una entidad
  (``start_conflict``), la entidad que parte de la superficie que deja otra es su sucesora
  (``successor_of``, ``chain_of``), la última de cada cadena es su superficie de diseño
  (``chain_tails``) y «Insertar antes o después de…» da el cambio de partida del sucesor
  (``insert_after`` e ``insert_before``). La partida de una entidad es el **nombre de una
  superficie** («gis_dtm_ladera», «des_srf_…») o ``entity:<código>`` (la superficie que deja otra
  entidad). Una entidad descartada es un registro: no ocupa su superficie ni forma parte de una
  cadena. Un ciclo o dos entidades desde la misma superficie se rechazan.
- **El registro de una versión** (con proyecto, sobre la cantera sintética de la 014): los códigos
  con parámetros ``des.platform.{e}.*`` de la versión, su operación vigente y su estado deducido
  del grafo (sin calcular, al día, obsoleta, descartada, «apoyo retirado»), solo leyendo. Las
  operaciones ``des.platform`` aún no existen (las declara la T04 y las crea la T13): aquí se
  registran **sintéticas**, con el mismo contrato (parámetros de la entidad, la superficie de
  partida como entrada, sus datos como salidas); la T13 y la T27 lo cierran con la operación
  real.
"""

from __future__ import annotations

import dataclasses
import unittest
from typing import Any, ClassVar

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter

entities = import_geoblender("design.entities")
messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
core_params = import_geoblender("core.params")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
datasets = import_geoblender("core.datasets.model")
dataset_registry = import_geoblender("core.datasets.registry")
builtin = import_geoblender("core.content.builtin")
gpkg_base = import_geoblender("core.gpkg.base")
versions_model = import_geoblender("core.versions.model")
graph = import_geoblender("core.provenance.graph")

PLATFORM = entities.EntityKind.PLATFORM
State = entities.EntityState
GROUND = "gis_dtm_ladera"
"""La superficie de partida de las cadenas de las pruebas: el terreno de la cantera."""
DESIGN = "des_srf_cantera"
"""Otra superficie de partida: una superficie de diseño de la versión."""
OP_TYPE = "des.platform"
"""El tipo de operación de la plataforma (``plan 015 §5.2.3``; lo declara la T04)."""


def code(number: int) -> str:
    return entities.format_code(PLATFORM, number)


def ref(number: int) -> str:
    """La partida ``entity:PLT-00n``: la superficie que deja la entidad número ``number``."""
    return entities.surface_ref(code(number))


def rec(number: int, start: str | None, *, state: Any = State.UNCALCULATED,
        name: str | None = None, support: str | None = None) -> Any:
    """La entidad número ``number`` (nombre ``P<n>``) que parte de ``start``."""
    return entities.EntityRecord(code(number), name or f"P{number}", PLATFORM, start, support,
                                 state)


def numbers(found: Any) -> list[int]:
    """Los números de las entidades de ``found`` (``PLT-003`` → 3), en su orden."""
    return [int(item.code.rsplit("-", 1)[1]) for item in found]


def applied(records: list[Any], changes: Any, new: Any) -> list[Any]:
    """Las entidades tras la inserción: ``new`` y las de ``records`` con los cambios de partida
    de ``changes`` (lo que escribirá la orden de insertar, T31)."""
    new_start = {item.code: item.new for item in changes}
    return [dataclasses.replace(item, start=new_start.get(item.code, item.start))
            for item in records] + [new]


class ReferenceTest(unittest.TestCase):
    """La partida de una entidad: un nombre de superficie o ``entity:<código>`` (RF-015-04)."""

    def test_the_surface_an_entity_leaves(self) -> None:
        """RF-015-04: la superficie que deja una entidad se escribe ``entity:<código>`` y su
        código se lee de vuelta; un nombre de superficie, un texto vacío o un código mal formado
        no son una entidad."""
        self.assertEqual(entities.surface_ref("PLT-001"), "entity:PLT-001")
        self.assertEqual(entities.ref_code("entity:PLT-001"), "PLT-001")
        self.assertEqual(entities.ref_code(" entity:PLT-1000 "), "PLT-1000")
        for text in (GROUND, "", "  ", None, "entity:", "entity:plt-001", "entity:PLT-1",
                     "entity: PLT-001", "entity:PLT-001 y", "Entity:PLT-001"):
            with self.subTest(text=text):
                self.assertIsNone(entities.ref_code(text))
        with self.assertRaises(ValueError):
            entities.surface_ref("P1")
        with self.assertRaises(TypeError):
            entities.surface_ref(1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            entities.ref_code(5)  # type: ignore[arg-type]

    def test_an_entity_is_found_by_its_code_or_its_name(self) -> None:
        """RF-015-04: la orden elige por nombre y el almacén guarda el código inmutable; el
        código manda si un nombre se parece a otro código."""
        records = [rec(1, GROUND, name="PLT-002"), rec(2, ref(1), name="Taller")]
        self.assertIs(entities.find_entity(records, "PLT-001"), records[0])
        self.assertIs(entities.find_entity(records, "Taller"), records[1])
        self.assertIs(entities.find_entity(records, "PLT-002"), records[1])  # el código manda
        self.assertIsNone(entities.find_entity(records, "no existe"))
        self.assertIsNone(entities.find_entity([], "P1"))


class StartConflictTest(unittest.TestCase):
    """RF-015-04: de cada superficie parte como mucho una entidad (D-2)."""

    def test_a_second_entity_from_the_same_surface_is_refused(self) -> None:
        """RF-015-04: dos entidades desde la misma superficie; el rechazo nombra la que ya parte
        de ella; otra superficie queda libre."""
        records = [rec(1, GROUND), rec(2, DESIGN)]
        self.assertIs(entities.start_conflict(records, GROUND), records[0])
        self.assertIs(entities.start_conflict(records, DESIGN), records[1])
        self.assertIsNone(entities.start_conflict(records, "des_srf_otra"))
        self.assertIsNone(entities.start_conflict([], GROUND))

    def test_the_surface_that_another_entity_leaves(self) -> None:
        """RF-015-04: la superficie de una entidad también es una partida (``entity:<código>``):
        solo una entidad parte de la de PLT-001."""
        records = [rec(1, GROUND), rec(2, ref(1))]
        self.assertIs(entities.start_conflict(records, ref(1)), records[1])
        self.assertIsNone(entities.start_conflict(records, ref(2)))

    def test_what_counts_as_the_same_surface(self) -> None:
        """RF-015-04: la partida se compara sin los espacios de los extremos; sin partida (``None``
        o en blanco) no hay conflicto; una entidad sin calcular también ocupa la suya."""
        records = [rec(1, GROUND, state=State.UNCALCULATED), rec(2, None)]
        self.assertIs(entities.start_conflict(records, f"  {GROUND} "), records[0])
        for blank in (None, "", "   "):
            self.assertIsNone(entities.start_conflict(records, blank))
        for state in State:
            if state is State.DISCARDED:
                continue
            with self.subTest(state=state):
                self.assertIsNotNone(entities.start_conflict([rec(1, GROUND, state=state)],
                                                             GROUND))
        with self.assertRaises(TypeError):
            entities.start_conflict(records, 7)  # type: ignore[arg-type]

    def test_a_discarded_entity_does_not_hold_its_surface(self) -> None:
        """RF-015-04, RF-015-17: una entidad descartada es un registro («registro, no usar»): otra
        puede partir de su superficie."""
        records = [rec(1, GROUND, state=State.DISCARDED)]
        self.assertIsNone(entities.start_conflict(records, GROUND))

    def test_the_entity_being_edited_does_not_conflict_with_itself(self) -> None:
        """RF-015-04: al cambiar la partida de una entidad, ella misma no cuenta (``ignoring``)."""
        records = [rec(1, GROUND), rec(2, DESIGN)]
        self.assertIsNone(entities.start_conflict(records, GROUND, ignoring="PLT-001"))
        self.assertIs(entities.start_conflict(records, DESIGN, ignoring="PLT-001"), records[1])

    def test_the_records_must_be_entities(self) -> None:
        with self.assertRaises(TypeError):
            entities.start_conflict(["PLT-001"], GROUND)  # type: ignore[list-item]


class ChainWalkTest(unittest.TestCase):
    """RF-015-04: de cada entidad, de qué superficie parte, qué entidad parte de la suya y su
    cadena hacia delante."""

    def setUp(self) -> None:
        # terreno → P1 → P2 → P3; y, aparte, DESIGN → P4
        self.records = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(2)), rec(4, DESIGN)]

    def test_chain_of_walks_forward_from_the_entity(self) -> None:
        """RF-015-04: ``chain_of`` da la entidad y las que parten de la suya, una tras otra; por
        código o por nombre; la última da lo que parte de nada."""
        self.assertEqual(numbers(entities.chain_of(self.records, "PLT-001")), [1, 2, 3])
        self.assertEqual(numbers(entities.chain_of(self.records, "P2")), [2, 3])
        self.assertEqual(numbers(entities.chain_of(self.records, "P3")), [3])
        self.assertEqual(numbers(entities.chain_of(self.records, "P4")), [4])
        with self.assertRaises(ValueError):
            entities.chain_of(self.records, "no existe")

    def test_the_successor_and_the_predecessor(self) -> None:
        """RF-015-04: qué entidad parte de la superficie de otra y de qué entidad parte una; la
        primera de una cadena no parte de ninguna (parte de un nombre de superficie)."""
        self.assertEqual(numbers([entities.successor_of(self.records, "P1")]), [2])
        self.assertIsNone(entities.successor_of(self.records, "P3"))
        self.assertEqual(numbers([entities.predecessor_of(self.records, "P3")]), [2])
        self.assertIsNone(entities.predecessor_of(self.records, "P1"))
        self.assertIsNone(entities.predecessor_of(self.records, "P4"))

    def test_a_discarded_entity_is_out_of_the_chain_but_stays_a_record(self) -> None:
        """RF-015-04, RF-015-17: lo que parte de una descartada sigue partiendo de su
        superficie («apoyo retirado»), pero la descartada no es sucesora de nadie; la entidad
        descartada por la que se pregunta sí sale en su cadena."""
        records = [rec(1, GROUND), rec(2, ref(1), state=State.DISCARDED), rec(3, ref(2))]
        self.assertEqual(numbers(entities.chain_of(records, "P1")), [1])
        self.assertIsNone(entities.successor_of(records, "P1"))
        self.assertEqual(numbers(entities.chain_of(records, "P2")), [2, 3])
        self.assertEqual(numbers([entities.predecessor_of(records, "P3")]), [2])

    def test_a_cycle_is_refused(self) -> None:
        """RF-015-04 (D-2, cadenas lineales): una entidad no puede partir, directa ni
        indirectamente, de su propia superficie: ``des.entity_chain_cycle`` con la vuelta que da."""
        loop = [rec(1, ref(2)), rec(2, ref(1))]
        selfish = [rec(1, ref(1))]
        for records in (loop, selfish):
            with self.subTest(records=len(records)), self.assertRaises(
                    messages.DesignError) as caught:
                entities.chain_of(records, "P1")
            self.assertEqual(caught.exception.code, "des.entity_chain_cycle")
            self.assertEqual(caught.exception.field, "start")
        text = caught.exception.text
        self.assertIn("«P1»", text)
        with self.assertRaises(messages.DesignError) as caught:
            entities.chain_of(loop, "P1")
        self.assertIn("«P1» → «P2» → «P1»", caught.exception.text)

    def test_two_entities_from_the_same_surface_are_refused(self) -> None:
        """RF-015-04: si los datos traen dos entidades vivas desde la misma superficie, andar la
        cadena da ``des.entity_start_taken`` con las dos, no elige una."""
        records = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(1))]
        with self.assertRaises(messages.DesignError) as caught:
            entities.chain_of(records, "P1")
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        self.assertIn("«P3»", caught.exception.text)
        self.assertIn("«P2»", caught.exception.text)


class ChainTailsTest(unittest.TestCase):
    """RF-015-04: la última de cada cadena es su superficie de diseño (la que congelar pide
    verificar, RF-012-25); las demás, superficies de trabajo."""

    def test_the_last_of_several_chains(self) -> None:
        """RF-015-04: una entidad que parte del terreno o de una superficie de diseño abre una
        cadena; la que ninguna otra tiene como partida es su cola."""
        records = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(2)), rec(4, DESIGN), rec(5, "otra")]
        self.assertEqual(numbers(entities.chain_tails(records)), [3, 4, 5])

    def test_the_order_is_the_one_of_the_records_by_chain(self) -> None:
        """RF-015-04: las colas salen en el orden en que aparece el principio de su cadena."""
        records = [rec(4, DESIGN), rec(2, ref(1)), rec(1, GROUND), rec(3, ref(2))]
        self.assertEqual(numbers(entities.chain_tails(records)), [4, 3])

    def test_no_entities_no_tails(self) -> None:
        self.assertEqual(entities.chain_tails([]), ())

    def test_an_entity_without_start_has_no_chain(self) -> None:
        """RF-015-04: una entidad sin partida (aún sin elegir) no está en ninguna cadena: no hay
        superficie que verificar."""
        self.assertEqual(numbers(entities.chain_tails([rec(1, GROUND), rec(2, None)])), [1])

    def test_an_entity_without_start_that_another_starts_from_opens_its_chain(self) -> None:
        """RF-015-04, RF-015-18 (T26): lo que deja «Traer las entidades de…» cuando la partida de la primera era un
        resultado de otra versión: P1 sin partida y P2 y P3, que parten de su superficie y de la de P2: la cadena la
        abre P1 (aún sin superficie de la que partir), su cola es P3 y **no es un ciclo**; si nadie parte de su
        superficie, sigue sin estar en ninguna cadena."""
        records = [rec(1, None), rec(2, ref(1)), rec(3, ref(2))]
        self.assertEqual(numbers(entities.chain_tails(records)), [3])
        self.assertIsNone(entities.check_chain(records))
        self.assertEqual(numbers(entities.chain_tails([rec(1, None), rec(2, GROUND)])), [2])
        self.assertEqual(numbers(entities.chain_tails([rec(2, ref(1)), rec(1, None), rec(3, GROUND)])), [2, 3])

    def test_a_discarded_entity_is_not_a_tail(self) -> None:
        """RF-015-04, RF-015-17: descartada la última, la anterior vuelve a ser la cola; descartada
        la única, la cadena desaparece; lo que partía de una descartada abre una cadena."""
        chain = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(2), state=State.DISCARDED)]
        self.assertEqual(numbers(entities.chain_tails(chain)), [2])
        self.assertEqual(entities.chain_tails([rec(1, GROUND, state=State.DISCARDED)]), ())
        middle = [rec(1, GROUND), rec(2, ref(1), state=State.DISCARDED), rec(3, ref(2))]
        self.assertEqual(numbers(entities.chain_tails(middle)), [1, 3])

    def test_the_state_of_the_others_does_not_matter(self) -> None:
        """RF-015-04: obsoleta, sin calcular o con el apoyo retirado, una entidad sigue en su
        cadena."""
        records = [rec(1, GROUND, state=State.STALE),
                   rec(2, ref(1), state=State.SUPPORT_REMOVED),
                   rec(3, ref(2), state=State.CURRENT)]
        self.assertEqual(numbers(entities.chain_tails(records)), [3])

    def test_a_cycle_is_refused(self) -> None:
        """RF-015-04: un ciclo, sin principio de cadena, no se pierde: ``des.entity_chain_cycle``,
        aunque haya otras cadenas bien."""
        records = [rec(1, GROUND), rec(2, ref(3)), rec(3, ref(2))]
        with self.assertRaises(messages.DesignError) as caught:
            entities.chain_tails(records)
        self.assertEqual(caught.exception.code, "des.entity_chain_cycle")
        self.assertIn("«P2»", caught.exception.text)
        self.assertIn("«P3»", caught.exception.text)

    def test_two_entities_from_the_same_surface_are_refused(self) -> None:
        records = [rec(1, GROUND), rec(2, GROUND)]
        with self.assertRaises(messages.DesignError) as caught:
            entities.chain_tails(records)
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        self.assertEqual(caught.exception.values["entity"], "P2")
        self.assertEqual(caught.exception.values["other"], "P1")

    def test_check_chain_is_the_same_check_without_the_tails(self) -> None:
        """RF-015-04: ``check_chain`` rechaza lo mismo y da ``None`` si la cadena está bien."""
        self.assertIsNone(entities.check_chain([rec(1, GROUND), rec(2, ref(1))]))
        with self.assertRaises(messages.DesignError):
            entities.check_chain([rec(1, ref(2)), rec(2, ref(1))])
        with self.assertRaises(messages.DesignError):
            entities.check_chain([rec(1, GROUND), rec(2, GROUND)])


class InsertTest(unittest.TestCase):
    """RF-015-05: insertar una entidad antes o después de otra de su cadena; la siguiente pasa a
    partir de la insertada (cambio de parámetro con su motivo, sin escribir nada)."""

    def setUp(self) -> None:
        self.records = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(2))]

    def test_insert_after_the_entity_in_the_middle(self) -> None:
        """RF-015-05: insertar P9 después de P1 deja P1 → P9 → P2 → P3: el único cambio es la
        partida de P2, de ``entity:PLT-001`` a ``entity:PLT-009``, con su clave, su valor
        anterior y su motivo; ``new`` parte de la superficie de P1 y no se escribe nada."""
        new = rec(9, ref(1))
        before = tuple(self.records)
        changes = entities.insert_after(self.records, "P1", new)
        self.assertEqual(tuple(self.records), before)
        (change,) = changes
        self.assertEqual((change.code, change.key, change.old, change.new),
                         ("PLT-002", "des.platform.plt_002.start", "entity:PLT-001",
                          "entity:PLT-009"))
        self.assertIn("P9", change.reason)
        self.assertIn("P2", change.reason)
        after = applied(self.records, changes, new)
        self.assertEqual(numbers(entities.chain_of(after, "P1")), [1, 9, 2, 3])
        self.assertEqual(numbers(entities.chain_tails(after)), [3])

    def test_insert_after_the_last_of_the_chain(self) -> None:
        """RF-015-05: después de la última no cambia ninguna otra: la nueva es la cola."""
        new = rec(9, ref(3))
        self.assertEqual(entities.insert_after(self.records, "P3", new), ())
        after = applied(self.records, (), new)
        self.assertEqual(numbers(entities.chain_of(after, "P1")), [1, 2, 3, 9])
        self.assertEqual(numbers(entities.chain_tails(after)), [9])

    def test_insert_before_the_first_of_the_chain(self) -> None:
        """RF-015-05: antes de la primera (que parte de una superficie, no de una entidad), la
        nueva parte de esa superficie y la primera pasa a partir de la nueva: «insertar antes» es
        insertar después de lo que hay antes."""
        new = rec(9, GROUND)
        self.assertEqual(entities.insertion_start(self.records, "P1", before=True), GROUND)
        (change,) = entities.insert_before(self.records, "P1", new)
        self.assertEqual((change.code, change.old, change.new),
                         ("PLT-001", GROUND, "entity:PLT-009"))
        after = applied(self.records, (change,), new)
        self.assertEqual(numbers(entities.chain_of(after, "P9")), [9, 1, 2, 3])
        self.assertEqual(numbers(entities.chain_tails(after)), [3])

    def test_insert_before_an_entity_in_the_middle_is_insert_after_its_predecessor(self) -> None:
        """RF-015-05: insertar P9 antes de P2 es lo mismo que después de P1."""
        new = rec(9, ref(1))
        self.assertEqual(entities.insertion_start(self.records, "P2", before=True), ref(1))
        before_p2 = entities.insert_before(self.records, "P2", new)
        after_p1 = entities.insert_after(self.records, "P1", new)
        self.assertEqual(before_p2, after_p1)
        self.assertEqual(numbers(entities.chain_of(
            applied(self.records, before_p2, new), "P1")), [1, 9, 2, 3])

    def test_insertion_start_is_the_surface_the_new_entity_takes(self) -> None:
        """RF-015-05: la partida que debe llevar la nueva: la superficie que deja la entidad
        (después) o la de la que parte ella (antes)."""
        self.assertEqual(entities.insertion_start(self.records, "P2"), ref(2))
        self.assertEqual(entities.insertion_start(self.records, "PLT-003"), ref(3))
        self.assertEqual(entities.insertion_start(self.records, "P2", before=True), ref(1))

    def test_a_new_entity_that_does_not_start_where_it_is_inserted_is_a_program_error(self) -> None:
        """RF-015-05: la nueva ya parte de donde se inserta (la orden la crea con
        ``insertion_start``); si no, es un error del programa, sin escribir nada."""
        for new in (rec(9, GROUND), rec(9, None), rec(9, ref(2))):
            with self.subTest(start=new.start), self.assertRaises(ValueError):
                entities.insert_after(self.records, "P1", new)

    def test_other_program_errors(self) -> None:
        """RF-015-05: una entidad que no existe, una descartada (no tiene sitio en la cadena), una
        sin partida (no hay superficie antes de ella) o una nueva con un código ya usado son
        errores del programa."""
        with self.assertRaises(ValueError):
            entities.insert_after(self.records, "no existe", rec(9, ref(1)))
        discarded = [rec(1, GROUND, state=State.DISCARDED)]
        with self.assertRaises(ValueError):
            entities.insert_after(discarded, "P1", rec(9, ref(1)))
        with self.assertRaises(ValueError):
            entities.insert_before(discarded, "P1", rec(9, GROUND))
        with self.assertRaises(ValueError):
            entities.insert_before([rec(1, None)], "P1", rec(9, None))
        with self.assertRaises(ValueError):
            entities.insert_after(self.records, "P1", rec(2, ref(1), name="otra"))
        with self.assertRaises(TypeError):
            entities.insert_after(self.records, "P1", "P9")  # type: ignore[arg-type]

    def test_inserting_in_a_broken_chain_is_refused(self) -> None:
        """RF-015-04: no se inserta en una cadena con dos entidades desde la misma superficie ni
        en un ciclo; se dice qué falla."""
        taken = [rec(1, GROUND), rec(2, ref(1)), rec(3, ref(1))]
        with self.assertRaises(messages.DesignError) as caught:
            entities.insert_after(taken, "P1", rec(9, ref(1)))
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        loop = [rec(1, ref(2)), rec(2, ref(1))]
        with self.assertRaises(messages.DesignError) as caught:
            entities.insert_after(loop, "P1", rec(9, ref(1)))
        self.assertEqual(caught.exception.code, "des.entity_chain_cycle")

    def test_the_reason_in_each_language(self) -> None:
        """RF-015-05 (RF-008-02: todo cambio de un parámetro lleva su motivo): el motivo del
        cambio de la sucesora, en español por defecto y en inglés si se pide."""
        new = rec(9, ref(1), name="Taller")
        (es,) = entities.insert_after(self.records, "P1", new)
        (en,) = entities.insert_after(self.records, "P1", new, language="en")
        self.assertEqual(es.reason, "Se inserta la entidad Taller antes de P2: P2 pasa a partir "
                                    "de la superficie que deja Taller.")
        self.assertEqual(en.reason, "Entity Taller is inserted before P2: P2 now starts from the "
                                    "surface that Taller leaves.")
        self.assertEqual(en.key, es.key)
        with self.assertRaises(ValueError):
            entities.insert_after(self.records, "P1", new, language="fr")


# --- El registro de una versión (con proyecto) ----------------------------------------------------


def synthetic_definition() -> Any:
    """El tipo ``des.platform`` de las pruebas: lo que la T04 declarará de verdad (versión,
    repetible, ámbito de versión); aquí sin recálculo."""

    def never(request: Any) -> Any:
        raise AssertionError("las pruebas del registro no recalculan con la función de bl")

    return contract.OperationDef(OP_TYPE, "1.0", "des", "Platform of the tests", True,
                                 scope="version", recompute=never)


class RegistryTest(efx.EntityProjectCase):
    """RF-015-01, RF-015-04, RF-015-16, RF-015-17 y RF-015-25 (el estado) con proyecto: las
    entidades de V01 con sus parámetros y, de algunas, su operación sintética; cada prueba
    trabaja con sus propias entidades (la cadena de P1 a P3 no se toca; la de P4 y P5 cambia un
    parámetro; la de P6 y P7, descarta; P8 repite su operación)."""

    STEP_M = qfx.COARSE_STEP_M
    gradient: ClassVar[dict[str, float]] = {}
    ops: ClassVar[dict[str, str]] = {}

    @classmethod
    def declare(cls, version: Any, number: int, name: str, start: str | None, *,
                support: str | None = None, level: float | None = 230.0,
                gradient: float | None = 1.0) -> list[str]:
        """Da de alta en ``version`` los parámetros de la entidad ``PLT-<n>`` y devuelve sus claves
        (las que lee su operación)."""
        values: dict[str, Any] = {"name": name, "start": start, "support": support,
                                  "start_level_m": level, "gradient_pct": gradient}
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        keys = []
        with cls.project.write_transaction() as conn:
            for param, value in values.items():
                if value is None:
                    continue
                key = params.entity_key(code(number), param)
                store.create(conn, key, value, kind="ADOPTADO", source="Prueba de la cadena",
                             source_kind="person", decided_by="Samuel (IMGA)",
                             reason="Prueba de la 015", version=version.code)
                keys.append(key)
        return keys

    @classmethod
    def run_operation(cls, version: Any, number: int, keys: list[str], *,
                      reads: str | None = None, supersedes: str | None = None,
                      fail: bool = False, outputs: bool = True) -> Any:
        """La operación ``des.platform`` sintética de la entidad ``PLT-<n>``: lee sus parámetros,
        consume como ``surface`` el dato de ``reads`` (la superficie de otra entidad) y escribe
        dos tablas (``des_psf_p<n>`` y ``des_epr_p<n>``) como salidas. ``fail`` la deja fallida."""
        cls.clock.advance(minutes=1)
        inputs = [operations.Use(f"des_psf_p{reads}", "surface")] if reads else []
        handle = operations.begin_operation(
            cls.project, OP_TYPE, settings={"code": code(number)}, inputs=inputs, params=keys,
            executor="blender", version=version.uid, supersedes=supersedes)
        if fail:
            handle.fail("Fallo de prueba")
            return handle
        specs = []
        with cls.project.write_transaction() as conn:
            for family, role in (("psf", "entity_surface"), ("epr", "entity_table")):
                name = f"des_{family}_p{number}"
                locator = versions_model.version_locator(name, version.code)
                if outputs and conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                                            (locator,)).fetchone() is None:
                    gpkg_base.create_attribute_table(
                        conn, locator, [gpkg_base.ColumnDef("value", "DOUBLE")], name,
                        "Dato sintético de la prueba de la cadena (spec 015)")
                    conn.execute(f'INSERT INTO "{locator}" (value) VALUES (?)', (float(number),))
                if outputs:
                    specs.append(datasets.DatasetSpec(
                        name, "des", "table", datasets.Store.GPKG, locator,
                        reader=builtin.GPKG_LAYER.id, role=role))
            handle.complete(conn, outputs=specs)
        return handle

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(params.ENTITY_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(synthetic_definition()))
        v1 = cls.v1
        keys = {n: cls.declare(v1, n, f"P{n}", start, support=support) for n, start, support in (
            (1, GROUND, None), (2, ref(1), DESIGN), (3, ref(2), None), (4, DESIGN, None),
            (5, ref(4), None), (6, "des_srf_otra", None), (7, ref(6), None),
            (8, "des_srf_tercera", None))}
        cls.keys = keys
        cls.ops = {}
        for number, reads in ((1, None), (2, 1), (4, None), (5, 4), (6, None), (7, 6), (8, None)):
            cls.ops[f"P{number}"] = cls.run_operation(v1, number, keys[number],
                                                      reads=reads).uid
        cls.v2_keys = cls.declare(cls.v2, 1, "P1 de V02", GROUND)

    def registry(self, version: Any = None) -> Any:
        return entities.registry(self.project, (version or self.v1).uid)

    def entry(self, name: str, version: Any = None) -> Any:
        found = self.registry(version).get(name)
        self.assertIsNotNone(found, name)
        return found

    def test_the_registry_lists_the_entities_of_the_version_with_their_parameters(self) -> None:
        """RF-015-01: los códigos con parámetros ``des.platform.{e}.*`` de la versión, por código,
        con su nombre, su tipo, su partida y su apoyo leídos de los parámetros; los de otra
        versión no entran."""
        found = self.registry()
        self.assertEqual([item.record.code for item in found.entries],
                         [code(n) for n in range(1, 9)])
        self.assertEqual([item.record.name for item in found.entries],
                         [f"P{n}" for n in range(1, 9)])
        self.assertTrue(all(item.record.kind is PLATFORM for item in found.entries))
        self.assertEqual([item.start for item in found.records],
                         [GROUND, ref(1), ref(2), DESIGN, ref(4), "des_srf_otra", ref(6),
                          "des_srf_tercera"])
        self.assertEqual([item.support for item in found.records],
                         [None, DESIGN, None, None, None, None, None, None])
        self.assertEqual(len(found), 8)
        other = self.registry(self.v2)
        self.assertEqual([(item.record.code, item.record.name) for item in other],
                         [("PLT-001", "P1 de V02")])
        self.assertIs(found.get("PLT-004").record, found.records[3])
        self.assertIs(found.get("P4"), found.get("PLT-004"))
        self.assertIsNone(found.get("P99"))
        self.assertEqual(entities.next_code(PLATFORM, [item.code for item in found.records]),
                         "PLT-009")

    def test_the_version_can_be_given_by_its_code_and_a_missing_one_is_refused(self) -> None:
        """RF-015-01: la versión, por uid o por código; una que el proyecto no tiene, el rechazo
        de las versiones."""
        by_code = entities.registry(self.project, self.v1.code)
        self.assertEqual([item.record.code for item in by_code],
                         [item.record.code for item in self.registry()])
        with self.assertRaises(versions_model.VersionError) as caught:
            entities.registry(self.project, "V99")
        self.assertEqual(caught.exception.code, "core.version_unknown")

    def test_an_entity_without_operation_is_uncalculated(self) -> None:
        """RF-015-25, plan 015 §5.2.3: con parámetros y sin operación, «sin calcular» (es lo que
        deja «Traer las entidades de…»); también la de otra versión con el mismo código que una de
        V01 con operación."""
        for entry in (self.entry("P3"), self.entry("P1 de V02", self.v2)):
            self.assertEqual(entry.record.state, State.UNCALCULATED)
            self.assertIsNone(entry.operation_uid)
            self.assertEqual(entry.causes, frozenset())
            self.assertEqual(entry.retired, ())

    def test_an_entity_with_its_operation_up_to_date_is_current(self) -> None:
        """RF-015-25: la operación vigente de la entidad, sin causas, la deja «al día»; cada una
        con la suya."""
        for name in ("P1", "P2"):
            entry = self.entry(name)
            self.assertEqual(entry.record.state, State.CURRENT)
            self.assertEqual(entry.operation_uid, self.ops[name])
            self.assertEqual(entry.causes, frozenset())
        self.assertNotEqual(self.entry("P1").operation_uid, self.entry("P2").operation_uid)

    def test_a_changed_parameter_makes_it_stale_and_so_what_depends_on_it(self) -> None:
        """RF-015-16, RF-015-25 (ADR-0025 §5): cambiar un parámetro de P4 la deja obsoleta con su
        causa (``parameter_changed``) y, en cascada, a P5, que consumió su superficie; el registro
        lo deduce del grafo, no lo apunta."""
        self.assertEqual(self.entry("P4").record.state, State.CURRENT)
        self.assertEqual(self.entry("P5").record.state, State.CURRENT)
        store = core_params.ParameterStore(self.project)
        key = params.entity_key("PLT-004", "gradient_pct")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            changed = store.change(conn, key, value=2.0, source="Prueba", source_kind="person",
                                   decided_by="Samuel (IMGA)", reason="Prueba de la cascada",
                                   version=self.v1.code)
        first, second = self.entry("P4"), self.entry("P5")
        self.assertEqual((first.record.state, second.record.state), (State.STALE, State.STALE))
        self.assertIn(graph.Cause(graph.CauseKind.PARAMETER_CHANGED, changed.uid), first.causes)
        self.assertTrue(second.causes)
        self.assertEqual(first.operation_uid, self.ops["P4"])
        self.assertEqual(first.retired, ())

    def test_a_discarded_entity_and_the_one_whose_support_was_removed(self) -> None:
        """RF-015-17, RF-015-25: con los datos de P6 descartados, P6 está «descartada» (su
        operación queda, nada se borra) y P7, que consumió su superficie, «apoyo retirado» con el
        dato descartado como causa; ninguna es «obsoleta». Descartar es de la T25 (esta prueba
        usa el doble del registro de datos de la 008, ``set_status``)."""
        self.assertEqual(self.entry("P6").record.state, State.CURRENT)
        self.assertEqual(self.entry("P7").record.state, State.CURRENT)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            uids = [dataset_registry.get(conn, f"des_{family}_p6", version_uid=self.v1.uid).uid
                    for family in ("psf", "epr")]
            for uid in uids:
                dataset_registry.set_status(conn, self.project, uid, "discarded")
        gone, orphan = self.entry("P6"), self.entry("P7")
        self.assertEqual(gone.record.state, State.DISCARDED)
        self.assertEqual(gone.operation_uid, self.ops["P6"])
        self.assertEqual(orphan.record.state, State.SUPPORT_REMOVED)
        self.assertEqual(orphan.operation_uid, self.ops["P7"])
        self.assertEqual(orphan.retired, (uids[0],))
        self.assertTrue(orphan.causes)
        entries = self.registry().records
        self.assertEqual(numbers(entities.chain_tails(entries)), [3, 5, 7, 8])  # P6 ya no es cola

    def test_the_latest_operation_in_force_is_the_one_of_the_entity(self) -> None:
        """RF-015-02, RF-015-25: recalcular es una operación nueva que sustituye a la anterior
        (historia): la vigente es la última hecha; una fallida o cancelada no cuenta."""
        keys = self.keys[8]
        first = self.ops["P8"]
        self.assertEqual(self.entry("P8").operation_uid, first)
        second = self.run_operation(self.v1, 8, keys, supersedes=first).uid
        self.assertEqual(self.entry("P8").operation_uid, second)
        self.run_operation(self.v1, 8, keys, fail=True)
        self.assertEqual(self.entry("P8").operation_uid, second)
        self.assertEqual(self.entry("P8").record.state, State.CURRENT)

    def test_reading_the_registry_writes_nothing(self) -> None:
        """RF-015-01 (solo lectura): ni una transacción: el contador de cambios de la base no se
        mueve."""
        before = change_counter(self.root)
        self.registry()
        self.registry(self.v2)
        self.assertEqual(change_counter(self.root), before)


if __name__ == "__main__":
    unittest.main()
