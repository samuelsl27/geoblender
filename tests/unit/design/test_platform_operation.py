# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular» una plataforma y su resumen (spec 015, T12; HU-015-3; RF-015-03, RF-015-13, RF-015-29;
plan 015 §5.3.2 y §5.4; E1 y E2 de la spec): caso (a) de ``test_platform_operation`` (el (b) lo
añade la T13 y los (c), (d) y (e), la T14).

Sobre la cantera sintética de la 014 con las capas de plataformas (``tests.support.entity_fixtures``)
y su rejilla gruesa de 2 m:

- **El cálculo compartido** (``entity_store.platform_compute_steps``): huella → aplicar → borde →
  perfil → ``platform_outcome``, por pasos y sin proyecto dentro, es lo que hacen a mano las
  funciones de las T06 a T09; lo comparten «Calcular», el recálculo y la reproducción.
- **«Calcular» no escribe** (RF-015-03, RF-015-29): ``steps.platform_run`` deja la superficie en un
  temporal y el resumen, y **nada en el proyecto** (ni la base de datos, ni operaciones, ni datos, ni
  parámetros); cerrarlo a mitad, descartar la cuenta o un fallo después del temporal no dejan nada;
  los rechazos salen al avanzar. Crearla es de la T13: aquí ``create()`` lo dice.
- **El resumen** (RF-015-03, RF-015-13): las cifras, los avisos (el salto creado, la magnitud, lo que
  llega a celdas sin dato fuera de la huella, el área que no mueve por la restricción de otra entidad
  con esa entidad, o con el nombre de la restricción) y lo que quedará obsoleto al crearla (si
  protege: las máscaras y lo que las usó; si inserta: la sucesora y las que le siguen; si sustituye
  una operación: lo que dependía de ella), con el singular («en 1 grupo»).
"""

from __future__ import annotations

import dataclasses
import re
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import freeze_rows
from tests.unit.design import test_edges_operation as edges_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
builtin = import_geoblender("core.content.builtin")
datasets = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
operations = import_geoblender("core.provenance.operations")
versions_model = import_geoblender("core.versions.model")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_report = import_geoblender("design.report")
entities_module = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
geotiff_reader = import_geoblender("gis.geotiff.reader")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
platform = import_geoblender("design.platform")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
res_provenance = import_geoblender("reserves.provenance")
steps = import_geoblender("design.steps")
zones_mod = import_geoblender("gis.masks.zones")
combine = import_geoblender("gis.masks.combine")

LOADING, TOWER, WORKSHOP = prep.LOADING, prep.TOWER, prep.WORKSHOP
START, GRID = prep.START, prep.GRID
CELL_M2 = 4.0
"""El área de una celda de la rejilla gruesa (2 × 2 m)."""
EDGE_HOLE_DATASET = "gis_dtm_borde"
"""El terreno de la cantera con un hueco sin dato **fuera** de la huella de la «Plataforma de carga»,
al norte de ella: las celdas de centro x de 201 a 209 m e y de 293 a 297 m (locales), donde su borde
corta."""
EDGE_HOLE_BOX = (200.0, 292.0, 210.0, 298.0)
EDGE_HOLE_CELLS = 15


def finish(work: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    last = None
    for last in work:
        pass
    return last.result


def edge_hole_raster() -> Any:
    """El terreno de la cantera con el hueco de :data:`EDGE_HOLE_BOX` sin dato."""
    x, y = qfx.local_centers(GRID)
    left, bottom, right, top = EDGE_HOLE_BOX
    hole = (x > left) & (x < right) & (y > bottom) & (y < top)
    return gis.Raster(GRID, np.where(hole, np.nan, qfx.terrain(GRID)), efx.CRS, efx.VERTICAL)


def codes(found: Any) -> list[str]:
    """Los códigos de los avisos y notas de un resumen, en su orden."""
    return [notice.code for notice in found.notices]


def only(found: Any, code: str) -> Any:
    """El aviso ``code`` del resumen ``found`` (uno solo)."""
    matching = [notice for notice in found.notices if notice.code == code]
    assert len(matching) == 1, f"{code}: {codes(found)}"
    return matching[0]


class OperationCase(prep.PrepareCase):
    """Lo de ``PrepareCase`` más un terreno con un hueco fuera de la huella de la «Plataforma de carga»
    y ``calculate``, que calcula en V01 con sus máscaras y deja la cuenta descartada al acabar."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        res_fixtures.write_grids(cls.project, [("borde", edge_hole_raster())],
                                 message="Terreno de la prueba con un hueco junto a la plataforma")
        cls.clock.advance(minutes=1)

    def run_steps(self, asked: Any, **options: Any) -> Iterator[Any]:
        options.setdefault("masks", self.masks_v1)
        options.setdefault("version", self.v1.uid)
        return steps.platform_run(self.project, asked, **options)

    def calculate(self, asked: Any, **options: Any) -> Any:
        """«Calcular» ``asked`` hasta el final: la ``Calculation``, que se descarta al acabar."""
        calculation = finish(self.run_steps(asked, **options))
        self.addCleanup(calculation.discard)
        return calculation

    def temporaries(self) -> list[str]:
        return sorted(name for name in self.state()["files"] if ".tmp-" in name)


# ---------------------------------------------------------------------------------------------
# El cálculo compartido
# ---------------------------------------------------------------------------------------------


class ComputeStepsTest(OperationCase):
    """RF-015-29, RF-015-03 (el dominio): ``platform_compute_steps`` es la huella, aplicar, el borde, el
    perfil y las cifras de las T06 a T09, por pasos y sin proyecto dentro."""

    def test_a_it_is_what_the_pieces_do_by_hand_and_writes_nothing(self) -> None:
        """RF-015-03, RF-015-29: por pasos (con un presupuesto mínimo: muchos), el resultado es
        el de ``apply_platform``, ``platform_edge`` y ``platform_outcome`` seguidos (superficie,
        cifras y avisos), con o sin la huella ya calculada, y nada se escribe."""
        prepared = self.units(prep.request())
        applied = platform.apply_platform(prepared.job, prepared.footprint)
        edge = platform.platform_edge(prepared.job, prepared.footprint, applied, prepared.common)
        direct = platform.platform_outcome(prepared.job, prepared.footprint, applied, edge,
                                           prepared.common)
        before = self.state()
        work = entity_store.platform_compute_steps(prepared.job, prepared.common,
                                                   footprint=prepared.footprint, budget_s=1e-9)
        shown: list[Any] = []
        while True:
            try:
                shown.append(next(work))
            except StopIteration as done:
                stepped = done.value
                break
        self.assertEqual(self.state(), before)
        self.assertGreater(len(shown), 3, "un presupuesto mínimo da muchos pasos")
        self.assertTrue({"platform_apply", "platform_edge"} <= {step.phase for step in shown})
        np.testing.assert_array_equal(stepped.result, direct.result)
        self.assertEqual(stepped.figures, direct.figures)
        self.assertEqual([n.code for n in stepped.notices], [n.code for n in direct.notices])
        with mock.patch.object(entity_store, "platform_footprint",
                               side_effect=AssertionError("la huella ya estaba calculada")):
            _last(entity_store.platform_compute_steps(prepared.job, prepared.common,
                                                      footprint=prepared.footprint))
        again = _last(entity_store.platform_compute_steps(prepared.job, prepared.common))
        np.testing.assert_array_equal(again.result, direct.result)
        np.testing.assert_array_equal(again.footprint.levels, prepared.footprint.levels)

    def test_a_the_outcome_names_itself_for_the_operation(self) -> None:
        """RF-015-02 (el mensaje de la operación): el resultado dice la plataforma, su código y sus
        cifras mayores en español; es lo que ``Calculation.message`` da a ``commit``."""
        prepared = self.units(prep.request())
        outcome = _last(entity_store.platform_compute_steps(
            prepared.job, prepared.common, footprint=prepared.footprint))
        self.assertIn(f"«{LOADING}»", outcome.message)
        self.assertIn("PLT-001", outcome.message)
        self.assertIn("4000 m²", outcome.message)


