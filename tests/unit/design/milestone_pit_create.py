# SPDX-License-Identifier: GPL-3.0-or-later
"""«Crear» la corta con el proyecto: la operación, los datos, la huella y las dependencias (spec 018, T23; HU-018-1 y HU-018-5; RF-018-01, RF-018-03, RF-018-19; RF-015-01, RF-015-02, RF-015-04, RF-015-10 a
RF-015-14, RF-015-25 y RF-015-29; plan 018 §5.2.3 y §5.3.2), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_pit_create.py``.

Sobre el proyecto de las cortas (rejilla de 2 m, 200 × 200 celdas):

- **La primera corta** (:class:`CreatePitTest`): «Crear» deja **una** operación ``des.pit`` hecha en V01 con sus ocho datos y su papel, la superficie entera, la huella de la entidad, las polilíneas
  y la línea de cielo con Z, los hallazgos, las cifras por banco y el informe tal como los dan las funciones puras; las cifras con el ámbito de la entidad; los parámetros con su origen; una sola transacción; las entradas
  no se modifican; el estado «al día» se deduce (RF-015-25); **la corta no declara restricciones** (RF-015-12).
- **Una segunda corta** da ``PIT-002`` y, si la superficie de la primera difiere de su partida en su huella, la anota como **entrada** (otro diseño, con su hash).
- **Lo no creado** (:class:`NothingLeftTest`): una creación cerrada a mitad o con una entrada cambiada no deja nada.
- **La pendiente media de rampa** (:class:`MeanConfirmationTest`): sin confirmar no se crea (y el cálculo sigue abierto); confirmada, queda en los ajustes con su motivo, quién y cuándo.
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from typing import Any

import numpy as np

from tests.support import pit_data as pd
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter
from tests.unit.design import test_pit_bench_ramp as rp
from tests.unit.design.milestone_pit_compute import CalculateCase
from tests.unit.design.milestone_pit_prepare_checks import CODE, FLAT, FLOORS, GRID, request
from tests.unit.design.test_pit_compute import run as run_job

gis = import_geoblender("gis")
entities = import_geoblender("design.entities")
core_params = import_geoblender("core.params")
messages = import_geoblender("design.messages")
pit_lines = import_geoblender("design.pit_lines")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
store = import_geoblender("design.store")
surfaces = import_geoblender("design.surfaces")

NAME = "Corta del fondo"
SECOND = "Segunda corta"
OTHER_TERRAIN = "gis_dtm_corta_otro"
BY = "Samuel (IMGA)"
FAMILIES = (provenance.ENTITY_SURFACE_GRID, provenance.ENTITY_TABLE, provenance.PIT_POLYLINES_TABLE, provenance.PIT_SKYLINE_TABLE, provenance.PIT_RAMPS_TABLE, provenance.PIT_FINDINGS_TABLE,
            provenance.PIT_BENCHES_TABLE, provenance.ENTITY_REPORT_TABLE)
ROLES = ("entity_surface", "entity", "pit_polylines", "pit_skyline", "pit_ramps", "pit_findings", "pit_benches", "entity_report")


class CreateCase(CalculateCase):
    def uid(self, stored: Any) -> str:
        return str(stored.handle.uid)

    def outputs(self, uid: str) -> list[tuple[str, str, str]]:
        """Lo que escribió la operación ``uid``: ``(nombre, ubicación, papel)`` de cada dato, en su orden."""
        return [tuple(row) for row in self.query(
            "SELECT d.name, d.locator, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def inputs(self, uid: str) -> list[tuple[str, str]]:
        return [(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def table(self, name: str, family: str) -> list[dict[str, Any]]:
        names = [column.name for column in store.columns_of(provenance.PIT, family)]
        found = self.query(f'SELECT {", ".join(names)} FROM "{provenance.dataset_locator(family, name, "V01")}" ORDER BY fid')
        return [dict(zip(names, row, strict=True)) for row in found]

    def figures_of(self, uid: str) -> list[tuple[str, float, dict[str, Any]]]:
        return [(key, value, json.loads(scope)) for key, scope, value in self.query("SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid)]

    def hashes(self, *names: str) -> dict[str, tuple[str, ...]]:
        with self.project.read() as conn:
            return {name: tuple(conn.execute("SELECT content_sha256, status FROM gb_dataset WHERE name = ? AND status = 'current'", (name,)).fetchone()) for name in names}


class CreatePitTest(CreateCase):
    """RF-018-01, RF-015-01, RF-015-02, RF-015-12: la primera corta, creada una vez en V01; la segunda, ``PIT-002``."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        res_fixtures.write_grids(cls.project, [("corta_otro", gis.Raster(GRID, pd.inclined_terrain(GRID), pd.CRS, pd.VERTICAL))], message="Otro terreno, de otra operación")
        cls.inputs_before = cls.hashes_of_inputs()
        cls.counter_before = change_counter(cls.root)
        cls.first = cls.calculate(cls, request())
        cls.clock.advance(minutes=1)
        cls.first_stored = cls.first.create(decided_by=BY)
        cls.counter_after = change_counter(cls.root)
        cls.clock.advance(minutes=1)
        cls.second = cls.calculate(cls, request(SECOND, start=OTHER_TERRAIN))
        cls.second_stored = cls.second.create(decided_by=BY)

    @classmethod
    def hashes_of_inputs(cls) -> dict[str, tuple[str, ...]]:
        with cls.project.read() as conn:
            return {name: tuple(conn.execute("SELECT content_sha256, status FROM gb_dataset WHERE name = ? AND status = 'current'", (name,)).fetchone()) for name in (FLAT, FLOORS)}

    def test_a_one_done_operation_with_the_eight_data_of_a_pit(self) -> None:
        """RF-018-01, RF-015-02: «Crear» deja **una** operación ``des.pit`` hecha en V01 con los ocho datos de su tipo, cada uno con su nombre, su ubicación y el papel con que lo leen los demás."""
        found = self.outputs(self.uid(self.first_stored))
        self.assertEqual([row[0] for row in found], [provenance.dataset_name(family, NAME) for family in FAMILIES])
        self.assertEqual([row[2] for row in found], list(ROLES))
        self.assertEqual([row[1] for row in found], [provenance.dataset_locator(family, NAME, "V01") for family in FAMILIES])
        self.assertTrue((self.root / found[0][1]).is_file())
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", self.uid(self.first_stored)), [(provenance.PIT, "version", "done")])
        self.assertEqual((self.first.op_type, self.first.open), (provenance.PIT, False))
        self.assertEqual(len(self.first_stored.records), 8)
        with self.assertRaises(RuntimeError):
            self.first.create()

    def test_b_the_data_are_what_was_computed(self) -> None:
        """RF-018-25, RF-015-01: la superficie guardada es **la entera** (bit a bit); la huella, los hallazgos, las cifras por banco y el informe son lo que dicen las funciones puras; las polilíneas, en
        el orden registrado y con la Z exacta; la línea de cielo, con la cota del terreno."""
        outcome, prepared = self.first.outcome, self.first.entity
        name = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, NAME)
        grid = surfaces.read_surface_steps(self.project, name, version_uid=self.v1.uid)
        while True:
            try:
                next(grid)
            except StopIteration as done:
                np.testing.assert_array_equal(done.value.values, outcome.compose(prepared.job.start))
                break
        (row,) = self.table(NAME, provenance.ENTITY_TABLE)
        expected = pit_store.pit_entity_rows(prepared.job, outcome, fid=0, start_surface=prepared.start_surface, support_surface=prepared.support_surface, sources_sha256=prepared.sources_sha256)
        self.assertEqual(tuple(row.values()), expected[0])
        self.assertEqual((row["code"], row["kind"], row["layer"], row["mode"], row["start_surface"]), (CODE, "pit", FLOORS, "up", FLAT))
        self.assertEqual(row["cells"] * prepared.job.grid.cell_area, {key: value for key, value, _scope in self.figures_of(self.uid(self.first_stored))}["des.pit_area_m2"])
        self.assertEqual([tuple(item.values()) for item in self.table(NAME, provenance.PIT_BENCHES_TABLE)], pit_store.pit_bench_rows(outcome))
        self.assertEqual([tuple(item.values()) for item in self.table(NAME, provenance.PIT_FINDINGS_TABLE)], pit_store.pit_finding_rows(outcome))
        self.assertEqual([tuple(item.values()) for item in self.table(NAME, provenance.ENTITY_REPORT_TABLE)], pit_store.pit_report_rows(outcome))
        self.assertEqual(self.table(NAME, provenance.PIT_RAMPS_TABLE), [])
        for family, wanted, closed in ((provenance.PIT_POLYLINES_TABLE, pit_store.pit_polyline_rows(outcome), "closed"), (provenance.PIT_SKYLINE_TABLE, pit_store.pit_skyline_rows(outcome), None)):
            with self.project.read() as conn:
                found = pit_lines.read_pit_lines(conn, provenance.dataset_locator(family, NAME, "V01"), family, closed_column=closed)
            self.assertEqual(len(found), len(wanted))
            for got, want in zip(found, wanted, strict=True):
                self.assertTrue(np.array_equal(got.points, want.points))
                self.assertEqual(got.values, want.values)
        self.assertGreater(len(outcome.polylines), 5)

    def test_c_the_figures_are_registered_with_the_scope_of_the_entity(self) -> None:
        """RF-018-31, RF-015-13: las cifras CALCULADO quedan registradas con el ámbito de la entidad (su nombre y su código), más ``des.supported_m3`` de lo que apoya (nada: ninguna aquí)."""
        by_key = {key: (value, scope) for key, value, scope in self.figures_of(self.uid(self.first_stored))}
        scope = provenance.entity_figure_scope(NAME, CODE)
        for figure in self.first.figures:
            self.assertEqual(by_key[figure.key], (figure.value, scope), figure.key)
        self.assertEqual(sorted(set(by_key) - {figure.key for figure in self.first.figures}), [])

    def test_d_the_parameters_are_written_with_their_origin_and_the_state_is_current(self) -> None:
        """RF-015-01, RF-015-08, RF-015-25: los parámetros de ``PIT-001`` quedan como filas **de la versión** con su origen y el decisor de quien creó; la entidad es una corta ``al día``."""
        parameters = core_params.ParameterStore(self.project)
        for row in self.first.entity.rows:
            record = parameters.get(row.key, version=self.v1.uid)
            self.assertIsNotNone(record, row.key)
            self.assertEqual((record.value, record.decided_by), (row.value, BY), row.key)
        entry = entities.registry(self.project, self.v1.uid).get(CODE)
        self.assertEqual((entry.record.kind, entry.record.state, entry.record.name), (entities.EntityKind.PIT, entities.EntityState.CURRENT, NAME))
        self.assertEqual(str(entry.operation_uid), self.uid(self.first_stored))

    def test_e_one_transaction_and_the_inputs_are_not_modified(self) -> None:
        """RF-015-29, RF-018-01, principio 7: «Crear» registra **una** operación (y una transacción); la capa de origen y la superficie de partida no se modifican (su hash y su estado, los de antes)."""
        self.assertEqual(self.counter_after - self.counter_before, 1)
        self.assertEqual(self.hashes_of_inputs(), self.inputs_before)
        written = {row[0] for uid in (self.uid(self.first_stored), self.uid(self.second_stored)) for row in self.outputs(uid)}
        self.assertFalse(written & set(self.inputs_before))

    def test_f_the_inputs_are_the_layer_the_start_and_the_masks(self) -> None:
        """RF-018-01, RF-015-06: las entradas son la capa de origen (``entity_layer``), la superficie de partida (``surface``) y las máscaras de V01; la primera no tiene otros diseños."""
        first = self.inputs(self.uid(self.first_stored))
        self.assertEqual(first[:2], [(FLOORS, "entity_layer"), (FLAT, "surface")])
        self.assertLessEqual({str(use.role) for use in self.masks_v1.uses()}, {role for _name, role in first})
        self.assertNotIn(provenance.ROAD_OTHER_DESIGN_ROLE, [role for _name, role in first])

    def test_g_the_pit_declares_nothing(self) -> None:
        """RF-018-01, RF-015-10, RF-015-12: la corta **no declara restricción alguna**: ninguna operación ``des.declare_constraints`` ni tabla de declaradas, y los ajustes de la operación no llevan ``protect``."""
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE op_type = ?", provenance.DECLARE_CONSTRAINTS), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE name = ?", provenance.dataset_name(provenance.DECLARED_TABLE)), [(0,)])
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", self.uid(self.first_stored))
        self.assertEqual(json.loads(settings), {"name": NAME, "code": CODE, "fields": {"name_field": "nombre", "level_field": "cota_m", "fixed_field": None}})

    def test_h_a_second_pit_is_pit_002_and_notes_the_first_as_another_design(self) -> None:
        """RF-015-04, RF-017-05 (b) en la corta: la segunda es ``PIT-002``, parte del mismo terreno y la superficie de la primera difiere de él en su huella: queda como **entrada** ``other_design`` con su hash."""
        self.assertEqual(self.second.entity.code, "PIT-002")
        first_surface = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, NAME)
        self.assertEqual(self.second.outcome.other_designs, (first_surface,))
        self.assertIn((first_surface, provenance.ROAD_OTHER_DESIGN_ROLE), self.inputs(self.uid(self.second_stored)))
        self.assertIn("des.pit_other_design_differs", [item.code for item in self.second.summary.notices])
        registry = entities.registry(self.project, self.v1.uid)
        self.assertEqual({code: registry.get(code).record.state for code in (CODE, "PIT-002")}, {CODE: entities.EntityState.CURRENT, "PIT-002": entities.EntityState.CURRENT})


