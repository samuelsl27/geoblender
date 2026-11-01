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
- **RF-012-16, RF-008-26 (D-19; T21)**: «Recalcular lo obsoleto» (``recompute_run`` de las máscaras
  y de la verificación): con las máscaras obsoletas, repetir la verificación se rechaza sin
  registrar nada; repetidas las máscaras y después la verificación, cada operación nueva sustituye
  a la anterior y da lo de hoy.
- **RF-012-19 (T27)**: ``zone_check`` da, de una restricción, lo que dice la última verificación
  vigente de la versión: de cada final su superficie, su veredicto, lo que cuenta con sus m³ y sus
  cifras registradas (las del recinto y, en un límite legal, también las de su banda hacia dentro).
- **RF-012-25 (D-7, D-29; T18)**: congelar con lo que no cumple. Con la comprobación de ``res``
  registrada (``freeze_findings``), ``freeze_plan`` lista la verificación con zonas que no
  cumplen (con los m³ por zona), la que tiene la marca de búsqueda pendiente, la obsoleta y la
  superficie de diseño sin verificación al día; no congela sin aceptarlas, con un motivo que
  queda en la revisión.
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
copy_mod = import_geoblender("core.versions.copy")
versions_model = import_geoblender("core.versions.model")
i18n = import_geoblender("core.i18n")
cmodel = import_geoblender("core.constraints.model")
constraints_store = import_geoblender("core.constraints.store")
reproduce = import_geoblender("core.versions.reproduce")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
access = import_geoblender("gis.masks.access")
recompute_mod = import_geoblender("core.provenance.recompute")
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
ItemKind = versions_model.ItemKind
ItemState = versions_model.ItemState


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def _dig(depth_m: float = DIG_M) -> Any:
    x, y = fx.site_centers()
    left, bottom, right, top = DIG_LOCAL
    inside = (x > left) & (x < right) & (y > bottom) & (y < top)
    return gis.Raster(fx.SITE_GRID, np.where(inside, fx.START_Z - depth_m, fx.START_Z), fx.CRS,
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

    def test_zone_check_says_what_the_last_check_says_of_a_zone(self) -> None:
        """RF-012-19: de la torre en V01, la verificación repetida (la que sustituyó a la primera):
        su nombre, no obsoleta y, por final, la superficie, el veredicto (cumple con la excavación,
        no cumple con la torre rebajada y sus 6.384 m³ de movimiento) y las cuatro cifras
        registradas del recinto, las mismas de ``gb_figure``; el límite legal suma las de su banda
        hacia dentro; un recinto que no entró sale sin veredicto ni cifras; V02, sin
        verificación."""
        case = fx.tower_case()
        with self.project.read() as conn:
            found = cstore.zone_check(conn, self.v1.uid, "torre")
            legal = cstore.zone_check(conn, self.v1.uid, "concesion")
            absent = cstore.zone_check(conn, self.v1.uid, "no_existe")
            nothing = cstore.zone_check(conn, self.v2.uid, "torre")
        self.assertIsNone(nothing)
        self.assertEqual((found.operation_uid, found.name, found.stale),
                         (self.again, NAME, False))
        first, second = found.finals
        self.assertEqual((first.position, first.surface, first.verdict, first.counts),
                         (1, "Excavación", V.COMPLIES.value, "any"))
        self.assertEqual(first.counted_m3, 0.0)
        self.assertEqual((second.position, second.surface, second.verdict, second.counts),
                         (2, "Torre rebajada", V.FAILS.value, "any"))
        self.assertAlmostEqual(second.counted_m3, case.cut_m3, delta=case.cut_m3 * 1e-9)
        keys = ["res.check_cut_m3", "res.check_fill_m3", "res.check_moved_area_m2",
                "res.check_nodata_area_m2"]
        for final in found.finals:
            self.assertEqual([figure.key for figure in final.figures], keys)
            self.assertEqual({(figure.scope["check"], figure.scope["final"], figure.scope["zone"])
                              for figure in final.figures}, {(NAME, final.position, "torre")})
            for figure in final.figures:
                self.assertEqual(figure.value, self.figure(self.again, figure.key, check=NAME,
                                                           final=final.position, zone="torre"))
        self.assertAlmostEqual(second.figures[0].value, case.cut_m3, delta=1e-6)
        self.assertEqual([len(final.figures) for final in legal.finals], [8, 8])
        self.assertEqual({figure.scope["zone"] for figure in legal.finals[0].figures},
                         {"concesion", "concesion:inner"})
        self.assertEqual(absent.name, NAME)
        for final in absent.finals:
            self.assertEqual((final.verdict, final.counts, final.counted_m3, final.figures),
                             ("", "", None, ()))
        self.assertEqual([final.surface for final in absent.finals],
                         ["Excavación", "Torre rebajada"])

    def test_read_verification_gives_the_table_the_groups_and_the_grid(self) -> None:
        """RF-012-23 (T28): ``read_verification`` da, de la última verificación vigente de V01 (o
        de la que se llama así), lo que guardó: su operación y su nombre, la superficie de cada
        final, lo de cada recinto y final (la torre no cumple en el final 2 con sus 6.384 m³), el
        grupo de la torre (su centro, 240 m², 6.384 m³ y 26,6 m) y el ``uid`` de la rejilla de
        incumplimientos solo del final que incumple; V02 y un nombre que no existe, ninguna;
        ``constraint_names`` da el nombre y el tipo de cada código sin leer su geometría y
        ``stored_violations`` con ``violation_sources``, lo que se lee para ver la rejilla."""
        case = fx.tower_case()
        _table, _groups, _first, second = self.names()
        with self.project.read() as conn:
            found = cstore.read_verification(conn, self.v1.uid)
            named = cstore.read_verification(conn, self.v1.uid, NAME)
            other = cstore.read_verification(conn, self.v1.uid, "No existe")
            nothing = cstore.read_verification(conn, self.v2.uid)
            listed = cstore.verification_names(conn, self.v1.uid)
            names = constraints_store.constraint_names(conn)
        self.assertEqual((found.operation_uid, found.name, found.stale), (self.again, NAME, False))
        self.assertEqual(found, named)
        self.assertEqual((other, nothing, listed), (None, None, (NAME,)))
        self.assertEqual(found.surfaces, ("Excavación", "Torre rebajada"))
        by_zone = {(item.zone, item.final): item for item in found.zones}
        tower = by_zone[("torre", 2)]
        self.assertEqual((tower.verdict, tower.counts), (V.FAILS.value, "any"))
        self.assertAlmostEqual(tower.cut_m3, case.cut_m3, delta=case.cut_m3 * 1e-9)
        self.assertEqual(by_zone[("torre", 1)].verdict, V.COMPLIES.value)
        self.assertAlmostEqual(by_zone[("perimetro", 1)].cut_m3, DIG_M3, delta=1e-6)
        self.assertEqual(by_zone[(compliance.OUTSIDE_LEGAL, 1)].counted_m3, 0.0)
        (group,) = [item for item in found.groups if item.zone == "torre"]
        self.assertEqual((group.final, group.cells, group.area_m2),
                         (2, fx.TOWER_ZONE_CELLS, case.group_area_m2))
        self.assertAlmostEqual(group.volume_m3, case.group_volume_m3,
                               delta=case.group_volume_m3 * 1e-9)
        self.assertAlmostEqual(group.max_m, fx.TOWER_DROP_M, delta=1e-9)
        self.assertAlmostEqual(group.x, case.group_center[0], delta=1e-6)
        self.assertAlmostEqual(group.y, case.group_center[1], delta=1e-6)
        self.assertEqual(dict(found.grids), {2: self.records[second].uid})
        self.assertEqual(names["torre"][1], cmodel.ConstraintType.UNTOUCHABLE)
        self.assertEqual(set(names), {"concesion", "perimetro", "torre", "balsa", "cuneta"})
        stored = cstore.stored_violations(self.project, self.records[second].uid)
        self.assertEqual((stored.name, stored.final, stored.version_uid, stored.surface),
                         (NAME, 2, self.v1.uid, self.finals[1]))
        final, violations = cstore.violation_sources(self.project, stored)
        self.assertEqual(violations.grid.shape, fx.SITE_GRID.shape)
        self.assertEqual(final.grid.shape, fx.SITE_GRID.shape)
        with self.assertRaises(ValueError):  # una tabla no es una rejilla de incumplimientos
            cstore.stored_violations(self.project, self.records[cstore.dataset_name(
                cstore.TABLE, NAME)].uid)

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
    """RF-011-03, RF-012-28, RF-012-24 y D-15 con las máscaras obsoletas, y su recálculo (T21)."""

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
        # En cada fase: sumar y agrupar, y el primer y el último paso de guardar (T36).
        for stop in (3, 9, "save", "last save"):
            known = len(self.ops(cstore.VERIFY))
            steps = self.steps(budget_s=0.0005)
            while len(self.ops(cstore.VERIFY)) == known:  # cargar las máscaras son varios pasos
                next(steps)
            if isinstance(stop, int):
                for _ in range(stop):
                    next(steps)
            else:
                seen = [next(steps) for _ in range(3)]
                while seen[-1].phase != "save":
                    seen.append(next(steps))
                if stop == "last save":
                    while seen[-1].done < seen[-1].total - 1:
                        seen.append(next(steps))
            steps.close()
            with self.subTest(stop=stop):
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

    def request(self, op_type: str, uid: str) -> Any:
        """La petición de «Recalcular lo obsoleto» de la operación ``uid`` de V01: su tipo y sus
        ajustes."""
        (settings,) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0]
        return recompute_mod.RecomputeRequest(
            self.project, uid, op_type, json.loads(settings), (), (), version=self.v1.uid)

    def test_d_recompute_repeats_the_masks_and_then_the_check(self) -> None:
        """RF-012-16, RF-008-26, D-19 (A12): cambiar otra vez el resguardo de la torre en V01
        deja obsoletas las máscaras y la verificación; repetir la verificación antes que las
        máscaras se rechaza (``MaskError``) sin registrar nada; repetir las máscaras
        (``gis.masks.store.recompute_run``) y, después, la verificación
        (``reserves.compliance_store.recompute_run``) empieza cada operación nueva, que sustituye
        a la anterior en V01 con el nombre y las superficies de sus ajustes, y da lo de hoy: la
        zona de la torre con 12 m es mayor que con 10 m. Una petición de otro tipo o que no es una
        petición se rechaza al llamar."""
        previous = _last(self.steps()).result.finals[1].zone("torre").cut_m3
        first, compiled = self.ops(cstore.VERIFY)[-1], self.ops(masks_provenance.COMPILE)[-1]
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            params.ParameterStore(self.project).change(
                conn, cparams.buffer_out_key("torre"), value=12.0, reason="Prueba de la 012",
                version=self.v1.code)
        verify_request = self.request(cstore.VERIFY, first)
        operations_before = self.query("SELECT count(*) FROM gb_operation")
        with self.assertRaises(access.MaskError) as caught:
            cstore.recompute_run(verify_request)
        self.assertEqual(caught.exception.code, "core.constraint_masks_stale")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), operations_before)
        for function, request in ((cstore.recompute_run, self.request(masks_provenance.COMPILE,
                                                                       compiled)),
                                  (masks_store.recompute_run, verify_request)):
            with self.subTest(function=function.__module__):
                with self.assertRaises(ValueError):
                    function(request)
        for function in (cstore.recompute_run, masks_store.recompute_run):
            with self.subTest(sin_petición=function.__module__):
                with self.assertRaises(TypeError):
                    function(object())  # type: ignore[arg-type]

        handle, steps = masks_store.recompute_run(self.request(masks_provenance.COMPILE,
                                                               compiled))
        self.assertEqual(handle.supersedes, compiled)
        _last(steps)
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0],
                         access.MaskState.CURRENT)
        handle, steps = cstore.recompute_run(verify_request)
        self.assertEqual(handle.supersedes, first)
        again = _last(steps)
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE "
                                    "uid = ?", handle.uid), [("done", first)])
        self.assertEqual(self.ops(cstore.VERIFY)[-1], handle.uid)
        self.assertEqual(again.result.name, NAME)
        self.assertGreater(again.result.finals[1].zone("torre").cut_m3, previous)


