# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación de verificar un diseño por recinto (spec 012, T17; RF-012-21, RF-012-23,
RF-012-24, RF-012-28; plan 012 §5.2.3, A11, D-28, D-40, D-42, D-43).

Sobre el proyecto de ``tests.support.constraints_project`` (una copia por clase), en V01, con tres
rejillas del proyecto en la rejilla de las máscaras: la partida (el llano del sitio), una final
que excava 2 m en un sitio permitido (cumple) y la de CE-012-02, que rebaja 26,6 m el entorno de
la torre (no cumple):

- **D-15, D-43**: sin máscaras compiladas, la verificación compila antes (una
  ``gis.compile_constraints`` propia) y, con las máscaras obsoletas (el resguardo de la torre
  cambiado en V01), vuelve a compilar antes de verificar.
- **RF-012-24**: ``res.verify_constraints`` es una operación de la versión con las máscaras
  (``MaskSet.uses``) y las superficies (``start``, ``final_1``, ``final_2``) como entradas y el
  espesor mínimo (0,02 m, D-6) anotado; sus cifras, CALCULADO con el ámbito
  ``{"check", "final", "zone"}`` y ninguna NaN; al cambiar una entrada, queda obsoleta.
- **RF-012-21**: la tabla en formato largo por recinto y final (la torre, 6.384 m³ de corte en
  el final 2, ≤ 10⁻⁹ relativo; lo excavado, 1.200 m³ en el perímetro del final 1).
- **RF-012-23 (D-42)**: la capa de grupos, un punto por grupo (el de la torre en su centro, 240 m²,
  6.384 m³ y 26,6 m); la rejilla de incumplimientos solo del final que incumple, con signo
  (final − partida, NaN en el resto) y el hash de su lector.
- **RF-011-03**: una superficie en otra rejilla o de otra versión se rechaza sin registrar nada.
- **RF-012-28**: cada paso, ≤ 0,05 s; Esc o un fallo a mitad no dejan nada (ni cifras, ni tablas,
  ni rejillas, ni temporales).
- Reproducir V01.r1 congelada da las mismas salidas y las mismas cifras, bit a bit.
"""

from __future__ import annotations

import json
import math
import unittest
from collections.abc import Iterator
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.res_fixtures import write_grids
from tests.support.timing import drive_steps, least_of, raised_priority
from tests.support.versions_fixtures import change_counter, files

gis = import_geoblender("gis")
gis_content = import_geoblender("gis.content")
params = import_geoblender("core.params")
cparams = import_geoblender("core.constraints.params")
operations = import_geoblender("core.provenance.operations")
registry = import_geoblender("core.datasets.registry")
figures_mod = import_geoblender("core.provenance.figures")
freeze = import_geoblender("core.versions.freeze")
reproduce = import_geoblender("core.versions.reproduce")
masks_provenance = import_geoblender("gis.masks.provenance")
access = import_geoblender("gis.masks.access")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
res_messages = import_geoblender("reserves.messages")

BUDGET_S = 0.05
NAME = "Diseño octubre"
DIG_LOCAL = (30.0, 30.0, 50.0, 60.0)
"""Donde excava la final que cumple (local): 10 × 15 celdas, dentro del perímetro y del núcleo
del límite, lejos de la torre, la balsa y la cuneta: 150 · 4 · 2 = 1.200 m³."""
DIG_M = 2.0
DIG_M3 = 150 * fx.SITE_GRID.cell_area * DIG_M
V = compliance.Verdict


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def _dig() -> Any:
    x, y = fx.site_centers()
    left, bottom, right, top = DIG_LOCAL
    inside = (x > left) & (x < right) & (y > bottom) & (y < top)
    return gis.Raster(fx.SITE_GRID, np.where(inside, fx.START_Z - DIG_M, fx.START_Z), fx.CRS,
                      fx.VERTICAL)


def _no_recompute(request: Any) -> Any:
    raise AssertionError("las pruebas de la verificación no recalculan con la función de bl")


class _VerifyCase(cp.ConstraintsProjectCase):
    """El proyecto de las restricciones con lo de la verificación registrado (lo hará ``bl``) y
    las tres superficies escritas como rejillas del proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(cstore.operation_def(_no_recompute, cstore.REPRODUCE[
            cstore.VERIFY]), *cstore.FIGURES))
        if cstore.MIN_THICKNESS not in params.DEFINITIONS:
            kept = [item for item in params.DEFINITIONS.values() if item.module == "res"]
            params.register_definitions(cstore.DEFINITIONS)

            def restore() -> None:
                params.unregister_definitions("res")
                params.register_definitions(kept)

            cls.addClassCleanup(restore)
        cls.clock.advance(minutes=1)
        write_grids(cls.project, [("partida", fx.site_start()), ("excavacion", _dig()),
                                  ("torre", fx.tower_case().final)], message="Superficies")
        cls.start = surfaces.SurfaceRef(dataset="gis_dtm_partida", label="Partida")
        cls.finals = (surfaces.SurfaceRef(dataset="gis_dtm_excavacion", label="Excavación"),
                      surfaces.SurfaceRef(dataset="gis_dtm_torre", label="Torre rebajada"))

    def steps(self, version: Any = None, *, finals: Any = None, budget_s: float = BUDGET_S,
              name: str = NAME) -> Iterator[Any]:
        self.clock.advance(minutes=1)
        return cstore.verify_project_steps(
            self.project, version=(version or self.v1).uid, name=name, start=self.start,
            finals=self.finals if finals is None else finals, budget_s=budget_s)

    def ops(self, op_type: str) -> list[str]:
        return [row[0] for row in self.query(
            "SELECT uid FROM gb_operation WHERE op_type = ? ORDER BY rowid", op_type)]

    def figures(self, uid: str) -> dict[tuple[str, str], tuple[float, str]]:
        return {(key, scope): (value, kind) for key, scope, value, kind in self.query(
            "SELECT key, scope, value, kind FROM gb_figure WHERE operation_uid = ?", uid)}

    def figure(self, uid: str, key: str, **scope: Any) -> float:
        return self.figures(uid)[(key, figures_mod.scope_json(scope))][0]

    def names(self) -> tuple[str, str, str, str]:
        return (cstore.dataset_name(cstore.TABLE, NAME),
                cstore.dataset_name(cstore.GROUPS, NAME),
                cstore.dataset_name(cstore.VIOLATIONS, NAME, 1),
                cstore.dataset_name(cstore.VIOLATIONS, NAME, 2))