def _last(work: Iterator[Any]) -> Any:
    """Lo que **devuelve** unos pasos (``yield from``)."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


# ---------------------------------------------------------------------------------------------
# «Calcular» no escribe
# ---------------------------------------------------------------------------------------------


class CalculateTest(OperationCase):
    """RF-015-03 y RF-015-29 con proyecto: «Calcular» deja el temporal y el resumen, y nada más."""

    def test_a_calculating_writes_nothing_and_leaves_the_surface_in_a_temporary(self) -> None:
        """RF-015-03, RF-015-29: tras «Calcular», ni el contador de cambios de la base (ninguna
        transacción de escritura), ni las operaciones, los datos o los parámetros se han movido; solo
        hay un fichero más, el temporal de la superficie (``des_psf_…``) con su hash preparado. Lo
        escrito es la partida fuera de lo que mueve la plataforma y su resultado dentro, y en «en
        corte» ninguna celda sube: el corte de las celdas es el de la cuenta."""
        before = self.state()
        calculation = self.calculate(prep.request())
        after = self.state()
        for key in ("counter", "operations", "datasets", "parameters"):
            self.assertEqual(after[key], before[key], key)
        stem = provenance.dataset_locator("psf", LOADING, "V01").rsplit("/", 1)[-1]
        (temporary,) = sorted(set(after["files"]) - set(before["files"]))
        self.assertRegex(temporary, rf"^{re.escape(stem)}\.tmp-[0-9a-f]+$")
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         ("des.platform", LOADING, "V01"))
        self.assertTrue(calculation.open)
        self.assertEqual([spec.name for spec in calculation.specs],
                         [provenance.dataset_name("psf", LOADING)])
        self.assertEqual(calculation.entity.code, "PLT-001")
        outcome = calculation.outcome
        self.assertIsInstance(outcome, platform.PlatformOutcome)
        self.assertEqual(calculation.message, outcome.message)
        written = geotiff_reader.read_geotiff(self.root / "rasters" / temporary).values
        start = qfx.terrain(GRID)
        expected = start.copy()
        expected[outcome.footprint.window] = outcome.result
        np.testing.assert_array_equal(written, expected)
        self.assertTrue((written <= start).all(), "«en corte» no sube ninguna celda")
        self.assertAlmostEqual(float(np.sum(start - written)) * CELL_M2, outcome.total_cut_m3,
                               delta=1e-9 * outcome.total_cut_m3)
        self.assertEqual({figure.key: figure.value for figure in calculation.figures
                          if figure.key == "des.plat_area_m2"}, {"des.plat_area_m2": 4000.0})
        self.assertEqual(self.units(prep.request()).start.inputs, calculation.entity.start.inputs)

    def test_a_the_steps_advance_with_progress_and_end_with_the_calculation(self) -> None:
        """RF-015-29: «Calcular» da pasos de ``Progress`` (fase, avance y texto) y el último lleva la
        ``Calculation``; con un presupuesto mínimo, muchos; cada fase de lo pesado tiene el suyo."""
        found = list(self.run_steps(prep.request(), budget_s=1e-9))
        self.addCleanup(found[-1].result.discard)
        phases = [step.phase for step in found]
        for phase in ("prepare", "platform_apply", "platform_edge", "store", "calculated"):
            self.assertIn(phase, phases)
        self.assertEqual(phases[-1], "calculated")
        self.assertTrue(all(step.result is None for step in found[:-1]))
        self.assertGreater(len(found), 12)
        self.assertTrue(all(step.message for step in found))

    def test_a_closing_the_steps_midway_leaves_nothing(self) -> None:
        """RF-015-29: cerrar «Calcular» (Esc, desactivar Geoblender) con la superficie ya en su
        temporal borra el temporal y no deja nada: el estado del proyecto es el de antes."""
        before = self.state()
        work = self.run_steps(prep.request(), budget_s=1e-9)
        for step in work:
            if step.phase == "store" and self.temporaries():
                break
        else:
            self.fail("no llegó a escribir el temporal")
        self.assertEqual(len(self.temporaries()), 1)
        work.close()
        self.assertEqual(self.state(), before)

    def test_a_closing_at_the_first_step_leaves_nothing(self) -> None:
        """RF-015-29: cerrar al empezar tampoco deja nada."""
        before = self.state()
        work = self.run_steps(prep.request(), budget_s=1e-9)
        next(work)
        work.close()
        self.assertEqual(self.state(), before)

    def test_a_a_failure_after_the_temporary_leaves_nothing(self) -> None:
        """RF-015-29: si algo falla después de escribir el temporal (aquí, al armar el resumen), el
        error sigue y no queda ni el temporal ni nada en el proyecto."""
        before = self.state()
        with mock.patch.object(entity_store, "platform_obsolete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                finish(self.run_steps(prep.request(), budget_s=1e-9))
        self.assertEqual(self.state(), before)

    def test_a_the_refusals_come_when_advancing_and_leave_nothing(self) -> None:
        """RF-015-29, RF-015-08, RF-009-21: un rechazo de la preparación (el alcance sin valor, un
        nombre ya usado por otra operación), sin versión o con una que no existe sale al avanzar y no
        deja nada."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            finish(self.run_steps(prep.request(reach_m=None)))
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        for version, code in ((None, "core.version_required"), ("V99", "core.version_unknown")):
            with self.subTest(version=version):
                with self.assertRaises(prep.versions_model.VersionError) as found:
                    finish(self.run_steps(prep.request(), version=version, masks=None))
                self.assertEqual(found.exception.code, code)
        self.assertEqual(self.state(), before)

    def test_a_discarding_deletes_the_temporary_and_a_calculation_is_a_context(self) -> None:
        """RF-015-03: «Cancelar» borra el temporal (y no hace nada la segunda vez); como gestor de
        contexto, al salir sin crear descarta."""
        before = self.state()
        calculation = finish(self.run_steps(prep.request()))
        self.assertEqual(len(self.temporaries()), 1)
        calculation.discard()
        calculation.discard()
        self.assertFalse(calculation.open)
        self.assertEqual(self.state(), before)
        with finish(self.run_steps(prep.request())) as inside:
            self.assertTrue(inside.open)
            self.assertEqual(len(self.temporaries()), 1)
        self.assertEqual(self.state(), before)

    def test_a_creating_is_not_available_until_t13(self) -> None:
        """RF-015-02 (T13): ``Calculation.create()`` de una plataforma dice que aún no se puede
        crear (``NotImplementedError``), sin escribir nada y sin cerrar la cuenta (se puede
        descartar)."""
        calculation = self.calculate(prep.request())
        before = self.state()
        with self.assertRaises(NotImplementedError) as caught:
            calculation.create()
        self.assertIn("T13", str(caught.exception))
        self.assertEqual(self.state(), before)
        self.assertTrue(calculation.open)
        calculation.discard()
        self.assertEqual(self.temporaries(), [])

    def test_a_the_counter_slope_is_confirmed_on_the_calculation(self) -> None:
        """RF-015-23 (T09, la orden de T15): una plataforma con contrapendiente pide confirmación
        (``needs_confirmation``); confirmarla en la cuenta (``confirm_counterslope``) o pedirla ya
        confirmada (``confirm_counterslope=True``) lo da por hecho, sin recalcular."""
        plain = self.calculate(prep.request(TOWER))
        self.assertTrue(plain.outcome.counter_slope)
        self.assertTrue(plain.needs_confirmation)
        outcome = plain.outcome
        plain.confirm_counterslope()
        self.assertFalse(plain.needs_confirmation)
        self.assertTrue(plain.outcome.confirmed)
        self.assertIs(plain.outcome.footprint, outcome.footprint)
        asked = self.calculate(prep.request(TOWER), confirm_counterslope=True)
        self.assertFalse(asked.needs_confirmation)
        self.assertTrue(self.calculate(prep.request()).outcome.counter_slope is False)


