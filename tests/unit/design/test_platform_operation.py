# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular» una plataforma y su resumen (spec 015, T12; HU-015-3; RF-015-03, RF-015-13, RF-015-29;
plan 015 §5.3.2 y §5.4; E1 y E2 de la spec), «Crear» (T13; HU-015-1; RF-015-01, RF-015-02, RF-015-04) y
recalcular y reproducir (T14; HU-015-1, HU-015-2; RF-015-02, RF-015-04, RF-015-16): casos (a), (b), (c), (d) y
(e) de ``test_platform_operation``.

Sobre la cantera sintética de la 014 con las capas de plataformas (``tests.support.entity_fixtures``)
y su rejilla gruesa de 2 m:

- **El cálculo compartido** (``entity_store.platform_compute_steps``): huella → aplicar → borde →
  perfil → ``platform_outcome``, por pasos y sin proyecto dentro, es lo que hacen a mano las
  funciones de las T06 a T09; lo comparten «Calcular», el recálculo y la reproducción.
- **«Calcular» no escribe** (RF-015-03, RF-015-29): ``steps.platform_run`` deja la superficie en un
  temporal y el resumen, y **nada en el proyecto** (ni la base de datos, ni operaciones, ni datos, ni
  parámetros); cerrarlo a mitad, descartar la cuenta o un fallo después del temporal no dejan nada;
  los rechazos salen al avanzar.
- **El resumen** (RF-015-03, RF-015-13): las cifras, los avisos (el salto creado, la magnitud, lo que
  llega a celdas sin dato fuera de la huella, el área que no mueve por la restricción de otra entidad
  con esa entidad, o con el nombre de la restricción) y lo que quedará obsoleto al crearla (si
  protege: las máscaras y lo que las usó; si inserta: la sucesora y las que le siguen; si sustituye
  una operación: lo que dependía de ella), con el singular («en 1 grupo»).
- **«Crear»** (T13; RF-015-01, RF-015-02, RF-015-04): registra todo en **una** transacción (la
  superficie ``des_psf_``, la tabla ``des_epr_`` con la huella en tramos de fila, el eje y los
  atributos, el informe ``des_prp_``, las cifras con el ámbito de la entidad, la operación con sus
  entradas y los parámetros de la entidad como filas de la versión con su origen); si algo falla a
  mitad no queda nada; no modifica la capa de origen; una plataforma que parte de otra consume su
  superficie y queda obsoleta, con la causa, si cambia la de la primera; una contrapendiente sin
  confirmar no se crea.
- **Recalcular** (T14, casos (c); RF-015-02, RF-015-16, RF-008-26): ``store.recompute_run`` repite la
  plataforma como una operación **nueva** que sustituye a la anterior (queda como historia) con los
  parámetros vigentes **de la versión** (no los de la capa: la cota, la pendiente y el ancho se copiaron al
  crearla, P-3), y da las mismas cifras y los mismos datos si nada cambió; un cambio que deja la superficie
  como estaba quita la marca de la siguiente sin recalcularla (RF-008-26); un parámetro que cambia entre
  preparar y empezar, o una contrapendiente que ya no está confirmada, no se registran.
- **Reproducir** (T14, casos (d); RF-015-02, RF-009-11): ``design.reproduce.reproduce_platform`` rehace, **sin
  proyecto**, desde lo congelado de V01.r1 (la capa, la partida, el apoyo, las máscaras y los parámetros
  congelados) la superficie, la tabla y el informe de cada plataforma con el **mismo hash** y las mismas
  cifras, sin escribir nada.
- **La cascada** (T14, casos (e); RF-015-16, RF-008-24, RF-009-19): cambiar un parámetro de P1 deja obsoleta
  P1 y, con su causa, P2, que consumió su superficie; «Recalcular lo obsoleto» las repite **en orden de
  dependencia** (P1 antes que P2, aunque la operación de P1 sea posterior a la de P2) y deja la revisión
  congelada como estaba (sus elementos no cambian y se reproduce igual).
"""

from __future__ import annotations

import dataclasses
import json
import math
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
from tests.support.versions_fixtures import change_counter, files, freeze_rows
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
design_reproduce = import_geoblender("design.reproduce")
freeze = import_geoblender("core.versions.freeze")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
figures_mod = import_geoblender("core.provenance.figures")
design_store = import_geoblender("design.store")
geotiff_reader = import_geoblender("gis.geotiff.reader")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
platform = import_geoblender("design.platform")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
res_provenance = import_geoblender("reserves.provenance")
steps = import_geoblender("design.steps")
timeutil = import_geoblender("core.timeutil")
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
                         [provenance.dataset_name(family, LOADING)
                          for family in ("psf", "epr", "prp")])
        self.assertTrue(all(spec.content is not None for spec in calculation.specs),
                        "las tres salidas llevan ya su hash")
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
    de la entidad si la declara una (código ``dec__…``), con su nombre si es una restricción normal y,
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
        """RF-015-13, RF-015-10: la zona ``dec__plt_001`` (sin relleno) impide rellenar 4 celdas de la
        huella: el aviso dice 16 m², la restricción, la entidad del registro y la primera celda (de
        norte a sur y de oeste a este) con sus coordenadas absolutas en float64."""
        zone = self.region(slice(3, 5), slice(4, 6))
        found = self.notices({"dec__plt_001": ("no_fill", zone)}, fill=zone,
                             declared={"dec__plt_001": "Plataforma P1"})
        (held,) = found
        self.assertEqual(held.code, "des.entity_held")
        self.assertEqual(dict(held.values), {
            "entity": "P2", "area": 16.0, "constraint": "dec__plt_001", "other": "Plataforma P1",
            "x": 725_000.0 + (4 + 0.5) * 2.0, "y": 4_400_000.0 - (3 + 0.5) * 2.0})
        self.assertIn("«Plataforma P1»", held.text("es"))
        self.assertIn("dec__plt_001", held.text("en"))

    def test_a_declared_constraint_of_an_unknown_entity_gives_its_code(self) -> None:
        """RF-015-13: una ``dec__…`` cuya entidad el registro no tiene (la borraron) se nombra con el
        código de la entidad; no se pierde el aviso."""
        zone = self.region(slice(2, 3), slice(3, 6))
        (held,) = self.notices({"dec__plt_009": ("no_cut", zone)}, cut=zone)
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
    """RF-015-13, RF-015-10: con una restricción declarada por otra entidad (``dec__plt_001``, de la
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
            zones={**cls.masks_v1.zones, "dec__plt_001": zones_mod.Runs.from_mask(zone)},
            ctypes={**cls.masks_v1.ctypes, "dec__plt_001": "no_cut"})

    def test_a_the_summary_names_the_entity_that_declares_the_constraint(self) -> None:
        """RF-015-13: la «Plataforma de carga» (PLT-002, tras la P1) no corta las 100 celdas de la
        zona declarada: el resumen dice 400 m², ``dec__plt_001`` y la entidad «Plataforma P1»; y, aparte,
        lo que su borde oeste no mueve por «Sin corte» (una restricción normal, con su nombre): entre
        las dos, todo lo que no mueve (y no hay aviso de máscaras sueltas)."""
        calculation = self.calculate(prep.request(), masks=self.double)
        self.assertEqual(calculation.entity.code, "PLT-002")
        held = only(calculation.summary, "des.entity_held")
        self.assertEqual((held.values["constraint"], held.values["other"], held.values["area"]),
                         ("dec__plt_001", self.P1, 400.0))
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


# ---------------------------------------------------------------------------------------------
# «Crear» (T13): lo que se registra
# ---------------------------------------------------------------------------------------------

PSF, EPR, PRP = (provenance.dataset_name(family, LOADING) for family in ("psf", "epr", "prp"))
"""Los nombres de los tres datos de la «Plataforma de carga»."""
EPR_TABLE = provenance.dataset_locator("epr", LOADING, "V01")
PRP_TABLE = provenance.dataset_locator("prp", LOADING, "V01")
ENTITY_COLUMNS = ("code", "name", "kind", "start_surface", "support_surface", "layer", "source_fid",
                  "geometry_sha256", "mode", "cells", "axis_principal", "bounds", "footprint",
                  "axis")
"""Las columnas de ``des_epr_``, en su orden."""
OUTSIDE_NOTICES = {"des.magnitude_cut", "des.magnitude_fill", "des.magnitude_no_reference",
                   "des.entity_quarry_order"}
"""Los avisos que dependen de algo que la operación no consume (la revisión congelada anterior y la
otra superficie de la cantera): no van al informe, que se reproduce sin el proyecto."""
LOADING_ROWS = list(range(55, 65))
"""Las filas de la huella de la «Plataforma de carga» (a mano: y de 270 a 290 m locales, de 2 m, desde
el norte de 400 m: 400 − 2·(fila + ½) de 271 a 289)."""
LOADING_COLUMNS = (55, 155)
"""Sus columnas (x de 110 a 310 m locales: de 2 m)."""


def written_tables(case: Any) -> list[str]:
    """Las tablas ``des_…`` del proyecto."""
    return [name for (name,) in case.query(
        "SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' ESCAPE '!' ORDER BY name")]


