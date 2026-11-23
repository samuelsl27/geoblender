# SPDX-License-Identifier: GPL-3.0-or-later
"""Recalcular la corta, «Cambiar parámetro…» y traerla a otra versión, con el proyecto (spec 018, T24; HU-018-5; RF-018-03; RF-015-07 a RF-015-09, RF-015-16, RF-015-18; plan 018 §5.2.3 y §5.3.2), como
prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene la suya, sin proyecto, en ``test_pit_recompute.py``.

Sobre el proyecto de las cortas (rejilla de 2 m, 200 × 200 celdas) con la corta ascendente ``PIT-001`` creada en V01:

- **Recalcular** (:class:`RecomputeTest`): repetirla sin cambiar nada da una operación nueva que sustituye a la anterior con los mismos datos bit a bit y las mismas cifras, sin escribir otra vez los
  parámetros; **cambiar un valor del perfil** o **el perfil de un sector** la deja obsoleta con su causa y «Recalcular lo obsoleto» da lo que daría crearla de nuevo; un parámetro que cambia entre
  prepararla y empezarla se rechaza (``des.input_changed``).
- **«Cambiar parámetro…»** (:class:`ParameterTest`): la fila del proyecto del nombre existe (la crea «Crear») y un nombre repetido se rechaza.
- **Traerla a otra versión** (:class:`BringTest`): queda **sin calcular**, con sus valores por sector, y se calcula traída con su código.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from unittest import mock

from tests.support import pit_data as pd
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_prepare_checks as checks
from tests.unit.design.milestone_pit_create import BY, NAME, CreateCase
from tests.unit.design.milestone_pit_prepare_checks import CODE, request

core_params = import_geoblender("core.params")
gis = import_geoblender("gis")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")

SEG = "sector_1"
FACE = "des.bench.expl_10_60_6.face_deg"
OTHER_PROFILE = "expl_10_45_6"
"""Un perfil de la misma altura y ancla que ``EXPL_10_60_6``, con otro ángulo de cara: lo que admite un sector."""
SECTOR_PROFILE = f"des.pit.pit_001.profile.{SEG}"


def finish_steps(work: Any) -> Any:
    found = None
    for step in work:
        found = step.result if step.result is not None else found
    return found


def recompute_function(request_: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``des.pit``: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request_)
    finish_steps(work)
    return handle


class RecomputeCase(CreateCase):
    @classmethod
    def setUpClass(cls) -> None:
        patcher = mock.patch.object(checks, "never", recompute_function)
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        parameters = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for param, value in (("height_m", 10.0), ("face_deg", 45.0), ("berm_m", 6.0), ("anchor_m", 125.0), ("mesh_factor", 1.0)):
                parameters.create(conn, design_params.bench_key(OTHER_PROFILE, param), value, kind="ADOPTADO" if param == "mesh_factor" else "HIPÓTESIS", reason="Perfil de la prueba",
                                  **checks.BY_HAND)
        cls.clock.advance(minutes=1)
        res_fixtures.write_grids(cls.project, [(label, gis.Raster(checks.GRID, pd.flat_terrain(checks.GRID), pd.CRS, pd.VERTICAL)) for label in ("corta_llano_b", "corta_llano_c")],
                                 message="Otros terrenos llanos, iguales al de partida: de cada superficie parte una sola entidad")
        cls.clock.advance(minutes=1)

    def current(self, code: str) -> str:
        entry = entities.registry(self.project, self.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def request_for(self, uid: str) -> Any:
        ((op_type, settings),) = self.query("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, op_type, json.loads(settings), (), (), version=self.v1.uid)

    def change(self, key: str, value: Any) -> None:
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(conn, key, value=value, source="prueba de recalcular (T24)", source_kind="person", decided_by=BY,
                                                            reason="Se cambia un parámetro de la corta", version=self.v1.uid)

    def recompute_all(self) -> list[str]:
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * len(outcome.results))
        return [str(uid) for result in outcome.results for uid in result.operations]

    def supersedes(self, uid: str) -> list[tuple[Any, ...]]:
        return self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", uid)

    def parameters(self) -> list[tuple[Any, ...]]:
        return self.query("SELECT key, value, rev, decided_by FROM gb_parameter WHERE key LIKE 'des.pit.%' ORDER BY key, scope")

    def create_pit(self, name: str, start: str = "gis_dtm_corta_llano_b", **changes: Any) -> str:
        self.clock.advance(minutes=1)
        return self.uid(self.calculate(request(name, start=start, **changes)).create(decided_by=BY))


class RecomputeTest(RecomputeCase):
    """RF-018-03, RF-015-02, RF-015-16, RF-008-26: recalcular la corta. **En orden** (``test_a`` a ``test_d``): cada una parte de lo que dejó la anterior."""

    first: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.first = cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))

    def test_a_recomputing_without_changing_anything_gives_the_same(self) -> None:
        """RF-015-02, RF-015-16: «Recalcular» ``PIT-001`` sin cambiar nada es una operación nueva que sustituye a la anterior, con los mismos ajustes, entradas, **datos bit a bit** y cifras; no escribe otra
        vez los parámetros y es la vigente, al día."""
        old = self.current(CODE)
        parameters = self.parameters()
        before = (self.outputs(old), self.inputs(old), self.figures_of(old), self.query("SELECT settings FROM gb_operation WHERE uid = ?", old))
        hashes = self.hashes_of(old)  # antes: el dato se sustituye y la operación vieja pasa a apuntar al nuevo
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(old))
        stored = finish_steps(work)
        new = str(handle.uid)
        self.assertEqual(self.supersedes(new), [(old, "done")])
        self.assertEqual(str(stored.handle.uid), new)
        self.assertEqual(self.current(CODE), new)
        self.assertEqual([row[0] for row in self.outputs(new)], [row[0] for row in before[0]])
        self.assertEqual(self.hashes_of(new), hashes, "lo recalculado es igual bit a bit")
        self.assertEqual(self.figures_of(new), before[2])
        self.assertEqual(set(self.inputs(new)), set(before[1]))
        self.assertEqual(self.query("SELECT settings FROM gb_operation WHERE uid = ?", new), before[3])
        self.assertEqual(self.parameters(), parameters, "un recálculo no escribe otra vez los parámetros de la entidad")
        self.assertEqual(self.stale_causes(new), set())
        self.assertEqual(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", new), [(provenance.PIT,)])
        RecomputeTest.first = new

    def hashes_of(self, uid: str) -> list[str]:
        return [str(row[0]) for row in self.query(
            "SELECT d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out' "
            "AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def test_b_a_changed_profile_value_makes_it_stale_and_recomputing_gives_what_creating_again_would(self) -> None:
        """RF-015-16, RF-008-26, RF-018-06: cambiar un valor del perfil (el ángulo de cara) deja obsoleta la corta **con su causa**; «Recalcular lo obsoleto» la repite con lo nuevo y da **lo que daría
        crearla de nuevo**: una corta gemela creada con el valor nuevo tiene la misma superficie bit a bit."""
        old = self.current(CODE)
        hashes = self.hashes_of(old)
        self.change(FACE, 50.0)
        self.assertIn(("parameter_changed", FACE), self.stale_causes(old))
        self.assertEqual(self.recompute_plan(), [(provenance.PIT,)])
        self.clock.advance(minutes=1)
        (made,) = self.recompute_all()
        self.assertEqual(self.supersedes(made), [(old, "done")])
        self.assertEqual(self.stale_causes(made), set())
        self.assertEqual(self.recompute_plan(), [])
        twin = self.create_pit("Corta gemela")
        self.assertEqual(self.hashes_of(made)[0], self.hashes_of(twin)[0], "la superficie recalculada es la de crearla de nuevo")
        self.assertNotEqual(self.hashes_of(made)[0], hashes[0], "el valor nuevo cambió el resultado")

    def test_c_a_sector_value_makes_it_stale_and_is_read_when_recomputing(self) -> None:
        """RF-018-06, RF-015-16: el perfil de un sector (el perímetro, ``perimeter__``) es un valor de la entidad: cambiarlo deja obsoleta la corta con su causa y recalcular lo lee."""
        self.create_pit("Corta con sector", "gis_dtm_corta_llano_c", sector_profiles={SEG: "expl_10_60_6"})
        code = "PIT-003"
        old = self.current(code)
        key = f"des.pit.pit_003.profile.{SEG}"
        self.assertEqual(core_params.ParameterStore(self.project).get(key, version=self.v1.uid).value, "expl_10_60_6")
        self.change(key, OTHER_PROFILE)
        self.assertIn(("parameter_changed", key), self.stale_causes(old))
        self.clock.advance(minutes=1)
        made = [uid for uid in self.recompute_all() if self.query("SELECT 1 FROM gb_operation WHERE uid = ? AND supersedes_uid = ?", uid, old)]
        self.assertEqual(len(made), 1)
        self.assertEqual(self.stale_causes(made[0]), set())
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", made[0])
        asked = provenance.pit_request(json.loads(settings), pit_store.pit_parameters(self.project, self.v1, code))
        self.assertEqual(asked.sector_profiles, ((SEG, OTHER_PROFILE),))

    def test_d_a_parameter_that_changes_while_starting_is_refused(self) -> None:
        """RF-013-17, D-14: un parámetro que cambia entre prepararla y empezar la operación se rechaza al avanzar con ``des.input_changed`` y la que sustituye sigue vigente."""
        old = self.current(CODE)
        prepared = pit_store.prepare_pit(self.project, request(), version=self.v1.uid, masks=self.masks_v1, code=CODE, supersedes=old)
        key = f"des.pit.pit_001.{design_params.PitParam.ARC_TOL.value}"
        self.change(key, 0.07)
        self.clock.advance(minutes=1)
        handle = prepared.start.begin(self.project)
        work = pit_store._pit_run(self.project, handle, prepared, (), old, 0.2)
        with self.assertRaises(messages.DesignError) as caught:
            finish_steps(work)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertEqual(self.current(CODE), old)


class ParameterTest(RecomputeCase):
    """RF-015-08, RF-015-01: «Cambiar parámetro…» de una corta."""

    def test_the_name_row_of_the_project_exists_and_a_repeated_name_is_refused(self) -> None:
        self.create_pit(NAME)
        key = f"des.pit.pit_001.{design_params.PitParam.NAME.value}"
        self.assertIsNotNone(core_params.ParameterStore(self.project).get(key), "«Cambiar parámetro…» pide la fila del proyecto del nombre")
        self.create_pit("Otra corta", "gis_dtm_corta_llano_c")
        with self.assertRaises(messages.DesignError) as caught:
            entity_store.check_parameter_change(self.project, "des.pit.pit_002.name", NAME, version=self.v1.uid)
        self.assertEqual(caught.exception.code, "des.entity_name_repeated")
        with self.assertRaises(messages.DesignError) as caught:
            entity_store.check_parameter_change(self.project, key, "", version=self.v1.uid)
        self.assertEqual(caught.exception.code, "des.entity_param_missing")


class BringTest(RecomputeCase):
    """RF-015-18, RF-009-01: traer una corta a otra versión y calcularla traída."""

    def test_brought_it_is_uncalculated_with_its_sector_values_and_is_calculated_with_its_code(self) -> None:
        self.create_pit(NAME, sector_profiles={SEG: "expl_10_60_6"})
        self.clock.advance(minutes=1)
        brought = entity_store.bring_entities(self.project, self.v1, self.v2, codes=[CODE])
        (item,) = brought.entities
        self.assertEqual(item.code, CODE)
        entry = entities.registry(self.project, self.v2.uid).get(CODE)
        self.assertEqual(entry.record.state, entities.EntityState.UNCALCULATED)
        parameters = core_params.ParameterStore(self.project)
        self.assertEqual(parameters.get(f"des.pit.pit_001.profile.{SEG}", version=self.v2.uid).value, "expl_10_60_6")
        self.assertIsNotNone(parameters.get("des.pit.pit_001.name"), "la fila del proyecto del nombre")
        asked = pit_store.entity_pit_request(self.project, self.v2, CODE)
        self.assertEqual((asked.name, asked.layer, asked.sector_profiles), (NAME, checks.FLOORS, ((SEG, "expl_10_60_6"),)))
        calculation = finish_steps(steps.pit_run(self.project, asked, version=self.v2.uid, code=CODE))
        stored = calculation.create(decided_by=BY)
        self.assertEqual(entities.registry(self.project, self.v2.uid).get(CODE).record.state, entities.EntityState.CURRENT)
        self.assertEqual(str(stored.handle.uid), str(entities.registry(self.project, self.v2.uid).get(CODE).operation_uid))
        with self.assertRaises(messages.DesignError) as caught:
            pit_store.entity_pit_request(self.project, self.v2, CODE)
        self.assertEqual(caught.exception.code, "des.entity_calculate_done")
