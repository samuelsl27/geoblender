# SPDX-License-Identifier: GPL-3.0-or-later
"""La lista de las restricciones y el comienzo de la compilación por pasos (spec 012, T23;
HU-012-2, HU-012-4; RF-012-02, RF-012-03, RF-012-04, RF-012-06, RF-012-11, RF-012-19, RF-012-28;
plan 012 §5.3.4, §5.5).

Sobre el proyecto de ``tests.support.constraints_project`` (cinco restricciones, V01 y V02):

- **RF-012-04, RF-012-19, RF-012-02**: ``listed_constraints`` da de cada restricción su estado en
  la versión (activa, inactiva en ella, incompleta, no válida) y lo que la hace incompleta o no
  válida; la «activa» de una versión no cambia la otra.
- **RF-012-04**: una dibujada en QGIS (sin código, sin tipo, motivo ni decisor) es incompleta
  y una que se corta a sí misma, no válida.
- **RF-012-18 (RNF-012-05, T26)**: ``shown_constraints_steps`` da las mismas restricciones en el
  mismo orden, con «activa» o «inactiva» en la versión según su parámetro, sin comprobarlas
  (la dibujada a medias y la que se corta a sí misma, activas y sin problemas): lo que necesita
  «Ver restricciones y límites» sin pagar la comprobación de cada polígono.
- **RF-012-28 (RNF-012-06)**: ``begin_compile_steps`` parte lo que hacía ``begin_compile`` de una
  vez (la lectura, la comprobación de cada restricción y de cada polígono, la operación): da el
  mismo ``OperationHandle`` que ``begin_compile`` (mismas entradas, parámetros y ajustes), se
  rechaza como él sin registrar nada y, cerrado antes del final, no deja nada.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date
from typing import Any

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.package import import_geoblender

cparams = import_geoblender("core.constraints.params")
cstore = import_geoblender("core.constraints.store")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
store = import_geoblender("gis.masks.store")

T = model.ConstraintType
G = model.GeometryKind


def _drawn(name: str, parts: Any, *, kind: Any = G.POLYGON, code: str = "",
           ctype: Any = None, reason: str | None = None, decided_by: str | None = None) -> Any:
    """Una restricción tal como la deja QGIS al dibujarla: la geometría y poco más."""
    return model.Constraint(
        uid=uuid.uuid4().hex, code=code, name=name, ctype=ctype, kind=kind, parts=parts,
        priority=0, reason=reason, decided_by=decided_by, decided_on=date(2026, 10, 31),
        decision_uid=None, intention_uid=None, source_input=None, source_fid=None,
        layer=cstore.layer_of(kind), fid=0)


class ListedConstraintsTest(cp.ConstraintsProjectCase):
    """La lista de las cinco restricciones y de dos dibujadas a mano."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        bowtie = fx.absolute([(40.0, 40.0), (60.0, 60.0), (60.0, 40.0), (40.0, 60.0),
                              (40.0, 40.0)])
        rows = (_drawn("Sin acabar", ((fx.rectangle(120.0, 120.0, 140.0, 140.0),),)),
                _drawn("Corbata", ((bowtie,),), code="corbata", ctype=T.NO_CUT,
                       reason="Se corta a sí misma", decided_by="Samuel (IMGA)"))
        cp.edit_constraints(cls.project, rows)
        cp.declare(cls.project, cls.clock, {
            cparams.active_key("corbata"): True, cparams.buffer_out_key("corbata"): 3.0})
        cp.declare(cls.project, cls.clock, {cparams.active_key("balsa"): False},
                   version=cls.v2)

    def listed(self, version: Any) -> dict[str, Any]:
        """Lo listado en ``version``, por código (o nombre, las que no lo tienen)."""
        found = store.listed_constraints(self.project, version=version.uid)
        return {item.constraint.code or item.constraint.name: item for item in found}

    def test_every_constraint_with_its_state_in_the_version(self) -> None:
        """RF-012-19, RF-012-02: las siete restricciones; las cinco del proyecto, activas en
        V01; la «activa» solo de V02 deja «balsa» inactiva allí y activa en V01."""
        first, second = self.listed(self.v1), self.listed(self.v2)
        self.assertEqual(sorted(first),
                         ["Sin acabar", "balsa", "concesion", "corbata", "cuneta", "perimetro",
                          "torre"])
        for code in ("concesion", "perimetro", "torre", "cuneta"):
            self.assertEqual((first[code].state, second[code].state), ("active", "active"), code)
            self.assertEqual(first[code].problems, ())
        self.assertEqual((first["balsa"].state, second["balsa"].state), ("active", "inactive"))
        self.assertEqual(first["torre"].constraint.ctype, T.UNTOUCHABLE)
        # El orden de las capas (polígonos, líneas, puntos) y, en cada una, el de su fid.
        order = [item.constraint.layer for item in store.listed_constraints(
            self.project, version=self.v1.uid)]
        self.assertEqual(order, sorted(order, key=("core_constraint_polygon",
                                                   "core_constraint_line",
                                                   "core_constraint_point").index))

    def test_a_drawn_one_is_incomplete_and_a_crossed_one_is_not_valid(self) -> None:
        """RF-012-04: la dibujada en QGIS, sin código, tipo, motivo ni decisor, es incompleta
        y dice qué le falta; la que se corta a sí misma, no válida (y dice por qué); las dos
        impiden compilar."""
        found = self.listed(self.v1)
        drawn, crossed = found["Sin acabar"], found["corbata"]
        self.assertEqual(drawn.state, "incomplete")
        self.assertEqual([problem.problem for problem in drawn.problems],
                         ["core.constraint_no_code", "core.constraint_no_type",
                          "core.constraint_no_reason", "core.constraint_no_decider"])
        self.assertEqual(crossed.state, "invalid")
        self.assertEqual([problem.problem for problem in crossed.problems],
                         ["core.constraint_self_intersecting"])
        self.assertEqual(sorted(problem.problem for problem in combine.check(
            [item.constraint for item in found.values()],
            store.gather(self.project, version=self.v1.uid).request.resolved)),
            sorted(problem.problem for item in found.values() for problem in item.problems))

    def test_steps_do_the_same_and_the_version_none_reads_the_project(self) -> None:
        """RF-012-02: por pasos da lo mismo que de una vez; sin versión, los valores del
        proyecto (donde «balsa» está activa)."""
        steps = store.listed_constraints_steps(self.project, version=self.v2.uid)
        count = 0
        while True:
            try:
                next(steps)
                count += 1
            except StopIteration as stop:
                again = stop.value
                break
        self.assertGreaterEqual(count, 2)
        self.assertEqual([(item.constraint.uid, item.state) for item in again],
                         [(item.constraint.uid, item.state) for item in
                          store.listed_constraints(self.project, version=self.v2.uid)])
        project_only = {item.constraint.code or item.constraint.name: item.state
                        for item in store.listed_constraints(self.project)}
        self.assertEqual(project_only["balsa"], "active")


    def test_shown_constraints_skip_the_checks(self) -> None:
        """RF-012-18, RNF-012-05: para dibujarlas, las mismas siete restricciones en el mismo
        orden que la lista, con su «activa» en la versión (V02 desactiva «balsa»; sin versión, los
        valores del proyecto) y nada más: las incompletas y las no válidas, activas y sin
        problemas; por pasos (la lectura y uno más) y sin escribir nada."""
        operations = self.query("SELECT count(*) FROM gb_operation")
        for version in (self.v1, self.v2, None):
            uid = None if version is None else version.uid
            listed = store.listed_constraints(self.project, version=uid)
            steps = store.shown_constraints_steps(self.project, version=uid)
            count = 0
            while True:
                try:
                    next(steps)
                    count += 1
                except StopIteration as stop:
                    shown = stop.value
                    break
            self.assertGreaterEqual(count, 1)
            self.assertEqual([item.constraint.uid for item in shown],
                             [item.constraint.uid for item in listed])
            self.assertEqual([item.state for item in shown],
                             ["inactive" if item.state == "inactive" else "active"
                              for item in listed])
            self.assertEqual([item.problems for item in shown], [()] * len(listed))
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), operations)


