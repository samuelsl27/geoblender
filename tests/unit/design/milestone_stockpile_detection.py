# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular» la detección de acopios y su resumen (spec 016, T12; HU-016-1; RF-016-04, RF-016-05, RF-016-06, RF-016-07,
RF-016-08; RF-015-03, RF-015-13, RF-015-29; RNF-016-03, RNF-016-05; plan 016 §5.3.2 y §5.4 A0) y crearla (spec 016, T13;
RF-016-02, RF-016-08, RF-016-09, RF-016-10, RF-015-01, RF-015-02, RF-015-04, RF-015-16, RNF-016-07): casos (a), (b) y (c) de
este módulo (repetir con candidatos, el hito ``milestone_stockpile_repeat``); y recalcularla y consultar lo
que dejó (spec 016, T14; RF-016-10, RF-015-02, RF-015-04, RF-015-16, CE-016-01: casos (d) y (e); reproducirla desde lo
congelado, el hito ``milestone_stockpile_recompute``).

Sobre la cantera sintética de los acopios (``tests.support.stockpile_data``, T01), con las cuentas hechas a mano:

- **El cálculo compartido** (:class:`ComputeStepsTest`, ``stockpile_store.detection_compute_steps``): es ``detect_steps``
  por pasos de ≤ ``budget_s``, sin proyecto dentro y sin escribir nada; lo comparten «Calcular», el recálculo y la
  reproducción. Devuelve el ``StockpileOutcome`` y cada acopio se calcula en su ventana de trabajo (A0). Cerrar el
  generador a mitad lo cierra todo y no toca ninguna entrada.
- **El resumen** (:class:`SummaryTest`, ``stockpile_store.stockpile_summary`` y ``preview.StockpileSummary``): cada acopio
  con su plano, su huella, su volumen, su espesor máximo y sus notas; los avisos de RF-016-05, 06 y 07 con su lugar y
  con el número de decimales que no esconde lo que dicen; los acopios **rechazados** nombrando marca, caso y lugar (y
  sin registrarlos); los candidatos y lo que quedará obsoleto al crearla.
- **«Calcular» no escribe** (:class:`CalculateTest`, ``steps.stockpile_run``): sobre el proyecto (en la rejilla de
  2 m, con las marcas de la cantera más una que no da acopio), del proyecto o de una versión, deja la ``Calculation`` con
  su resumen y **nada en el proyecto** (ni la base de datos, ni operaciones, datos, parámetros, ficheros ni temporales);
  cerrar a mitad o un fallo después de calcular no dejan nada; los rechazos salen al avanzar.
- **Crear** (:class:`CreateTest`, ``Calculation.create`` y ``create_steps``; T13): en el proyecto y en una versión **la misma
  detección** —los mismos datos con el mismo contenido, las mismas cifras y las mismas filas de parámetros— y **lo único que
  cambia es dónde se escribe** (con y sin el código de versión); en **una transacción** (si algo falla no queda nada, ni
  ficheros); el hash de la capa de marcas, sin cambio; la tabla de acopios, la de candidatos, la base y el espesor por
  material (dispersos), el terreno sin acopios, la superficie con que se detectó y el informe; las cifras con su ámbito
  (acopio y material); una detección sin ningún acopio; y por pasos de la interfaz (RNF-016-03).
- **Las decisiones sobre los candidatos** (:class:`DecisionsTest`, sin proyecto): el formato del parámetro, la clave
  ``c03`` de cada candidato (estable al repetir por la regla de D-23) y la conversión de un candidato en acopio.
- **Recalcular y consultar** (:class:`RecomputeTest`, ``store.recompute_run`` y ``stockpile_store.detections_on``; T14): la
  detección de V01 y la del proyecto, recalculadas como operación nueva que sustituye a la anterior **con la misma
  identidad**, lo que dejó, consultable por superficie (solo las al día), y el umbral de la 011 cambiado: las dos obsoletas con
  su causa y «Recalcular lo obsoleto» las repite.
Spec 016, T43 (RNF-016-06): pasó del «verde» al paso «hito» (P-13), sin cambiar ninguna prueba; antes, ``test_stockpile_operation.py``.
"""

from __future__ import annotations

import dataclasses
import json
import math
import time
import unittest
from collections.abc import Generator, Iterator
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import milestone_stockpile_prepare as tp
from tests.unit.design.test_stockpile_candidates import cparams
from tests.unit.design.test_stockpile_footprint import params_of

gis_messages = import_geoblender("gis.messages")
core_params = import_geoblender("core.params")
gis = import_geoblender("gis")
gis_store = import_geoblender("gis.store")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
surfaces = import_geoblender("design.surfaces")
design_params = import_geoblender("design.params")
entities_module = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
recompute_mod = import_geoblender("core.provenance.recompute")
stockpile_store = import_geoblender("design.stockpile_store")
stockpiles = import_geoblender("design.stockpiles")

GRID = qfx.grid_of(qfx.COARSE_STEP_M)
"""La rejilla gruesa de la cantera (200 × 200 celdas de 2 m)."""
FLAT_BOX = (20.0, 20.0, 40.0, 40.0)
"""Una marca sobre el plano del levantamiento, sin montón: ninguna celda sube sobre el umbral (se rechaza)."""
PERIMETER_BOX = (20.0, 60.0, 360.0, 340.0)
"""El perímetro de actuación de la cantera (local)."""
LAYER_MIXED = "gis_fea_marcas_con_llano"
THRESHOLD = "0,30 m"
"""El umbral de la huella (el de la 011, 0,30 m) como lo lee una persona."""


def last(work: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos (``Calculation`` de «Calcular»)."""
    result = None
    for step in work:
        result = step.result
    return result


def returned[T](work: Generator[Any, None, T]) -> tuple[list[Any], T]:
    """Los pasos que da ``work`` y lo que **devuelve** (``yield from``)."""
    shown: list[Any] = []
    while True:
        try:
            shown.append(next(work))
        except StopIteration as done:
            return shown, done.value


def survey_marks(*, flat: bool = True) -> tuple[Any, ...]:
    """Las cinco marcas de la cantera sobre el levantamiento de 2 m (el Acopio 5 con su base propia) y, si ``flat``,
    la ``Llano``, sobre un plano sin montón."""
    marks = [stockpiles.StockpileMark(mark.name, tp.hand_cells(mark.box), margin_m=mark.margin_m,
                                      material=mark.material, base=mark.base) for mark in sdata.MARKS]
    if flat:
        marks.append(stockpiles.StockpileMark("Llano", tp.hand_cells(FLAT_BOX), material="estéril"))
    return tuple(marks)


def survey_job(*, candidates: bool = False, flat: bool = True, surface: np.ndarray | None = None) -> Any:
    """El trabajo de detección del levantamiento: las cinco marcas (más la que no da acopio) y, si ``candidates``, el
    perímetro de la cantera con los umbrales de D-3."""
    return stockpiles.StockpileJob(
        "Acopios", "STK-001", GRID, sdata.survey(GRID) if surface is None else surface, survey_marks(flat=flat),
        params_of(), {sdata.PREVIOUS_LABEL: sdata.previous_survey(GRID)},
        cparams() if candidates else None, sdata.in_box(PERIMETER_BOX, GRID) if candidates else None)


def case_job(case: Any, key: str = "Acopio", *, material: str | None = None) -> Any:
    """El trabajo de un montón de :func:`sdata.mound_case` con su marca y el plano de 3° o de 8°."""
    mark = stockpiles.StockpileMark(key, np.flatnonzero(sdata.in_box(case.mark_box, case.grid)), material=material)
    return stockpiles.StockpileJob("Acopios", "STK-001", case.grid, case.terrain, (mark,), params_of())


def pair_job() -> Any:
    """El Acopio 1 y el 2, que se tocan, en su ventana de celdas de 1 m (E1, RF-016-06)."""
    case = sdata.touching_pair()
    marks = tuple(stockpiles.StockpileMark(mark.name, np.flatnonzero(sdata.in_box(mark.box, case.grid)))
                  for mark in case.marks)
    return stockpiles.StockpileJob("Acopios", "STK-001", case.grid, case.terrain, marks, params_of())


def summary_of(job: Any, **options: Any) -> tuple[Any, Any]:
    """El resultado de ``job`` y su resumen (de una versión, sin nada obsoleto)."""
    outcome = stockpiles.detect_stockpiles(job)
    return outcome, stockpile_store.stockpile_summary(outcome, version="V01", scope=stockpile_store.VERSION, **options)


def codes(found: Any) -> list[str]:
    """Los códigos de los avisos y notas de un resumen, en su orden."""
    return [notice.code for notice in found.notices]


def only(found: Any, code: str) -> Any:
    """El aviso ``code`` del resumen ``found`` (uno solo)."""
    matching = [notice for notice in found.notices if notice.code == code]
    assert len(matching) == 1, f"{code}: {codes(found)}"
    return matching[0]


def absolute_centre(box: tuple[float, float, float, float]) -> tuple[float, float]:
    """El centro absoluto (a mano) de la caja local ``box``."""
    left, bottom, right, top = box
    x, y = cfx.absolute([((left + right) / 2.0, (bottom + top) / 2.0)])[0]
    return float(x), float(y)


# ---------------------------------------------------------------------------------------------
# El cálculo compartido
# ---------------------------------------------------------------------------------------------


