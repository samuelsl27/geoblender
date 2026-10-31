# SPDX-License-Identifier: GPL-3.0-or-later
"""Las máscaras y la verificación en las versiones (spec 012, T19; RF-012-16, RF-012-24, CE-012-07;
plan 012 A5, D-4).

Sobre el proyecto de ``tests.support.constraints_project`` (una copia por clase), con lo de la
verificación de ``tests.unit.reserves.test_compliance_store`` registrado: en V01 se verifica la
partida frente a dos finales (compila antes: las máscaras y la verificación son de su revisión
r1), en V02 se compilan las máscaras (sin fila propia del resguardo de la torre: lee el del
proyecto, 6 m; V01 tiene 8 m, D-4) y se congela V01.r1. Después, en el orden de las pruebas:

- **a** (RF-012-16, RF-012-24): V01.r1 congela las máscaras y la verificación (sus datos, sus
  operaciones y sus cifras), al día y sin alterar.
- **b** (CE-012-07): cambiar el resguardo de la torre **solo en V01** deja obsoletas las máscaras y
  la verificación de V01.r2 con la causa ``parameter_changed`` sobre la fila de V01; lo congelado
  de V01.r1 y las máscaras de V02 no cambian.
- **c** (CE-012-07): recalculadas, las máscaras de V01 son las de ``gis.masks.combine`` con el
  nuevo resguardo y la verificación da otros m³; lo congelado de V01.r1 sigue igual.
- **d** (CE-012-07, RF-012-16, RF-012-24): reproducir V01.r1 da sus salidas con el mismo hash y
  sus cifras bit a bit, sin escribir en el proyecto, aunque lo vivo de V01 ya sea otro.
- **e** (RF-012-16, D-4): V02, sin fila de versión, leyó el valor del proyecto en su compilación
  y no se ha movido con el cambio de V01.
"""

from __future__ import annotations

import json
import unittest
from collections import defaultdict
from typing import Any

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.reserves.test_compliance_store import NAME, _last, _VerifyCase

params = import_geoblender("core.params")
cparams = import_geoblender("core.constraints.params")
combine = import_geoblender("gis.masks.combine")
access = import_geoblender("gis.masks.access")
masks_provenance = import_geoblender("gis.masks.provenance")
cstore = import_geoblender("reserves.compliance_store")
freeze = import_geoblender("core.versions.freeze")
versions_check = import_geoblender("core.versions.check")
versions_model = import_geoblender("core.versions.model")
reproduce = import_geoblender("core.versions.reproduce")
figures_mod = import_geoblender("core.provenance.figures")
graph = import_geoblender("core.provenance.graph")

TOWER_NEW_M = 10.0
"""El resguardo nuevo de la torre en V01 (antes, 8 m)."""
MASK_NAMES = tuple(masks_provenance.dataset_name(family.code)
                   for family in masks_provenance.FAMILIES)
ItemKind = versions_model.ItemKind
ItemState = versions_model.ItemState
TOWER_KEY = cparams.buffer_out_key("torre")
CAUSE = graph.CauseKind.PARAMETER_CHANGED.value