class BeginCompileStepsTest(cp.ConstraintsProjectCase):
    """``begin_compile_steps`` frente a ``begin_compile``."""

    def counts(self) -> tuple[int, int]:
        return (self.query("SELECT count(*) FROM gb_operation")[0][0],
                self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'")[0][0])

    def drive(self, steps: Any) -> tuple[int, Any]:
        """Los pasos hasta el final: (cuántos, el ``OperationHandle``)."""
        count = 0
        while True:
            try:
                next(steps)
                count += 1
            except StopIteration as stop:
                return count, stop.value

    def test_same_operation_as_the_one_call_version(self) -> None:
        """RF-012-28, RNF-012-06: en varios pasos (la lectura, una comprobación por restricción
        y por polígono), con la misma operación que ``begin_compile``: tipo, versión, entradas,
        parámetros y ajustes."""
        self.clock.advance(minutes=1)
        steps, handle = self.drive(store.begin_compile_steps(self.project, version=self.v1.uid))
        self.assertGreaterEqual(steps, 6)
        self.clock.advance(minutes=1)
        other = store.begin_compile(self.project, version=self.v1.uid)
        for name in ("op_type", "version_uid", "params", "inputs", "executor"):
            self.assertEqual(getattr(handle, name), getattr(other, name), name)
        self.assertEqual(dict(handle.settings), dict(other.settings))
        other.cancel("prueba")
        handle.cancel("prueba")

    def test_closed_before_the_end_leaves_nothing(self) -> None:
        """RF-012-28: cerrar los pasos antes de que empiece la operación no deja ninguna."""
        before = self.counts()
        steps = store.begin_compile_steps(self.project, version=self.v1.uid)
        next(steps)
        next(steps)
        steps.close()
        self.assertEqual(self.counts(), before)

    def test_available_tables_are_the_registered_ones(self) -> None:
        """RF-012-16: lo que consumiría la compilación sin leer las restricciones: las tablas
        registradas (las tres capas y los sectores; aún no las búsquedas)."""
        found = store.available_tables(self.project)
        self.assertEqual(found, frozenset(cstore.TABLES))
        self.assertIn("core_constraint_polygon", found)


class BeginCompileRefusedTest(BeginCompileStepsTest):
    """Con una restricción dibujada en QGIS sin acabar (su propio proyecto)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cp.edit_constraints(cls.project, (_drawn("Sin acabar", (
            (fx.rectangle(120.0, 120.0, 140.0, 140.0),),)),))

    # Las del padre se prueban en el suyo, con el proyecto sin esa restricción.
    test_same_operation_as_the_one_call_version = None  # type: ignore[assignment]
    test_closed_before_the_end_leaves_nothing = None  # type: ignore[assignment]
    test_available_tables_are_the_registered_ones = None  # type: ignore[assignment]

    def test_refused_like_begin_compile_and_nothing_registered(self) -> None:
        """RF-012-04, RF-012-15: una restricción incompleta rechaza al ir por pasos, como
        ``begin_compile``, sin registrar ninguna operación; sin versión, también."""
        before = self.counts()
        with self.assertRaises(combine.IncompleteConstraints) as caught:
            self.drive(store.begin_compile_steps(self.project, version=self.v1.uid))
        with self.assertRaises(combine.IncompleteConstraints) as eager:
            store.begin_compile(self.project, version=self.v1.uid)
        self.assertEqual([item.problem for item in caught.exception.problems],
                         [item.problem for item in eager.exception.problems])
        with self.assertRaises(Exception) as missing:
            self.drive(store.begin_compile_steps(self.project, version=None))
        self.assertEqual(getattr(missing.exception, "code", ""), "core.version_required")
        self.assertEqual(self.counts(), before)


if __name__ == "__main__":
    unittest.main()