class NothingLeftTest(CreateCase):
    """RF-015-29, RF-018-35, principio 7: lo que no se crea no deja nada."""

    def test_a_closing_the_steps_halfway_leaves_nothing(self) -> None:
        for cut in (1, 3, 6, 10):
            with self.subTest(closed_after=cut):
                calculation = self.calculate(request("Corta a medias"))
                before = self.snapshot()
                work = calculation.create_steps(budget_s=1e-9)
                for _step in range(cut):
                    next(work)
                work.close()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(calculation.open)

    def test_b_an_input_changed_since_calculating_leaves_nothing(self) -> None:
        """RF-015-02: un parámetro de la entidad cambiado entre «Calcular» y «Crear» deja ``des.input_changed`` y nada escrito."""
        calculation = self.calculate(request("Corta que cambia"))
        key = next(iter(calculation._values))
        calculation._values = {**calculation._values, key: "otra cosa"}
        before = self.snapshot()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=BY)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(calculation.open)


class MeanConfirmationTest(CreateCase):
    """RF-018-19: la pendiente media de una rampa por encima de pm no se crea sin confirmar; confirmada, queda en los ajustes con su motivo, quién y cuándo."""

    def over_pm(self) -> tuple[Any, Any]:
        """Una ``Calculation`` del proyecto con la comprobación de una rampa que pasa de pm (la espiral del proyecto de 1 m: el de las cortas no tiene una rampa que quepa, T22b (c))."""
        job = rp.spiral_job()
        profile = rp.road(min_radius_m=7.0, max_mean_gradient_pct=5.0)
        job = pit_store.replace(job, road_profiles=(profile,), ramps=(pit_store.replace(job.ramps[0], road_profile=profile.code),))
        ramp, _times = run_job(job)
        calculation = self.calculate(request("Corta con rampa"))
        calculation.outcome = dataclasses.replace(calculation.outcome, extra={**calculation.outcome.extra, "checked_ramps": ramp.extra["checked_ramps"]})
        return calculation, ramp.extra["mean_pending"][0]

    def test_a_without_confirmation_it_is_not_created_and_the_calculation_stays_open(self) -> None:
        calculation, (code, mean, _limit) = self.over_pm()
        self.assertTrue(calculation.needs_mean_confirmation)
        before = self.snapshot()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=BY)
        self.assertEqual(caught.exception.code, "des.pit_ramp_mean_over")
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(calculation.open)
        calculation.discard()

    def test_b_confirmed_it_is_recorded_with_who_and_when(self) -> None:
        calculation, (code, mean, _limit) = self.over_pm()
        calculation.confirm_pit([provenance.ramp_confirmation(code, mean, "Hay que cruzar el cauce", BY, "2026-11-23T10:00:00Z")])
        self.assertFalse(calculation.needs_mean_confirmation)
        stored = calculation.create(decided_by=BY)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", self.uid(stored))
        found = provenance.ramp_confirmed(json.loads(settings))
        self.assertEqual([(item.ramp, item.reason, item.decided_by, item.decided_on) for item in found], [(code, "Hay que cruzar el cauce", BY, "2026-11-23T10:00:00Z")])
        self.assertEqual(found[0].mean_pct, mean)


if __name__ == "__main__":
    unittest.main()
