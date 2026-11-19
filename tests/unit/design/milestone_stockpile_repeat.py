# SPDX-License-Identifier: GPL-3.0-or-later
"""Repetir la detección de acopios con la identidad por marca y decidir sobre los candidatos (spec 016, T13; HU-016-1;
RF-016-02, RF-016-08, RF-016-09, RF-016-10, RF-015-01, RF-015-02, RF-015-04, RF-015-16; D-15, D-23; plan 016 §5.4 A4, P-2 y
P-14): el hito de ``milestone_stockpile_detection`` (casos (b) y (c)). Va al paso «hito» (P-13): varias detecciones creadas y
repetidas en proyectos de 2 m y, para la regla de la mitad, la cantera de 1 m.

Repetir una detección es lo que hará el recálculo (T14): cambiar un parámetro de la entidad (o sus decisiones) y volver a
calcular con su código, **sustituyendo** la operación vigente (``supersedes``): se hace aquí con los mismos pasos —
``entity_parameters``, ``provenance.stockpile_request``, ``steps.stockpile_run(code=, supersedes=)`` y ``Calculation.create``—.

- **En una versión** (:class:`RepeatVersionTest`, en orden: ``test_a`` a ``test_e``): cambiar un umbral deja obsoleta la
  operación; repetirla da **la misma identidad** (las mismas claves de acopio, la misma entidad ``STK-001``, los mismos
  nombres de dato, los parámetros sin reescribir) con las cifras de cada acopio al día (la vigente de su ámbito), y lo que
  dependía de lo que escribió queda **obsoleto con su causa** (el dato que cambió) y lo demás, no; decidir sobre un candidato
  cambia el parámetro ``decisions`` (con su historial y decisor), deja obsoleta la detección con su causa, y repetirla da el
  candidato convertido como un acopio más con su clave (``c03``) y el descartado con su motivo; volver a preguntar lo quita.
- **En el proyecto** (:class:`RepeatProjectTest`): la misma operación con otro levantamiento, sin versión; lo que dependía de
  ella, en el proyecto y en una versión (RF-009-05), queda obsoleto.
- **La regla de la mitad con la cantera de 1 m** (:class:`MovedPileTest`, sin proyecto): el montículo que se corre 6 m
  conserva su clave y su decisión (el 77 % de cada huella) y el que se corre 15 m (el 42 %), no.
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_stockpile_operation as mso
from tests.unit.design import milestone_stockpile_prepare as tp
from tests.unit.design.test_stockpile_candidates import cparams
from tests.unit.design.test_stockpile_footprint import params_of

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
steps = import_geoblender("design.steps")
stockpile_store = import_geoblender("design.stockpile_store")
stockpiles = import_geoblender("design.stockpiles")

CODE = "STK-001"
USER = ops.USER
SECOND_SURVEY = "levantamiento_2"
"""El segundo levantamiento del proyecto: el primero sin el montón del Acopio 3 (otra fecha, otro volumen)."""


def key(name: str) -> str:
    """La clave del parámetro ``name`` de la detección ``STK-001``."""
    return design_params.entity_key(CODE, name)


class RepeatCase(mso.ObsoleteCase):
    """Lo de :class:`~tests.unit.design.milestone_stockpile_operation.ObsoleteCase` (V01 de la cantera de 2 m con los tipos de
    operación de prueba de lo que depende de una detección) con las operaciones y las cifras de la detección registradas y
    ``repeat``: repetir la detección vigente con otro valor de sus parámetros, como lo hará el recálculo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(
            *(provenance.OPERATION_TYPES_BY_NAME[op_type].definition(tp.never)
              for op_type in provenance.STOCKPILE_DETECT_TYPES), *provenance.STOCKPILE_FIGURES))

    @classmethod
    def create(cls, asked: Any, **options: Any) -> tuple[Any, Any]:
        """«Calcula» y «Crea» ``asked`` (V01 y sus máscaras por defecto): la ``Calculation`` y lo guardado."""
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        calculation = ops.last(steps.stockpile_run(cls.project, asked, **options))
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def change(self, name: str, value: Any, *, version: bool = True) -> None:
        """Cambia el parámetro ``name`` de ``STK-001`` a ``value`` (de V01 o, con ``version`` falso, del proyecto)."""
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, key(name), value=value, source="prueba de repetir (T13)", source_kind="person", decided_by=USER,
                reason="Se repite la detección con otro valor", version=self.v1.uid if version else None)
        self.clock.advance(minutes=1)

    def repeat(self, previous: str, *, version: bool = True) -> tuple[Any, Any]:
        """Repite la detección vigente ``previous`` (el uid de su operación) con los parámetros de su entidad **ahora**: la
        petición sale de sus ajustes y de sus valores vigentes (``entity_parameters``), se calcula con su código y
        sustituyendo a ``previous``, y se crea."""
        values = entity_store.entity_parameters(self.project, CODE, version=self.v1 if version else None)
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", previous)[0][0])
        asked = provenance.stockpile_request(settings, values)
        options: dict[str, Any] = {"code": CODE, "supersedes": previous}
        if not version:
            options.update(version=None, masks=None)
        return self.create(asked, **options)

    def table(self, family: str, name: str, *, version: bool = True) -> list[dict[str, Any]]:
        return list(stockpile_store.read_detection_table(self.project, family, name,
                                                         version_uid=self.v1.uid if version else ""))

    def latest_figure(self, name: str, **scope: str) -> float:
        """El valor vigente de la cifra ``name`` de ``scope`` (la última de su ámbito: RF-009-20)."""
        rows = self.query("SELECT value, scope FROM gb_figure WHERE key = ? ORDER BY created_at DESC, fid DESC", name)
        for value, found in rows:
            if all(json.loads(found).get(k) == v for k, v in scope.items()):
                return float(value)
        raise AssertionError(f"no hay ninguna cifra {name} con {scope}")


