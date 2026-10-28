# SPDX-License-Identifier: GPL-3.0-or-later
"""El contrato de los operadores: pedir las máscaras de una versión (spec 012, T11;
RF-012-10, RF-012-17; plan 012 §5.3.1, A12, D-26, D-43; ADR-0028).

Sobre el proyecto de ``tests.support.constraints_project`` (una copia por clase), en V01, con una
operación de prueba de otro módulo (``des.test``, de versión, declarada aquí):

- **RF-012-17**: sin compilar, el estado es «no existen» y ``load_masks`` las rechaza;
  ``ensure_masks_steps`` compila antes como operación propia (D-15, D-43) y da un ``MaskSet`` al
  día: cada máscara por su tipo (la de ``gis.masks.combine`` sobre las mismas restricciones), cada
  zona por su código, el peso de las «preferible no afectar» y sus ``Use``, que quedan como
  entradas de ``des.test``. Cambiar un resguardo deja obsoleta ``des.test`` y las máscaras:
  ``load_masks`` las rechaza y ``ensure_masks_steps`` vuelve a compilar.
- **RF-012-10** (A12, D-26): mientras un sector no tiene búsqueda vigente, el ``MaskSet`` lleva la
  marca con su código y su nombre, calculada al vuelo; una búsqueda de su misma geometría la quita
  y una obsoleta no cuenta.
- **D-43**: si no se puede compilar (sin límite legal activo), la que pide se rechaza con lo mismo,
  sin registrar nada.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from typing import Any

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

access = import_geoblender("gis.masks.access")
combine = import_geoblender("gis.masks.combine")
provenance = import_geoblender("gis.masks.provenance")
cparams = import_geoblender("core.constraints.params")
cmodel = import_geoblender("core.constraints.model")
cstore = import_geoblender("core.constraints.store")
cmessages = import_geoblender("core.constraints.messages")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
params = import_geoblender("core.params")

DESIGN_TYPE = "des.test"
"""La operación de prueba de otro módulo que pide las máscaras."""
BUDGET_S = 0.05
MASK_ROLES = {provenance.dataset_name(provenance.CLASSES): "masks_classes",
              provenance.dataset_name(provenance.ZONES): "masks_zones",
              provenance.dataset_name(provenance.REPORT): "masks_report"}
SECTOR_NAMES = tuple(fx.SECTORS_LOCAL)


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


class AccessTest(cp.ConstraintsProjectCase):
    """El ciclo de un operador sobre V01: pedir, usar, quedar obsoleto y volver a pedir."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        design = contract.OperationDef(DESIGN_TYPE, "1.0", "des", "Design of the tests", False,
                                       scope="version")
        cls.enterClassContext(registered(design))

    def compiles(self) -> list[str]:
        return [row[0] for row in self.query(
            "SELECT uid FROM gb_operation WHERE op_type = ? ORDER BY rowid", provenance.COMPILE)]

    def stale(self, uid: str) -> bool:
        return bool(self.query("SELECT 1 FROM gb_stale WHERE item_kind = 'operation' AND "
                               "item_uid = ?", uid))

    def design(self, masks: Any) -> str:
        """``des.test`` en V01 con las máscaras como entradas; devuelve su uid."""
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, DESIGN_TYPE, settings={},
                                            inputs=masks.uses(), executor="blender",
                                            version=self.v1.uid)
        with self.project.write_transaction() as conn:
            handle.complete(conn, message="Diseño de prueba")
        return handle.uid

    def change_tower(self, value: float) -> None:
        self.clock.advance(minutes=1)
        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.change(conn, cparams.buffer_out_key("torre"), value=value,
                         reason="Prueba del contrato", version=self.v1.code)

    def close_search(self, sector: Any) -> None:
        """Una búsqueda cerrada de ``sector`` (con su huella), escrita por la operación de prueba
        de las restricciones."""
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, cp.EDIT_TYPE, settings={"count": 0},
                                            executor="blender")
        record = cmodel.SearchRecord(f"search{'0' * 26}", handle.uid, sector.code,
                                     cstore.sector_sha256(sector), fx.SEARCH_DISTANCE_M,
                                     "Samuel (IMGA)", "2026-10-28T10:00:00Z")
        with self.project.write_transaction() as conn:
            cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cstore.dataset_specs(
                crs_epsg=self.project.record.crs_epsg), message="Búsqueda de prueba")

    def assertMasks(self, masks: Any, tower_m: float) -> None:  # noqa: N802
        resolved = dict(cp.project_values())
        resolved[cparams.buffer_out_key("torre")] = tower_m
        prepared = combine.prepare(self.stored_constraints(), resolved, fx.SITE_GRID)
        expected = combine.combine(prepared.zones, prepared.limits, fx.SITE_GRID)
        shape = fx.SITE_GRID.shape
        self.assertEqual(masks.grid, fx.SITE_GRID)
        self.assertEqual(masks.classes.dtype.name, "uint16")
        self.assertTrue((masks.classes == expected.classes).all())
        for name in ("default_domain", "cut_allowed", "fill_allowed", "fill_strip"):
            found = getattr(masks, name)()
            self.assertEqual(found.dtype, bool, name)
            self.assertTrue((found == getattr(expected, name).mask(shape)).all(), name)
        for code, zone in prepared.zones.items():
            self.assertEqual(masks.zone(code), zone.runs, code)
        self.assertEqual(masks.zone("torre").cells,
                         fx.TOWER_ZONE_CELLS if tower_m == cp.TOWER_V01_M else
                         prepared.zones["torre"].runs.cells)
        self.assertEqual(dict(masks.avoid_weights()), {})
        with self.assertRaises(KeyError):
            masks.zone("no_existe")

    def test_operator_cycle(self) -> None:
        """RF-012-17 y RF-012-10: el ciclo entero (véase el módulo)."""
        v1 = self.v1.uid
        # Sin compilar: «no existen» y no se entregan.
        state, pending = access.mask_state(self.project, v1)
        self.assertIs(state, access.MaskState.MISSING)
        self.assertEqual(pending, ("sector_1", "sector_2"))
        with self.assertRaises(access.MaskError) as caught:
            access.load_masks(self.project, v1)
        self.assertEqual(caught.exception.code, "core.constraint_masks_missing")
        self.assertIn(provenance.COMMAND, str(caught.exception))

        # Pedirlas compila antes, como operación propia (D-15, D-43), por pasos.
        masks = _last(access.ensure_masks_steps(self.project, v1, budget_s=BUDGET_S))
        (first,) = self.compiles()
        self.assertIsInstance(masks, access.MaskSet)
        self.assertIs(masks.state, access.MaskState.CURRENT)
        self.assertEqual((masks.version_uid, masks.operation_uid), (v1, first))
        self.assertEqual(masks.pending_sectors, ("sector_1", "sector_2"))
        self.assertEqual(masks.pending_names, SECTOR_NAMES)
        self.assertMasks(masks, cp.TOWER_V01_M)
        self.assertEqual(access.mask_state(self.project, v1)[0], access.MaskState.CURRENT)
        loaded = access.load_masks(self.project, v1)
        self.assertEqual(loaded.operation_uid, first)
        again = _last(access.ensure_masks_steps(self.project, v1, budget_s=BUDGET_S))
        self.assertEqual((again.operation_uid, self.compiles()), (first, [first]))

        # Sus Use quedan como entradas de la operación que las pide.
        uses = masks.uses()
        self.assertEqual(uses, access.mask_uses(masks))
        design = self.design(masks)
        roles = {name: role for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", design)}
        self.assertEqual(roles, MASK_ROLES)
        self.assertFalse(self.stale(design))

        # Cambiar un resguardo deja obsoletas las máscaras y la operación que las usó.
        self.change_tower(7.0)
        self.assertTrue(self.stale(design))
        self.assertEqual(access.mask_state(self.project, v1)[0], access.MaskState.STALE)
        with self.assertRaises(access.MaskError) as caught:
            access.load_masks(self.project, v1)
        self.assertEqual(caught.exception.code, "core.constraint_masks_stale")
        masks = _last(access.ensure_masks_steps(self.project, v1, budget_s=BUDGET_S))
        compiled = self.compiles()
        self.assertEqual(len(compiled), 2)
        self.assertEqual(masks.operation_uid, compiled[-1])
        self.assertIs(masks.state, access.MaskState.CURRENT)
        self.assertMasks(masks, 7.0)

        # La búsqueda del sector 1 quita su marca (al vuelo); la del 2 sigue.
        sector_1 = cp.sectors()[0]
        self.close_search(sector_1)
        state, pending = access.mask_state(self.project, v1)
        self.assertIs(state, access.MaskState.STALE)  # las búsquedas son entrada suya
        self.assertEqual(pending, ("sector_2",))
        masks = _last(access.ensure_masks_steps(self.project, v1, budget_s=BUDGET_S))
        self.assertEqual(masks.pending_sectors, ("sector_2",))
        self.assertEqual(masks.pending_names, SECTOR_NAMES[1:])
        (settings,) = self.query("SELECT settings FROM gb_operation WHERE uid = ?",
                                 masks.operation_uid)
        self.assertIn('"pending_sectors":["sector_2"]', settings[0].replace(" ", ""))

        # Una búsqueda obsoleta no cuenta (A12).
        (search_op,) = self.query("SELECT operation_uid FROM core_untouchable_search")
        with self.project.write_transaction() as conn:
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, "
                         "since) VALUES ('operation', ?, 'dataset_changed', ?, ?)",
                         (search_op[0], "x" * 32, "2026-10-28T10:00:00Z"))
        self.assertEqual(access.mask_state(self.project, v1)[1], ("sector_1", "sector_2"))

    def test_cannot_compile_rejects_the_same(self) -> None:
        """D-43 (RF-012-15): sin límite legal activo en V02, pedir las máscaras se rechaza como
        la compilación, sin registrar ninguna operación."""
        self.clock.advance(minutes=1)
        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.create(conn, cparams.active_key("concesion"), False, kind="ADOPTADO",
                         **cp.PARAMS_BY_HAND, reason="Prueba del contrato", version=self.v2.code)
        count = self.query("SELECT count(*) FROM gb_operation")
        with self.assertRaises(cmessages.ConstraintError) as caught:
            _last(access.ensure_masks_steps(self.project, self.v2.uid, budget_s=BUDGET_S))
        self.assertEqual(caught.exception.code, "core.constraint_no_legal_limit")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)


if __name__ == "__main__":
    unittest.main()