# ---------------------------------------------------------------------------------------------
# El resumen
# ---------------------------------------------------------------------------------------------


class SummaryTest(OperationCase):
    """RF-015-03 y RF-015-13: el resumen lleva las cifras y los avisos de lo que calcula."""

    def test_a_the_summary_has_the_figures_and_the_notices(self) -> None:
        """RF-015-03: el resumen de la cuenta lleva el nombre, el código y la versión, las cifras (las
        de ``PLATFORM_FIGURES`` que existen, con su unidad y el ámbito de la entidad), los avisos que
        enseña la cuenta (los de la cantera, línea a línea, en los dos idiomas) y, sin proteger ni
        sustituir, nada obsoleto."""
        calculation = self.calculate(prep.request())
        summary = calculation.summary
        self.assertEqual((summary.name, summary.code, summary.version), (LOADING, "PLT-001", "V01"))
        self.assertEqual(summary.figures, calculation.figures)
        declared = {figure.key: figure.unit for figure in provenance.PLATFORM_FIGURES}
        self.assertEqual({figure.key: figure.unit for figure in summary.figures},
                         {key: unit for key, unit in declared.items()
                          if key in {f.key for f in summary.figures}})
        self.assertIn("des.plat_area_m2", {figure.key for figure in summary.figures})
        scope = provenance.entity_figure_scope(LOADING, "PLT-001")
        self.assertTrue(all(figure.scope == scope for figure in summary.figures))
        self.assertEqual(summary.notices, calculation.notices)
        self.assertEqual(summary.obsolete, ())
        self.assertEqual(calculation.lines("es"), summary.lines("es"))
        self.assertEqual(calculation.lines("en"), summary.lines("en"))
        self.assertEqual(calculation.warnings("es"), summary.warnings("es"))
        self.assertTrue(all(isinstance(line, str) and "{" not in line
                            for line in (*summary.lines("es"), *summary.lines("en"))))
        self.assertIn("des.magnitude_no_reference", codes(summary))

    def test_a_the_created_step_and_the_wall_of_a_short_reach(self) -> None:
        """RF-015-13, RF-014-20, RF-014-21: con un alcance corto (4 m) el borde queda empinado en su
        límite y deja un salto creado: el resumen lo avisa con el nombre de la entidad (el aviso del
        salto creado de la 014 y sus tramos, no más de 10) y dice la pared más empinada."""
        summary = self.calculate(prep.request(reach_m=4.0)).summary
        wall = only(summary, "des.platform_edge_steep")
        self.assertEqual(wall.values["entity"], LOADING)
        step = only(summary, "des.edge_surface_step")
        self.assertEqual(step.values["surface"], LOADING)
        self.assertEqual(step.severity, "warning")
        stretches = [n for n in summary.notices if n.code == "des.edge_stretch"]
        self.assertTrue(0 < len(stretches) <= 10)
        self.assertEqual("des.edge_more_stretches" in codes(summary), step.values["stretches"] > 10)

    def test_a_what_reaches_cells_without_data_outside_the_footprint(self) -> None:
        """RF-015-13: lo que el borde mueve junto a celdas sin dato fuera de la huella se avisa con su
        área (15 celdas de hueco, a 8 m de la huella) y su lugar: el terreno de partida con el hueco
        al norte de la «Plataforma de carga» deja ``des.entity_edge_outside``."""
        summary = self.calculate(prep.request(start=EDGE_HOLE_DATASET)).summary
        outside = only(summary, "des.entity_edge_outside")
        self.assertEqual(outside.values["entity"], LOADING)
        self.assertGreater(outside.values["cells"], 0)
        self.assertAlmostEqual(outside.values["area"], outside.values["cells"] * CELL_M2)
        self.assertTrue(290.0 < outside.values["y"] - efx.BASE[1] < 300.0)
        self.assertTrue(195.0 < outside.values["x"] - efx.BASE[0] < 215.0)
        calm = self.calculate(prep.request()).summary
        self.assertNotIn("des.entity_edge_outside", codes(calm))

    def test_a_the_magnitude_against_the_last_frozen_revision(self) -> None:
        """RF-015-13, RF-013-30: sin revisión congelada, la nota de que no hay con qué comparar (con
        el nombre de la entidad); con una (la de ``platform_previous``) con un desmonte mucho menor,
        el aviso de magnitud con su revisión."""
        plain = self.calculate(prep.request()).summary
        self.assertEqual(only(plain, "des.magnitude_no_reference").values["operation"], LOADING)
        before = design_report.Previous(LOADING, "V01.r1", cut_m3=1.0, fill_m3=0.0)
        with mock.patch.object(entity_store, "platform_previous", return_value=before):
            compared = self.calculate(prep.request()).summary
        self.assertNotIn("des.magnitude_no_reference", codes(compared))
        cut = only(compared, "des.magnitude_cut")
        self.assertEqual(cut.values["revision"], "V01.r1")
        self.assertTrue(any("V01.r1" in line for line in compared.warnings("es")))

    def test_a_what_a_constraint_does_not_let_move_names_the_constraint(self) -> None:
        """RF-015-13, RF-015-07 (intocable real): la «Plataforma de la torre» cruza la zona del
        intocable «Torre» (entera dentro de su huella): sus celdas no se cortan y el resumen dice su
        área (m²), la restricción (con su nombre y su código) y su lugar; el área es la de la zona
        (a mano: sus celdas por 4 m²) y es toda la que las máscaras no dejan mover."""
        calculation = self.calculate(prep.request(TOWER))
        summary = calculation.summary
        zone = self.masks_v1.zone("torre")
        footprint = np.zeros(GRID.shape, dtype=bool)
        window = calculation.outcome.footprint.window
        footprint[window] = calculation.outcome.footprint.cells
        zone_cells = zone.mask(GRID.shape)
        self.assertFalse((zone_cells & ~footprint).any(), "la zona de la torre cae dentro de la huella")
        held = only(summary, "des.entity_held_constraint")
        self.assertEqual(held.values["entity"], TOWER)
        self.assertEqual(held.values["constraint"], "Torre (torre)")
        self.assertEqual(held.values["area"], zone.cells * CELL_M2)
        self.assertEqual(calculation.outcome.held_area_m2, zone.cells * CELL_M2)
        self.assertNotIn("des.entity_held_masks", codes(summary))
        rows, cols = np.nonzero(zone_cells)  # la primera celda: de norte a sur y de oeste a este
        self.assertEqual(held.values["x"], round(GRID.west + (cols[0] + 0.5) * GRID.dx, 2))
        self.assertEqual(held.values["y"], round(GRID.north - (rows[0] + 0.5) * GRID.dy, 2))
        self.assertEqual(held.severity, "warning")
        self.assertIn("«Torre (torre)»", summary.lines("es")[codes(summary).index(
            "des.entity_held_constraint")])

    def test_a_a_count_of_one_takes_its_singular(self) -> None:
        """RF-015-13, RF-015-24 (spec 014, T60): el grupo de celdas por encima de la rasante de la torre
        es uno (el de la zona del intocable): el resumen dice «en 1 grupo» y «in 1 group», no «1
        grupos», con el número sin escribir (el singular lo elige ``Notice.text``)."""
        summary = self.calculate(prep.request(TOWER)).summary
        above = only(summary, "des.platform_above")
        self.assertEqual(above.values["groups"], 1)
        spanish = summary.lines("es")[codes(summary).index("des.platform_above")]
        english = summary.lines("en")[codes(summary).index("des.platform_above")]
        self.assertIn("en 1 grupo,", spanish)
        self.assertIn("in 1 group,", english)
        for line in (*summary.lines("es"), *summary.lines("en")):
            self.assertNotRegex(line, r"\b1 (grupos|groups|celdas|cells)\b")

    def test_the_group_notes_are_capped_like_the_stretches(self) -> None:
        """RF-015-24, RF-015-03: el resumen enseña los 10 primeros grupos de lo que queda por encima o
        por debajo de la rasante y una nota con los que faltan (con su singular); la lista entera se
        queda en el resultado."""
        notice = preview.Notice
        every = [notice("des.platform_above", {"entity": "P", "area": 1.0, "maximum": 1.0,
                                               "groups": 12}),
                 *(notice("des.platform_above_group", {"group": n, "cells": 2, "area": 8.0,
                                                       "maximum": 1.0, "x": 1.0, "y": 2.0})
                   for n in range(1, 13)),
                 notice("des.platform_below", {"entity": "P", "area": 1.0, "maximum": 1.0,
                                               "groups": 3}),
                 *(notice("des.platform_below_group", {"group": n, "cells": 2, "area": 8.0,
                                                       "maximum": 1.0, "x": 1.0, "y": 2.0})
                   for n in range(1, 4)),
                 notice("des.magnitude_no_reference", {"operation": "P"})]
        shown = platform.summary_notices(every)
        found = [n.code for n in shown]
        self.assertEqual(found.count("des.platform_above_group"), 10)
        self.assertEqual(found.count("des.platform_below_group"), 3)
        self.assertEqual(found.count("des.platform_more_groups"), 1)
        more = shown[found.index("des.platform_more_groups")]
        self.assertEqual(more.values["groups"], 2)
        self.assertIn("y 2 grupos más", more.text("es"))
        self.assertEqual(found.index("des.platform_more_groups") - found.index("des.platform_above"), 11)
        eleven = every[:12] + every[13:]  # 11 grupos por encima: uno de más
        one = platform.summary_notices(eleven, limit=10)
        self.assertEqual(len(one), len(eleven))  # sale el grupo 11 y entra la nota
        self.assertEqual([n.values["groups"] for n in one if n.code == "des.platform_more_groups"],
                         [1])
        singular = platform.summary_notices(every, limit=11)
        self.assertIn("y 1 grupo más", [n for n in singular
                                          if n.code == "des.platform_more_groups"][0].text("es"))


