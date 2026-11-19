# SPDX-License-Identifier: GPL-3.0-or-later
"""La orden de retirar un acopio, su almacén: preparar, calcular, crear, recalcular y reproducir (spec 016, T20; HU-016-2;
RF-016-11 a RF-016-15, RF-015-02, RF-015-03, RF-015-07, RF-015-29, RF-009-11, RNF-016-05; plan 016 §5.2.3, §5.3.2, §5.4 A6 a A8,
§5.7 P-9 y P-12; ADR-0031 §4). Es el patrón de la T25 y la T27: ``design.supported_store`` hace, para la retirada, lo que
``design.stockpile_store`` hace para la detección (y ``entity_store`` para la plataforma).

La cantera de los acopios de 2 m con la detección ``Acopios`` (``STK-001``, V01: las cinco marcas sobre el levantamiento de V01). **En
orden** (``test_a`` a ``test_n``): cada una parte de lo que dejó la anterior.

- «Calcular» (RF-015-03, RF-015-29, RNF-016-05): la retirada del Acopio 1 **no escribe nada** (solo un temporal que se borra al
  descartarla ni al cerrar los pasos a mitad) y deja el resumen con sus cifras.
- «Crear» (RF-016-11, RF-016-13, RF-015-02): **una** transacción con los parámetros de la entidad, la operación con sus entradas (la
  superficie de partida y, con el papel ``removed_stockpile``, lo que lee del acopio), la superficie, la huella, el informe y las
  cifras; un fallo no deja nada y ninguna entrada se modifica.
- Lo que se apoyaba (RF-016-14) y la pared (RF-016-15), con sus confirmaciones, su motivo y su decisor.
- Recalcular (RF-015-02, RF-016-10) y reproducir (RF-009-11).
- Los rechazos (RF-016-12, RF-015-07, RF-015-08), sin escribir nada.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Iterator
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_stockpile_prepare as tp
from tests.unit.design import milestone_stockpile_supports as sup

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
freeze = import_geoblender("core.versions.freeze")
geotiff_reader = import_geoblender("gis.geotiff.reader")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
project_model = import_geoblender("core.project.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
removal = import_geoblender("design.removal")
stale_module = import_geoblender("core.provenance.stale")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
stockpile_store = import_geoblender("design.stockpile_store")
supported_store = import_geoblender("design.supported_store")
versions_model = import_geoblender("core.versions.model")

GRID = sup.GRID
USER = sup.USER
SURVEY = sup.SURVEY
CODE = "RMV-001"
FIRST = "Retirada del acopio 1"
SECOND = "Retirada del acopio 2"
THIRD = "Retirada del acopio 3"
ANGLE_DEG = 30.0


def asked(name: str = FIRST, key: str = "Acopio 1", *, start: str = SURVEY, **changes: Any) -> Any:
    """La petición de retirar el acopio ``key`` de ``STK-001`` desde ``start`` con la transición de 30°."""
    base: dict[str, Any] = {"stockpile": f"STK-001#{key}", "start": start, "transition_deg": ANGLE_DEG}
    return model.RemovalRequest(name=name, **{**base, **changes})


def forged_wall(height_m: float, angle_deg: float) -> Any:
    """Una pared de un tramo (como la que deja una superficie sin transición: la de A6 nunca la deja, T19) en lugar de medirla."""

    def walled(job: Any, outcome: Any, project: Any, *, budget_s: float = 0.05) -> Iterator[Any]:
        stretch = removal.WallStretch(1, 6, height_m, angle_deg, 4.0, 100.0, 200.0)
        wall = removal.Wall((stretch,), outcome.transition_deg, 1.0, 0.02, 1.0, 6, 6)
        found = dataclasses.replace(outcome, wall=wall, wall_max_m=wall.height_m,
                                    notices=(*outcome.notices, *removal.wall_notices(outcome.stockpile_name, wall)))
        yield project_model.Progress("removal_wall", 1, 1, "Pared medida", result=found)

    return mock.patch.object(removal, "wall_steps", walled)


class RemovalCase(sup.SupportsCase):
    """La cantera de los acopios con el tipo de la retirada registrado con sus funciones reales (recalcular y reproducir) y las
    ayudas de lo registrado."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        removal_type = provenance.OPERATION_TYPES_BY_NAME[provenance.STOCKPILE_REMOVAL].definition(
            ops.recompute_function, design_reproduce.reproduce_stockpile_removal)
        return (*super().definitions(), removal_type, *provenance.REMOVAL_FIGURES)

    @classmethod
    def calculate(cls, request: Any, **options: Any) -> Any:
        """«Calcula» ``request`` en V01 con sus máscaras: la ``Calculation`` (sin registrar nada)."""
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        return ops.last(steps.removal_run(cls.project, request, **options))

    @classmethod
    def make(cls, request: Any, **options: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» ``request`` (un minuto después de lo anterior): la ``Calculation`` y lo guardado."""
        cls.clock.advance(minutes=1)
        calculation = cls.calculate(request)
        confirm = options.pop("confirm", {})
        if confirm:
            calculation.confirm_removal(**confirm)
        stored = calculation.create(decided_by=USER, **options)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def state(self) -> dict[str, Any]:
        """Todo lo que podría escribir una retirada que no se crea: el contador de cambios de la base, las operaciones, los datos,
        los parámetros y las cifras, y los ficheros de ``rasters/`` (sin los temporales)."""
        return {
            "counter": change_counter(self.root),
            "operations": self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"),
            "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset ORDER BY rowid"),
            "parameters": self.query("SELECT key, scope_uid, value FROM gb_parameter ORDER BY rowid"),
            "figures": self.query("SELECT key, scope, value FROM gb_figure ORDER BY rowid"),
            "files": sorted(path.name for path in (self.root / "rasters").iterdir() if ".tmp" not in path.name)}

    def temporaries(self) -> list[str]:
        return sorted(path.name for path in (self.root / "rasters").iterdir() if ".tmp" in path.name)

    def refused(self, request: Any, expected: str, **options: Any) -> Any:
        """«Calcular» ``request`` se rechaza con el código ``expected`` y **no escribe nada** (ni deja un temporal); devuelve el
        error, cuyo texto no deja ningún marcador sin llenar en ninguno de los dos idiomas."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            self.calculate(request, **options)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(self.state(), before, "el rechazo ha escrito algo")
        self.assertEqual(self.temporaries(), [], "el rechazo ha dejado un temporal")
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)
        return error

    def operation_of(self, code: str) -> str:
        entry = entities.registry(self.project, self.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def inputs_of(self, uid: str) -> list[tuple[str, str]]:
        """Las entradas de la operación ``uid``: ``(papel, nombre)`` de cada dato, en su orden."""
        return [(role, name) for role, name in self.query(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def outputs_of(self, uid: str) -> list[tuple[str, str]]:
        return [(role, name) for role, name in self.query(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def figures_by_key(self, uid: str) -> dict[str, float]:
        return {key: value for key, _scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid)}

    def surface_of(self, name: str) -> np.ndarray:
        return np.asarray(self.grid_of(name))

    def footprint_of(self, key: str) -> np.ndarray:
        """Las celdas de la huella del acopio ``key`` como índices planos (a mano: de los tramos de su fila de ``des_stk_``)."""
        rows, cols = self.cells_of(key)
        return rows.astype(np.int64) * GRID.ncols + cols


class RemovalOperationTest(RemovalCase):
    """RF-016-11 a RF-016-15, RF-015-02, RF-015-03, RF-015-07, RF-015-29, RF-009-11, RNF-016-05, **en orden**: la detección
    ``Acopios`` (``STK-001``, V01) y, sobre ella, las retiradas de los acopios 1, 2 y 3."""

    first: ClassVar[Any]
    stored: ClassVar[Any]
    revision: ClassVar[str]
    before_creating: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.detect()
        cls.clock.advance(minutes=1)

    # --- Calcular ------------------------------------------------------------------------------------------

    def test_a_calculating_writes_nothing_and_leaves_the_summary_with_its_figures(self) -> None:
        """RF-015-03, RF-016-11, RF-016-13 (A6): «Calcular» la retirada del Acopio 1 no escribe **nada** en el proyecto (ni la base de
        datos, ni las operaciones, los datos, los parámetros o las cifras; solo el temporal de su superficie, que **descartar** borra):
        deja la entidad ``RMV-001`` preparada, el resumen con las cifras y la superficie nueva, que no baja de la base en ninguna celda;
        lo retirado más lo apoyado, la transición y lo no retirado suma lo que había sobre la base a ≤ 10⁻⁹ relativo."""
        before = self.state()
        calculation = self.calculate(asked())
        self.assertEqual(self.state(), before, "calcular no escribe")
        self.assertEqual(len(self.temporaries()), 1, "solo el temporal de la superficie")
        self.assertTrue(calculation.open)
        self.assertEqual((calculation.op_type, calculation.name, calculation.version, calculation.entity.code),
                         (provenance.STOCKPILE_REMOVAL, FIRST, "V01", CODE))
        outcome = calculation.outcome
        self.assertEqual((outcome.stockpile, outcome.code), ("Acopio 1", CODE))
        self.assertGreater(outcome.removed_m3, 0.0)
        parts = math.fsum((outcome.removed_m3, outcome.resting_m3, outcome.transition_m3, outcome.kept_m3))
        self.assertLessEqual(abs(parts - outcome.above_base_m3) / outcome.above_base_m3, 1e-9)
        summary = calculation.summary
        self.assertEqual((summary.name, summary.code, summary.stockpile, summary.stockpile_name, summary.version),
                         (FIRST, CODE, "STK-001#Acopio 1", "Acopio 1", "V01"))
        self.assertEqual(summary.resting, (), "nada se apoya en el Acopio 1")
        self.assertEqual(summary.figures, outcome.figures)
        self.assertFalse(calculation.needs_resting_confirmation or calculation.needs_wall_confirmation)
        survey = sdata.survey(GRID)
        whole = outcome.compose(survey)
        base = calculation.entity.job.stockpile.base
        footprint = calculation.entity.job.stockpile.cells
        self.assertTrue(np.all(whole.ravel()[footprint] >= np.minimum(survey.ravel()[footprint], base)), "nunca baja de la base")
        np.testing.assert_array_equal(np.delete(whole.ravel(), footprint), np.delete(survey.ravel(), footprint),
                                      "fuera de la huella, la partida bit a bit")
        calculation.discard()
        self.assertEqual(self.temporaries(), [], "descartar borra el temporal")
        self.assertEqual(self.state(), before)

    def test_a_the_dialog_offers_the_stockpiles_of_the_detections_of_the_version_with_their_numbers(self) -> None:
        """RF-016-11, RF-016-12 (plan §5.3.3: «el acopio» del diálogo): ``removable_stockpiles`` lista, **sin escribir nada**, los acopios
        de las detecciones de la versión (``des_stk_``) con la referencia que lleva la retirada (``STK-001#Acopio 1``), su nombre, su
        detección, su material y sus cifras —las de la tabla, bit a bit—, en el orden de la tabla y al día."""
        before = self.state()
        found = supported_store.removable_stockpiles(self.project, self.v1.uid)
        self.assertEqual(self.state(), before, "solo lee")
        table = stockpile_store.read_detection_table(self.project, provenance.STOCKPILES_TABLE, sup.DETECTION,
                                                     version_uid=self.v1.uid)
        self.assertEqual([item.ref for item in found], [f"STK-001#{row['key']}" for row in table])
        self.assertEqual([item.ref for item in found], [f"STK-001#Acopio {number}" for number in range(1, 6)])
        for item, row in zip(found, table, strict=True):
            with self.subTest(ref=item.ref):
                self.assertEqual((item.key, item.name, item.detection, item.detection_name, item.scope, item.material),
                                 (row["key"], row["name"], "STK-001", sup.DETECTION, "version", row["material"]))
                self.assertEqual((item.area_m2, item.volume_m3), (row["area_m2"], row["volume_m3"]))
                self.assertEqual(item.state, entities.EntityState.CURRENT)
        self.assertEqual(supported_store.removable_stockpiles(self.project, self.v2.uid), (), "V02 no tiene detección")

    def test_a_closing_the_steps_halfway_leaves_nothing(self) -> None:
        """RF-015-29, RNF-016-05: con un presupuesto de 0 s son varios pasos y cerrar el generador a mitad (Esc) o justo antes del último
        no deja nada —ni un temporal—, y ninguna entrada se modifica; el último paso es el que lleva el cálculo."""
        before = self.state()
        work = steps.removal_run(self.project, asked(), version=self.v1.uid, masks=self.masks_v1, budget_s=0.0)
        shown = [next(work) for _ in range(4)]
        self.assertTrue(all(step.result is None for step in shown))
        work.close()
        self.assertEqual((self.state(), self.temporaries()), (before, []))
        every = list(steps.removal_run(self.project, asked(), version=self.v1.uid, masks=self.masks_v1, budget_s=0.0))
        self.assertGreater(len(every), 10, "por pasos")
        self.assertTrue(all(step.result is None for step in every[:-1]))
        self.assertIsInstance(every[-1].result, steps.Calculation)
        every[-1].result.discard()
        work = steps.removal_run(self.project, asked(), version=self.v1.uid, masks=self.masks_v1, budget_s=0.0)
        for _step in range(len(every) - 1):
            next(work)
        work.close()
        self.assertEqual((self.state(), self.temporaries()), (before, []), "cerrado antes del último paso")

    # --- Los rechazos ---------------------------------------------------------------------------------------

    def test_b_the_refusals_write_nothing_and_name_what_is_wrong(self) -> None:
        """RF-016-12, RF-015-08, RF-016-11: cada rechazo sale **al avanzar** (antes de calcular) y no escribe nada: un acopio sin su
        clave, que no existe o de una detección que no existe (``des.removal_stockpile_unknown``, nombrándolo); sin ángulo de
        transición (``des.entity_param_missing``: D-2, no se elige uno por la persona) y fuera de (0; 90)° o con un factor de malla fuera
        de rango (``des.entity_param_range``); una partida que no es la superficie de una entidad calculada
        (``des.entity_start_unknown``); y sin versión activa."""
        error = self.refused(asked(stockpile="STK-001"), "des.removal_stockpile_unknown")
        self.assertEqual(error.values["value"], "STK-001")
        error = self.refused(asked(stockpile="STK-001#Nada"), "des.removal_stockpile_unknown")
        self.assertIn("Nada", error.text)
        self.refused(asked(stockpile="STK-009#Acopio 1"), "des.removal_stockpile_unknown")
        error = self.refused(asked(transition_deg=None), "des.entity_param_missing")
        self.assertEqual(error.values["field"], "des.removal.rmv_001.transition_deg")
        for angle in (0.0, 90.0, 120.0):
            with self.subTest(angle=angle):
                self.refused(asked(transition_deg=angle), "des.entity_param_range")
        self.refused(asked(mesh_factor=1.5), "des.entity_param_range")
        self.refused(asked(start="entity:PLT-009"), "des.entity_start_unknown")
        with self.assertRaises(versions_model.VersionError) as caught:
            self.calculate(asked(), version=None)
        self.assertEqual(caught.exception.code, "core.version_required")

    # --- Crear ---------------------------------------------------------------------------------------------

    def test_c_creating_fails_as_a_whole_if_a_table_cannot_be_written(self) -> None:
        """RF-015-02, RF-015-29: «Crear» es **una** transacción: un fallo al escribir la segunda tabla no deja nada —ni la operación, los
        datos, los parámetros de la entidad, las cifras o los ficheros, ni un temporal— y el cálculo queda descartado."""
        calculation = self.calculate(asked())
        before = self.state()
        written: list[str] = []
        real = store.DesignWriter._write_table

        def breaks(writer: Any, conn: Any, table: Any) -> None:
            written.append(table.family)
            if len(written) == 2:
                raise RuntimeError("falla la segunda tabla")
            real(writer, conn, table)

        with mock.patch.object(store.DesignWriter, "_write_table", breaks):
            with self.assertRaises(RuntimeError):
                calculation.create(decided_by=USER)
        self.assertEqual(self.state(), before, "no queda nada")
        self.assertEqual(self.temporaries(), [])
        self.assertFalse(calculation.open, "el cálculo queda descartado")

    def test_d_creating_registers_the_removal_in_one_transaction_and_modifies_no_input(self) -> None:
        """RF-016-11, RF-016-13, RF-015-02, RF-015-01 (P-9, P-12): «Crear» la retirada del Acopio 1 registra **de una vez** los
        parámetros de la entidad (``des.removal.rmv_001.*`` de V01, con su decisor y su origen), la operación ``des.stockpile_removal``
        con sus entradas —la superficie de partida (``surface``) y, con el papel ``removed_stockpile``, lo que lee del acopio: su tabla,
        su base y la superficie con que se detectó— y sus parámetros (el acopio, tal como lo leyó: lo que lee P-9), la superficie
        entera (``des_psf_``), la huella (``des_epr_``) y el informe, y las cifras ``des.rmv_*`` con el ámbito de la entidad. La
        superficie escrita es la de la retirada; la de partida, la tabla y las bases no cambian de contenido."""
        survey_before = self.record(SURVEY, self.v1).content_sha256
        detection_before = {name: self.record(name, self.v1).content_sha256 for name in (
            sup.TABLE, sup.DETECTED, provenance.dataset_name("stb", "Acopios mineral"))}
        calculation, stored = self.make(asked())
        type(self).first, type(self).stored = calculation, stored
        uid = str(stored.handle.uid)
        self.assertEqual(self.query("SELECT op_type, scope, status, supersedes_uid FROM gb_operation WHERE uid = ?", uid),
                         [(provenance.STOCKPILE_REMOVAL, "version", "done", None)])
        self.assertEqual(self.operation_of(CODE), uid)
        rows = {key: (value, decided_by) for key, value, decided_by in self.query(
            "SELECT key, value, decided_by FROM gb_parameter WHERE key LIKE 'des.removal.rmv_001.%' AND scope = 'version'")}
        for param, value in (("name", FIRST), ("stockpile", "STK-001#Acopio 1"), ("start", SURVEY),
                             ("transition_deg", ANGLE_DEG), ("mesh_factor", 1.0), ("metric", "exact")):
            found = rows[f"des.removal.rmv_001.{param}"]
            self.assertEqual((json.loads(found[0]), found[1]), (value, USER), param)
        read = {name for (name,) in self.query(
            "SELECT p.key FROM gb_operation_param AS p WHERE p.operation_uid = ?", uid)}
        self.assertIn("des.removal.rmv_001.stockpile", read, "P-9 lee el parámetro del acopio tal como lo leyó")
        inputs = self.inputs_of(uid)
        self.assertEqual(inputs[0], ("surface", SURVEY))
        self.assertEqual([item for item in inputs if item[0] == "removed_stockpile"],
                         [("removed_stockpile", sup.TABLE), ("removed_stockpile", provenance.dataset_name("stb", "Acopios mineral")),
                          ("removed_stockpile", sup.DETECTED)])
        surface = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, FIRST)
        self.assertEqual([name for _role, name in self.outputs_of(uid)],
                         [surface, provenance.dataset_name(provenance.ENTITY_TABLE, FIRST),
                          provenance.dataset_name(provenance.ENTITY_REPORT_TABLE, FIRST)])
        self.assertEqual(self.record(SURVEY, self.v1).content_sha256, survey_before, "la superficie de partida no cambia")
        for name, sha in detection_before.items():
            self.assertEqual(self.record(name, self.v1).content_sha256, sha, f"{name} no cambia")
        written = self.surface_of(surface)
        np.testing.assert_array_equal(written, calculation.outcome.compose(sdata.survey(GRID)))
        figures = self.figures_by_key(uid)
        for key, value in (("des.rmv_removed_m3", calculation.outcome.removed_m3),
                           ("des.rmv_resting_m3", calculation.outcome.resting_m3),
                           ("des.rmv_transition_m3", calculation.outcome.transition_m3),
                           ("des.rmv_kept_m3", calculation.outcome.kept_m3),
                           ("des.rmv_transition_m2", calculation.outcome.transition_m2), ("des.rmv_wall_max_m", 0.0)):
            self.assertEqual(figures[key], value, key)
        scopes = [json.loads(scope) for (scope,) in self.query(
            "SELECT scope FROM gb_figure WHERE operation_uid = ? AND key = 'des.rmv_removed_m3'", uid)]
        self.assertEqual(scopes, [{"name": "retirada_del_acopio_1", "entity": CODE}])
        entry = entities.registry(self.project, self.v1.uid).get(CODE)
        assert entry is not None
        self.assertEqual((entry.record.kind, entry.record.name, entry.record.start, entry.record.state),
                         (entities.EntityKind.REMOVAL, FIRST, SURVEY, entities.EntityState.CURRENT))
        (table,) = self.query(f'SELECT code, name, kind, start_surface, layer, cells, footprint FROM '
                              f'"{provenance.dataset_locator(provenance.ENTITY_TABLE, FIRST, "V01")}"')
        self.assertEqual(table[:4], (CODE, FIRST, "removal", SURVEY))
        self.assertEqual(table[5], len(self.footprint_of("Acopio 1")))
        runs = tuple(tuple(run) for run in json.loads(table[6]))
        np.testing.assert_array_equal(np.sort(np.concatenate([
            row * GRID.ncols + np.arange(first, last) for row, first, last in runs])), self.footprint_of("Acopio 1"))
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.stale_causes(uid), set())

    def test_e_the_removal_report_and_the_removed_stockpile_are_what_the_graph_reads(self) -> None:
        """RF-016-13, RF-016-15, RF-015-17 (P-9): el informe (``des_prp_``) lleva las cifras de la retirada y de su pared con los dos
        umbrales de CA-9 copiados; la retirada **viva** del Acopio 1 no le quita el apoyo a nadie (nada se le apoya) y la detección sigue
        al día."""
        report = {quantity: value for quantity, value, _unit, _note in self.query(
            f'SELECT quantity, value, unit_code, note FROM "{provenance.dataset_locator(provenance.ENTITY_REPORT_TABLE, FIRST, "V01")}"')}
        outcome = self.first.outcome
        for quantity, value in (("removed_m3", outcome.removed_m3), ("resting_m3", outcome.resting_m3),
                                ("transition_m3", outcome.transition_m3), ("kept_m3", outcome.kept_m3),
                                ("transition_m2", outcome.transition_m2), ("wall_max_m", 0.0),
                                ("wall_reason_min_angle_deg", removal.WALL_REASON_MIN_ANGLE_DEG),
                                ("wall_reason_min_height_m", removal.WALL_REASON_MIN_HEIGHT_M),
                                ("transition_deg", ANGLE_DEG), ("mesh_factor", 1.0)):
            self.assertEqual(report[quantity], value, quantity)
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states, {"STK-001": entities.EntityState.CURRENT, CODE: entities.EntityState.CURRENT})

    def test_e_the_thresholds_of_ca_9_are_copied_to_the_report_with_their_kind_and_provenance(self) -> None:
        """RF-016-15 (T48; hallazgos B-4 y S-8 de la verificación única; principio 2, spec §4): el informe (``des_prp_``) copia los dos
        umbrales de CA-9 (45° y 3 m) **con su tipo** (ADOPTADO) y su procedencia (CA-9 y D-6), además del valor y su unidad: una cifra
        sin tipo no se escribe."""
        rows = {quantity: (value, unit, note) for quantity, value, unit, note in self.query(
            f'SELECT quantity, value, unit_code, note FROM "{provenance.dataset_locator(provenance.ENTITY_REPORT_TABLE, FIRST, "V01")}"')}
        for quantity, value, unit in (("wall_reason_min_angle_deg", removal.WALL_REASON_MIN_ANGLE_DEG, "deg"),
                                      ("wall_reason_min_height_m", removal.WALL_REASON_MIN_HEIGHT_M, "m")):
            with self.subTest(quantity=quantity):
                found = rows[quantity]
                self.assertEqual(found[:2], (value, unit))
                self.assertEqual(found[2], removal.WALL_REASON_NOTE)
                for part in ("ADOPTADO", "CA-9", "D-6"):
                    self.assertIn(part, found[2])

    def test_f_a_second_removal_from_the_same_surface_is_refused_and_one_from_its_surface_is_created(self) -> None:
        """RF-015-04, RF-015-01: de cada superficie parte **una** entidad (``des.entity_start_taken``) y el nombre es único en la versión
        (``des.entity_name_repeated``): ninguna escribe nada; la retirada del Acopio 2 desde la **superficie de la primera**
        (``entity:RMV-001``) se crea como ``RMV-002`` y encadena."""
        error = self.refused(asked(SECOND, "Acopio 2"), "des.entity_start_taken")
        self.assertEqual(error.values["other"], FIRST)
        self.refused(asked(FIRST, "Acopio 2", start="entity:RMV-001"), "des.entity_name_repeated")
        _calculation, stored = self.make(asked(SECOND, "Acopio 2", start="entity:RMV-001"))
        self.assertEqual(self.operation_of("RMV-002"), str(stored.handle.uid))
        first_surface = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, FIRST)
        self.assertEqual(self.inputs_of(str(stored.handle.uid))[0], ("surface", first_surface), "parte de la superficie de la primera")
        chain = [(entry.record.code, entry.record.start) for entry in entities.registry(self.project, self.v1.uid)]
        self.assertEqual(chain, [("STK-001", None), (CODE, SURVEY), ("RMV-002", "entity:RMV-001")])

    # --- Lo apoyado y la pared ------------------------------------------------------------------------------

    def test_h_the_wall_is_confirmed_expressly_and_a_reason_is_recorded_when_it_passes_ca9(self) -> None:
        """RF-016-15 (A8; D-6, CA-9; error 47): con una pared (la de una superficie sin transición: aquí, forjada) más empinada que el
        ángulo de transición más la tolerancia de cara, «Crear» **no crea sin la confirmación expresa** (``des.removal_wall_unconfirmed``)
        y, de más de 45° y 3 m, tampoco sin un motivo (``des.removal_wall_reason``), **sin escribir nada y sin cerrar el cálculo**; con
        ella, se crea con el motivo como parámetro ``wall_reason`` y la confirmación (decisor, fecha, altura e inclinación) en los ajustes
        de la operación."""
        with forged_wall(4.0, 60.0):
            calculation = self.calculate(asked(THIRD, "Acopio 3", start="entity:RMV-002"))
        self.assertTrue(calculation.needs_wall_confirmation and calculation.needs_wall_reason)
        self.assertTrue(any(code == "des.removal_wall" for code in (notice.code for notice in calculation.notices)))
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.removal_wall_unconfirmed")
        self.assertEqual((caught.exception.values["height"], caught.exception.values["angle"]), (4.0, 60.0))
        calculation.confirm_removal(wall=True)
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.removal_wall_reason", "un motivo, además de la confirmación")
        self.assertEqual(self.state(), before, "sin escribir nada")
        self.assertTrue(calculation.open, "sin cerrar el cálculo")
        calculation.discard()
        with forged_wall(4.0, 60.0):
            reasoned = self.calculate(asked(THIRD, "Acopio 3", start="entity:RMV-002", wall_reason="Talud del vial de acceso"))
        self.clock.advance(minutes=1)
        reasoned.confirm_removal(wall=True)
        stored = reasoned.create(decided_by=USER)
        uid = str(stored.handle.uid)
        reason = self.query("SELECT value, decided_by FROM gb_parameter WHERE key = 'des.removal.rmv_003.wall_reason'")
        self.assertEqual([(json.loads(value), who) for value, who in reason], [("Talud del vial de acceso", USER)])
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0][0])
        confirmed = settings[supported_store.CONFIRMED]["wall"]
        self.assertEqual((confirmed["height_m"], confirmed["angle_deg"], confirmed["reason"], confirmed["decided_by"]),
                         (4.0, 60.0, "Talud del vial de acceso", USER))
        self.assertRegex(confirmed["decided_on"], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(self.figures_by_key(uid)["des.rmv_wall_max_m"], 4.0)
        self.assertNotIn(supported_store.CONFIRMED, json.loads(self.query(
            "SELECT settings FROM gb_operation WHERE uid = ?", str(self.stored.handle.uid))[0][0]), "sin pared, nada que confirmar")

    # --- Recalcular y reproducir ---------------------------------------------------------------------------

    def test_i_recomputing_repeats_the_removal_with_the_parameters_of_its_entity(self) -> None:
        """RF-015-02, RF-016-10, RF-015-16: cambiar el ángulo de transición de la entidad (``des.removal.rmv_001.transition_deg``) la deja
        obsoleta con su causa y **«Recalcular lo obsoleto»** la repite como una operación nueva que sustituye a la anterior (los
        parámetros de su entidad, no los que leyó la otra), con la misma identidad (``RMV-001``), sin reescribir sus parámetros, con
        la transición de 45° (otra superficie, otras cifras) y lo que la sigue en la cadena, obsoleto."""
        old = str(self.stored.handle.uid)
        figures = self.figures_by_key(old)
        self.assertEqual(self.stale_causes(old), set())
        self.change(design_params.entity_key(CODE, "transition_deg"), 45.0)
        self.assertNotEqual(self.stale_causes(old), set(), "obsoleta con su causa")
        self.assertEqual(entities.registry(self.project, self.v1.uid).get(CODE).record.state, entities.EntityState.STALE)
        rows = self.query("SELECT key, scope, value, rev FROM gb_parameter WHERE key LIKE 'des.removal.rmv_001.%' ORDER BY key, scope")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertTrue(all(result.status == recompute_mod.UnitStatus.DONE for result in outcome.results), outcome.results)
        new = self.operation_of(CODE)
        self.assertNotEqual(new, old)
        self.assertEqual(self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", new), [(old, "done")])
        self.assertEqual(len(self.query("SELECT rev FROM gb_parameter WHERE key = 'des.removal.rmv_001.transition_deg' AND scope = 'version'")), 1)
        after = self.query("SELECT key, scope, value, rev FROM gb_parameter WHERE key LIKE 'des.removal.rmv_001.%' ORDER BY key, scope")
        self.assertEqual([row[0] for row in after], [row[0] for row in rows], "sin parámetros nuevos")
        angle = self.query(f'SELECT value FROM "{provenance.dataset_locator(provenance.ENTITY_REPORT_TABLE, FIRST, "V01")}" '
                           "WHERE quantity = 'transition_deg'")
        self.assertEqual(angle, [(45.0,)], "lo repite con el parámetro vigente de su entidad, no con el que leyó la otra")
        self.assertEqual([figures[key] for key in sorted(figures)], [self.figures_by_key(new)[key] for key in sorted(figures)],
                         "el acopio 1 está en llano: la transición no cambia sus cifras")
        self.assertEqual(self.stale_causes(new), set())
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(entities.registry(self.project, self.v1.uid).get(CODE).record.state, entities.EntityState.CURRENT)

    def test_g_reproducing_the_frozen_revision_gives_the_same_surface_tables_and_figures(self) -> None:
        """RF-009-11, RF-015-02: congelada ``V01.r1`` con las dos primeras retiradas, reproducirla —**sin el proyecto**: desde lo congelado, la
        superficie de partida, las máscaras, el acopio (su tabla, su base y la superficie con que se detectó) y los parámetros—
        da, de cada retirada, la misma superficie, la misma huella y el mismo informe (el hash de cada dato) y las mismas cifras;
        reproducir no escribe nada en el proyecto."""
        self.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        type(self).revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before,
                         "reproducir no escribe en el proyecto")
        uids = {self.operation_of(code) for code in (CODE, "RMV-002")}
        mine = [check for check in report.outputs if check.operation_uid in uids]
        self.assertEqual(len(mine), 6, "la superficie, la huella y el informe de cada retirada")
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        self.assertEqual(len([check for check in report.figures if check.operation_uid in uids]), 12, "las seis cifras de cada una")
        self.assertTrue(all(check.same for check in report.outputs), [check for check in report.outputs if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    # --- La detección obsoleta ------------------------------------------------------------------------------

    def test_n_a_stale_detection_refuses_the_removal_naming_the_stockpile_and_what_changed(self) -> None:
        """RF-016-12: con la detección del acopio **obsoleta** (se cambió un umbral suyo), retirarlo se rechaza nombrando el acopio, la
        detección y lo que cambió (``des.removal_detection_stale``), **sin registrar nada**; con la detección al día otra vez
        (recalculada), no."""
        self.change(design_params.entity_key("STK-001", "margin_m"), 8.0)
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("STK-001").record.state, entities.EntityState.STALE)
        offered = supported_store.removable_stockpiles(self.project, self.v1.uid)
        self.assertEqual([item.state for item in offered], [entities.EntityState.STALE] * 5,
                         "el diálogo los sigue ofreciendo, con su estado: calcular dice qué cambió")
        error = self.refused(asked("Otra retirada", "Acopio 4", start="entity:RMV-003"), "des.removal_detection_stale")
        self.assertEqual((error.values["stockpile"], error.values["detection"]), ("Acopio 4", "Acopios"))
        self.assertTrue(error.values["cause"])
        self.assertIn(str(error.values["cause"]), error.text)
        self.clock.advance(minutes=1)
        ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("STK-001").record.state, entities.EntityState.CURRENT)
        self.calculate(asked("Otra retirada", "Acopio 4", start="entity:RMV-003")).discard()

    def test_n_the_cause_of_a_stale_detection_is_said_in_the_language_of_the_interface(self) -> None:
        """RF-016-12, RF-012-31 (T48; hallazgo D-5 de la verificación única): la causa de la detección obsoleta que da el rechazo es la de
        la 008 **en cada idioma** (``cause`` en español y ``cause_en`` en inglés: el texto en inglés ya no lleva la causa en español dentro
        de la frase inglesa); lo mismo que dice el texto de la 008 para esa operación."""
        self.change(design_params.entity_key("STK-001", "margin_m"), 9.0)
        error = self.refused(asked("Otra retirada", "Acopio 4", start="entity:RMV-003"), "des.removal_detection_stale")
        entry = entities.registry(self.project, self.v1.uid).get("STK-001")
        with self.project.read() as conn:
            wanted = {language: stale_module.item_text(conn, stale_module.OPERATION, str(entry.operation_uid), language=language)
                      for language in ("es", "en")}
        self.assertTrue(wanted["es"] and wanted["en"] and wanted["es"] != wanted["en"])
        self.assertEqual((error.values["cause"], error.values["cause_en"]), (wanted["es"], wanted["en"]))
        self.assertIn(wanted["es"], error.text_in("es"))
        self.assertNotIn(wanted["en"], error.text_in("es"))
        self.assertIn(wanted["en"], error.text_in("en"))
        self.assertNotIn(wanted["es"], error.text_in("en"))
        self.clock.advance(minutes=1)
        ops.finish(recompute_mod.recompute_steps(self.project))

    def test_o_a_sector_with_the_search_pending_refuses_the_removal_naming_it(self) -> None:
        """RF-015-07: la retirada **sí** llama a ``refuse_pending`` (la detección no: no mueve celdas), con los sectores que toca la huella
        del acopio: con su búsqueda de intocables **pendiente**, se rechaza (``des.sector_pending``) nombrando el sector y la orden que lo
        busca, sin escribir nada; con la búsqueda hecha, no se llama (como la plataforma, solo se mira el sector si hay alguno pendiente)."""
        with self.project.write_transaction() as conn:
            conn.execute("DELETE FROM core_untouchable_search")
        error = self.refused(asked("Otra retirada", "Acopio 4", start="entity:RMV-003"), "des.sector_pending")
        self.assertIn("Buscar elementos intocables por sector", error.text)