class CreateCase(OperationCase):
    """Lo de ``OperationCase`` más ayudantes **de clase** (las historias de «Crear» se hacen una vez
    en ``setUpClass``) y ``written``: lo que ``des`` y las operaciones han dejado en el proyecto."""

    @classmethod
    def query_of(cls, sql: str, *values: Any) -> list[Any]:
        with cls.project.read() as conn:
            return conn.execute(sql, values).fetchall()

    @classmethod
    def written(cls) -> dict[str, Any]:
        """Todo lo que podría escribir «Crear» (sin el contador de cambios: un deshacer lo deja)."""
        return {
            "operations": cls.query_of(
                "SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
            "datasets": cls.query_of(
                "SELECT uid, name, status, content_sha256 FROM gb_dataset ORDER BY fid"),
            "parameters": cls.query_of(
                "SELECT key, scope, scope_uid, value, unconfirmed FROM gb_parameter ORDER BY fid"),
            "io": cls.query_of(
                "SELECT operation_uid, direction, item_uid, role FROM gb_operation_io ORDER BY fid"),
            "figures": cls.query_of(
                "SELECT operation_uid, key, scope, value FROM gb_figure ORDER BY fid"),
            "tables": cls.query_of("SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' "
                                   "ESCAPE '!' ORDER BY name"),
            "files": sorted(path.name for path in (cls.root / "rasters").iterdir())}

    @staticmethod
    def settled(state: dict[str, Any]) -> dict[str, Any]:
        """``state`` sin los temporales (``….tmp-…``) de un cálculo abierto: lo que queda en el proyecto
        cuando ese cálculo se descarta o falla al crearse."""
        return {**state, "files": [name for name in state["files"] if ".tmp-" not in name]}

    @classmethod
    def layers(cls) -> dict[str, Any]:
        """Las capas de plataformas como están: su registro y todo el contenido de su tabla."""
        found: dict[str, Any] = {}
        for name in efx.LAYERS:
            (locator,) = cls.query_of("SELECT locator FROM gb_dataset WHERE name = ?", name)[0]
            found[name] = (cls.query_of("SELECT uid, status, content_sha256 FROM gb_dataset "
                                        "WHERE name = ?", name),
                           cls.query_of(f'SELECT * FROM "{locator}" ORDER BY fid'))
        return found

    @classmethod
    def calculate_in(cls, asked: Any, **options: Any) -> Any:
        """«Calcular» ``asked`` hasta el final (la ``Calculation``, que **no** se descarta al acabar)."""
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        return finish(steps.platform_run(cls.project, asked, **options))

    def grid_of(self, name: str) -> np.ndarray:
        """La rejilla del dato ``name`` de V01 tal como está en su fichero."""
        record = self.record(name, self.v1)
        return geotiff_reader.read_geotiff(self.root / record.locator).values

    def figures_of(self, uid: str) -> dict[tuple[str, str], float]:
        return {(key, scope): value for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def rows_of(self, table: str) -> dict[str, list[tuple[Any, str | None, str | None]]]:
        """Las filas de un informe largo por su cifra: ``quantity`` → lista de ``(valor, unidad, nota)``."""
        found: dict[str, list[Any]] = {}
        for quantity, value, unit, note in self.query(
                f'SELECT quantity, value, unit_code, note FROM "{table}" ORDER BY fid'):
            found.setdefault(quantity, []).append((value, unit, note))
        return found


class CreateTest(CreateCase):
    """RF-015-01, RF-015-02, RF-015-04: la «Plataforma de carga» (PLT-001, del terreno) calculada y creada
    y la «Plataforma de taller» (PLT-002) de la superficie de la primera, ambas una vez en V01."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    first_stored: ClassVar[Any]
    second_stored: ClassVar[Any]
    clean: ClassVar[dict[str, Any]]
    calculated: ClassVar[dict[str, Any]]
    layers_before: ClassVar[dict[str, Any]]
    layers_after: ClassVar[dict[str, Any]]
    counters: ClassVar[tuple[int, int, int]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.layers_before = cls.layers()
        cls.clean = cls.written()
        before = change_counter(cls.root)
        cls.clock.advance(minutes=1)
        cls.first = cls.calculate_in(prep.request())
        cls.calculated = cls.written()
        calculated = change_counter(cls.root)
        cls.clock.advance(minutes=1)
        cls.first_stored = cls.first.create()
        cls.counters = (before, calculated, change_counter(cls.root))
        cls.clock.advance(minutes=1)
        cls.second = cls.calculate_in(prep.request(WORKSHOP, start="entity:PLT-001"))
        cls.clock.advance(minutes=1)
        cls.second_stored = cls.second.create()
        cls.layers_after = cls.layers()

    # --- Una transacción --------------------------------------------------------------------

    def test_b_creating_is_one_write_transaction(self) -> None:
        """RF-015-02, RF-015-29: «Calcular» no sube el contador de cambios de la base y «Crear» lo sube
        **una** vez: la operación, los tres datos, las tablas, las cifras y los parámetros de la
        entidad entran en una sola transacción de escritura (el fichero de la superficie se pone en
        su sitio dentro de ella)."""
        before, calculated, created = self.counters
        self.assertEqual(calculated, before, "calcular no escribe")
        self.assertEqual(created, calculated + 1, "crear es una sola transacción")
        self.assertTrue(self.first.open is False)
        with self.assertRaises(RuntimeError):
            self.first.create()
        self.first.discard()  # lo creado no se toca
        self.assertEqual(self.written()["operations"][-2:],
                         [(self.first_stored.handle.uid, "des.platform", "done"),
                          (self.second_stored.handle.uid, "des.platform", "done")])

    # --- La operación y sus tres datos ---------------------------------------------------------

    def test_b_the_operation_with_its_inputs_settings_and_message(self) -> None:
        """RF-015-02, RF-015-04, RF-015-06: la operación ``des.platform`` de V01 (revisión abierta), hecha,
        con los ajustes de la entidad, la capa (``entity_layer``), la superficie de partida
        (``surface``) y las máscaras como entradas y los parámetros que lee; el mensaje es el del
        resumen de lo calculado."""
        uid = self.first_stored.handle.uid
        ((op_type, status, settings, message, revision),) = self.query(
            "SELECT op_type, status, settings, message, revision_uid FROM gb_operation "
            "WHERE uid = ?", uid)
        self.assertEqual((op_type, status), ("des.platform", "done"))
        self.assertEqual(json.loads(settings), provenance.platform_settings(prep.request(), "PLT-001"))
        self.assertEqual(message, self.first.outcome.message)
        self.assertEqual(self.query("SELECT version_uid, state FROM gb_revision WHERE uid = ?",
                                    revision), [(self.v1.uid, "open")])
        inputs = [(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "ORDER BY io.fid", uid)]
        self.assertEqual(inputs[:2], [(efx.AXES_LAYER, "entity_layer"), (START, "surface")])
        self.assertTrue(all(role.startswith("masks_") for _name, role in inputs[2:]), inputs)
        self.assertNotIn("supported_on", [role for _name, role in inputs])
        params = [key for (key,) in self.query(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ? ORDER BY fid", uid)]
        self.assertEqual(sorted(params), sorted(provenance.platform_params("PLT-001", prep.request())))
        self.assertEqual([record.name for record in self.first_stored.records], [PSF, EPR, PRP])

    def test_b_the_three_data_with_their_roles_and_hashes(self) -> None:
        """RF-015-01, RF-015-02: ``des_psf_`` (``entity_surface``), ``des_epr_`` (``entity``) y
        ``des_prp_`` (``entity_report``) son datos vivos de V01 escritos por la operación, con el hash
        que se preparó al calcular; la superficie está en su sitio sin temporales y las dos tablas, en el
        proyecto."""
        uid = self.first_stored.handle.uid
        outputs = {name: (role, status, sha) for name, role, status, sha in self.query(
            "SELECT d.name, io.role, d.status, io.content_sha256 FROM gb_operation_io AS io "
            "JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? "
            "AND io.direction = 'out'", uid)}
        prepared = {spec.name: spec.content.content_sha256 for spec in self.first.specs}
        self.assertEqual({name: role for name, (role, _status, _sha) in outputs.items()},
                         {PSF: "entity_surface", EPR: "entity", PRP: "entity_report"})
        self.assertEqual({name: sha for name, (_role, _status, sha) in outputs.items()}, prepared)
        self.assertEqual({status for _role, status, _sha in outputs.values()}, {"current"})
        self.assertEqual(self.record(PSF, self.v1).locator,
                         provenance.dataset_locator("psf", LOADING, "V01"))
        stems = {path for path in self.written()["files"]} - set(self.clean["files"])
        self.assertEqual(stems, {provenance.dataset_locator("psf", LOADING, "V01").rsplit("/", 1)[-1],
                                 provenance.dataset_locator("psf", WORKSHOP, "V01").rsplit("/", 1)[-1]})
        self.assertEqual([name for name in written_tables(self) if name in (EPR_TABLE, PRP_TABLE)],
                         sorted((EPR_TABLE, PRP_TABLE)))
        start = qfx.terrain(GRID)
        expected = start.copy()
        expected[self.first.outcome.footprint.window] = self.first.outcome.result
        np.testing.assert_array_equal(self.grid_of(PSF), expected)

    # --- La tabla de la entidad -----------------------------------------------------------------

    def test_b_the_table_of_the_entity_has_the_footprint_the_axis_and_the_attributes(self) -> None:
        """RF-015-01: ``des_epr_`` lleva **una** fila con el código, el nombre, el tipo, la partida, la capa
        y el ``fid`` de origen, el hash de la geometría de origen, el modo, las celdas, la ventana, la huella
        en tramos de fila ``(fila, col0, col1)`` (a mano: 10 filas de 55 a 155) y los vértices del eje
        (absolutos, float64, exactos, los de la capa)."""
        found = self.query(f'SELECT {", ".join(ENTITY_COLUMNS)} FROM "{EPR_TABLE}"')
        self.assertEqual(len(found), 1)
        row = dict(zip(ENTITY_COLUMNS, found[0], strict=True))
        self.assertEqual((row["code"], row["name"], row["kind"]), ("PLT-001", LOADING, "platform"))
        self.assertEqual((row["start_surface"], row["support_surface"]), (START, None))
        self.assertEqual((row["layer"], row["source_fid"], row["mode"], row["cells"],
                          row["axis_principal"]), (efx.AXES_LAYER, efx.axis_fid(LOADING), "cut", 1000, 0))
        runs = json.loads(row["footprint"])
        self.assertEqual(runs, [[r, *LOADING_COLUMNS] for r in LOADING_ROWS])
        footprint = self.first.outcome.footprint
        window = footprint.window
        self.assertEqual(json.loads(row["bounds"]),
                         [window[0].start, window[0].stop, window[1].start, window[1].stop])
        mask = entity_store.runs_mask(runs, GRID.shape)
        self.assertEqual(int(mask.sum()), 1000)
        np.testing.assert_array_equal(mask[window], footprint.cells)
        axis = np.array(json.loads(row["axis"]))
        layer_axis = self.read_layer(efx.AXES_LAYER).parts[efx.axis_fid(LOADING) - 1][0][0]
        np.testing.assert_array_equal(axis, np.asarray(layer_axis)[:, :2])
        self.assertEqual(axis.dtype, np.float64)
        origin = platform.PlatformGeometry(
            "line", self.read_layer(efx.AXES_LAYER).parts[efx.axis_fid(LOADING) - 1])
        self.assertEqual(row["geometry_sha256"], entity_store.geometry_sha256(origin))
        self.assertRegex(row["geometry_sha256"], r"^[0-9a-f]{64}$")

    def test_b_the_second_platform_table_names_its_start_as_a_surface(self) -> None:
        """RF-015-04: la fila de la «Plataforma de taller» guarda su partida resuelta (el dato de la
        superficie de la primera, no ``entity:PLT-001``) y su código; el hash de su geometría no es el
        de la otra."""
        table = provenance.dataset_locator("epr", WORKSHOP, "V01")
        ((code, start, sha),) = self.query(
            f'SELECT code, start_surface, geometry_sha256 FROM "{table}"')
        (other_sha,) = self.query(f'SELECT geometry_sha256 FROM "{EPR_TABLE}"')[0]
        self.assertEqual((code, start), ("PLT-002", PSF))
        self.assertNotEqual(sha, other_sha)

    # --- El informe -----------------------------------------------------------------------------

    def test_b_the_report_has_the_profile_the_counter_slopes_and_the_edge(self) -> None:
        """RF-015-02, RF-015-13, RF-015-23, RF-015-24: ``des_prp_`` en formato largo lleva las cifras de la
        huella y del borde, una fila por tramo del perfil longitudinal, las contrapendientes (ninguna en
        esta plataforma), las pendientes del salto creado y los avisos con su código y sus valores; no lleva
        los que dependen de lo que la operación no consume (la revisión anterior, la otra superficie de la
        cantera), ni ningún valor que no sea finito."""
        rows = self.rows_of(PRP_TABLE)
        outcome = self.first.outcome
        self.assertEqual(rows["area_m2"], [(4000.0, "m2", None)])
        self.assertEqual(rows["cut_m3"][0][:2], (outcome.applied.cut_m3, "m3"))
        self.assertEqual(rows["edge_cut_m3"][0][:2], (outcome.edge.cut_m3, "m3"))
        self.assertEqual(rows["edge_fill_m3"][0][:2], (outcome.edge.fill_m3, "m3"))
        self.assertEqual(rows["axis_m"][0][:2], (outcome.footprint.axis.length_m, "m"))
        self.assertEqual(rows["start_level_m"][0][0], 250.0)
        self.assertEqual(rows["gradient_pct"][0][:2], (1.0, "%"))
        profile = outcome.profile
        shown = [json.loads(note) for _value, _unit, note in rows["profile"]]
        self.assertEqual(len(shown), profile.section.size)
        self.assertEqual([item["section"] for item in shown], profile.section.tolist())
        self.assertEqual([value for value, _unit, _note in rows["profile"]], profile.level_m.tolist())
        self.assertEqual([item["chainage_m"] for item in shown], profile.chainage_m.tolist())
        self.assertNotIn("counter_slope", rows)
        self.assertEqual(rows["counter_sections"][0][0], 0.0)
        self.assertEqual(rows["counter_tolerance_m"][0][:2], (0.1, "m"))
        found = [json.loads(note)["code"] for quantity in ("warning", "note")
                 for _value, _unit, note in rows.get(quantity, [])]
        expected = [notice.code for notice in outcome.notices if notice.code not in OUTSIDE_NOTICES]
        self.assertEqual(sorted(found), sorted(expected))
        self.assertTrue(set(found).isdisjoint(OUTSIDE_NOTICES))
        self.assertTrue(set(codes(self.first.summary)) & OUTSIDE_NOTICES, "el resumen sí los lleva")
        for values in rows.values():
            for value, _unit, _note in values:
                self.assertTrue(value is None or math.isfinite(value))

    # --- Las cifras ------------------------------------------------------------------------------

    def test_b_the_figures_have_the_scope_of_their_entity(self) -> None:
        """RF-015-02, RF-008-30: las cifras de cada plataforma (CALCULADO, con su unidad) se registran con
        el ámbito de su entidad (el nombre y el código): las de la otra con las mismas claves no las pisan
        (a mano: 4.000 m² la primera)."""
        first = self.figures_of(self.first_stored.handle.uid)
        second = self.figures_of(self.second_stored.handle.uid)
        scope = figures_mod.scope_json(provenance.entity_figure_scope(LOADING, "PLT-001"))
        other = figures_mod.scope_json(provenance.entity_figure_scope(WORKSHOP, "PLT-002"))
        self.assertEqual(first, {(figure.key, scope): figure.value for figure in self.first.figures})
        self.assertEqual(second, {(figure.key, other): figure.value for figure in self.second.figures})
        self.assertEqual(first[("des.plat_area_m2", scope)], 4000.0)
        self.assertGreater(len(first), 9)
        self.assertTrue(set(key for key, _scope in first) & set(key for key, _scope in second))
        both = self.query("SELECT key, count(*), count(DISTINCT scope) FROM gb_figure "
                          "WHERE key = 'des.plat_area_m2' GROUP BY key")
        self.assertEqual(both, [("des.plat_area_m2", 2, 2)])
        kinds = {kind for (kind,) in self.query(
            "SELECT DISTINCT kind FROM gb_figure WHERE operation_uid IN (?, ?)",
            self.first_stored.handle.uid, self.second_stored.handle.uid)}
        self.assertEqual(kinds, {"CALCULADO"})

    # --- Los parámetros de la entidad ------------------------------------------------------------

    def test_b_the_parameters_of_the_entity_are_version_rows_with_their_origin(self) -> None:
        """RF-015-01, RF-008-01, RF-009-29: «Crear» escribe cada parámetro de la entidad como una fila de la
        **versión** (ADOPTADO, de la persona que tiene abierto el proyecto, con su motivo) con su origen:
        «capa X, campo Y, entidad Z» los copiados de la capa; el diálogo, lo que eligió la persona; el valor
        por defecto, la procedencia de su definición. El registro ve la entidad al día con su operación.

        **Limitación conocida** (trampa de la T04, ``docs/trampas.md`` §6): ``begin_operation`` deja en el
        proyecto una fila «sin confirmar» por clave que lee (``ensure_default``; no hacen entidad ni se
        leen: la de la versión manda); solo de las que lee, no las del nombre, lo que declara o la
        pendiente máxima."""
        store = core_params.ParameterStore(self.project)
        decider = self.project.session.user_host
        for row in self.first.entity.rows:
            with self.subTest(key=row.key):
                record = store.get(row.key, version=self.v1.uid)
                self.assertIsNotNone(record)
                self.assertEqual((record.scope, record.scope_uid), ("version", self.v1.uid))
                self.assertEqual((record.value, str(record.kind), record.decided_by),
                                 (row.value, "ADOPTADO", decider))
                self.assertEqual((record.source, str(record.source_kind)),
                                 (row.source, row.source_kind))
                self.assertFalse(record.unconfirmed)
                self.assertIsNotNone(record.decided_at)
        origin = {row.param.value: row.source for row in self.first.entity.rows}
        for param, field in (("width_m", "ancho"), ("start_level_m", "cota_inicial"),
                             ("gradient_pct", "pendiente")):
            self.assertEqual(origin[param],
                             f"capa «{efx.AXES_LAYER}», campo «{field}», entidad «{LOADING}»")
        versioned = {key for (key,) in self.query(
            "SELECT key FROM gb_parameter WHERE key LIKE 'des.platform.plt_001.%' "
            "AND scope = 'version'")}
        self.assertEqual(versioned, {row.key for row in self.first.entity.rows})
        read = {item for item in provenance.platform_params("PLT-001", prep.request())
                if item.startswith("des.platform.")}
        placeholders = {key: unconfirmed for key, unconfirmed in self.query(
            "SELECT key, unconfirmed FROM gb_parameter WHERE key LIKE 'des.platform.plt_001.%' "
            "AND scope = 'project'")}
        self.assertEqual(set(placeholders), read)
        self.assertTrue(all(placeholders.values()), "sin confirmar, no de la entidad")
        self.assertNotIn(design_params.entity_key("PLT-001", "name"), placeholders)
        self.assertNotIn(design_params.entity_key("PLT-001", "protect"), placeholders)
        by_key = {item.key: (item.scope, item.value) for item in self.first_stored.handle.params}
        for row in self.first.entity.rows:
            if row.key in read:
                self.assertEqual(by_key[row.key], ("version", row.value), row.key)
        registry = entities_module.registry(self.project, self.v1.uid)
        entry = registry.get("PLT-001")
        self.assertEqual((entry.record.name, str(entry.record.state)), (LOADING, "current"))
        self.assertEqual(entry.operation_uid, self.first_stored.handle.uid)

    # --- La capa de origen ------------------------------------------------------------------------

    def test_b_the_source_layers_are_not_modified(self) -> None:
        """RF-015-01 (principio 7): tras calcular y crear dos plataformas, las capas de plataformas (ejes y
        polígonos) tienen el mismo registro (uid, estado y hash de contenido) y el mismo contenido que
        antes, y las operaciones las anotan como entradas con ese hash."""
        self.assertEqual(self.layers_after, self.layers_before)
        sha = self.layers_before[efx.AXES_LAYER][0][0][2]
        io = self.query("SELECT content_sha256 FROM gb_operation_io WHERE operation_uid = ? "
                        "AND role = 'entity_layer'", self.first_stored.handle.uid)
        self.assertEqual(io, [(sha,)])

    # --- La cadena ----------------------------------------------------------------------------------

    def test_b_a_chained_platform_consumes_the_surface_of_the_first(self) -> None:
        """RF-015-04, RF-015-01: la «Plataforma de taller», con partida ``entity:PLT-001``, consume la
        superficie de la primera (``des_psf_…``, papel ``surface``) y no el terreno; su resultado es igual a
        esa superficie fuera de las celdas que mueve (y por debajo de ella), y la última de la cadena es la
        suya."""
        uid = self.second_stored.handle.uid
        inputs = {(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid)}
        self.assertIn((PSF, "surface"), inputs)
        self.assertNotIn((START, "surface"), inputs)
        self.assertEqual(self.second.entity.start_surface, PSF)
        value = core_params.ParameterStore(self.project).get(
            design_params.entity_key("PLT-002", "start"), version=self.v1.uid)
        self.assertEqual(value.value, "entity:PLT-001")
        first, second = self.grid_of(PSF), self.grid_of(provenance.dataset_name("psf", WORKSHOP))
        mine = self.second.outcome.footprint.window
        theirs = self.first.outcome.footprint.window
        self.assertFalse(mine[0].start < theirs[0].stop and theirs[0].start < mine[0].stop
                         and mine[1].start < theirs[1].stop and theirs[1].start < mine[1].stop,
                         "las ventanas de trabajo no se cruzan")
        untouched = np.ones(GRID.shape, dtype=bool)
        untouched[mine] = False
        np.testing.assert_array_equal(second[untouched], first[untouched])
        with np.errstate(invalid="ignore"):
            self.assertTrue((second <= first).all())
            self.assertTrue((second < first).any())
        records = entities_module.registry(self.project, self.v1.uid).records
        self.assertEqual([item.code for item in entities_module.chain_tails(records)], ["PLT-002"])
        self.assertEqual([str(entry.record.state) for entry in
                          entities_module.registry(self.project, self.v1.uid)],
                         ["current", "current"])


class ChainStaleTest(CreateCase):
    """RF-015-04, RF-015-16, RF-008-24: cambiar un parámetro de la primera plataforma deja obsoleta la
    primera y, en cascada, la que parte de su superficie, cada una con su causa."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.first = cls.calculate_in(prep.request()).create()
        cls.clock.advance(minutes=1)
        cls.second = cls.calculate_in(prep.request(WORKSHOP, start="entity:PLT-001")).create()

    def test_b_changing_a_parameter_of_the_first_stales_it_and_the_next_with_the_cause(self) -> None:
        """RF-015-04, RF-015-16: antes de cambiar nada ninguna está obsoleta; con el alcance de la primera
        cambiado (parámetro de su fila de la versión), la primera queda obsoleta por ese parámetro y la
        segunda, que consumió su superficie, también (``parameter_changed``, en cascada); el registro de las
        entidades las da como obsoletas, con la causa, y «Recalcular lo obsoleto» tiene dos operaciones."""
        reach = design_params.entity_key("PLT-001", "reach_m")
        first, second = self.first.handle.uid, self.second.handle.uid
        self.assertEqual((self.stale_causes(first), self.stale_causes(second)), (set(), set()))
        self.assertEqual(self.recompute_plan(), [])
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, reach, value=25.0, version=self.v1.uid, reason="Prueba de la T13")
        self.assertEqual(self.stale_causes(first), {("parameter_changed", reach)})
        self.assertIn(("parameter_changed", reach), self.stale_causes(second))
        own = design_params.entity_key("PLT-002", "reach_m")
        self.assertNotIn(("parameter_changed", own), self.stale_causes(second))
        registry = entities_module.registry(self.project, self.v1.uid)
        self.assertEqual([str(entry.record.state) for entry in registry], ["stale", "stale"])
        for entry in registry:
            self.assertEqual({cause.kind for cause in entry.causes}, {"parameter_changed"})
        self.assertEqual(len(self.recompute_plan()), 2)


# ---------------------------------------------------------------------------------------------
# «Crear»: todo o nada
# ---------------------------------------------------------------------------------------------


class AtomicCreateTest(CreateCase):
    """RF-015-02, RF-015-29: si algo falla a mitad de «Crear», no queda nada: ni operación, ni datos, ni
    tablas, ni cifras, ni parámetros, ni la superficie en su sitio, ni el temporal."""

    def test_b_a_failure_midway_leaves_nothing(self) -> None:
        """Un fallo simulado al abrir la operación (con los parámetros de la entidad ya escritos en la
        transacción), al escribir las tablas (con la superficie ya en su sitio) y al completar (con todo
        hecho menos confirmar) deja el proyecto como antes de calcular, el error sigue y la cuenta queda
        cerrada; calculada y creada otra vez sin el fallo, se registra con el mismo código."""
        clean = self.written()
        failures = (
            ("abrir la operación", mock.patch.object(design_store.OperationStart, "begin",
                                                     side_effect=RuntimeError("fallo de prueba"))),
            ("escribir las tablas", mock.patch.object(design_store.DesignWriter, "_write_table",
                                                      side_effect=RuntimeError("fallo de prueba"))),
            ("completar", mock.patch.object(operations.OperationHandle, "complete",
                                            side_effect=RuntimeError("fallo de prueba"))))
        for step, patched in failures:
            with self.subTest(step=step):
                calculation = self.calculate_in(prep.request())
                self.assertNotEqual(self.written()["files"], clean["files"], "el temporal")
                with patched:
                    with self.assertRaises(RuntimeError) as caught:
                        calculation.create()
                self.assertEqual(str(caught.exception), "fallo de prueba")
                self.assertEqual(self.written(), clean)
                self.assertFalse(calculation.open)
        self.clock.advance(minutes=1)
        stored = self.calculate_in(prep.request()).create()
        entry = entities_module.registry(self.project, self.v1.uid).get("PLT-001")
        self.assertEqual(entry.operation_uid, stored.handle.uid)


class ChangedMeanwhileTest(CreateCase):
    """RF-015-02, RF-013-04 (``des.input_changed``): lo que cambia entre «Calcular» y «Crear» (nada se
    registra, así que cada prueba puede calcular la misma plataforma)."""

    def test_b_an_input_that_changed_meanwhile_is_not_registered(self) -> None:
        """RF-015-02, RF-013-04 (``des.input_changed``): si la superficie de partida cambia entre «Calcular» y
        «Crear», el resultado ya no le corresponde: se rechaza **al abrir la operación, ya con los
        parámetros de la entidad escritos**, y todo se deshace."""
        clean = self.written()
        calculation = self.calculate_in(prep.request())
        shifted = gis.Raster(GRID, qfx.terrain(GRID) + 1.0, efx.CRS, efx.VERTICAL)
        self.clock.advance(minutes=1)
        res_fixtures.write_grids(self.project, [(START.removeprefix("gis_dtm_"), shifted)],
                                 message="La partida cambia mientras se calcula")
        changed = self.written()
        self.assertNotEqual(changed["datasets"], clean["datasets"], "la partida cambió")
        self.assertEqual(changed["parameters"], clean["parameters"])
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(START, caught.exception.text)
        self.assertEqual(self.written(), self.settled(changed))
        self.assertFalse(calculation.open)

    def test_b_a_parameter_that_changed_meanwhile_is_not_registered(self) -> None:
        """RF-015-02 (``des.input_changed``): lo mismo con un parámetro del proyecto que lee el cálculo
        (el umbral de aviso de magnitud): se rechaza antes de escribir nada y el temporal se borra."""
        clean = self.written()
        calculation = self.calculate_in(prep.request())
        self.clock.advance(minutes=1)
        key = design_params.WARNING_RATIO
        with self.project.write_transaction() as conn:
            store = core_params.ParameterStore(self.project)
            store.ensure_default(conn, key, geoblender_version="0.1.0")
            store.change(conn, key, value=3.0, reason="Prueba de la T13", source="Prueba",
                         source_kind="person", decided_by=prep.USER)
        changed = self.written()
        self.assertNotEqual(changed["parameters"], clean["parameters"], "el parámetro cambió")
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(key, caught.exception.text)
        self.assertEqual(self.written(), self.settled(changed))
        self.assertFalse(calculation.open)


class CounterSlopeCreateTest(CreateCase):
    """RF-015-23: una plataforma con contrapendiente que pasa de la tolerancia no se crea sin la
    confirmación expresa de quien la pide."""

    def test_b_a_counter_slope_is_not_created_without_confirmation(self) -> None:
        """La «Plataforma de la torre» (con una contrapendiente: la torre de la zona intocable) pide
        confirmación: ``create()`` se rechaza (``des.platform_counter_unconfirmed``) **antes de escribir
        nada** y deja la cuenta abierta; confirmada en la cuenta, se crea, con su contrapendiente en el
        informe y su aviso."""
        calculation = self.calculate_in(prep.request(TOWER))
        self.addCleanup(calculation.discard)
        self.assertTrue(calculation.needs_confirmation)
        before = self.written()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.written(), before)
        self.assertTrue(calculation.open)
        with self.assertRaises(messages.DesignError) as direct:  # la función pública, por sí sola
            entity_store.create_platform(self.project, calculation._writer, calculation.entity,
                                         calculation.outcome)
        self.assertEqual(direct.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.written(), before)
        calculation.confirm_counterslope()
        self.clock.advance(minutes=1)
        stored = calculation.create()
        self.assertEqual(stored.handle.op_type, "des.platform")
        table = provenance.dataset_locator("prp", TOWER, "V01")
        rows = self.rows_of(table)
        profile = calculation.outcome.profile
        self.assertEqual(len(rows["counter_slope"]), profile.counter_sections)
        self.assertGreater(len(rows["counter_slope"]), 0)
        worst = max(rows["counter_slope"], key=lambda item: item[0])
        self.assertEqual(worst[0], float(profile.rise_m.max()))
        self.assertEqual(rows["counter_sections"][0][0], float(profile.counter_sections))
        found = [json.loads(note)["code"] for _value, _unit, note in rows["warning"]]
        self.assertIn("des.platform_counter_slope", found)