# ---------------------------------------------------------------------------------------------
# Lo que no se mueve por una restricción: las funciones puras
# ---------------------------------------------------------------------------------------------


class HeldNoticesTest(unittest.TestCase):
    """RF-015-13: a partir de lo que no se mueve (la huella que no se corta ni se rellena, y el borde) y
    las zonas de las máscaras, ``preview.held_notices`` dice qué restricción lo impide: con el nombre
    de la entidad si la declara una (código ``DEC-…``), con su nombre si es una restricción normal y,
    si no es ninguna zona, que las máscaras no lo admiten."""

    GRID = gis.Grid(725_000.0, 4_400_000.0, 2.0, 2.0, 10, 8)
    WINDOW = (slice(1, 7), slice(2, 8))  # filas 1 a 6 y columnas 2 a 7 de la rejilla

    @classmethod
    def masks(cls, zones: dict[str, tuple[str, Any]]) -> Any:
        """Unas máscaras de doble con las zonas ``zones`` (código → (tipo, máscara de la rejilla))."""
        return access.MaskSet(
            cls.GRID, "version", "operation", access.MaskState.CURRENT, (),
            np.zeros(cls.GRID.shape, dtype=np.uint16),
            zones={code: zones_mod.Runs.from_mask(mask) for code, (_ctype, mask) in zones.items()},
            ctypes={code: ctype for code, (ctype, _mask) in zones.items()})

    @classmethod
    def region(cls, rows: slice, cols: slice) -> np.ndarray:
        """Una máscara de la rejilla entera con las filas y columnas dadas."""
        mask = np.zeros(cls.GRID.shape, dtype=bool)
        mask[rows, cols] = True
        return mask

    def window(self, mask: np.ndarray) -> np.ndarray:
        """La parte de ``mask`` que cae en la ventana de trabajo."""
        return mask[self.WINDOW]

    def notices(self, zones: dict[str, tuple[str, Any]], *, cut: Any = None, fill: Any = None,
                edge: Any = None, names: dict[str, str] | None = None,
                declared: dict[str, str] | None = None) -> tuple[Any, ...]:
        empty = np.zeros((6, 6), dtype=bool)
        return preview.held_notices(
            "P2", self.masks(zones), self.WINDOW,
            cut=empty if cut is None else self.window(cut),
            fill=empty if fill is None else self.window(fill),
            edge=empty if edge is None else self.window(edge),
            names=names or {}, declared=declared or {})

    def test_a_declared_constraint_names_the_entity_that_declares_it(self) -> None:
        """RF-015-13, RF-015-10: la zona ``DEC-PLT-001`` (sin relleno) impide rellenar 4 celdas de la
        huella: el aviso dice 16 m², la restricción, la entidad del registro y la primera celda (de
        norte a sur y de oeste a este) con sus coordenadas absolutas en float64."""
        zone = self.region(slice(3, 5), slice(4, 6))
        found = self.notices({"DEC-PLT-001": ("no_fill", zone)}, fill=zone,
                             declared={"DEC-PLT-001": "Plataforma P1"})
        (held,) = found
        self.assertEqual(held.code, "des.entity_held")
        self.assertEqual(dict(held.values), {
            "entity": "P2", "area": 16.0, "constraint": "DEC-PLT-001", "other": "Plataforma P1",
            "x": 725_000.0 + (4 + 0.5) * 2.0, "y": 4_400_000.0 - (3 + 0.5) * 2.0})
        self.assertIn("«Plataforma P1»", held.text("es"))
        self.assertIn("DEC-PLT-001", held.text("en"))

    def test_a_declared_constraint_of_an_unknown_entity_gives_its_code(self) -> None:
        """RF-015-13: una ``DEC-…`` cuya entidad el registro no tiene (la borraron) se nombra con el
        código de la entidad; no se pierde el aviso."""
        zone = self.region(slice(2, 3), slice(3, 6))
        (held,) = self.notices({"DEC-PLT-009": ("no_cut", zone)}, cut=zone)
        self.assertEqual((held.code, held.values["other"]), ("des.entity_held", "PLT-009"))
        self.assertEqual(held.values["area"], 12.0)

    def test_a_normal_constraint_is_named_with_its_code(self) -> None:
        """RF-015-13: una restricción normal se nombra con su nombre y su código («Torre (torre)») o,
        sin nombre, con el código; el borde también cuenta (en una zona de «sin corte»)."""
        zone = self.region(slice(2, 4), slice(2, 5))
        (held,) = self.notices({"torre": ("untouchable", zone)}, cut=zone,
                               names={"torre": "Torre"})
        self.assertEqual((held.code, held.values["constraint"], held.values["area"]),
                         ("des.entity_held_constraint", "Torre (torre)", 24.0))
        (edge,) = self.notices({"sin_corte": ("no_cut", zone)}, edge=zone)
        self.assertEqual((edge.values["constraint"], edge.values["area"]), ("sin_corte", 24.0))

    def test_a_cell_outside_every_zone_is_what_the_masks_do_not_allow(self) -> None:
        """RF-015-13: lo que ninguna zona explica (fuera del límite, su banda…) se avisa aparte
        (``des.entity_held_masks``) con su área y su lugar; lo explicado y lo no explicado salen
        cada uno en su aviso y el área no se cuenta dos veces."""
        zone = self.region(slice(1, 2), slice(2, 4))
        loose = self.region(slice(5, 7), slice(6, 8))
        found = self.notices({"torre": ("untouchable", zone)}, cut=zone | loose,
                             names={"torre": "Torre"})
        self.assertEqual([n.code for n in found], ["des.entity_held_constraint",
                                                   "des.entity_held_masks"])
        self.assertEqual((found[0].values["area"], found[1].values["area"]), (8.0, 16.0))
        self.assertEqual((found[1].values["x"], found[1].values["y"]),
                         (725_000.0 + 6.5 * 2.0, 4_400_000.0 - 5.5 * 2.0))

    def test_a_zone_that_does_not_forbid_the_movement_does_not_explain_it(self) -> None:
        """RF-015-13: una zona «preferible no afectar» no prohíbe nada, y una de «sin relleno» no
        explica una celda que no se corta: esas celdas quedan para «las máscaras no lo admiten»."""
        zone = self.region(slice(2, 4), slice(3, 5))
        for ctype in ("avoid", "requires_access", "no_fill"):
            with self.subTest(ctype=ctype):
                (held,) = self.notices({"zona": (ctype, zone)}, cut=zone)
                self.assertEqual(held.code, "des.entity_held_masks")
        (filled,) = self.notices({"zona": ("no_fill", zone)}, fill=zone)
        self.assertEqual(filled.code, "des.entity_held_constraint")

    def test_a_legal_limit_band_is_named_by_its_limit(self) -> None:
        """RF-015-13: la banda hacia dentro de un límite legal (zona ``<código>:inner``) impide cortar y
        se nombra con el límite."""
        band = self.region(slice(1, 3), slice(2, 8))
        (held,) = self.notices({"concesion:inner": ("legal_limit", band)}, cut=band,
                               names={"concesion": "Concesión"})
        self.assertEqual((held.code, held.values["constraint"]),
                         ("des.entity_held_constraint", "Concesión (concesion)"))

    def test_a_zone_larger_than_what_is_held_counts_only_what_is_held(self) -> None:
        """RF-015-13: la zona se mira solo donde hay celdas que no se mueven: una zona que cubre toda la
        rejilla y dos grupos separados dan el área de esas celdas (6 + 1, a 4 m²) y el lugar de la
        primera de norte a sur y de oeste a este."""
        everything = self.region(slice(0, 8), slice(0, 10))
        held = self.region(slice(2, 4), slice(3, 6)) | self.region(slice(5, 6), slice(6, 7))
        (found,) = self.notices({"z": ("untouchable", everything)}, cut=held)
        self.assertEqual(found.values["area"], 28.0)
        self.assertEqual((found.values["x"], found.values["y"]),
                         (725_000.0 + 3.5 * 2.0, 4_400_000.0 - 2.5 * 2.0))

    def test_nothing_held_nothing_said(self) -> None:
        """RF-015-13: sin celdas que no se muevan, ningún aviso (y sin zonas, tampoco)."""
        zone = self.region(slice(2, 4), slice(3, 5))
        self.assertEqual(self.notices({"torre": ("untouchable", zone)}), ())
        self.assertEqual(self.notices({}), ())

    def test_a_zone_outside_the_window_is_ignored(self) -> None:
        """RF-015-13: una zona que no toca la ventana de trabajo no cuenta (ni se pinta entera)."""
        outside = self.region(slice(0, 1), slice(0, 2))
        near = self.region(slice(1, 3), slice(2, 4))
        (held,) = self.notices({"lejos": ("untouchable", outside),
                                "cerca": ("untouchable", near)}, cut=near)
        self.assertEqual(held.values["constraint"], "cerca")


