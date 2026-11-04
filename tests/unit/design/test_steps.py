# SPDX-License-Identifier: GPL-3.0-or-later
"""Los pasos con presupuesto y cancelación del cálculo de las envolventes y el escalonado (spec 013,
T17; HU-013-1, HU-013-3; RF-013-03, RF-013-33; RNF-013-01, RNF-013-07; plan 013 §5.3.2, D-14, D-20,
D-27).

``design.steps`` compone el cálculo en generadores de ``Progress`` que agrupan sus unidades en pasos
de ``budget_s`` como mucho (``pace_units``): ``preview_steps`` (la vista previa, que solo lee),
``envelope_run`` y ``design_run`` («Calcular»: el cálculo entero, con la rejilla en su temporal, **sin
registrar nada**). El último paso de los dos lleva una ``Calculation``: «Crear» la registra en una
transacción y «Cancelar» (o cerrar la ventana) borra los temporales. Cerrar el generador a mitad
borra los temporales y no deja nada.

Cuota del plazo (RNF-013-07): ningún paso pasa de 0,2 s con la rejilla de prueba. Se mide la CPU del
proceso del paso más lento de la mejor de tres pasadas (en pared flaquea con la CPU de otros
programas, T36); el presupuesto (0,05 s) lo reparte ``pace_units``, que se comprueba con presupuestos
diminutos (un paso por unidad).
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import time
import types
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design.test_store import (
    BOTTOM_M,
    BY_HAND,
    OTHER_PROFILE,
    OTHER_VALUES,
    POOL,
    PROFILE,
    SECTOR_SLOPE,
    STEPPED,
    SURFACE,
    _StoreCase,
    declare_profile,
    definitions,
    drive,
    envelope_request,
    finish,
    last,
    pool_request,
    stepped_request,
)

steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
core_params = import_geoblender("core.params")
access = import_geoblender("gis.masks.access")
geotiff_reader = import_geoblender("gis.geotiff.reader")
res_provenance = import_geoblender("reserves.provenance")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_compile = import_geoblender("gis.masks.compile")

STEP_LIMIT_S = 0.2
"""RNF-013-07: lo que hace Geoblender en cada llamada del hilo de Blender."""
PASSES = 3
"""Pasadas de la medida de un paso: se toma la mejor (la máquina de desarrollo no está siempre en
reposo)."""


def renamed(request: Any, name: str) -> Any:
    """La misma petición con otro nombre (el nombre es único en la versión)."""
    return dataclasses.replace(request, name=name)


def release(found: list[Any]) -> None:
    """Quita los temporales de un cálculo que acabó (los pasos de la vista previa no tienen)."""
    result = found[-1].result if found else None
    if hasattr(result, "discard"):
        result.discard()


def one_pass(make: Callable[[], Iterator[Any]]) -> tuple[float, list[Any]]:
    """Lleva los pasos de ``make()`` hasta el final y devuelve el paso más lento (s) y los pasos.

    Mide la CPU del proceso (``time.process_time()``): la pared de un paso sube con lo que gasten
    los demás programas del equipo, y el plazo de pared de verdad lo mide la prueba de rendimiento."""
    iterator = make()
    slowest, found = 0.0, []
    while True:
        begun = time.process_time()
        try:
            step = next(iterator)
        except StopIteration:
            return slowest, found
        slowest = max(slowest, time.process_time() - begun)
        found.append(step)


def timed(make: Callable[[], Iterator[Any]]) -> tuple[float, list[Any]]:
    """El paso más lento (s) y los pasos de la mejor de hasta :data:`PASSES` pasadas de ``make()``
    (se detiene en la primera que cumple el plazo); lo que dejan las demás se quita."""
    best: tuple[float, list[Any]] | None = None
    for _attempt in range(PASSES):
        slowest, found = one_pass(make)
        if best is None or slowest < best[0]:
            if best is not None:
                release(best[1])
            best = (slowest, found)
        else:
            release(found)
        if best[0] <= STEP_LIMIT_S:
            break
    assert best is not None
    return best


def snapshot(project: Any, root: Path) -> dict[str, Any]:
    """Todo lo que el cálculo podría dejar en el proyecto: operaciones, datos, tablas, cifras,
    filas de parámetros y los ficheros de ``rasters/`` (con sus temporales)."""
    with project.read() as conn:
        return {
            "operations": conn.execute("SELECT uid, status FROM gb_operation "
                                       "ORDER BY fid").fetchall(),
            "datasets": conn.execute("SELECT name, status FROM gb_dataset "
                                     "ORDER BY name").fetchall(),
            "tables": conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall(),
            "figures": conn.execute("SELECT count(*) FROM gb_figure").fetchall(),
            "parameters": conn.execute("SELECT count(*) FROM gb_parameter").fetchall(),
            "files": sorted(path.name for path in (root / "rasters").iterdir())}


def cut_points(found: list[Any]) -> list[int]:
    """Dónde cerrar unos pasos a mitad (cuántos pasos se avanzan antes): al empezar, en la mitad del
    cálculo, en el primer paso de escribir (``store``) y en el penúltimo (con la rejilla ya en su
    temporal); el último paso lleva el resultado."""
    first_store = next(index for index, step in enumerate(found) if step.phase == "store")
    return sorted({1, len(found) // 2, first_store + 1, len(found) - 1})


def same_bits(left: np.ndarray, right: np.ndarray) -> bool:
    """Los mismos bits en float64, también los NaN."""
    return bool(left.dtype == right.dtype == np.float64 and left.shape == right.shape
                and np.array_equal(left.view(np.uint64), right.view(np.uint64)))


def register_design_parameters(case: type[unittest.TestCase]) -> None:
    """Registra para la clase lo que declara ``des`` en ``bl``: parámetros, familias y espesor."""
    core_params.register_definitions(design_params.DEFINITIONS)
    case.addClassCleanup(core_params.unregister_definitions, "des")
    core_params.register_families(design_params.FAMILIES)
    case.addClassCleanup(core_params.unregister_families, "des")
    core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
    case.addClassCleanup(core_params.unregister_definitions, "res")


class StepsCase(dfx.DesignProjectCase):
    """Una copia del proyecto del diseño **por clase**, con dos perfiles, 20° de talud impuesto en
    el sector 2, el hoyo calculado y registrado (``store.run_envelope``) y su escalonado
    (``store.run_design``): el cálculo por pasos de estas pruebas no registra nada, así que no se
    pisan entre sí (cada una mira lo que había antes de empezar)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        register_design_parameters(cls)
        cls.enterClassContext(registered(*definitions()))
        declare_profile(cls.project, cls.clock, PROFILE)
        declare_profile(cls.project, cls.clock, OTHER_PROFILE, **OTHER_VALUES)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, SECTOR_SLOPE, 20.0, kind="HIPÓTESIS", reason="Talud del sector 2",
                version=cls.v1.code, **BY_HAND)
        cls.clock.advance(minutes=1)
        cls.pool = finish(store.run_envelope(cls.project, pool_request(), version=cls.v1.uid))
        cls.clock.advance(minutes=1)
        cls.stepped = finish(store.run_design(cls.project, stepped_request(), SURFACE,
                                              version=cls.v1.uid))
        cls.loaded = access.load_masks(cls.project, cls.v1.uid)

    # --- Ayudas -------------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return snapshot(self.project, self.root)

    def envelope_steps(self, name: str = "Hoyo nuevo", request: Any | None = None,
                       **kw: Any) -> Iterator[Any]:
        kw.setdefault("masks", self.loaded)
        return steps.envelope_run(self.project, request or renamed(pool_request(), name),
                                  version=self.v1.uid, **kw)

    def design_steps(self, name: str = "Bancos nuevos", **kw: Any) -> Iterator[Any]:
        kw.setdefault("masks", self.loaded)
        return steps.design_run(self.project, renamed(stepped_request(), name), SURFACE,
                                version=self.v1.uid, **kw)

    def read_back(self, dataset: str) -> np.ndarray:
        """Las celdas de la rejilla ``dataset`` de V01 tal como están en el proyecto."""
        record = self.record(dataset, self.v1)
        return geotiff_reader.read_geotiff(self.root / record.locator).values

    def figures_of(self, uid: str) -> dict[str, float]:
        return dict(self.query("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))

    def assertClosingLeavesNothing(self, make: Callable[..., Iterator[Any]]  # noqa: N802
                                   ) -> None:
        """Cerrar los pasos de ``make(budget_s=…)`` en cada punto de :func:`cut_points` (el último
        con la rejilla ya en su temporal) no deja nada en el proyecto."""
        before = self.snapshot()
        found = list(make(budget_s=1e-9))
        release(found)
        self.assertEqual(self.snapshot(), before, "los pasos completos, sin crear, no dejan nada")
        # (el cálculo entero ya se quitó con release; ahora, a mitad)
        for advance in cut_points(found):
            with self.subTest(advance=advance, phase=found[advance - 1].phase):
                iterator = make(budget_s=1e-9)
                for _ in range(advance):
                    next(iterator)
                if advance == len(found) - 1:
                    self.assertNotEqual(self.snapshot()["files"], before["files"],
                                        "el temporal existe antes de cerrar")
                iterator.close()
                self.assertEqual(self.snapshot(), before)

    # --- La vista previa ------------------------------------------------------------------------

    def test_the_preview_steps_are_short_and_write_nothing(self) -> None:
        """RF-013-03, RNF-013-07: la vista previa da pasos cortos, el último con el resumen de las
        semillas y el dominio, y no escribe nada; con un presupuesto diminuto da un paso por
        unidad; cerrarla a mitad no deja nada."""
        before = self.snapshot()
        slowest, found = timed(lambda: steps.preview_steps(self.project, pool_request(),
                                                           self.v1.uid))
        self.assertLessEqual(slowest, STEP_LIMIT_S)
        summary = found[-1].result
        self.assertIsInstance(summary, preview.PreviewSummary)
        self.assertGreater(summary.seeds.cells, 0)
        self.assertTrue(all(step.result is None for step in found[:-1]))
        fine = list(steps.preview_steps(self.project, pool_request(), self.v1.uid, budget_s=1e-9))
        self.assertGreater(len(fine), 4)
        self.assertGreaterEqual(len(fine), len(found), "un presupuesto menor no da menos pasos")
        self.assertEqual(fine[-1].result.lines("es"), summary.lines("es"))
        iterator = steps.preview_steps(self.project, pool_request(), self.v1.uid, budget_s=1e-9)
        next(iterator)
        next(iterator)
        iterator.close()
        self.assertEqual(self.snapshot(), before)

    # --- La envolvente --------------------------------------------------------------------------

    def test_the_envelope_steps_are_short_and_end_in_a_calculation_with_only_a_temporary(
            self) -> None:
        """RNF-013-07, RF-013-33, D-14: «Calcular» da pasos de 0,2 s como mucho (los presupuestos
        diminutos, uno por unidad), solo el último con el resultado; el cálculo deja la rejilla en
        su temporal y **nada más**: ni operación, ni dato, ni tabla, ni cifra, ni fila de
        parámetros."""
        before = self.snapshot()
        slowest, found = timed(lambda: self.envelope_steps())
        self.assertLessEqual(slowest, STEP_LIMIT_S)
        self.assertTrue(all(step.result is None for step in found[:-1]))
        self.assertGreater(len(found), 2)
        self.assertIsInstance(found[-1].result, steps.Calculation)
        release(found)
        self.assertEqual(self.snapshot(), before, "descartar quita el temporal")
        fine = list(self.envelope_steps(budget_s=1e-9))
        self.assertGreater(len(fine), 6)
        self.assertGreaterEqual(len(fine), len(found), "un presupuesto menor no da menos pasos")
        calculation = fine[-1].result
        after = self.snapshot()
        (temporary,) = set(after["files"]) - set(before["files"])
        self.assertRegex(temporary, r"^des_env_hoyo_nuevo_v01\.tif\.tmp-[0-9a-f]+$")
        self.assertEqual({key: after[key] for key in after if key != "files"},
                         {key: before[key] for key in before if key != "files"},
                         "calcular no registra nada")
        calculation.discard()
        self.assertEqual(self.snapshot(), before)

    def test_the_units_are_grouped_into_steps_of_the_budget(self) -> None:
        """RNF-013-07, D-20: lo que se prepara antes de calcular (unidades de unos milisegundos) se
        agrupa con ``pace_units``: con un presupuesto diminuto cada unidad es un paso y, con el
        presupuesto de verdad (el trabajo se planea sobre su mitad, 25 ms) y un reloj de mentira que
        avanza 10 ms en cada medida, cada paso reúne dos unidades."""
        def prepare_steps(budget_s: float) -> int:
            iterator = self.envelope_steps(budget_s=budget_s)
            count = 0
            for step in iterator:
                if step.phase != "prepare":
                    break
                count += 1
            iterator.close()
            return count

        ticks = itertools.count()
        fake = types.SimpleNamespace(perf_counter=lambda: next(ticks) * 0.01)
        units = prepare_steps(1e-9)
        with mock.patch.object(masks_compile, "time", fake):
            grouped = prepare_steps(masks_compile.STEP_BUDGET_S)
        self.assertGreater(units, 4)
        self.assertEqual(grouped, units // 2)

    def test_closing_the_envelope_steps_midway_leaves_nothing(self) -> None:
        """RF-013-33, D-20: cerrar los pasos de la envolvente a mitad —al leer, al calcular, al
        escribir, con la rejilla ya en su temporal— borra los temporales y no deja ni operación
        ni dato ni cifra."""
        self.assertClosingLeavesNothing(lambda **kw: self.envelope_steps(**kw))

    def test_the_envelope_calculation_is_what_run_envelope_registers(self) -> None:
        """RF-013-17, D-14: la rejilla y las cifras que calcula «Calcular» son, bit a bit, las que
        registra ``run_envelope`` con la misma petición (la misma función de cálculo)."""
        calculation = last(self.envelope_steps()).result
        self.addCleanup(calculation.discard)
        registered_grid = self.read_back("des_env_hoyo_del_sector_1")
        self.assertTrue(same_bits(calculation.outcome.grid, registered_grid))
        self.assertEqual(
            {spec.key: spec.value for spec in calculation.figures},
            {key: value for key, value in self.figures_of(self.pool.handle.uid).items()})
        self.assertEqual(calculation.outcome.figures, calculation.figures)
        self.assertEqual(calculation.message, calculation.outcome.message)
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         (provenance.ENVELOPE, "Hoyo nuevo", "V01"))
        self.assertEqual([spec.name for spec in calculation.specs], ["des_env_hoyo_nuevo"])
        self.assertGreater(calculation.seeds.cells, 0)
        self.assertEqual(float(np.nanmin(calculation.outcome.grid)), BOTTOM_M)
        codes = [notice.code for notice in calculation.notices]
        self.assertEqual("des.seeds_outside_domain" in codes, calculation.seeds.outside_domain > 0)
        self.assertEqual("des.seeds_without_data" in codes, calculation.seeds.nodata_cells > 0)
        self.assertEqual(calculation.lines("es"),
                         tuple(notice.text("es") for notice in calculation.notices))

    def test_the_envelope_warns_of_the_seeds_outside_the_domain(self) -> None:
        """RF-013-03, RF-013-01: si el dominio se acota a un sector y las semillas están en otro,
        el resumen avisa del número y el área de las semillas fuera del dominio (se conservan: la
        envolvente las usa), como la vista previa."""
        request = renamed(pool_request(domain=model.WorkDomain(sectors=("sector_2",))),
                          "Fuera del dominio")
        calculation = last(self.envelope_steps(request=request)).result
        self.addCleanup(calculation.discard)
        self.assertGreater(calculation.seeds.outside_domain, 0)
        self.assertEqual(calculation.seeds.outside_domain, calculation.seeds.cells)
        self.assertIn("des.seeds_outside_domain", [notice.code for notice in calculation.notices])
        self.assertTrue(calculation.warnings("es"))
        self.assertEqual(calculation.notices,
                         preview.seed_notices(request, calculation.seeds))

    def test_a_failure_after_writing_the_grid_leaves_nothing(self) -> None:
        """RF-013-33: un fallo cuando la rejilla ya está en su temporal (al armar el resumen) borra
        el temporal y el error sigue; no queda nada registrado."""
        before = self.snapshot()
        with mock.patch.object(preview, "seed_notices", side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                drive(self.envelope_steps())
        self.assertEqual(self.snapshot(), before)

    def test_creating_the_envelope_registers_everything_in_one_transaction(self) -> None:
        """RF-013-17, RF-013-31, D-14, D-27, R4: «Crear» abre la operación, mueve el temporal,
        escribe las cifras y completa en **una** transacción de escritura: operación hecha de la
        versión, su rejilla con su hash (el del cálculo) y sus cifras, y ni rastro de temporal."""
        before = self.snapshot()
        calculation = last(self.envelope_steps("Hoyo creado")).result
        entered: list[str] = []
        original = self.project.write_transaction

        def spy() -> Any:
            entered.append("write")
            return original()

        self.clock.advance(minutes=1)
        self.assertTrue(calculation.open)
        with mock.patch.object(self.project, "write_transaction", spy):
            stored = calculation.create()
        self.assertFalse(calculation.open)
        self.assertEqual(entered, ["write"])
        self.assertEqual([item.name for item in stored.records], ["des_env_hoyo_creado"])
        record = self.record("des_env_hoyo_creado", self.v1)
        self.assertEqual(record.content_sha256, calculation.specs[0].content.content_sha256)
        self.assertEqual(record.operation_uid, stored.handle.uid)
        self.assertTrue(same_bits(self.read_back("des_env_hoyo_creado"),
                                  calculation.outcome.grid))
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    stored.handle.uid), [("done",)])
        self.assertEqual({key: value for key, value in self.figures_of(stored.handle.uid).items()},
                         {spec.key: spec.value for spec in calculation.figures})
        after = self.snapshot()
        self.assertEqual(sorted(set(after["files"]) - set(before["files"])),
                         ["des_env_hoyo_creado_v01.tif"], "sin temporal ni copia apartada")
        self.assertEqual([name for name, _status in after["datasets"]
                          if name not in {n for n, _s in before["datasets"]}],
                         ["des_env_hoyo_creado"])
        with self.assertRaises(RuntimeError):
            calculation.create()
        calculation.discard()  # tras crear no quita lo creado
        self.assertEqual(self.snapshot(), after)

    def test_discarding_deletes_the_temporaries_and_creating_after_it_is_refused(self) -> None:
        """RF-013-33, D-14: «Cancelar» (o cerrar la ventana, o salir del ``with``) borra los
        temporales y no deja nada; se puede repetir; y no se puede crear lo descartado."""
        before = self.snapshot()
        calculation = last(self.envelope_steps()).result
        self.assertNotEqual(self.snapshot()["files"], before["files"])
        calculation.discard()
        calculation.discard()
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(RuntimeError):
            calculation.create()
        self.assertEqual(self.snapshot(), before)
        with last(self.envelope_steps()).result as inside:
            self.assertNotEqual(self.snapshot()["files"], before["files"])
            self.assertIsInstance(inside, steps.Calculation)
        self.assertEqual(self.snapshot(), before)

    def test_closing_the_steps_after_the_result_keeps_the_calculation(self) -> None:
        """D-14: tras el último paso la ``Calculation`` es de quien la recibió: cerrar el generador
        no borra su temporal (lo borra ``discard``) y aún se puede crear."""
        before = self.snapshot()
        iterator = self.envelope_steps("Hoyo que sigue")
        found = []
        for step in iterator:
            found.append(step)
            if step.result is not None:
                break
        iterator.close()
        calculation = found[-1].result
        self.assertNotEqual(self.snapshot()["files"], before["files"])
        self.clock.advance(minutes=1)
        stored = calculation.create()
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    stored.handle.uid), [("done",)])

    # --- El escalonado --------------------------------------------------------------------------

    def test_the_design_steps_are_short_and_leave_only_two_temporaries(self) -> None:
        """RNF-013-07, RF-013-33, D-14: el escalonado da pasos de 0,2 s como mucho y, al
        calcular, deja la superficie y la rejilla de bermas en sus temporales y nada registrado
        (las tablas, en memoria)."""
        before = self.snapshot()
        slowest, found = timed(lambda: self.design_steps())
        self.assertLessEqual(slowest, STEP_LIMIT_S)
        self.assertTrue(all(step.result is None for step in found[:-1]))
        self.assertIsInstance(found[-1].result, steps.Calculation)
        release(found)
        self.assertEqual(self.snapshot(), before, "descartar quita los temporales")
        fine = list(self.design_steps(budget_s=1e-9))
        self.assertGreater(len(fine), 8)
        self.assertGreaterEqual(len(fine), len(found))
        calculation = fine[-1].result
        self.assertIsInstance(calculation, steps.Calculation)
        after = self.snapshot()
        temporaries = sorted(set(after["files"]) - set(before["files"]))
        self.assertEqual(len(temporaries), 2, temporaries)
        self.assertRegex(temporaries[0], r"^des_brm_bancos_nuevos_v01\.tif\.tmp-")
        self.assertRegex(temporaries[1], r"^des_srf_bancos_nuevos_v01\.tif\.tmp-")
        self.assertEqual({key: after[key] for key in after if key != "files"},
                         {key: before[key] for key in before if key != "files"})
        calculation.discard()
        self.assertEqual(self.snapshot(), before)

    def test_closing_the_design_steps_midway_leaves_nothing(self) -> None:
        """RF-013-33, D-20: cerrar los pasos del escalonado a mitad —al leer, al calcular, al
        escribir la primera o la segunda rejilla— no deja nada."""
        self.assertClosingLeavesNothing(lambda **kw: self.design_steps(**kw))

    def test_the_design_calculation_is_what_run_design_registers(self) -> None:
        """RF-013-17, RF-013-30, D-14: la superficie, las bermas, sus filas, el informe y las
        cifras de «Calcular» son los que registra ``run_design`` con la misma petición."""
        calculation = last(self.design_steps()).result
        self.addCleanup(calculation.discard)
        self.assertTrue(same_bits(calculation.outcome.design,
                                  self.read_back("des_srf_bancos_del_hoyo")))
        self.assertTrue(same_bits(calculation.outcome.berms.grid,
                                  self.read_back("des_brm_bancos_del_hoyo")))
        self.assertEqual(
            {spec.key: spec.value for spec in calculation.figures},
            {key: value for key, value in self.figures_of(self.stepped.handle.uid).items()})
        rows = [list(row.values()) for row in calculation.outcome.berms.table]
        self.assertEqual(rows, [list(row) for row in self.query(
            "SELECT sector, profile, level_m, cells, area_m2, anchor_m, anchor_diff_m "
            'FROM "des_bmt_bancos_del_hoyo_v01" ORDER BY fid')])
        self.assertGreater(len(rows), 0)
        self.assertEqual(calculation.notices, calculation.outcome.report.notices)
        self.assertEqual(calculation.lines("es"), calculation.outcome.report.lines("es"))
        self.assertEqual(calculation.warnings("en"), calculation.outcome.report.warnings("en"))
        self.assertIsNone(calculation.seeds)
        self.assertEqual([spec.name for spec in calculation.specs], [
            "des_srf_bancos_nuevos", "des_brm_bancos_nuevos", "des_bmt_bancos_nuevos",
            "des_rpt_bancos_nuevos"])

    def test_the_design_is_compared_with_the_last_frozen_revision(self) -> None:
        """RF-013-30, D-25: el escalonado se compara con el desmonte y el terraplén de la revisión
        congelada más reciente (``previous_comparison``), como el que se registra de una vez: sin
        ninguna, una nota lo dice; con una mucho menor, el aviso de magnitud."""
        plain = last(self.design_steps()).result
        self.addCleanup(plain.discard)
        self.assertIn("des.magnitude_no_reference", [n.code for n in plain.notices])
        before = {"operation": STEPPED, "revision": "V01.r1", "cut_m3": 1.0, "fill_m3": 0.0}
        with mock.patch.object(store, "previous_comparison", return_value=before):
            compared = last(self.design_steps()).result
        self.addCleanup(compared.discard)
        codes = [notice.code for notice in compared.notices]
        self.assertNotIn("des.magnitude_no_reference", codes)
        self.assertIn("des.magnitude_cut", codes)
        self.assertTrue(any("V01.r1" in line for line in compared.warnings("es")))

    def test_creating_the_design_registers_its_four_outputs(self) -> None:
        """RF-013-31, RF-013-28, RF-013-30, D-14: «Crear» registra la superficie de diseño con su
        papel, las cotas de las bermas, su tabla y el informe, con las cifras, en una operación
        ``des.stepped_design`` hecha."""
        calculation = last(self.design_steps("Bancos creados")).result
        self.clock.advance(minutes=1)
        stored = calculation.create()
        self.assertEqual([item.name for item in stored.records], [
            "des_srf_bancos_creados", "des_brm_bancos_creados", "des_bmt_bancos_creados",
            "des_rpt_bancos_creados"])
        self.assertEqual(self.query("SELECT op_type, status FROM gb_operation WHERE uid = ?",
                                    stored.handle.uid), [(provenance.STEPPED, "done")])
        self.assertEqual(self.query("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND "
                                    "direction = 'out' AND item_uid = ?", stored.handle.uid,
                                    stored.records[0].uid), [("design_surface",)])
        self.assertTrue(same_bits(self.read_back("des_srf_bancos_creados"),
                                  calculation.outcome.design))
        self.assertEqual(self.figures_of(stored.handle.uid),
                         {spec.key: spec.value for spec in calculation.figures})
        self.assertGreater(self.query('SELECT count(*) FROM "des_bmt_bancos_creados_v01"')[0][0],
                           0)
        self.assertEqual([name for name in self.snapshot()["files"] if ".tmp" in name], [])

    # --- Lo que se rechaza ----------------------------------------------------------------------

    def test_the_steps_refuse_when_they_advance_and_leave_nothing(self) -> None:
        """RF-013-16, RF-013-17, RF-013-19, RF-009-21: los rechazos salen al avanzar, antes de
        calcular y sin dejar nada: un nombre repetido (de la envolvente y del escalonado), sin
        versión activa y una envolvente que no existe."""
        no_envelope = dataclasses.replace(stepped_request(), name="Sin hoyo", envelope="No existe")
        cases = (
            ("des.operation_name_repeated", lambda: steps.envelope_run(
                self.project, pool_request(), version=self.v1.uid, masks=self.loaded)),
            ("des.operation_name_repeated", lambda: steps.design_run(
                self.project, stepped_request(), SURFACE, version=self.v1.uid,
                masks=self.loaded)),
            ("core.version_required", lambda: steps.envelope_run(
                self.project, renamed(pool_request(), "Sin versión"), version=None)),
            ("gis.dataset_unknown", lambda: steps.design_run(
                self.project, no_envelope, SURFACE, version=self.v1.uid, masks=self.loaded)),
        )
        before = self.snapshot()
        for code, make in cases:
            with self.subTest(code=code):
                iterator = make()  # el generador no hace nada hasta avanzar
                self.assertEqual(self.snapshot(), before)
                with self.assertRaises(Exception) as caught:
                    drive(iterator)
                self.assertEqual(getattr(caught.exception, "code", None), code)
                self.assertEqual(self.snapshot(), before)


