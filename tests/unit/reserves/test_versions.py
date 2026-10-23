# SPDX-License-Identifier: GPL-3.0-or-later
"""La cubicación y las versiones: obsoleta, recalcular, congelar y reproducir (spec 011, T15;
RF-011-20, RF-011-21; CE-011-04; plan 011 A12, D-16, D-19, D-38).

Sobre el proyecto de ``tests.support.res_fixtures`` (una copia por clase) con la columna
sintética guardada (``res.edit_materials``) y sus densidades, sus K y sus porcentajes en el
proyecto. El recálculo de cada tipo es :func:`_recompute`, la función de prueba: empieza la
operación nueva con ``reserves.store.recompute_run`` y avanza sus pasos hasta el final (la de
``bl``, T19, los deja en la cola de ``res``). Reproducir, con las funciones de
``reserves.reproduce``.
"""

from __future__ import annotations

import json
import math
import unittest
from collections.abc import Iterable, Iterator
from typing import Any, ClassVar

from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files

provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
res_reproduce = import_geoblender("reserves.reproduce")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
params = import_geoblender("reserves.params")
operations = import_geoblender("core.provenance.operations")
graph = import_geoblender("core.provenance.graph")
recompute = import_geoblender("core.provenance.recompute")
figures_mod = import_geoblender("core.provenance.figures")
contract = import_geoblender("core.provenance.contract")
freeze = import_geoblender("core.versions.freeze")
reproduce = import_geoblender("core.versions.reproduce")

START = surfaces.SurfaceRef(dataset=fx.START_GRID, label="Partida")
FINAL = surfaces.SurfaceRef(dataset=fx.FINAL_GRID, label="Final")
FLOOR = surfaces.SurfaceRef(elevation=600.0, label="Cota 600")
K_V01 = 1.30
"""El K de la montera solo en V01 (el del proyecto, el de la columna sintética: 1,25)."""
MONTERA = "montera"
CHANGED = graph.CauseKind.DATASET_CHANGED
PARAMETER = graph.CauseKind.PARAMETER_CHANGED


def _last(steps: Iterator[Any]) -> Any:
    """El resultado del último paso de ``steps``."""
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def _recompute(request: Any) -> Any:
    """La función de recálculo de prueba de ``res.volume``, ``res.tonnage`` y
    ``res.difference``: la operación nueva de ``reserves.store.recompute_run`` con sus pasos
    avanzados hasta el final."""
    handle, steps = store.recompute_run(request)
    _last(steps)
    return handle