class HeldByDeclaredTest(OperationCase):
    """RF-015-13, RF-015-10: con una restricción declarada por otra entidad (``DEC-PLT-001``, de la
    «Plataforma P1» del registro) que impide cortar, el resumen dice el área que no mueve y esa
    entidad. La declarada es un doble (la tabla de las declaradas es de la T16)."""

    P1 = "Plataforma P1"
    BOX = (150.0, 270.0, 170.0, 290.0)
    """Parte de la huella de la «Plataforma de carga» (local): 10 × 10 celdas de 2 m = 400 m²."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for param, value in (("name", cls.P1), ("start", "des_srf_otra"),
                                 ("start_level_m", 230.0), ("gradient_pct", 1.0)):
                store.create(conn, design_params.entity_key("PLT-001", param), value,
                             kind="ADOPTADO", source="Prueba de la 015", source_kind="person",
                             decided_by="Samuel (IMGA)", reason="Prueba de T12",
                             version=cls.v1.code)
        zone = qfx.in_box(cls.BOX, GRID)
        classes = np.array(cls.masks_v1.classes)
        classes[zone] &= ~np.uint16(int(combine.ClassBit.CUT_ALLOWED))
        cls.declared_zone = zone
        cls.double = dataclasses.replace(
            cls.masks_v1, classes=classes,
            zones={**cls.masks_v1.zones, "DEC-PLT-001": zones_mod.Runs.from_mask(zone)},
            ctypes={**cls.masks_v1.ctypes, "DEC-PLT-001": "no_cut"})

    def test_a_the_summary_names_the_entity_that_declares_the_constraint(self) -> None:
        """RF-015-13: la «Plataforma de carga» (PLT-002, tras la P1) no corta las 100 celdas de la
        zona declarada: el resumen dice 400 m², ``DEC-PLT-001`` y la entidad «Plataforma P1»; y, aparte,
        lo que su borde oeste no mueve por «Sin corte» (una restricción normal, con su nombre): entre
        las dos, todo lo que no mueve (y no hay aviso de máscaras sueltas)."""
        calculation = self.calculate(prep.request(), masks=self.double)
        self.assertEqual(calculation.entity.code, "PLT-002")
        held = only(calculation.summary, "des.entity_held")
        self.assertEqual((held.values["constraint"], held.values["other"], held.values["area"]),
                         ("DEC-PLT-001", self.P1, 400.0))
        normal = only(calculation.summary, "des.entity_held_constraint")
        self.assertEqual(normal.values["constraint"], "Sin corte (sin_corte)")
        self.assertGreater(normal.values["area"], 0.0)
        self.assertEqual(held.values["area"] + normal.values["area"],
                         calculation.outcome.held_area_m2)
        self.assertNotIn("des.entity_held_masks", codes(calculation.summary))
        text = calculation.summary.lines("es")[codes(calculation.summary).index("des.entity_held")]
        self.assertIn(f"«{self.P1}»", text)
        self.assertEqual(len(self.temporaries()), 1)

    def test_a_without_the_declared_zone_only_the_normal_constraint_is_named(self) -> None:
        """RF-015-13: con las máscaras de V01 (sin la declarada) la misma plataforma corta toda su
        huella y solo avisa de lo que su borde no mueve junto a «Sin corte»."""
        calculation = self.calculate(prep.request())
        summary = calculation.summary
        self.assertNotIn("des.entity_held", codes(summary))
        self.assertNotIn("des.entity_held_masks", codes(summary))
        normal = only(summary, "des.entity_held_constraint")
        self.assertEqual(normal.values["constraint"], "Sin corte (sin_corte)")
        self.assertEqual(normal.values["area"], calculation.outcome.held_area_m2)


# ---------------------------------------------------------------------------------------------
# Lo que quedará obsoleto
# ---------------------------------------------------------------------------------------------


class ObsoleteCase(OperationCase):
    """V01 con una cantera de la 014 y su transición (usan las máscaras: son lo que depende de ellas) y
    cuatro entidades en el registro: P2 (parte del terreno), P3 (de la superficie de P2) y P4 (de la
    de P3), **hechas** (sus operaciones, sintéticas, leen sus parámetros y consumen la superficie de la
    anterior como lo hará la T13), y P5 (de la de P4), sin calcular; más una capa de una plataforma
    a 330 m."""

    QUARRY, TRANSITION = "Cantera E7", "Transición E7"
    HIGH_LAYER = "gis_fea_plataformas_altas"
    quarry: ClassVar[Any]
    transition: ClassVar[Any]
    chain: ClassVar[dict[str, str]]

    @classmethod
    def declare(cls, key: str, value: object) -> None:
        """Declara un parámetro del proyecto."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, key, value, kind="ADOPTADO", source="Perfil de prueba", source_kind="person",
                decided_by="Samuel (IMGA)", reason="Prueba de T12")

    @classmethod
    def entity(cls, number: int, name: str, start: str, *, made: bool = True) -> str:
        """Da de alta la entidad ``PLT-00<n>`` en V01 y, si ``made``, registra su operación sintética (la
        del contrato de la T03): lee sus parámetros, consume como ``surface`` la superficie de la
        entidad de la que parte (``entity:PLT-00<m>``) y escribe la suya (``des_psf_p<n>``, una tabla
        de juguete). Devuelve el uid de la operación (``""`` sin ella)."""
        store = core_params.ParameterStore(cls.project)
        code = f"PLT-00{number}"
        cls.clock.advance(minutes=1)
        keys = []
        with cls.project.write_transaction() as conn:
            for param, value in (("name", name), ("start", start)):
                keys.append(design_params.entity_key(code, param))
                store.create(conn, keys[-1], value, kind="ADOPTADO", source="Prueba de la 015",
                             source_kind="person", decided_by="Samuel (IMGA)",
                             reason="Prueba de T12", version=cls.v1.code)
        if not made:
            return ""
        cls.clock.advance(minutes=1)
        before = entities_module.ref_code(start)
        reads = [] if before is None else [operations.Use(
            f"des_psf_p{int(before.rsplit('-', 1)[1])}", "surface")]
        handle = operations.begin_operation(
            cls.project, "des.platform", settings={"code": code, "name": name}, params=keys,
            inputs=reads, executor="blender", version=cls.v1.uid)
        label = f"des_psf_p{number}"
        locator = versions_model.version_locator(label, cls.v1.code)
        with cls.project.write_transaction() as conn:
            gpkg_base.create_attribute_table(
                conn, locator, [gpkg_base.ColumnDef("value", "DOUBLE")], label,
                "Dato sintético de la prueba de T12 (spec 015)")
            conn.execute(f'INSERT INTO "{locator}" (value) VALUES (?)', (float(number),))
            handle.complete(conn, outputs=[datasets.DatasetSpec(
                label, "des", "table", datasets.Store.GPKG, locator, reader=builtin.GPKG_LAYER.id,
                role="entity_surface")])
        return str(handle.uid)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.FAMILIES)
        cls.enterClassContext(registered(*edges_test.definitions()))
        for profile in (qfx.EXPLOITATION_PROFILE, qfx.FINAL_PROFILE):
            for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
                cls.declare(design_params.bench_key(profile.code, param), getattr(profile, param))
        cls.declare(design_params.EDGE_TRANSITION, edges_test.ANGLE_DEG)
        cls.clock.advance(minutes=1)
        asked = model.QuarryRequest(
            name=cls.QUARRY, start=START, final=model.QuarrySide(qfx.FINAL_PROFILE.code),
            exploitation=model.QuarrySide(qfx.EXPLOITATION_PROFILE.code))
        cls.quarry = finish(steps.quarry_run(cls.project, asked, version=cls.v1.uid,
                                             masks=cls.masks_v1)).create()
        cls.clock.advance(minutes=1)
        cls.transition = finish(steps.edge_transition_run(
            cls.project, cls.TRANSITION, provenance.dataset_name("fin", cls.QUARRY), START,
            version=cls.v1.uid, masks=cls.masks_v1)).create()
        cls.chain = {"P2": cls.entity(2, "P2", START),
                     "P3": cls.entity(3, "P3", "entity:PLT-002"),
                     "P4": cls.entity(4, "P4", "entity:PLT-003"),
                     "P5": cls.entity(5, "P5", "entity:PLT-004", made=False)}
        qfx.write_feature_layer(cls.project, cls.clock, qfx.LayerData(
            cls.HIGH_LAYER, "line", (((cfx.absolute(efx.AXES[0].path),),),), ("Alta",),
            {"ancho": (20.0,), "cota_inicial": (330.0,), "pendiente": (0.0,)}))
        cls.clock.advance(minutes=1)
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)


