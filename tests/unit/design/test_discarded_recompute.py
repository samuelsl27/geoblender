# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo descartado no vuelve a «Recalcular lo obsoleto» y lo apoyado espera su decisión (spec 015, T40; hallazgos
C-4 y E-3; HU-015-2; RF-015-17, RF-008-26, RF-008-28; E3 de §2 y §10.1; plan 015 §5.4 A7; ADR-0030 §4).

Una entidad **descartada mientras estaba obsoleta** (protegiera o no) seguía en el plan de «Recalcular lo obsoleto»
por su cifra vigente (sus datos descartados no son «vivos»), fallaba con ``core.recompute_failed`` y un texto técnico
(«Ya hay «rasters/des_psf_….tif» en el proyecto…») y **persistía en cada «Recalcular lo obsoleto» posterior del
proyecto**, de cualquier versión, dejando una operación fallida cada pasada. Lo **apoyado** en ella queda en «apoyo
retirado» y no se recalcula (RF-015-17), pero se enseñaba como un rechazo técnico en cada pasada.

- **(a)** (:class:`DiscardedObsoleteTest`, sobre el mundo de CE-015-01: P1, P2 de su superficie, P3, «Balsa 2» y una
  verificación) P1 se cambia —queda obsoleta con todo lo que depende de ella— y se descarta: ninguna operación suya
  está en el plan, ni cuenta en «! n obsoletos» (``figure_only``), y «Recalcular lo obsoleto» no la intenta, **en
  ninguna pasada**, ni deja ninguna operación fallida en el proyecto.
- **(b)** Lo apoyado (P2 y «Balsa 2») se rehúsa con un texto que dice que **espera una decisión** (rehacerla sobre otra
  superficie, descartarla o darla por buena con un motivo) en las dos lenguas, sin recalcularse y sin escribir nada.
- **(a, protege)** (:class:`DiscardedProtectingTest`, el caso de la sonda ``probe_c4.py`` del verificador: P1 que
  protege con 4 m y P2 de su superficie, la plataforma que declara su restricción) lo mismo con una entidad que
  protegía: su restricción sale de las máscaras (RF-015-10) y su operación no vuelve al plan ni falla.
