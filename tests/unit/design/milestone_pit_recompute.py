# SPDX-License-Identifier: GPL-3.0-or-later
"""Recalcular la corta, «Cambiar parámetro…» y traerla a otra versión, con el proyecto (spec 018, T24; HU-018-5; RF-018-03; RF-015-07 a RF-015-09, RF-015-16, RF-015-18; plan 018 §5.2.3 y §5.3.2), como
prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene la suya, sin proyecto, en ``test_pit_recompute.py``.

Sobre el proyecto de las cortas (rejilla de 2 m, 200 × 200 celdas) con la corta ascendente ``PIT-001`` creada en V01:

- **Recalcular** (:class:`RecomputeTest`): repetirla sin cambiar nada da una operación nueva que sustituye a la anterior con los mismos datos bit a bit y las mismas cifras, sin escribir otra vez los
  parámetros; **cambiar un valor del perfil** o **el perfil de un sector** la deja obsoleta con su causa y «Recalcular lo obsoleto» da lo que daría crearla de nuevo; un parámetro que cambia entre
  prepararla y empezarla se rechaza (``des.input_changed``).
- **«Cambiar parámetro…»** (:class:`ParameterTest`): la fila del proyecto del nombre existe (la crea «Crear») y un nombre repetido se rechaza.
- **Traerla a otra versión** (:class:`BringTest`): queda **sin calcular**, con sus valores por sector, y se calcula traída con su código.
- **Reproducirla** (:class:`PitReproduceTest`, T24b, DIFF-018g; RF-018-25, RF-009-11): un V01.r1 congelado con cortas de los tres tipos de partida da de cada dato **el mismo hash** y de cada cifra el
  mismo valor —también las distancias de la línea de cielo al límite legal y al perímetro, con su geometría anotada como entrada—, **sin escribir** nada en el proyecto.
"""

from __future__ import annotations

import dataclasses
import json
import types
import unittest
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import pit_data as pd
from tests.support import res_fixtures
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_pit_prepare_checks as checks
from tests.unit.design.milestone_pit_create import BY, NAME, CreateCase
from tests.unit.design.milestone_pit_prepare_checks import CODE, request

core_params = import_geoblender("core.params")
gis = import_geoblender("gis")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
pit_lines = import_geoblender("design.pit_lines")
messages = import_geoblender("design.messages")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
road_model = import_geoblender("design.road_model")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")

SEG = "sector_1"
FACE = "des.bench.expl_10_60_6.face_deg"
OTHER_PROFILE = "expl_10_45_6"
"""Un perfil de la misma altura y ancla que ``EXPL_10_60_6``, con otro ángulo de cara: lo que admite un sector."""
SECTOR_PROFILE = f"des.pit.pit_001.profile.{SEG}"
FIXED_LAYER = "gis_brk_corta_banco_2"
ROLES_OF_A_PIT = ("entity_surface", "entity", "pit_polylines", "pit_skyline", "pit_ramps", "pit_findings", "pit_benches", "entity_report")


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
        for name, found in (("never", recompute_function), ("never_reproduced", design_reproduce.reproduce_pit)):
            patcher = mock.patch.object(checks, name, found)
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