class ObsoleteTest(ObsoleteCase):
    """RF-015-03 (RF-015-16, RF-015-05): lo que quedará obsoleto al crear la entidad."""

    def test_a_a_platform_that_protects_makes_the_masks_and_what_used_them_obsolete(self) -> None:
        """RF-015-03, RF-015-10, RF-015-16: al crear una plataforma que protege su huella (con su
        resguardo), quedan obsoletas las máscaras de la versión y lo que las usó (la cantera y su
        transición, por su nombre y su tipo: del grafo de la 008); el resumen lo dice en dos notas, la
        segunda con la cuenta y los nombres."""
        calculation = self.calculate(prep.request(start="gis_dtm_borde", protect=True,
                                                  guard_m=4.0))
        summary = calculation.summary
        self.assertEqual(summary.obsolete[0].kind, preview.ObsoleteKind.MASKS)
        self.assertEqual(summary.obsolete[0].name, "V01")
        consumers = {(item.name, item.op_type, item.uid) for item in summary.obsolete
                     if item.kind is preview.ObsoleteKind.CONSUMER}
        self.assertEqual(consumers, {
            (self.QUARRY, "des.quarry", self.quarry.handle.uid),
            (self.TRANSITION, "des.edge_transition", self.transition.handle.uid)})
        masks = only(summary, "des.entity_obsolete_masks")
        self.assertEqual((masks.values["entity"], masks.values["version"]), (LOADING, "V01"))
        used = only(summary, "des.entity_obsolete_consumers")
        self.assertEqual(used.values["operations"], 2)
        self.assertIn(f"«{self.QUARRY}»", used.text("es"))
        self.assertIn(f"«{self.TRANSITION}»", used.text("es"))
        self.assertEqual(calculation.entity.values["protect"], True)
        self.assertEqual(len(summary.obsolete), 3)

    def test_a_a_platform_that_does_not_protect_makes_nothing_obsolete(self) -> None:
        """RF-015-03: sin proteger, ni las máscaras ni lo que las usó quedan obsoletos y el resumen no
        dice nada de lo obsoleto."""
        summary = self.calculate(prep.request(start="gis_dtm_borde")).summary
        self.assertEqual(summary.obsolete, ())
        self.assertFalse([code for code in codes(summary) if "obsolete" in code])

    def test_a_a_single_consumer_takes_its_singular(self) -> None:
        """RF-015-03 (spec 014, T60): lo que quedaría obsoleto por una sola operación se dice en
        singular, con el número sin escribir: «1 operación», no «1 operaciones»."""
        one = (preview.Obsolete(preview.ObsoleteKind.CONSUMER, self.QUARRY, "des.quarry", "u1"),)
        notices = preview.obsolete_notices(LOADING, "V01", one)
        self.assertEqual([n.code for n in notices], ["des.entity_obsolete_consumers"])
        self.assertIn("Con ellas quedará obsoleta 1 operación", notices[0].text("es"))
        self.assertIn("With them, 1 operation", notices[0].text("en"))

    def test_a_an_insertion_makes_the_successor_and_the_ones_after_it_obsolete(self) -> None:
        """RF-015-03, RF-015-05: una plataforma que se inserta antes de P2 (parte de su misma
        superficie, el terreno) deja obsoletas P2 y las que le siguen (P3 y P4): el resumen las lista;
        P5, sin calcular, no (no tiene nada que quedar obsoleto); y sin ``insert_before`` el mismo
        cálculo se rechaza (de cada superficie parte una sola)."""
        with self.assertRaises(messages.DesignError) as caught:
            finish(self.run_steps(prep.request()))
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        summary = self.calculate(prep.request(), insert_before="P2").summary
        self.assertEqual([(item.kind, item.name) for item in summary.obsolete],
                         [(preview.ObsoleteKind.SUCCESSOR, "P2"),
                          (preview.ObsoleteKind.SUCCESSOR, "P3"),
                          (preview.ObsoleteKind.SUCCESSOR, "P4")])
        self.assertEqual([item.uid for item in summary.obsolete],
                         [self.chain["P2"], self.chain["P3"], self.chain["P4"]])
        text = only(summary, "des.entity_obsolete_successor")
        self.assertEqual((text.values["entities"], text.values["entity"]), (3, LOADING))
        self.assertNotIn("des.entity_obsolete_masks", codes(summary))

    def test_a_an_insertion_is_checked_like_any_chain(self) -> None:
        """RF-015-04, RF-015-05: ``insert_before`` solo vale con la entidad que parte de la misma
        superficie (P3 parte de la de P2, no del terreno: error del programa) y con una que no existe
        también; sin él, una superficie libre se calcula sin problema y sin nada obsoleto."""
        with self.assertRaises(ValueError):
            finish(self.run_steps(prep.request(), insert_before="P3"))
        with self.assertRaises(ValueError):
            finish(self.run_steps(prep.request(), insert_before="P9"))
        free = self.calculate(prep.request(start=provenance.dataset_name("fin", self.QUARRY)))
        self.assertEqual(free.summary.obsolete, ())

    def test_a_what_depends_on_the_operation_it_replaces(self) -> None:
        """RF-015-03, RF-008-26: si la nueva sustituye a una operación, lo que dependía de ella (lo que
        consume lo que escribió: la transición, de la superficie final de la cantera) queda obsoleto;
        la propia operación no, y una operación de la que nada depende no deja nada. Lo da
        ``platform_obsolete`` sobre el grafo."""
        prepared = self.units(prep.request(start="gis_dtm_borde"))
        found = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                               supersedes=self.quarry.handle.uid)
        self.assertEqual([(item.kind, item.name, item.uid) for item in found],
                         [(preview.ObsoleteKind.DEPENDENT, self.TRANSITION,
                           self.transition.handle.uid)])
        notices = preview.obsolete_notices(LOADING, "V01", found)
        self.assertEqual([n.code for n in notices], ["des.entity_obsolete_dependents"])
        self.assertIn("quedará obsoleta 1 operación", notices[0].text("es"))
        self.assertEqual(entity_store.platform_obsolete(
            self.project, self.v1, prepared, self.masks_v1,
            supersedes=self.transition.handle.uid), ())

    def test_a_the_cascade_goes_as_far_as_the_chain_does(self) -> None:
        """RF-015-03, RF-015-16, RF-008-24: sustituir la operación de P2 deja obsoletas la de P3, que
        consumió su superficie, y en cascada la de P4, que consumió la de P3 (no P2 ni P5, que no tiene
        operación ni consumió nada)."""
        prepared = self.units(prep.request(start="gis_dtm_borde"))
        found = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                               supersedes=self.chain["P2"])
        self.assertEqual([(item.kind, item.name, item.uid) for item in found],
                         [(preview.ObsoleteKind.DEPENDENT, "P3", self.chain["P3"]),
                          (preview.ObsoleteKind.DEPENDENT, "P4", self.chain["P4"])])
        last = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                              supersedes=self.chain["P4"])
        self.assertEqual(last, ())

    def test_a_what_the_replaced_operation_used_is_not_counted_with_the_masks(self) -> None:
        """RF-015-03: si la nueva protege y sustituye la operación de la cantera, que también usó las
        máscaras, la sustituida no cuenta entre lo que queda obsoleto (se rehace, no se invalida); sí la
        transición, que usó las máscaras y, además, dependía de la cantera: una sola vez."""
        prepared = self.units(prep.request(start="gis_dtm_borde", protect=True, guard_m=4.0))
        found = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                               supersedes=self.quarry.handle.uid)
        self.assertEqual([(item.kind, item.uid) for item in found],
                         [(preview.ObsoleteKind.MASKS, self.masks_v1.operation_uid),
                          (preview.ObsoleteKind.CONSUMER, self.transition.handle.uid)])

    # --- RF-015-14: el orden de la cantera ----------------------------------------------------

    def test_a_a_platform_over_the_final_surface_above_the_exploitation_warns(self) -> None:
        """RF-015-14: una plataforma «en corte y relleno» a 330 m sobre la superficie final de la
        cantera la sube por encima de la de explotación: el resumen avisa con la cantera, las dos
        superficies, el área y el lugar, y no impide crearla (ni pide confirmación por ello)."""
        final = provenance.dataset_name("fin", self.QUARRY)
        exploitation = provenance.dataset_name("exp", self.QUARRY)
        asked = prep.request("Alta", fields=prep.line_fields(self.HIGH_LAYER), start=final,
                             mode="cut_fill")
        calculation = self.calculate(asked)
        order = only(calculation.summary, "des.entity_quarry_order")
        self.assertEqual((order.values["quarry"], order.values["surface"], order.values["other"]),
                         (self.QUARRY, final, exploitation))
        outcome = calculation.outcome
        self.assertIsNotNone(outcome.order)
        self.assertEqual(order.values["area"], outcome.order.area_m2)
        self.assertGreater(order.values["area"], 0.0)
        other = geotiff_reader.read_geotiff(
            self.root / self.record(exploitation, self.v1).locator).values
        expected = platform.order_check(outcome.result, other, "final", GRID,
                                        outcome.footprint.window)
        self.assertEqual(expected.cells, outcome.order.cells)
        self.assertFalse(calculation.needs_confirmation)

    def test_a_a_surface_that_is_not_of_a_quarry_does_not_warn(self) -> None:
        """RF-015-14: sobre el terreno (que no es de una cantera) no hay otra superficie con la que
        comparar y no se avisa."""
        calculation = self.calculate(prep.request(start="gis_dtm_borde"))
        self.assertIsNone(calculation.outcome.order)
        self.assertNotIn("des.entity_quarry_order", codes(calculation.summary))