class VersionsTest(_VerifyCase):
    """CE-012-07 (véase el módulo): una sola historia, en el orden de las pruebas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        helper = cls("test_a_freeze_keeps_masks_and_check")
        _last(helper.steps())  # V01: compila antes y verifica (revisión r1)
        _last(access.ensure_masks_steps(cls.project, cls.v2.uid))
        cls.compile_1 = helper.version_ops(masks_provenance.COMPILE, cls.v1)[-1]
        cls.verify_1 = helper.version_ops(cstore.VERIFY, cls.v1)[-1]
        cls.compile_2 = helper.version_ops(masks_provenance.COMPILE, cls.v2)[-1]
        cls.v1_before = helper.outputs(cls.v1)
        cls.v2_before = helper.outputs(cls.v2)
        cls.figures_before = {uid: helper.figures(uid)
                              for uid in (cls.compile_1, cls.verify_1)}
        cls.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega"))
        cls.r1, cls.r2 = str(outcome.frozen.uid), str(outcome.opened.uid)
        cls.frozen_before = helper.frozen(cls.r1)

    # --- Ayudas -------------------------------------------------------------------------------

    def version_ops(self, op_type: str, version: Any) -> list[str]:
        """Los uid de las operaciones ``op_type`` de ``version`` (de cualquiera de sus
        revisiones), en el orden en que se hicieron."""
        return [row[0] for row in self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = ? AND r.version_uid = ? ORDER BY o.rowid", op_type, version.uid)]

    def outputs(self, version: Any) -> dict[str, str]:
        """El hash de contenido de cada salida viva de ``version`` (máscaras y verificación)."""
        found = {name: self.record(name, version) for name in (*MASK_NAMES, *self.names())}
        return {name: record.content_sha256 for name, record in found.items()
                if record is not None}

    def checked_names(self) -> tuple[str, ...]:
        """Los nombres de los datos de la verificación que existen (la rejilla de la final que
        cumple no existe)."""
        return tuple(name for name in self.names() if self.record(name, self.v1) is not None)

    def frozen(self, revision_uid: str) -> dict[str, Any]:
        """Lo congelado por ``revision_uid``: la fila de la revisión y cada elemento."""
        return {
            "revision": self.query("SELECT state, snapshot_dir, snapshot_sha256, altered_at FROM "
                                   "gb_revision WHERE uid = ?", revision_uid),
            "items": self.query("SELECT item_kind, item_uid, part, item_rev, content_sha256, "
                                "copied, snapshot_path, snapshot_layer, file_sha256, file_size, "
                                "state FROM gb_revision_item WHERE revision_uid = ? "
                                "ORDER BY item_kind, item_uid", revision_uid)}

    def causes(self) -> dict[tuple[str, str], set[tuple[str, str]]]:
        """Las causas de obsolescencia de cada elemento obsoleto: ``(clase, uid)`` →
        ``{(causa, sujeto)}``."""
        found: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        for kind, uid, cause, subject in self.query(
                "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale"):
            found[(kind, uid)].add((cause, subject))
        return dict(found)

    def tower_row(self, version: Any) -> str:
        """El uid de la fila del resguardo de la torre de ``version``."""
        return self.query("SELECT uid FROM gb_parameter WHERE key = ? AND scope_uid = ?",
                          TOWER_KEY, version.uid)[0][0]

    def tower_cells(self, tower_m: float) -> Any:
        """Las celdas de la zona de la torre con ``tower_m`` de resguardo, de
        ``gis.masks.combine`` sobre las restricciones guardadas."""
        resolved = dict(cp.project_values())
        resolved[TOWER_KEY] = tower_m
        prepared = combine.prepare(self.stored_constraints(), resolved, fx.SITE_GRID)
        return prepared.zones["torre"].runs

    def tower_cut_m3(self, uid: str) -> float:
        """Los m³ de corte de la torre en la final que incumple (la 2) de la verificación."""
        return self.figure(uid, "res.check_cut_m3", check=NAME, final=2, zone="torre")

    # --- La historia --------------------------------------------------------------------------

    def test_a_freeze_keeps_masks_and_check(self) -> None:
        """RF-012-16, RF-012-24 (RF-009-07): V01.r1 congela, al día, los datos de las máscaras y de
        la verificación, las dos operaciones y sus cifras, con el contenido que tenían, y su
        instantánea coincide con lo congelado."""
        frozen = {(row[0], row[1]): row for row in self.frozen_before["items"]}
        self.assertEqual(set(self.v1_before), {*MASK_NAMES, *self.checked_names()})
        for name, sha in self.v1_before.items():
            row = frozen[("dataset", self.record(name, self.v1).uid)]
            self.assertEqual((row[4], row[10]), (sha, "current"), name)
        for uid in (self.compile_1, self.verify_1):
            self.assertEqual(frozen[("operation", uid)][10], "current", uid)
        made = {row[0] for row in self.query(
            "SELECT uid FROM gb_figure WHERE operation_uid IN (?, ?)", self.compile_1,
            self.verify_1)}
        self.assertTrue(made)
        self.assertEqual({uid for kind, uid in frozen if kind == "figure"} & made, made)
        self.assertEqual({row[10] for row in self.frozen_before["items"]}, {"current"})
        (state, _dir, _sha, altered) = self.frozen_before["revision"][0]
        self.assertEqual((state, altered), ("frozen", None))
        findings = graph.drain(versions_check.check_steps(self.project, [self.r1], full=True))
        self.assertEqual([item.altered for item in findings], [False])
        self.assertEqual(self.causes(), {})

    def test_b_change_in_v01_only_makes_its_open_revision_stale(self) -> None:
        """CE-012-07, RF-012-16: cambiar el resguardo de la torre solo en V01 deja obsoletas las
        máscaras y la verificación de V01.r2 con la causa ``parameter_changed`` sobre la fila de
        V01, y el plan de congelar lo lista con su causa; V02 y lo congelado de V01.r1 no
        cambian."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            params.ParameterStore(self.project).change(
                conn, TOWER_KEY, value=TOWER_NEW_M, reason="Prueba de la 012",
                version=self.v1.code)
        row = (CAUSE, self.tower_row(self.v1))
        causes = self.causes()
        for uid in (self.compile_1, self.verify_1):
            self.assertIn(row, causes[("operation", uid)], uid)
        live = {self.record(name, self.v1).uid for name in (*MASK_NAMES, *self.checked_names())}
        self.assertEqual({uid for (kind, uid) in causes if kind == "dataset"}, live)
        self.assertTrue(all(row in causes[("dataset", uid)] for uid in live))
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)
        plan = freeze.freeze_plan(self.project, self.v1.uid)
        stale_ops = {item.item_uid for item in plan.items
                     if item.item_kind == ItemKind.OPERATION and item.state == ItemState.STALE}
        self.assertEqual(stale_ops, {self.compile_1, self.verify_1})
        self.assertEqual({entry.item_uid for entry in plan.accept}, live)
        for entry in plan.accept:
            self.assertEqual(entry.state, ItemState.STALE, entry.name)
            self.assertEqual(entry.text, "Obsoleto: cambió Resguardo hacia fuera · torre")
        # Lo que no es de V01: V02 sigue al día y V01.r1 es la que era.
        self.assertEqual(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.CURRENT)
        self.assertFalse([key for key in causes if key[1] == self.compile_2])
        self.assertEqual(self.frozen(self.r1), self.frozen_before)

    def test_c_recomputed_change_and_the_frozen_does_not(self) -> None:
        """CE-012-07: recalculadas, las máscaras de V01 son las de ``combine`` con el resguardo
        nuevo (más celdas en la zona de la torre) y la verificación da más m³; lo congelado en
        V01.r1 y las máscaras de V02 siguen igual."""
        before = self.tower_cut_m3(self.verify_1)
        _last(self.steps())  # compila antes (las máscaras estaban obsoletas) y verifica
        compile_new = self.version_ops(masks_provenance.COMPILE, self.v1)[-1]
        verify_new = self.version_ops(cstore.VERIFY, self.v1)[-1]
        for uid, old_uid in ((compile_new, self.compile_1), (verify_new, self.verify_1)):
            self.assertNotEqual(uid, old_uid)
            self.assertEqual(self.query("SELECT revision_uid, supersedes_uid FROM gb_operation "
                                        "WHERE uid = ?", uid), [(self.r2, old_uid)])
        # Lo vivo está al día; solo quedan marcadas las dos operaciones de V01.r1 que se sustituyeron.
        self.assertEqual(set(self.causes()), {("operation", self.compile_1),
                                              ("operation", self.verify_1)})
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT)
        now = self.outputs(self.v1)
        for name in (MASK_NAMES[0], MASK_NAMES[1], self.names()[0]):
            self.assertNotEqual(now[name], self.v1_before[name], name)
        masks = access.load_masks(self.project, self.v1.uid)
        expected = self.tower_cells(TOWER_NEW_M)
        self.assertEqual(masks.zone("torre"), expected)
        self.assertGreater(expected.cells, fx.TOWER_ZONE_CELLS)
        self.assertGreater(self.tower_cut_m3(verify_new), before)
        self.assertEqual(self.frozen(self.r1), self.frozen_before)
        self.assertEqual(self.outputs(self.v2), self.v2_before)
        findings = graph.drain(versions_check.check_steps(self.project, [self.r1], full=True))
        self.assertEqual([item.altered for item in findings], [False])

    def test_d_reproduce_v01_r1_gives_the_same(self) -> None:
        """CE-012-07, RF-012-16, RF-012-24 (RF-009-11): reproducir V01.r1, ya con otro resguardo
        vivo, da las salidas de la compilación y de la verificación con el mismo hash, y sus
        cifras bit a bit, sin escribir nada en el proyecto."""
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, self.r1))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        self.assertEqual(report.not_reproducible, ())
        mine = [check for check in report.outputs
                if check.operation_uid in (self.compile_1, self.verify_1)]
        self.assertEqual(
            sorted(check.role for check in mine if check.operation_uid == self.compile_1),
            sorted(family.role for family in masks_provenance.FAMILIES))
        self.assertEqual(sorted(check.role for check in mine if check.operation_uid
                                == self.verify_1), ["groups", "table", "violations_2"])
        self.assertTrue(all(check.same for check in mine), mine)
        self.assertTrue(all(check.reproduced_sha256 == check.frozen_sha256 for check in mine))
        for uid in (self.compile_1, self.verify_1):
            reproduced = {(check.key, figures_mod.scope_json(check.scope)): check.reproduced
                          for check in report.figures if check.operation_uid == uid}
            self.assertEqual(
                reproduced, {key: value for key, (value, _kind) in self.figures_before[uid].items()},
                uid)
        self.assertTrue(report.matches)

    def test_e_v02_without_a_row_reads_the_project_value(self) -> None:
        """RF-012-16 (D-4): V02, sin fila de versión, compiló con el resguardo del proyecto
        (6 m): lo anotó con su ámbito, su zona es la de ``combine`` con ese valor y el cambio de
        V01 no la movió."""
        with self.project.read() as conn:
            resolved = params.ParameterStore(self.project).resolve(
                conn, TOWER_KEY, ("version", "project"), version=self.v2.code)
        self.assertEqual((resolved.scope, resolved.scope_uid, resolved.value),
                         ("project", "", cp.TOWER_PROJECT_M))
        used = {key: (scope, scope_uid, json.loads(value)) for key, scope, scope_uid, value in
                self.query("SELECT p.key, g.scope, g.scope_uid, p.value FROM gb_operation_param "
                           "AS p JOIN gb_parameter AS g ON g.uid = p.parameter_uid WHERE "
                           "p.operation_uid = ?", self.compile_2)}
        self.assertEqual(used[TOWER_KEY], ("project", "", cp.TOWER_PROJECT_M))
        v1_used = {key: (scope, scope_uid, json.loads(value)) for key, scope, scope_uid, value in
                   self.query("SELECT p.key, g.scope, g.scope_uid, p.value FROM "
                              "gb_operation_param AS p JOIN gb_parameter AS g ON g.uid = "
                              "p.parameter_uid WHERE p.operation_uid = ?", self.compile_1)}
        self.assertEqual(v1_used[TOWER_KEY][:2], ("version", self.v1.uid))
        self.assertEqual(v1_used[TOWER_KEY][2], cp.TOWER_V01_M)
        masks = access.load_masks(self.project, self.v2.uid)
        self.assertEqual(masks.zone("torre"), self.tower_cells(cp.TOWER_PROJECT_M))
        self.assertLess(masks.zone("torre").cells, fx.TOWER_ZONE_CELLS)
        self.assertEqual(self.outputs(self.v2), self.v2_before)


if __name__ == "__main__":
    unittest.main()
