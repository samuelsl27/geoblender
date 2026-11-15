# SPDX-License-Identifier: GPL-3.0-or-later
"""Aceptar con un motivo la edición de la tabla de las declaradas limpia «Recalcular lo obsoleto» (spec 015, T40;
hallazgo C-2; RF-015-11, RF-008-27, RF-008-56, RF-015-16; plan 015 §2.1 y §5.8; ADR-0025 §4 y §5).

La tabla ``des_decl_<vNN>`` de una versión se edita en QGIS: la 008 la bloquea (``core.external_edit_version``,
T20) y, como la declaración, las máscaras y las entidades forman un ciclo (tabla → máscaras → entidad → tabla), la
operación de la edición queda en «**revisar a mano**» y **todo lo que depende de la tabla espera a ella** en el plan.
Aceptar la edición con un motivo la dejaba así (``core.accept_review``, que la daría por buena, es de proyecto y no
admite datos de una versión): el plan no avanzaba y solo se limpiaba repitiendo la declaración, que **borra lo
aceptado**.

Ahora aceptar la edición **es** esa decisión: da por buena la operación de la edición con la misma razón
(``core.accept_review_version``, de la versión del dato, que conserva su contenido: lo aceptado no se toca) y nada
espera a ella.

- **(a)** (:class:`AcceptedEditTest`) tras aceptar: la operación de la edición queda sustituida por la de «dar por
  buena», con su motivo, su evento y el contenido de la tabla igual; el plan ya no tiene ninguna unidad que espere
  a ``core.external_edit_version`` ni la revisión a mano (que contaba en «! n obsoletos»), y la tabla sigue
  diferiendo de las entidades (lo aceptado se queda).
- **(b)** las máscaras se compilan con lo aceptado y «Recalcular lo obsoleto» rehace lo que dependía de la tabla
  **sin tocar la declaración**: la tabla conserva la fila aceptada y no queda nada obsoleto.
- **(c)** una segunda edición en QGIS vuelve a bloquear la tabla y se sigue ofreciendo **recalcular** (la entidad la
  vuelve a poner: la operación de «dar por buena» no es quien escribió la tabla) y recalcular funciona.
- **(d)** (:class:`RecomputeRightAfterAcceptingTest`) «Recalcular lo obsoleto» justo tras aceptar, sin compilar antes
  las máscaras, termina sin fallos y sin dejar nada obsoleto: la declaración, la primera de la cola, se rehace desde
  las entidades (como toda orden de entidades: lo aceptado se queda hasta que una entidad la vuelve a poner).
"""

from __future__ import annotations

from typing import Any

from tests.support.package import import_geoblender
from tests.unit.gis.masks import test_declared_blocked as tdb

access = import_geoblender("gis.masks.access")
contract = import_geoblender("core.provenance.contract")
entity_store = import_geoblender("design.entity_store")
events = import_geoblender("core.project.events")
external = import_geoblender("core.datasets.external")
graph_mod = import_geoblender("core.provenance.graph")
recompute_mod = import_geoblender("core.provenance.recompute")
stale_mod = import_geoblender("core.provenance.stale")

EDIT, ACCEPT = contract.EXTERNAL_EDIT_VERSION, contract.ACCEPT_REVIEW_VERSION
REASON = "La propiedad pide proteger también la balsa (Q:\\a\\b.pdf)"
SHOWN = "La propiedad pide proteger también la balsa (b.pdf)"
"""El motivo como queda registrado: sin rutas absolutas."""
SkipReason = recompute_mod.SkipReason