class _VersionsCase(fx.ResProjectCase):
    """El proyecto de la cubicación con la columna guardada y sus parámetros en el proyecto."""

    recompute: ClassVar[Any] = {op_type: _recompute for op_type in (
        provenance.VOLUME, provenance.TONNAGE, provenance.DIFFERENCE)}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.column = fx.project_column()
        cls.declare(fx.column_values())
        cls.save_column(cls.column)

    @classmethod
    def save_column(cls, column: Any) -> None:
        """``res.edit_materials``: la columna ``column`` en el proyecto."""
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(cls.project, provenance.EDIT_MATERIALS,
                                            settings={"units": len(column.units)},
                                            executor="blender")
        store.save_materials(cls.project, handle, column)

    @classmethod
    def begin(cls, op_type: str, request: Any, version: Any) -> Any:
        """La operación ``op_type`` «en curso» en ``version`` con lo que anotan sus ayudas."""
        if op_type == provenance.TONNAGE:
            values = {"settings": provenance.tonnage_settings(request),
                      "inputs": provenance.tonnage_inputs(request),
                      "params": provenance.tonnage_params(cls.column)}
        else:
            values = {"settings": provenance.volume_settings(request),
                      "inputs": provenance.volume_inputs(request),
                      "params": provenance.volume_params(request)}
        cls.clock.advance(minutes=1)
        return operations.begin_operation(cls.project, op_type, executor="blender",
                                          version=version.uid, **values)

    @classmethod
    def cubicate(cls, name: str, version: Any, *, grid: bool = False) -> tuple[str, str]:
        """``res.volume`` (con la columna; con ``grid``, también la rejilla) y ``res.tonnage``
        de la cubicación ``name`` en ``version``: sus uid."""
        request = volumes.VolumeRequest(name, START, FINAL, column=cls.column,
                                        difference_grid=grid)
        volume = cls.begin(provenance.VOLUME, request, version)
        _last(store.volume_run(cls.project, volume, request))
        tonnage = cls.begin(provenance.TONNAGE, name, version)
        _last(store.tonnage_run(cls.project, tonnage))
        return volume.uid, tonnage.uid

    # --- Lo que se mira -------------------------------------------------------------------

    def stale(self) -> dict[str, frozenset[Any]]:
        """Las operaciones obsoletas sin sustituir con sus causas (``deduce`` de la 008)."""
        with self.project.read() as conn:
            return dict(graph.deduce(graph.load_graph(conn)).operations)

    def recompute_all(self) -> Any:
        """«Recalcular lo obsoleto» hasta el final: su ``RecomputeOutcome``."""
        self.clock.advance(minutes=1)
        return _last(recompute.recompute_steps(self.project))

    def operation(self, uid: str) -> dict[str, Any]:
        columns = ("op_type", "status", "revision_uid", "supersedes_uid", "superseded_by")
        (row,) = self.query(f"SELECT {', '.join(columns)} FROM gb_operation WHERE uid = ?", uid)
        return dict(zip(columns, row, strict=True))

    def open_revision(self, version: Any) -> str:
        (row,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND "
                            "state = 'open'", version.uid)
        return str(row[0])

    def figures(self, uids: Iterable[str]) -> dict[tuple[str, str, str], float]:
        """(operación, clave, ámbito JSON) → valor de las cifras de las operaciones ``uids``."""
        found: dict[tuple[str, str, str], float] = {}
        for uid in uids:
            for key, scope, value in self.query(
                    "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid):
                found[(uid, key, scope)] = value
        return found

    def figure(self, uid: str, key: str, **scope: Any) -> float:
        """La cifra ``key`` de la operación ``uid`` con el ámbito ``scope``."""
        (row,) = self.query("SELECT value FROM gb_figure WHERE operation_uid = ? AND key = ? "
                            "AND scope = ?", uid, key, figures_mod.scope_json(scope))
        return float(row[0])

    def param_read(self, uid: str, key: str) -> tuple[str, str, Any]:
        """(ámbito, versión, valor) del parámetro ``key`` que leyó la operación ``uid``."""
        (row,) = self.query(
            "SELECT p.scope, g.scope_uid, p.value FROM gb_operation_param AS p JOIN "
            "gb_parameter AS g ON g.uid = p.parameter_uid WHERE p.operation_uid = ? AND "
            "p.key = ?", uid, key)
        return str(row[0]), str(row[1]), json.loads(row[2])

    def parameter_uids(self, key: str) -> set[str]:
        return {str(row[0]) for row in self.query("SELECT uid FROM gb_parameter WHERE key = ?",
                                                  key)}

    def dataset_uid(self, name: str) -> str:
        return self.record(name).uid

    def assertDone(self, outcome: Any, count: int) -> tuple[str, ...]:  # noqa: N802
        """Las ``count`` unidades de ``outcome`` recalculadas, sin nada que quede: las
        operaciones nuevas, en orden."""
        self.assertEqual([result.status for result in outcome.results],
                         [recompute.UnitStatus.DONE] * count,
                         [result.reason for result in outcome.results])
        self.assertEqual(outcome.remaining.units, ())
        return tuple(uid for result in outcome.results for uid in result.operations)


class CascadeTest(_VersionsCase):
    """La cascada de la 008 en las dos operaciones encadenadas de V01 y de V02 (D-16)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.v01 = cls.cubicate("Mensual", cls.v1)
        cls.v02 = cls.cubicate("Mensual", cls.v2)

    def test_changes_leave_it_stale_and_recompute_redoes_it_in_its_version(self) -> None:
        """RF-011-20, RF-011-21 (RF-008-24, RF-008-26, RF-009-24; D-16): un K declarado solo
        en V01 deja obsoleto solo ``res.tonnage`` de V01 (los m³ in situ y V02 no), con su
        causa; recalcularlo registra la operación nueva en la revisión abierta de V01, que
        sustituye a la anterior, lee el K de V01 y cambia los m³ esponjados de la montera.
        Cambiar la columna deja obsoletas las cuatro (la columna, su causa) y cambiar la
        superficie final, además, los dos ``res.volume`` (la superficie, su causa); recalcular
        lo obsoleto las rehace cada una en la revisión abierta de su versión, y nada queda
        obsoleto."""
        volume_1, tonnage_1 = self.v01
        volume_2, tonnage_2 = self.v02
        self.assertEqual(self.stale(), {})

        self.declare({params.swell_key(MONTERA): K_V01}, version=self.v1)
        found = self.stale()
        self.assertEqual(set(found), {tonnage_1})
        self.assertEqual({cause.kind for cause in found[tonnage_1]}, {PARAMETER})
        self.assertTrue({cause.subject for cause in found[tonnage_1]}
                        <= self.parameter_uids(params.swell_key(MONTERA)))

        (redone,) = self.assertDone(self.recompute_all(), 1)
        state = self.operation(redone)
        self.assertEqual((state["op_type"], state["status"], state["revision_uid"],
                          state["supersedes_uid"]),
                         (provenance.TONNAGE, "done", self.open_revision(self.v1), tonnage_1))
        self.assertEqual(self.operation(tonnage_1)["superseded_by"], redone)
        self.assertEqual(self.param_read(redone, params.swell_key(MONTERA)),
                         ("version", self.v1.uid, K_V01))
        unit = {"cubication": "Mensual", "unit": MONTERA}
        montera_m3 = self.figure(volume_1, "res.unit_volume_m3", **unit)
        before = self.figure(tonnage_1, "res.unit_swell_m3", **unit)
        after = self.figure(redone, "res.unit_swell_m3", **unit)
        self.assertTrue(math.isclose(before, montera_m3 * 1.25, rel_tol=1e-15))
        self.assertTrue(math.isclose(after, montera_m3 * K_V01, rel_tol=1e-15))
        self.assertEqual(self.figure(tonnage_2, "res.unit_swell_m3", **unit), before)
        self.assertEqual(self.stale(), {})

        column = type(self.column)(tuple(unit.renamed("Montera revisada")
                                         if unit.code == MONTERA else unit
                                         for unit in self.column.units))
        self.save_column(column)
        materials = self.dataset_uid(provenance.MATERIALS)
        found = self.stale()
        self.assertEqual(set(found), {volume_1, redone, volume_2, tonnage_2})
        for uid in found:
            self.assertIn(graph.Cause(CHANGED, materials), found[uid])
        self.clock.advance(minutes=1)
        fx.write_grids(self.project, [fx.moved_grid("Final", 1.0)], message="Final revisada")
        final = self.dataset_uid(fx.FINAL_GRID)
        found = self.stale()
        for uid in (volume_1, volume_2):
            self.assertEqual(found[uid], {graph.Cause(CHANGED, materials),
                                          graph.Cause(CHANGED, final)})

        made = self.assertDone(self.recompute_all(), 4)
        states = {uid: self.operation(uid) for uid in made}
        self.assertEqual(sorted((state["op_type"], state["supersedes_uid"], state["revision_uid"])
                                for state in states.values()),
                         sorted([(provenance.VOLUME, volume_1, self.open_revision(self.v1)),
                                 (provenance.VOLUME, volume_2, self.open_revision(self.v2)),
                                 (provenance.TONNAGE, redone, self.open_revision(self.v1)),
                                 (provenance.TONNAGE, tonnage_2, self.open_revision(self.v2))]))
        self.assertEqual(self.stale(), {})
        new_volume = next(uid for uid, state in states.items()
                          if state["supersedes_uid"] == volume_1)
        new_tonnage = next(uid for uid, state in states.items()
                           if state["supersedes_uid"] == redone)
        whole = {"cubication": "Mensual"}
        self.assertLess(self.figure(new_volume, "res.cut_m3", **whole),
                        self.figure(volume_1, "res.cut_m3", **whole))
        self.assertEqual(self.param_read(new_tonnage, params.swell_key(MONTERA)),
                         ("version", self.v1.uid, K_V01))


class FreezeAndReproduceTest(_VersionsCase):
    """CE-011-04: congelar V01.r1 y cambiar K solo en V01."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.volume, cls.tonnage = cls.cubicate("Entrega", cls.v1, grid=True)
        request = volumes.VolumeRequest("Diferencia", START, FLOOR, difference_grid=True)
        handle = cls.begin(provenance.DIFFERENCE, request, cls.v1)
        _last(store.volume_run(cls.project, handle, request))
        cls.difference = handle.uid

    def test_ce_011_04_frozen_figures_do_not_change_and_reproduce_the_same(self) -> None:
        """CE-011-04, RF-011-20, RF-011-21 (RF-009-07, RF-009-11; D-38): congelada V01.r1, un
        K de la montera solo en V01 deja obsoleta la cubicación de la revisión abierta (sus
        toneladas, no sus m³) y, recalculada en V01.r2, sus m³ esponjados cambian; las cifras
        de V01.r1 no cambian (las mismas filas, en su instantánea) y reproducirla da las mismas
        salidas (tablas y rejillas, con su hash) y las mismas cifras **bit a bit**, cada
        operación de ``res`` con su función de reproducir (lo de ``gis`` y la columna editada a
        mano, tomados de lo congelado), sin escribir nada en el proyecto."""
        mine = (self.volume, self.tonnage, self.difference)
        frozen = self.figures(mine)
        self.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega"))
        self.assertIsNotNone(outcome.frozen)
        r1 = str(outcome.frozen.uid)
        r2 = self.open_revision(self.v1)
        self.assertNotEqual(r1, r2)

        self.declare({params.swell_key(MONTERA): K_V01}, version=self.v1)
        found = self.stale()
        self.assertEqual(set(found), {self.tonnage})
        self.assertEqual({cause.kind for cause in found[self.tonnage]}, {PARAMETER})
        (redone,) = self.assertDone(self.recompute_all(), 1)
        self.assertEqual(self.operation(redone)["revision_uid"], r2)
        unit = {"cubication": "Entrega", "unit": MONTERA}
        self.assertNotEqual(self.figure(redone, "res.unit_swell_m3", **unit),
                            self.figure(self.tonnage, "res.unit_swell_m3", **unit))
        self.assertEqual(self.figures(mine), frozen)
        uids = {str(row[0]) for row in self.query(
            "SELECT item_uid FROM gb_revision_item WHERE revision_uid = ? AND "
            "item_kind = 'figure'", r1)}
        self.assertEqual(uids, {str(row[0]) for row in self.query(
            "SELECT uid FROM gb_figure WHERE operation_uid IN (?, ?, ?)", *mine)})

        for op_type in (provenance.VOLUME, provenance.TONNAGE, provenance.DIFFERENCE):
            self.assertIs(contract.OPERATIONS[op_type].reproduce,
                          res_reproduce.REPRODUCE[op_type])
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, r1))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        self.assertEqual(report.not_reproducible, ())
        self.assertEqual({(note.op_type, note.why) for note in report.taken_frozen},
                         {("gis.resample", reproduce.Why.MODULE),
                          (provenance.EDIT_MATERIALS, reproduce.Why.MANUAL)})
        self.assertEqual(sorted((check.op_type, check.role, check.same)
                                for check in report.outputs),
                         sorted([(provenance.VOLUME, "volumes", True),
                                 (provenance.VOLUME, "difference", True),
                                 (provenance.TONNAGE, "tonnage", True),
                                 (provenance.DIFFERENCE, "difference", True)]))
        reproduced = {(check.operation_uid, check.key, figures_mod.scope_json(check.scope)):
                      check.reproduced for check in report.figures}
        self.assertEqual(reproduced, frozen)  # bit a bit, no solo dentro de la tolerancia
        self.assertTrue(all(check.tolerance == provenance.FIGURE_TOLERANCE
                            for check in report.figures))
        self.assertTrue(report.matches)


if __name__ == "__main__":
    unittest.main()