class ComputeStepsTest(unittest.TestCase):
    """RF-016-04, RF-016-05, RF-016-08, RF-015-29, RNF-016-03, RNF-016-05, A0 (el dominio): ``detection_compute_steps`` es
    la detección por pasos, sin proyecto dentro y sin escribir nada."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = survey_job(candidates=True)

    def test_it_is_the_detection_by_steps_and_returns_the_outcome(self) -> None:
        """RF-016-04, RF-016-05, RF-016-08: lo que **devuelve** (``yield from``) es el ``StockpileOutcome`` de
        ``detect_stockpiles`` —los cinco acopios (celdas, volumen y notas), la marca que se rechaza, los candidatos, las
        cifras y los avisos— con un presupuesto mínimo (muchos pasos) y con el de por defecto."""
        direct = stockpiles.detect_stockpiles(self.job)
        for options in ({"budget_s": 1e-9}, {}):
            shown, found = returned(stockpile_store.detection_compute_steps(self.job, **options))
            with self.subTest(options=options):
                self.assertTrue(all(step.result is None for step in shown), "el resultado se devuelve, no se enseña")
                self.assertIsInstance(found, stockpiles.StockpileOutcome)
                self.assertEqual([item.key for item in found.stockpiles], [item.key for item in direct.stockpiles])
                for mine, theirs in zip(found.stockpiles, direct.stockpiles, strict=True):
                    np.testing.assert_array_equal(mine.cells, theirs.cells)
                    np.testing.assert_array_equal(mine.base, theirs.base)
                    self.assertEqual((mine.volume_m3, mine.area_m2), (theirs.volume_m3, theirs.area_m2))
                    self.assertEqual([(n.code, dict(n.values)) for n in mine.notes],
                                     [(n.code, dict(n.values)) for n in theirs.notes])
                self.assertEqual([item.key for item in found.rejected], ["Llano"])
                self.assertEqual(len(found.candidates.items), len(direct.candidates.items))
                self.assertEqual(found.figures, direct.figures)
        self.assertEqual(len(direct.stockpiles), 5)
        self.assertEqual(len(direct.candidates.items), 8, "los ocho que pasan los filtros de CE-016-01")

    def test_it_gives_small_steps_with_their_progress(self) -> None:
        """RNF-016-03, RNF-016-05, RF-015-29: con un presupuesto mínimo da **muchos** pasos —el primero, antes de
        calcular nada—, cada uno con su fase, de ``0`` a un total que no baja de lo hecho y con un texto en español;
        pasan por la formación de los acopios, las bases y los candidatos."""
        shown, _found = returned(stockpile_store.detection_compute_steps(self.job, budget_s=1e-9))
        self.assertGreater(len(shown), 10)
        self.assertEqual((shown[0].phase, shown[0].done), ("stockpile_compute", 0))
        self.assertIn("«Acopios»", shown[0].message)
        for step in shown:
            self.assertTrue(0 <= step.done <= step.total, step)
            self.assertTrue(step.message and "{" not in step.message, step)
        self.assertTrue({"stockpiles"} <= {step.phase for step in shown})
        self.assertGreater(len(shown), len(self.job.marks), "al menos un paso por marca")

    def test_each_stockpile_is_calculated_in_its_own_work_window(self) -> None:
        """A0 (plan 016 §5.4): cada marca se forma en **su ventana de trabajo** —su caja ampliada por el margen y la
        corona—, no en la rejilla entera: la superficie que recibe ``grow_footprint`` de cada una es menor que
        la de la rejilla (200 × 200) y cabe la marca con su margen."""
        shapes: list[tuple[int, ...]] = []
        job = survey_job()
        original = stockpiles.grow_footprint

        def spy(z: np.ndarray, mark: np.ndarray, grid: Any, params: Any) -> Any:
            shapes.append(z.shape)
            return original(z, mark, grid, params)

        with mock.patch.object(stockpiles, "grow_footprint", spy):
            returned(stockpile_store.detection_compute_steps(job))
        self.assertEqual(len(shapes), 5, "una por marca sin base propia: A1 a A4 y la Llano (la del Acopio 5 usa la suya)")
        for shape in shapes:
            self.assertTrue(shape[0] < GRID.nrows and shape[1] < GRID.ncols, shape)
            self.assertGreaterEqual(min(shape), 10 + 2 * 7, "la marca (10 celdas) con su margen y su corona por lado")

    def test_closing_it_midway_closes_the_detection_and_changes_no_input(self) -> None:
        """RF-015-29, RNF-016-05: cerrar el generador tras unos pasos cierra los de la detección (el generador de
        debajo), no da resultado y no modifica la superficie, las marcas ni las bases del trabajo."""
        surface = np.array(self.job.surface, copy=True)
        cells = [np.array(mark.cells, copy=True) for mark in self.job.marks]
        closed: list[bool] = []

        def spy(job: Any, *, budget_s: float) -> Iterator[Any]:
            try:
                yield from stockpiles.detect_steps(job, budget_s=budget_s)
            finally:
                closed.append(True)

        with mock.patch.object(stockpile_store, "detect_steps", spy):
            work = stockpile_store.detection_compute_steps(self.job, budget_s=1e-9)
            for _ in range(4):
                next(work)
            self.assertEqual(closed, [])
            work.close()
            self.assertEqual(closed, [True], "cerrar el generador cierra la detección de debajo")
            with self.assertRaises(StopIteration):
                next(work)
        np.testing.assert_array_equal(self.job.surface, surface)
        for mine, before in zip((mark.cells for mark in self.job.marks), cells, strict=True):
            np.testing.assert_array_equal(mine, before)

    def test_a_job_that_is_not_a_job_is_a_program_error(self) -> None:
        """RF-015-29: lo que no es un ``StockpileJob`` es un error del programa (``TypeError``) al avanzar, antes de
        calcular nada."""
        with self.assertRaises(TypeError):
            returned(stockpile_store.detection_compute_steps("no es un trabajo"))  # type: ignore[arg-type]

    def test_the_outcome_names_itself_for_the_operation(self) -> None:
        """RF-015-02 (el mensaje de la operación): el resultado dice la detección, su código, los acopios y los m²
        y m³ de su huella en español; es lo que ``Calculation.message`` da a ``commit`` al crearla (T13)."""
        outcome = stockpiles.detect_stockpiles(self.job)
        text = outcome.message
        for part in ("«Acopios»", "STK-001", "5 acopios", "1 marca rechazada", "8 candidatos"):
            self.assertIn(part, text)
        area = round(math.fsum(item.area_m2 for item in outcome.stockpiles), 2)
        volume = round(math.fsum(item.volume_m3 for item in outcome.stockpiles), 2)
        self.assertIn(f"{gis_messages.format_value(area)} m²", text)
        self.assertIn(f"{gis_messages.format_value(volume)} m³", text)
        one = stockpiles.detect_stockpiles(survey_job(flat=False)).message
        self.assertNotIn("rechazada", one)
        self.assertNotIn("candidato", one)


# ---------------------------------------------------------------------------------------------
# El resumen
# ---------------------------------------------------------------------------------------------


class SummaryTest(unittest.TestCase):
    """RF-016-04, RF-016-05, RF-016-06, RF-016-07, RF-016-08, RF-015-03, RF-015-13: lo que dice el resumen de lo calculado."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.outcome, cls.summary = summary_of(survey_job(candidates=True))
        cls.pair_outcome, cls.pair = summary_of(pair_job())
        cls.tilt_outcome, cls.tilted = summary_of(case_job(sdata.mound_case("cone", 8.0), "Acopio 7", material="mineral"))

    def test_the_summary_names_the_detection_and_carries_the_figures(self) -> None:
        """RF-015-03: el resumen lleva el nombre, el código y la versión (``None`` si es del proyecto), las cifras
        que se registrarán (las de la detección: cuántos acopios y candidatos y, por acopio y material, su área, su
        volumen, su espesor máximo y la inclinación de su plano), el ámbito y una nota de cabecera con los acopios y
        su volumen."""
        summary, outcome = self.summary, self.outcome
        self.assertEqual((summary.name, summary.code, summary.version, summary.scope),
                         ("Acopios", "STK-001", "V01", stockpile_store.VERSION))
        self.assertEqual(summary.figures, outcome.figures)
        self.assertEqual({figure.key for figure in summary.figures},
                         {"des.stk_count", "des.stk_candidates", "des.stk_area_m2", "des.stk_volume_m3",
                          "des.stk_thickness_max_m", "des.stk_plane_tilt_deg"})
        head = summary.notices[0]
        self.assertEqual(head.code, "des.stockpile_summary")
        self.assertEqual((head.values["entity"], head.values["code"], head.values["stockpiles"]),
                         ("Acopios", "STK-001", 5))
        self.assertAlmostEqual(head.values["volume"], sum(item.volume_m3 for item in outcome.stockpiles), delta=1e-9)
        self.assertAlmostEqual(head.values["area"], sum(item.area_m2 for item in outcome.stockpiles), delta=1e-9)
        project = stockpile_store.stockpile_summary(outcome, version=None, scope=stockpile_store.PROJECT)
        self.assertEqual((project.version, project.scope), (None, stockpile_store.PROJECT))

    def test_each_stockpile_has_its_plane_footprint_volume_and_maximum_thickness(self) -> None:
        """RF-016-04, RF-016-02: un renglón por acopio **registrado** (en el orden de las marcas, sin la rechazada)
        con su material, su área, su volumen, su espesor máximo, su lugar y su plano (la cota en el centro, la pendiente
        en % y el azimut; ninguno si su base es propia, y entonces dice de qué superficie sale); su línea del resumen lo
        dice en español y en inglés con la coma o el punto decimal."""
        rows = {row.key: row for row in self.summary.stockpiles}
        self.assertEqual(list(rows), [item.key for item in self.outcome.stockpiles])
        self.assertNotIn("Llano", rows)
        for item in self.outcome.stockpiles:
            row = rows[item.key]
            with self.subTest(stockpile=item.key):
                self.assertEqual((row.name, row.material, row.base_surface), (item.name, item.material, item.base_surface))
                self.assertEqual((row.area_m2, row.volume_m3, row.thickness_max_m, row.x, row.y),
                                 (item.area_m2, item.volume_m3, item.thickness_max_m, item.x, item.y))
                self.assertEqual((row.plane_level_m, row.plane_slope_percent, row.plane_azimuth_deg,
                                  row.plane_tilt_deg),
                                 (item.plane_level_m, item.plane_slope_percent, item.plane_azimuth_deg,
                                  item.plane_tilt_deg))
        self.assertIsNone(rows["Acopio 5"].plane_level_m)
        self.assertEqual(rows["Acopio 5"].base_surface, sdata.PREVIOUS_LABEL)
        lines = {notice.values["mark"]: notice for notice in self.summary.notices
                 if notice.code in ("des.stockpile_item", "des.stockpile_item_own_base")}
        self.assertEqual(set(lines), set(rows))
        self.assertEqual(lines["Acopio 5"].code, "des.stockpile_item_own_base")
        self.assertEqual(lines["Acopio 1"].code, "des.stockpile_item")
        text = lines["Acopio 2"].text("es")
        self.assertIn("«Acopio 2»", text)
        self.assertIn(f"{rows['Acopio 2'].thickness_max_m:.3f}".replace(".", ","), text)  # 3,100 m
        self.assertIn("mineral", text)
        self.assertIn("«levantamiento_previo»", lines["Acopio 5"].text("es"))
        self.assertIn("maximum thickness 3.100 m", lines["Acopio 2"].text("en"))
        for line in (*self.summary.lines("es"), *self.summary.lines("en")):
            self.assertTrue(isinstance(line, str) and "{" not in line and "?" not in line, line)

    def test_the_notes_of_a_stockpile_carry_their_mark_and_place_once(self) -> None:
        """RF-016-05: los avisos y notas de cada acopio —la corona con pocas celdas llanas, que no se estabilice— van
        en su renglón y en el resumen, **una vez**, con su marca y su lugar (``x``, ``y`` absolutas)."""
        found = codes(self.summary)
        self.assertEqual(found.count("des.stockpile_crown_few_flat"), 2, "el Acopio 1 y el 3; el 5 usa su base propia")
        self.assertEqual(found.count("des.stockpile_not_converged"), 1)
        row = {item.key: item for item in self.summary.stockpiles}["Acopio 4"]
        self.assertEqual([note.code for note in row.notes], ["des.stockpile_not_converged"])
        note = only(self.summary, "des.stockpile_not_converged")
        self.assertEqual(note.values["mark"], "Acopio 4")
        self.assertTrue(all(key in note.values for key in ("x", "y", "turns")))
        self.assertIn("«Acopio 4»", note.text("es"))
        self.assertEqual(note.severity, "warning")
        after = codes(self.summary)
        item = next(i for i, notice in enumerate(self.summary.notices)
                    if notice.code == "des.stockpile_item" and notice.values["mark"] == "Acopio 4")
        self.assertEqual(after[item + 1], "des.stockpile_not_converged", "la nota va tras la línea de su acopio")

    def test_shared_cells_are_told_once_with_both_marks_the_area_and_the_place(self) -> None:
        """RF-016-06 (E1): los dos acopios que se tocan comparten celdas: el resumen lo avisa **una vez** con las
        dos marcas, el área repartida (m²) y el lugar, y la nota está en el renglón de cada uno de los dos."""
        found = codes(self.pair)
        self.assertEqual(found.count("des.stockpile_shared_cells"), 1)
        shared = only(self.pair, "des.stockpile_shared_cells")
        self.assertEqual({shared.values["mark"], shared.values["other"]}, {"Acopio 1", "Acopio 2"})
        self.assertGreater(shared.values["area"], 0.0)
        self.assertEqual(shared.severity, "warning")
        self.assertIn(f"{shared.values['mark']}", shared.text("es"))
        for row in self.pair.stockpiles:
            self.assertIn("des.stockpile_shared_cells", [note.code for note in row.notes])
        self.assertEqual(self.pair_outcome.shared[0].area_m2, shared.values["area"])

    def test_a_tilt_that_is_limited_says_both_inclinations_to_the_hundredth(self) -> None:
        """RF-016-07: el aviso de la inclinación limitada da la ajustada y la limitada (≈ 8° → 4°) y el cuantil, con dos
        decimales: 4,04° frente a 4° no se leería «4,0° … 4,0°»; el acopio lleva la nota."""
        note = only(self.tilted, "des.stockpile_tilt_limited")
        fitted = note.values["fitted"]
        self.assertAlmostEqual(fitted, 8.0, delta=0.05)  # el ajuste con las vueltas de la huella: 7,99° del plano de 8°
        self.assertEqual((note.values["limit"], note.values["quantile"]), (4.0, 0.6))
        text = note.text("es")
        for part in ("«Acopio 7»", f"{fitted:.2f}".replace(".", ",") + "°", "4,00°", "0,60"):
            self.assertIn(part, text)
        self.assertIn(f"{fitted:.2f}°", note.text("en"))
        self.assertIn("des.stockpile_tilt_limited", [n.code for n in self.tilted.stockpiles[0].notes])
        close = preview.Notice("des.stockpile_tilt_limited", {"mark": "A", "fitted": 4.04, "limit": 4.0, "quantile": 0.65,
                                                              "x": 1.0, "y": 2.0})
        self.assertIn("4,04°", close.text("es"))
        self.assertIn("4,00°", close.text("es"))
        self.assertIn("0,65", close.text("es"))

    def test_the_threshold_of_a_rejection_keeps_its_hundredths(self) -> None:
        """RF-016-04, D-17: el umbral de la huella de ``des.stockpile_no_cells`` se lee con sus centésimas: 0,25 m no se
        lee «0,2 m» ni 0,30 m, «0,3 m»."""
        for value, shown in ((0.25, "0,25 m"), (0.3, THRESHOLD)):
            notice = preview.Notice("des.stockpile_no_cells", {"mark": "M", "threshold": value, "x": 1.0, "y": 2.0})
            with self.subTest(value=value):
                self.assertIn(shown, notice.text("es"))
        self.assertIn("0.25 m", preview.Notice("des.stockpile_no_cells", {"mark": "M", "threshold": 0.25, "x": 1.0,
                                                                         "y": 2.0}).text("en"))

    def test_the_decimals_of_the_015_do_not_change(self) -> None:
        """RF-015-13 (sin cambiar los de la 015): ``limit`` y ``threshold`` de los avisos de la plataforma y de la
        cantera siguen con **un** decimal: el cambio es de los mensajes de los acopios, no de los nombres de los valores."""
        edge = preview.Notice("des.platform_edge_steep", {"entity": "P", "cells": 3, "angle": 35.0, "tolerance": 5.0,
                                                          "max": 52.25, "limit": 40.04, "x": 1.0, "y": 2.0,
                                                          "at_reach": 1, "reach": 20.0, "at_masks": 1, "other": 1})
        self.assertIn("límite de 40,0°", edge.text("es"))
        self.assertNotIn("40,04", edge.text("es"))

    def test_a_rejected_mark_is_named_with_its_case_and_place_and_is_not_registered(self) -> None:
        """RF-016-04: la marca que no da ninguna celda sobre el umbral (``Llano``, un plano sin montón) sale en el
        resumen **nombrando la marca, el caso y su lugar** (el centro de la marca, a mano), con el umbral de 0,30 m, y no
        se registra: no tiene renglón de acopio ni cifras; es un aviso."""
        (rejected,) = self.summary.rejected
        self.assertEqual((rejected.key, rejected.name, rejected.notice.code), ("Llano", "Llano", "des.stockpile_no_cells"))
        x, y = absolute_centre(FLAT_BOX)
        self.assertEqual(rejected.notice.values["mark"], "Llano")
        self.assertAlmostEqual(rejected.notice.values["x"], x, delta=1e-6)
        self.assertAlmostEqual(rejected.notice.values["y"], y, delta=1e-6)
        self.assertEqual(rejected.notice.severity, "warning")
        text = rejected.notice.text("es")
        for part in ("«Llano»", THRESHOLD, "no se registra"):
            self.assertIn(part, text)
        self.assertIn(rejected.notice, self.summary.notices)
        self.assertEqual(codes(self.summary).index("des.stockpile_no_cells"), 1, "justo tras la cabecera")
        self.assertNotIn("Llano", {row.key for row in self.summary.stockpiles})
        self.assertNotIn("Llano", {figure.scope.get("stockpile") for figure in self.summary.figures})
        self.assertIn(text, self.summary.warnings("es"))
        self.assertEqual(only(self.summary, "des.stockpile_summary").values["rejected"], 1)

    def test_a_mark_without_terrain_is_rejected_with_its_place_too(self) -> None:
        """RF-016-04: una marca a la que le falta terreno en su huella o en su corona (un hueco de la superficie sin
        dato) se rechaza, se nombra con el caso y el lugar del primer hueco, y las demás marcas se calculan igual."""
        surface = sdata.survey(GRID)
        left, bottom, right, top = sdata.MARKS[2].box
        surface[sdata.in_box((left - 4.0, bottom - 4.0, right + 4.0, top + 4.0), GRID)] = np.nan
        outcome = stockpiles.detect_stockpiles(survey_job(surface=surface))
        summary = stockpile_store.stockpile_summary(outcome, version="V01", scope=stockpile_store.VERSION)
        (rejected,) = [row for row in summary.rejected if row.key == "Acopio 3"]
        self.assertIn(rejected.notice.code, ("des.stockpile_no_terrain", "des.stockpile_no_terrain_crown"))
        self.assertTrue(left - 4.0 <= rejected.notice.values["x"] - sdata.BASE[0] <= right + 4.0)
        self.assertTrue(bottom - 4.0 <= rejected.notice.values["y"] - sdata.BASE[1] <= top + 4.0)
        self.assertEqual({row.key for row in summary.stockpiles}, {"Acopio 1", "Acopio 2", "Acopio 4", "Acopio 5"})
        self.assertEqual(only(summary, "des.stockpile_summary").values["stockpiles"], 4)
        self.assertIn("«Acopio 3»", rejected.notice.text("es"))

    def test_the_candidates_are_listed_with_their_footprint_volume_and_plane(self) -> None:
        """RF-016-08: con los candidatos pedidos, el resumen dice cuántos hay (8) y por qué se descartó el resto de
        las zonas (sobre una marca, fuera del rango de área y las que no se pudieron formar), y lista cada candidato
        con su huella, su volumen y su plano —el de la detección, sin cálculo nuevo—; nunca una zona sin filtrar."""
        found, rows = self.outcome.candidates, self.summary.candidates
        self.assertEqual(len(rows), 8)
        for number, (row, item) in enumerate(zip(rows, found.items, strict=True), start=1):
            with self.subTest(candidate=number):
                self.assertEqual((row.number, row.area_m2, row.volume_m3), (number, item.footprint.area_m2,
                                                                            item.footprint.volume_m3))
                self.assertEqual((row.x, row.y), item.centre)
                self.assertEqual(row.plane_slope_percent, item.footprint.plane.slope_percent)
        counts = self.summary.counts
        self.assertEqual((counts.zones, counts.on_marks, counts.too_small, counts.too_large, counts.rejected),
                         (found.zones, found.on_marks, found.too_small, found.too_large, found.rejected))
        self.assertEqual(counts.zones, 8 + counts.on_marks + counts.filtered + counts.rejected)
        head = only(self.summary, "des.stockpile_candidates")
        self.assertEqual((head.values["candidates"], head.values["zones"]), (8, found.zones))
        self.assertEqual(codes(self.summary).count("des.stockpile_candidate_item"), 8)
        self.assertIn("8 candidatos", head.text("es"))
        self.assertEqual(only(self.summary, "des.stockpile_summary").values["candidates"], 8)
        self.assertNotIn("des.stockpile_more_candidates", codes(self.summary))

    def test_without_candidates_the_summary_has_none_and_does_not_mention_them(self) -> None:
        """RF-016-08: si no se piden los candidatos, el resumen no los tiene (``None``, no «0») ni los nombra."""
        _outcome, plain = summary_of(survey_job())
        self.assertIsNone(plain.candidates)
        self.assertIsNone(plain.counts)
        self.assertTrue(all("candidate" not in code for code in codes(plain)), codes(plain))
        self.assertNotIn("candidates", only(plain, "des.stockpile_summary").values)

    def test_the_candidate_lines_are_capped_like_the_obsolete_names(self) -> None:
        """RF-016-08, RF-015-03: el resumen lista los 10 primeros candidatos y una nota con los que faltan (con su
        singular); la lista entera se queda en el resumen."""
        outcome = self.outcome
        many = dataclasses.replace(outcome, candidates=dataclasses.replace(
            outcome.candidates, items=outcome.candidates.items * 2))  # 16
        summary = stockpile_store.stockpile_summary(many, version="V01", scope=stockpile_store.VERSION)
        found = codes(summary)
        self.assertEqual(found.count("des.stockpile_candidate_item"), preview.SUMMARY_ITEMS)
        self.assertEqual(len(summary.candidates), 16)
        more = only(summary, "des.stockpile_more_candidates")
        self.assertEqual(more.values["candidates"], 6)
        self.assertIn("y 6 candidatos más", more.text("es"))
        eleven = dataclasses.replace(outcome, candidates=dataclasses.replace(
            outcome.candidates, items=(*outcome.candidates.items, outcome.candidates.items[0], outcome.candidates.items[1],
                                       outcome.candidates.items[2])))  # 11
        one = stockpile_store.stockpile_summary(eleven, version="V01", scope=stockpile_store.VERSION)
        self.assertIn("y 1 candidato más", only(one, "des.stockpile_more_candidates").text("es"))

    def test_what_will_become_stale_is_told_with_the_singular(self) -> None:
        """RF-015-03, RF-015-13 (RF-015-16): lo que quedará obsoleto al crear se dice en notas con su cuenta y sus
        nombres entre «», los 10 primeros y un «…», con el singular («1 operación»); sin nada, ninguna nota."""
        make = preview.Obsolete
        kind = preview.ObsoleteKind.DEPENDENT
        none = preview.stockpile_obsolete_notices("Acopios", "V01", ())
        self.assertEqual(none, ())
        one = preview.stockpile_obsolete_notices(
            "Acopios", "V01", (make(kind, "Retirada del 7", "des.stockpile_removal", "uid-1"),))
        self.assertEqual([note.code for note in one], ["des.stockpile_obsolete_dependents"])
        self.assertIn("1 operación", one[0].text("es"))
        self.assertIn("1 operation ", one[0].text("en"))
        self.assertIn("«Retirada del 7»", one[0].text("es"))
        twelve = [make(kind, f"Op {number}", "des.platform", f"uid-{number}") for number in range(12)]
        many = preview.stockpile_obsolete_notices("Acopios", "V01", twelve)
        self.assertIn("12 operaciones", many[0].text("es"))
        self.assertEqual(many[0].text("es").count("«Op"), preview.SUMMARY_ITEMS)
        self.assertIn("…", many[0].text("es"))
        summary = stockpile_store.stockpile_summary(self.outcome, version="V01", scope=stockpile_store.VERSION,
                                                    obsolete=twelve)
        self.assertEqual(summary.obsolete, tuple(twelve))
        self.assertEqual(codes(summary)[-1], "des.stockpile_obsolete_dependents", "lo obsoleto, al final")
        self.assertEqual(self.summary.obsolete, ())
        self.assertNotIn("des.stockpile_obsolete_dependents", codes(self.summary))

    def test_the_lines_and_the_warnings_are_the_notices_in_both_languages(self) -> None:
        """RF-015-03: ``lines`` da todo lo que dice el resumen, línea a línea, y ``warnings`` solo los avisos, en español y
        en inglés, sin marcadores por llenar."""
        self.assertEqual(len(self.summary.lines("es")), len(self.summary.notices))
        warnings = self.summary.warnings("es")
        self.assertEqual(len(warnings), sum(1 for notice in self.summary.notices if notice.severity == "warning"))
        self.assertTrue(warnings)
        for line in (*self.summary.lines("es"), *self.summary.lines("en")):
            self.assertNotIn("{", line)
        self.assertNotEqual(self.summary.lines("es"), self.summary.lines("en"))


