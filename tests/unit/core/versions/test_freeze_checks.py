# SPDX-License-Identifier: GPL-3.0-or-later
"""Las comprobaciones de los módulos al congelar y su nota (spec 012, T18; RF-012-25; plan 012
D-7, D-29 y §5.3.2; ADR-0028).

``core.versions.freeze`` deja que un módulo pida aceptar, al congelar, lo que él sabe que no está
bien (``register_freeze_check``: una función que lee la base y da ``FreezeFinding``), sin
esquema nuevo: la nota va en ``AcceptItem.finding`` y, al congelar, en el ``accepted`` (JSON) de
la revisión, con el estado real del elemento. Sobre el proyecto de la demostración de versiones
(``tests/support/versions_fixtures.py``) y con comprobaciones de prueba:

1. **El registro**: registrar es idempotente por (módulo, función), un módulo puede tener varias,
   ``unregister_freeze_checks`` dice cuántas quitó; argumentos mal dados, errores del programa.
2. **El plan** (``freeze_plan``): sin comprobaciones registradas, es el de la 009 (ninguna nota);
   con ellas, cada hallazgo es un elemento que aceptar con su estado real (el de lo obsoleto
   sigue obsoleto, con su texto) y su nota; dos hallazgos del mismo elemento, una sola entrada;
   las comprobaciones leen la misma instantánea y el plan no escribe nada.
3. **Congelar** (``freeze_steps``): no congela sin aceptarlos con un motivo, que queda en la
   revisión (``accepted``) con la nota de cada hallazgo; el esquema sigue siendo el 3.

Datos solo sintéticos.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any

from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.package import import_geoblender

freeze = import_geoblender("core.versions.freeze")
copy_mod = import_geoblender("core.versions.copy")
model = import_geoblender("core.versions.model")
project_schema = import_geoblender("core.project.schema")
events_mod = import_geoblender("core.project.events")

ItemKind = model.ItemKind
ItemState = model.ItemState
REASON = "Se entrega con lo anotado"
NOTE = "La verificación «Diseño» no cumple: «torre» 6.384 m³."
SOURCE = "Plan de labores (prueba)"
DECIDER = "Samuel (IMGA)"


def _check(*found: Any) -> Any:
    """Una comprobación de prueba que da siempre ``found``."""

    def check(_conn: Any, _version_uid: str) -> tuple[Any, ...]:
        return found

    return check


def _finding(item_kind: Any, item_uid: str, name: str, text: str = NOTE,
             module: str = "prueba") -> Any:
    return freeze.FreezeFinding(module, item_kind, item_uid, name, text)


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertEqual(freeze.freeze_checks(), ())
        self.addCleanup(self.clean)

    @staticmethod
    def clean() -> None:
        for module in {module for module, _check in freeze.freeze_checks()}:
            freeze.unregister_freeze_checks(module)

    def test_register_unregister_and_count(self) -> None:
        """RF-012-25 (plan 012 §5.3.2): registrar la misma función del mismo módulo dos veces
        la deja una vez; un módulo puede tener varias y ``unregister_freeze_checks`` dice
        cuántas quitó (0 si no había ninguna); no toca las de otro módulo; se llaman en el
        orden en que se registraron."""
        first, second, other = _check(), _check(), _check()
        freeze.register_freeze_check("res", first)
        freeze.register_freeze_check("res", first)
        freeze.register_freeze_check("res", second)
        freeze.register_freeze_check("des", other)
        self.assertEqual(freeze.freeze_checks(),
                         (("res", first), ("res", second), ("des", other)))
        self.assertEqual(freeze.unregister_freeze_checks("res"), 2)
        self.assertEqual(freeze.freeze_checks(), (("des", other),))
        self.assertEqual(freeze.unregister_freeze_checks("res"), 0)
        self.assertEqual(freeze.unregister_freeze_checks("nada"), 0)
        self.assertEqual(freeze.unregister_freeze_checks("des"), 1)
        self.assertEqual(freeze.freeze_checks(), ())

    def test_bad_arguments(self) -> None:
        """RF-012-25: un módulo que no es un texto o está vacío, una comprobación que no se
        puede llamar, o un módulo mal dado al quitar, son errores del programa; no queda nada
        registrado."""
        for module, check, error in (("", _check(), ValueError), (" ", _check(), ValueError),
                                     (None, _check(), TypeError), ("res", None, TypeError),
                                     ("res", "no", TypeError)):
            with self.subTest(module=module, check=check):
                with self.assertRaises(error):
                    freeze.register_freeze_check(module, check)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            freeze.unregister_freeze_checks(None)  # type: ignore[arg-type]
        self.assertEqual(freeze.freeze_checks(), ())

    def test_finding_is_checked(self) -> None:
        """RF-012-25: un hallazgo lleva un elemento de los que congela la 009 (una clase de
        ``ItemKind``, también por su valor), su uid, su nombre y su nota, y no es una nota
        vacía."""
        found = _finding("dataset", "u" * 32, "res_chk_diseno")
        self.assertIs(found.item_kind, ItemKind.DATASET)
        self.assertEqual((found.module, found.item_uid, found.name, found.text),
                         ("prueba", "u" * 32, "res_chk_diseno", NOTE))
        for kind, uid, name, text in (("nada", "u", "n", "t"), (ItemKind.DATASET, "", "n", "t"),
                                      (ItemKind.DATASET, "u", " ", "t"),
                                      (ItemKind.DATASET, "u", "n", "  ")):
            with self.subTest(kind=kind, uid=uid, name=name, text=text):
                with self.assertRaises(ValueError):
                    freeze.FreezeFinding("prueba", kind, uid, name, text)


class FindingsCase(fixtures.VersionsProjectCase):
    """Ayudas: V01 con el hueco (datos y operaciones) y comprobaciones de prueba."""

    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(freeze.freeze_checks(), ())
        self.pit = self.demo.pit(self.project, "V01")
        self.grid = self.record(vdemo.PIT_GRID, "V01")
        self.mesh = self.record(vdemo.PIT_MESH, "V01")

    def register(self, check: Any, module: str = "prueba") -> None:
        freeze.register_freeze_check(module, check)
        self.addCleanup(freeze.unregister_freeze_checks, module)

    def plan(self) -> Any:
        return freeze.freeze_plan(self.project, "V01")

    def bench(self, value: float) -> None:
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=value, source=SOURCE, decided_by=DECIDER,
            reason="Banco de la prueba", version="V01"))

    def freeze(self, reason: str = REASON, **kw: Any) -> Any:
        """Congela V01 hasta el final (un minuto después): su ``FreezeOutcome``."""
        self.tick()
        last = None
        for step in freeze.freeze_steps(self.project, "V01", reason=reason, **kw):
            last = step
        return last.result


class PlanTest(FindingsCase):
    def test_without_checks_it_is_the_plan_of_009(self) -> None:
        """RF-012-25 (D-7): sin comprobaciones registradas, el plan es el de la 009: un hueco al
        día no pide aceptar nada y, con el banco cambiado, lo obsoleto se acepta como siempre,
        sin nota."""
        plan = self.plan()
        self.assertEqual((plan.accept, plan.needs_acceptance, plan.blockers), ((), False, ()))
        self.bench(12.0)
        plan = self.plan()
        self.assertEqual(len(plan.accept), 3)
        self.assertEqual({entry.state for entry in plan.accept}, {ItemState.STALE})
        self.assertEqual([entry.finding for entry in plan.accept], [None] * 3)

    def test_findings_are_listed_with_their_real_state(self) -> None:
        """RF-012-25: cada hallazgo es un elemento que aceptar con su estado real (al día, el
        del dato y el de la operación) y su nota; aparecen después de lo de la 009 y el plan
        pide aceptar; lo que no está en el plan, al día. Los hallazgos de un elemento que ya
        pide aceptar por obsoleto van en su entrada (que sigue obsoleta, con su texto) y no la
        repiten."""
        self.register(_check(
            _finding(ItemKind.DATASET, self.grid.uid, self.grid.name, "Nota de la rejilla."),
            _finding(ItemKind.OPERATION, self.pit.uid, "Hueco", "Nota de la operación."),
            _finding(ItemKind.DATASET, "x" * 32, "Fuera del plan", "Nota de un dato ajeno.")))
        plan = self.plan()
        self.assertTrue(plan.needs_acceptance)
        self.assertEqual([(entry.item_kind, entry.item_uid, entry.name, entry.state, entry.text,
                           entry.finding) for entry in plan.accept], [
            (ItemKind.DATASET, self.grid.uid, self.grid.name, ItemState.CURRENT, "",
             "Nota de la rejilla."),
            (ItemKind.OPERATION, self.pit.uid, "Hueco", ItemState.CURRENT, "",
             "Nota de la operación."),
            (ItemKind.DATASET, "x" * 32, "Fuera del plan", ItemState.CURRENT, "",
             "Nota de un dato ajeno.")])
        self.bench(12.0)
        plan = self.plan()
        by_uid = {(entry.item_kind, entry.item_uid): entry for entry in plan.accept}
        grid = by_uid[(ItemKind.DATASET, self.grid.uid)]
        self.assertEqual((grid.state, grid.name, grid.finding),
                         (ItemState.STALE, self.grid.name, "Nota de la rejilla."))
        self.assertTrue(grid.text.startswith("Obsoleto"), grid.text)
        self.assertEqual(sum(entry.item_uid == self.grid.uid for entry in plan.accept), 1)
        self.assertEqual(len(plan.accept), 5)  # tres obsoletos + la operación + el ajeno
        operation = by_uid[(ItemKind.OPERATION, self.pit.uid)]
        self.assertEqual((operation.state, operation.finding),
                         (ItemState.STALE, "Nota de la operación."))
        self.assertTrue(operation.text.startswith("Obsoleto"), operation.text)
        self.assertEqual({entry.finding for entry in plan.accept if entry.item_uid
                          in {self.mesh.uid}}, {None})
        stale = [entry for entry in plan.accept if entry.finding is None]
        self.assertEqual(len(stale), 2)
        self.assertTrue(all(entry.text.startswith("Obsoleto") for entry in stale))

    def test_one_entry_per_item_and_the_checks_read_the_snapshot(self) -> None:
        """RF-012-25: dos comprobaciones (de módulos distintos) con hallazgos del mismo
        elemento dan una sola entrada, con las notas en el orden de registro, sin repetir la que
        es igual y con el nombre del primero; la comprobación recibe la conexión del plan, en su
        instantánea, y el uid de la versión; el plan no escribe nada, ni en la base ni en el
        disco; otra cosa que un hallazgo es un error del programa."""
        self.register(_check(_finding(ItemKind.OPERATION, self.pit.uid, "Primero", "Una."),
                             _finding(ItemKind.OPERATION, self.pit.uid, "Otro", "Una.")), "uno")
        self.register(_check(_finding(ItemKind.OPERATION, self.pit.uid, "Segundo", "Otra.",
                                      module="dos")), "dos")
        (entry,) = self.plan().accept
        self.assertEqual((entry.name, entry.finding), ("Primero", "Una. Otra."))
        freeze.unregister_freeze_checks("uno")
        freeze.unregister_freeze_checks("dos")
        seen: list[tuple[bool, str]] = []

        def check(conn: Any, version_uid: str) -> list[Any]:
            seen.append((conn.in_transaction, version_uid))
            return []

        self.register(check)
        files, counter = self.files(), self.change_counter()
        plan = self.plan()
        self.assertEqual(seen, [(True, self.v1.uid)])
        self.assertEqual((self.change_counter(), self.files()), (counter, files))
        self.assertEqual(plan.accept, ())
        freeze.unregister_freeze_checks("prueba")
        self.register(_check("no es un hallazgo"))
        with self.assertRaises(TypeError):
            self.plan()


class FreezeTest(FindingsCase):
    def test_not_without_accepting_and_the_note_stays_in_the_revision(self) -> None:
        """RF-012-25, RF-009-08 (D-7, D-29): con un hallazgo, no se congela sin aceptarlo (el
        rechazo nombra el elemento y no escribe nada) ni con una aceptación que no lo cubre;
        con ella, la revisión queda congelada con el motivo y, en lo aceptado, el elemento con
        su estado real y su nota (también en el manifiesto); las demás entradas, sin nota. El
        esquema sigue siendo el 3 y el estado de un elemento congelado, uno de los cinco. Quitada
        la comprobación, V01.r2 no pide aceptar nada, como en la 009 (sus pruebas, en verde)."""
        self.register(_check(_finding(ItemKind.OPERATION, self.pit.uid, "Hueco", NOTE)))
        plan = self.plan()
        before = (self.files(), self.change_counter())
        with self.assertRaises(model.VersionError) as caught:
            self.freeze()
        self.assertEqual(caught.exception.code, "core.version_freeze_accept")
        self.assertIn("Hueco", str(caught.exception))
        with self.assertRaises(model.VersionError) as caught:
            self.freeze(accepted=freeze.Acceptance(frozenset({("dataset", self.grid.uid)})))
        self.assertEqual(caught.exception.code, "core.version_freeze_accept")
        self.assertEqual((self.files(), self.change_counter()), before)

        whole = freeze.Acceptance.of(plan)
        self.assertEqual(whole.items, frozenset({("operation", self.pit.uid)}))
        outcome = self.freeze(accepted=whole)
        expected = copy_mod.acceptance(plan, reason=REASON)
        self.assertEqual(expected, {"reason": REASON, "items": [{
            "item_kind": "operation", "item_uid": self.pit.uid, "name": "Hueco",
            "state": "current", "text": "", "finding": NOTE}]})
        accepted = json.loads(str(outcome.frozen.accepted))
        self.assertEqual(accepted, expected)
        body = json.loads((self.root / "snapshots" / "V01.r1" / copy_mod.MANIFEST_NAME)
                          .read_bytes())
        self.assertEqual(body["accepted"], expected)
        (event,) = self.read(lambda conn: events_mod.read_events(
            conn, events_mod.EventKind.REVISION_FROZEN))
        self.assertEqual(event.data["accepted"], 1)
        self.assertIn(REASON, event.message)
        rows = self.query("SELECT state FROM gb_revision_item WHERE revision_uid = ?",
                          (outcome.frozen.uid,))
        self.assertTrue({row[0] for row in rows} <= {str(state) for state in ItemState})
        self.assertEqual(project_schema.SCHEMA_VERSION, 4)
        (ddl,) = self.query("SELECT sql FROM sqlite_master WHERE name = 'gb_revision_item'")
        (listed,) = re.findall(r"CHECK \(state IN \(([^)]*)\)\)", ddl[0])
        self.assertEqual(listed.replace("'", "").split(","), [str(s) for s in ItemState])

        # V01.r2, abierta, sin comprobaciones registradas: como en la 009 (D-7), nada que aceptar.
        freeze.unregister_freeze_checks("prueba")
        self.assertEqual(self.plan().accept, ())

    def test_the_stale_ones_keep_their_text_and_their_state(self) -> None:
        """RF-012-25, RF-009-08: un hallazgo de un dato obsoleto se acepta con lo obsoleto (una
        entrada) y lo que queda anotado en la revisión (``copy.acceptance``, lo que escribe
        ``freeze_steps`` en ``accepted`` y en el manifiesto) conserva el estado real
        («stale»), el texto de lo obsoleto y la nota, y solo esa entrada la lleva."""
        self.bench(12.0)
        self.register(_check(_finding(ItemKind.DATASET, self.grid.uid, self.grid.name, NOTE)))
        plan = self.plan()
        self.assertEqual(len(plan.accept), 3)
        accepted = copy_mod.acceptance(plan, reason=REASON)
        self.assertEqual(accepted["reason"], REASON)
        entries = {entry["item_uid"]: entry for entry in accepted["items"]}
        self.assertEqual(len(entries), 3)
        grid = entries[self.grid.uid]
        self.assertEqual((grid["state"], grid["finding"]), ("stale", NOTE))
        self.assertTrue(grid["text"].startswith("Obsoleto"), grid["text"])
        self.assertTrue(all("finding" not in entry for uid, entry in entries.items()
                            if uid != self.grid.uid))
        self.assertTrue(freeze.Acceptance.of(plan).covers(plan))


if __name__ == "__main__":
    unittest.main()
