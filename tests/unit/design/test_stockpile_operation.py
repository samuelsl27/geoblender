# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular» la detección de acopios y su resumen (spec 016, T12; HU-016-1; RF-016-04, RF-016-05, RF-016-06, RF-016-07,
RF-016-08; RF-015-03, RF-015-13, RF-015-29; RNF-016-03, RNF-016-05; plan 016 §5.3.2 y §5.4 A0): casos (a) de
``test_stockpile_operation`` (crear, repetir y consultar —(b), (c), (d) y (e)— son de la T13 y la T14).

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
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from collections.abc import Generator, Iterator
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design import test_stockpile_prepare as tp
from tests.unit.design.test_stockpile_candidates import cparams
from tests.unit.design.test_stockpile_footprint import params_of

gis_messages = import_geoblender("gis.messages")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
steps = import_geoblender("design.steps")
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

    def test_creating_a_detection_is_the_next_task_and_does_not_close_the_calculation(self) -> None:
        """RF-015-03: crear la detección (T13) aún no está: ``Calculation.create`` lo dice y deja el cálculo abierto y
        el proyecto como estaba."""
        before = self.state()
        calculation = self.calculate(self.mixed())
        with self.assertRaises(NotImplementedError) as caught:
            calculation.create()
        self.assertIn("T13", str(caught.exception))
        self.assertTrue(calculation.open)
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
