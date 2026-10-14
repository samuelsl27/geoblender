# SPDX-License-Identifier: GPL-3.0-or-later
"""Incorporar el resultado de un trabajo en segundo plano (spec 008, T31; RF-008-20,
RF-008-18, RF-008-19, RF-008-24; ADR-0004 R4; plan 008 §5.3.1 y §5.4.7).

``core.provenance.operations.ingest_job`` incorpora lo que entregó un trabajo de la 004 a la
operación que lo lanzó (registrada «en curso» al empezar) a partir de ``JobOutcome``, un objeto
de datos de ``core`` (``core`` no importa ``jobs``: lo construye ``jobs.ingest.job_outcome``
desde el ``state.json`` del trabajo):

- un trabajo terminado se incorpora en una sola transacción, la del módulo, con la procedencia
  técnica del trabajo (intérprete, Python, numpy, BLAS e identificador del motor), su ejecutor
  (en hilo o en proceso aparte) y su identificador;
- antes, la huella de cada salida en ``out/``: una que falta o no coincide no se incorpora y la
  operación queda fallida con el mensaje de la 004; uno fallido, cancelado, con el tiempo
  agotado o interrumpido deja la operación fallida o cancelada con el motivo de la 004;
- lo que consumió se compara con lo vigente al incorporarla: si un parámetro o un dato cambió
  mientras se calculaba, entra obsoleta, «… mientras se calculaba», y nunca como vigente.

Cada prueba usa el proyecto sintético de ``test_graph`` (esquema 2, reloj simulado) y una
carpeta de trabajo simulada con su ``out/``; ``tests/unit/jobs/test_ingest.py`` lo prueba con
un trabajo real del autodiagnóstico de la 004.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import sqlite3
import unittest
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender
from tests.unit.core.provenance.test_graph import (
    STEP_B,
    GraphCase,
    _replace_table,
    _spec,
    _uses,
)
from tests.unit.core.provenance.test_operations import _now

provenance = import_geoblender("core.provenance")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
graph_mod = import_geoblender("core.provenance.graph")
stale_mod = import_geoblender("core.provenance.stale")
messages = import_geoblender("core.provenance.messages")
project_model = import_geoblender("core.project.model")
hashing = import_geoblender("core.hashing")

JobOutcome = operations.JobOutcome
OutputPrint = operations.OutputPrint

JOB_UID = "20261005_081244_a1b2c3"
OTHER_JOB = "20261005_081244_d4e5f6"
LABEL = "Años por banco"
INTERPRETER = {"kind": "compute", "python": "3.13.13", "numpy": "2.3.4",
               "blas": "scipy-openblas", "lock_id": "b4958a26c4c9"}
SUM_BYTES = b"\x93NUMPY suma de prueba 199990000"
PRODUCTION_CHANGED_WHILE = "Obsoleto: cambió Producción mientras se calculaba"


class IngestCase(GraphCase):
    """El proyecto de ``GraphCase`` y la carpeta de un trabajo simulado con su ``out/``."""

    def setUp(self) -> None:
        super().setUp()
        self.folder = self.tmp / "trabajos" / JOB_UID
        (self.folder / "out").mkdir(parents=True)
        self.written: list[str] = []

    # --- El trabajo -------------------------------------------------------------------------

    def output(self, name: str = "sum.npy", data: bytes = SUM_BYTES, *,
               role: str = "sum") -> Any:
        """Una salida que el trabajo dejó en ``out/`` con su huella y su tamaño."""
        (self.folder / "out" / name).write_bytes(data)
        return OutputPrint(f"out/{name}", hashing.sha256_bytes(data), role, size=len(data))

    def outcome(self, state: str = "succeeded", *, outputs: Sequence[Any] | None = None,
                **kw: Any) -> Any:
        values: dict[str, Any] = {
            "label": LABEL, "folder": self.folder,
            "outputs": (self.output(),) if outputs is None else tuple(outputs),
            "interpreter": INTERPRETER, "summary": {"op": "chunked_sum", "sum": 199990000},
        }
        values.update(kw)
        executor = values.pop("executor", "job_process")
        return JobOutcome(values.pop("job_uid", JOB_UID), state, executor, **values)

    def start(self, **kw: Any) -> Any:
        """La operación de un trabajo, registrada «en curso» al lanzarlo: lee la producción y
        ``res_base``."""
        values: dict[str, Any] = {"inputs": _uses(["res_base"]), "params": ["res.production"],
                                  "executor": "job_process"}
        values.update(kw)
        handle = self.begin("res.step_b", **values)
        self.tick()
        return handle

    def writer(self, values: Sequence[float] = (7.0, 8.0),
               table: str = "res_years") -> Callable[[sqlite3.Connection], list[Any]]:
        """Lo que hace el módulo al incorporar: escribe su tabla en la transacción y la
        declara como salida."""

        def write(conn: sqlite3.Connection) -> list[Any]:
            self.written.append(table)
            _replace_table(conn, table, values)
            return [_spec(table)]

        return write

    def ingest(self, handle: Any, outcome: Any, outputs: Any = None, **kw: Any) -> Any:
        chosen = self.writer() if outputs is None else outputs
        result = operations.ingest_job(self.project, handle, outcome, chosen, **kw)
        self.tick()
        return result

    def base(self) -> Any:
        """``res_base``, lo que consume la operación del trabajo."""
        return self.run_op("res.step_a", {"res_base": [1.0, 2.0]})


class DoneTest(IngestCase):
    def test_done_with_the_technical_provenance_of_the_job(self) -> None:
        """RF-008-20, RF-008-18: un trabajo terminado se incorpora en la transacción del
        módulo: la operación queda hecha con el intérprete del trabajo (Python, numpy, BLAS y
        el identificador del motor), su ejecutor (proceso aparte) y su identificador; sus
        salidas, registradas, y sus rutas, sueltas. Al día: nada obsoleto."""
        self.base()
        handle = self.start()
        handle.claim_paths("rasters/res_years.tif")
        outcome = self.outcome()
        result = self.ingest(handle, outcome)

        row = self.row(handle.uid)
        self.assertEqual(
            {name: row[name] for name in ("status", "status_reason", "executor", "job_uid",
                                          "interpreter", "finished_at")},
            {"status": "done", "status_reason": None, "executor": "job_process",
             "job_uid": JOB_UID,
             "interpreter": hashing.canonical_json(INTERPRETER).decode("utf-8"),
             "finished_at": _now(2)},
        )
        self.assertEqual(self.written, ["res_years"])
        self.assertEqual((result.operation_uid, result.job_uid, result.status, result.reason),
                         (handle.uid, JOB_UID, "done", None))
        self.assertTrue(result.ingested)
        self.assertFalse(result.stale)
        self.assertEqual((result.causes, result.text(), result.text("en")),
                         (frozenset(), None, None))
        self.assertEqual([record.name for record in result.outputs], ["res_years"])
        self.assertEqual(result.outputs[0].operation_uid, handle.uid)
        self.assertEqual(operations.claimed_paths(self.project), set())
        with self.assertRaises(RuntimeError):
            handle.claim_paths("rasters/res_otro.tif")
        self.assertNothingStale(self.stale())

    def test_job_in_a_thread_and_its_files(self) -> None:
        """RF-008-20, RF-008-18: un trabajo en un hilo de Blender queda con ese ejecutor (el
        de su ``state.json``, aunque la operación se lanzara pensando en otro), sin
        identificador del motor si no lo usó; el módulo encuentra cada salida en la carpeta
        del trabajo por su papel, y las salidas sueltas se dan como una lista."""
        self.base()
        handle = self.start(job_uid=JOB_UID)
        interpreter = {"kind": "blender", "python": "3.13.13", "numpy": "2.3.4",
                       "blas": "auto", "lock_id": None}
        outcome = self.outcome(executor="job_thread", interpreter=interpreter,
                               outputs=[self.output(), self.output("n.npy", b"n", role="n")])
        self.assertEqual(outcome.output("n").path, "out/n.npy")
        self.assertEqual(outcome.file(outcome.output("sum")), self.folder / "out" / "sum.npy")
        self.assertEqual(outcome.file("n").read_bytes(), b"n")
        with self.assertRaises(KeyError):
            outcome.output("otra")

        def write(conn: sqlite3.Connection) -> None:
            _replace_table(conn, "res_years", [float(len(outcome.file("sum").read_bytes()))])

        self.write(write)
        result = self.ingest(handle, outcome, [_spec("res_years")])
        self.assertEqual(result.status, "done")
        row = self.row(handle.uid)
        self.assertEqual((row["executor"], row["job_uid"], row["interpreter"]),
                         ("job_thread", JOB_UID,
                          hashing.canonical_json(interpreter).decode("utf-8")))


class FingerprintTest(IngestCase):
    def test_output_with_another_hash_is_not_ingested(self) -> None:
        """RF-008-20, RF-008-19: una salida que ya no coincide con su huella (otro contenido,
        otro tamaño) o que falta no se incorpora: la operación queda fallida con el mensaje
        de la 004 («El resultado out/sum.npy del trabajo «…» falta o no coincide con su
        huella.»), sin salidas, y el módulo no llega a escribir nada."""
        self.base()
        cases: dict[str, Callable[[], None]] = {
            "otro contenido": lambda: (self.folder / "out" / "sum.npy").write_bytes(
                SUM_BYTES[::-1]),
            "otro tamaño": lambda: (self.folder / "out" / "sum.npy").write_bytes(
                SUM_BYTES + b"0"),
            "falta": lambda: (self.folder / "out" / "sum.npy").unlink(),
        }
        expected = ("El resultado out/sum.npy del trabajo «Años por banco» falta o no "
                    "coincide con su huella.")
        for name, tamper in cases.items():
            with self.subTest(name):
                handle = self.start()
                outcome = self.outcome()
                tamper()
                result = self.ingest(handle, outcome)
                self.assertEqual((result.status, result.reason, result.ingested),
                                 ("failed", expected, False))
                self.assertEqual(
                    (self.status(handle.uid), self.row(handle.uid)["status_reason"]),
                    ("failed", expected),
                )
                self.assertNoOutputs(handle.uid)
        self.assertEqual(self.written, [])
        self.assertEqual(
            messages.render("core.job_output_mismatch", language="en", path="out/sum.npy",
                            job=LABEL),
            "Result out/sum.npy of job «Años por banco» is missing or does not match its hash.",
        )

    def test_output_outside_out_is_not_ingested(self) -> None:
        """RF-008-20: una salida declarada fuera de ``out/`` no vale, y una que dentro de
        ``out/`` lleva fuera (una unión de carpetas) no se incorpora."""
        for bad in ("in/sum.npy", "out", "out/../in/x.npy", "/out/sum.npy", "C:/out/x.npy",
                    "out//x.npy", "out/./x.npy", ""):
            with self.subTest(path=bad):
                with self.assertRaises(ValueError):
                    OutputPrint(bad, hashing.sha256_bytes(b""), "sum")
        self.assertEqual(OutputPrint("out\\sub\\x.npy", hashing.sha256_bytes(b""), "x").path,
                         "out/sub/x.npy")
        try:
            import _winapi
        except ImportError:
            _winapi = None
        if _winapi is None or not hasattr(_winapi, "CreateJunction"):
            self.skipTest("[ENTORNO] uniones de carpetas de Windows no disponibles")
        self.base()
        outside = self.tmp / "trabajos" / "fuera"
        outside.mkdir()
        (outside / "sum.npy").write_bytes(SUM_BYTES)
        _winapi.CreateJunction(str(outside), str(self.folder / "out" / "union"))
        self.addCleanup(os.rmdir, self.folder / "out" / "union")
        handle = self.start()
        printed = OutputPrint("out/union/sum.npy", hashing.sha256_bytes(SUM_BYTES), "sum",
                              size=len(SUM_BYTES))
        result = self.ingest(handle, self.outcome(outputs=[printed]))
        self.assertEqual((result.status, self.status(handle.uid)), ("failed", "failed"))
        self.assertEqual(self.written, [])


class EndedTest(IngestCase):
    def test_failed_cancelled_timed_out_or_interrupted_job(self) -> None:
        """RF-008-20, RF-008-19: el trabajo que no terminó bien deja la operación cancelada
        (si se canceló) o fallida, con el motivo de la 004 y sin salidas; el módulo no
        escribe nada."""
        self.base()
        cases = (
            ("failed", "Autodiagnóstico: fallo provocado en el trozo 2 de 4.", "failed"),
            ("cancelled", "Trabajo «Años por banco» cancelado.", "cancelled"),
            ("timed_out", "El trabajo «Años por banco» superó su tiempo máximo de 60 s y se "
                          "ha detenido.", "failed"),
            ("interrupted", "El trabajo «Años por banco» quedó interrumpido: Geoblender se "
                            "cerró mientras se ejecutaba.", "failed"),
        )
        for state, text, status in cases:
            with self.subTest(state=state):
                handle = self.start()
                outcome = self.outcome(state, outputs=(), error_code="x", error_text=text)
                result = self.ingest(handle, outcome)
                self.assertEqual((result.status, result.reason, result.outputs),
                                 (status, text, ()))
                self.assertEqual(
                    (self.status(handle.uid), self.row(handle.uid)["status_reason"]),
                    (status, text),
                )
                self.assertNoOutputs(handle.uid)
        self.assertEqual(self.written, [])

    def test_ended_job_of_an_operation_with_libraries(self) -> None:
        """RF-008-19, RF-008-20 (regresión de la spec 006, T33; RF-006-28): el trabajo
        cancelado o fallido de una operación que declara las bibliotecas que influyen en sus
        cifras (``OperationDef.libraries``) la deja cancelada o fallida con el motivo de la
        004 sin las versiones, que no hacen falta sin cifras: es lo que hace la sesión de
        Blender al terminar un trabajo que el módulo no incorporó (antes, ``ValueError`` y la
        operación seguía «en curso»). Terminado bien, sin ellas sigue siendo un error del
        programa."""
        self.base()
        contract.unregister_operation(STEP_B.op_type)
        contract.register_operation(dataclasses.replace(STEP_B, libraries=("numpy",)))
        for state, text in (("cancelled", "Trabajo «Años por banco» cancelado."),
                            ("failed", "Autodiagnóstico: fallo provocado en el trozo 2 de 4.")):
            with self.subTest(state=state):
                handle = self.start()
                outcome = self.outcome(state, outputs=(), error_code="x", error_text=text)
                result = self.ingest(handle, outcome)
                self.assertEqual((result.status, result.reason), (state, text))
                self.assertEqual(self.status(handle.uid), state)
        handle = self.start()
        self.assertRejected(ValueError, None, lambda: self.ingest(handle, self.outcome()))
        self.assertEqual(self.written, [])

    def test_module_failure_leaves_the_operation_failed(self) -> None:
        """RF-008-19, RF-008-23: si lo que escribe el módulo al incorporar falla, no queda
        nada a medias: la operación queda fallida con el motivo y el error sigue."""
        self.base()
        handle = self.start()

        def broken(conn: sqlite3.Connection) -> list[Any]:
            _replace_table(conn, "res_years", [1.0])
            raise RuntimeError("no se pudo leer C:\\Datos\\cliente\\sum.npy")

        with self.assertRaises(RuntimeError):
            self.ingest(handle, self.outcome(), broken)
        self.assertEqual(
            (self.status(handle.uid), self.row(handle.uid)["status_reason"]),
            ("failed", "error durante la operación: RuntimeError: no se pudo leer sum.npy"),
        )
        self.assertNoOutputs(handle.uid)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gpkg_contents WHERE table_name = ?",
                                    ("res_years",)), [(0,)])


class WhileRunningTest(IngestCase):
    def test_parameter_changed_while_running_is_ingested_stale(self) -> None:
        """RF-008-20, RF-008-24 (CE-008-10): si la producción cambia mientras corre el
        trabajo que la usa, su resultado se incorpora obsoleto, con la causa «… mientras se
        calculaba», en el resultado de la incorporación, en la lista de lo obsoleto y en la
        obsolescencia deducida, y nunca como vigente; lo que se calcula después con él lo ve
        obsoleto sin «mientras se calculaba» (cambió antes de empezar)."""
        self.base()
        handle = self.start()
        self.change("res.production", 120000.0)
        result = self.ingest(handle, self.outcome())

        self.assertEqual(result.status, "done")
        self.assertTrue(result.ingested)
        self.assertTrue(result.stale)
        self.assertEqual(result.causes, frozenset({self.changed("res.production")}))
        self.assertEqual(result.text(), PRODUCTION_CHANGED_WHILE)
        self.assertEqual(result.text("en"),
                         "Stale: Test production changed while it was being calculated")
        report = stale_mod.stale_items(self.project)
        self.assertEqual([(item.name, item.text) for item in report.items],
                         [("res_years", PRODUCTION_CHANGED_WHILE)])
        self.assertEqual(report.counts.stale, 1)
        with self.project.read() as conn:
            self.assertEqual(stale_mod.item_text(conn, "dataset", self.dataset("res_years"),
                                                 language="en"),
                             "Stale: Test production changed while it was being calculated")
            self.assertEqual(stale_mod.item_causes(conn, "dataset", self.dataset("res_years")),
                             result.causes)
            with self.assertRaises(ValueError):
                stale_mod.item_causes(conn, "figure", handle.uid)
        state = self.stale()
        self.assertEqual(state.operations, {handle.uid: {self.changed("res.production")}})
        with self.project.read() as conn:
            shown = graph_mod.stale_state(conn)
        self.assertEqual(shown.text(handle.uid), PRODUCTION_CHANGED_WHILE)
        self.assertEqual(shown.text(self.dataset("res_years")), PRODUCTION_CHANGED_WHILE)
        self.assertEqual(state.text(handle.uid), "Obsoleto: cambió Producción")
        later = self.run_op("res.step_c", {"res_c": [1.0]}, reads=["res_years"])
        with self.project.read() as conn:
            shown = graph_mod.stale_state(conn)
        self.assertEqual(shown.text(later.uid), "Obsoleto: cambió Producción")
        self.assertEqual(
            [(item.name, item.text) for item in stale_mod.stale_items(self.project).items],
            [("res_c", "Obsoleto: cambió Producción"),
             ("res_years", PRODUCTION_CHANGED_WHILE)],
        )

    def test_changed_after_it_finished_is_not_while_running(self) -> None:
        """RF-008-20, RF-008-24: lo que cambia después de incorporarla la deja obsoleta, pero
        no «mientras se calculaba»; un parámetro o un dato que vuelve a lo que leyó, o un
        parámetro que solo cambia de tipo, mientras corre no la deja obsoleta."""
        self.base()
        handle = self.start()
        self.change("res.production", 120000.0)
        self.run_op("res.edit", {"res_base": [1.0, 3.0]}, reads=["res_base"])
        self.change("res.production", 100000.0)
        self.run_op("res.edit", {"res_base": [1.0, 2.0]}, reads=["res_base"])
        self.change("res.production", kind="ADOPTADO")
        result = self.ingest(handle, self.outcome())
        self.assertFalse(result.stale)
        self.assertIsNone(result.text())
        self.change("res.production", 90000.0)
        self.run_op("res.edit", {"res_base": [1.0, 5.0]}, reads=["res_base"])
        after = "Obsoleto: cambió «res_base»; cambió Producción"
        with self.project.read() as conn:
            shown = graph_mod.stale_state(conn)
        self.assertEqual(shown.text(handle.uid), after)
        self.assertEqual(
            [(item.name, item.text) for item in stale_mod.stale_items(self.project).items],
            [("res_years", after)],
        )

    def test_dataset_changed_while_running_is_ingested_stale(self) -> None:
        """RF-008-20, RF-008-24: si lo que consume cambia mientras corre (otra operación lo
        reescribe), entra obsoleta «cambió «res_base» mientras se calculaba»; si cambia antes
        de empezar o después de terminar, no lo dice, y una edición que reescribe lo que lee
        no cambia lo que consumió mientras se calculaba."""
        self.base()
        self.run_op("res.edit", {"res_base": [1.0, 3.0]}, reads=["res_base"])
        first = self.start(params=[])
        self.run_op("res.edit", {"res_base": [1.0, 4.0]}, reads=["res_base"])
        result = self.ingest(first, self.outcome())
        while_running = "Obsoleto: cambió «res_base» mientras se calculaba"
        self.assertEqual(result.text(), while_running)
        second = self.start(params=[])
        self.assertFalse(self.ingest(second, self.outcome(), self.writer(table="res_other")).stale)
        self.run_op("res.edit", {"res_base": [1.0, 5.0]}, reads=["res_base"])
        changed = graph_mod.Cause(graph_mod.CauseKind.DATASET_CHANGED, self.dataset("res_base"))
        with self.project.read() as conn:
            self.assertEqual(graph_mod.changes_while_running(conn),
                             {first.uid: frozenset({changed})})
            self.assertEqual(graph_mod.changes_while_running(conn, [second.uid]), {})
            self.assertEqual(graph_mod.changes_while_running(conn, []), {})
        self.assertEqual(
            [(item.name, item.text) for item in stale_mod.stale_items(self.project).items],
            [("res_other", "Obsoleto: cambió «res_base»"), ("res_years", while_running)],
        )

    def test_a_write_from_a_clock_ahead_is_not_while_running(self) -> None:
        """RF-008-20: lo que escribió antes de empezar otro equipo con el reloj adelantado
        (su hora es posterior al final de la operación) no se toma por un cambio mientras se
        calculaba."""
        self.base()
        self.clock.advance(minutes=60)
        self.run_op("res.edit", {"res_base": [1.0, 3.0]}, reads=["res_base"])
        self.clock._now -= dt.timedelta(minutes=61)  # el reloj de este equipo, una hora antes
        handle = self.start(params=[])
        self.assertFalse(self.ingest(handle, self.outcome()).stale)
        self.clock.advance(minutes=120)
        self.run_op("res.edit", {"res_base": [1.0, 4.0]}, reads=["res_base"])
        with self.project.read() as conn:
            self.assertEqual(graph_mod.changes_while_running(conn), {})
            self.assertEqual(stale_mod.item_text(conn, "operation", handle.uid),
                             "Obsoleto: cambió «res_base»")

    def test_only_what_is_still_a_cause(self) -> None:
        """RF-008-20, RF-008-24: lo que cambió mientras se calculaba y después vuelve a lo que
        leyó ya no es causa: la operación y lo que escribió quedan al día."""
        self.base()
        handle = self.start()
        self.change("res.production", 120000.0)
        self.run_op("res.edit", {"res_base": [1.0, 3.0]}, reads=["res_base"])
        self.assertTrue(self.ingest(handle, self.outcome()).stale)
        changed = graph_mod.Cause(graph_mod.CauseKind.DATASET_CHANGED, self.dataset("res_base"))
        with self.project.read() as conn:
            self.assertEqual(graph_mod.changes_while_running(conn),
                             {handle.uid: frozenset({self.changed("res.production"), changed})})
        self.change("res.production", 100000.0)
        self.run_op("res.edit", {"res_base": [1.0, 2.0]}, reads=["res_base"])
        with self.project.read() as conn:
            self.assertEqual(graph_mod.changes_while_running(conn), {})
            self.assertIsNone(stale_mod.item_text(conn, "operation", handle.uid))
        self.assertNothingStale(self.stale())
        self.assertEqual(stale_mod.stale_items(self.project).items, ())


class RejectionsTest(IngestCase):
    def test_wrong_job_read_only_or_not_running(self) -> None:
        """RF-008-20, RF-008-19: el resultado de otro trabajo o de otra operación no se
        incorpora (un error del programa); en solo lectura no se registra nada
        (``core.read_only``) y la operación sigue en curso; una que ya terminó no se
        incorpora. En todos, sin escribir nada."""
        self.base()
        handle = self.start(job_uid=JOB_UID)
        for outcome in (self.outcome(job_uid=OTHER_JOB),
                        self.outcome(operation_uid="00000000-0000-4000-8000-0000000003ff")):
            with self.subTest(outcome=outcome):
                self.assertRejected(ValueError, None,
                                    lambda outcome=outcome: self.ingest(handle, outcome))
        bad_args: Mapping[str, Any] = {"software": {"scipy": "1.16"}, "message": 42}
        for name, value in bad_args.items():
            with self.subTest(argument=name):
                self.assertRejected((TypeError, ValueError), None,
                                    lambda name=name, value=value: self.ingest(
                                        handle, self.outcome(), **{name: value}))
        self.assertRejected(TypeError, None, lambda: self.ingest(handle, {"state": "x"}))
        self.assertRejected(TypeError, None, lambda: self.ingest("op", self.outcome()))
        self.assertEqual(self.written, [])
        ended = self.start()
        ended.cancel("Cancelado por la persona")
        self.assertRejected(provenance.ProvenanceError, "core.operation_not_running",
                            lambda: self.ingest(ended, self.outcome()))
        self.assertEqual(self.written, [])
        before = self.snapshot()
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED,
                                   "otra sesión lo tiene en escritura")
        with self.assertRaises(provenance.ProvenanceError) as caught:
            self.ingest(handle, self.outcome())
        self.assertEqual(caught.exception.code, "core.read_only")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.status(handle.uid), "running")

    def test_outcome_and_print_are_checked(self) -> None:
        """RF-008-20: el resultado de un trabajo se comprueba al crearlo (``ValueError`` o
        ``TypeError``): un trabajo que aún no ha terminado, un ejecutor que no es de un
        trabajo, sin carpeta completa, sin nombre o sin el motivo de un final que no es bueno;
        una huella que no es un sha256 o un tamaño negativo."""
        sha = hashing.sha256_bytes(b"")
        good: dict[str, Any] = {"label": LABEL, "folder": self.folder}
        for state, executor, values in (
            ("running", "job_process", {**good, "error_text": "En curso"}),
            ("queued", "job_process", {**good, "error_text": "En cola"}),
            ("terminado", "job_process", good),
            ("succeeded", "blender", good),
            ("succeeded", "external", good),
            ("succeeded", "job_process", {**good, "folder": Path("trabajos")}),
            ("succeeded", "job_process", {**good, "label": " "}),
            ("failed", "job_process", good),
            ("cancelled", "job_process", {**good, "error_text": " "}),
            ("succeeded", "job_process", {**good, "outputs": [OutputPrint("out/a", sha, "a"),
                                                              OutputPrint("out/a", sha, "b")]}),
        ):
            with self.subTest(state=state, executor=executor, values=values):
                with self.assertRaises((TypeError, ValueError)):
                    JobOutcome(JOB_UID, state, executor, **values)
        for args, kw in (((("out/a", "ABC", "a")), {}), (("out/a", sha.upper(), "a"), {}),
                         (("out/a", sha, ""), {}), (("out/a", sha, "a"), {"size": -1}),
                         (("out/a", sha, "a"), {"size": True}), ((Path("out/a"), sha, "a"), {})):
            with self.subTest(args=args, kw=kw):
                with self.assertRaises((TypeError, ValueError)):
                    OutputPrint(*args, **kw)
        outcome = JobOutcome(JOB_UID, "succeeded", "job_thread", label=LABEL,
                             folder=self.folder, summary={"n": 1}, interpreter=INTERPRETER)
        self.assertEqual((outcome.executor, outcome.outputs, outcome.error_text),
                         (operations.Executor.JOB_THREAD, (), None))
        with self.assertRaises(TypeError):
            outcome.summary["n"] = 2  # type: ignore[index]
        with self.assertRaises(TypeError):
            outcome.interpreter["kind"] = "x"  # type: ignore[index]


class VocabularyTest(unittest.TestCase):
    def test_public_api_and_job_states(self) -> None:
        """Plan §5.3.1: ``core.provenance`` reexporta la incorporación de un trabajo; los
        finales de un trabajo son los de la 004 (``succeeded``, ``failed``, ``cancelled``,
        ``timed_out`` e ``interrupted``)."""
        for name in ("JobOutcome", "OutputPrint", "IngestOutcome", "ingest_job",
                     "JOB_FINAL_STATES"):
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIs(getattr(provenance, name), getattr(operations, name))
        self.assertEqual(set(operations.JOB_FINAL_STATES),
                         {"succeeded", "failed", "cancelled", "timed_out", "interrupted"})


if __name__ == "__main__":
    unittest.main()