class VerifyTest(_VerifyCase):
    """Verificar en V01 la partida frente a las dos finales (y reproducirlo congelado)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        helper = cls("test_compiles_first_and_registers_the_operation")
        cls.compiles_before = helper.ops(masks_provenance.COMPILE)
        cls.stored = _last(helper.steps())
        cls.compiles_after = helper.ops(masks_provenance.COMPILE)
        cls.uid = helper.ops(cstore.VERIFY)[-1]
        runs: list[Any] = []

        def longest() -> float:
            with raised_priority():
                run = drive_steps(helper.steps())
            runs.append(run)
            return run.longest_s

        cls.longest = least_of(longest, BUDGET_S, max_attempts=3)
        cls.again = helper.ops(cstore.VERIFY)[-1]
        cls.records = {name: helper.record(name, cls.v1) for name in helper.names()}
        cls.figures_again = helper.figures(cls.again)

    def test_compiles_first_and_registers_the_operation(self) -> None:
        """D-15, D-43, RF-012-24: compila antes (una sola vez) y registra la verificación en la
        revisión abierta de V01 con las máscaras y las superficies como entradas y el espesor
        mínimo del proyecto (0,02 m, ADOPTADO «sin confirmar»)."""
        self.assertEqual((len(self.compiles_before), len(self.compiles_after)), (0, 1))
        (row,) = self.query("SELECT o.op_type, o.status, r.version_uid, r.state FROM "
                            "gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
                            "WHERE o.uid = ?", self.uid)
        self.assertEqual(row, (cstore.VERIFY, "done", self.v1.uid, "open"))
        roles = {role: name for role, name in self.query(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", self.uid)}
        self.assertEqual(roles, {"masks_classes": "gis_msk", "masks_zones": "gis_mskz",
                                 "masks_report": "gis_mskr", "start": "gis_dtm_partida",
                                 "final_1": "gis_dtm_excavacion", "final_2": "gis_dtm_torre"})
        self.assertEqual(self.query("SELECT key, value, unit FROM gb_operation_param WHERE "
                                    "operation_uid = ?", self.uid),
                         [(cstore.MIN_THICKNESS, "0.02", "m")])

    def test_steps_within_budget(self) -> None:
        """RF-012-28: ningún paso pasa de 0,05 s."""
        self.assertLessEqual(self.longest, BUDGET_S, f"un paso tardó {self.longest * 1000:.0f} ms")

    def test_table_by_zone_and_final(self) -> None:
        """RF-012-21, RF-012-22: la tabla en formato largo, por recinto y final, con el veredicto;
        la torre no cumple en el final 2 con 6.384 m³; el final 1 cumple en todo."""
        table, *_ = self.names()
        with self.project.read() as conn:
            rows = cstore.read_table(conn, self.records[table].locator)
        values = {(zone, final, quantity): (value, unit, note)
                  for zone, final, quantity, value, unit, note in rows}
        case = fx.tower_case()
        cut = values[("torre", 2, "cut_m3")][0]
        self.assertAlmostEqual(cut, case.cut_m3, delta=case.cut_m3 * 1e-9)
        self.assertEqual(values[("torre", 2, "verdict")], (None, None, V.FAILS.value))
        self.assertEqual(values[("torre", 1, "verdict")], (None, None, V.COMPLIES.value))
        self.assertAlmostEqual(values[("perimetro", 1, "cut_m3")][0], DIG_M3, delta=1e-6)
        self.assertEqual(values[("", 1, "surface")][2], "Excavación")
        for final in (1, 2):
            for zone in (compliance.OUTSIDE_PERIMETER, compliance.OUTSIDE_LEGAL, "concesion",
                         "concesion:inner", "perimetro", "torre", "balsa", "cuneta"):
                self.assertIn((zone, final, "fill_m3"), values)
        verdicts = {final: {note for (_z, f, q), (_v, _u, note) in values.items()
                            if f == final and q == "verdict"} for final in (1, 2)}
        self.assertEqual(verdicts[1], {V.COMPLIES.value})
        self.assertIn(V.FAILS.value, verdicts[2])
        self.assertEqual(self.stored.result.fails, (False, True))

    def test_groups_layer_and_violations_grid(self) -> None:
        """RF-012-23 (D-28, D-42): un punto por grupo (el de la torre en su centro, 240 m²,
        6.384 m³, 26,6 m); la rejilla de incumplimientos, solo del final 2, con signo (final −
        partida en sus celdas, NaN en el resto) y el hash de su lector."""
        _table, groups, first, second = self.names()
        self.assertIsNone(self.records[first])
        record = self.records[second]
        self.assertEqual((record.reader, record.locator),
                         ("gis.geotiff@1", "rasters/res_chkv_diseno_octubre_2_v01.tif"))
        checked = self.stored.result.finals[1]
        with self.project.read() as conn:
            points = cstore.read_groups(conn, self.records[groups].locator)
            for item in self.records.values():
                if item is not None:
                    self.assertEqual(registry.content_digest(conn, self.project, item)
                                     .content_sha256, item.content_sha256, item.name)
        self.assertEqual(len(points), len(checked.groups))
        self.assertEqual({point[0] for point in points}, {2})
        (tower,) = [point for point in points if point[1] == "torre"]
        case = fx.tower_case()
        self.assertEqual(tower[2], fx.TOWER_ZONE_CELLS)
        self.assertEqual(tower[3], case.group_area_m2)
        self.assertAlmostEqual(tower[4], case.group_volume_m3, delta=case.group_volume_m3 * 1e-9)
        self.assertAlmostEqual(tower[5], fx.TOWER_DROP_M, delta=1e-9)
        self.assertAlmostEqual(tower[6], case.group_center[0], delta=1e-6)
        self.assertAlmostEqual(tower[7], case.group_center[1], delta=1e-6)
        expected = np.full(fx.SITE_GRID.shape, np.nan)
        moved = case.final.values - case.start.values  # final − partida (≈ −26,6 m)
        for group in checked.groups:
            expected[group.rows, group.cols] = moved[group.rows, group.cols]
        self.assertTrue(np.all(np.abs(expected[np.isfinite(expected)] + fx.TOWER_DROP_M)
                               < 1e-9))
        raster = gis.Raster(fx.SITE_GRID, expected, fx.CRS, fx.VERTICAL)
        self.assertEqual(gis_content.raster_digest(raster, {}).content_sha256,
                         record.content_sha256)

    def test_figures_are_calculated_with_their_scope(self) -> None:
        """RF-012-24: las cifras, CALCULADO con el ámbito ``{"check", "final", "zone"}``,
        finitas; la de la torre, sus m³; repetir la verificación da las mismas, bit a bit."""
        found = self.figures(self.uid)
        self.assertEqual({kind for _value, kind in found.values()}, {"CALCULADO"})
        self.assertTrue(all(math.isfinite(value) for value, _kind in found.values()))
        self.assertEqual({tuple(sorted(json.loads(scope))) for _k, scope in found},
                         {("check", "final", "zone")})
        self.assertAlmostEqual(
            self.figure(self.uid, "res.check_cut_m3", check=NAME, final=2, zone="torre"),
            fx.tower_case().cut_m3, delta=1e-6)
        self.assertEqual(self.figures_again, found)
        (row,) = self.query("SELECT supersedes_uid FROM gb_operation WHERE uid = ?", self.again)
        self.assertIsNotNone(row[0])

    def test_z_reproduce_frozen_gives_the_same(self) -> None:
        """RF-012-24 (RF-009-07): congelada V01.r1, reproducir da las mismas salidas (con su
        hash) y las mismas cifras bit a bit, sin escribir nada en el proyecto."""
        frozen = self.figures(self.again)
        self.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega"))
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, str(outcome.frozen.uid)))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        mine = [check for check in report.outputs if check.operation_uid == self.again]
        self.assertEqual(sorted(check.role for check in mine), ["groups", "table", "violations_2"])
        self.assertTrue(all(check.same for check in mine), mine)
        reproduced = {(check.key, figures_mod.scope_json(check.scope)): check.reproduced
                      for check in report.figures if check.operation_uid == self.again}
        self.assertEqual(reproduced, {key: value for key, (value, _kind) in frozen.items()})


class RejectCancelStaleTest(_VerifyCase):
    """RF-011-03, RF-012-28, RF-012-24 y D-15 con las máscaras obsoletas."""

    def assertNothing(self, before: Any, figures: int) -> None:  # noqa: N802
        self.assertEqual(self.query("SELECT count(*) FROM gb_figure")[0][0], figures)
        self.assertEqual({name: self.record(name, self.v1) for name in self.names()},
                         dict.fromkeys(self.names()))
        self.assertEqual(files(self.root, skip=(), skip_dirs=("cache",)).keys() - before, set())
        tables = {row[0] for row in self.query("SELECT name FROM sqlite_master")}
        self.assertFalse(any(name.startswith("res_chk") for name in tables))

    def test_a_other_grid_or_version_is_rejected(self) -> None:
        """RF-011-03: una superficie en otra rejilla (paso de 1 m) o de otra versión (las
        máscaras de V01 vistas desde V02) se rechaza al llamar, sin registrar nada."""
        grid = gis.Grid(fx.SITE_GRID.west, fx.SITE_GRID.north, 1.0, 1.0, 320, 320)
        self.clock.advance(minutes=1)
        write_grids(self.project, [("otra", gis.Raster(grid, np.full(grid.shape, 640.0),
                                                       fx.CRS, fx.VERTICAL))], message="Otra")
        _last(access.ensure_masks_steps(self.project, self.v1.uid))
        count = self.query("SELECT count(*) FROM gb_operation")
        for version, final, code in (
                (self.v1, surfaces.SurfaceRef(dataset="gis_dtm_otra"), "res.surfaces_mismatch"),
                (self.v2, surfaces.SurfaceRef(dataset="gis_msk"), "res.surface_other_version")):
            with self.subTest(code=code):
                with self.assertRaises(res_messages.ResError) as caught:
                    self.steps(version, finals=(final,))
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)

    def test_b_cancel_or_fail_leave_nothing(self) -> None:
        """RF-012-28: cerrar los pasos a mitad deja la verificación «cancelada»; fallar al
        confirmar, «fallida»; ninguna deja cifras, tablas, rejillas ni temporales."""
        _last(access.ensure_masks_steps(self.project, self.v1.uid))
        before = set(files(self.root, skip=(), skip_dirs=("cache",)))
        count = self.query("SELECT count(*) FROM gb_figure")[0][0]
        steps = self.steps(budget_s=0.0005)
        for _ in range(3):
            next(steps)
        steps.close()
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    self.ops(cstore.VERIFY)[-1]), [("cancelled",)])
        self.assertNothing(before, count)
        with mock.patch.object(operations.OperationHandle, "complete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                _last(self.steps())
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    self.ops(cstore.VERIFY)[-1]), [("failed",)])
        self.assertNothing(before, count)

    def test_c_stale_masks_compile_first(self) -> None:
        """RF-012-24, D-15: cambiar el resguardo de la torre en V01 deja obsoleta la
        verificación; verificar otra vez compila antes y da otra zona de la torre."""
        stored = _last(self.steps())
        first = self.ops(cstore.VERIFY)[-1]
        compiles = len(self.ops(masks_provenance.COMPILE))
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            params.ParameterStore(self.project).change(
                conn, cparams.buffer_out_key("torre"), value=10.0, reason="Prueba de la 012",
                version=self.v1.code)
        self.assertTrue(self.query("SELECT 1 FROM gb_stale WHERE item_kind = 'operation' AND "
                                   "item_uid = ?", first))
        again = _last(self.steps())
        self.assertEqual(len(self.ops(masks_provenance.COMPILE)), compiles + 1)
        before = stored.result.finals[1].zone("torre").cut_m3
        after = again.result.finals[1].zone("torre").cut_m3
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main()
