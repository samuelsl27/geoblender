# SPDX-License-Identifier: GPL-3.0-or-later
"""Descartar una entidad, «apoyo retirado» y soltar el apoyo (spec 015, T25; HU-015-2; RF-015-17, RF-009-12,
RF-008-26, RF-008-27, RF-015-10, RF-015-15; D-12; plan 015 §5.2.3, §5.3.3, §5.4 A7 y §5.7 P-6; ADR-0030 §4;
CE-015-01 y CE-015-04): el caso del **error 59** (un relleno seguía apoyado en un acopio que se retiraba).

- **La lista antes** (``entity_store.discard_plan``): **una sola lista** de lo que se apoya en la entidad y de lo que
  parte de ella —nombre, tipo y volumen apoyado en m³, la de ``entities.dependents``—, sin escribir nada.
- **Descartar** (``entity_store.discard_entity``): poner ``DISCARDED`` los datos que escribió (nada se borra,
  RF-009-12) o, si no está calculada, el parámetro de versión ``des.platform.{e}.discarded``; con un **evento**
  (``entity_discarded``) y el motivo. Lo que se le apoyaba queda en **«apoyo retirado»**, con la causa
  («Apoyo retirado: se descartó la plataforma P1»), y «Recalcular lo obsoleto» **no lo recalcula**
  (``core.recompute_no_successor_release``) hasta que la persona lo rehaga sobre otra superficie, lo descarte o lo dé
  por bueno con un motivo.
- **Soltar el apoyo** (``entity_store.release_support``, A7, P-6): repetir la operación **con** ``supersedes`` sin
  esa entrada, con el motivo y el decisor en sus ajustes (``supports_released``, acumulada) y un evento
  (``support_released``); su salida no cambia (mismo hash) y lo que dependía de ella **no se recalcula**
  (RF-008-26); el gancho de las dependencias no vuelve a registrar una entidad soltada.
- **La restricción** de la entidad descartada **sale de las máscaras** (``after_entity_change``).

Tres mundos sobre la cantera de la 014 con las capas de plataformas (rejilla gruesa de 2 m): el de CE-015-01
(P1, P2 que parte de su superficie y rellena sobre ella, P3, el «solo relleno» «Balsa 2» y una verificación),
uno con dos cosas que se apoyan sin partir de P1 —una plataforma que lo declara y el «solo relleno»— y una
verificación de éste, y el de una plataforma que protege.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import create_version
from tests.unit.design import test_after_entity_change as chain_test
from tests.unit.design import test_entity_dependents as dep
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
cstore = import_geoblender("reserves.compliance_store")
dataset_registry = import_geoblender("core.datasets.registry")
declared_mod = import_geoblender("core.constraints.declared")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
events = import_geoblender("core.project.events")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
steps = import_geoblender("design.steps")
surfaces = import_geoblender("reserves.surfaces")

DesignError = messages.DesignError
EntityState = entities.EntityState
BALSA, ON_TOP, DRAG, TWIN = dep.BALSA, dep.ON_TOP, dep.DRAG, dep.TWIN
WORKSHOP = prep.WORKSHOP
PSF1, PSF2, EPR1, EPR2 = dep.PSF1, dep.PSF2, dep.EPR1, dep.EPR2
PRP1 = provenance.dataset_name("prp", BALSA)
TWIN_SURFACE = dep.TWIN_SURFACE
TWIN_CHECK = "Revisión de Balsa 2"
BY = "Samuel (IMGA)"
WHY = "La balsa no se hace: la propiedad cambia el plan"


class DiscardCase:
    """Lo común de los tres mundos: ayudantes de lo que queda registrado (eventos, estados, el estado entero del
    proyecto)."""

    def events(self, kind: Any) -> list[Any]:
        with self.project.read() as conn:  # type: ignore[attr-defined]
            return events.read_events(conn, kind)

    def states(self) -> dict[str, Any]:
        registry = entities.registry(self.project, self.v1.uid)  # type: ignore[attr-defined]
        return {entry.record.code: entry.record.state for entry in registry}

    def state_of(self, code: str) -> Any:
        return self.states()[code]

    def dataset_status(self, *names: str) -> dict[str, str]:
        return dict(self.query(  # type: ignore[attr-defined]
            f"SELECT name, status FROM gb_dataset WHERE name IN ({', '.join('?' for _ in names)}) "
            "AND version_uid = ?", *names, self.v1.uid))  # type: ignore[attr-defined]

    def everything(self) -> dict[str, Any]:
        """Todo lo que podría escribir descartar o soltar, con los eventos."""
        return {**self.written(), "events": self.query("SELECT kind, message FROM gb_event ORDER BY fid")}  # type: ignore[attr-defined]

    def locator(self, name: str) -> str:
        """Dónde está el dato ``name`` de V01, **también descartado** (``record`` solo da lo vigente)."""
        ((found,),) = self.query("SELECT locator FROM gb_dataset WHERE name = ? AND version_uid = ?",  # type: ignore[attr-defined]
                                 name, self.v1.uid)  # type: ignore[attr-defined]
        return str(found)

    def settings_of(self, uid: str) -> dict[str, Any]:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)  # type: ignore[attr-defined]
        return dict(json.loads(settings))


# ---------------------------------------------------------------------------------------------
# CE-015-01: P1, P2 (de su superficie), P3, «Balsa 2» y una verificación
# ---------------------------------------------------------------------------------------------


class DiscardTest(DiscardCase, dep.DependentsCase):
    """RF-015-17, RF-009-12, D-12, RF-008-26, CE-015-01, en el orden de las pruebas: (a) la lista antes y el
    gancho, (b) descartar P1, (c) «Recalcular lo obsoleto» no lo recalcula, (d) lo que no se puede dar por bueno,
    (e) descartar P2 (con su lista) y (f) rehacer P3 sobre otra superficie."""

    # --- (a) La lista antes ------------------------------------------------------------------------

    def test_a_the_list_before_discarding_is_one_list_with_name_type_and_volume_and_writes_nothing(self) -> None:
        """RF-015-17: antes de descartar P1, **una sola lista** de lo que se le apoya y de lo que parte de ella:
        P2 (parte de su superficie y rellena sobre ella: los 8.000 m³ a mano) y «Balsa 2» (el «solo relleno» de
        la 014, con el suyo), cada una con su nombre, su tipo y su volumen en m³, en las dos lenguas; la misma
        lista de ``entities.dependents``. No escribe nada."""
        before = self.everything()
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(self.everything(), before, "la lista no escribe nada")
        self.assertEqual((plan.code, plan.name, plan.state, plan.calculated),
                         ("PLT-001", BALSA, EntityState.CURRENT, True))
        self.assertEqual([(row.name, row.op_type, row.entity) for row in plan.dependents],
                         [(ON_TOP, "des.platform", "PLT-002"), (TWIN, "des.fill_only", None)])
        self.assertEqual(plan.dependents, entities.dependents(self.project, self.v1.uid, "PLT-001"))
        by_hand = dep.FILL_M * self.cells_of(EPR1) * sup.CELL_M2
        self.assertLessEqual(abs(plan.dependents[0].volume_m3 - by_hand) / by_hand, 1e-9)
        oracle = self.by_hand(TWIN_SURFACE, qfx.terrain(self.grid), PSF1, EPR1)
        self.assertLessEqual(abs(plan.dependents[1].volume_m3 - oracle) / oracle, 1e-9)
        shown = plan.lines("es")
        self.assertEqual(len(shown), 2)
        self.assertTrue(shown[0].startswith(f"{ON_TOP} (Plataforma): "), shown[0])
        self.assertIn("m³", shown[0])
        self.assertIn("(Solo relleno)", shown[1])
        self.assertIn("(Fill only)", plan.lines("en")[1])
        # una entidad sin nada apoyado: lista vacía; la que no es de la versión, un error del programa.
        self.assertEqual(entity_store.discard_plan(self.project, self.v1.uid, "PLT-003").dependents, ())
        with self.assertRaises(ValueError):
            entity_store.discard_plan(self.project, self.v1.uid, "PLT-009")
        self.assertEqual(entity_store.discard_plan(self.project, self.v1.code, BALSA).code, "PLT-001",
                         "por su nombre y con el código de la versión")

    def test_a_the_hook_does_not_register_a_released_entity(self) -> None:
        """RF-015-17, A7, ADR-0030 §4: el gancho de las dependencias (``survey_supports``) detecta P1 y P2 en lo
        que rellena «Balsa 2»; **sin** la entidad que se soltó (``released``), no vuelve a registrarla."""
        result, start = self.grid_of(TWIN_SURFACE), qfx.terrain(self.grid)
        options: dict[str, Any] = {"written": {TWIN_SURFACE}, "start_values": start}
        found = entity_store.survey_supports(self.project, self.v1, [result], fill_test.START, **options)
        self.assertEqual([item.code for item in found.supports], ["PLT-001", "PLT-002"])
        left = entity_store.survey_supports(self.project, self.v1, [result], fill_test.START,
                                            released=("PLT-001",), **options)
        self.assertEqual([item.code for item in left.supports], ["PLT-002"])

    # --- (b) Descartar P1 --------------------------------------------------------------------------

    def test_b_discarding_the_first_platform_discards_its_data_deletes_nothing_and_leaves_an_event(self) -> None:
        """RF-015-17, RF-009-12 (nada se borra), D-12: descartar P1 pone ``discarded`` los tres datos que
        escribió (la superficie, la tabla y el informe) con **un evento** (``entity_discarded``: quién, por qué,
        qué datos y la lista de lo que se le apoyaba, con sus m³); **nada se borra** (las filas, los ficheros, las
        tablas, las operaciones y las cifras siguen); P1 queda «descartada» y lo que se le apoyaba, **«apoyo
        retirado»**, con la causa: P2 y «Balsa 2» lo dicen («Apoyo retirado: se descartó la plataforma …») y P3,
        que parte de P2, obsoleta con la 008."""
        listed = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        before = self.everything()
        files = sorted(path.name for path in (self.root / "rasters").iterdir())
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "PLT-001", reason=WHY, decided_by=BY)
        self.assertEqual((found.code, found.name, found.version, found.reason, found.decided_by),
                         ("PLT-001", BALSA, "V01", WHY, BY))
        self.assertEqual(found.operation_uid, self.current("PLT-001"))
        self.assertEqual(sorted(found.datasets), sorted([PSF1, EPR1, PRP1]))
        self.assertEqual(found.dependents, listed.dependents, "la lista que se enseñó es la que se registra")
        self.assertEqual(set(self.dataset_status(PSF1, EPR1, PRP1).values()), {"discarded"})
        after = self.everything()
        for what in ("operations", "io", "figures", "tables"):  # nada se borra (RF-009-12)
            self.assertEqual(after[what], before[what], what)
        self.assertEqual(len(after["datasets"]), len(before["datasets"]))
        self.assertEqual(sorted(path.name for path in (self.root / "rasters").iterdir()), files)
        self.assertTrue((self.root / self.locator(PSF1)).is_file(), "su fichero sigue ahí")
        self.assertEqual(self.query(f'SELECT count(*) FROM "{self.locator(EPR1)}"'), [(1,)])
        self.assertEqual(self.states(), {"PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.SUPPORT_REMOVED,
                                         "PLT-003": EntityState.STALE})
        (event,) = self.events(events.EventKind.ENTITY_DISCARDED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.user_host != ""),
                         ("entity", "PLT-001", True))
        self.assertIn(BALSA, event.message)
        self.assertIn(WHY, event.message)
        self.assertEqual({key: event.data[key] for key in ("version", "entity", "name", "reason", "decided_by")},
                         {"version": "V01", "entity": "PLT-001", "name": BALSA, "reason": WHY, "decided_by": BY})
        self.assertEqual([(item["name"], item["type"]) for item in event.data["dependents"]],
                         [(ON_TOP, "des.platform"), (TWIN, "des.fill_only")])
        self.assertEqual(sorted(event.data["datasets"]), sorted([PSF1, EPR1, PRP1]))

    def test_b_what_was_resting_on_it_says_why_in_both_languages(self) -> None:
        """RF-015-17, RF-015-25 (D-12): la causa de lo que se apoyaba en P1 es «Apoyo retirado: se descartó la
        plataforma P1», con su **nombre** (no los datos que cambiaron), para la entidad (P2) y para un diseño
        de la 013 o la 014 («Balsa 2»); en inglés, el suyo; P3, que no se apoyaba en P1 sino en P2, conserva el
        «Obsoleto» de la 008."""
        wanted = f"Apoyo retirado: se descartó la plataforma {BALSA}"
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, "PLT-002"), wanted)
        self.assertEqual(entities.operation_reason(self.project, self.v1.uid, self.fill_uid()), wanted)
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, "PLT-002", language="en"),
                         f"Support removed: the platform {BALSA} was discarded")
        self.assertTrue(entities.stale_reason(self.project, self.v1.uid, "PLT-003").startswith("Obsoleto: "))
        retired = {row.name: row for row in entities.retired_supports(self.project, self.v1.uid)}
        self.assertEqual(sorted(retired), sorted([ON_TOP, TWIN]))
        self.assertEqual([(item.code, item.name, item.roles) for item in retired[ON_TOP].retired],
                         [("PLT-001", BALSA, ("supported_on", "surface"))])
        self.assertEqual([(item.code, item.name, item.roles) for item in retired[TWIN].retired],
                         [("PLT-001", BALSA, ("supported_on",))])
        self.assertEqual(retired[ON_TOP].entity, "PLT-002")
        self.assertIsNone(retired[TWIN].entity)

    def test_b_it_cannot_be_discarded_twice_nor_without_a_reason_nor_if_it_is_not_there(self) -> None:
        """RF-015-17, RF-009-12: P1 ya está descartada (``des.entity_already_discarded``: es un registro); sin
        motivo no se descarta nada (``des.entity_discard_reason``); una entidad que no es de la versión es un
        error del programa; sin escribir nada."""
        before = self.everything()
        with self.assertRaises(DesignError) as caught:
            entity_store.discard_entity(self.project, self.v1.uid, "PLT-001", reason=WHY, decided_by=BY)
        self.assertEqual(caught.exception.code, "des.entity_already_discarded")
        self.assertIn(BALSA, caught.exception.text)
        for blank in ("", "  "):
            with self.assertRaises(DesignError) as missing:
                entity_store.discard_entity(self.project, self.v1.uid, "PLT-003", reason=blank, decided_by=BY)
            self.assertEqual(missing.exception.code, "des.entity_discard_reason")
        with self.assertRaises(ValueError):
            entity_store.discard_entity(self.project, self.v1.uid, "PLT-009", reason=WHY, decided_by=BY)
        self.assertEqual(self.everything(), before)

    # --- (c) «Recalcular lo obsoleto» no lo recalcula ------------------------------------------------

    def test_c_recompute_stale_does_not_recompute_what_lost_its_support(self) -> None:
        """RF-015-17, RF-008-26 (error 59): «Recalcular lo obsoleto» **no recalcula** lo que se apoyaba en P1
        (``core.recompute_no_successor_release``: lo que consumía se descartó y no tiene sucesor): no se crea ninguna
        operación, P2, P3, «Balsa 2» y la verificación siguen obsoletas y en la lista del plan, y P2 sigue en
        «apoyo retirado»."""
        before = self.query("SELECT uid, status FROM gb_operation ORDER BY fid")
        self.assertEqual(len(self.recompute_plan()), 4)
        self.clock.advance(minutes=1)
        outcome = sup.finish(recompute_mod.recompute_steps(self.project))
        first = outcome.results[0]
        self.assertEqual((first.status, first.code), (recompute_mod.UnitStatus.REFUSED, "core.recompute_no_successor_release"))
        self.assertIn("se descartó y no tiene sucesor", first.reason)
        self.assertEqual([result.status for result in outcome.results].count(recompute_mod.UnitStatus.DONE), 0)
        self.assertEqual(self.query("SELECT uid, status FROM gb_operation ORDER BY fid"), before,
                         "ninguna operación nueva")
        self.assertEqual(len(self.recompute_plan()), 4)
        self.assertEqual(self.state_of("PLT-002"), EntityState.SUPPORT_REMOVED)

    # --- (d) Lo que no se puede dar por bueno --------------------------------------------------------

    def test_d_what_cannot_be_given_as_good_is_refused_with_its_reason_and_nothing_is_written(self) -> None:
        """RF-015-17, A7, P-6: P2 **parte** de la superficie de P1 (sin ella no hay sobre qué repetirla: se rehace
        sobre otra superficie o se descarta: ``des.entity_release_start``); P3 no se apoya en P1
        (``des.entity_release_unknown``), ni «Balsa 2» en P2, que no está descartada; sin motivo, nada
        (``des.entity_release_reason``); lo que no existe es un error del programa. Nada se escribe."""
        before = self.everything()

        def refused(target: str, entity: str | None, code: str, reason: str = WHY) -> Any:
            with self.assertRaises(DesignError) as caught:
                entity_store.release_support(self.project, self.v1.uid, target, entity, reason=reason,
                                             decided_by=BY)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(self.everything(), before)
            return caught.exception

        error = refused("PLT-002", "PLT-001", "des.entity_release_start")
        self.assertIn(ON_TOP, error.text)
        self.assertIn(BALSA, error.text)
        refused("PLT-002", None, "des.entity_release_start")
        refused("PLT-003", "PLT-001", "des.entity_release_unknown")
        refused(TWIN, "PLT-002", "des.entity_release_unknown")
        refused("PLT-001", "PLT-001", "des.entity_release_unknown")
        refused(TWIN, "PLT-001", "des.entity_release_reason", reason="  ")
        with self.assertRaises(ValueError):
            entity_store.release_support(self.project, self.v1.uid, "No existe", None, reason=WHY, decided_by=BY)
        with self.assertRaises(ValueError):
            entity_store.release_support(self.project, self.v1.uid, TWIN, "PLT-009", reason=WHY, decided_by=BY)

    # --- (e) Descartar P2 ---------------------------------------------------------------------------

    def test_e_discarding_the_second_platform_lists_what_starts_from_it_and_what_rests_on_it(self) -> None:
        """RF-015-17, D-12: P2, que está en «apoyo retirado», se descarta también (una de las tres salidas: la
        persona la descarta): su lista es **una sola** con P3 (parte de su superficie: sin volumen) y «Balsa 2»
        (con sus m³); quedan P1 y P2 «descartadas», P3 y «Balsa 2» en «apoyo retirado» y hay **dos** eventos."""
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-002")
        self.assertEqual([(row.name, row.entity, row.roles, row.volume_m3 is None) for row in plan.dependents],
                         [(DRAG, "PLT-003", ("surface",), True), (TWIN, None, ("supported_on",), False)])
        self.assertEqual(plan.lines("es")[0], f"{DRAG} (Plataforma): superficie de partida")
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "PLT-002", reason=WHY, decided_by=BY)
        self.assertEqual(sorted(found.datasets), sorted([PSF2, EPR2, provenance.dataset_name("prp", ON_TOP)]))
        self.assertEqual(self.states(), {"PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.DISCARDED,
                                         "PLT-003": EntityState.SUPPORT_REMOVED})
        self.assertEqual([event.data["entity"] for event in self.events(events.EventKind.ENTITY_DISCARDED)],
                         ["PLT-001", "PLT-002"])
        listed = entities.retired_supports(self.project, self.v1.uid)
        self.assertNotIn(ON_TOP, [row.name for row in listed], "una entidad descartada es un registro")
        (twin,) = [row for row in listed if row.name == TWIN]
        self.assertEqual([item.code for item in twin.retired], ["PLT-001", "PLT-002"],
                         "«Balsa 2» ha perdido el apoyo en las dos")
        with self.assertRaises(DesignError) as others:  # soltar una sola dejaría la otra sin dar por buena
            entity_store.release_support(self.project, self.v1.uid, TWIN, "PLT-001", reason=WHY, decided_by=BY)
        self.assertEqual(others.exception.code, "des.entity_release_others")
        self.assertIn(ON_TOP, others.exception.text)

    # --- (f) Rehacerla sobre otra superficie --------------------------------------------------------

    def test_f_remaking_the_platform_on_another_surface_restores_it(self) -> None:
        """RF-015-17: «rehacerla sobre otra superficie» es crearla de nuevo con otra partida y ``supersedes``
        (``platform_run(code=, supersedes=)``, con el parámetro de partida cambiado): P3, que partía de la
        superficie de P2 (descartada), parte ahora del terreno, que P1 y P2, descartadas, ya no ocupan; deja
        de estar en «apoyo retirado», al día y sin la dependencia de P2; lo que se apoya en P2 es ya solo
        «Balsa 2»."""
        old = self.current("PLT-003")
        self.change(design_params.entity_key("PLT-003", "start"), fill_test.START)
        self.clock.advance(minutes=1)
        made = ops_test.finish(steps.platform_run(
            self.project, sup.asked(DRAG, start=fill_test.START), version=self.v1.uid, masks=self.masks_v1,
            code="PLT-003", supersedes=old)).create()
        self.assertNotEqual(made.handle.uid, old)
        self.assertEqual(self.current("PLT-003"), made.handle.uid)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old),
                         [(made.handle.uid,)])
        self.assertEqual(self.state_of("PLT-003"), EntityState.CURRENT)
        self.assertEqual(self.supports_of(made.handle.uid), [])
        self.assertIsNone(entities.stale_reason(self.project, self.v1.uid, "PLT-003"))
        self.assertEqual([row.name for row in entities.dependents(self.project, self.v1.uid, "PLT-002")], [TWIN])
        (rests,) = entities.dependencies_of(self.project, self.v1.uid, "PLT-003")
        self.assertEqual((rests.name, rests.entity), (fill_test.START, None), "parte del terreno")

    # --- (g) La que se descartó con datos llega descartada a la versión hija (T27, hallazgo de la T26) -----

    def test_g_what_was_discarded_with_its_data_arrives_discarded_in_a_version_that_starts_from_it(self) -> None:
        """RF-015-17, RF-015-18, RF-009-01, D-12 (hallazgo (a) de la T26, decisión de la sesión principal en la
        T27): descartar una entidad **calculada** escribe también su parámetro de versión ``discarded`` (verdadero,
        con su historial), no solo los estados de sus datos: la versión hija que hereda los parámetros (RF-009-01,
        sin resultados) la recibe **descartada** —sin ocupar su partida ni su nombre— y no «viva y sin calcular»,
        y «Traer las entidades de…» no la trae. Lo que sigue vivo (P3, rehecha en (f)) llega «sin calcular»."""
        store = core_params.ParameterStore(self.project)
        for code, why in (("PLT-001", WHY), ("PLT-002", WHY)):
            key = design_params.entity_key(code, "discarded")
            found = store.get(key, version=self.v1.uid)
            self.assertIsNotNone(found, f"{code}: sin el parámetro, una versión hija la recibe viva")
            self.assertIs(found.value, True)
            self.assertEqual((found.decided_by, found.kind.name), (BY, "ADOPTADO"))
            (entry,) = store.history(key, version=self.v1.uid)
            self.assertEqual(entry.reason, why)
        self.assertEqual(self.states(), {"PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.DISCARDED,
                                         "PLT-003": EntityState.CURRENT})
        self.clock.advance(minutes=1)
        child = create_version(self.project, feature="Hija", title="Hija de V01", parent="V01")
        mine = {entry.record.code: entry.record.state for entry in entities.registry(self.project, child.uid)}
        self.assertEqual(mine, {"PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.DISCARDED,
                                "PLT-003": EntityState.UNCALCULATED})
        with self.assertRaises(DesignError) as asked:
            entity_store.bring_entities(self.project, "V01", "V02", codes=["PLT-001"])
        self.assertEqual(asked.exception.code, "des.entity_bring_discarded")
        brought = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual([item.source_code for item in brought.entities], ["PLT-003"], "la descartada no se trae")


# ---------------------------------------------------------------------------------------------
# Dar por bueno (A7, P-6): una plataforma que lo declara y un «solo relleno», sin partir de P1
# ---------------------------------------------------------------------------------------------


class ReleaseTest(DiscardCase, sup.SupportsCase):
    """RF-015-17, A7, P-6, RF-008-26, RF-008-27, RF-009-12: P1 (la «Plataforma de la balsa»), el «taller»
    (PLT-002, de otro terreno, que **declara** que se apoya en P1: 0 m³) y «Balsa 2» (un «solo relleno» que rellena
    sobre P1) con **su verificación**. Ninguno parte de la superficie de P1: descartada P1 se pueden dar por
    buenos sin ella. En el orden de las pruebas: (a) la lista, (b) descartar P1, (c) soltar el apoyo de la
    plataforma, (d) un recálculo después, (e) el del «solo relleno» y lo que dependía de él y (f) los eventos."""

    twin: ClassVar[Any]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return dep.DependentsCase.definitions()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            fill_test.declare(cls.project, cls.clock, design_params.bench_key(fill_test.REST.code, param),
                              getattr(fill_test.REST, param))
        envelope = model.EnvelopeRequest(
            fill_test.ENVELOPE, "down",
            model.SeedSource("fixed", zone=model.Zone("layer", qfx.WATER_LAYER),
                             elevation_m=fill_test.ENVELOPE_LEVEL_M),
            slope_deg=fill_test.ENVELOPE_SLOPE_DEG)
        cls.clock.advance(minutes=1)
        fill_test.drive(steps.envelope_run(cls.project, envelope, version=cls.v1.uid,
                                           masks=cls.masks_v1)).result.create()
        cls.made(sup.asked(BALSA))
        cls.made(prep.request(WORKSHOP, start=prep.HOLE_DATASET))
        cls.declare("PLT-002", "PLT-001")
        cls.clock.advance(minutes=1)
        _handle, work = design_store.recompute_run(cls.request_of(cls.current_uid("PLT-002")))
        sup.finish(work)
        cls.clock.advance(minutes=1)
        cls.twin = fill_test.drive(steps.fill_only_run(
            cls.project, model.FillOnlyRequest(TWIN, fill_test.ENVELOPE, fill_test.START, fill_test.REST.code,
                                               water=fill_test.WATER),
            version=cls.v1.uid, masks=cls.masks_v1)).result.create()
        cls.clock.advance(minutes=1)
        sup.finish(cstore.verify_project_steps(
            cls.project, version=cls.v1.uid, name=TWIN_CHECK,
            start=surfaces.SurfaceRef(dataset=fill_test.START, label="Partida"),
            finals=(surfaces.SurfaceRef(dataset=TWIN_SURFACE, label=TWIN),)))

    @classmethod
    def declare(cls, code: str, text: str) -> None:
        """Declara en la versión que la entidad ``code`` se apoya en ``text`` (como lo hace la T23)."""
        cls.clock.advance(minutes=1)
        key = design_params.entity_key(code, "supports")
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, key, text, kind="ADOPTADO", source="Prueba de la T25", source_kind="person",
                decided_by=BY, reason="Dependencia declarada", version=cls.v1.uid)

    @classmethod
    def current_uid(cls, code: str) -> str:
        entry = entities.registry(cls.project, cls.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    @classmethod
    def request_of(cls, uid: str) -> Any:
        ((settings,),) = cls.query_of("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(cls.project, uid, provenance.PLATFORM, json.loads(settings),
                                              (), (), version=cls.v1.uid)

    def fill_op(self) -> str:
        """El uid de la operación vigente de «Balsa 2»."""
        ((uid,),) = self.query("SELECT o.uid FROM gb_operation AS o WHERE o.op_type = 'des.fill_only' AND "
                               "o.status = 'done' AND o.superseded_by IS NULL")
        return str(uid)

    def check_op(self) -> str:
        """El uid de la verificación vigente de «Balsa 2»."""
        ((uid,),) = self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND "
                               "superseded_by IS NULL", cstore.VERIFY)
        return str(uid)

    def test_a_two_things_rest_on_the_first_platform_without_starting_from_it(self) -> None:
        """RF-015-17, D-11: sobre P1 están el taller (declarado: **0 m³**, ni un metro apoyado) y «Balsa 2» (con
        los suyos), los dos solo ``supported_on``: ninguno parte de su superficie, así que se pueden dar por
        buenos sin ella; una sola lista, en el orden de registro."""
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual([(row.name, row.roles) for row in plan.dependents],
                         [(WORKSHOP, ("supported_on",)), (TWIN, ("supported_on",))])
        self.assertEqual(plan.dependents[0].volume_m3, 0.0)
        self.assertGreater(plan.dependents[1].volume_m3, 100.0)
        self.assertEqual(plan.lines("es")[0], f"{WORKSHOP} (Plataforma): 0 m³ apoyados")
        self.assertEqual(self.stale_causes(self.check_op()), set())

    def test_b_discarding_the_first_platform_leaves_both_in_support_removed(self) -> None:
        """RF-015-17, RF-009-12: descartada P1, el taller (una entidad) y «Balsa 2» (un diseño) quedan en
        «apoyo retirado» y la verificación de «Balsa 2», obsoleta en cascada; ninguna operación nueva."""
        operations = self.query("SELECT uid, status FROM gb_operation ORDER BY fid")
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "PLT-001", reason=WHY, decided_by=BY)
        self.assertEqual(self.states(), {"PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.SUPPORT_REMOVED})
        self.assertEqual(sorted((row.name, row.op_type) for row in entities.retired_supports(
            self.project, self.v1.uid)), [(TWIN, "des.fill_only"), (WORKSHOP, "des.platform")])
        self.assertNotEqual(self.stale_causes(self.check_op()), set(), "la verificación de «Balsa 2»: en cascada")
        self.assertEqual(self.query("SELECT uid, status FROM gb_operation ORDER BY fid"), operations)

    def test_c_a_closing_the_steps_before_the_end_leaves_no_event_and_the_old_operation_in_place(self) -> None:
        """RF-015-17, RF-015-29 (Esc): si los pasos de «dar por bueno» se cierran antes de acabar, no queda el evento
        (se registra al completarse), la operación nueva queda «cancelada», la anterior sigue vigente y sin
        sustituir, sin ningún temporal."""
        old = self.fill_op()
        written = self.written()
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, TWIN, None, reason=WHY,
                                                    decided_by=BY)
        next(work)
        work.close()
        self.assertEqual(self.fill_op(), old)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid), [("cancelled",)])
        self.assertEqual(self.events(events.EventKind.SUPPORT_RELEASED), [])
        self.assertFalse([name for name in self.written()["files"] if ".tmp-" in name])
        self.assertEqual(self.written()["datasets"], written["datasets"])
        self.clock.advance(minutes=1)  # y sin llegar a empezar: la operación abierta queda «cancelada», no «en curso»
        idle, never = entity_store.release_support(self.project, self.v1.uid, TWIN, None, reason=WHY, decided_by=BY)
        never.close()
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", idle.uid), [("cancelled",)])
        self.assertEqual(self.fill_op(), old)
        self.assertEqual(self.events(events.EventKind.SUPPORT_RELEASED), [])

    def test_c_giving_the_platform_as_good_repeats_it_without_that_support_and_its_output_does_not_change(
            self) -> None:
        """RF-015-17, A7, P-6, RF-008-27: «dar por buena» el taller es **repetirla con ``supersedes``** sin el apoyo
        en P1 (que ya no está: lo declarado se salta, no se rechaza), con el motivo y el decisor en sus ajustes
        (``supports_released``) y **un evento**: su salida **no cambia** (los mismos hash), sale de «apoyo
        retirado» y de la lista de lo apoyado en P1, y el parámetro que lo declaraba sigue como lo puso la
        persona."""
        old = self.current_uid("PLT-002")
        hashes = self.hashes_of(old)
        self.assertIsNone(self.settings_of(old).get("supports_released"))
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, "PLT-002", "PLT-001",
                                                    reason=WHY, decided_by=BY)
        sup.finish(work)
        new = handle.uid
        self.assertNotEqual(new, old)
        self.assertEqual(self.current_uid("PLT-002"), new)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old), [(new,)])
        self.assertEqual(self.state_of("PLT-002"), EntityState.CURRENT)
        self.assertEqual(self.hashes_of(new), hashes, "su salida no cambia")
        self.assertEqual(self.supports_of(new), [])
        self.assertEqual(self.volumes_of(new), {})
        (released,) = self.settings_of(new)["supports_released"]
        self.assertEqual({key: released[key] for key in ("entity", "reason", "by")},
                         {"entity": "PLT-001", "reason": WHY, "by": BY})
        self.assertRegex(released["when"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        (event,) = self.events(events.EventKind.SUPPORT_RELEASED)
        self.assertEqual((event.entity_kind, event.entity_uid), ("operation", new))
        self.assertEqual({key: event.data[key] for key in ("version", "name", "reason", "decided_by", "operation",
                                                           "superseded", "entities")},
                         {"version": "V01", "name": WORKSHOP, "reason": WHY, "decided_by": BY, "operation": new,
                          "superseded": old, "entities": ["PLT-001"]})
        self.assertIn(WORKSHOP, event.message)
        self.assertIn(WHY, event.message)
        key = design_params.entity_key("PLT-002", "supports")
        self.assertEqual(core_params.ParameterStore(self.project).get(key, version=self.v1.uid).value, "PLT-001")
        self.assertEqual([row.name for row in entities.dependents(self.project, self.v1.uid, "PLT-001")], [TWIN])
        self.assertEqual([row.name for row in entities.retired_supports(self.project, self.v1.uid)], [TWIN])

    def test_d_a_later_recompute_keeps_the_release_and_does_not_register_it_again(self) -> None:
        """RF-015-17, A7, ADR-0030 §4: recalcular el taller **después** (un recálculo normal, sin soltar nada)
        conserva lo que se soltó —sigue en sus ajustes, acumulada— y no vuelve a pedirle a lo declarado la
        entidad descartada (``des.entity_supports_unknown``) ni a registrarla como apoyo."""
        old = self.current_uid("PLT-002")
        released = self.settings_of(old)["supports_released"]
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_of(old))
        sup.finish(work)
        self.assertEqual(self.settings_of(handle.uid)["supports_released"], released)
        self.assertEqual(self.supports_of(handle.uid), [])
        self.assertEqual(self.state_of("PLT-002"), EntityState.CURRENT)

    def test_e_giving_the_fill_only_as_good_does_not_recompute_what_depended_on_it(self) -> None:
        """RF-015-17, A7, RF-008-26: «dar por bueno» «Balsa 2» (sin indicar la entidad: todas las que perdió, aquí
        P1) repite el «solo relleno» con ``supersedes`` sin ese apoyo: su superficie y su informe salen **con los
        mismos hash**, así que su verificación **no se recalcula** —sigue siendo la misma operación— y deja de
        estar obsoleta; ya no queda nada que recalcular ni en «apoyo retirado»."""
        old, check = self.fill_op(), self.check_op()
        hashes = self.hashes_of(old)
        self.assertGreater(len(self.supports_of(old)), 0)
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, TWIN, None, reason=WHY,
                                                    decided_by=BY)
        sup.finish(work)
        new = handle.uid
        self.assertEqual(self.fill_op(), new)
        self.assertEqual(self.hashes_of(new), hashes, "su salida no cambia")
        self.assertEqual(self.supports_of(new), [])
        self.assertEqual(self.volumes_of(new), {})
        (released,) = self.settings_of(new)["supports_released"]
        self.assertEqual((released["entity"], released["reason"], released["by"]), ("PLT-001", WHY, BY))
        self.assertEqual(self.stale_causes(new), set())
        self.assertEqual(self.check_op(), check, "lo que dependía de ella no se recalcula")
        self.assertEqual(self.stale_causes(check), set(), "y deja de estar obsoleto: su entrada es la misma")
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "PLT-001"), ())
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())

    def test_f_each_release_left_its_event_and_nothing_was_deleted(self) -> None:
        """RF-009-12, RF-015-17: dos eventos ``support_released`` (el taller y «Balsa 2»), cada uno con su motivo
        y su decisor; los datos de P1 siguen descartados, no borrados."""
        found = self.events(events.EventKind.SUPPORT_RELEASED)
        self.assertEqual([event.data["name"] for event in found], [WORKSHOP, TWIN])
        self.assertEqual({event.data["reason"] for event in found}, {WHY})
        self.assertEqual(set(self.dataset_status(PSF1, EPR1, PRP1).values()), {"discarded"})
        self.assertTrue((self.root / self.locator(PSF1)).is_file())


class ReleasedLiveEntityTest(DiscardCase, sup.SupportsCase):
    """RF-015-17, A7, ADR-0030 §4: lo que se suelta **no vuelve a registrarse** aunque la entidad siga viva (lo que
    habrá con la retirada de un acopio de la 016): P1 (la «Plataforma de la balsa») y «Balsa 2», que rellena sobre
    ella. Repetir «Balsa 2» soltando P1 no lleva sus entradas ni su cifra, y un recálculo después, que sí detectaría
    P1 (sigue viva y «Balsa 2» sigue rellenando sobre ella), tampoco: lo soltado va en sus ajustes."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return dep.DependentsCase.definitions()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            fill_test.declare(cls.project, cls.clock, design_params.bench_key(fill_test.REST.code, param),
                              getattr(fill_test.REST, param))
        envelope = model.EnvelopeRequest(
            fill_test.ENVELOPE, "down",
            model.SeedSource("fixed", zone=model.Zone("layer", qfx.WATER_LAYER),
                             elevation_m=fill_test.ENVELOPE_LEVEL_M),
            slope_deg=fill_test.ENVELOPE_SLOPE_DEG)
        cls.clock.advance(minutes=1)
        fill_test.drive(steps.envelope_run(cls.project, envelope, version=cls.v1.uid,
                                           masks=cls.masks_v1)).result.create()
        cls.made(sup.asked(BALSA))
        cls.clock.advance(minutes=1)
        fill_test.drive(steps.fill_only_run(
            cls.project, model.FillOnlyRequest(TWIN, fill_test.ENVELOPE, fill_test.START, fill_test.REST.code,
                                               water=fill_test.WATER),
            version=cls.v1.uid, masks=cls.masks_v1)).result.create()

    def fill_op(self) -> str:
        ((uid,),) = self.query("SELECT uid FROM gb_operation WHERE op_type = 'des.fill_only' AND status = 'done' "
                               "AND superseded_by IS NULL")
        return str(uid)

    def request(self, uid: str) -> Any:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, "des.fill_only", json.loads(settings), (), (),
                                              version=self.v1.uid)

    def test_a_what_is_released_is_neither_carried_nor_registered_again_by_the_hook(self) -> None:
        """RF-015-17, A7, ADR-0030 §4: «Balsa 2» rellena sobre P1, que está viva: sin soltar nada se apoya en ella
        (las entradas y la cifra); repetida **soltando** P1 (``recompute_run(released=…)``) no lleva sus entradas
        (``carried``) ni su cifra (el gancho no la detecta) y deja lo soltado en sus ajustes; un recálculo normal
        después —P1 sigue viva y «Balsa 2» sigue rellenando sobre ella— tampoco la vuelve a registrar; el estado de
        P1 no cambia."""
        first = self.fill_op()
        self.assertEqual([name for name, _role in self.supports_of(first)], [PSF1, EPR1])
        self.assertEqual(list(self.volumes_of(first)), ["PLT-001"])
        released = provenance.ReleasedSupport("PLT-001", WHY, BY, "2026-11-15T10:00:00Z")
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request(first), released=(released,))
        sup.finish(work)
        self.assertEqual(self.supports_of(handle.uid), [])
        self.assertEqual(self.volumes_of(handle.uid), {})
        self.assertEqual(self.settings_of(handle.uid)["supports_released"], [released.settings()])
        self.clock.advance(minutes=1)
        again, work = design_store.recompute_run(self.request(handle.uid))
        sup.finish(work)
        self.assertEqual(self.supports_of(again.uid), [], "el gancho no la vuelve a registrar")
        self.assertEqual(self.volumes_of(again.uid), {})
        self.assertEqual(self.settings_of(again.uid)["supports_released"], [released.settings()])
        self.assertEqual(self.state_of("PLT-001"), EntityState.CURRENT)
        with self.assertRaises(ValueError):  # lo que no deja una superficie que se apoye en una entidad
            design_store.recompute_run(recompute_mod.RecomputeRequest(
                self.project, "uid", "des.envelope", {}, (), (), version=self.v1.uid), released=(released,))