class PitReproduceTest(RecomputeCase):
    """RF-018-25, RF-009-11, RF-015-02, DIFF-018g: las cortas de V01 congeladas en ``V01.r1`` y reproducidas **sin proyecto**: la ascendente de los fondos, la que lleva un valor por sector (el sector es
    una entrada congelada), la descendente desde un límite, la de la roseta con una capa de zonas sin rampa y la de un banco fijado (la capa de líneas con Z congelada)."""

    revision: ClassVar[str]
    pits: ClassVar[dict[str, str]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.pits = {}
        res_fixtures.write_grids(cls.project, [(label, gis.Raster(checks.GRID, pd.flat_terrain(checks.GRID), pd.CRS, pd.VERTICAL)) for label in ("corta_llano_d", "corta_llano_e")],
                                 message="Más terrenos llanos, iguales al de partida")
        cls.clock.advance(minutes=1)
        for code, name, start, changes in (
                ("PIT-001", NAME, "gis_dtm_corta_llano_b", {}),
                ("PIT-002", "Corta con sector", "gis_dtm_corta_llano_c", {"sector_profiles": {SEG: "expl_10_60_6"}}),
                ("PIT-003", "Corta del límite", checks.LIMIT, {"mode": "down", "source": checks.LIMITS, "profile": checks.EXPL}),
                ("PIT-004", "Corta con roseta", "gis_dtm_corta_llano_d", {"rose": cls.rose, "noramp": road_model.LayerFields("gis_fea_corta_sin_rampa", "nombre")})):
            cls.clock.advance(minutes=1)
            cls.pits[code] = cls.uid(cls, cls.calculate(cls, request(name, start=start, **changes)).create(decided_by=BY))
        with cls.project.read() as conn:  # el pie del banco 2 de la primera corta, como línea de rotura con Z: una corta con ese banco fijado lo usa tal cual
            lines = pit_lines.read_pit_lines(conn, provenance.dataset_locator(provenance.PIT_POLYLINES_TABLE, NAME, "V01"), provenance.PIT_POLYLINES_TABLE, closed_column="closed")
        foot = next(line for line in lines if (line.values[0], line.values[1]) == (2, "foot"))
        sdata.write_breaklines(cls.project, cls.clock, FIXED_LAYER, [np.vstack([foot.points, foot.points[:1]])])
        cls.clock.advance(minutes=1)
        cls.clock.advance(minutes=1)
        cls.pits["PIT-005"] = cls.uid(cls, cls.calculate(cls, request("Corta con banco fijado", start="gis_dtm_corta_llano_e", fixed=road_model.LayerFields(FIXED_LAYER, "line_id"))).create(decided_by=BY))
        cls.clock.advance(minutes=1)
        cls.revision = str(finish_steps(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba")).frozen.uid)
        cls.clock.advance(minutes=1)

    def test_a_reproducing_the_frozen_revision_gives_the_same_without_writing(self) -> None:
        """RF-018-25, RF-009-11: reproducir ``V01.r1`` —sin proyecto, desde la capa, la partida, las máscaras, los parámetros, el perímetro, el límite legal y los sectores congelados— da de cada corta el
        **mismo hash** de sus ocho datos y **las mismas cifras** (con las distancias de la línea de cielo), sin escribir nada en el proyecto (ni ficheros ni el contador de cambios de la base)."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish_steps(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        for code, uid in self.pits.items():
            with self.subTest(pit=code):
                mine = [check for check in report.outputs if check.operation_uid == uid]
                self.assertEqual([check.role for check in mine], list(ROLES_OF_A_PIT))
                self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
                found = [check for check in report.figures if check.operation_uid == uid]
                self.assertEqual(len(found), len(self.figures_of(uid)))
                self.assertTrue(found and all(check.same for check in found), [check for check in found if not check.same])
                self.assertNotIn(uid, [note.operation_uid for note in report.not_reproducible])
        keys = {check.key for check in report.figures if check.operation_uid == self.pits["PIT-001"]}
        self.assertIn("des.pit_sky_dist_legal_m", keys)
        self.assertIn("des.pit_sky_dist_perimeter_m", keys)

    def test_b_the_geometry_of_the_limits_and_of_the_named_sectors_are_inputs_with_their_own_role(self) -> None:
        """DIFF-018g: la operación anota la geometría del perímetro y del límite legal (los polígonos compilados de las restricciones) con el papel ``pit_limits``; los sectores (``sectors``) solo si la
        corta los nombra."""
        roles = {code: [role for _name, role in self.inputs(uid)] for code, uid in self.pits.items()}
        self.assertEqual(roles["PIT-001"].count(provenance.PIT_LIMITS_ROLE), 1)
        self.assertEqual(roles["PIT-002"].count(provenance.PIT_LIMITS_ROLE), 1)
        self.assertNotIn(provenance.SECTORS_ROLE, roles["PIT-001"])
        self.assertEqual(roles["PIT-002"].count(provenance.SECTORS_ROLE), 1)
        for code in ("PIT-003", "PIT-004", "PIT-005"):
            self.assertNotIn(provenance.SECTORS_ROLE, roles[code])
            self.assertEqual(roles[code].count(provenance.PIT_LIMITS_ROLE), 1)
        self.assertEqual(roles["PIT-005"].count(provenance.ENTITY_LAYER_ROLE), 2, "la capa de origen y la de los bancos fijados")


class FrozenReaderTest(RecomputeCase):
    """RF-018-25, RF-018-07, RF-018-15, DIFF-018g: lo que lee la reproducción de lo congelado (``_FrozenPit``) es lo que lee la preparación del proyecto (``ProjectReader``): las rosetas, las rampas con su
    perfil de pista y los perfiles de banco, salvo los nombres libres (que no son un valor)."""

    def test_the_roses_ramps_and_profiles_read_from_the_frozen_values_are_the_project_ones(self) -> None:
        reader = pit_store.ProjectReader(self.project, self.v1)
        keys = sorted({key for (key,) in self.query("SELECT key FROM gb_parameter WHERE key LIKE 'des.rose.%' OR key LIKE 'des.pitramp.%' OR key LIKE 'des.roadprofile.%' OR key LIKE 'des.bench.%'")})
        frozen = types.SimpleNamespace(values=reader.values(keys), request=types.SimpleNamespace(inputs=()))
        mine = design_reproduce._FrozenPit(frozen)
        asked = request(rose=self.rose, ramps=(self.ramp_codes["Espiral"], self.ramp_codes["Zigzag"]), profile=checks.EXPL)
        self.assertEqual(pit_store._roses(mine, asked, CODE, {}), pit_store._roses(reader, asked, CODE, {}))
        by_project, by_frozen = (pit_store._ramps(item, asked, CODE, checks.GRID) for item in (reader, mine))
        self.assertEqual([dataclasses.replace(item, name="") for item in by_project[0]], [dataclasses.replace(item, name="") for item in by_frozen[0]])
        plain = [[{key: value for key, value in dataclasses.asdict(item).items() if key not in ("name", "class_name")} for item in found[1]] for found in (by_project, by_frozen)]
        self.assertEqual(plain[0], plain[1])
        self.assertEqual(repr(by_project[2:]), repr(by_frozen[2:]), "el inicio de cada rampa y las capas de puntos que leyó")
        self.assertEqual(pit_store._profiles(mine, asked, CODE, {})[0], pit_store._profiles(reader, asked, CODE, {})[0])


if __name__ == "__main__":
    unittest.main()