class FrozenConsumersTest(ObsoleteCase):
    """RF-015-16 (RF-009-19): lo que usó las máscaras en una revisión **congelada** no se marca
    obsoleto."""

    def test_a_the_operations_of_a_frozen_revision_are_not_marked(self) -> None:
        """RF-015-16: tras congelar V01, la cantera y su transición (ya en la revisión congelada) no
        salen entre lo que quedará obsoleto; las máscaras de la versión, sí."""
        with self.project.write_transaction() as conn:
            freeze_rows(conn, self.v1, now=self.clock.now().isoformat(timespec="seconds"),
                        reason="Siguiente")
        calculation = self.calculate(prep.request(start="gis_dtm_borde", protect=True,
                                                  guard_m=4.0))
        self.assertEqual([item.kind for item in calculation.summary.obsolete],
                         [preview.ObsoleteKind.MASKS])
        self.assertNotIn("des.entity_obsolete_consumers", codes(calculation.summary))


# ---------------------------------------------------------------------------------------------
# Con qué se compara la magnitud
# ---------------------------------------------------------------------------------------------


class PreviousFrozenTest(OperationCase):
    """RF-015-13, RF-013-30 (D-25): la magnitud se compara con la plataforma de la **revisión congelada**
    más reciente de la versión que tiene el mismo código de entidad, con el desmonte y el relleno de su
    huella y de su borde sumados; una operación de ese tipo sin esas cifras, de otra entidad o de una
    revisión sin congelar no cuenta."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.written = cls.operation(LOADING, "PLT-001", cut=100.0, fill=10.0, edge_cut=50.0,
                                    edge_fill=5.0)
        cls.other = cls.operation("Otra", "PLT-002", cut=1.0, fill=1.0, edge_cut=1.0, edge_fill=1.0)
        with cls.project.write_transaction() as conn:
            freeze_rows(conn, cls.v1, now=cls.clock.now().isoformat(timespec="seconds"),
                        reason="Siguiente")
        cls.clock.advance(minutes=1)
        cls.unfrozen = cls.operation(LOADING, "PLT-001", cut=9_999.0, fill=9_999.0,
                                     edge_cut=9_999.0, edge_fill=9_999.0)

    @classmethod
    def operation(cls, name: str, code: str, *, cut: float, fill: float, edge_cut: float,
                  edge_fill: float) -> str:
        """Una operación ``des.platform`` hecha de ``code`` con las cifras dadas."""
        figures = provenance.platform_figures(name, code, {
            "des.plat_area_m2": 1.0, "des.plat_axis_m": 1.0, "des.plat_footprint_m": 1.0,
            "des.plat_start_level_m": 1.0, "des.plat_end_level_m": 1.0, "des.plat_cut_m3": cut,
            "des.plat_fill_m3": fill, "des.edge_cut_m3": edge_cut, "des.edge_fill_m3": edge_fill,
            "des.edge_wall_max_m": None, "des.plat_below_m2": 0.0, "des.plat_below_max_m": None})
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(
            cls.project, "des.platform", settings=provenance.platform_settings(
                prep.request(name), code), executor="blender", version=cls.v1.uid)
        with cls.project.write_transaction() as conn:
            handle.complete(conn, outputs=(), figures=figures)
        return str(handle.uid)

    def test_a_the_previous_is_the_entity_of_the_last_frozen_revision(self) -> None:
        """RF-013-30, D-25: ``platform_previous`` da, de la entidad PLT-001, el desmonte (100 + 50) y el
        relleno (10 + 5) de la revisión V01.r1 con el nombre de su operación; la de otra entidad no se
        mezcla y la de la revisión abierta (con otras cifras) no cuenta; sin revisión congelada, o sin
        operación de esa entidad en ella, ninguna."""
        with self.project.read() as conn:
            found = entity_store.platform_previous(conn, self.v1, "PLT-001")
            other = entity_store.platform_previous(conn, self.v1, "PLT-002")
            nobody = entity_store.platform_previous(conn, self.v1, "PLT-009")
            before_any = entity_store.platform_previous(conn, self.v2, "PLT-001")
        self.assertEqual((found.operation, found.revision, found.cut_m3, found.fill_m3),
                         (LOADING, "V01.r1", 150.0, 15.0))
        self.assertEqual((other.operation, other.cut_m3, other.fill_m3), ("Otra", 2.0, 2.0))
        self.assertIsNone(nobody)
        self.assertIsNone(before_any)

    def test_a_calculating_compares_with_it(self) -> None:
        """RF-015-13: «Calcular» la «Plataforma de carga» (PLT-004: hay tres operaciones antes en la
        versión pero ninguna entidad en el registro, así que parte del código PLT-001) compara su
        desmonte con el de la congelada (150 m³): el aviso de magnitud con V01.r1."""
        calculation = self.calculate(prep.request())
        self.assertEqual(calculation.entity.code, "PLT-001")
        cut = only(calculation.summary, "des.magnitude_cut")
        self.assertEqual((cut.values["revision"], cut.values["previous"]), ("V01.r1", 150))
        self.assertNotIn("des.magnitude_no_reference", codes(calculation.summary))


if __name__ == "__main__":
    unittest.main()