# ---------------------------------------------------------------------------------------------
# «Calcular» no escribe
# ---------------------------------------------------------------------------------------------


class CalculateTest(tp.PrepareCase):
    """RF-015-03, RF-015-29, RF-016-04, RF-016-08: ``steps.stockpile_run`` deja la ``Calculation`` con su resumen y **nada
    en el proyecto**, en el proyecto o en una versión; los rechazos salen al avanzar; cerrar a mitad o fallar tras
    calcular no dejan nada."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        sdata.write_layer(cls.project, cls.clock, tp.layer_of(
            LAYER_MIXED, [cfx.rectangle(*tp.BOXES["Acopio 1"]), cfx.rectangle(*tp.BOXES["Acopio 3"]),
                          cfx.rectangle(*FLAT_BOX)], ["Acopio 1", "Acopio 3", "Llano"],
            margen=(None, 6.0, None), material=("mineral", "estéril", "estéril")))
        cls.clock.advance(minutes=1)

    def run_steps(self, asked: Any, **options: Any) -> Iterator[Any]:
        options.setdefault("masks", self.masks_v1)
        options.setdefault("version", self.v1.uid)
        return steps.stockpile_run(self.project, asked, **options)

    def calculate(self, asked: Any, **options: Any) -> Any:
        """«Calcular» ``asked`` hasta el final: la ``Calculation``, que se descarta al acabar."""
        calculation = last(self.run_steps(asked, **options))
        self.addCleanup(calculation.discard)
        return calculation

    def mixed(self, **changes: Any) -> Any:
        """La detección de las tres marcas (con la que no da acopio) sobre el levantamiento de V01."""
        return tp.request(layer=LAYER_MIXED, surface=tp.VERSION_SURFACE, **changes)

    def test_a_version_detection_is_calculated_without_writing_anything(self) -> None:
        """RF-015-03, RF-016-04, RF-016-08: «Calcular» sobre una superficie de V01 deja la ``Calculation`` de
        ``des.stockpile_detect`` (abierta, con su resultado, su entidad preparada ``STK-001`` y sus cifras) y el
        resumen (los dos acopios, la marca ``Llano`` rechazada y los candidatos pedidos) **sin escribir nada** (ni la base
        de datos, ni operaciones, datos, parámetros ni ficheros ni temporales); descartarla tampoco."""
        before = self.state()
        calculation = last(self.run_steps(self.mixed(candidates=True)))
        self.assertEqual(self.state(), before, "calcular no escribe nada")
        self.assertEqual([name for name in self.state()["files"] if ".tmp" in name], [])
        self.assertTrue(calculation.open)
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         (provenance.STOCKPILE_DETECT, tp.request().name, "V01"))
        self.assertEqual((calculation.entity.code, calculation.entity.scope), ("STK-001", stockpile_store.VERSION))
        self.assertIsInstance(calculation.outcome, stockpiles.StockpileOutcome)
        self.assertEqual(calculation.figures, calculation.outcome.figures)
        self.assertIn("«Acopios»", calculation.message)
        summary = calculation.summary
        self.assertIsInstance(summary, preview.StockpileSummary)
        self.assertEqual((summary.name, summary.code, summary.version), ("Acopios", "STK-001", "V01"))
        self.assertEqual([row.key for row in summary.stockpiles], ["Acopio 1", "Acopio 3"])
        self.assertEqual([row.key for row in summary.rejected], ["Llano"])
        self.assertEqual(len(summary.candidates), len(calculation.outcome.candidates.items))
        self.assertGreater(len(summary.candidates), 8, "los ocho de CE-016-01 y los montones del levantamiento sin marca")
        self.assertEqual(calculation.notices, summary.notices)
        self.assertEqual(calculation.lines("es"), summary.lines("es"))
        self.assertEqual(calculation.warnings("es"), summary.warnings("es"))
        calculation.discard()
        self.assertFalse(calculation.open)
        self.assertEqual(self.state(), before, "descartarla no deja nada")

    def test_a_project_detection_is_calculated_without_writing_anything_either(self) -> None:
        """RF-015-03, D-15: sobre una superficie **del proyecto** (sin versión activa) «Calcular» deja la ``Calculation`` de
        ``des.stockpile_detect_project`` —del proyecto: sin versión ni máscaras— con el mismo resumen y nada escrito."""
        before = self.state()
        calculation = last(self.run_steps(tp.request(), version=None, masks=None))
        self.assertEqual(self.state(), before)
        self.assertEqual(calculation.op_type, provenance.STOCKPILE_DETECT_PROJECT)
        self.assertEqual((calculation.entity.scope, calculation.entity.version), (stockpile_store.PROJECT, None))
        summary = calculation.summary
        self.assertEqual((summary.version, summary.scope), (None, stockpile_store.PROJECT))
        self.assertEqual([row.key for row in summary.stockpiles], list(tp.NAMES))
        self.assertIsNone(summary.candidates)
        calculation.discard()
        self.assertEqual(self.state(), before)

    def test_a_refused_detection_is_refused_when_advancing_and_writes_nothing(self) -> None:
        """RF-015-29, RF-015-08: los rechazos de la preparación (aquí, una superficie que no existe) salen **al avanzar**,
        antes de calcular, con su código y sin escribir nada."""
        before = self.state()
        work = self.run_steps(tp.request(surface="gis_dtm_no_existe"), version=None, masks=None)
        with self.assertRaises(Exception) as caught:
            list(work)
        self.assertEqual(getattr(caught.exception, "code", None), "gis.dataset_unknown")
        self.assertEqual(self.state(), before)

    def test_closing_it_midway_or_failing_after_calculating_leaves_nothing(self) -> None:
        """RF-015-29, RNF-016-05: cerrar los pasos tras unos cuantos (Esc), o un fallo **después** de calcular (al
        armar el resumen), no dejan nada en el proyecto ni temporales; con un presupuesto mínimo los pasos son
        muchos."""
        before = self.state()
        work = self.run_steps(self.mixed(candidates=True), budget_s=1e-9)
        shown = [next(work) for _ in range(12)]
        self.assertTrue(all(step.result is None for step in shown))
        work.close()
        self.assertEqual(self.state(), before)
        with mock.patch.object(stockpile_store, "detection_summary", side_effect=RuntimeError("falla el resumen")):
            with self.assertRaises(RuntimeError):
                list(self.run_steps(self.mixed()))
        self.assertEqual(self.state(), before)

    def test_the_threshold_it_read_is_checked_again_when_creating_in_a_version_and_in_the_project(self) -> None:
        """RF-015-03, RF-016-02, D-17 (D-14 de la 013): el umbral de la huella que leyó el cálculo (``res.anthropic_presence_m``,
        el de la 011) se comprueba otra vez al crear —también en una detección **del proyecto**, que no tiene versión y solo lee
        el ámbito del proyecto—: sigue valiendo lo mismo y, si cambia entre «Calcular» y «Crear», el resultado ya no le
        corresponde (``des.input_changed``)."""
        key = "res.anthropic_presence_m"
        self.assertEqual(steps.resolve_values(self.project, "", [key]), {key: 0.3})
        for asked, options in ((self.mixed(), {}), (tp.request(), {"version": None, "masks": None})):
            calculation = self.calculate(asked, **options)
            with self.subTest(op_type=calculation.op_type):
                self.assertEqual(calculation._values, {key: 0.3})
                calculation._check_parameters()
                with mock.patch.object(steps, "resolve_values", return_value={key: 0.5}):
                    with self.assertRaises(messages.DesignError) as caught:
                        calculation._check_parameters()
                self.assertEqual(caught.exception.code, "des.input_changed")


# ---------------------------------------------------------------------------------------------
# Crear: en el proyecto y en la versión, en una transacción (T13)
# ---------------------------------------------------------------------------------------------

LAYER_FLAT_ONLY = "gis_fea_solo_llano"
LAYER_MATERIALS = "gis_fea_materiales_repetidos"
OWN_BASE = {"base_field": "base", "margin_field": None, "material_field": None}
MATERIALS = ("mineral", "estéril")
"""Los materiales de las cinco marcas de la cantera, por orden de aparición (Acopio 1 a 5)."""
USER = "Samuel (IMGA)"


class CreateTest(tp.PrepareCase):
    """RF-016-02, RF-016-08, RF-016-09, RF-015-01, RF-015-02, RF-015-04, RNF-016-03, RNF-016-07: «Crear» la detección de
    acopios en una versión (``des.stockpile_detect``) y en el proyecto (``des.stockpile_detect_project``): **la misma
    detección** con lo único distinto de dónde se escribe, en una transacción y con las capas de entrada sin tocar.

    Cuatro detecciones sobre la cantera de 2 m: ``version`` (las cinco marcas y los candidatos, sobre el levantamiento
    de V01), ``project`` (lo mismo sobre el levantamiento del proyecto), ``own`` (una marca con la superficie de su base
    propia, del proyecto) y ``empty`` (una marca que no da acopio, de V01)."""

    calculations: ClassVar[dict[str, Any]]
    stored: ClassVar[dict[str, Any]]
    before: ClassVar[dict[str, Any]]
    after: ClassVar[dict[str, Any]]

    @classmethod
    def marks_state(cls) -> dict[str, Any]:
        """La capa de marcas como la verá QGIS: su hash en el registro y sus filas."""
        with cls.project.read() as conn:
            found = gis_store.read_features(conn, sdata.MARKS_LAYER)
            digest = conn.execute("SELECT content_sha256 FROM gb_dataset WHERE name = ?", (sdata.MARKS_LAYER,)).fetchall()
        return {"sha256": digest, "fids": list(found.fids),
                "values": {name: list(column) for name, column in found.values.items()}}

    @classmethod
    def build(cls, key: str, asked: Any, **options: Any) -> None:
        """«Calcula» y «Crea» ``asked`` (V01 y sus máscaras por defecto) y lo guarda en ``key``."""
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        calculation = last(steps.stockpile_run(cls.project, asked, **options))
        cls.calculations[key] = calculation
        cls.stored[key] = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(
            *(provenance.OPERATION_TYPES_BY_NAME[op_type].definition(tp.never)
              for op_type in provenance.STOCKPILE_DETECT_TYPES), *provenance.STOCKPILE_FIGURES))
        for layer in tp.defect_layers():
            if layer.name == tp.LAYER_BASE_OK:
                sdata.write_layer(cls.project, cls.clock, layer)
        sdata.write_layer(cls.project, cls.clock, tp.layer_of(LAYER_FLAT_ONLY, [cfx.rectangle(*FLAT_BOX)], ["Llano"]))
        sdata.write_layer(cls.project, cls.clock, tp.layer_of(
            LAYER_MATERIALS, [cfx.rectangle(*tp.BOXES["Acopio 1"]), cfx.rectangle(*tp.BOXES["Acopio 3"])],
            ["Acopio 1", "Acopio 3"], margen=(None, None), material=("Estéril", "estéril")))
        cls.clock.advance(minutes=1)
        cls.before, cls.calculations, cls.stored = cls.marks_state(), {}, {}
        cls.build("version", tp.request(surface=tp.VERSION_SURFACE, candidates=True))
        cls.build("project", tp.request(candidates=True), version=None, masks=None)
        cls.build("own", tp.request("Con base", layer=tp.LAYER_BASE_OK, marks=OWN_BASE), version=None, masks=None)
        cls.build("empty", tp.request("Vacia", layer=LAYER_FLAT_ONLY, surface=tp.VERSION_SURFACE,
                                      marks={"margin_field": None, "material_field": None}))
        cls.after = cls.marks_state()

    # --- Ayudas ----------------------------------------------------------------------------------

    def outcome(self, which: str) -> Any:
        return self.calculations[which].outcome

    def uid(self, which: str) -> str:
        return str(self.stored[which].handle.uid)

    def outputs(self, which: str) -> list[tuple[str, str, str, str]]:
        """Lo que escribió la operación ``which``: ``(nombre, ubicación, papel, hash)`` de cada dato, en su orden."""
        return [tuple(row) for row in self.query(
            "SELECT d.name, d.locator, io.role, d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' "
            "ORDER BY io.fid", self.uid(which))]

    def locator(self, which: str, family: str, label: str | None = None) -> str:
        """La ubicación del dato de la familia ``family`` de la detección ``which`` (``label``, el material si lo hay)."""
        call = self.calculations[which]
        name = call.name if label is None else f"{call.name} {label}"
        return provenance.dataset_locator(family, name, call.version or None)

    def table(self, which: str, family: str) -> list[dict[str, Any]]:
        """Las filas de la tabla ``family`` de la detección ``which``, por el nombre de cada columna."""
        names = [column.name for column in store.columns_of(self.calculations[which].op_type, family)]
        found = self.query(f'SELECT {", ".join(names)} FROM "{self.locator(which, family)}" ORDER BY fid')
        return [dict(zip(names, row, strict=True)) for row in found]

    def sparse(self, which: str, family: str, label: str | None = None) -> np.ndarray:
        """La rejilla dispersa de la familia ``family`` de la detección ``which`` leída del proyecto."""
        call = self.calculations[which]
        name = provenance.dataset_name(family, call.name if label is None else f"{call.name} {label}")
        return tp.drive(surfaces.read_surface_steps(self.project, name, version_uid=call.entity.version_uid or "")).values

    def figures(self, which: str) -> list[tuple[str, dict[str, str], float]]:
        return [(key, json.loads(scope), value) for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", self.uid(which))]

    # --- Dónde se escribe ----------------------------------------------------------------------------

    def test_the_same_detection_is_written_in_the_project_and_in_the_version(self) -> None:
        """RF-016-02, RF-016-09, D-15: la detección de V01 y la del proyecto (el mismo levantamiento) escriben **los mismos
        datos** —los mismos nombres, papeles y hashes de contenido, una base y un espesor por material— y lo único que
        cambia es **dónde**: la ubicación lleva el código de la versión (``_v01``) o no lo lleva."""
        version, project = self.outputs("version"), self.outputs("project")
        expected = [f"des_{family}_acopios{label}" for family, label in (
            ("stk", ""), ("stc", ""), ("stb", "_mineral"), ("stb", "_esteril"), ("stt", "_mineral"),
            ("stt", "_esteril"), ("stg", ""), ("stp", ""), ("prp", ""))]
        roles = ["stockpiles", "stockpile_candidates", "stockpile_base", "stockpile_base", "stockpile_thickness",
                 "stockpile_thickness", "stockpile_ground", "stockpile_surface", provenance.ENTITY_REPORT_ROLE]
        for found in (version, project):
            self.assertEqual([row[0] for row in found], expected)
            self.assertEqual([row[2] for row in found], roles)
        self.assertEqual([row[3] for row in version], [row[3] for row in project], "el mismo contenido, dato a dato")
        for here, there in zip(version, project, strict=True):
            self.assertEqual(here[1], tp.versions_model.version_locator(there[1], "V01"), here[0])
            self.assertTrue((self.root / here[1]).exists() if here[1].startswith("rasters/") else True)
        self.assertEqual(self.figures("version"), self.figures("project"))

    def test_each_scope_has_its_operation_and_its_parameters(self) -> None:
        """RF-015-01, RF-015-04, D-15: la operación de V01 es ``des.stockpile_detect`` (de versión) y la del proyecto,
        ``des.stockpile_detect_project`` (de proyecto), las dos hechas; **todas las filas** de los parámetros de la entidad
        (las de los valores por defecto también: ``begin_operation`` no crea otras) son de la versión o del proyecto, con
        su origen y el decisor de quien creó; el código ``STK-001`` es el de cada ámbito."""
        found = {row[0]: row[1:] for row in self.query(
            "SELECT uid, op_type, scope, status FROM gb_operation WHERE uid IN (?, ?)", self.uid("version"),
            self.uid("project"))}
        self.assertEqual(found[self.uid("version")], (provenance.STOCKPILE_DETECT, "version", "done"))
        self.assertEqual(found[self.uid("project")], (provenance.STOCKPILE_DETECT_PROJECT, "project", "done"))
        store_of = core_params.ParameterStore(self.project)
        for which, version in (("version", self.v1.uid), ("project", None)):
            prepared = self.calculations[which].entity
            self.assertEqual(prepared.code, "STK-001")
            self.assertGreaterEqual(len(prepared.rows), 20)
            with self.subTest(scope=which):
                for row in prepared.rows:
                    record = store_of.get(row.key, version=version)
                    self.assertIsNotNone(record, row.key)
                    self.assertEqual((record.value, record.source, record.decided_by), (row.value, row.source, USER),
                                     row.key)
        owned = self.query("SELECT scope, count(*) FROM gb_parameter WHERE key LIKE 'des.stockpile.stk_001.%' "
                           "GROUP BY scope ORDER BY scope")
        self.assertEqual([row[0] for row in owned], ["project", "version"])
        self.assertEqual(owned[0][1], owned[1][1], "las mismas filas en los dos ámbitos")

    def test_the_layer_of_marks_is_not_modified(self) -> None:
        """RF-016-02, principio 7: la capa de marcas (su hash en el registro, sus filas y sus campos) es la misma después de
        crear cuatro detecciones; es una entrada, no una salida."""
        self.assertEqual(self.after, self.before)
        for which in ("version", "project", "own", "empty"):
            self.assertNotIn(sdata.MARKS_LAYER, {row[0] for row in self.outputs(which)})

    # --- Las tablas -----------------------------------------------------------------------------------

    def test_the_table_of_stockpiles_has_one_row_per_stockpile_with_its_footprint_in_runs(self) -> None:
        """RF-016-02, RF-016-09: ``des_stk_`` tiene una fila por acopio, en el orden de las marcas: su clave, su nombre, su
        procedencia (la capa, la marca y su margen), su material, el plano en el centro de su huella, la huella en tramos
        (que son **las celdas** de la huella), el área, el volumen y el espesor máximo (iguales a lo calculado) y sus
        notas con su código."""
        outcome = self.outcome("version")
        rows = self.table("version", provenance.STOCKPILES_TABLE)
        self.assertEqual([row["key"] for row in rows], list(tp.NAMES))
        fids = self.calculations["version"].entity.fids
        for row, item in zip(rows, outcome.stockpiles, strict=True):
            with self.subTest(key=item.key):
                self.assertEqual((row["name"], row["material"], row["origin"], row["layer"], row["source_fid"]),
                                 (item.name, item.material, "mark", sdata.MARKS_LAYER, fids[item.key]))
                self.assertEqual(row["margin_m"], 6.0 if item.key == "Acopio 3" else 10.0)
                runs = np.array(json.loads(row["footprint"]), dtype=np.int64).reshape(-1, 3)
                self.assertTrue(np.array_equal(stockpiles.runs_cells(runs, GRID.ncols), item.cells))
                self.assertEqual((row["cells"], row["area_m2"], row["volume_m3"], row["thickness_max_m"]),
                                 (item.cells.size, item.area_m2, item.volume_m3, item.thickness_max_m))
                self.assertEqual((row["x"], row["y"]), (item.x, item.y))
                self.assertEqual((row["plane_level_m"], row["plane_slope_percent"], row["plane_azimuth_deg"],
                                  row["plane_tilt_deg"]),
                                 (item.plane_level_m, item.plane_slope_percent, item.plane_azimuth_deg,
                                  item.plane_tilt_deg))
                self.assertEqual((row["turns"], bool(row["converged"])), (item.turns, item.converged))
                self.assertEqual([note["code"] for note in json.loads(row["notes"])], [note.code for note in item.notes])
                self.assertIsNone(row["base_surface"])

    def test_a_mark_with_its_own_base_keeps_it_in_its_column_and_has_no_plane(self) -> None:
        """RF-016-03, D-20: el acopio con una superficie de base propia (el campo ``base`` de la capa) la anota en
        ``base_surface`` —el nombre del dato— y no tiene plano (ni cota, ni pendiente, ni azimut, ni inclinación); el que
        no la pide, sí."""
        rows = self.table("own", provenance.STOCKPILES_TABLE)
        self.assertEqual([row["key"] for row in rows], ["Con base", "Sin base"])
        own, plain = rows
        self.assertEqual(own["base_surface"], sdata.PREVIOUS_DATASET)
        for name in ("plane_level_m", "plane_slope_percent", "plane_azimuth_deg", "plane_tilt_deg"):
            self.assertIsNone(own[name], name)
        self.assertEqual((own["turns"], bool(own["converged"])), (1, True))
        self.assertIsNone(plain["base_surface"])
        self.assertIsNotNone(plain["plane_level_m"])

    def test_the_table_of_candidates_has_one_row_per_candidate_with_its_key_and_state(self) -> None:
        """RF-016-08, RF-016-10: ``des_stc_`` tiene una fila por candidato (los que pasan los filtros, nunca los otros), con su
        clave ``c01``…, su estado ``pending``, su huella en tramos (las celdas del candidato), su área, su volumen y su plano;
        todos sin decisión; sin pedirlos, la tabla está vacía."""
        outcome = self.outcome("version")
        rows = self.table("version", provenance.STOCKPILE_CANDIDATES_TABLE)
        found = outcome.candidates.items
        self.assertEqual(len(rows), len(found))
        self.assertEqual(len(rows), 8, "los ocho de CE-016-01")
        self.assertEqual([row["key"] for row in rows], [f"c{number:02d}" for number in range(1, len(rows) + 1)])
        for row, item in zip(rows, found, strict=True):
            with self.subTest(key=row["key"]):
                self.assertEqual((row["state"], row["reason"], row["decided_by"], row["decided_on"]),
                                 ("pending", None, None, None))
                runs = np.array(json.loads(row["footprint"]), dtype=np.int64).reshape(-1, 3)
                self.assertTrue(np.array_equal(stockpiles.runs_cells(runs, GRID.ncols), item.cells))
                plane = item.footprint.plane
                self.assertEqual((row["cells"], row["area_m2"], row["volume_m3"]),
                                 (item.cells.size, item.footprint.area_m2, item.footprint.volume_m3))
                self.assertEqual((row["x"], row["y"]), item.centre)
                self.assertEqual((row["plane_level_m"], row["plane_slope_percent"], row["plane_azimuth_deg"]),
                                 (float(plane.at(*item.centre)), plane.slope_percent, plane.azimuth_deg))
        self.assertEqual(self.table("project", provenance.STOCKPILE_CANDIDATES_TABLE), rows)
        self.assertEqual(self.table("own", provenance.STOCKPILE_CANDIDATES_TABLE), [])

    # --- Los datos dispersos ----------------------------------------------------------------------------

    def test_the_base_and_the_thickness_of_each_material_are_sparse_grids(self) -> None:
        """RF-016-01, RF-016-09, D-19, P-4: una base y un espesor **por material** (``des_stb_<det>_<mat>`` y
        ``des_stt_<det>_<mat>``) con dato solo en las huellas de sus acopios (NaN fuera), iguales bit a bit a lo calculado; el
        espesor nunca es negativo; el terreno sin acopios y la superficie con que se detectó, solo en las huellas de todos."""
        outcome = self.outcome("version")
        for which in ("version", "project"):
            with self.subTest(scope=which):
                for material in MATERIALS:
                    base = self.sparse(which, provenance.STOCKPILE_BASE_GRID, material)
                    thickness = self.sparse(which, provenance.STOCKPILE_THICKNESS_GRID, material)
                    self.assertTrue(np.array_equal(base, outcome.base_grid(material), equal_nan=True), material)
                    self.assertTrue(np.array_equal(thickness, outcome.thickness_grid(material), equal_nan=True))
                    cells = sum(item.cells.size for item in outcome.stockpiles if item.material == material)
                    self.assertEqual(int(np.isfinite(base).sum()), cells)
                    self.assertEqual(int(np.isfinite(thickness).sum()), cells)
                    self.assertGreaterEqual(float(np.nanmin(thickness)), 0.0)
                ground = self.sparse(which, provenance.STOCKPILE_GROUND_GRID)
                surface = self.sparse(which, provenance.STOCKPILE_SURFACE_GRID)
                self.assertTrue(np.array_equal(ground, outcome.ground_grid(), equal_nan=True))
                self.assertTrue(np.array_equal(surface, outcome.surface_grid(), equal_nan=True))
                self.assertTrue(np.array_equal(np.isfinite(ground), np.isfinite(surface)))
                self.assertTrue(bool(np.all(ground[np.isfinite(ground)] <= surface[np.isfinite(surface)])))

    def test_what_it_keeps_is_small(self) -> None:
        """RNF-016-07: los datos dispersos de una detección de cinco acopios y sus candidatos ocupan, en disco, mucho menos
        que las rejillas enteras (≤ 2 MiB con 9 acopios y 38.000 m² de huella: lo mide entero la T37): cada GeoTIFF disperso,
        una fracción de la rejilla sin comprimir."""
        sizes = {name: (self.root / locator).stat().st_size for name, locator, _role, _hash in self.outputs("version")
                 if locator.endswith(".tif")}
        self.assertEqual(len(sizes), 6)
        whole = GRID.nrows * GRID.ncols * 8
        for name, size in sizes.items():
            self.assertLess(size, whole / 4, name)
        self.assertLess(sum(sizes.values()), 2 * 1024 * 1024)

    # --- Las cifras y el informe -------------------------------------------------------------------------

    def test_the_figures_carry_the_stockpile_and_the_material_in_their_scope(self) -> None:
        """RF-016-02, RF-016-08, plan §5.2.3 y ``figure_scope``: ``des.stk_count`` y ``des.stk_candidates`` de la detección y,
        por cada acopio, su área, su volumen, su espesor máximo y la inclinación de su plano con su ámbito (la detección, la
        clave del acopio y su material); las de dos acopios no se pisan."""
        outcome = self.outcome("version")
        by_key: dict[str, list[tuple[dict[str, str], float]]] = {}
        for key, scope, value in self.figures("version"):
            by_key.setdefault(key, []).append((scope, value))
        entity = provenance.entity_figure_scope("Acopios", "STK-001")
        self.assertEqual(by_key["des.stk_count"], [(entity, 5.0)])
        self.assertEqual(by_key["des.stk_candidates"], [(entity, float(len(outcome.candidates.items)))])
        for item in outcome.stockpiles:
            scope = provenance.stockpile_figure_scope("Acopios", "STK-001", item.key, item.material)
            with self.subTest(key=item.key):
                self.assertIn((scope, item.volume_m3), by_key["des.stk_volume_m3"])
                self.assertIn((scope, item.area_m2), by_key["des.stk_area_m2"])
                self.assertIn((scope, item.thickness_max_m), by_key["des.stk_thickness_max_m"])
        self.assertEqual(len(by_key["des.stk_volume_m3"]), 5)
        self.assertEqual(len({json.dumps(scope, sort_keys=True) for scope, _value in by_key["des.stk_volume_m3"]}), 5)

    def test_the_report_has_the_counts_and_every_notice_with_its_code(self) -> None:
        """RF-016-04, RF-016-05, RF-016-06, RF-016-08: ``des_prp_`` lleva los acopios, su área y su volumen, los candidatos
        (cuántos, y las zonas que descartó el filtro, contadas y sin listar) y **cada aviso con su código y sus valores**, no
        su texto."""
        outcome = self.outcome("version")
        rows = self.query(f'SELECT quantity, value, unit_code, note FROM "{self.locator("version", "prp")}" ORDER BY fid')
        counts = {quantity: value for quantity, value, _unit, _note in rows if value is not None}
        self.assertEqual(counts["stockpiles"], 5.0)
        self.assertEqual(counts["area_m2"], math.fsum(item.area_m2 for item in outcome.stockpiles))
        self.assertEqual(counts["volume_m3"], math.fsum(item.volume_m3 for item in outcome.stockpiles))
        self.assertEqual(counts["candidates"], float(len(outcome.candidates.items)))
        self.assertEqual(counts["candidate_zones"], float(outcome.candidates.zones))
        self.assertEqual(counts["candidates_filtered"], float(outcome.candidates.filtered))
        told = [json.loads(note)["code"] for quantity, _value, _unit, note in rows if quantity in ("warning", "note")]
        self.assertEqual(told, [notice.code for notice in outcome.notices])

    def test_a_detection_without_any_stockpile_is_created_without_bases(self) -> None:
        """RF-016-04: la marca que no da acopio se rechaza y no se registra, y la detección sin ningún acopio se crea igual (con
        sus tablas vacías, el informe con el aviso de la marca y la cifra ``des.stk_count`` en 0) **sin** base, espesor,
        terreno ni superficie: no tiene nada que decir de ellos."""
        self.assertEqual([row[0] for row in self.outputs("empty")], ["des_stk_vacia", "des_stc_vacia", "des_prp_vacia"])
        self.assertEqual(self.table("empty", provenance.STOCKPILES_TABLE), [])
        self.assertEqual(self.table("empty", provenance.STOCKPILE_CANDIDATES_TABLE), [])
        self.assertEqual([(key, value) for key, _scope, value in self.figures("empty")], [("des.stk_count", 0.0)])
        report = self.query(f'SELECT quantity, note FROM "{self.locator("empty", "prp")}" ORDER BY fid')
        self.assertIn("des.stockpile_no_cells",
                      [json.loads(note)["code"] for quantity, note in report if quantity in ("warning", "note")])

    # --- En una transacción -----------------------------------------------------------------------------

    def test_if_anything_fails_nothing_is_left(self) -> None:
        """RF-015-02, RF-015-29: «Crear» es **una** transacción: si falla la escritura de la segunda tabla —cuando ya están
        puestas las rejillas en su sitio y escritos los parámetros— no queda ni la operación, ni los datos, ni los
        parámetros, ni una cifra, ni un fichero (ni temporales), y el cálculo queda descartado; de una versión y del
        proyecto."""
        before = self.state()
        for asked, options in ((tp.request("Fallida", surface=tp.VERSION_SURFACE), {}),
                               (tp.request("Fallida del proyecto"), {"version": None, "masks": None})):
            calculation = last(steps.stockpile_run(self.project, asked, **{
                "masks": self.masks_v1, "version": self.v1.uid, **options}))
            calls: list[str] = []
            real = store.DesignWriter._write_table

            def breaks(writer: Any, conn: Any, table: Any, _real: Any = real, _calls: list[str] = calls) -> None:
                _calls.append(table.family)
                if len(_calls) == 2:
                    raise RuntimeError("falla la segunda tabla")
                _real(writer, conn, table)

            with self.subTest(op_type=calculation.op_type):
                with mock.patch.object(store.DesignWriter, "_write_table", breaks):
                    with self.assertRaises(RuntimeError):
                        calculation.create(decided_by=USER)
                self.assertEqual(len(calls), 2)
                self.assertFalse(calculation.open)
                self.assertEqual(self.state(), before, "ha quedado algo de una creación fallida")
                self.assertEqual([name for name in self.state()["files"] if ".tmp" in name], [])

    def test_a_parameter_that_changed_since_calculating_is_checked_again_and_leaves_nothing(self) -> None:
        """RF-015-02, RF-016-02, D-17: lo que leyó el cálculo se comprueba otra vez al crear (el umbral de la huella de la 011,
        también en una detección del proyecto): si cambió entre «Calcular» y «Crear», el resultado ya no le corresponde
        (``des.input_changed``), antes de escribir nada, y el cálculo queda descartado."""
        key = "res.anthropic_presence_m"
        before = self.state()
        for asked, options in ((tp.request("Cambiada", surface=tp.VERSION_SURFACE), {}),
                               (tp.request("Cambiada del proyecto"), {"version": None, "masks": None})):
            calculation = last(steps.stockpile_run(self.project, asked, **{
                "masks": self.masks_v1, "version": self.v1.uid, **options}))
            with self.subTest(op_type=calculation.op_type):
                with mock.patch.object(steps, "resolve_values", return_value={key: 0.5}):
                    with self.assertRaises(messages.DesignError) as caught:
                        calculation.create()
                self.assertEqual(caught.exception.code, "des.input_changed")
                self.assertFalse(calculation.open)
                self.assertEqual(self.state(), before)

    def test_two_materials_that_give_the_same_dataset_name_are_refused_before_calculating(self) -> None:
        """RF-016-09, D-19: «Estéril» y «estéril» darían el mismo dato de base y de espesor (``des_stb_<det>_esteril``) y se
        pisarían: la preparación lo rechaza nombrando los dos materiales, antes de calcular y sin escribir nada."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            self.prepare(tp.request("Materiales", layer=LAYER_MATERIALS, surface=tp.VERSION_SURFACE))
        error = caught.exception
        self.assertEqual(error.code, "des.stockpile_material_repeated")
        self.assertEqual((error.values["value"], error.values["other"], error.values["layer"]),
                         ("estéril", "Estéril", LAYER_MATERIALS))
        self.assertNotIn("{", error.text)
        self.assertEqual(self.state(), before)

    def test_the_writer_only_omits_what_it_has_not_prepared(self) -> None:
        """RF-016-09: ``DesignWriter.omit`` (una detección sin acopios no tiene base ni espesor) solo admite una familia de las
        salidas del tipo que aún no se ha preparado, y una familia omitida ya no se puede preparar: son errores del
        programa (``ValueError``), no del usuario."""
        with store.design_writer(self.project, provenance.STOCKPILE_DETECT, "Omitida", version=self.v1.uid) as writer:
            with self.assertRaises(ValueError):
                writer.omit(provenance.ENTITY_SURFACE_GRID)  # no es una salida de la detección
            tp.drive(writer.table_steps(provenance.ENTITY_REPORT_TABLE, [("stockpiles", 0.0, "-", None)]))
            with self.assertRaises(ValueError):
                writer.omit(provenance.ENTITY_REPORT_TABLE)  # ya está preparada
            writer.omit(provenance.STOCKPILE_BASE_GRID)
            raster = gis.Raster(self.grid, np.full(self.grid.shape, np.nan), sdata.CRS, sdata.VERTICAL)
            with self.assertRaises(ValueError):
                tp.drive(writer.grid_steps(provenance.STOCKPILE_BASE_GRID, raster))  # omitida
            with self.assertRaises(ValueError):
                writer.commit(None, message="faltan salidas")

    def test_a_calculation_is_created_once(self) -> None:
        """RF-015-02: lo calculado se crea una sola vez: una ``Calculation`` ya creada se rechaza otra vez
        (``RuntimeError``) y no está abierta."""
        calculation = self.calculations["version"]
        self.assertFalse(calculation.open)
        with self.assertRaises(RuntimeError):
            calculation.create()
        with self.assertRaises(RuntimeError):
            list(calculation.create_steps())

    def test_creating_by_steps_is_paced_cancellable_and_leaves_nothing_if_closed(self) -> None:
        """RNF-016-03, RF-016-02, RF-015-29: ``Calculation.create_steps`` escribe por pasos (cada llamada del hilo de Blender,
        ≪ 0,2 s: con un presupuesto mínimo son muchos), el último lleva lo guardado (``Stored``), y cerrarlo a mitad no deja
        nada y descarta el cálculo."""
        calculation = last(steps.stockpile_run(self.project, tp.request("Por pasos", surface=tp.VERSION_SURFACE),
                                               masks=self.masks_v1, version=self.v1.uid))
        count, longest, result = 0, 0.0, None
        work = calculation.create_steps(decided_by=USER, budget_s=1e-9)
        while True:
            started = time.perf_counter()
            try:
                step = next(work)
            except StopIteration:
                break
            longest = max(longest, time.perf_counter() - started)
            count, result = count + 1, step.result
        self.assertGreater(count, 10)
        self.assertLess(longest, 0.2)
        self.assertIsNotNone(result)
        self.assertEqual(result.handle.op_type, provenance.STOCKPILE_DETECT)
        self.assertFalse(calculation.open)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", str(result.handle.uid)),
                         [("done",)])
        before = self.state()
        closed = last(steps.stockpile_run(self.project, tp.request("Cerrada", surface=tp.VERSION_SURFACE),
                                          masks=self.masks_v1, version=self.v1.uid))
        work = closed.create_steps(decided_by=USER, budget_s=1e-9)
        for _ in range(6):
            next(work)
        work.close()
        self.assertFalse(closed.open)
        self.assertEqual(self.state(), before)