# ---------------------------------------------------------------------------------------------
# La restricción de una entidad descartada y descartar sin calcular
# ---------------------------------------------------------------------------------------------


class DiscardedConstraintTest(DiscardCase, chain_test.ChainCase):
    """RF-015-17, RF-015-10, RF-012-06, D-12, CE-015-04: P1 (que no protege) y P2 (que protege 4 m, de la
    superficie de P1) con su declaración y sus máscaras. Descartar P2 y lo que sigue (``after_entity_change``)
    **quita su restricción de las máscaras**; y descartar una entidad **sin calcular** no toca ningún dato."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.chain()
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=chain_test.GUARD_M))
        cls.chain()
        cls.settle()

    def zone(self) -> np.ndarray:
        """Las celdas de la zona de la restricción declarada por P2 en las máscaras vigentes."""
        masks = access.load_masks(self.project, self.v1.uid)
        return np.asarray(masks.zone(chain_test.CODE).mask(masks.classes.shape))

    def test_a_before_discarding_the_restriction_of_the_platform_is_in_the_masks(self) -> None:
        """RF-015-10: P2 declara su restricción (``dec__plt_002``, «sin relleno») y las máscaras tienen su zona,
        en la que no se admite el relleno."""
        self.assertEqual([row.code for row in self.declared()], [chain_test.CODE])
        zone = self.zone()
        self.assertTrue(zone.any())
        self.assertFalse(access.load_masks(self.project, self.v1.uid).fill_allowed()[zone].any())

    def test_b_discarding_it_takes_its_restriction_out_of_the_declaration_and_the_masks(self) -> None:
        """RF-015-17, RF-015-10, RF-012-06, CE-015-04: descartar P2 (nada se borra: su tabla sigue) y lo que sigue
        (``after_entity_change``) **declara de nuevo** sin ella (la tabla vacía), **compila las máscaras** de nuevo
        y su zona **sale** (``KeyError``): el relleno se admite otra vez donde protegía, y el informe dice lo
        perdido por esa restricción."""
        zone = self.zone()
        table = self.record(provenance.dataset_name("epr", WORKSHOP), self.v1).locator
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "PLT-002", reason=WHY, decided_by=BY)
        self.assertEqual(found.code, "PLT-002")
        self.assertEqual(self.states()["PLT-002"], EntityState.DISCARDED)
        chain = self.chain()
        self.assertIsNone(chain.failure)
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (0, True, True))
        self.assertEqual(self.declared(), (), "la declaración ya no la lleva")
        masks = access.load_masks(self.project, self.v1.uid)
        with self.assertRaises(KeyError):
            masks.zone(chain_test.CODE)
        self.assertTrue(masks.fill_allowed()[zone].any(), "el relleno se admite otra vez en su zona")
        lost = [change for change in chain.changes if change.code == chain_test.CODE]
        self.assertEqual(len(lost), 1)
        self.assertGreater(lost[0].zone_lost_m2, 0.0)
        self.assertEqual(self.query(f'SELECT count(*) FROM "{table}"'), [(1,)], "nada se borra: su tabla sigue")

    def test_c_discarding_an_uncalculated_entity_sets_its_flag_and_touches_no_data(self) -> None:
        """RF-015-17, RF-009-12, D-12: una entidad **sin calcular** (lo que deja «Traer las entidades de…»: sus
        parámetros y ninguna operación) no tiene datos que descartar: se descarta con el parámetro de versión
        ``des.platform.{e}.discarded`` (``true``, con su historial: quién, por qué y cuándo) y un evento; el
        registro la da por «descartada», su lista está vacía, no cambia ningún dato ni operación y su código
        **no se reutiliza**."""
        for param, value in (("name", "Sin calcular"), ("start", "entity:PLT-001")):
            self.create_param(design_params.entity_key("PLT-003", param), value)
        self.assertEqual(self.state_of("PLT-003"), EntityState.UNCALCULATED)
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-003")
        self.assertEqual((plan.calculated, plan.state, plan.dependents), (False, EntityState.UNCALCULATED, ()))
        before = self.everything()
        key = design_params.entity_key("PLT-003", "discarded")
        self.assertIsNone(core_params.ParameterStore(self.project).get(key, version=self.v1.uid))
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "PLT-003", reason=WHY, decided_by=BY)
        self.assertEqual((found.code, found.operation_uid, found.datasets, found.dependents),
                         ("PLT-003", None, (), ()))
        self.assertEqual(self.state_of("PLT-003"), EntityState.DISCARDED)
        after = self.everything()
        for what in ("operations", "datasets", "io", "figures", "tables", "files"):
            self.assertEqual(after[what], before[what], what)
        record = core_params.ParameterStore(self.project).get(key, version=self.v1.uid)
        self.assertIs(record.value, True)
        self.assertEqual((record.decided_by, record.kind.name), (BY, "ADOPTADO"))
        (entry,) = core_params.ParameterStore(self.project).history(key, version=self.v1.uid)
        self.assertEqual(entry.reason, WHY)
        (event,) = [item for item in self.events(events.EventKind.ENTITY_DISCARDED)
                    if item.data["entity"] == "PLT-003"]
        self.assertIsNone(event.data["operation"])
        self.assertEqual(event.data["datasets"], [])
        self.assertEqual(entities.next_code(entities.EntityKind.PLATFORM, self.states()), "PLT-004",
                         "su código no se reutiliza")
        with self.assertRaises(DesignError) as again:
            entity_store.discard_entity(self.project, self.v1.uid, "PLT-003", reason=WHY, decided_by=BY)
        self.assertEqual(again.exception.code, "des.entity_already_discarded")

    def test_d_the_steps_discard_and_chain_what_follows_in_one_call_and_write_nothing_before_the_first_step(
            self) -> None:
        """RF-015-17, RF-015-10, RF-015-29 (plan 015 §5.3.2): ``discard_entity_steps`` descarta (a partir del segundo
        paso: el primero solo dice que empieza y antes no se escribe nada) y encadena ``after_entity_change`` por
        pasos; el último trae el ``DiscardResult`` con lo descartado y la cadena (declara de nuevo, sin fallo)."""
        before = self.everything()
        work = entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-001", reason=WHY, decided_by=BY)
        self.assertEqual(self.everything(), before, "sin avanzar no se escribe nada")
        self.clock.advance(minutes=1)
        result = ops_test.finish(work)
        self.assertIsInstance(result, entity_store.DiscardResult)
        self.assertEqual((result.discarded.code, result.discarded.reason), ("PLT-001", WHY))
        self.assertIsNone(result.chain.failure)
        self.assertEqual(result.chain.declared, 0)
        self.assertEqual(self.states()["PLT-001"], EntityState.DISCARDED)
        self.assertEqual([event.data["entity"] for event in self.events(events.EventKind.ENTITY_DISCARDED)],
                         ["PLT-002", "PLT-003", "PLT-001"])
        stopped = entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-009", reason=WHY, decided_by=BY)
        next(stopped)  # el primer paso solo dice que empieza
        with self.assertRaises(ValueError):  # una entidad que no es de la versión: error del programa, sin escribir
            next(stopped)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
