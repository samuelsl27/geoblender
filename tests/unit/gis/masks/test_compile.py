# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación de compilar las restricciones (spec 012, T10; RF-012-06, RF-012-11, RF-012-15,
RF-012-16, RF-012-28; plan 012 §5.2.3, A5, A11, D-24, D-36).

Sobre el proyecto de ``tests.support.constraints_project`` (una copia por clase), en V01:

- **RF-012-16**: ``gis.compile_constraints`` es una operación de la versión con sus entradas (las
  tres capas, los sectores y las búsquedas) y los parámetros de cada restricción resueltos
  versión → proyecto y anotados (el resguardo de la torre, de V01; los demás, del proyecto).
- **RF-012-11**: la rejilla de clases (GeoTIFF con el hash de su lector), las zonas en tramos de
  fila, el informe y las partes de la franja son las de ``gis.masks.combine`` sobre las mismas
  restricciones, y las cifras, CALCULADO, las del sitio (40.000, 34.400, 27.600 y 6.800 m²; la
  torre, 60 celdas de 4 m²).
- **RF-012-28**: cada paso, ≤ 0,05 s; cerrar los pasos o un fallo al confirmar no dejan nada (ni
  cifras, ni tablas, ni rejilla, ni temporal). Sin versión activa o en una SUPERADO, el rechazo
  de la 009, sin registrar nada.
- Compilar dos veces da lo mismo bit a bit (salidas y cifras).
- **RF-012-06 (A5, D-36)**: redibujar el perímetro (+1,43 ha, CE-012-04) y compilar da su
  polígono ganado y perdido (14.300 y 0 m²) y su zona ganada y perdida (celdas × 4 m²); lo que no
  cambió no sale.
- **RF-012-16 (reproducir)**: congelada V01.r1, reproducir da las mismas salidas y las mismas
  cifras bit a bit, sin escribir en el proyecto.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from typing import Any
from unittest import mock

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.package import import_geoblender
from tests.support.timing import drive_steps, least_of, raised_priority
from tests.support.versions_fixtures import change_counter, files

gis = import_geoblender("gis")
cparams = import_geoblender("core.constraints.params")
combine = import_geoblender("gis.masks.combine")
compile_mod = import_geoblender("gis.masks.compile")
provenance = import_geoblender("gis.masks.provenance")
store = import_geoblender("gis.masks.store")
operations = import_geoblender("core.provenance.operations")
registry = import_geoblender("core.datasets.registry")
figures_mod = import_geoblender("core.provenance.figures")
versions_model = import_geoblender("core.versions.model")
freeze = import_geoblender("core.versions.freeze")
reproduce = import_geoblender("core.versions.reproduce")

BUDGET_S = 0.05
CELL_M2 = fx.SITE_STEP_M ** 2
NAMES = tuple(provenance.dataset_name(family.code) for family in provenance.FAMILIES)


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


class _CompileCase(cp.ConstraintsProjectCase):

    def compile(self, version: Any) -> Any:
        """Compila ``version`` hasta el final: (``handle``, lo guardado)."""
        self.clock.advance(minutes=1)
        handle = store.begin_compile(self.project, version=version.uid)
        return handle, _last(store.compile_run(self.project, handle))

    def expected(self, version_value: float) -> Any:
        """Lo preparado y combinado de las restricciones guardadas, con el resguardo de la torre
        ``version_value``: (preparado, máscaras)."""
        resolved = dict(cp.project_values())
        resolved[cparams.buffer_out_key("torre")] = version_value
        prepared = combine.prepare(self.stored_constraints(), resolved, fx.SITE_GRID)
        return prepared, combine.combine(prepared.zones, prepared.limits, fx.SITE_GRID)

    def figures(self, uid: str) -> dict[tuple[str, str], tuple[float, str]]:
        return {(key, scope): (value, kind) for key, scope, value, kind in self.query(
            "SELECT key, scope, value, kind FROM gb_figure WHERE operation_uid = ?", uid)}

    def figure(self, uid: str, key: str, **scope: Any) -> float:
        return self.figures(uid)[(key, figures_mod.scope_json(scope))][0]

    def outputs(self, version: Any) -> dict[str, Any]:
        return {name: self.record(name, version) for name in NAMES}


