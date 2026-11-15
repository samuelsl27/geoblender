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

