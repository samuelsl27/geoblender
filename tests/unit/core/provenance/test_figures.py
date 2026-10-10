# SPDX-License-Identifier: GPL-3.0-or-later
"""Cifras con tipo y procedencia (spec 008, T19; RF-008-30, RF-008-59; plan 008 §5.3.1 y D15;
ADR-0025 §5).

``core.provenance.figures`` registra cada cifra que produce una operación en curso
(``record_figure`` u ``OperationHandle.complete(figures=…)``, antes de dejarla «hecha») con su
clave, su texto en español, su valor, su unidad del catálogo, su tipo, su operación y su ámbito.
Rechaza, nombrando su clave y su operación y sin escribir nada, una cifra sin tipo, sin unidad
del catálogo, sin operación en curso, NaN o infinita, y la cero o negativa que su ``FigureDef``
no admite (RF-008-30). Lo que calcula una operación es CALCULADO; una cifra que muestra un
parámetro lleva su tipo. Una cifra que calcula un parámetro y difiere de él deja el aviso de la
spec §8 (``divergences``), y **ningún parámetro cambia nunca**: ni su valor ni su tipo, tampoco
uno «sin confirmar» ni uno CALCULADO (RF-008-59; S-1, decisión de Samuel del 08/10/2026).

Cada prueba usa el proyecto sintético de ``test_operations`` (esquema 2, reloj simulado, tipos
y parámetros de prueba de ``res``) con las cifras de prueba registradas.
"""

from __future__ import annotations

import ast
import datetime as dt
import math
import re
import sqlite3
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.core.provenance.test_operations import (
    SOFTWARE,
    OperationsCase,
    _now,
    _table_spec,
    _write_table,
)

provenance = import_geoblender("core.provenance")
figures = import_geoblender("core.provenance.figures")
messages = import_geoblender("core.provenance.messages")
schema = import_geoblender("core.provenance.schema")
params = import_geoblender("core.params")
hashing = import_geoblender("core.hashing")
i18n = import_geoblender("core.i18n")

FigureSpec = figures.FigureSpec
ProvenanceError = messages.ProvenanceError

SELLABLE = provenance.FigureDef("res.sellable_t", "t", "Test sellable tonnes")
NET_FILL = provenance.FigureDef("res.net_fill", "m3", "Test net fill", allow_negative=True)
STRIP = provenance.FigureDef("res.strip_ratio", "-", "Test strip ratio", allow_zero=False)
SWELL_K = provenance.FigureDef("res.swell_factor", "-", "Test swell factor K")
RECOVERY_USED = provenance.FigureDef("res.recovery_used", "%", "Test recovery used")
RECOVERY_CALC = provenance.FigureDef("res.recovery_calc", "%", "Test recovery computed")
FIGURE_DEFS = (SELLABLE, NET_FILL, STRIP, SWELL_K, RECOVERY_USED, RECOVERY_CALC)
LABELS_ES = {
    "Test sellable tonnes": "Toneladas vendibles",
    "Test net fill": "Relleno neto",
    "Test strip ratio": "Ratio estéril/mineral",
    "Test swell factor K": "K",
    "Test recovery used": "Recuperación usada",
    "Test recovery computed": "Recuperación",
}

K = "res.swell_factor"
PROPERTY_DATE = dt.datetime(2026, 9, 24, 9, 31, tzinfo=dt.UTC)
UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
FIGURE_COLUMNS = ("key", "label", "value", "unit", "kind", "operation_uid", "parameter_uid",
                  "parameter_rev", "scope", "scope_key", "created_at")


def _json(value: object) -> str:
    return hashing.canonical_json(value).decode("utf-8")


def _scope_key(scope: Mapping[str, Any]) -> str:
    return hashing.sha256_bytes(hashing.canonical_json(scope))[:16]