class CounterSlopeAskedTest(CreateCase):
    """RF-015-23: lo mismo con la confirmación pedida desde el principio."""

    def test_b_a_counter_slope_asked_confirmed_is_created(self) -> None:
        """Pedida ya confirmada (``confirm_counterslope=True``), se crea sin más."""
        calculation = self.calculate_in(prep.request(TOWER), confirm_counterslope=True)
        self.assertFalse(calculation.needs_confirmation)
        self.clock.advance(minutes=1)
        self.assertEqual(calculation.create().handle.op_type, "des.platform")


# ---------------------------------------------------------------------------------------------
# «Crear»: una entidad que ya está en la versión y el gancho de las dependencias
# ---------------------------------------------------------------------------------------------


class ExistingEntityTest(CreateCase):
    """RF-015-01 (RF-015-18): una entidad que ya está en la versión (sus parámetros, sin calcular: lo que
    deja «Traer las entidades de…») se calcula con su código y «Crear» registra su operación **sin escribir
    otra vez sus parámetros**."""

    def test_b_an_entity_already_in_the_version_is_not_written_again(self) -> None:
        asked = prep.request()
        prepared = self.units(asked)
        self.clock.advance(minutes=1)
        entity_store.set_entity_params(self.project, prepared.rows, version=self.v1.uid,
                                       decided_by=prep.USER)
        rows = self.query("SELECT uid, key, value, decided_by, rev FROM gb_parameter "
                          "WHERE scope = 'version' ORDER BY fid")
        self.clock.advance(minutes=1)
        calculation = self.calculate_in(asked, code="PLT-001")
        self.assertTrue(calculation.entity.existing)
        self.assertFalse(self.calculate(prep.request(WORKSHOP, start=prep.HOLE_DATASET))
                         .entity.existing)
        stored = calculation.create()
        self.assertEqual(self.query("SELECT uid, key, value, decided_by, rev FROM gb_parameter "
                                    "WHERE scope = 'version' AND key LIKE 'des.platform.plt_001.%' "
                                    "ORDER BY fid"), rows)
        entry = entities_module.registry(self.project, self.v1.uid).get("PLT-001")
        self.assertEqual((str(entry.record.state), entry.operation_uid),
                         ("current", stored.handle.uid))
        scopes = {item.scope for item in stored.handle.params
                  if item.key.startswith("des.platform.")}
        self.assertEqual(scopes, {"version"})


