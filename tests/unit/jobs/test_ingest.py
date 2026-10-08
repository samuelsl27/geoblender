# SPDX-License-Identifier: GPL-3.0-or-later
"""El final de un trabajo de la 004 para incorporarlo (spec 008, T31; RF-008-20, RF-008-18,
RF-008-19; ADR-0004 R4; plan 008 §5.3.1 y §5.4.7).

``jobs.ingest.job_outcome`` convierte el final de un trabajo (``JobResult``) y su
``state.json`` en el ``JobOutcome`` de ``core`` (``core`` no importa ``jobs``): su estado, su
ejecutor (en hilo o en proceso aparte), su nombre, la operación que lo lanzó, sus resultados
con su huella, su resumen, su error y la procedencia técnica del intérprete (Python, numpy,
BLAS e identificador del motor de cálculo). Con él, ``core.provenance.ingest_job`` incorpora el
resultado a la operación y el lanzador lo da por incorporado (``mark_ingested``).

Las pruebas lanzan trabajos reales del autodiagnóstico de la 004 (``selftest``) con un
``JobRunner``, en un hilo y en proceso aparte, sobre el proyecto sintético de
``tests/unit/core/provenance/test_graph.py``; el del motor de cálculo, con su ``lock_id``, es un
``state.json`` escrito con ``jobs.records``.
"""

from __future__ import annotations

import dataclasses
import platform
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR
from tests.unit.core.provenance.test_graph import GraphCase, _replace_table, _spec, _uses

catalog = import_geoblender("jobs.catalog")
jobs_messages = import_geoblender("jobs.messages")
paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")
ingest = import_geoblender("jobs.ingest")
operations = import_geoblender("core.provenance.operations")
messages = import_geoblender("core.provenance.messages")
stale_mod = import_geoblender("core.provenance.stale")
hashing = import_geoblender("core.hashing")

SUM_PARAMS = {"n": 1000, "chunks": 2}
FAIL_PARAMS = {"n": 1000, "chunks": 2, "fail_at": 1}
SUM = 499_500
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 60.0
POLL_S = 0.02
LABEL = "Años por banco"
COMPUTE = {"kind": "compute", "python": "3.13.13", "numpy": "2.3.4", "blas": "scipy-openblas",
           "lock_id": "b4958a26c4c9"}