class CompileTest(_CompileCase):
    """Compilar V01 (y otra vez, igual)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        runs: list[Any] = []

        def longest() -> float:
            cls.clock.advance(minutes=1)
            handle = store.begin_compile(cls.project, version=cls.v1.uid)
            with raised_priority():
                run = drive_steps(store.compile_run(cls.project, handle))
            runs.append((handle, run))
            return run.longest_s

        cls.longest = least_of(longest, BUDGET_S, max_attempts=3)
        cls.handle, run = runs[-1]
        cls.stored = run.result
        helper = cls("test_steps_within_budget")
        cls.first = {name: record.content_sha256
                     for name, record in helper.outputs(cls.v1).items()}
        cls.first_figures = helper.figures(cls.handle.uid)
        cls.again, cls.stored_again = helper.compile(cls.v1)

    def test_steps_within_budget(self) -> None:
        """RF-012-28: ningún paso pasa de 0,05 s."""
        self.assertLessEqual(self.longest, BUDGET_S, f"un paso tardó {self.longest * 1000:.0f} ms")

    def test_version_operation_with_inputs_and_params(self) -> None:
        """RF-012-16 (RF-009-05, RF-009-24): de V01, en su revisión abierta, con las tres capas,
        los sectores y las búsquedas como entradas y los parámetros de cada restricción
        resueltos versión → proyecto."""
        (row,) = self.query("SELECT o.op_type, o.status, r.version_uid, o.revision_uid FROM "
                            "gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
                            "WHERE o.uid = ?", self.handle.uid)
        self.assertEqual(row[:3], (provenance.COMPILE, "done", self.v1.uid))
        (open_rev,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND "
                                 "state = 'open'", self.v1.uid)
        self.assertEqual(row[3], open_rev[0])
        roles = {role: name for role, name in self.query(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'",
            self.handle.uid)}
        self.assertEqual(roles, {"constraints_polygon": "core_constraint_polygon",
                                 "constraints_line": "core_constraint_line",
                                 "constraints_point": "core_constraint_point",
                                 "sectors": "core_sector",
                                 "searches": "core_untouchable_search"})
        read = {key: (scope, scope_uid, json.loads(value)) for key, scope, scope_uid, value in
                self.query("SELECT p.key, p.scope, g.scope_uid, p.value FROM gb_operation_param "
                           "AS p JOIN gb_parameter AS g ON g.uid = p.parameter_uid WHERE "
                           "p.operation_uid = ?", self.handle.uid)}
        self.assertEqual(set(read), set(cp.project_values()))
        self.assertEqual(read[cparams.buffer_out_key("torre")],
                         ("version", self.v1.uid, cp.TOWER_V01_M))
        self.assertEqual(read[cparams.buffer_in_key("concesion")],
                         ("project", "", cp.LEGAL_INWARD_M))

    def test_outputs_match_combine(self) -> None:
        """RF-012-11 (D-24): la rejilla de clases (con el hash de su lector), las zonas en
        tramos, el informe, las partes de la franja y las cifras CALCULADO."""
        prepared, masks = self.expected(cp.TOWER_V01_M)
        records = self.outputs(self.v1)
        self.assertTrue(all(record is not None for record in records.values()))
        classes = records[provenance.dataset_name(provenance.CLASSES)]
        self.assertEqual(classes.locator, "rasters/gis_msk_v01.tif")
        self.assertEqual(classes.reader, "gis.geotiff@1")
        with self.project.read() as conn:
            for record in records.values():
                self.assertEqual(registry.content_digest(conn, self.project, record)
                                 .content_sha256, record.content_sha256, record.name)
            zones = store.read_zone_runs(conn, records["gis_mskz"].locator)
            report = store.read_report(conn, records["gis_mskr"].locator)
            parts = conn.execute(f'SELECT area_m2 FROM "{records["gis_mskp"].locator}"'
                                 ).fetchall()
        raster = gis.Raster(fx.SITE_GRID, masks.classes.astype("float64"), fx.CRS, fx.VERTICAL)
        digest = import_geoblender("gis.content").raster_digest(raster, {})
        self.assertEqual(digest.content_sha256, classes.content_sha256)
        for code, zone in prepared.zones.items():
            self.assertEqual(zones[code], zone.runs, code)
        self.assertEqual(zones["concesion:inner"], prepared.limits.legal.band)
        self.assertEqual(zones["torre"].cells, fx.TOWER_ZONE_CELLS)
        self.assertEqual(parts, [(6_800.0,)])
        uid = self.handle.uid
        hand = {"gis.legal_area_m2": 40_000.0, "gis.perimeter_area_m2": 34_400.0,
                "gis.limits_intersection_m2": 27_600.0, "gis.fill_strip_area_m2": 6_800.0,
                "gis.default_domain_m2": masks.default_domain.area(fx.SITE_GRID),
                "gis.cut_allowed_m2": masks.cut_allowed.area(fx.SITE_GRID),
                "gis.fill_allowed_m2": masks.fill_allowed.area(fx.SITE_GRID),
                "gis.no_movement_m2": masks.no_movement_m2}
        for key, value in hand.items():
            self.assertAlmostEqual(self.figure(uid, key), value, delta=value * 1e-9, msg=key)
        self.assertEqual(self.figure(uid, "gis.zone_area_m2", constraint="torre"),
                         fx.TOWER_ZONE_CELLS * CELL_M2)
        self.assertEqual({kind for _value, kind in self.figures(uid).values()}, {"CALCULADO"})
        quantities = {(row[0], row[1]) for row in report}
        self.assertIn(("", "legal_area"), quantities)
        self.assertIn(("torre", "zone_area"), quantities)

    def test_twice_gives_the_same_bits(self) -> None:
        """Compilar otra vez lo mismo sustituye a la anterior con las mismas salidas y las
        mismas cifras, bit a bit, sin ganado ni perdido."""
        (row,) = self.query("SELECT supersedes_uid FROM gb_operation WHERE uid = ?",
                            self.again.uid)
        self.assertEqual(row[0], self.handle.uid)
        now = {name: record.content_sha256 for name, record in self.outputs(self.v1).items()}
        self.assertEqual(now, self.first)
        self.assertEqual(self.figures(self.again.uid), self.first_figures)
        self.assertEqual(self.stored_again.result.changes, ())


class ChangesTest(_CompileCase):
    """RF-012-06: redibujar el perímetro y compilar."""

    def test_redrawn_perimeter_gives_gained_and_lost(self) -> None:
        """RF-012-06 (A5, D-36; CE-012-04): +14.300 m² de polígono y la zona ganada en celdas;
        nada perdido; las demás restricciones, sin filas de cambio."""
        self.compile(self.v1)
        _prepared, _masks = self.expected(cp.TOWER_V01_M)
        before = _prepared.zones["perimetro"].runs
        (perimeter,) = [c for c in self.stored_constraints() if c.code == "perimetro"]
        redrawn = cp.constraints(perimeter=fx.REDRAWN_PERIMETER_LOCAL)[1]
        self.clock.advance(minutes=1)
        cp.edit_constraints(self.project, [type(redrawn)(**{
            **{f: getattr(redrawn, f) for f in redrawn.__dataclass_fields__},
            "uid": perimeter.uid, "fid": perimeter.fid})])
        handle, stored = self.compile(self.v1)
        after = self.expected(cp.TOWER_V01_M)[0].zones["perimetro"].runs
        (change,) = stored.result.changes
        self.assertEqual(change.code, "perimetro")
        limits = fx.limits()
        self.assertAlmostEqual(change.polygon_gained_m2, limits.gained_m2, delta=1e-6)
        self.assertEqual(change.polygon_lost_m2, 0.0)
        self.assertEqual(change.zone_gained_m2, after.difference(before).cells * CELL_M2)
        self.assertGreater(change.zone_gained_m2, 0.0)
        self.assertEqual(change.zone_lost_m2, 0.0)
        record = self.record("gis_mskr", self.v1)
        with self.project.read() as conn:
            report = store.read_report(conn, record.locator)
        rows = {(r[0], r[1]): r[2] for r in report if r[1].startswith(("polygon_", "zone_g",
                                                                        "zone_l"))}
        self.assertEqual(set(rows), {("perimetro", "polygon_gained"), ("perimetro", "polygon_lost"),
                                     ("perimetro", "zone_gained"), ("perimetro", "zone_lost")})
        self.assertEqual(rows[("perimetro", "zone_gained")], change.zone_gained_m2)
        self.assertEqual(self.figure(handle.uid, "gis.perimeter_area_m2"),
                         limits.redrawn_area_m2)


class RejectAndCancelTest(_CompileCase):
    """RF-012-16 (versión editable) y RF-012-28 (nada a medias)."""

    def assertNothing(self, before: Any, count: int) -> None:  # noqa: N802
        self.assertEqual(self.query("SELECT count(*) FROM gb_figure")[0][0], count)
        self.assertEqual(self.outputs(self.v1), dict.fromkeys(NAMES))
        self.assertEqual(files(self.root, skip=(), skip_dirs=("cache",)).keys() - before, set())
        tables = {row[0] for row in self.query("SELECT name FROM sqlite_master")}
        self.assertFalse(any(name.startswith("gis_msk") for name in tables))

    def test_cancel_or_fail_leave_nothing(self) -> None:
        """RF-012-28: cerrar los pasos a mitad deja la operación «cancelada»; fallar al
        confirmar, «fallida»; ninguna deja cifras, tablas, rejilla ni temporal."""
        before = set(files(self.root, skip=(), skip_dirs=("cache",)))
        count = self.query("SELECT count(*) FROM gb_figure")[0][0]
        handle = store.begin_compile(self.project, version=self.v1.uid)
        steps = store.compile_run(self.project, handle, budget_s=0.001)
        next(steps)
        next(steps)
        steps.close()
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("cancelled",)])
        self.assertNothing(before, count)

        handle = store.begin_compile(self.project, version=self.v1.uid)
        with mock.patch.object(operations.OperationHandle, "complete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                _last(store.compile_run(self.project, handle))
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("failed",)])
        self.assertNothing(before, count)

    def test_needs_an_editable_version(self) -> None:
        """RF-012-16 (RF-009-05, RF-009-04): sin versión, ``core.version_required``; en una
        SUPERADO, su texto; ninguna registra nada."""
        count = self.query("SELECT count(*) FROM gb_operation")
        with self.assertRaises(versions_model.VersionError) as caught:
            store.begin_compile(self.project, version=None)
        self.assertEqual(caught.exception.code, "core.version_required")
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v2.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", ("Prueba de la 012", self.v2.uid))
        with self.assertRaises(versions_model.VersionError) as caught:
            store.begin_compile(self.project, version=self.v2.uid)
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)


class ReproduceTest(_CompileCase):
    """RF-012-16: congelar V01.r1 y reproducir."""

    def test_reproduce_frozen_gives_the_same(self) -> None:
        """RF-012-16 (RF-009-07, RF-009-11): las mismas salidas (con su hash) y las mismas
        cifras bit a bit, sin escribir nada en el proyecto."""
        handle, _stored = self.compile(self.v1)
        frozen = self.figures(handle.uid)
        self.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega"))
        r1 = str(outcome.frozen.uid)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, r1))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        self.assertEqual(report.not_reproducible, ())
        mine = [check for check in report.outputs if check.op_type == provenance.COMPILE]
        self.assertEqual(sorted(check.role for check in mine),
                         sorted(family.role for family in provenance.FAMILIES))
        self.assertTrue(all(check.same for check in mine), mine)
        reproduced = {(check.key, figures_mod.scope_json(check.scope)): check.reproduced
                      for check in report.figures if check.operation_uid == handle.uid}
        self.assertEqual(reproduced, {key: value for key, (value, _kind) in frozen.items()})
        self.assertTrue(report.matches)


if __name__ == "__main__":
    unittest.main()