class RacedEntityTest(CreateCase):
    """RF-015-01: dos sesiones calcularon la misma entidad nueva (el mismo código) y una creó antes."""

    def test_b_a_new_entity_whose_rows_appeared_meanwhile_is_refused(self) -> None:
        """Si entre «Calcular» y «Crear» alguien dio de alta una entidad con el mismo código (sus
        parámetros), «Crear» no pisa ni se queda con las suyas: ``core.param_exists``, nada se escribe y
        la cuenta queda cerrada."""
        calculation = self.calculate_in(prep.request())
        self.assertEqual(calculation.entity.code, "PLT-001")
        other = self.units(prep.request(WORKSHOP, start=prep.HOLE_DATASET), code="PLT-001")
        self.clock.advance(minutes=1)
        entity_store.set_entity_params(self.project, other.rows, version=self.v1.uid,
                                       decided_by=prep.USER)
        expected = self.settled(self.written())
        with self.assertRaises(core_params.ParamError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "core.param_exists")
        self.assertEqual(self.written(), expected)
        self.assertFalse(calculation.open)


class SupportsHookTest(CreateCase):
    """RF-015-15 (T23): el gancho de las dependencias queda preparado y vacío: hoy no añade ninguna
    entrada ``supported_on``; lo que devuelva se añade como entrada de la operación al crearla."""

    def test_b_the_hook_is_empty_and_what_it_returns_is_an_input_of_the_operation(self) -> None:
        calculation = self.calculate_in(prep.request())
        self.assertEqual(entity_store.detected_supports(
            self.project, calculation.entity, calculation.outcome), ())
        self.clock.advance(minutes=1)
        with mock.patch.object(entity_store, "detected_supports",
                               return_value=(prep.HOLE_DATASET,)):
            stored = calculation.create()
        inputs = self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.role = 'supported_on'",
            stored.handle.uid)
        self.assertEqual(inputs, [(prep.HOLE_DATASET, "supported_on")])