class AcceptCase(tdb.DeclaredBlockedCase):
    """Lo común: editar la tabla en QGIS, aceptar la edición y mirar el plan."""

    def plan(self) -> Any:
        with self.project.read() as conn:
            return recompute_mod.plan_recompute(graph_mod.load_graph(conn))

    def waiting_for_the_edit(self) -> list[Any]:
        """Lo que el plan deja fuera por la operación de la edición: ella (revisar a mano) y lo que espera a ella."""
        return [item for item in self.plan().skipped
                if item.reason is SkipReason.REVIEW or any(ref.op_type == EDIT for ref in item.waits_for)]

    def edit_op(self) -> str:
        return str(self.query("SELECT uid FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1", EDIT)[0][0])

    def edit_and_accept(self) -> str:
        """QGIS añade la restricción de una entidad que no existe y la persona acepta la edición con el motivo: el uid de
        la operación de la edición."""
        self.qgis(tdb.EXTRA_ROW.format(table=tdb.TABLE), (tdb.EXTRA_CODE,))
        self.assertBlocked()
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            external.accept_edit(conn, self.project, self.uid(), REASON)
        return self.edit_op()

    def counts(self) -> Any:
        return stale_mod.counts(self.project)


class AcceptedEditTest(AcceptCase):
    """(a) aceptar da por buena la edición, (b) las máscaras y «Recalcular lo obsoleto» con lo aceptado y (c) una
    segunda edición; cada prueba parte de lo que dejó la anterior."""

    def test_a_accepting_the_edit_gives_it_as_good_and_nothing_waits_for_it_any_more(self) -> None:
        """C-2, RF-015-11, RF-008-27: antes de aceptar, la operación de la edición espera revisión a mano y la
        declaración, la compilación, las plataformas y la capa de entidades **esperan a ella**; aceptar con un motivo la
        sustituye por una ``core.accept_review_version`` (de la versión del dato, con el motivo y el decisor de la
        sesión, sin consumir nada ni cambiar el contenido de la tabla) y deja un evento ``review_accepted``; el plan ya
        no tiene la revisión ni nada que espere a ella, y ya no cuenta en «! n obsoletos»."""
        self.qgis(tdb.EXTRA_ROW.format(table=tdb.TABLE), (tdb.EXTRA_CODE,))
        self.assertBlocked()
        waiting = self.waiting_for_the_edit()
        self.assertEqual(sorted(item.op_type for item in waiting),
                         sorted([EDIT, "des.declare_constraints", "gis.compile_constraints", "des.entity_layer",
                                 "des.platform", "des.platform"]))
        self.assertEqual(self.counts().review, 1)
        edit = self.edit_op()
        hash_edited = str(self.record_of().content_sha256)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            external.accept_edit(conn, self.project, self.uid(), REASON)
        self.assertEqual(str(self.status()), "current")
        self.assertEqual(str(self.record_of().content_sha256), hash_edited, "lo aceptado no se toca")
        self.assertTrue(entity_store.declaration_diverges(self.project, self.v1), "lo aceptado difiere de las entidades")
        ((uid, op_type, status, supersedes, repeatable, executor, revision),) = self.query(
            "SELECT uid, op_type, status, supersedes_uid, repeatable, executor, revision_uid FROM gb_operation "
            "WHERE op_type = ?", ACCEPT)
        self.assertEqual((op_type, status, supersedes, repeatable, executor), (ACCEPT, "done", edit, 0, "blender"))
        self.assertEqual(self.query("SELECT superseded_by, revision_uid FROM gb_operation WHERE uid = ?", edit),
                         [(uid, revision)], "de la misma revisión (la versión del dato)")
        self.assertTrue(revision)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'",
                                    uid), [(0,)], "no consume nada: lo que se da por bueno es lo que ella escribió")
        (event,) = self.logged(events.EventKind.REVIEW_ACCEPTED)
        self.assertEqual((event.entity_uid, event.data["op_type"], event.data["reason"], event.data["accepted_by"]),
                         (edit, EDIT, SHOWN, uid))
        self.assertEqual(len(self.logged(events.EventKind.EDIT_ACCEPTED)), 1)
        self.assertEqual(self.waiting_for_the_edit(), [], "nada espera ya a la edición")
        plan = self.plan()
        self.assertEqual(sorted(unit.op_types[0] for unit in plan.units),
                         sorted(["des.declare_constraints", "gis.compile_constraints", "des.entity_layer",
                                 "des.platform", "des.platform"]), "lo que esperaba, ahora se puede recalcular")
        self.assertEqual(plan.skipped, ())
        self.assertEqual(self.counts().review, 0)

    def test_b_the_masks_use_what_was_accepted_and_recompute_redoes_what_depended_on_it(self) -> None:
        """C-2, RF-015-11, RF-015-16, RF-008-26: las máscaras (obsoletas por el cambio de la tabla) se compilan con la
        fila aceptada; «Recalcular lo obsoleto» rehace entonces lo que dependía de ellas (las dos plataformas, que
        recalculadas dan lo mismo) **sin rehacer la declaración**: la tabla conserva la fila aceptada, no queda nada
        obsoleto ni esperando, y ninguna unidad falla."""
        self.clock.advance(minutes=1)
        masks = tdb.ops.finish(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertIs(masks.state, access.MaskState.CURRENT)
        self.assertIn(tdb.EXTRA_CODE, masks.zones, "las máscaras llevan la restricción aceptada")
        self.assertEqual(self.waiting_for_the_edit(), [])
        accepted = self.declared_dump()
        done = self.settle()
        self.assertTrue(done)
        self.assertEqual({str(result.status) for result in done}, {"done"}, [result.text() for result in done])
        self.assertEqual(self.declared_dump(), accepted, "la declaración no se rehizo: la fila aceptada sigue")
        self.assertTrue(entity_store.declaration_diverges(self.project, self.v1))
        self.assertIn(tdb.EXTRA_CODE, access.load_masks(self.project, self.v1.uid).zones)
        plan = self.plan()
        self.assertEqual((plan.units, plan.skipped), ((), ()), "nada obsoleto ni esperando")
        self.assertEqual(self.counts().obsolete, 0)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status <> 'done'"), [(0,)])

    def test_c_a_second_edit_blocks_it_again_and_the_entity_can_still_put_it_back(self) -> None:
        """RF-015-11, RF-008-56, RF-008-57: la operación de «dar por buena» «produce» la tabla pero no es quien la
        calcula (``external.last_writer``): una segunda edición en QGIS la vuelve a bloquear, se ofrece **aceptar y
        recalcular** (la declaración, repetible, es quien la escribió) y recalcular la deja como la declaran las
        entidades (la fila aceptada antes se va, como con toda declaración nueva)."""
        self.qgis('UPDATE "{table}" SET active = 0'.format(table=tdb.TABLE))
        self.assertBlocked()
        self.assertEqual([str(offer) for offer in self.read_offers()], ["accept", "recompute"])
        self.put_back()
        self.assertSameAsEntities(same_hash=False)
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v1))


class RecomputeRightAfterAcceptingTest(AcceptCase):
    """(d) «Recalcular lo obsoleto» justo tras aceptar, sin compilar antes las máscaras."""

    def test_d_recompute_right_after_accepting_finishes_without_failures_and_leaves_nothing_stale(self) -> None:
        """C-2, RF-015-11, RF-008-26: tras aceptar, «Recalcular lo obsoleto» (sin que nadie compilara las máscaras) rehace la
        declaración, la primera de la cola (como toda orden de entidades, lo aceptado se queda hasta que una entidad
        la vuelve a poner) y lo que depende de ella: ninguna unidad falla ni se rehúsa, el plan queda vacío y las
        máscaras al día. (Antes, el plan se quedaba esperando a la revisión de la edición.)"""
        self.edit_and_accept()
        self.assertEqual(self.waiting_for_the_edit(), [])
        done = self.settle()
        self.assertTrue(done)
        self.assertEqual({str(result.status) for result in done}, {"done"}, [result.text() for result in done])
        plan = self.plan()
        self.assertEqual((plan.units, plan.skipped), ((), ()))
        self.assertEqual(self.counts().obsolete, 0)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status <> 'done'"), [(0,)])
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT)