class JobsCase(GraphCase):
    """El proyecto de ``GraphCase``, el autodiagnóstico registrado y un lanzador con su raíz de
    trabajos."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(mock.patch.dict(catalog._REGISTRY, clear=True))
        builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
        self.selftest = dataclasses.replace(builtin, default_timeout_s=JOB_TIMEOUT_S)
        catalog.register_worker(self.selftest)
        self.jobs_root = self.tmp / "jobs"
        self.jobs_root.mkdir()
        self.runner = runner.JobRunner(jobs_root=self.jobs_root, package_dir=EXTENSION_DIR,
                                       blender_python=Path(sys.executable))
        self.addCleanup(self.runner.shutdown)
        self.run_op("res.step_a", {"res_base": [1.0, 2.0]})

    def start(self, op_type: str = "res.step_b", executor: str = "job_thread") -> Any:
        handle = self.begin(op_type, inputs=_uses(["res_base"]), params=["res.production"],
                            executor=executor)
        self.tick()
        return handle

    def submit(self, handle: Any, params: dict[str, Any] = SUM_PARAMS, *,
               process: bool = False) -> Any:
        """El trabajo de la operación ``handle`` (con su uid en la petición); con
        ``process``, en proceso aparte."""
        request = protocol.new_request("selftest", label=LABEL, owner="res", params=params,
                                       project_uid=self.project.uid,
                                       operation_uid=handle.uid)
        if not process:
            return self.runner.submit(request)
        as_process = dataclasses.replace(self.selftest, policy="subprocess")
        with mock.patch.dict(catalog._REGISTRY, {"selftest": as_process}):
            return self.runner.submit(request)

    def finish(self, *jobs: Any) -> list[Any]:
        """Sondea hasta que terminan ``jobs`` y devuelve sus ``JobResult``."""
        deadline = time.monotonic() + DEADLINE_S
        while any(job.result() is None for job in jobs):
            if time.monotonic() > deadline:
                raise AssertionError("los trabajos no terminaron a tiempo")
            self.runner.poll()
            time.sleep(POLL_S)
        return [job.result() for job in jobs]

    def writer(self, outcome: Any) -> Any:
        """Lo que hace el módulo al incorporar: lee la suma de ``out/`` y la escribe."""

        def write(conn: sqlite3.Connection) -> list[Any]:
            value = np.load(outcome.file("sum"), allow_pickle=False)
            _replace_table(conn, "res_years", [float(value)])
            return [_spec("res_years")]

        return write


class RealJobTest(JobsCase):
    def test_real_jobs_with_the_provenance_of_their_state_json(self) -> None:
        """RF-008-20, RF-008-18: el final de un trabajo real del autodiagnóstico, en un hilo
        y en proceso aparte, da su ``JobOutcome`` con el intérprete de su ``state.json``
        (Python, numpy y BLAS del intérprete que lo ejecutó), su ejecutor, su nombre, la
        operación que lo lanzó, sus resultados y su resumen; la operación se incorpora con
        esa procedencia técnica y el lanzador lo da por incorporado."""
        in_thread = self.start("res.step_b", "job_process")
        in_process = self.start("res.step_c", "job_thread")
        jobs = (self.submit(in_thread), self.submit(in_process, process=True))
        results = self.finish(*jobs)
        cases = ((in_thread, "job_thread", np.__version__),
                 (in_process, "job_process", _support.blender_numpy_version()))
        for (handle, executor, numpy_version), job, result in zip(cases, jobs, results,
                                                                    strict=True):
            with self.subTest(executor=executor):
                outcome = ingest.job_outcome(result, job.job_dir)
                record = records.read_record(job.job_dir)
                interpreter = record.interpreter.to_json()
                self.assertEqual(
                    (outcome.job_uid, outcome.state, outcome.executor, outcome.label,
                     outcome.operation_uid, outcome.folder, dict(outcome.summary)),
                    (job.job_uid, "succeeded", executor, LABEL, handle.uid, job.job_dir.path,
                     {"op": "chunked_sum", "n": 1000, "chunks": 2, "sum": SUM}),
                )
                self.assertEqual(dict(outcome.interpreter), interpreter)
                self.assertEqual(
                    (interpreter["kind"], interpreter["python"], interpreter["numpy"],
                     interpreter["lock_id"]),
                    ("blender", platform.python_version(), numpy_version, None),
                )
                self.assertTrue(interpreter["blas"])
                (ref,) = result.outputs
                self.assertEqual(outcome.outputs, (operations.OutputPrint(
                    ref.path, ref.sha256, ref.role, size=ref.size),))
                self.assertEqual((outcome.error_code, outcome.error_text), (None, None))

                done = operations.ingest_job(self.project, handle, outcome,
                                             self.writer(outcome))
                self.tick()
                self.assertEqual((done.status, done.stale), ("done", False))
                row = self.row(handle.uid)
                self.assertEqual(
                    (row["status"], row["executor"], row["job_uid"], row["interpreter"]),
                    ("done", executor, job.job_uid,
                     hashing.canonical_json(interpreter).decode("utf-8")),
                )
                self.assertGreater(self.runner.mark_ingested(job.job_uid), 0)
                self.assertIsNotNone(records.read_record(job.job_dir).ingested_at)
        self.assertEqual(self.query('SELECT valor FROM "res_years"'), [(float(SUM),)])

    def test_production_changed_while_the_job_runs(self) -> None:
        """RF-008-20, RF-008-24 (CE-008-10): si la producción cambia mientras corre un
        trabajo que la usa, su resultado se incorpora obsoleto, «Obsoleto: cambió Producción
        mientras se calculaba», y nunca como vigente."""
        handle = self.start()
        job = self.submit(handle)
        self.change("res.production", 120000.0)
        (result,) = self.finish(job)
        done = operations.ingest_job(self.project, handle,
                                     ingest.job_outcome(result, job.job_dir),
                                     self.writer(ingest.job_outcome(result, job.job_dir)))
        text = "Obsoleto: cambió Producción mientras se calculaba"
        self.assertEqual((done.status, done.stale, done.text()), ("done", True, text))
        self.assertEqual(
            [(item.name, item.text) for item in stale_mod.stale_items(self.project).items],
            [("res_years", text)],
        )

    def test_failed_job_leaves_the_operation_failed(self) -> None:
        """RF-008-20, RF-008-19: un trabajo que falla deja la operación fallida con el motivo
        de la 004 y sin salidas."""
        handle = self.start()
        job = self.submit(handle, FAIL_PARAMS)
        (result,) = self.finish(job)
        outcome = ingest.job_outcome(result, job.job_dir)
        text = "Autodiagnóstico: fallo provocado en el trozo 1 de 2."
        self.assertEqual((outcome.state, outcome.error_code, outcome.error_text, outcome.outputs),
                         ("failed", "selftest_failed", text, ()))
        done = operations.ingest_job(self.project, handle, outcome, self.writer(outcome))
        self.assertEqual((done.status, done.reason), ("failed", text))
        self.assertEqual((self.status(handle.uid), self.row(handle.uid)["status_reason"]),
                         ("failed", text))
        self.assertNoOutputs(handle.uid)


class StateJsonTest(JobsCase):
    def _compute_job(self, operation_uid: str | None) -> tuple[Any, Any]:
        request = protocol.new_request("selftest", label=LABEL, owner="res", params=SUM_PARAMS,
                                       operation_uid=operation_uid)
        folder = paths.job_dir(self.jobs_root, request.job_uid).create()
        (folder.outputs_dir / "sum.npy").write_bytes(b"suma")
        ref = protocol.OutputRef("out/sum.npy", hashing.sha256_bytes(b"suma"), 4, "sum")
        record = dataclasses.replace(
            records.JobRecord.from_request(request, executor="subprocess"),
            state="succeeded", interpreter=records.InterpreterInfo(**COMPUTE),
            outputs=(ref,), started_at="2026-10-05T08:12:45.000Z",
            ended_at="2026-10-05T08:12:50.000Z", duration_s=5.0, exit_code=0,
        )
        records.write_record(folder, record)
        result = runner.JobResult(request.job_uid, "succeeded", (ref,), {"sum": 1}, None, None,
                                  5.0, folder)
        return result, folder

    def test_compute_engine_with_its_lock_id(self) -> None:
        """RF-008-20: el de un trabajo del motor de cálculo en proceso aparte lleva su
        identificador del motor (``lock_id``) y su BLAS, y la operación los guarda."""
        handle = self.start(executor="job_process")
        result, folder = self._compute_job(handle.uid)
        outcome = ingest.job_outcome(result, folder)
        self.assertEqual((outcome.executor, dict(outcome.interpreter), dict(outcome.summary)),
                         ("job_process", COMPUTE, {"sum": 1}))

        def write(conn: sqlite3.Connection) -> list[Any]:
            _replace_table(conn, "res_years", [1.0])
            return [_spec("res_years")]

        done = operations.ingest_job(self.project, handle, outcome, write)
        self.assertEqual(done.status, "done")
        self.assertEqual(self.row(handle.uid)["interpreter"],
                         hashing.canonical_json(COMPUTE).decode("utf-8"))

    def test_rejections(self) -> None:
        """RF-008-20: sin ``state.json`` (o ilegible) no se conoce la procedencia técnica del
        trabajo: un error del programa, como la carpeta de otro trabajo o un final que no es
        un ``JobResult``."""
        result, folder = self._compute_job(None)
        other, other_folder = self._compute_job(None)
        with self.assertRaises(ValueError):
            ingest.job_outcome(result, other_folder)
        with self.assertRaises(TypeError):
            ingest.job_outcome({"job_uid": result.job_uid}, folder)
        with self.assertRaises(TypeError):
            ingest.job_outcome(result, folder.path)
        (folder.path / records.RECORD_FILE).write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError), self.assertLogs("geoblender.jobs", "WARNING"):
            ingest.job_outcome(result, folder)
        (other_folder.path / records.RECORD_FILE).unlink()
        with self.assertRaises(ValueError):
            ingest.job_outcome(other, other_folder)


class VocabularyTest(unittest.TestCase):
    def test_the_vocabulary_of_the_004(self) -> None:
        """RF-008-20 (ADR-0004 R4): ``core`` repite lo que necesita de la 004 sin importarla:
        los finales de un trabajo, sus dos ejecutores y el mensaje de una salida que falta o
        no coincide con su huella (el mismo ``msgid`` y el mismo texto)."""
        self.assertEqual(set(operations.JOB_FINAL_STATES), set(records.FINAL_STATES))
        self.assertEqual(set(ingest.EXECUTORS), set(records.EXECUTORS))
        self.assertEqual(set(ingest.EXECUTORS.values()), set(operations.JOB_EXECUTORS))
        mine = messages.MESSAGES["core.job_output_mismatch"]
        for code in ("output_hash_mismatch", "output_missing"):
            with self.subTest(code=code):
                theirs = jobs_messages.MESSAGES[code]
                self.assertEqual((mine.msgid, mine.es), (theirs.msgid, theirs.es))


if __name__ == "__main__":
    unittest.main()