# ---------------------------------------------------------------------------------------------
# Las funciones puras de la tabla de la entidad
# ---------------------------------------------------------------------------------------------


class EntityTableTest(unittest.TestCase):
    """RF-015-01: la huella en tramos de fila, su inversa y el hash de la geometría de origen."""

    def test_b_the_footprint_in_runs_and_back(self) -> None:
        """La huella de una ventana (con un hueco, una celda suelta y los bordes de la ventana) son sus
        tramos ``(fila, col0, col1)`` **absolutos** de la rejilla, de norte a sur y de oeste a este, con
        ``col1`` excluida; ``runs_mask`` los devuelve a la máscara de la rejilla entera."""
        mask = np.array([[1, 1, 0, 1, 1],
                         [0, 0, 0, 0, 0],
                         [1, 0, 0, 0, 1],
                         [0, 1, 1, 1, 0]], dtype=bool)
        window = (slice(3, 7), slice(2, 7))
        found = entity_store.footprint_runs(mask, window)
        self.assertEqual(found, [(3, 2, 4), (3, 5, 7), (5, 2, 3), (5, 6, 7), (6, 3, 6)])
        whole = entity_store.runs_mask(found, (10, 10))
        np.testing.assert_array_equal(whole[window], mask)
        self.assertEqual(int(whole.sum()), int(mask.sum()))
        self.assertEqual(entity_store.footprint_runs(np.zeros((2, 2), dtype=bool),
                                                     (slice(0, 2), slice(0, 2))), [])
        self.assertFalse(entity_store.runs_mask([], (3, 3)).any())

    def test_b_a_run_outside_the_grid_is_a_program_error(self) -> None:
        for runs in ([(0, 3, 3)], [(0, 4, 2)], [(3, 0, 1)], [(0, 0, 4)], [(-1, 0, 1)]):
            with self.subTest(runs=runs):
                with self.assertRaises(ValueError):
                    entity_store.runs_mask(runs, (3, 3))

    def test_b_the_geometry_hash_follows_the_geometry_to_the_last_bit(self) -> None:
        """El hash de la geometría de origen es el mismo para la misma geometría y cambia con el tipo, con
        un vértice movido 10⁻⁹ m (la resolución de un float64 a 4,4 Mm de norte), con otra parte y con el
        eje enlazado de un polígono."""
        path = np.array([[725_100.0, 4_400_100.5], [725_200.0, 4_400_100.5]])
        base = platform.PlatformGeometry("line", ((path,),))
        again = platform.PlatformGeometry("line", ((path.copy(),),))
        self.assertEqual(entity_store.geometry_sha256(base), entity_store.geometry_sha256(again))
        self.assertRegex(entity_store.geometry_sha256(base), r"^[0-9a-f]{64}$")
        moved = path.copy()
        moved[1, 1] = np.nextafter(moved[1, 1], np.inf)
        self.assertNotEqual(entity_store.geometry_sha256(platform.PlatformGeometry("line", ((moved,),))),
                            entity_store.geometry_sha256(base))
        ring = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]])
        polygon = platform.PlatformGeometry("polygon", ((ring,),))
        self.assertNotEqual(entity_store.geometry_sha256(polygon),
                            entity_store.geometry_sha256(platform.PlatformGeometry("line", ((ring,),))))
        linked = platform.PlatformGeometry("polygon", ((ring,),), axis_parts=((path,),))
        self.assertNotEqual(entity_store.geometry_sha256(linked), entity_store.geometry_sha256(polygon))
        two = platform.PlatformGeometry("line", ((path,), (path,)))
        self.assertNotEqual(entity_store.geometry_sha256(two), entity_store.geometry_sha256(base))

    def test_b_the_columns_of_the_tables_of_an_entity(self) -> None:
        """RF-015-01: el escritor conoce las tablas de la plataforma: ``des_epr_`` con las columnas de
        la entidad y ``des_prp_`` con las del informe largo."""
        found = design_store.columns_of("des.platform", "epr")
        self.assertEqual(tuple(column.name for column in found), ENTITY_COLUMNS)
        self.assertEqual(found, design_store.ENTITY_COLUMNS)
        self.assertEqual(design_store.columns_of("des.platform", "prp"), design_store.REPORT_COLUMNS)
        with self.assertRaises(KeyError):
            design_store.columns_of("des.platform", "psf")


# ---------------------------------------------------------------------------------------------
# Recalcular y reproducir (T14; casos (c), (d) y (e))
# ---------------------------------------------------------------------------------------------