# ---------------------------------------------------------------------------------------------
# Las decisiones sobre los candidatos (T13; RF-016-08, RF-016-10, D-23, P-14)
# ---------------------------------------------------------------------------------------------

DECIDED_ON = "2026-11-18"


def compute(job: Any, **options: Any) -> Any:
    """El resultado de ``stockpile_store.detection_compute_steps`` de ``job`` (con las ``decisions`` de ``options``)."""
    return returned(stockpile_store.detection_compute_steps(job, **options))[1]


def decision_of(item: Any, state: str, reason: str) -> Any:
    """La decisión ``state`` con su ``reason`` sobre el candidato ``item`` (un ``CandidateState``) de la rejilla gruesa."""
    return stockpile_store.candidate_decision(item, GRID.ncols, state=state, reason=reason, decided_by=USER,
                                              decided_on=DECIDED_ON)


class DecisionsTextTest(unittest.TestCase):
    """RF-016-08, RF-016-10, P-14: las decisiones son un parámetro de **texto** de la detección (con su historial, decisor y
    fecha en el almacén de parámetros): lo que se escribe se lee igual, sin decisiones es el texto vacío válido y un texto
    que no es de decisiones se rechaza con su código, no con un error del programa."""

    @classmethod
    def setUpClass(cls) -> None:
        run = compute(survey_job(candidates=True, flat=False))
        cls.first = run

    def test_what_is_written_is_read_back_equal_with_its_footprint_in_runs(self) -> None:
        """RF-016-10, P-14: cada decisión lleva la clave del candidato, el estado (convertido o descartado), su motivo, el
        decisor, la fecha y **la huella en tramos** que tenía al decidir (con ella se reconoce el candidato al repetir, sin
        el proyecto); el texto es JSON y se lee tal como se escribió, en el mismo orden."""
        picked = (decision_of(self.first.states[2], "converted", "Es un acopio de mineral"),
                  decision_of(self.first.states[4], "discarded", "Es una escombrera antigua"))
        text = stockpile_store.format_decisions(picked)
        self.assertEqual(json.loads(text)["decisions"][0]["key"], "c03")
        self.assertEqual(stockpile_store.parse_decisions(text), picked)
        self.assertEqual(picked[0].decided_by, USER)
        self.assertEqual(picked[0].decided_on, DECIDED_ON)
        cells = stockpiles.runs_cells(np.array(picked[0].runs, dtype=np.int64).reshape(-1, 3), GRID.ncols)
        self.assertTrue(np.array_equal(cells, self.first.states[2].candidate.cells))
        self.assertEqual(stockpile_store.format_decisions(stockpile_store.parse_decisions(text)), text)

    def test_no_decisions_is_the_empty_text_and_a_bad_text_is_refused_with_its_code(self) -> None:
        """RF-016-10, RF-015-08: ``None``, el texto en blanco y el texto vacío válido no tienen decisiones; un texto que no es
        JSON, una decisión de un estado que no existe, una clave repetida o una huella que no son tramos se rechazan con
        ``des.stockpile_decisions_invalid`` (en los dos idiomas, sin marcadores sin llenar)."""
        for empty in (None, "", "  ", stockpile_store.EMPTY_DECISIONS):
            self.assertEqual(stockpile_store.parse_decisions(empty), ())
        good = json.loads(stockpile_store.format_decisions((decision_of(self.first.states[0], "discarded", "no"),)))
        bad_state = json.loads(json.dumps(good))
        bad_state["decisions"][0]["state"] = "pending"
        twice = json.loads(json.dumps(good))
        twice["decisions"].append(twice["decisions"][0])
        bad_runs = json.loads(json.dumps(good))
        bad_runs["decisions"][0]["runs"] = [[1, 5]]
        for text in ("esto no es JSON", "[1, 2]", json.dumps(bad_state), json.dumps(twice), json.dumps(bad_runs),
                     json.dumps({"decisions": [{"key": "c01"}]})):
            with self.subTest(text=text[:30]):
                with self.assertRaises(messages.DesignError) as caught:
                    stockpile_store.parse_decisions(text)
                self.assertEqual(caught.exception.code, "des.stockpile_decisions_invalid")
                for shown in (caught.exception.text, caught.exception.text_in("en")):
                    self.assertNotIn("{", shown)