class FreezeFindingsTest(_VerifyCase):
    """RF-012-25 (D-7, D-29): lo que ``res`` pide aceptar al congelar V01, en el orden de las
    pruebas (el proyecto es de la clase): una verificación con zonas que no cumplen y la marca de
    búsqueda pendiente; la obsoleta (cerrar las búsquedas) y la que cumple, sin nada; la
    superficie de diseño cuya verificación se sustituyó; y congelar."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        freeze.register_freeze_check(cstore.MODULE, cstore.freeze_findings)
        cls.addClassCleanup(freeze.unregister_freeze_checks, cstore.MODULE)
        cls.clock.advance(minutes=1)
        write_grids(cls.project, [("temporal", _dig(1.0)), ("otra", _dig(3.0))],
                    message="Más superficies")
        cls.temporary = surfaces.SurfaceRef(dataset="gis_dtm_temporal", label="Temporal")
        cls.other = surfaces.SurfaceRef(dataset="gis_dtm_otra", label="Otra")

    def plan(self, version: Any = None) -> Any:
        return freeze.freeze_plan(self.project, (version or self.v1).uid)

    def findings(self, plan: Any = None) -> dict[str, Any]:
        """Las entradas con nota del plan de V01, por nombre."""
        return {entry.name: entry for entry in (plan or self.plan()).accept if entry.finding}

    def verify(self, name: str, finals: Any) -> str:
        """Verifica en V01 la partida frente a ``finals`` y da el uid de la operación."""
        _last(self.steps(finals=finals, name=name))
        return self.ops(cstore.VERIFY)[-1]

    def close_searches(self) -> None:
        """Cierra la búsqueda de cada sector (operación de prueba de las restricciones)."""
        for index, sector in enumerate(cp.sectors(), start=1):
            self.clock.advance(minutes=1)
            handle = operations.begin_operation(self.project, cp.EDIT_TYPE,
                                                settings={"count": 0}, executor="blender")
            record = cmodel.SearchRecord(f"search{index}{'0' * 25}", handle.uid, sector.code,
                                         constraints_store.sector_sha256(sector),
                                         fx.SEARCH_DISTANCE_M, "Samuel (IMGA)",
                                         "2026-10-28T10:00:00Z")
            with self.project.write_transaction() as conn:
                constraints_store.append_search(conn, record, ())
                handle.complete(conn, outputs=constraints_store.dataset_specs(
                    crs_epsg=self.project.record.crs_epsg), message="Búsqueda de prueba")

    def test_a_failing_zones_with_cubic_metres_and_the_pending_mark(self) -> None:
        """RF-012-25: sin verificaciones no hay nada que listar (ni en V01 ni en V02); la
        verificación con la torre sin cumplir se lista con sus m³ por zona (6.384 m³ de movimiento,
        los de la tabla, y solo de la final que incumple) y, como se hizo con los dos sectores
        sin búsqueda, con sus nombres; es la operación, al día, y lo único que pide aceptar."""
        self.assertEqual((self.plan().accept, self.plan(self.v2).accept), ((), ()))
        uid = self.verify(NAME, self.finals)
        plan = self.plan()
        (entry,) = plan.accept
        self.assertEqual((entry.item_kind, entry.item_uid, entry.name, entry.state, entry.text),
                         (ItemKind.OPERATION, uid, NAME, ItemState.CURRENT, ""))
        self.assertEqual(self.plan(self.v2).accept, ())
        sectors = ", ".join(f"«{name}»" for name in fx.SECTORS_LOCAL)
        self.assertIn(f"La verificación «{NAME}» se hizo con la búsqueda de intocables "
                      f"pendiente en {sectors}.", entry.finding)
        self.assertIn(f"La verificación «{NAME}» no cumple en la final «Torre rebajada»: "
                      f"«torre»: 6{i18n.THIN_SPACE}384 m³ de movimiento", entry.finding)
        self.assertNotIn("Excavación", entry.finding)
        self.assertNotIn("obsoleta", entry.finding)
        with self.project.read() as conn:
            rows = cstore.read_table(conn, self.record(self.names()[0], self.v1).locator)
        failing = [zone for zone, final, quantity, _v, _u, note in rows
                   if final == 2 and quantity == "verdict" and note == V.FAILS.value]
        self.assertIn("torre", failing)
        self.assertEqual(entry.finding.count(" m³ de "), len(failing))
        self.assertTrue(plan.needs_acceptance)

    def test_b_closed_searches_stale_and_the_one_that_complies(self) -> None:
        """RF-012-25 (D-26): cerradas las búsquedas, la verificación sigue (sus máscaras no
        cambian) pero sin la marca, que se calcula al vuelo; cambiado el resguardo de la torre
        en V01, queda obsoleta (estado y texto de lo obsoleto, y la nota); la que cumple, hecha
        con las máscaras al día y sin sectores pendientes, no se lista y la obsoleta sigue,
        ahora «no reproducible» (consumió unas máscaras que ya no existen: el estado real);
        repetida la primera (sustituye a la obsoleta), sale al día, sin la marca y con lo que
        no cumple."""
        self.close_searches()
        entries = self.findings()
        self.assertEqual(set(entries), {NAME})
        self.assertIn("no cumple en la final «Torre rebajada»", entries[NAME].finding)
        self.assertNotIn("pendiente", entries[NAME].finding)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            params.ParameterStore(self.project).change(
                conn, cparams.buffer_out_key("torre"), value=10.0, reason="Prueba de la 012",
                version=self.v1.code)
        stale = self.findings()[NAME]
        self.assertEqual(stale.state, ItemState.STALE)
        self.assertTrue(stale.text.startswith("Obsoleto"), stale.text)
        self.assertIn(f"La verificación «{NAME}» está obsoleta", stale.finding)
        clean = self.verify("Limpia", self.finals[:1])  # compila antes: las máscaras cambiaron
        entries = self.findings()
        self.assertEqual(set(entries), {NAME})
        self.assertNotIn(clean, {entry.item_uid for entry in entries.values()})
        # Consumió unas máscaras que ya no existen: el estado real de la 009 es otro.
        self.assertEqual(entries[NAME].state, ItemState.NOT_REPRODUCIBLE)
        self.assertIn("obsoleta", entries[NAME].finding)
        again = self.verify(NAME, self.finals)
        entries = self.findings()
        self.assertEqual(set(entries), {NAME})
        entry = entries[NAME]
        self.assertEqual((entry.item_uid, entry.state, entry.text),
                         (again, ItemState.CURRENT, ""))
        self.assertIn("no cumple en la final «Torre rebajada»", entry.finding)
        self.assertNotIn("obsoleta", entry.finding)
        self.assertNotIn("pendiente", entry.finding)

    def test_c_design_surface_without_an_up_to_date_check(self) -> None:
        """RF-012-25 (D-29): una superficie que fue final de una verificación de la versión y
        cuya verificación se sustituyó por otra que ya no la incluye, se lista sin verificación
        al día; las que están en una verificación vigente (y esta, que cumple), no."""
        self.verify("Reemplazada", (self.other, self.temporary))
        self.assertEqual(set(self.findings()), {NAME})
        self.verify("Reemplazada", (self.temporary,))
        entries = self.findings()
        self.assertEqual(set(entries), {NAME, "gis_dtm_otra"})
        entry = entries["gis_dtm_otra"]
        self.assertEqual((entry.item_kind, entry.item_uid, entry.state, entry.text),
                         (ItemKind.DATASET, self.record("gis_dtm_otra").uid,
                          ItemState.CURRENT, ""))
        self.assertEqual(entry.finding, "«gis_dtm_otra» es una superficie de diseño sin "
                                        "verificación al día: ninguna verificación vigente la "
                                        "incluye.")

    def test_d_not_frozen_without_accepting_and_the_reason_stays(self) -> None:
        """RF-012-25, RF-009-08 (D-7): sin aceptar no se congela (el rechazo nombra lo que
        falta y no escribe nada), ni aceptando solo una parte; aceptado todo, V01.r1 queda
        congelada con el motivo y, en lo aceptado, cada elemento con su nota; V01.r2, abierta,
        sigue listando lo mismo (los datos son de la versión)."""
        plan = self.plan()
        self.assertEqual(set(self.findings(plan)), {NAME, "gis_dtm_otra"})
        before = files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)
        self.clock.advance(minutes=1)
        for accepted in (None, freeze.Acceptance(frozenset(
                {("dataset", self.record("gis_dtm_otra").uid)}))):
            with self.assertRaises(versions_model.VersionError) as caught:
                freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega",
                                    accepted=accepted)
            self.assertEqual(caught.exception.code, "core.version_freeze_accept")
            self.assertIn(NAME, str(caught.exception))
            self.assertIn("gis_dtm_otra", str(caught.exception))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        reason = "Se entrega con la torre pendiente de corregir"
        outcome = _last(freeze.freeze_steps(self.project, self.v1.uid, reason=reason,
                                            accepted=freeze.Acceptance.of(plan)))
        accepted = json.loads(str(outcome.frozen.accepted))
        self.assertEqual(accepted, copy_mod.acceptance(plan, reason=reason))
        self.assertEqual(accepted["reason"], reason)
        notes = {item["name"]: item["finding"] for item in accepted["items"]
                 if "finding" in item}
        self.assertEqual(set(notes), {NAME, "gis_dtm_otra"})
        self.assertIn("«torre»", notes[NAME])
        self.assertEqual(set(self.findings()), {NAME, "gis_dtm_otra"})


if __name__ == "__main__":
    unittest.main()