PSF2 = provenance.dataset_name("psf", WORKSHOP)
"""El nombre de la superficie de la «Plataforma de taller»."""


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``des.platform``: lleva los pasos hasta el
    final."""
    handle, work = design_store.recompute_run(request)
    finish(work)
    return handle


def real_definitions() -> tuple[Any, ...]:
    """Los tipos de las entidades con las funciones **reales** de la plataforma (recalcular y reproducir),
    las de los otros dos tipos sin llamar y las cifras, como los registra ``bl``."""
    types = prep.ENTITY_TYPES
    return (*provenance.entity_operation_defs(
        {kind: recompute_function if kind == provenance.PLATFORM else prep.never for kind in types},
        {kind: design_reproduce.reproduce_platform if kind == provenance.PLATFORM else prep.never
         for kind in types}), *provenance.ENTITY_FIGURES)


class RecomputeCase(CreateCase):
    """Lo de ``CreateCase`` con los tipos de las entidades registrados con sus funciones reales y los
    ayudantes de las historias de recalcular y reproducir."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return real_definitions()

    @classmethod
    def made(cls, asked: Any) -> Any:
        """«Calcula» y «crea» ``asked`` en V01 (un minuto después de lo anterior): su ``Stored``."""
        cls.clock.advance(minutes=1)
        return cls.calculate_in(asked).create()

    def current(self, code: str) -> str:
        """El uid de la operación vigente de la entidad ``code`` de V01 (el registro de las entidades)."""
        entry = entities_module.registry(self.project, self.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def request_for(self, uid: str) -> Any:
        """Lo que recibe ``bl`` para recalcular la operación ``uid``: sus ajustes y su versión."""
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, provenance.PLATFORM,
                                              json.loads(settings), (), (), version=self.v1.uid)

    @classmethod
    def change(cls, key: str, value: object) -> None:
        """Cambia el parámetro de la versión ``key`` (un minuto después)."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).change(
                conn, key, value=value, version=cls.v1.uid, reason="Prueba de la T14")

    def hashes_of(self, uid: str) -> dict[str, str]:
        """El hash que anotó la operación ``uid`` de cada dato que escribió (por su nombre)."""
        return dict(self.query(
            "SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid))

    def version_rows(self) -> list[tuple[Any, ...]]:
        """Los parámetros propios de las versiones, con su historial."""
        return self.query("SELECT key, value, rev, decided_by FROM gb_parameter "
                          "WHERE scope = 'version' ORDER BY fid")

    def plan_units(self) -> list[tuple[str, ...]]:
        """Las operaciones (su uid) de cada unidad del plan de «Recalcular lo obsoleto», en su orden."""
        graph = import_geoblender("core.provenance.graph")
        with self.project.read() as conn:
            return [tuple(unit.operations) for unit in
                    recompute_mod.plan_recompute(graph.load_graph(conn)).units]


class RecomputeTest(RecomputeCase):
    """RF-015-02, RF-015-04, RF-015-16, RF-008-24, RF-008-26: P1 (la «Plataforma de carga», del terreno) y
    P2 (la «Plataforma de taller», de la superficie de P1) creadas en V01 y recalculadas, por el orden de
    los nombres de las pruebas: (c1) sin cambiar nada, (c2) con un cambio que no toca la superficie y (e1)
    con uno que sí la toca."""

    first: ClassVar[Any]
    second: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))

    # --- (c) Recalcular -----------------------------------------------------------------------

    def test_c1_recomputing_repeats_the_platform_with_what_it_was(self) -> None:
        """RF-015-02, RF-008-26: recalcular P1 sin que nada cambie da una operación **nueva** que sustituye a
        la anterior (queda como historia) con los mismos ajustes, entradas, cifras y datos (el mismo hash de
        la superficie, de la tabla y del informe, en su mismo sitio); no escribe los parámetros de la entidad
        (ya están en la versión); la entidad sigue al día con la operación nueva y P2, que consumió su
        superficie, no queda obsoleta."""
        old = self.first.handle.uid
        rows, figures, hashes = self.version_rows(), self.figures_of(old), self.hashes_of(old)
        inputs = self.query("SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? "
                            "AND direction = 'in' ORDER BY fid", old)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", old)
        self.assertEqual(sorted(hashes), sorted((PSF, EPR, PRP)))
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        stored = finish(work)
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query("SELECT op_type, status, supersedes_uid FROM gb_operation "
                                    "WHERE uid = ?", handle.uid),
                         [("des.platform", "done", old)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old),
                         [(handle.uid,)])
        self.assertEqual(self.hashes_of(handle.uid), hashes)
        self.assertEqual(self.figures_of(handle.uid), figures)
        self.assertEqual(self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid),
                         [(settings,)])
        self.assertEqual(self.query("SELECT item_uid, role FROM gb_operation_io WHERE "
                                    "operation_uid = ? AND direction = 'in' ORDER BY fid",
                                    handle.uid), inputs)
        self.assertEqual(self.version_rows(), rows, "no escribe los parámetros de la entidad")
        self.assertEqual(self.current("PLT-001"), handle.uid)
        self.assertEqual(self.current("PLT-002"), self.second.handle.uid)
        self.assertEqual(self.stale_causes(self.second.handle.uid), set())
        self.assertEqual(self.recompute_plan(), [])
        self.assertFalse([name for name in self.written()["files"] if ".tmp-" in name])

    def test_c2_a_change_that_leaves_the_surface_as_it_was_clears_the_mark_of_the_next(self) -> None:
        """RF-008-26, RF-015-16: la tolerancia de contrapendiente de P1 cambia: P1 queda obsoleta por ese
        parámetro y P2, que consumió su superficie, también (en cascada). «Recalcular lo obsoleto» repite P1,
        cuya superficie sale **igual** (la tolerancia solo está en su informe, que cambia): P2 se queda sin
        causa y **no se recalcula** (sigue siendo su operación) y no queda nada obsoleto."""
        key = design_params.entity_key("PLT-001", "counter_tol_m")
        first, second = self.current("PLT-001"), self.current("PLT-002")
        before = self.hashes_of(first)
        self.change(key, 0.25)
        self.assertEqual(self.stale_causes(first), {("parameter_changed", key)})
        self.assertIn(("parameter_changed", key), self.stale_causes(second))
        self.assertEqual(self.plan_units(), [(first,), (second,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([(result.status, len(result.operations)) for result in outcome.results],
                         [(recompute_mod.UnitStatus.DONE, 1)])
        (made,) = outcome.results[0].operations
        after = self.hashes_of(made)
        self.assertEqual(after[PSF], before[PSF], "la superficie es la misma")
        self.assertEqual(after[EPR], before[EPR])
        self.assertNotEqual(after[PRP], before[PRP], "el informe lleva la tolerancia")
        self.assertEqual(self.rows_of(PRP_TABLE)["counter_tolerance_m"][0][:2], (0.25, "m"))
        self.assertEqual(self.current("PLT-001"), made)
        self.assertEqual(self.current("PLT-002"), second, "P2 no se recalculó")
        self.assertEqual(self.stale_causes(second), set())
        self.assertEqual(self.recompute_plan(), [])

    def test_c5_recomputing_uses_the_parameters_of_the_version_and_not_the_layer(self) -> None:
        """RF-015-01, RF-015-02, RF-015-16 (P-3): la cota inicial de la rasante se copió de la capa a la
        entidad al crearla (250 m) y es un parámetro de su versión con su historial: cambiada en la versión
        (248 m), P1 queda obsoleta por ella y recalcular la usa (el informe y la cifra, a 248 m) **aunque la
        capa siga diciendo 250**, que no se toca (el mismo registro y el mismo contenido); la superficie
        baja, la de P2 la sigue y la geometría de origen es la misma."""
        key = design_params.entity_key("PLT-001", "start_level_m")
        first, second = self.current("PLT-001"), self.current("PLT-002")
        layers = self.layers()
        sha = self.hashes_of(first)
        self.change(key, 248.0)
        self.assertEqual(self.stale_causes(first), {("parameter_changed", key)})
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 2)
        (new_first,), (new_second,) = (result.operations for result in outcome.results)
        self.assertEqual(self.rows_of(PRP_TABLE)["start_level_m"][0][:2], (248.0, "m"))
        self.assertEqual(self.figures_of(new_first)[("des.plat_start_level_m", figures_mod.scope_json(
            provenance.entity_figure_scope(LOADING, "PLT-001")))], 248.0)
        self.assertEqual(self.layers(), layers, "la capa no se toca (sigue diciendo 250 m)")
        after = self.hashes_of(new_first)
        self.assertNotEqual(after[PSF], sha[PSF])
        self.assertEqual(after[EPR], sha[EPR], "la huella y el eje son los mismos")
        self.assertNotEqual(self.hashes_of(new_second)[PSF2], self.hashes_of(second)[PSF2])
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual((self.current("PLT-001"), self.current("PLT-002")), (new_first, new_second))
        self.assertNotEqual(first, new_first)

    # --- (e) La cascada de la cadena -------------------------------------------------------------

    def test_e1_changing_the_first_stales_the_next_and_recomputing_goes_in_dependency_order(self) -> None:
        """RF-015-16, RF-008-24, RF-008-26: se vuelve a registrar la operación de P1 (queda **después** de la
        de P2) y se cambia el alcance de P1 (``reach_m``): P1 queda obsoleta por ese parámetro y P2 con la
        misma causa (``parameter_changed`` de la clave de **P1**, no de P2). El plan de «Recalcular lo
        obsoleto» las pone en orden de dependencia, P1 y P2 (no en el de registro, que es P2 y P1), y
        recalculadas cada una sustituye a la suya: P1 usa el alcance nuevo (de su fila de la versión, no de la
        capa), la superficie de P2 sigue a la de P1 fuera de su ventana y nada queda obsoleto."""
        reach = design_params.entity_key("PLT-001", "reach_m")
        self.clock.advance(minutes=1)
        recompute_function(self.request_for(self.current("PLT-001")))
        first, second = self.current("PLT-001"), self.current("PLT-002")
        order = dict(self.query("SELECT uid, fid FROM gb_operation WHERE uid IN (?, ?)",
                                first, second))
        self.assertGreater(order[first], order[second], "P1 se registró después que P2")
        self.assertEqual((self.stale_causes(first), self.stale_causes(second)), (set(), set()))
        surfaces = (self.hashes_of(first)[PSF], self.hashes_of(second)[PSF2])
        self.change(reach, 25.0)
        self.assertEqual(self.stale_causes(first), {("parameter_changed", reach)})
        self.assertIn(("parameter_changed", reach), self.stale_causes(second))
        self.assertNotIn(("parameter_changed", design_params.entity_key("PLT-002", "reach_m")),
                         self.stale_causes(second))
        self.assertEqual(self.plan_units(), [(first,), (second,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 2)
        (new_first,), (new_second,) = (result.operations for result in outcome.results)
        self.assertEqual(self.query("SELECT supersedes_uid FROM gb_operation WHERE uid IN (?, ?) "
                                    "ORDER BY fid", new_first, new_second), [(first,), (second,)])
        self.assertEqual((self.current("PLT-001"), self.current("PLT-002")), (new_first, new_second))
        self.assertEqual(self.rows_of(PRP_TABLE)["edge_reach_m"][0][:2], (25.0, "m"))
        self.assertNotEqual(self.hashes_of(new_first)[PSF], surfaces[0])
        self.assertNotEqual(self.hashes_of(new_second)[PSF2], surfaces[1], "P2 sigue a P1")
        ((bounds,),) = self.query(
            f'SELECT bounds FROM "{provenance.dataset_locator("epr", WORKSHOP, "V01")}"')
        row0, row1, col0, col1 = json.loads(bounds)
        outside = np.ones(GRID.shape, dtype=bool)
        outside[row0:row1, col0:col1] = False
        np.testing.assert_array_equal(self.grid_of(PSF2)[outside], self.grid_of(PSF)[outside])
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual((self.stale_causes(new_first), self.stale_causes(new_second)), (set(), set()))
        entry = entities_module.registry(self.project, self.v1.uid).get("PLT-001")
        self.assertEqual(str(entry.record.state), "current")


class RecomputeRefusalTest(RecomputeCase):
    """RF-015-02, RF-013-17 (``des.input_changed``): lo que impide registrar un recálculo, con P1 creada."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())

    def test_c3_a_dataset_that_changes_before_it_starts_is_not_registered(self) -> None:
        """RF-013-04, RF-013-17: si la superficie de partida cambia entre que se prepara el recálculo y que la
        operación nueva empieza, el resultado no le corresponde: ``des.input_changed`` al empezar (con el
        dato), la operación nueva queda fallida, la anterior sigue vigente sin sustituir y no queda ningún
        temporal."""
        old = self.current("PLT-001")
        real = design_store.OperationStart.begin
        shifted = gis.Raster(GRID, qfx.terrain(GRID) + 1.0, efx.CRS, efx.VERTICAL)

        def racing(start: Any, project: Any, **options: Any) -> Any:
            self.clock.advance(minutes=1)
            res_fixtures.write_grids(self.project, [(START.removeprefix("gis_dtm_"), shifted)],
                                     message="La partida cambia justo antes de empezar")
            return real(start, project, **options)

        self.clock.advance(minutes=1)
        with mock.patch.object(design_store.OperationStart, "begin", racing):
            with self.assertRaises(messages.DesignError) as caught:
                design_store.recompute_run(self.request_for(old))
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(START, caught.exception.text)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE supersedes_uid = ?", old),
                         [("failed",)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old),
                         [(None,)])
        self.assertEqual(self.current("PLT-001"), old)
        self.assertFalse([name for name in self.written()["files"] if ".tmp-" in name])

    def test_c3_a_parameter_that_changes_before_it_starts_is_not_registered(self) -> None:
        """RF-013-17, RF-015-16: si el alcance de P1 cambia entre que se prepara el recálculo y que la
        operación nueva empieza (y anota los valores que lee), el cálculo no le corresponde: al avanzar,
        ``des.input_changed`` con el parámetro, la operación nueva queda fallida y la anterior, vigente, sin
        sustituir."""
        old = self.current("PLT-001")
        reach = design_params.entity_key("PLT-001", "reach_m")
        real = design_store.OperationStart.begin

        def racing(start: Any, project: Any, **options: Any) -> Any:
            self.change(reach, 26.0)  # cambia justo antes de empezar
            return real(start, project, **options)

        self.clock.advance(minutes=1)
        with mock.patch.object(design_store.OperationStart, "begin", racing):
            handle, work = design_store.recompute_run(self.request_for(old))
        with self.assertRaises(messages.DesignError) as caught:
            finish(work)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(reach, caught.exception.text)
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("failed", old)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old),
                         [(None,)])
        self.assertEqual(self.current("PLT-001"), old)
        self.assertFalse([name for name in self.written()["files"] if ".tmp-" in name])