class ChangesTest(_StoreCase):
    """Una copia del proyecto **por prueba**: lo que cambia entre calcular y crear, un sector con la
    búsqueda pendiente y las máscaras que faltan."""

    def setUp(self) -> None:
        super().setUp()
        self.declare_profile(PROFILE)
        self.declare_profile(OTHER_PROFILE, **OTHER_VALUES)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).create(
                conn, SECTOR_SLOPE, 20.0, kind="HIPÓTESIS", reason="Talud del sector 2",
                version=self.v1.code, **BY_HAND)

    def test_a_parameter_changed_meanwhile_is_not_recorded(self) -> None:
        """RF-013-17, D-14: si cambia un parámetro que lee el cálculo (la berma de un perfil)
        entre «Calcular» y «Crear», el resultado ya no le corresponde: ``des.input_changed``, no se
        registra nada y el temporal se borra."""
        before = self.des_state()
        calculation = last(steps.envelope_run(
            self.project, pool_request(), version=self.v1.uid, masks=self.cached_masks())).result
        self.assertNotEqual(self.des_state()["files"], before["files"])
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, design_params.bench_key(PROFILE, "berm_m"), value=7.0, reason="Prueba")
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn("berm_m", str(caught.exception))
        self.assertEqual(self.des_state(), before)
        with self.assertRaises(RuntimeError):
            calculation.create()

    def test_a_pending_search_refuses_when_advancing_and_leaves_nothing(self) -> None:
        """RF-013-05, RF-013-33: con la búsqueda de un sector que toca el dominio pendiente, el
        cálculo se niega al avanzar, nombrando el sector, sin dejar nada."""
        masks = self.cached_masks()
        with self.project.write_transaction() as conn:
            conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_1'")
        before = self.des_state()
        with self.assertRaises(messages.DesignError) as caught:
            drive(steps.envelope_run(self.project, pool_request(), version=self.v1.uid,
                                     masks=masks))
        self.assertEqual(caught.exception.code, "des.sector_pending")
        self.assertIn("Sector 1", str(caught.exception))
        self.assertEqual(self.des_state(), before)

    def test_missing_masks_are_compiled_first_in_steps(self) -> None:
        """RF-013-04, RNF-013-07: si las máscaras de la versión no están al día, se compilan antes
        como operación propia **por pasos** (los primeros pasos son los de compilar, de 0,2 s como
        mucho) y el cálculo sigue; no hay operación de ``des`` y el temporal se quita con
        ``discard``."""
        request = envelope_request("Sin máscaras")
        before = self.des_state()
        compiled_before = self.query("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                     masks_provenance.COMPILE)
        slowest, found = one_pass(lambda: steps.envelope_run(self.project, request,
                                                             version=self.v2.uid))
        self.assertLessEqual(slowest, STEP_LIMIT_S)
        self.assertEqual(found[0].phase, "compile")
        self.assertIsInstance(found[-1].result, steps.Calculation)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE op_type = ? "
                                    "AND status = 'done'", masks_provenance.COMPILE),
                         [(compiled_before[0][0] + 1,)], "la compilación de V02")
        after = self.des_state()
        self.assertEqual(after["operations"], before["operations"], "ninguna operación de des")
        self.assertEqual(after["datasets"], before["datasets"])
        extra = sorted(set(after["files"]) - set(before["files"]))
        self.assertEqual(len(extra), 2, extra)
        self.assertRegex(extra[0], r"^des_env_sin_mascaras_v02\.tif\.tmp-[0-9a-f]+$")
        self.assertEqual(extra[1], "gis_msk_v02.tif", "las máscaras que compiló")
        found[-1].result.discard()
        left = set(self.des_state()["files"]) - set(before["files"])
        self.assertEqual(left, {"gis_msk_v02.tif"}, "queda lo que compiló, que es otra operación")