class FiguresCase(OperationsCase):
    """El proyecto de ``OperationsCase`` con las cifras de prueba de ``res`` registradas."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(*FIGURE_DEFS))
        i18n.install(LABELS_ES)

    def snapshot(self) -> list[Any]:
        with self.project.read() as conn:
            stored = conn.execute("SELECT * FROM gb_figure ORDER BY fid").fetchall()
        return [*super().snapshot(), stored]

    def parameters(self) -> list[Any]:
        """Los parámetros del proyecto y su historial, tal como están guardados."""
        return self.query("SELECT * FROM gb_parameter ORDER BY fid") + self.query(
            "SELECT * FROM gb_parameter_history ORDER BY fid")

    def figure_rows(self, operation_uid: str) -> list[dict[str, Any]]:
        with self.project.read() as conn:
            cursor = conn.execute("SELECT * FROM gb_figure WHERE operation_uid = ? ORDER BY fid",
                                  (operation_uid,))
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def complete(self, handle: Any, specs: list[Any]) -> None:
        """Completa ``handle`` (``res.balance`` o ``res.survey``) con sus cifras, sin salidas."""
        software = SOFTWARE if handle.definition.libraries else None
        self.write(lambda conn: handle.complete(conn, figures=specs, software=software))

    def divergences(self, operation_uid: str) -> list[Any]:
        with self.project.read() as conn:
            return figures.divergences(conn, operation_uid)

    def set_k(self, value: float, kind: str = "ADOPTADO", **kw: Any) -> Any:
        """Una persona fija K (lo da de alta o lo cambia)."""
        values: dict[str, Any] = {"kind": kind, "source": "Acta de la propiedad",
                                  "source_kind": "document", "decided_by": "la propiedad",
                                  "decided_at": PROPERTY_DATE, "reason": "K de la propiedad"}
        values.update(kw)
        if self.store.get(K) is None:
            return self.write(lambda conn: self.store.create(conn, K, value, **values))
        return self.write(lambda conn: self.store.change(conn, K, value=value, **values))

    def rejected(self, error: type[BaseException], code: str | None, handle: Any,
                 spec: Any) -> BaseException:
        """``record_figure`` rechaza ``spec`` sin escribir nada: el rechazo se captura dentro
        de la transacción, que se confirma igual."""
        before = self.snapshot()

        def work(conn: sqlite3.Connection) -> BaseException:
            with self.assertRaises(error) as caught:
                figures.record_figure(conn, handle, spec)
            return caught.exception

        found = self.write(work)
        if code is not None:
            self.assertEqual(getattr(found, "code", None), code, str(found))
        self.assertTrue(self.project.writable)
        self.assertEqual(self.snapshot(), before)
        return found


class RecordTest(FiguresCase):
    def test_figures_recorded_with_kind_unit_operation_and_scope(self) -> None:
        """RF-008-30: una cifra de una operación en curso queda con su clave, su texto en
        español, su valor (float64; −0,0 es 0,0), su unidad del catálogo, CALCULADO, la
        operación que la produjo y su ámbito (JSON canónico y su clave de búsqueda), registrada
        con ``record_figure`` o al completar la operación, antes de dejarla «hecha»; la cero
        y la negativa, si su definición las admite."""
        handle = self.begin()
        self.tick()

        def work(conn: sqlite3.Connection) -> Any:
            _write_table(conn, "res_balance", [1.0])
            first = figures.record_figure(
                conn, handle, FigureSpec("res.strip_ratio", np.float32(2.5), "-",
                                         scope={"phase": "1"}))
            zero = figures.record_figure(conn, handle, FigureSpec(
                "res.sellable_t", -0.0, "t", kind="CALCULADO", scope={"phase": "2"}))
            handle.complete(conn, outputs=[_table_spec("res_balance", "balance")], figures=[
                FigureSpec("res.sellable_t", 1_234_567.5, "t", scope={"phase": "1", "bench": 125}),
                FigureSpec("res.net_fill", -350.25, "m3"),
            ], software=SOFTWARE)
            return first, zero

        first, zero = self.write(work)
        rows = self.figure_rows(handle.uid)
        at = _now(1)
        self.assertEqual(
            [tuple(row[name] for name in FIGURE_COLUMNS) for row in rows],
            [
                ("res.strip_ratio", "Ratio estéril/mineral", 2.5, "-", "CALCULADO", handle.uid,
                 None, None, _json({"phase": "1"}), _scope_key({"phase": "1"}), at),
                ("res.sellable_t", "Toneladas vendibles", 0.0, "t", "CALCULADO", handle.uid,
                 None, None, _json({"phase": "2"}), _scope_key({"phase": "2"}), at),
                ("res.sellable_t", "Toneladas vendibles", 1_234_567.5, "t", "CALCULADO",
                 handle.uid, None, None, '{"bench":125,"phase":"1"}',
                 _scope_key({"bench": 125, "phase": "1"}), at),
                ("res.net_fill", "Relleno neto", -350.25, "m3", "CALCULADO", handle.uid, None,
                 None, "{}", "", at),
            ],
        )
        for value in (zero.value, rows[1]["value"]):  # −0,0 → 0,0
            self.assertEqual(math.copysign(1.0, value), 1.0)
        self.assertEqual(len({row["uid"] for row in rows}), 4)
        for row in rows:
            self.assertRegex(row["uid"], UID)
        self.assertEqual(self.status(handle.uid), "done")
        self.assertEqual(
            (first.uid, first.key, first.label, first.value, first.unit, first.kind,
             first.operation_uid, first.parameter_uid, dict(first.scope), first.scope_key,
             first.created_at),
            (rows[0]["uid"], "res.strip_ratio", "Ratio estéril/mineral", 2.5, "-", "CALCULADO",
             handle.uid, None, {"phase": "1"}, _scope_key({"phase": "1"}), at),
        )
        with self.project.read() as conn:
            stored = conn.execute(f"SELECT {figures.RECORD_COLUMNS} FROM gb_figure WHERE uid = ?",
                                  (first.uid,)).fetchone()
        self.assertEqual(figures.FigureRecord.from_row(stored), first)
        self.assertEqual((figures.scope_key({}), figures.scope_key({"bench": 125, "phase": "1"})),
                         ("", _scope_key({"bench": 125, "phase": "1"})))
        self.assertEqual(self.divergences(handle.uid), [])


class RejectTest(FiguresCase):
    def test_rejected_naming_key_and_operation(self) -> None:
        """RF-008-30: una cifra sin tipo, sin unidad del catálogo (o en otra que la de su
        definición), sin valor, NaN o infinita, y la cero o negativa que su definición no
        admite, se rechaza sin escribir nada y el rechazo nombra su clave y su operación; lo
        que produce una operación sin mostrar un parámetro es CALCULADO."""
        handle = self.begin()
        error = self.rejected(ProvenanceError, "core.figure_nan", handle,
                              FigureSpec("res.sellable_t", math.nan, "t"))
        self.assertEqual(str(error), "La cifra «res.sellable_t» de la operación «res.balance» "
                                     "es NaN: revise sus entradas.")
        self.assertEqual((error.values["key"], error.values["op_type"]),
                         ("res.sellable_t", "res.balance"))
        cases = (
            ("core.figure_infinite", "res.sellable_t", math.inf, "t", {}),
            ("core.figure_infinite", "res.sellable_t", -math.inf, "t", {}),
            ("core.figure_infinite", "res.sellable_t", 10**400, "t", {}),
            ("core.figure_value_missing", "res.sellable_t", None, "t", {}),
            ("core.figure_kind_missing", "res.sellable_t", 1.0, "t", {"kind": None}),
            ("core.figure_kind_missing", "res.sellable_t", 1.0, "t", {"kind": " "}),
            ("core.figure_kind_unknown", "res.sellable_t", 1.0, "t", {"kind": "ESTIMADO"}),
            ("core.figure_kind_without_parameter", "res.sellable_t", 1.0, "t",
             {"kind": "ADOPTADO"}),
            ("core.figure_unit_missing", "res.sellable_t", 1.0, None, {}),
            ("core.figure_unit_missing", "res.sellable_t", 1.0, "", {}),
            ("core.figure_unit_unknown", "res.sellable_t", 1.0, "tn", {}),
            ("core.figure_unit_other", "res.sellable_t", 1.0, "kt", {}),
            ("core.figure_zero", "res.strip_ratio", 0.0, "-", {}),
            ("core.figure_zero", "res.strip_ratio", -0.0, "-", {}),
            ("core.figure_negative", "res.sellable_t", -1.5, "t", {}),
        )
        for code, key, value, unit, extra in cases:
            with self.subTest(code=code, value=value, unit=unit, extra=extra):
                error = self.rejected(ProvenanceError, code, handle,
                                      FigureSpec(key, value, unit, **extra))
                self.assertIn(f"«{key}»", str(error))
                self.assertIn("«res.balance»", str(error))
        texts = {
            "core.figure_infinite": "La cifra «res.sellable_t» de la operación «res.balance» es "
                                    "infinita: revise sus entradas.",
            "core.figure_zero": "La cifra «res.strip_ratio» de la operación «res.balance» es "
                                "cero y su definición no lo admite: revise sus entradas.",
            "core.figure_negative": "La cifra «res.sellable_t» de la operación «res.balance» es "
                                    "negativa (-1,5) y su definición no lo admite: revise sus "
                                    "entradas.",
            "core.figure_unit_other": "La cifra «res.sellable_t» de la operación «res.balance» "
                                      "está en «kt» y su definición la declara en «t».",
        }
        for code, text in texts.items():
            with self.subTest(code=code):
                self.assertEqual(messages.render(code, **self._values(code)), text)
        # Sin operación de origen, de una operación terminada o una cifra sin declarar.
        error = self.rejected(ProvenanceError, "core.figure_operation_missing", None,
                              FigureSpec("res.sellable_t", 1.0, "t"))
        self.assertEqual(str(error), "La cifra «res.sellable_t» no tiene operación de origen: "
                                     "solo la registra una operación en curso.")
        survey, _terrain = self.survey()
        error = self.rejected(ProvenanceError, "core.figure_operation_not_running", survey,
                              FigureSpec("res.sellable_t", 1.0, "t"))
        self.assertEqual(str(error), "La cifra «res.sellable_t» de la operación «res.survey» no "
                                     "se registra: la operación ya no está en curso.")
        failed = self.begin()
        failed.fail("prueba")
        self.rejected(ProvenanceError, "core.figure_operation_not_running", failed,
                      FigureSpec("res.sellable_t", 1.0, "t"))
        self.rejected(ProvenanceError, "core.figure_unregistered", handle,
                      FigureSpec("res.unknown_t", 1.0, "t"))
        self.assertEqual(self.figure_rows(handle.uid), [])
        self.assertEqual(self.status(handle.uid), "running")

    @staticmethod
    def _values(code: str) -> dict[str, Any]:
        key = "res.strip_ratio" if code == "core.figure_zero" else "res.sellable_t"
        return {"key": key, "op_type": "res.balance", "value": -1.5, "unit": "kt",
                "declared": "t"}

    def test_badly_formed_and_complete_writes_nothing(self) -> None:
        """RF-008-30: un argumento mal formado es un error del programa, sin escribir nada; una
        operación registra cada cifra (clave y ámbito) una vez; y si ``complete`` rechaza una
        de sus cifras, no registra ninguna, ni sus salidas, y la operación sigue en curso."""
        handle = self.begin()
        self.write(lambda conn: _write_table(conn, "res_balance", [1.0]))
        good = FigureSpec("res.sellable_t", 1.0, "t", scope={"phase": "1"})
        cases = (
            (TypeError, "res.sellable_t"),
            (TypeError, FigureSpec(1, 1.0, "t")),
            (TypeError, FigureSpec("res.sellable_t", "1,0", "t")),
            (TypeError, FigureSpec("res.sellable_t", True, "t")),
            (TypeError, FigureSpec("res.sellable_t", 1.0, "t", scope=[("phase", "1")])),
            (ValueError, FigureSpec("res.sellable_t", 1.0, "t", scope={"Fase": "1"})),
            (TypeError, FigureSpec("res.sellable_t", 1.0, "t", scope={"phase": True})),
            (TypeError, FigureSpec("res.sellable_t", 1.0, "t", scope={"phase": None})),
            (ValueError, FigureSpec("res.sellable_t", 1.0, "t", scope={"phase": " "})),
            (ValueError, FigureSpec("res.sellable_t", 1.0, "t", scope={"bench": math.inf})),
            (ValueError, FigureSpec("res.sellable_t", 1.0, "t",
                                    scope={"file": "C:\\datos\\fase1.csv"})),
            (TypeError, FigureSpec("res.sellable_t", 1.0, "t", parameter_key=3)),
        )
        for error, spec in cases:
            with self.subTest(spec=spec):
                self.rejected(error, None, handle, spec)
        with self.assertRaises(TypeError):
            self.write(lambda conn: figures.record_figure(conn, object(), good))
        with self.project.read() as conn, self.assertRaises(ValueError):
            figures.record_figure(conn, handle, good)  # fuera de una transacción de escritura
        # Cada cifra, una vez por operación (con su ámbito).
        self.write(lambda conn: figures.record_figure(conn, handle, good))
        self.rejected(ValueError, None, handle, good)
        before = self.snapshot()

        def complete(conn: sqlite3.Connection, specs: list[Any]) -> BaseException:
            with self.assertRaises((ProvenanceError, ValueError)) as caught:
                handle.complete(conn, outputs=[_table_spec("res_balance", "balance")],
                                figures=specs, software=SOFTWARE)
            return caught.exception

        for specs, code in (
            ([FigureSpec("res.sellable_t", 2.0, "t"), FigureSpec("res.net_fill", math.nan,
                                                                 "m3")], "core.figure_nan"),
            ([FigureSpec("res.net_fill", 2.0, "m3"), FigureSpec("res.net_fill", 3.0, "m3")],
             None),
            ([FigureSpec("res.sellable_t", 2.0, "t", scope={"phase": "1"})], None),
        ):
            with self.subTest(specs=specs):
                error = self.write(lambda conn, specs=specs: complete(conn, specs))
                self.assertEqual(getattr(error, "code", None), code, str(error))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.status(handle.uid), "running")
        self.assertEqual(len(self.figure_rows(handle.uid)), 1)


class ParameterTest(FiguresCase):
    def test_k_calculated_differs_from_adopted_k(self) -> None:
        """RF-008-59: la operación que calcula K = 1,11 con K ADOPTADO 1,23 deja la cifra
        CALCULADO, ligada al parámetro, y el aviso de la spec §8; K no cambia. Solo una persona
        adopta la cifra (T13) y entonces el aviso desaparece."""
        adopted = self.set_k(1.23)
        before = self.parameters()
        self.tick()
        handle = self.begin()
        self.complete(handle, [FigureSpec(K, 1.11, "-", parameter_key=K)])
        (row,) = self.figure_rows(handle.uid)
        self.assertEqual(
            (row["key"], row["label"], row["value"], row["unit"], row["kind"],
             row["parameter_uid"], row["parameter_rev"]),
            (K, "K", 1.11, "-", "CALCULADO", adopted.uid, adopted.rev),
        )
        self.assertEqual(self.parameters(), before)
        (warning,) = self.divergences(handle.uid)
        self.assertEqual(warning.text, "La operación «res.balance» calcula K = 1,11; el valor "
                                       "adoptado es 1,23 (la propiedad, 24/09/2026).")
        self.assertEqual(warning.render("en"), "Operation «res.balance» computes Test swell "
                                               "factor K = 1.11; the adopted value is 1.23 (la "
                                               "propiedad, 24/09/2026).")
        self.assertEqual(
            (warning.figure_uid, warning.operation_uid, warning.value, warning.parameter_uid,
             warning.parameter_value, warning.parameter_kind, warning.unconfirmed),
            (row["uid"], handle.uid, 1.11, adopted.uid, 1.23, "ADOPTADO", False),
        )
        with self.project.read() as conn:
            figure = conn.execute(f"SELECT {figures.RECORD_COLUMNS} FROM gb_figure "
                                  "WHERE uid = ?", (row["uid"],)).fetchone()
            self.assertEqual(figures.divergence(conn, figures.FigureRecord.from_row(figure)),
                             warning)
        # Lo decide una persona: adopta la cifra como CALCULADO y el aviso desaparece.
        self.tick()
        self.write(lambda conn: self.store.change(conn, K, from_figure=row["uid"],
                                                  decided_by="Samuel (IMGA)",
                                                  reason="Se adopta el K del balance"))
        record = self.store.get(K)
        self.assertEqual((record.value, record.kind, record.operation_uid),
                         (1.11, "CALCULADO", handle.uid))
        self.assertEqual(self.divergences(handle.uid), [])

    def test_no_parameter_ever_changes(self) -> None:
        """RF-008-59 (S-1, decisión de Samuel del 08/10/2026): ningún cálculo cambia un
        parámetro, ni su valor ni su tipo: tampoco uno «sin confirmar», uno MEDIDO o uno
        CALCULADO. Si el proyecto aún no lo tiene, queda registrado con su valor por defecto
        «sin confirmar», nunca con el calculado; la cifra difiere de él y lo avisa."""
        handle = self.begin()
        self.complete(handle, [FigureSpec(K, 1.08, "-", parameter_key=K)])
        default = self.store.get(K)
        self.assertEqual(
            (default.value, default.kind, default.unconfirmed, default.decided_by, default.rev,
             [entry.action for entry in self.store.history(K)]),
            (1.15, "HIPÓTESIS", True, params.DEFAULT_DECIDER, 1, ["default"]),
        )
        self.assertEqual(
            [warning.text for warning in self.divergences(handle.uid)],
            ["La operación «res.balance» calcula K = 1,08; el valor hipotético sin confirmar es "
             "1,15 (Geoblender (valor por defecto), 05/10/2026)."],
        )
        expected = "La operación «res.balance» calcula K = {value}; el valor {kind} es {shown}."
        for value, kind, change in (
            (1.12, "hipotético sin confirmar", None),
            (1.10, "medido", {"value": 1.2, "kind": "MEDIDO", "decided_by": "Laboratorio"}),
            (1.08, "calculado", "adopt"),
        ):
            with self.subTest(kind=kind):
                if change == "adopt":
                    previous = self.figure_rows(handle.uid)[-1]["uid"]
                    self.write(lambda conn, uid=previous: self.store.change(
                        conn, K, from_figure=uid, decided_by="Samuel (IMGA)",
                        reason="Se adopta el K calculado"))
                elif change is not None:
                    self.set_k(**change)
                record = self.store.get(K)
                before = self.parameters()
                self.tick()
                handle = self.begin()
                self.complete(handle, [FigureSpec(K, value, "-", parameter_key=K)])
                self.assertEqual(self.parameters(), before)
                (row,) = self.figure_rows(handle.uid)
                self.assertEqual((row["kind"], row["parameter_uid"], row["parameter_rev"]),
                                 ("CALCULADO", record.uid, record.rev))
                shown = f"{params.format_value(record.value)} ({record.decided_by}, "
                shown += f"{'24/09/2026' if kind == 'medido' else '05/10/2026'})"
                self.assertEqual(
                    [warning.text for warning in self.divergences(handle.uid)],
                    [expected.format(value=params.format_value(value), kind=kind, shown=shown)],
                )

    def test_percent_figure_against_a_fraction_parameter(self) -> None:
        """RF-008-59: la cifra se compara con el parámetro en la unidad de este (92 % = 0,92):
        la misma no avisa y la distinta avisa con cada una en su unidad; el parámetro no
        cambia."""
        self.write(lambda conn: self.store.create(
            conn, "res.recovery", 0.92, kind="ADOPTADO", source="Plan de labores 2026",
            source_kind="document", decided_by="la propiedad", decided_at=PROPERTY_DATE,
            reason="Recuperación del plan",
        ))
        before = self.parameters()
        handle = self.begin()
        self.complete(handle, [
            FigureSpec("res.recovery_calc", 92.0, "%", parameter_key="res.recovery"),
            FigureSpec("res.recovery_calc", 90.5, "%", scope={"phase": "2"},
                       parameter_key="res.recovery"),
        ])
        self.assertEqual(self.parameters(), before)
        self.assertEqual(
            [warning.text for warning in self.divergences(handle.uid)],
            ["La operación «res.balance» calcula Recuperación = 90,5 %; el valor adoptado es "
             "0,92 (la propiedad, 24/09/2026)."],
        )

    def test_figure_showing_a_parameter_carries_its_type(self) -> None:
        """RF-008-30: una cifra que muestra un parámetro que leyó la operación lleva su tipo
        (el que leyó), su valor (en cualquier unidad convertible) y su revisión; con otro tipo
        o con otro valor se rechaza (un ADOPTADO no se presenta como MEDIDO: error 34), y no
        puede mostrar uno que la operación no leyó. El parámetro no cambia."""
        self.write(lambda conn: self.store.create(
            conn, "res.recovery", 0.92, kind="ADOPTADO", source="Plan de labores 2026",
            source_kind="document", decided_by="la propiedad", reason="Recuperación del plan",
        ))
        handle = self.begin(params=["res.recovery", K])
        before = self.parameters()
        recovery, swell = handle.params
        error = self.rejected(ProvenanceError, "core.figure_parameter_kind", handle, FigureSpec(
            "res.recovery_used", 92.0, "%", kind="MEDIDO", parameter_key="res.recovery"))
        self.assertEqual(str(error), "La cifra «res.recovery_used» de la operación «res.balance» "
                                     "muestra el parámetro «res.recovery», que es ADOPTADO: "
                                     "lleva su tipo, no MEDIDO.")
        error = self.rejected(ProvenanceError, "core.figure_parameter_value", handle, FigureSpec(
            "res.recovery_used", 95.0, "%", kind="ADOPTADO", parameter_key="res.recovery"))
        self.assertEqual(str(error), "La cifra «res.recovery_used» de la operación «res.balance» "
                                     "muestra el parámetro «res.recovery» (0,92) y vale 95 %: "
                                     "si la operación lo calcula, la cifra es CALCULADO.")
        other = self.begin()
        self.rejected(ValueError, None, other, FigureSpec(
            "res.recovery_used", 92.0, "%", kind="ADOPTADO", parameter_key="res.recovery"))
        self.complete(handle, [
            FigureSpec("res.recovery_used", 92.0, "%", kind="ADOPTADO",
                       parameter_key="res.recovery"),
            FigureSpec(K, 1.15, "-", kind="HIPÓTESIS", parameter_key=K),
        ])
        self.assertEqual(
            [(row["key"], row["value"], row["unit"], row["kind"], row["parameter_uid"],
              row["parameter_rev"]) for row in self.figure_rows(handle.uid)],
            [("res.recovery_used", 92.0, "%", "ADOPTADO", recovery.parameter_uid, recovery.rev),
             (K, 1.15, "-", "HIPÓTESIS", swell.parameter_uid, swell.rev)],
        )
        self.assertEqual(self.divergences(handle.uid), [])
        self.assertEqual(self.parameters(), before)
        # Lo que muestra no es un cálculo: aunque el parámetro cambie después, no avisa.
        self.write(lambda conn: self.store.change(conn, "res.recovery", value=0.95,
                                                  reason="Nuevo plan de labores"))
        with self.project.read() as conn:
            shown = conn.execute(f"SELECT {figures.RECORD_COLUMNS} FROM gb_figure "
                                 "WHERE operation_uid = ? ORDER BY fid", (handle.uid,)).fetchall()
            self.assertEqual(
                [figures.divergence(conn, figures.FigureRecord.from_row(row)) for row in shown],
                [None, None],
            )


class VocabularyTest(unittest.TestCase):
    def test_kinds_messages_and_public_api(self) -> None:
        """RF-008-30: los tipos de una cifra son los cuatro de ``gb_figure``; cada rechazo de
        una cifra nombra su clave y (si la tiene) su operación; ``core.provenance`` reexporta
        la API de las cifras al usarla, sin importarla al importar el paquete."""
        ddl = schema.TABLES["gb_figure"]
        for kind in params.ParamKind:
            with self.subTest(kind=kind):
                self.assertIn(f"'{kind}'", ddl)
        codes = [code for code in messages.MESSAGES if code.startswith("core.figure_")]
        self.assertGreaterEqual(len(codes), 15)
        for code in codes:
            if code == "core.figure_differs":  # el aviso de RF-008-59, no un rechazo
                continue
            with self.subTest(code=code):
                message = messages.MESSAGES[code]
                self.assertIn("{key}", message.es)
                if code not in ("core.figure_operation_missing", "core.figure_unregistered"):
                    self.assertIn("{op_type}", message.es)
        for name in ("FigureSpec", "FigureRecord", "Divergence", "record_figure", "divergence",
                     "divergences", "scope_key"):
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIs(getattr(provenance, name), getattr(figures, name))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                with self.subTest(line=node.lineno):
                    self.assertNotEqual(node.module, "figures")
                    self.assertNotIn("figures", [alias.name for alias in node.names])
        self.assertIsInstance(FigureSpec("res.sellable_t", 1.0, "t").kind, str)
        self.assertEqual(FigureSpec("res.sellable_t", 1.0, "t").kind, "CALCULADO")


if __name__ == "__main__":
    unittest.main()