class RecomputeCounterSlopeTest(RecomputeCase):
    """RF-015-23: un recálculo no confirma por la persona una contrapendiente mayor que la que ella confirmó
    (T14; con la confirmada de T15, véase ``RecomputeConfirmedCounterSlopeTest``)."""

    def test_c4_a_counter_slope_that_is_not_confirmed_is_not_registered(self) -> None:
        """RF-015-23: la «Plataforma de la torre», creada con la confirmación de su contrapendiente y con su
        cota inicial 3 m más baja (la contrapendiente crece más que la tolerancia sobre la confirmada), al
        recalcularla **no la confirma por la persona**: se rechaza al avanzar
        (``des.platform_counter_unconfirmed``), la operación nueva queda fallida, la anterior sigue
        vigente y no queda ningún dato, cifra ni temporal más."""
        self.clock.advance(minutes=1)
        old = self.calculate_in(prep.request(TOWER), confirm_counterslope=True).create().handle.uid
        self.change(design_params.entity_key("PLT-001", "start_level_m"), 212.0)
        before = self.written()
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        with self.assertRaises(messages.DesignError) as caught:
            finish(work)
        self.assertEqual(caught.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("failed", old)])
        self.assertEqual(self.current("PLT-001"), old)
        after = self.written()
        for key in ("datasets", "parameters", "figures", "tables", "files"):
            self.assertEqual(after[key], before[key], key)