class RegularizationWarningTest(dfx.DesignProjectCase):
    """RF-013-26, RF-013-30, RF-013-31 (spec 0.4; F-1), con proyecto: una envolvente de pendiente
    constante de 60° (más empinada que el talud general del perfil base, 40,4°, con el talud de
    20° impuesto en el sector 2) y su escalonado en corte. El aviso de que la regularización la bajó
    llega adonde llegan los avisos: el resumen de «Calcular» (``warnings``, lo que cuenta «Crear con
    N avisos»), el informe ``des_rpt_`` que registra «Crear» y, sin él, ninguno cuando la
    envolvente es la de la pendiente de cada sector."""

    STEEP = "Hoyo empinado"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        register_design_parameters(cls)
        cls.enterClassContext(registered(*definitions()))
        declare_profile(cls.project, cls.clock, PROFILE)
        declare_profile(cls.project, cls.clock, OTHER_PROFILE, **OTHER_VALUES)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, SECTOR_SLOPE, 20.0, kind="HIPÓTESIS", reason="Talud del sector 2",
                version=cls.v1.code, **BY_HAND)
        cls.clock.advance(minutes=1)
        cls.steep = finish(store.run_envelope(
            cls.project, renamed(pool_request(slope_mode="constant", slope_deg=60.0), cls.STEEP),
            version=cls.v1.uid))
        cls.clock.advance(minutes=1)
        cls.pool = finish(store.run_envelope(cls.project, pool_request(), version=cls.v1.uid))
        cls.loaded = access.load_masks(cls.project, cls.v1.uid)

    def calculation(self, envelope: str, name: str) -> Any:
        request = renamed(stepped_request(envelope=envelope), name)
        calculation = last(steps.design_run(self.project, request, SURFACE, version=self.v1.uid,
                                            masks=self.loaded)).result
        self.addCleanup(calculation.discard)
        return calculation

    @staticmethod
    def lowered(calculation: Any) -> list[Any]:
        return [n for n in calculation.notices if n.code == "des.regularization_lowered"]

    def test_the_notice_reaches_the_summary_and_the_count_of_warnings(self) -> None:
        """RF-013-30, RF-013-31: «Calcular» enseña el aviso con sus avisos (``warnings``, de donde
        sale el «N avisos» de «Crear»), en los dos idiomas, con las celdas y el descenso máximo
        del informe y el nombre de los sectores donde bajó (solo el 2: la envolvente asciende
        desde las semillas del sector 1 y allí es donde la regularización la baja)."""
        found = self.calculation(self.STEEP, "Bancos empinados")
        (notice,) = self.lowered(found)
        self.assertGreater(notice.values["cells"], 1000)
        self.assertGreater(notice.values["drop"], 1.0)
        self.assertEqual(notice.values["sectors"], "Sector 2")
        for language in ("es", "en"):
            self.assertIn(notice.text(language), found.warnings(language))
            self.assertIn(notice.text(language), found.lines(language))
        self.assertIn("sectores: Sector 2)", notice.text("es"))
        self.assertIn("sectors: Sector 2)", notice.text("en"))
        warnings = [n for n in found.notices if n.severity == "warning"]
        self.assertEqual(len(found.warnings("es")), len(warnings))
        self.assertIn(notice, warnings)

    def test_creating_records_the_notice_in_the_report_without_changing_the_figures(self) -> None:
        """RF-013-30, RF-013-31: «Crear» escribe el aviso en el informe ``des_rpt_`` como una
        fila ``warning`` con su código y sus valores en JSON (las mismas celdas y el mismo descenso
        que el resumen, sin redondear), y las cifras (desmonte, terraplén, inclinación) son las
        mismas filas que el informe sin avisos: el aviso no cambia ninguna."""
        found = self.calculation(self.STEEP, "Bancos empinados creados")
        (notice,) = self.lowered(found)
        self.clock.advance(minutes=1)
        stored = found.create()
        rows = self.query('SELECT quantity, value, note FROM "des_rpt_bancos_empinados_creados_'
                          'v01" ORDER BY fid')
        warned = [json.loads(note) for quantity, _value, note in rows if quantity == "warning"]
        (recorded,) = [item for item in warned if item["code"] == "des.regularization_lowered"]
        self.assertEqual(recorded["values"], {"cells": notice.values["cells"],
                                              "drop": notice.values["drop"],
                                              "slope": notice.values["slope"],
                                              "sectors": notice.values["sectors"]})
        self.assertEqual([item["code"] for item in warned],
                         [n.code for n in found.notices if n.severity == "warning"])
        figures = {quantity: value for quantity, value, _note in rows
                   if quantity not in ("warning", "note")}
        self.assertEqual(figures["cut_m3"], found.outcome.report.cut_m3)
        self.assertEqual(figures["fill_m3"], found.outcome.report.fill_m3)
        self.assertEqual({spec.key: spec.value for spec in found.figures},
                         {key: value for key, value in self.query(
                             "SELECT key, value FROM gb_figure WHERE operation_uid = ?",
                             stored.handle.uid)})

    def test_the_envelope_by_sectors_is_not_warned(self) -> None:
        """RF-013-26, RF-013-30: con la envolvente de la pendiente de cada sector (el hoyo de las
        demás pruebas) la regularización no baja nada: ni aviso en el resumen."""
        found = self.calculation(POOL, "Bancos del hoyo regular")
        self.assertEqual(self.lowered(found), [])
        self.assertFalse(any("regulariz" in line for line in found.warnings("es")))

if __name__ == "__main__":
    unittest.main()