class DecisionsComputeTest(unittest.TestCase):
    """RF-016-08, RF-016-10, D-23: ``detection_compute_steps`` con las decisiones de la entidad. Sin ellas cada candidato es
    ``pending`` con su clave ``c01``…; con ellas un candidato cuya huella coincide con la de una decisión (más de la mitad
    del área de cada una) **conserva su clave y su decisión** y los demás se preguntan otra vez con la primera clave libre;
    un candidato **convertido** es un acopio más de la detección (con su clave ``c03``), con el plano, la huella y el
    volumen que tenía como candidato, y deja de ser candidato; uno **descartado** sigue en la lista, con su motivo."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = survey_job(candidates=True, flat=False)
        cls.first = compute(cls.job)
        cls.convert = decision_of(cls.first.states[2], "converted", "Es un acopio de mineral")
        cls.discard = decision_of(cls.first.states[4], "discarded", "Es una escombrera antigua")
        cls.again = compute(cls.job, decisions=(cls.convert, cls.discard))

    def test_without_decisions_every_candidate_is_pending_with_its_key(self) -> None:
        """RF-016-08: la lista de candidatos de una detección sin decisiones: ``c01``, ``c02``… (dos cifras, en el orden de
        lectura de su zona), todos ``pending`` y sin motivo, decisor ni fecha; son los mismos que los de ``outcome.candidates``;
        sin pedir candidatos, ninguno."""
        first = self.first
        self.assertEqual(len(first.states), 8, "los ocho de CE-016-01")
        self.assertEqual([item.key for item in first.states], [f"c{n:02d}" for n in range(1, len(first.states) + 1)])
        self.assertEqual({item.state for item in first.states}, {"pending"})
        self.assertEqual({(item.reason, item.decided_by, item.decided_on) for item in first.states}, {(None, None, None)})
        self.assertEqual([id(item.candidate) for item in first.states], [id(item) for item in first.candidates.items])
        plain = compute(survey_job(flat=False))
        self.assertEqual((plain.states, plain.candidates), ((), None))

    def test_a_decision_keeps_its_key_by_the_footprint_and_the_others_are_asked_again(self) -> None:
        """RF-016-10, D-23: repetir con las decisiones sobre el mismo levantamiento da las mismas claves para todos
        (los de las decisiones, por su huella; los demás, la primera clave libre) y cada decisión en su candidato, con su
        motivo, decisor y fecha; los demás siguen sin decidir."""
        again, first = self.again, self.first
        self.assertEqual([item.key for item in again.states], [item.key for item in first.states])
        for index, item in enumerate(again.states):
            with self.subTest(key=item.key):
                if index == 2:
                    self.assertEqual((item.state, item.reason, item.decided_by, item.decided_on),
                                     ("converted", "Es un acopio de mineral", USER, DECIDED_ON))
                elif index == 4:
                    self.assertEqual((item.state, item.reason, item.decided_by, item.decided_on),
                                     ("discarded", "Es una escombrera antigua", USER, DECIDED_ON))
                else:
                    self.assertEqual((item.state, item.reason), ("pending", None))
                self.assertTrue(np.array_equal(item.candidate.cells, first.states[index].candidate.cells))

    def test_a_converted_candidate_is_one_more_stockpile_with_its_key_and_no_longer_a_candidate(self) -> None:
        """RF-016-08, RF-016-09, RF-016-10: el candidato convertido es un acopio de la detección con la clave ``c03`` y el
        nombre «Candidato c03», sin material ni base propia, con **la misma huella y el mismo volumen** (a ≤ 10⁻⁹) y el mismo
        plano que como candidato; los demás acopios no cambian; ya no está entre los candidatos (que cuentan como tales
        los pendientes y los descartados), la zona cuenta como «con marca» y las cifras lo cuentan como acopio."""
        again, first = self.again, self.first
        before = first.stockpiles
        self.assertEqual([item.key for item in again.stockpiles], [*(item.key for item in before), "c03"])
        for old, new in zip(before, again.stockpiles, strict=False):
            self.assertTrue(np.array_equal(old.cells, new.cells))
            self.assertEqual(old.volume_m3, new.volume_m3)
        mine = again.stockpiles[-1]
        candidate = first.states[2].candidate
        self.assertEqual((mine.key, mine.name, mine.material, mine.base_surface), ("c03", "Candidato c03", None, None))
        self.assertTrue(np.array_equal(mine.cells, candidate.cells))
        self.assertAlmostEqual(mine.volume_m3 / candidate.footprint.volume_m3, 1.0, delta=1e-9)
        self.assertAlmostEqual(mine.plane.slope_percent, candidate.footprint.plane.slope_percent, delta=1e-9)
        self.assertEqual(len(again.candidates.items), len(first.candidates.items) - 1)
        self.assertEqual([id(item) for item in again.candidates.items],
                         [id(item.candidate) for item in again.states if item.state != "converted"])
        self.assertEqual(again.candidates.on_marks, first.candidates.on_marks + 1)
        self.assertEqual(again.candidates.zones, first.candidates.zones)
        figures = {(figure.key, tuple(sorted(figure.scope.items()))): figure.value for figure in again.figures}
        entity = tuple(sorted(provenance.entity_figure_scope("Acopios", "STK-001").items()))
        self.assertEqual(figures[("des.stk_count", entity)], float(len(first.stockpiles) + 1))
        self.assertEqual(figures[("des.stk_candidates", entity)], float(len(first.candidates.items) - 1))

    def test_the_report_counts_what_the_filter_discarded_and_what_was_decided(self) -> None:
        """RF-016-08, RF-016-10: el informe de la detección cuenta, sin listarlos, los candidatos, las zonas, las de marca, las
        que descartó el filtro (las pequeñas **y** las grandes) y las rechazadas, y cuántos candidatos se convirtieron y se
        descartaron (``des_prp_``)."""
        found = self.again
        wide = dataclasses.replace(found, candidates=dataclasses.replace(found.candidates, too_large=3, rejected=2))
        rows = {quantity: value for quantity, value, _unit, _note in stockpile_store.detection_report_rows(wide)
                if value is not None}
        self.assertEqual(rows["candidates_filtered"], float(wide.candidates.too_small + 3))
        self.assertEqual((rows["candidates_rejected"], rows["candidates_on_marks"], rows["candidate_zones"]),
                         (2.0, float(found.candidates.on_marks), float(found.candidates.zones)))
        self.assertEqual((rows["candidates"], rows["candidates_converted"], rows["candidates_discarded"]),
                         (float(len(found.candidates.items)), 1.0, 1.0))

    def test_a_decision_that_matches_nothing_keeps_its_key_reserved(self) -> None:
        """RF-016-10, D-23: la decisión cuya huella ya no coincide con ningún candidato no se aplica (se pregunta otra vez por
        todos) y **su clave no se reutiliza** para otro candidato: las claves nuevas saltan la ``c02``."""
        far = dataclasses.replace(decision_of(self.first.states[1], "discarded", "Ya no está"),
                                  runs=((0, 0, 3), (1, 0, 3), (2, 0, 3)))
        found = compute(self.job, decisions=(far,))
        keys = [item.key for item in found.states]
        self.assertNotIn("c02", keys)
        self.assertEqual(keys[:2], ["c01", "c03"])
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual({item.state for item in found.states}, {"pending"})
        self.assertEqual(len(found.stockpiles), len(self.first.stockpiles))

    def test_a_converted_candidate_cannot_take_the_key_of_a_mark(self) -> None:
        """RF-016-02, RF-016-10: si una marca de la capa se llama como el candidato convertido (``c03``), la clave de un
        acopio sería ambigua: se rechaza con ``des.stockpile_candidate_key_taken`` nombrando la clave, no con un error del
        programa."""
        marks = list(self.job.marks)
        marks[0] = stockpiles.StockpileMark("c03", marks[0].cells, margin_m=marks[0].margin_m, material=marks[0].material,
                                            base=marks[0].base)
        job = dataclasses.replace(self.job, marks=tuple(marks))
        with self.assertRaises(messages.DesignError) as caught:
            compute(job, decisions=(self.convert,))
        self.assertEqual(caught.exception.code, "des.stockpile_candidate_key_taken")
        self.assertIn("c03", caught.exception.text)

    def test_the_decisions_do_not_modify_the_job_or_the_first_outcome(self) -> None:
        """RF-015-29, principio 7: calcular con decisiones no toca el trabajo (su superficie y sus marcas) ni el resultado
        anterior."""
        self.assertEqual(len(self.job.marks), 5)
        self.assertEqual(len(self.first.stockpiles), 5)
        self.assertTrue(np.array_equal(self.job.surface, sdata.survey(GRID), equal_nan=True))


# ---------------------------------------------------------------------------------------------
# Recalcular y consultar (T14; RF-016-10, RF-015-02, RF-015-04, RF-015-16, CE-016-01: casos (d) y (e))
# ---------------------------------------------------------------------------------------------

CODE = "STK-001"
THRESHOLD_KEY = "res.anthropic_presence_m"
"""El umbral de la huella de la 011: una entrada de la operación entera (CE-016-01)."""


def finish(work: Iterator[Any]) -> Any:
    """Los pasos de ``work`` hasta el final: lo que lleva el último (lo guardado)."""
    return last(work)


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de la detección: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request)
    finish(work)
    return handle


class RecomputeCase(tp.PrepareCase):
    """Lo de ``PrepareCase`` con los dos tipos de la detección registrados con su función real de recalcular (la de ``bl``) y
    las cifras, y las ayudas de las historias de recalcular ``STK-001`` en V01 y en el proyecto."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        """Los tipos de la detección con lo que registra ``bl``; las clases que reproducen añaden su función."""
        return tuple(provenance.OPERATION_TYPES_BY_NAME[op_type].definition(recompute_function)
                     for op_type in provenance.STOCKPILE_DETECT_TYPES)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(*cls.definitions(), *provenance.STOCKPILE_FIGURES))

    @classmethod
    def create(cls, asked: Any, **options: Any) -> tuple[Any, Any]:
        """«Calcula» y «Crea» ``asked`` (V01 y sus máscaras por defecto; con ``version=None``, en el proyecto): la
        ``Calculation`` y lo guardado."""
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        calculation = last(steps.stockpile_run(cls.project, asked, **options))
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def current(self, *, version: bool = True) -> str:
        """El uid de la operación vigente de ``STK-001`` en V01 o, sin ``version``, en el proyecto (el registro de entidades)."""
        registry = (entities_module.registry(self.project, self.v1.uid) if version
                    else entities_module.project_registry(self.project))
        entry = registry.get(CODE)
        assert entry is not None and entry.operation_uid is not None
        return str(entry.operation_uid)

    def request_for(self, uid: str, *, version: bool = True) -> Any:
        """Lo que recibe ``bl`` para recalcular la operación ``uid``: su tipo, sus ajustes y su versión (``None``: de proyecto)."""
        ((op_type, settings),) = self.query("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, op_type, json.loads(settings), (), (),
                                              version=self.v1.uid if version else None)

    def hashes_of(self, uid: str) -> dict[str, str]:
        """El hash que anotó la operación ``uid`` de cada dato que escribió, por su nombre."""
        return dict(self.query(
            "SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out'", uid))

    def figures_of(self, uid: str) -> list[tuple[str, str, float]]:
        return self.query("SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid)

    def parameter_rows(self) -> list[tuple[Any, ...]]:
        """Los parámetros de la entidad, con su historial (los del proyecto y los de V01)."""
        return self.query("SELECT key, scope, value, rev FROM gb_parameter WHERE key LIKE 'des.stockpile.stk_001.%' "
                          "ORDER BY key, scope")

    def table(self, family: str, *, version: bool = True) -> list[dict[str, Any]]:
        return list(stockpile_store.read_detection_table(self.project, family, "Acopios",
                                                         version_uid=self.v1.uid if version else ""))

    def change(self, key: str, value: Any, *, version: bool = True) -> None:
        """Cambia el parámetro ``key`` (de V01 o, sin ``version``, del proyecto) un minuto después."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, key, value=value, source="prueba de recalcular (T14)", source_kind="person", decided_by=USER,
                reason="Se cambia el parámetro de la detección", version=self.v1.uid if version else None)

    def change_threshold(self, value: float) -> None:
        """Cambia el umbral de la huella del proyecto (un minuto después)."""
        self.change(THRESHOLD_KEY, value, version=False)

    def temporaries(self) -> list[str]:
        return sorted(name for name in self.state()["files"] if ".tmp" in name)