"""

from __future__ import annotations

import json
from typing import Any

from tests.support.package import import_geoblender
from tests.unit.design import test_entities_ce as ce
from tests.unit.design import test_entity_dependents as dep
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_platform_operation as ops_test

access = import_geoblender("gis.masks.access")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
graph_mod = import_geoblender("core.provenance.graph")
recompute_mod = import_geoblender("core.provenance.recompute")
stale_mod = import_geoblender("core.provenance.stale")

EntityState = entities.EntityState
UnitStatus = recompute_mod.UnitStatus
BALSA, ON_TOP, TWIN = dep.BALSA, dep.ON_TOP, dep.TWIN
BY = ce.BY
WHY = ce.WHY
RELEASE = "core.recompute_no_successor_release"
WAITS_ES = "Espera a que se rehaga sobre otra cosa, se descarte o se dé por buena con un motivo."
WAITS_EN = "It waits until it is redone on something else, discarded or given as good with a reason."


class RecomputeHelpers:
    """«Recalcular lo obsoleto» del proyecto tantas veces como se pida, y lo que queda registrado."""

    def name_of(self, uid: str) -> str:
        ((op_type, settings),) = self.query(  # type: ignore[attr-defined]
            "SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return str(json.loads(settings).get("name", op_type))

    def states(self) -> dict[str, Any]:
        return {entry.record.code: entry.record.state
                for entry in entities.registry(self.project, self.v1.uid)}  # type: ignore[attr-defined]

    def platform_names_in_plan(self) -> list[str]:
        """Los nombres de las **plataformas** (``des.platform``) de las unidades del plan de «Recalcular lo obsoleto»."""
        found = []
        for unit in self.plan_units():  # type: ignore[attr-defined]
            for uid in unit:
                ((op_type,),) = self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)  # type: ignore[attr-defined]
                if op_type == "des.platform":
                    found.append(self.name_of(uid))
        return found

    def recompute_once(self) -> Any:
        """Una pasada de la orden «Recalcular lo obsoleto» (``recompute_steps``): su ``RecomputeOutcome``."""
        self.clock.advance(minutes=1)  # type: ignore[attr-defined]
        return ops_test.finish(recompute_mod.recompute_steps(self.project))  # type: ignore[attr-defined]

    def not_done_operations(self) -> list[tuple[Any, ...]]:
        """Las operaciones del proyecto que no están hechas (fallidas, canceladas, en curso): ninguna, en un proyecto
        sano."""
        return self.query("SELECT op_type, status FROM gb_operation WHERE status <> 'done'")  # type: ignore[attr-defined]


class DiscardedObsoleteTest(RecomputeHelpers, dep.DependentsCase):
    """RF-015-17, RF-008-26 (C-4, E-3), en el orden de las pruebas: (a) P1, obsoleta por el cambio de su pendiente,
    se descarta y sale del plan; (b) «Recalcular lo obsoleto» no la intenta, nunca, y lo apoyado espera su decisión."""

    def test_a_a_discarded_platform_that_was_obsolete_is_neither_in_the_plan_nor_counted(self) -> None:
        """C-4, E-3, RF-015-17, RF-008-28: P1 queda obsoleta (cambia su pendiente: la causa llega a todo lo que depende
        de ella) y se descarta (``discard_entity``: sus tres datos pasan a «descartados»); su operación **sigue
        obsoleta como historia** pero ya no está en el plan (ni su unidad ni lo que se deja fuera), no la cuenta
        ``figure_only`` (la barra «! n obsoletos»: la deducción y la caché dicen lo mismo) y la deducción la tiene como
        descartada; lo demás de la cascada sí está en el plan."""
        self.change(dep.GRADIENT, ce.SLOPE_PCT)
        first = self.current("PLT-001")
        self.assertEqual(self.stale_causes(first), {("parameter_changed", dep.GRADIENT)})
        self.assertIn(BALSA, self.platform_names_in_plan(), "antes de descartarla, P1 se rehace con lo demás")
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "PLT-001", reason=WHY, decided_by=BY)
        self.assertEqual(len(found.datasets), 3)
        self.assertEqual(self.states()["PLT-001"], EntityState.DISCARDED)
        self.assertNotEqual(self.stale_causes(first), set(), "sigue obsoleta: es historia")
        names = self.platform_names_in_plan()
        self.assertNotIn(BALSA, names, "su operación ya no está en el plan de «Recalcular lo obsoleto»")
        self.assertEqual(names, [ON_TOP, dep.DRAG], "lo que depende de ella, sí (se rehúsa al ejecutar)")
        with self.project.read() as conn:
            graph = graph_mod.load_graph(conn)
            state = graph_mod.deduce(graph)
            plan = recompute_mod.plan_recompute(graph)
            self.assertEqual(stale_mod.figure_only_operations(conn), state.figure_only)
        self.assertIn(first, state.discarded)
        self.assertNotIn(first, state.figure_only)
        self.assertNotIn(first, {*plan.operations, *(item.operation_uid for item in plan.skipped)})

    def test_b_recompute_does_not_try_it_in_any_pass_and_leaves_no_failed_operation(self) -> None:
        """C-4, E-3, RF-015-17, RF-008-26: «Recalcular lo obsoleto» **no intenta** P1 descartada: ninguna unidad suya
        acaba fallida (antes, ``core.recompute_failed`` con «Ya hay «rasters/des_psf_….tif» en el proyecto…»), ni en la
        primera pasada ni en las siguientes del proyecto, y ninguna operación del proyecto queda fallida; lo
        apoyado (P2 y «Balsa 2») se rehúsa **sin recalcularse** y sin crear nada."""
        written = self.written()
        files = sorted(path.name for path in (self.root / "rasters").iterdir())
        for number in (1, 2, 3):
            outcome = self.recompute_once()
            statuses = {result.status for result in outcome.results}
            self.assertNotIn(UnitStatus.FAILED, statuses, f"pasada {number}")
            self.assertNotIn(UnitStatus.DONE, statuses, f"pasada {number}: lo demás espera su decisión")
            attempted = {self.name_of(result.unit.operations[0]) for result in outcome.results}
            self.assertNotIn(BALSA, attempted, f"pasada {number}: P1 descartada no se intenta")
            self.assertEqual(attempted, {ON_TOP}, f"pasada {number}: lo que parte de P2 ni se intenta")
        self.assertEqual(self.not_done_operations(), [], "ninguna operación fallida en todo el proyecto")
        self.assertEqual(self.written(), written, "no se escribe nada")
        self.assertEqual(sorted(path.name for path in (self.root / "rasters").iterdir()), files)

    def test_c_what_rested_on_it_says_it_waits_for_a_decision_in_both_languages(self) -> None:
        """E3, RF-015-17, error 59: lo apoyado en P1 (P2, que parte de su superficie, y «Balsa 2») se rehúsa con
        ``core.recompute_no_successor_release``: «se descartó y no tiene sucesor» y que **espera a que se rehaga
        sobre otra cosa, se descarte o se dé por buena con un motivo**, en español y en inglés; sigue en «apoyo
        retirado»."""
        outcome = self.recompute_once()
        refused = {self.name_of(result.unit.operations[0]): result for result in outcome.results}
        self.assertEqual(set(refused), {ON_TOP}, "«Balsa 2» y P3, que dependen de P2, esperan a que se decida P2")
        for name, result in refused.items():
            self.assertEqual((result.status, result.code), (UnitStatus.REFUSED, RELEASE), name)
            self.assertIn("se descartó y no tiene sucesor", result.reason, name)
            self.assertTrue(result.reason.endswith(WAITS_ES), result.reason)
            self.assertTrue(result.text(language="en").endswith(WAITS_EN), name)
        self.assertEqual(self.states()["PLT-002"], EntityState.SUPPORT_REMOVED)


class DiscardedProtectingTest(RecomputeHelpers, ce.ProtectedPlatformTest):
    """El caso de la sonda ``probe_c4.py``: P1 («Plataforma de la balsa», en corte, que protege con 4 m) y P2 («Sobre la
    balsa», «en corte y relleno» de su superficie) se descartan: la restricción de P1 sale de las máscaras (lo que
    deja obsoleta, entre otras, a la operación de P1) y «Recalcular lo obsoleto» no la intenta ni falla."""

    def test_a_discarding_the_platform_that_protects_leaves_it_out_of_every_recompute(self) -> None:
        """C-4, E-3, RF-015-17, RF-015-10, E3: P1 que protege (y P2 de su superficie) se descarta con lo que sigue
        (``discard_entity_steps``: su restricción sale de la declaración y de las máscaras, que dejan obsoleta su
        propia operación, ya descartada); en tres pasadas de «Recalcular lo obsoleto» ninguna operación fallida,
        P1 no se intenta, P2 se rehúsa con su decisión pendiente y las máscaras siguen al día sin su zona."""
        self.made(sup.asked(ce.BALSA, protect=True, guard_m=self.GUARD_M))
        self.chain()
        self.passes()
        self.made(dep.on_top())
        self.assertEqual(self.plan_names(), [])
        self.clock.advance(minutes=1)
        result = sup.finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-001", reason=ce.WHY,
                                                              decided_by=ce.BY))
        self.assertIsNone(result.chain.failure)
        self.assertEqual(self.states(), {"PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.SUPPORT_REMOVED})
        self.assertNotIn(ce.BALSA, self.platform_names_in_plan(), "P1 descartada ya no está en el plan")
        for number in (1, 2, 3):
            outcome = self.recompute_once()
            statuses = {result.status for result in outcome.results}
            self.assertNotIn(UnitStatus.FAILED, statuses, f"pasada {number}")
            self.assertNotIn(ce.BALSA, {self.name_of(r.unit.operations[0]) for r in outcome.results
                                        if r.unit.op_types == ("des.platform",)}, f"pasada {number}")
            refused = {r.code for r in outcome.results if r.status is UnitStatus.REFUSED}
            self.assertLessEqual(refused, {RELEASE}, f"pasada {number}")
            if number == 1:  # lo demás de la cascada (la lámina de agua) se rehace una vez
                self.assertEqual({r.status for r in outcome.results} - {UnitStatus.REFUSED}, {UnitStatus.DONE})
                written = self.written()
            else:
                self.assertEqual(self.written(), written, f"pasada {number}: ya no se crea nada")
        self.assertEqual(self.not_done_operations(), [], "ninguna operación fallida")
        self.assertEqual(self.states()["PLT-002"], EntityState.SUPPORT_REMOVED)
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT)


for _name in dir(ce.ProtectedPlatformTest):  # sus pruebas son suyas: aquí solo el mundo y los ayudantes
    if _name.startswith("test_") and _name not in vars(DiscardedProtectingTest):
        setattr(DiscardedProtectingTest, _name, None)
del _name