class RepeatVersionTest(RepeatCase):
    """RF-016-02, RF-016-08, RF-016-10, RF-015-16: la detección de V01 (las cinco marcas y los candidatos) repetida con otro
    margen y con decisiones sobre sus candidatos. **En orden** (``test_a`` a ``test_e``): cada una parte de lo que dejó la
    anterior."""

    first: ClassVar[Any]
    stored: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first, cls.stored = cls.create(tp.request(surface=tp.VERSION_SURFACE, candidates=True))
        mineral = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios mineral")
        cls.made("cubicación", mso.CONSUMER_VERSION, [mineral])
        cls.made("informe", mso.CONSUMER_VERSION, [provenance.dataset_name(provenance.ENTITY_REPORT_TABLE, "Acopios")])
        cls.made("sin relación", mso.CONSUMER_VERSION, [])
        cls.uid = str(cls.stored.handle.uid)

    def test_a_changing_a_threshold_makes_the_detection_stale_with_its_cause(self) -> None:
        """RF-016-10, RF-015-16, CE-016-01: cambiar el margen de la entidad deja obsoleta la operación **entera** con su causa
        (el parámetro, por su clave) y, en cascada, lo que depende de lo que escribió, sin tocar lo que no tiene relación."""
        self.assertEqual(self.stale_causes(self.uid), set())
        self.assertEqual(self.stale_causes(self.uids["cubicación"]), set())
        self.change("margin_m", 1.0)
        self.assertIn(("parameter_changed", key("margin_m")), self.stale_causes(self.uid))
        self.assertEqual(self.stale_causes(self.uids["sin relación"]), set())

    def test_b_repeating_keeps_the_identity_by_mark_and_makes_what_depended_stale_with_its_cause(self) -> None:
        """RF-016-10, RF-015-16, RF-015-01, RF-015-02: repetir con el margen nuevo sustituye a la operación (la anterior queda
        como historia) y da **la misma identidad**: la misma entidad ``STK-001``, las mismas claves de acopio en su orden, los
        mismos nombres de dato y los parámetros sin reescribir (sus filas y su historial son los de siempre más el cambio);
        las cifras de cada acopio, las de su clave al día (la vigente de su ámbito); y lo que dependía de la base de un material
        o del informe queda obsoleto con su causa (el dato que cambió), no lo que no tiene relación."""
        before_rows = self.table(provenance.STOCKPILES_TABLE, "Acopios")
        before_names = sorted(row[0] for row in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset'", self.uid))
        parameters = self.query("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.stockpile.stk_001.%'")
        calculation, stored = self.repeat(self.uid)
        self.assertTrue(calculation.entity.existing)
        new = str(stored.handle.uid)
        self.assertEqual(self.query("SELECT superseded_by, status FROM gb_operation WHERE uid = ?", self.uid),
                         [(new, "done")])
        self.assertEqual(self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", new),
                         [(self.uid, "done")])
        self.assertEqual(self.stale_causes(new), set(), "la repetida está al día")
        after_rows = self.table(provenance.STOCKPILES_TABLE, "Acopios")
        self.assertEqual([row["key"] for row in after_rows], [row["key"] for row in before_rows])
        self.assertTrue(any(new_row["volume_m3"] != old["volume_m3"] for new_row, old in zip(after_rows, before_rows,
                                                                                            strict=True)))
        self.assertEqual({row["margin_m"] for row in after_rows if row["key"] != "Acopio 3"}, {1.0})
        after_names = sorted(row[0] for row in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset'", new))
        self.assertEqual(after_names, before_names)
        self.assertEqual(self.query("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.stockpile.stk_001.%'"),
                         parameters, "repetir no reescribe los parámetros de la entidad")
        for row in after_rows:
            scope = {"stockpile": row["key"]}
            self.assertEqual(self.latest_figure("des.stk_volume_m3", **scope), row["volume_m3"], row["key"])
        self.assertEqual(self.latest_figure("des.stk_count"), 5.0)
        mineral = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios mineral")
        self.assertIn(("dataset_changed", mineral), self.stale_causes(self.uids["cubicación"]))
        report = provenance.dataset_name(provenance.ENTITY_REPORT_TABLE, "Acopios")
        self.assertIn(("dataset_changed", report), self.stale_causes(self.uids["informe"]))
        self.assertEqual(self.stale_causes(self.uids["sin relación"]), set())
        type(self).uid = new

    def test_c_deciding_on_a_candidate_changes_the_parameter_and_makes_the_detection_stale(self) -> None:
        """RF-016-08, RF-016-10, RF-015-16, P-14: decidir sobre un candidato (la lista vigente, ``c03``) es **cambiar** el
        parámetro ``decisions`` de la entidad (su historial, su decisor y su motivo) con la huella del candidato tal como la
        enseña la lista; la detección, que lo lee, queda obsoleta con su causa. Descartar otro y volver a preguntar lo quita;
        una clave que no está, un estado que no existe o la falta de motivo se rechazan."""
        candidates = self.table(provenance.STOCKPILE_CANDIDATES_TABLE, "Acopios")
        self.assertEqual([row["state"] for row in candidates], ["pending"] * 8)
        record = stockpile_store.decide_candidate(self.project, CODE, "c03", "converted", "Es un acopio de mineral",
                                                  version=self.v1, decided_by=USER)
        self.assertEqual(record.decided_by, USER)
        self.assertIn(("parameter_changed", key("decisions")), self.stale_causes(self.uid))
        found = stockpile_store.parse_decisions(record.value)
        self.assertEqual([(item.key, item.state, item.reason, item.decided_by) for item in found],
                         [("c03", "converted", "Es un acopio de mineral", USER)])
        self.assertEqual([list(run) for run in found[0].runs], json.loads(candidates[2]["footprint"]))
        stockpile_store.decide_candidate(self.project, CODE, "c05", "discarded", "Es una escombrera antigua",
                                         version=self.v1, decided_by=USER)
        stockpile_store.decide_candidate(self.project, CODE, "c05", "pending", "Se vuelve a preguntar", version=self.v1,
                                         decided_by=USER)
        now = stockpile_store.parse_decisions(
            entity_store.entity_parameters(self.project, CODE, version=self.v1)["decisions"])
        self.assertEqual([item.key for item in now], ["c03"])
        stockpile_store.decide_candidate(self.project, CODE, "c05", "discarded", "Es una escombrera antigua",
                                         version=self.v1, decided_by=USER)
        now_and_c05 = stockpile_store.parse_decisions(
            entity_store.entity_parameters(self.project, CODE, version=self.v1)["decisions"])
        self.assertEqual([item.key for item in now_and_c05], ["c03", "c05"])
        history = self.query("SELECT count(*) FROM gb_parameter_history h JOIN gb_parameter p ON p.uid = h.parameter_uid "
                             "WHERE p.key = ?", key("decisions"))
        self.assertGreaterEqual(history[0][0], 4)
        same = stockpile_store.decide_candidate(self.project, CODE, "c07", "pending", "Nunca se decidió", version=self.v1,
                                                decided_by=USER)
        self.assertEqual(stockpile_store.parse_decisions(same.value), now_and_c05, "volver a preguntar lo no decidido no cambia")
        with self.assertRaises(ValueError):
            stockpile_store.read_detection_table(self.project, provenance.ENTITY_TABLE, "Acopios", version_uid=self.v1.uid)
        with self.assertRaises(messages.DesignError) as caught:
            stockpile_store.decide_candidate(self.project, CODE, "c99", "converted", "No existe", version=self.v1)
        self.assertEqual(caught.exception.code, "des.stockpile_decisions_invalid")
        with self.assertRaises(ValueError):
            stockpile_store.decide_candidate(self.project, CODE, "c03", "quizá", "No es un estado", version=self.v1)
        with self.assertRaises(ValueError):
            stockpile_store.decide_candidate(self.project, CODE, "c03", "converted", "  ", version=self.v1)

    def test_d_repeating_with_the_decisions_makes_the_converted_candidate_a_stockpile(self) -> None:
        """RF-016-08, RF-016-09, RF-016-10, D-23: repetir con las decisiones deja las mismas claves de candidato, el ``c03``
        **convertido** (con su motivo, decisor y fecha) como un acopio más de la tabla de acopios —origen ``candidate``, sin capa
        ni marca, sin material— con su base y su espesor en el dato «sin material», y el ``c05`` descartado con su motivo en la
        lista; las cifras cuentan 6 acopios y 7 candidatos y la detección está al día."""
        before = self.table(provenance.STOCKPILE_CANDIDATES_TABLE, "Acopios")
        calculation, stored = self.repeat(self.uid)
        new = str(stored.handle.uid)
        self.assertEqual(self.stale_causes(new), set())
        after = self.table(provenance.STOCKPILE_CANDIDATES_TABLE, "Acopios")
        self.assertEqual([row["key"] for row in after], [row["key"] for row in before])
        by_key = {row["key"]: row for row in after}
        self.assertEqual((by_key["c03"]["state"], by_key["c03"]["reason"], by_key["c03"]["decided_by"]),
                         ("converted", "Es un acopio de mineral", USER))
        self.assertRegex(by_key["c03"]["decided_on"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual((by_key["c05"]["state"], by_key["c05"]["reason"]), ("discarded", "Es una escombrera antigua"))
        self.assertEqual(sum(row["state"] == "pending" for row in after), 6)
        rows = self.table(provenance.STOCKPILES_TABLE, "Acopios")
        self.assertEqual([row["key"] for row in rows], [*tp.NAMES, "c03"])
        mine = rows[-1]
        self.assertEqual((mine["name"], mine["origin"], mine["layer"], mine["source_fid"], mine["material"]),
                         ("Candidato c03", "candidate", None, None, None))
        self.assertEqual(mine["cells"], by_key["c03"]["cells"])
        self.assertEqual(json.loads(mine["footprint"]), json.loads(by_key["c03"]["footprint"]))
        self.assertAlmostEqual(mine["volume_m3"] / by_key["c03"]["volume_m3"], 1.0, delta=1e-9)
        self.assertEqual(self.latest_figure("des.stk_count"), 6.0)
        self.assertEqual(self.latest_figure("des.stk_candidates"), 7.0)
        label = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios sin material")
        outputs = {row[0] for row in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset'", new)}
        self.assertIn(label, outputs)
        self.assertEqual(calculation.entity.decisions[0].key, "c03")
        type(self).uid = new

    def test_e_a_candidate_taken_back_to_pending_leaves_the_stockpile(self) -> None:
        """RF-016-10, RF-015-16: volver a preguntar por el ``c03`` lo quita de los acopios en la detección siguiente: la tabla
        de acopios vuelve a tener las cinco marcas, el candidato vuelve a ``pending`` con su clave y su motivo y decisor se
        pierden, y los datos de «sin material» (que ya no tienen acopio) no se escriben otra vez: los de la operación
        anterior pasan a «sustituidos» (no quedan vigentes sin operación que los respalde) y lo que los usaba, a obsoleto."""
        gone = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios sin material")
        self.made("usa lo de sin material", mso.CONSUMER_VERSION, [gone])
        self.assertEqual(self.stale_causes(self.uids["usa lo de sin material"]), set())
        stockpile_store.decide_candidate(self.project, CODE, "c03", "pending", "Se vuelve a preguntar", version=self.v1,
                                         decided_by=USER)
        _calculation, stored = self.repeat(self.uid)
        rows = self.table(provenance.STOCKPILES_TABLE, "Acopios")
        self.assertEqual([row["key"] for row in rows], list(tp.NAMES))
        by_key = {row["key"]: row for row in self.table(provenance.STOCKPILE_CANDIDATES_TABLE, "Acopios")}
        self.assertEqual((by_key["c03"]["state"], by_key["c03"]["reason"]), ("pending", None))
        self.assertEqual(by_key["c05"]["state"], "discarded")
        outputs = {row[0] for row in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset'", str(stored.handle.uid))}
        self.assertNotIn(gone, outputs)
        for family in (provenance.STOCKPILE_BASE_GRID, provenance.STOCKPILE_THICKNESS_GRID):
            name = provenance.dataset_name(family, "Acopios sin material")
            self.assertEqual(self.query("SELECT status FROM gb_dataset WHERE name = ?", name), [("superseded",)],
                             "lo que la detección ya no escribe no sigue vigente")
        self.assertNotEqual(self.stale_causes(self.uids["usa lo de sin material"]), set())
        self.assertEqual(self.latest_figure("des.stk_count"), 5.0)
        self.assertEqual(self.latest_figure("des.stk_candidates"), 8.0)


class RepeatProjectTest(RepeatCase):
    """RF-016-02, RF-016-10, RF-009-05, D-15: la detección **del proyecto** repetida con otro levantamiento (el primero sin el
    montón del Acopio 3): la misma identidad por marca, sin versión, y lo que dependía de lo que escribió queda obsoleto con su
    causa **en el proyecto y en una versión** (una versión puede consumir un dato del proyecto)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        grid = cls.grid
        others = tuple(mound for mound in sdata.SURVEY_MOUNDS if mound.name != "Acopio 3")
        lower = sdata.previous_survey(grid) + sdata.mound_heights(grid.shape, grid.dx, others)
        res_fixtures.write_grids(cls.project, [(SECOND_SURVEY, gis.Raster(grid, lower, sdata.CRS, sdata.VERTICAL))],
                                 message="Segundo levantamiento: sin el montón del Acopio 3")
        cls.clock.advance(minutes=1)
        cls.first, cls.stored = cls.create(tp.request(), version=None, masks=None)
        base = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios estéril")
        cls.made("cubicación", mso.CONSUMER_PROJECT, [base], version=False)
        cls.made("retirada en V01", mso.CONSUMER_VERSION, [base])
        cls.made("sin relación", mso.CONSUMER_PROJECT, [], version=False)
        cls.uid = str(cls.stored.handle.uid)

    def test_repeating_on_another_survey_keeps_the_identity_and_makes_the_dependents_stale(self) -> None:
        """RF-016-10, RF-015-16, D-15, RF-009-05: cambiar la superficie de la entidad del proyecto al segundo levantamiento deja
        obsoleta la detección (``des.stockpile.stk_001.surface``); repetirla da las mismas claves de acopio y el Acopio 3, sin
        su montón, queda sin huella (se rechaza y no se registra: RF-016-04); lo demás es lo mismo; y la cubicación del proyecto y
        la retirada de V01 que usaban la base de los acopios de estéril quedan obsoletas con su causa, y la que no tiene relación,
        no."""
        before = {row["key"]: row for row in self.table(provenance.STOCKPILES_TABLE, "Acopios", version=False)}
        self.assertEqual(list(before), list(tp.NAMES))
        self.change("surface", sdata.SURVEY_DATASET.replace(sdata.SURVEY_LABEL, SECOND_SURVEY), version=False)
        self.assertIn(("parameter_changed", key("surface")), self.stale_causes(self.uid))
        calculation, stored = self.repeat(self.uid, version=False)
        self.assertEqual(calculation.op_type, provenance.STOCKPILE_DETECT_PROJECT)
        after = {row["key"]: row for row in self.table(provenance.STOCKPILES_TABLE, "Acopios", version=False)}
        self.assertEqual(list(after), [name for name in tp.NAMES if name != "Acopio 3"],
                         "sin su montón, el Acopio 3 no da huella: se rechaza y no se registra")
        for name, row in after.items():
            self.assertEqual(row["volume_m3"], before[name]["volume_m3"], name)
        self.assertEqual([item.key for item in calculation.outcome.rejected], ["Acopio 3"])
        self.assertEqual(self.stale_causes(str(stored.handle.uid)), set())
        base = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios estéril")
        for name in ("cubicación", "retirada en V01"):
            with self.subTest(consumer=name):
                self.assertIn(("dataset_changed", base), self.stale_causes(self.uids[name]))
        self.assertEqual(self.stale_causes(self.uids["sin relación"]), set())
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", self.uid),
                         [(str(stored.handle.uid),)])


class MovedPileTest(unittest.TestCase):
    """RF-016-10, D-23 con la cantera de 1 m (sin proyecto): repetir la detección con los candidatos y una decisión sobre
    ``P1``: si el montículo se corre 6 m al este (el 77 % de cada huella) conserva su clave y su decisión y, si se corre 15 m (el
    42 %), se pregunta otra vez con otra clave, y la decisión sigue reservando la suya."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = qfx.GRID
        cls.marks = tuple(stockpiles.StockpileMark(mark.name, np.flatnonzero(sdata.in_box(mark.box, cls.grid)),
                                                   margin_m=mark.margin_m, material=mark.material, base=mark.base)
                          for mark in sdata.MARKS)
        cls.perimeter = sdata.in_box(qfx.PERIMETER_LOCAL)
        cls.job = stockpiles.StockpileJob(
            "Acopios", CODE, cls.grid, sdata.survey(), cls.marks, params_of(), {sdata.PREVIOUS_LABEL: sdata.previous_survey()},
            cparams(), cls.perimeter)
        cls.first = ops.compute(cls.job)
        cls.pile = sdata.survey_mound("P1")
        cls.row, cls.col = cls.grid.nrows - 1 - int(cls.pile.cy), int(cls.pile.cx)

    def holder(self, found: Any, row: int, col: int) -> int:
        """El índice del candidato cuya zona tiene la celda ``(row, col)``."""
        for index, item in enumerate(found.states):
            mask = np.zeros(self.grid.shape, dtype=bool)
            mask[item.candidate.window] = item.candidate.zone
            if mask[row, col]:
                return index
        raise AssertionError("ningún candidato tiene esa celda")

    def decision(self) -> tuple[int, Any]:
        index = self.holder(self.first, self.row, self.col)
        item = self.first.states[index]
        decided = stockpile_store.candidate_decision(item, self.grid.ncols, state="discarded", reason="Es una escombrera",
                                                     decided_by=USER, decided_on=ops.DECIDED_ON)
        return index, decided

    def test_a_pile_moved_by_six_meters_keeps_its_key_and_decision(self) -> None:
        """RF-016-10, D-23: el montículo P1 corrido 6 m al este (comparte el 77 % del área de cada huella) es el mismo
        candidato: conserva su clave y su decisión (descartado, con su motivo), y los demás, sin decidir."""
        index, decided = self.decision()
        moved = tuple(m.moved(6.0, 0.0) if m.name == "P1" else m for m in sdata.SURVEY_MOUNDS)
        surface = sdata.previous_survey() + sdata.mound_heights(self.grid.shape, 1.0, moved)
        again = ops.compute(dataclasses.replace(self.job, surface=surface), decisions=(decided,))
        slot = self.holder(again, self.row, self.col + 6)
        item = again.states[slot]
        self.assertEqual((item.key, item.state, item.reason), (decided.key, "discarded", "Es una escombrera"))
        self.assertEqual(len(again.states), 8)
        self.assertEqual(sum(state.state == "pending" for state in again.states), 7)
        self.assertEqual(len({state.key for state in again.states}), 8)
        self.assertEqual(again.states[slot].key, f"c{index + 1:02d}")

    def test_a_pile_moved_by_fifteen_meters_is_asked_again_and_the_key_stays_reserved(self) -> None:
        """RF-016-10, D-23: el montículo P1 corrido 15 m (comparte el 42 %) es otro candidato: sin decidir, con una clave que no
        es la de la decisión (que sigue reservada y no se reutiliza); todos los candidatos están sin decidir."""
        index, decided = self.decision()
        moved = tuple(m.moved(15.0, 0.0) if m.name == "P1" else m for m in sdata.SURVEY_MOUNDS)
        surface = sdata.previous_survey() + sdata.mound_heights(self.grid.shape, 1.0, moved)
        again = ops.compute(dataclasses.replace(self.job, surface=surface), decisions=(decided,))
        slot = self.holder(again, self.row, self.col + 15)
        self.assertEqual(again.states[slot].state, "pending")
        self.assertEqual({state.state for state in again.states}, {"pending"})
        self.assertNotIn(decided.key, [state.key for state in again.states])
        self.assertEqual(len({state.key for state in again.states}), len(again.states))
        self.assertEqual(len(again.stockpiles), 5, "descartar no convierte nada")


if __name__ == "__main__":
    unittest.main()