class RecomputeTest(RecomputeCase):
    """RF-016-10, RF-015-02, RF-015-04, RF-015-16, CE-016-01 (casos (d) y (e)): la detección de V01 (las cinco marcas y los
    candidatos, sobre el levantamiento de V01) y la del proyecto (lo mismo sobre el del proyecto) recalculadas como operación
    nueva, consultables por superficie y obsoletas con su causa al cambiar el umbral. **En orden** (``test_a`` a ``test_d``):
    cada una parte de lo que dejó la anterior."""

    version_calculation: ClassVar[Any]
    project_calculation: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.version_calculation, _ = cls.create(tp.request(surface=tp.VERSION_SURFACE, candidates=True))
        cls.project_calculation, _ = cls.create(tp.request(candidates=True), version=None, masks=None)

    def test_a_the_detections_on_a_surface_are_the_current_ones_made_on_it(self) -> None:
        """RF-016-10, RF-015-16 (lo que leen la T15 y la T30): ``detections_on(version, surface)`` da la detección **al día**
        hecha sobre esa superficie con su código, su nombre, su ámbito, la operación que la escribió y sus datos —la tabla de
        acopios, la de candidatos, el informe, y por material (en el orden de los acopios) su base y su espesor dispersos,
        el terreno sin acopios y la superficie con que se detectó— con su nombre, su ubicación y su papel; la de V01 sobre una
        superficie de V01 y la del proyecto sobre una del proyecto (que ve también V01); un proyecto no ve lo de una versión; y
        ninguna sobre otra superficie."""
        version_op, project_op = self.current(), self.current(version=False)
        found = stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE)
        self.assertEqual([(item.code, item.name, item.scope, item.version, item.surface, item.operation) for item in found],
                         [(CODE, "Acopios", stockpile_store.VERSION, "V01", tp.VERSION_SURFACE, version_op)])
        mine = found[0]
        self.assertEqual(mine.version_uid, self.v1.uid)
        for data, family, role in ((mine.stockpiles, "stk", "stockpiles"), (mine.candidates, "stc", "stockpile_candidates"),
                                   (mine.report, "prp", provenance.ENTITY_REPORT_ROLE),
                                   (mine.ground, "stg", "stockpile_ground"), (mine.detected, "stp", "stockpile_surface")):
            self.assertEqual((data.name, data.locator, data.role),
                             (provenance.dataset_name(family, "Acopios"),
                              provenance.dataset_locator(family, "Acopios", "V01"), role), family)
        self.assertEqual([(item.material, item.base.name, item.thickness.name, item.base.role, item.thickness.role)
                          for item in mine.materials],
                         [(material, provenance.dataset_name("stb", f"Acopios {material}"),
                           provenance.dataset_name("stt", f"Acopios {material}"), "stockpile_base", "stockpile_thickness")
                          for material in ("mineral", "estéril")])
        self.assertEqual(mine.materials[0].base.locator, provenance.dataset_locator("stb", "Acopios mineral", "V01"))
        for item, wanted in zip(mine.materials, ("mineral", "estéril"), strict=True):  # lo que leerá la 011: por su papel
            self.assertEqual(self.query("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND item_uid = ?",
                                        version_op, item.base.uid), [("stockpile_base",)], wanted)
            read = tp.drive(surfaces.read_surface_steps(self.project, item.base.name, version_uid=mine.version_uid)).values
            np.testing.assert_array_equal(read, self.version_calculation.outcome.base_grid(item.material))
        project_found = stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET)
        self.assertEqual([(item.scope, item.version, item.version_uid, item.operation, item.stockpiles.locator)
                          for item in project_found],
                         [(stockpile_store.PROJECT, None, "", project_op, provenance.dataset_locator("stk", "Acopios", None))])
        self.assertEqual(stockpile_store.detections_on(self.project, None, sdata.SURVEY_DATASET), project_found,
                         "sin versión, lo del proyecto")
        self.assertEqual(stockpile_store.detections_on(self.project, None, tp.VERSION_SURFACE), (),
                         "un proyecto no ve lo de una versión")
        self.assertEqual(stockpile_store.detections_on(self.project, self.v1.uid, sdata.PREVIOUS_DATASET), ())
        self.assertEqual(stockpile_store.detections_on(self.project, self.v2.uid, tp.VERSION_SURFACE), (),
                         "otra versión no ve lo de V01")
        self.assertEqual([item.scope for item in stockpile_store.detections_on(self.project, "V01", sdata.SURVEY_DATASET)],
                         [stockpile_store.PROJECT], "la versión, también por su código")
        with self.assertRaises(tp.versions_model.VersionError) as unknown:
            stockpile_store.detections_on(self.project, "V99", tp.VERSION_SURFACE)
        self.assertEqual(unknown.exception.code, "core.version_unknown")

    def test_b_recomputing_a_version_detection_repeats_it_as_a_new_operation_with_the_same_identity(self) -> None:
        """RF-016-10, RF-015-02, RF-015-04, RF-008-26: recalcular la detección de V01 sin que nada cambie da una operación
        **nueva** (``des.stockpile_detect``) que sustituye a la anterior —queda como historia— con los mismos ajustes, entradas,
        cifras y datos (el mismo hash de cada uno, con el mismo nombre); no escribe los parámetros de la entidad (ya están); la
        entidad sigue siendo ``STK-001`` y está al día con la operación nueva, y la consulta la da; no deja temporales."""
        old = self.current()
        hashes, figures = self.hashes_of(old), self.figures_of(old)
        inputs = self.query("SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in' "
                            "ORDER BY fid", old)
        settings = self.query("SELECT settings FROM gb_operation WHERE uid = ?", old)
        rows = self.parameter_rows()
        before = self.table("stk")
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(old))
        stored = finish(work)
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query("SELECT op_type, scope, status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [(provenance.STOCKPILE_DETECT, "version", "done", old)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old), [(handle.uid,)])
        self.assertEqual(self.hashes_of(handle.uid), hashes)
        self.assertEqual(self.figures_of(handle.uid), figures)
        self.assertEqual(self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid), settings)
        self.assertEqual(self.query("SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? AND "
                                    "direction = 'in' ORDER BY fid", handle.uid), inputs)
        self.assertEqual(self.parameter_rows(), rows, "no escribe los parámetros de la entidad")
        self.assertEqual(self.table("stk"), before)
        self.assertEqual(self.current(), handle.uid)
        self.assertEqual(self.stale_causes(handle.uid), set())
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual(self.temporaries(), [])
        (mine,) = stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE)
        self.assertEqual(mine.operation, handle.uid)

    def test_c_recomputing_a_project_detection_repeats_it_in_the_project(self) -> None:
        """RF-016-10, RF-015-02, D-15: lo mismo con la detección **del proyecto** (``des.stockpile_detect_project``, sin
        versión: ``RecomputeRequest.version`` ``None``): operación nueva de proyecto que sustituye a la anterior, los mismos
        datos y cifras, ninguna fila de parámetros escrita, y la entidad del proyecto al día con la operación nueva."""
        old = self.current(version=False)
        hashes, figures = self.hashes_of(old), self.figures_of(old)
        rows = self.parameter_rows()
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(old, version=False))
        finish(work)
        self.assertEqual(self.query("SELECT op_type, scope, status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [(provenance.STOCKPILE_DETECT_PROJECT, "project", "done", old)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old), [(handle.uid,)])
        self.assertEqual(self.hashes_of(handle.uid), hashes)
        self.assertEqual(self.figures_of(handle.uid), figures)
        self.assertEqual(self.parameter_rows(), rows)
        self.assertEqual(self.current(version=False), handle.uid)
        self.assertEqual(self.stale_causes(handle.uid), set())
        self.assertEqual(self.temporaries(), [])
        self.assertEqual([item.operation for item in
                          stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET)], [handle.uid])

    def test_d_changing_the_threshold_makes_the_whole_operation_stale_and_recomputing_gives_the_new_footprints(self) -> None:
        """CE-016-01 (la última frase), RF-016-10, RF-015-16: cambiar el umbral de la huella (``res.anthropic_presence_m``, de
        la 011) deja obsoleta **la operación entera**, la de V01 y la del proyecto, con su causa (``parameter_changed`` de esa
        clave); ya no son «al día» (``detections_on`` no las da) y «Recalcular lo obsoleto» repite las dos —cada una sustituye a
        la suya— con el umbral nuevo (las huellas de las mismas cinco marcas; las de las cuatro sin base propia, las de la
        detección a 0,6 m calculada aparte, y alguna cambia) y las deja al día."""
        wanted = stockpiles.detect_stockpiles(dataclasses.replace(
            survey_job(flat=False), params=params_of(threshold_m=0.6)))
        expected = {item.key: int(item.cells.size) for item in wanted.stockpiles if item.key != "Acopio 5"}
        old = {"version": self.current(), "project": self.current(version=False)}
        before = {"version": {row["key"]: row["cells"] for row in self.table("stk")},
                  "project": {row["key"]: row["cells"] for row in self.table("stk", version=False)}}
        for uid in old.values():
            self.assertEqual(self.stale_causes(uid), set())
        self.change_threshold(0.6)
        for uid in old.values():
            self.assertEqual(self.stale_causes(uid), {("parameter_changed", THRESHOLD_KEY)})
        self.assertEqual(stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE), ())
        self.assertEqual(stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET), ())
        self.assertEqual(sorted(self.recompute_plan()),
                         [(provenance.STOCKPILE_DETECT,), (provenance.STOCKPILE_DETECT_PROJECT,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 2)
        new = {"version": self.current(), "project": self.current(version=False)}
        for scope in old:
            self.assertNotEqual(new[scope], old[scope])
            self.assertEqual(self.stale_causes(new[scope]), set())
            self.assertEqual(self.query("SELECT supersedes_uid FROM gb_operation WHERE uid = ?", new[scope]),
                             [(old[scope],)])
        after = {"version": {row["key"]: row["cells"] for row in self.table("stk")},
                 "project": {row["key"]: row["cells"] for row in self.table("stk", version=False)}}
        for scope in old:
            with self.subTest(scope=scope):
                self.assertEqual(list(after[scope]), list(before[scope]), "la misma identidad: las mismas marcas")
                self.assertEqual({key: after[scope][key] for key in expected}, expected)
                self.assertNotEqual(after[scope], before[scope], "el umbral cambió la huella de alguna")
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual([item.operation for item in
                          stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE)], [new["version"]])
        self.assertEqual([item.operation for item in
                          stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET)], [new["project"]])

    def test_e_recomputing_uses_the_parameters_of_the_entity_in_its_own_scope(self) -> None:
        """RF-016-10, RF-015-01, RF-015-02, RF-009-24 (P-3 de la 015): una entidad se define por sus parámetros **de su
        ámbito**, no por los que leyó la operación anterior ni por los del otro ámbito: cambiado el margen de ``STK-001`` en
        V01 (4 m), la detección de V01 queda obsoleta por ese parámetro y recalcularla lo usa (la columna de margen de cada
        acopio, salvo el Acopio 3, que lleva el suyo en la capa) y la del proyecto, que tiene su fila de 10 m, ni se entera."""
        key = design_params.entity_key(CODE, "margin_m")
        project_old, version_old = self.current(version=False), self.current()
        self.assertEqual(self.stale_causes(version_old), set())
        self.change(key, 4.0)
        self.assertEqual(self.stale_causes(version_old), {("parameter_changed", key)})
        self.assertEqual(self.stale_causes(project_old), set(), "el parámetro de V01 no es el del proyecto")
        self.clock.advance(minutes=1)
        recompute_function(self.request_for(version_old))
        self.assertEqual({row["key"]: row["margin_m"] for row in self.table("stk")},
                         {"Acopio 1": 4.0, "Acopio 2": 4.0, "Acopio 3": 6.0, "Acopio 4": 4.0, "Acopio 5": 4.0})
        self.assertEqual({row["margin_m"] for row in self.table("stk", version=False) if row["key"] != "Acopio 3"}, {10.0})
        self.assertEqual(self.current(version=False), project_old)
        self.assertEqual(self.stale_causes(project_old), set())

    def test_f_a_project_detection_with_candidates_is_not_reproduced(self) -> None:
        """RF-009-11, RF-016-10, D-15: la detección del proyecto con candidatos saca su perímetro de la restricción del
        proyecto, que ninguna revisión congela, así que **no se reproduce** (``ValueError`` al avanzar, antes de leer nada de lo
        congelado); y lo que no es una petición de ese tipo es un error del programa al llamar."""
        reproduce_mod = import_geoblender("core.versions.reproduce")
        design_reproduce = import_geoblender("design.reproduce")
        uid = self.current(version=False)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        found = entity_store.entity_parameters(self.project, CODE)
        params = {design_params.entity_key(CODE, name): (value, "") for name, value in found.items()}
        params[THRESHOLD_KEY] = (0.3, "m")
        self.assertIs(found["candidates"], True)
        request = reproduce_mod.ReproduceRequest(provenance.STOCKPILE_DETECT_PROJECT, json.loads(settings), (), params,
                                                 self.root, self.project.record)
        with self.assertRaises(ValueError) as caught:
            next(design_reproduce.reproduce_stockpile_detect(request))
        self.assertIn("«Acopios»", str(caught.exception))
        with self.assertRaises(ValueError):
            design_reproduce.reproduce_stockpile_detect(dataclasses.replace(request, op_type="des.quarry"))


if __name__ == "__main__":
    unittest.main()