class ConfirmedCounterSlopeTest(RecomputeCase):
    """RF-015-23, RF-015-02, RF-008-26 (T15; decisión de la sesión principal, revisable): la contrapendiente
    que la persona confirmó al crear queda en los ajustes de la operación (cuánto, en qué abscisa, quién y
    cuándo) y un recálculo la reutiliza mientras la nueva no pase de la confirmada más la tolerancia; si
    pasa, vuelve a pedirla. La «Plataforma de la torre» (cota inicial de la capa, 215 m) creada con su
    contrapendiente confirmada y recalculada por el orden de los nombres de las pruebas: (f1) lo que se
    anota, (f2) la que se reutiliza y (f3) la que se vuelve a pedir."""

    KEY = "counterslope_confirmed"
    LEVEL = design_params.entity_key("PLT-001", "start_level_m")
    TOLERANCE_M = 0.1
    """La tolerancia de contrapendiente por defecto (D-8)."""
    plain_worst: ClassVar[tuple[float, float]]
    first: ClassVar[str]
    created_on: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        plain = cls.calculate_in(prep.request(TOWER))
        cls.plain_worst = cls.worst(plain)
        plain.discard()
        cls.clock.advance(minutes=1)
        cls.first = cls.calculate_in(prep.request(TOWER),
                                     confirm_counterslope=True).create().handle.uid
        cls.created_on = timeutil.format_utc(cls.clock.now())

    @staticmethod
    def worst(calculation: Any) -> tuple[float, float]:
        """La contrapendiente de su peor tramo y su abscisa."""
        profile = calculation.outcome.profile
        index = profile.worst
        assert index is not None
        return float(profile.rise_m[index]), float(profile.chainage_m[index])

    def settings_of(self, uid: str) -> dict[str, Any]:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return dict(json.loads(settings))

    def rise_with(self, level: float) -> float:
        """Cambia la cota inicial de la torre en la versión a ``level`` y da lo que sube su
        contrapendiente así (calculada sin crear)."""
        self.change(self.LEVEL, level)
        calculation = self.calculate_in(prep.request(TOWER), code="PLT-001",
                                        supersedes=self.current("PLT-001"))
        try:
            return self.worst(calculation)[0]
        finally:
            calculation.discard()  # no deja su temporal

    def test_f1_creating_with_the_confirmation_records_what_was_confirmed(self) -> None:
        """RF-015-23: lo confirmado se anota en los ajustes de la operación al crear: la cuantía y la
        abscisa del peor tramo (los del perfil), quién lo confirmó (quien tiene abierto el proyecto) y
        cuándo; una plataforma sin contrapendiente no lleva nada (los ajustes de siempre)."""
        recorded = self.settings_of(self.first)[self.KEY]
        self.assertEqual(sorted(recorded), ["abscissa_m", "amount_m", "decided_by", "decided_on"])
        self.assertEqual((recorded["amount_m"], recorded["abscissa_m"]), self.plain_worst)
        self.assertGreater(recorded["amount_m"], self.TOLERANCE_M)
        self.assertEqual(recorded["decided_by"], self.project.session.user_host)
        self.assertEqual(recorded["decided_on"], self.created_on)
        self.clock.advance(minutes=1)
        free = self.calculate_in(prep.request(LOADING, start=EDGE_HOLE_DATASET),
                                 confirm_counterslope=True).create()
        self.assertNotIn(self.KEY, self.settings_of(free.handle.uid), "sin contrapendiente, nada")
        self.assertEqual(self.settings_of(free.handle.uid), provenance.platform_settings(
            prep.request(LOADING, start=EDGE_HOLE_DATASET), "PLT-002"))

    def test_f2_a_recompute_reuses_the_confirmation_while_the_counter_slope_does_not_grow(self) -> None:
        """RF-015-23, RF-008-26: recalcular la torre sin cambiar nada, o con un cambio que sube la
        contrapendiente menos que la tolerancia (0,1 m), da una operación nueva que sustituye a la
        anterior **sin pedir la confirmación otra vez** y que lleva la **misma** confirmación (la cuantía
        y el decisor de la primera: no se actualiza a la del recálculo); «Recalcular lo obsoleto» tampoco
        la rechaza."""
        confirmed = self.settings_of(self.first)[self.KEY]
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(self.first))
        stored = finish(work)
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("done", self.first)])
        self.assertEqual(self.settings_of(handle.uid)[self.KEY], confirmed)
        self.assertEqual(self.current("PLT-001"), handle.uid)
        rise = self.rise_with(214.95)  # 5 cm más baja que la de la capa: sube la contrapendiente 5 cm
        self.assertGreater(rise, confirmed["amount_m"])
        self.assertLessEqual(rise, confirmed["amount_m"] + self.TOLERANCE_M)
        self.assertEqual(self.stale_causes(handle.uid), {("parameter_changed", self.LEVEL)})
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE])
        (newest,) = outcome.results[0].operations
        self.assertEqual(self.settings_of(newest)[self.KEY], confirmed)
        self.assertEqual(self.current("PLT-001"), newest)
        self.assertEqual(self.recompute_plan(), [])

    def test_f3_a_counter_slope_over_the_confirmed_one_is_asked_again(self) -> None:
        """RF-015-23: si la contrapendiente nueva pasa de la confirmada más la tolerancia, el recálculo
        vuelve a pedir la confirmación (falla con ``des.platform_counter_unconfirmed``, la operación
        vigente no cambia y no queda nada más) y quien la quiere vuelve a «Calcular», la confirma y la
        crea con la cuantía nueva: la que se reutilizará desde entonces."""
        current = self.current("PLT-001")
        confirmed = self.settings_of(current)[self.KEY]
        rise = self.rise_with(212.0)
        self.assertGreater(rise, confirmed["amount_m"] + self.TOLERANCE_M,
                           "el caso: crece más que la tolerancia")
        before = self.written()
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(current))
        with self.assertRaises(messages.DesignError) as caught:
            finish(work)
        self.assertEqual(caught.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("failed", current)])
        self.assertEqual(self.current("PLT-001"), current)
        after = self.written()
        for key in ("datasets", "parameters", "figures", "tables", "files"):
            self.assertEqual(after[key], before[key], key)
        self.clock.advance(minutes=1)
        again = self.calculate_in(prep.request(TOWER), code="PLT-001", supersedes=current)
        self.assertTrue(again.needs_confirmation)
        again.confirm_counterslope()
        self.clock.advance(minutes=1)
        newest = again.create().handle.uid
        renewed = self.settings_of(newest)[self.KEY]
        self.assertEqual(renewed["amount_m"], rise)
        self.assertGreater(renewed["amount_m"], confirmed["amount_m"])
        self.assertEqual(self.current("PLT-001"), newest)
        self.clock.advance(minutes=1)  # y recalcular ya no la pide
        _handle, work = design_store.recompute_run(self.request_for(newest))
        self.assertEqual(finish(work).handle.op_type, "des.platform")


class ReproduceTest(RecomputeCase):
    """RF-015-02, RF-009-11, RF-009-19: P1 (línea), P2 (de la superficie de P1) y P3 (un polígono con su eje
    enlazado, que parte de otro terreno y se apoya en la superficie de P1) creadas en V01; la cota inicial de
    P1 se cambia en la versión (249 m, no los 250 de su capa) y las tres se recalculan; congeladas en
    V01.r1 (las operaciones de ``uids`` son las del recálculo)."""

    NAME = "Explanada con eje"
    revision: ClassVar[str]
    uids: ClassVar[tuple[str, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))
        cls.made(prep.polygon_request(cls.NAME, start=EDGE_HOLE_DATASET, support="entity:PLT-001"))
        cls.change(design_params.entity_key("PLT-001", "start_level_m"), 249.0)
        cls.clock.advance(minutes=1)
        again = finish(recompute_mod.recompute_steps(cls.project))
        assert [result.status for result in again.results] == [recompute_mod.UnitStatus.DONE] * 3
        registry = entities_module.registry(cls.project, cls.v1.uid)
        cls.uids = tuple(str(registry.get(code).operation_uid)
                         for code in ("PLT-001", "PLT-002", "PLT-003"))
        cls.clock.advance(minutes=1)
        frozen = finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def reproduce(self) -> Any:
        """La reproducción de V01.r1, comprobando que **no escribió** nada en el proyecto (los ficheros y el
        contador de cambios de la base, sin la caché donde reproduce)."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        return report

    def assert_same(self, report: Any) -> None:
        """Las tres plataformas reprodujeron sus tres salidas y sus cifras, todas iguales."""
        mine = [check for check in report.outputs if check.operation_uid in self.uids]
        self.assertEqual(sorted((check.operation_uid, check.role) for check in mine),
                         sorted((uid, role) for uid in self.uids
                                for role in ("entity", "entity_report", "entity_surface")))
        self.assertTrue(all(check.same for check in mine), [c for c in mine if not c.same])
        for uid in self.uids:
            found = [check for check in report.figures if check.operation_uid == uid]
            self.assertEqual({check.key for check in found},
                             {key for key, _scope in self.figures_of(uid)})
            self.assertGreaterEqual(len(found), 9)
            self.assertTrue(all(check.same for check in found), [c for c in found if not c.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    def test_d1_reproducing_the_frozen_revision_gives_the_same_without_writing(self) -> None:
        """RF-015-02, RF-009-11: reproducir V01.r1 —sin proyecto, desde la capa (y la de los ejes), la
        partida, el apoyo, las máscaras y los parámetros congelados— da, de cada plataforma, la superficie,
        la tabla y el informe con el **mismo hash** que registró su operación (la de P2 parte de la
        superficie de P1; la de P3, de otro terreno, con el apoyo ``entity:PLT-001`` y un polígono con su eje
        enlazado) y las mismas cifras, sin escribir nada en el proyecto."""
        self.assert_same(self.reproduce())

    def test_e2_changing_and_recomputing_after_freezing_leaves_the_frozen_revision_as_it_was(self) -> None:
        """RF-015-16, RF-009-19, RF-009-11, RF-008-26: congelada V01.r1, cambiar el alcance de P1 deja
        obsoletas (en curso, en la revisión abierta, D-23) las tres operaciones y «Recalcular lo obsoleto» las
        repite en orden de dependencia (P1 primero) **registrando las nuevas en la revisión abierta**; lo
        congelado no cambia (la revisión sigue congelada, sus elementos son los mismos, las operaciones
        sustituidas quedan en ella como historia, no se marca nada de ella) y V01.r1 se reproduce otra vez
        igual, con los hash de cuando se congeló (aunque lo vivo ya sea otro)."""
        reach = design_params.entity_key("PLT-001", "reach_m")
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid",
                           self.revision)
        self.assertTrue(items)
        frozen = {uid: self.hashes_of(uid) for uid in self.uids}
        self.change(reach, 25.0)
        self.assertEqual(self.plan_units(), [(self.uids[0],), (self.uids[1],), (self.uids[2],)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 3)
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'",
                               self.v1.uid)[0]
        made = [result.operations[0] for result in outcome.results]
        self.assertEqual(self.query("SELECT supersedes_uid, revision_uid FROM gb_operation "
                                    "WHERE uid IN (?, ?, ?) ORDER BY fid", *made),
                         [(old, opened) for old in self.uids])
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid IN (?, ?, ?) "
                                    "ORDER BY fid", *self.uids), [(self.revision,)] * 3)
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", self.revision),
                         [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? "
                                    "ORDER BY fid", self.revision), items)
        self.assertEqual({uid: self.hashes_of(uid) for uid in self.uids}, frozen)
        self.assertNotEqual(self.hashes_of(made[0])[PSF], frozen[self.uids[0]][PSF], "lo vivo cambió")
        self.assertEqual(self.recompute_plan(), [])
        self.assert_same(self.reproduce())


class ReproduceFunctionsTest(unittest.TestCase):
    """RF-015-02: las funciones de reproducir de los tipos de las entidades."""

    def test_d2_what_is_not_a_request_or_not_a_platform_is_a_program_error(self) -> None:
        """RF-015-02: lo que no es una petición de reproducir, o es la de otro tipo de operación, es un error
        del programa."""
        with self.assertRaises(TypeError):
            design_reproduce.reproduce_platform("petición")
        other = reproduce_mod.ReproduceRequest("des.quarry", {}, (), {}, ".", None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            design_reproduce.reproduce_platform(other)

    def test_d2_the_layer_is_not_reproducible_yet(self) -> None:
        """RF-015-27: la capa de entidades (T30) aún no tiene su reproducción: lo dice con un
        ``NotImplementedError`` que nombra la tarea, no con un ``AttributeError``. La de la declaración de
        restricciones es real desde la T17 (``test_declare_operation``)."""
        with self.assertRaises(NotImplementedError) as caught:
            design_reproduce.reproduce_entity_layer(None)
        self.assertIn("T30", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
