# SPDX-License-Identifier: GPL-3.0-or-later
"""Limpieza de las carpetas de los trabajos e «Interrumpido» al reabrir (spec 004, T17;
RF-004-13, RF-004-16, RF-004-17; plan 004 §5.3.1, §5.4.5 y §5.4.6).

- RF-004-13: al abrir un proyecto, ``records.mark_interrupted`` deja «Interrumpido» lo que
  su ``state.json`` decía «En cola» o «En curso» y no está en el lanzador (Blender se cayó),
  con la hora de su último evento.
- RF-004-16: cuando el módulo dueño confirma que incorporó los resultados
  (``JobRunner.mark_ingested``), se borran las entradas y los resultados de la carpeta
  (``cleanup.release``) y quedan solo los cinco ficheros del registro.
- RF-004-17: ``cleanup.purge`` borra las carpetas de los trabajos terminados hace más de
  ``older_than_days`` días (o de todos los terminados) y dice cuántos MB liberó; nunca uno
  activo. ``cleanup.folder_size_mb`` da el tamaño de la raíz para el panel.

Las fechas se inyectan (``now`` y los registros escritos a mano): nada espera a que pase el
tiempo. Las carpetas se construyen en una raíz temporal; solo :class:`MarkIngestedTest`
lanza trabajos de verdad, en hilo (sin procesos).
"""

import datetime as dt
import json
import os
import stat
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
cleanup = import_geoblender("jobs.cleanup")
messages = import_geoblender("jobs.messages")
paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")
timeutil = import_geoblender("core.timeutil")

NOW = dt.datetime(2026, 10, 7, 12, 0, 0, tzinfo=dt.UTC)
DAY = dt.timedelta(days=1)
RETENTION_DAYS = 7
REGISTRY = sorted(["request.json", "events.jsonl", "job.log", "result.json", "state.json"])
LABEL = "Autodiagnóstico de la limpieza · «ñ»"
LOGGER = "geoblender.jobs"
INGEST_WORKER = "gbtest_ingest"
OUTPUT_BYTES = b"resultado de las pruebas \xc3\xb1" * 4000
DEADLINE_S = 10.0
POLL_S = 0.02


def _utc(moment: dt.datetime) -> str:
    return timeutil.format_utc(moment)


def _bytes(path: Path) -> int:
    """Bytes de los ficheros bajo ``path`` (lo que debería liberar borrarlo)."""
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _listing(folder: Path) -> list[str]:
    return sorted(os.listdir(folder))


def _make_job(
    root: Path,
    *,
    state: str,
    ended: dt.datetime | None = None,
    queued: dt.datetime | None = None,
    started: dt.datetime | None = None,
    label: str = LABEL,
    with_files: bool = True,
):
    """La carpeta de un trabajo con su petición, su ``state.json`` (fechas a mano), una
    entrada de solo lectura en ``in/``, resultados en ``out/`` (con una subcarpeta),
    ``events.jsonl``, ``job.log`` y, si terminó bien, ``result.json``."""
    request = protocol.new_request("selftest", label=label, owner="jobs",
                                   environment="blender", timeout_s=60)
    folder = paths.job_dir(root, request.job_uid).create()
    protocol.write_request(folder, request)
    queued = queued or (ended or NOW) - dt.timedelta(minutes=5)
    final = state in records.FINAL_STATES
    if final and started is None and state != "interrupted":
        started = queued + dt.timedelta(seconds=1)
    record = records.JobRecord(
        job_uid=request.job_uid, worker="selftest", label=label, owner="jobs",
        state=state, executor="subprocess", queued_at=_utc(queued),
        started_at=None if started is None else _utc(started),
        ended_at=None if ended is None else _utc(ended),
        duration_s=None if ended is None or started is None
        else (ended - started).total_seconds(),
        exit_code=0 if state == "succeeded" else None,
        error=None if state in ("queued", "running", "succeeded") else records.ErrorInfo(
            code="worker_crashed", msgid="Job crashed", text="Falló"),
    )
    records.write_record(folder, record)
    if with_files:
        folder.write_array("datos", np.arange(20_000, dtype=np.float64))
        (folder.outputs_dir / "resultado.bin").write_bytes(OUTPUT_BYTES)
        (folder.outputs_dir / "sub").mkdir()
        (folder.outputs_dir / "sub" / "malla.bin").write_bytes(b"\x00" * 3000)
        folder.events_file.write_bytes(b'{"note": "launched", "ts": 1.0}\n')
        folder.log_file.write_bytes("Geoblender: arranque del worker\n".encode("utf-8"))
        if state == "succeeded":
            folder.result_file.write_text('{"outputs": []}\n', encoding="utf-8")
    return folder


def _run_ingest(ctx):
    """La función del tipo de trabajo de las pruebas: deja un resultado en ``out/``."""
    path = ctx.output_path("resultado.bin")
    path.write_bytes(OUTPUT_BYTES)
    ctx.add_output(path, "datos")
    return {"bytes": len(OUTPUT_BYTES)}


def _quick(params) -> float:
    return 0.01


class _RootCase(unittest.TestCase):
    """Una raíz de trabajos temporal por prueba."""

    def setUp(self):
        tmp = _support.temp_jobs_root()
        self.root = tmp.__enter__()
        self.addCleanup(tmp.__exit__, None, None, None)


class MarkInterruptedTest(_RootCase):
    """``records.mark_interrupted``: lo que Blender dejó a medias al caerse."""

    def setUp(self):
        super().setUp()
        self.started = dt.datetime(2026, 10, 1, 9, 0, 0, tzinfo=dt.UTC)
        base = self.started.timestamp()
        self.orphan = _make_job(self.root, state="running", queued=self.started - DAY,
                                started=self.started, with_files=False)
        start = protocol.JobEvent.start({"pid": 4120, "kind": "blender"}, ts=base + 0.1)
        progress = protocol.JobEvent.progress(0.4, "Trozo 2 de 5", ts=base + 1.0)
        log = protocol.JobEvent.log("info", "Sigue", ts=base + 1.5)
        lines = [
            json.dumps({"note": "launched", "ts": base}).encode() + b"\n",
            protocol.encode_event(start),
            protocol.encode_event(progress),
            protocol.encode_event(log),
            "texto suelto que no es JSON · ñ\n".encode("utf-8"),
            json.dumps({"note": "cancel_requested", "ts": base + 2.0,
                        "reason": "user"}).encode() + b"\n",
            b'{"v": 1, "t": "progress", "ts": ',  # Blender murió escribiendo
        ]
        self.orphan.events_file.write_bytes(b"".join(lines))
        self.orphan.log_file.write_bytes(b"Geoblender: arranque del worker\n")
        self.last_event = dt.datetime.fromtimestamp(base + 1.5, dt.UTC)
        self.last_line = dt.datetime.fromtimestamp(base + 2.0, dt.UTC)
        self.queued_at = dt.datetime(2026, 10, 2, 8, 30, 0, tzinfo=dt.UTC)
        self.never_started = _make_job(self.root, state="queued", queued=self.queued_at,
                                       with_files=False)
        self.alive = _make_job(self.root, state="running", started=self.started,
                               with_files=False)
        self.final = _make_job(self.root, state="failed", ended=self.started + DAY)
        self.untouched = {
            folder.job_uid: (folder.path / records.RECORD_FILE).read_bytes()
            for folder in (self.alive, self.final)
        }

    def _mark(self):
        return records.mark_interrupted(self.root, active_uids={self.alive.job_uid})

    def test_orphans_become_interrupted(self):
        """RF-004-13: lo que constaba «En curso» o «En cola» y no está en el lanzador queda
        «Interrumpido» con ``job_interrupted`` (que nombra el trabajo), sin código de salida;
        se devuelven sus identificadores por orden."""
        marked = self._mark()
        self.assertEqual(marked, sorted([self.orphan.job_uid, self.never_started.job_uid]))
        expected = messages.JobError("job_interrupted", job=LABEL)
        for folder in (self.orphan, self.never_started):
            record = records.read_record(folder)
            self.assertEqual(record.state, "interrupted")
            self.assertTrue(record.is_final)
            self.assertIsNone(record.exit_code)
            self.assertEqual(record.error.code, "job_interrupted")
            self.assertEqual(record.error.text, expected.text)
            self.assertIn(LABEL, record.error.text)

    def test_running_orphan_keeps_its_last_event(self):
        """RF-004-13: el que estaba «En curso» queda con la hora de su último evento
        (``last_event_at``) y termina en la última línea de su ``events.jsonl`` (una nota
        del lanzador), con su duración desde que arrancó; las líneas rotas o que no son
        eventos no cuentan."""
        self._mark()
        record = records.read_record(self.orphan)
        self.assertEqual(record.last_event_at, _utc(self.last_event))
        self.assertEqual(record.ended_at, _utc(self.last_line))
        self.assertEqual(record.started_at, _utc(self.started))
        self.assertAlmostEqual(record.duration_s, 2.0, places=3)

    def test_never_started_orphan_ends_at_its_queue_time(self):
        """RF-004-13: el que estaba «En cola» (sin eventos) queda sin inicio ni duración,
        terminado a la hora en que entró en la cola."""
        self._mark()
        record = records.read_record(self.never_started)
        self.assertIsNone(record.started_at)
        self.assertIsNone(record.duration_s)
        self.assertEqual(record.ended_at, _utc(self.queued_at))

    def test_registry_says_why(self):
        """RF-004-13, RF-004-15: el registro lo cuenta: una nota final en ``events.jsonl``
        (en su propia línea, aunque la última quedara rota) y una línea en ``job.log``."""
        self._mark()
        lines = self.orphan.events_file.read_bytes().split(b"\n")
        note = json.loads(lines[-2])
        self.assertEqual(lines[-1], b"")
        self.assertEqual(note[runner.NOTE_KEY], "finished")
        self.assertEqual(note["state"], "interrupted")
        self.assertEqual(note["error"], "job_interrupted")
        self.assertTrue(note["orphan"])
        self.assertEqual(lines[-3], b'{"v": 1, "t": "progress", "ts": ')
        log = self.orphan.log_file.read_text(encoding="utf-8")
        self.assertTrue(log.startswith("Geoblender: arranque del worker\n"))
        last = log.splitlines()[-1]
        self.assertTrue(last.startswith(records.LOG_PREFIX))
        self.assertIn("«Interrumpido»", last)

    def test_active_and_final_jobs_are_not_touched(self):
        """RF-004-13: un trabajo que sigue en el lanzador y uno ya terminado no cambian."""
        self._mark()
        for uid, data in self.untouched.items():
            self.assertEqual((self.root / uid / records.RECORD_FILE).read_bytes(), data)

    def test_second_call_changes_nothing(self):
        """RF-004-13: marcar otra vez no encuentra nada ni cambia nada."""
        self._mark()
        snapshot = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(self._mark(), [])
        self.assertEqual(
            {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()},
            snapshot,
        )

    def test_missing_root_and_bad_arguments(self):
        """RF-004-13: una raíz que no existe no tiene nada que marcar; ``active_uids`` es
        una colección de identificadores, no un texto."""
        self.assertEqual(records.mark_interrupted(self.root / "no_existe", active_uids=()),
                         [])
        with self.assertRaises(TypeError):
            records.mark_interrupted(self.root, active_uids=self.alive.job_uid)
        with self.assertRaises(TypeError):
            records.mark_interrupted(self.root, active_uids=[7])
        self.assertEqual(records.read_record(self.orphan).state, "running")


class ReleaseTest(_RootCase):
    """``cleanup.release``: entradas y resultados fuera, el registro se queda."""

    def test_only_the_registry_remains(self):
        """RF-004-16: tras incorporar quedan solo los cinco ficheros del registro, intactos;
        se borran ``in/`` (de solo lectura), ``out/`` (con subcarpetas) y el centinela, y
        se devuelven los MB liberados."""
        folder = _make_job(self.root, state="succeeded", ended=NOW)
        folder.cancel_file.touch()
        kept = {name: (folder.path / name).read_bytes() for name in REGISTRY}
        expected = sum(_bytes(folder.path / name) for name in ("in", "out", "cancel"))
        self.assertGreater(expected, 150_000)
        freed = cleanup.release(folder)
        self.assertEqual(_listing(folder.path), REGISTRY)
        self.assertEqual({name: (folder.path / name).read_bytes() for name in REGISTRY},
                         kept)
        self.assertAlmostEqual(freed, expected / 1_000_000, places=9)

    def test_twice_frees_nothing_more(self):
        """RF-004-16: liberar otra vez no borra nada más y libera 0 MB."""
        folder = _make_job(self.root, state="failed", ended=NOW)
        cleanup.release(folder)
        listing = _listing(folder.path)
        self.assertEqual(cleanup.release(folder.path), 0.0)
        self.assertEqual(_listing(folder.path), listing)

    def test_active_or_unknown_job_is_refused(self):
        """RF-004-16: un trabajo en cola o en curso, o una carpeta sin ``state.json``, no se
        tocan (:class:`ValueError`)."""
        for state in ("queued", "running"):
            folder = _make_job(self.root, state=state)
            before = _bytes(folder.path)
            with self.assertRaises(ValueError):
                cleanup.release(folder)
            self.assertEqual(_bytes(folder.path), before)
        folder = _make_job(self.root, state="succeeded", ended=NOW)
        (folder.path / records.RECORD_FILE).unlink()
        with self.assertRaises(ValueError):
            cleanup.release(folder)
        self.assertTrue(folder.inputs_dir.exists())


class MarkIngestedTest(_RootCase):
    """``JobRunner.mark_ingested``: el módulo dueño confirma la incorporación."""

    def setUp(self):
        super().setUp()
        registry = mock.patch.dict(catalog._REGISTRY, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        catalog.register_worker(catalog.WorkerInfo(INGEST_WORKER, "Ingest test job",
                                                   estimate_s=_quick, run=_run_ingest))
        self.runner = runner.JobRunner(jobs_root=self.root, package_dir=EXTENSION_DIR,
                                       blender_python=Path(sys.executable))
        self.addCleanup(self.runner.shutdown)

    def _request(self):
        return protocol.new_request(INGEST_WORKER, label=LABEL, owner="jobs")

    def _finished_job(self):
        folder = self.runner.prepare(self._request())
        folder.write_array("datos", np.arange(30_000, dtype=np.float64))
        handle = self.runner.submit(folder)
        deadline = time.monotonic() + DEADLINE_S
        while handle.result() is None:
            if time.monotonic() > deadline:
                raise AssertionError("el trabajo en hilo no terminó a tiempo")
            self.runner.poll()
            time.sleep(POLL_S)
        self.assertEqual(handle.state, "succeeded")
        return handle

    def test_ingested_job_keeps_only_its_registry(self):
        """RF-004-16: tras ``mark_ingested`` quedan solo los cinco ficheros del registro,
        ``state.json`` dice cuándo se incorporó y se devuelven los MB liberados (los de
        ``in/`` y ``out/``)."""
        handle = self._finished_job()
        folder = handle.job_dir
        expected = _bytes(folder.inputs_dir) + _bytes(folder.outputs_dir)
        self.assertGreater(expected, 240_000)
        before = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        freed = self.runner.mark_ingested(handle.job_uid)
        after = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1)
        self.assertAlmostEqual(freed, expected / 1_000_000, places=9)
        self.assertEqual(_listing(folder.path), REGISTRY)
        record = records.read_record(folder)
        self.assertEqual(record.state, "succeeded")
        ingested = timeutil.parse_utc(record.ingested_at)
        self.assertTrue(before <= ingested <= after, record.ingested_at)

    def test_second_confirmation_is_harmless(self):
        """RF-004-16: confirmar otra vez libera 0 MB y no cambia la hora de incorporación."""
        handle = self._finished_job()
        self.runner.mark_ingested(handle.job_uid)
        state = (handle.job_dir.path / records.RECORD_FILE).read_bytes()
        self.assertEqual(self.runner.mark_ingested(handle.job_uid), 0.0)
        self.assertEqual((handle.job_dir.path / records.RECORD_FILE).read_bytes(), state)

    def test_job_of_a_previous_session(self):
        """RF-004-16: un trabajo terminado que este lanzador no lanzó se busca en la raíz."""
        folder = _make_job(self.root, state="succeeded", ended=NOW)
        expected = _bytes(folder.inputs_dir) + _bytes(folder.outputs_dir)
        freed = self.runner.mark_ingested(folder.job_uid)
        self.assertAlmostEqual(freed, expected / 1_000_000, places=9)
        self.assertEqual(_listing(folder.path), REGISTRY)
        self.assertIsNotNone(records.read_record(folder).ingested_at)

    def test_active_or_unknown_job_is_refused(self):
        """RF-004-16: uno en cola o en curso, uno que no existe o un identificador que no
        vale son :class:`ValueError` y no se borra nada."""
        prepared = self.runner.prepare(self._request())
        prepared.write_array("datos", np.arange(10, dtype=np.float64))
        with self.assertRaises(ValueError):
            self.runner.mark_ingested(prepared.job_uid)
        self.assertEqual(_listing(prepared.inputs_dir), ["datos.npy"])
        handle = self.runner.submit(self.runner.prepare(self._request()))
        with self.assertRaises(ValueError):  # en curso hasta el siguiente sondeo
            self.runner.mark_ingested(handle.job_uid)
        with self.assertRaises(ValueError):
            self.runner.mark_ingested(paths.new_job_uid())
        with self.assertRaises(ValueError):
            self.runner.mark_ingested("../otra")


class PurgeTest(_RootCase):
    """``cleanup.purge``: por antigüedad o todos los terminados; nunca los activos."""

    def setUp(self):
        super().setUp()
        self.old_ok = _make_job(self.root, state="succeeded", ended=NOW - 8 * DAY)
        self.old_failed = _make_job(self.root, state="failed",
                                    ended=NOW - 8 * DAY - dt.timedelta(hours=1))
        self.old_interrupted = _make_job(self.root, state="interrupted",
                                         ended=NOW - 30 * DAY)
        self.recent = _make_job(self.root, state="succeeded", ended=NOW - 6 * DAY)
        self.edge = _make_job(self.root, state="cancelled", ended=NOW - 7 * DAY)
        self.old_queued = _make_job(self.root, state="queued", queued=NOW - 30 * DAY)
        self.old_running = _make_job(self.root, state="running", started=NOW - 30 * DAY)
        self.in_runner = _make_job(self.root, state="succeeded", ended=NOW - 8 * DAY)
        self.broken = _make_job(self.root, state="succeeded", ended=NOW - 30 * DAY)
        (self.broken.path / records.RECORD_FILE).write_text("{roto", encoding="utf-8")
        (self.root / "otra_cosa").mkdir()
        (self.root / "otra_cosa" / "nota.txt").write_text("no es un trabajo", encoding="utf-8")
        (self.root / "nota.txt").write_text("tampoco", encoding="utf-8")
        # Los activos según su ``state.json`` no hace falta pasarlos: no se borran igual.
        self.active = {self.in_runner.job_uid}

    def _purge(self, **options):
        options.setdefault("older_than_days", RETENTION_DAYS)
        with self.assertLogs(LOGGER, "WARNING") as logs:  # el ``state.json`` roto
            report = cleanup.purge(self.root, active=self.active, now=NOW, **options)
        self.assertTrue(any(self.broken.job_uid in line for line in logs.output))
        return report

    def _remaining(self) -> set[str]:
        return set(os.listdir(self.root))

    def test_old_finished_jobs_are_removed(self):
        """RF-004-17: ``purge`` de 7 días borra las carpetas enteras de los terminados hace
        8 días o más (bien, mal o interrumpidos; las entradas de solo lectura también) y
        dice cuántos MB liberó."""
        gone = [self.old_ok, self.old_failed, self.old_interrupted]
        expected = sum(_bytes(folder.path) for folder in gone)
        report = self._purge()
        self.assertEqual(report.removed, tuple(sorted(f.job_uid for f in gone)))
        self.assertEqual(report.failed, ())
        self.assertAlmostEqual(report.freed_mb, expected / 1_000_000, places=9)
        for folder in gone:
            self.assertFalse(folder.path.exists(), folder.job_uid)

    def test_recent_and_active_jobs_stay(self):
        """RF-004-17: no se borran los de 6 días, el de 7 justos («hace más de 7 días»), ni
        los activos (en cola o en curso, aunque sean viejos, ni el que sigue en el
        lanzador), ni lo que no es la carpeta de un trabajo con su ``state.json``."""
        kept = [self.recent, self.edge, self.old_queued, self.old_running, self.in_runner,
                self.broken]
        sizes = {folder.job_uid: _bytes(folder.path) for folder in kept}
        self._purge()
        self.assertEqual(self._remaining(),
                         {*sizes, "otra_cosa", "nota.txt"})
        for folder in kept:
            self.assertEqual(_bytes(folder.path), sizes[folder.job_uid], folder.job_uid)

    def test_finished_scope_removes_every_final_job(self):
        """RF-004-17: con ``all_finished`` (el «FINISHED» del usuario) se borran todos los
        terminados, recientes incluidos, y nunca los activos."""
        report = self._purge(older_than_days=None, all_finished=True)
        gone = [self.old_ok, self.old_failed, self.old_interrupted, self.recent, self.edge]
        self.assertEqual(report.removed, tuple(sorted(f.job_uid for f in gone)))
        self.assertEqual(self._remaining(), {
            self.old_queued.job_uid, self.old_running.job_uid, self.in_runner.job_uid,
            self.broken.job_uid, "otra_cosa", "nota.txt",
        })

    def test_nothing_to_remove(self):
        """RF-004-17: sin nada viejo, ni se borra ni se libera nada; una raíz que no existe
        tampoco tiene nada."""
        report = self._purge(older_than_days=60)
        self.assertEqual((report.removed, report.freed_mb, report.failed), ((), 0.0, ()))
        empty = cleanup.purge(self.root / "no_existe", older_than_days=7, active=set(),
                              now=NOW)
        self.assertEqual(empty.removed, ())

    def test_bad_arguments(self):
        """RF-004-17: hace falta una antigüedad (≥ 0 días) o ``all_finished``; ``now`` con
        zona; ``active`` es una colección de identificadores. Nada se borra."""
        before = self._remaining()
        for days in (None, -1, float("nan"), float("inf"), True, "7"):
            with self.subTest(days=days), self.assertRaises((ValueError, TypeError)):
                cleanup.purge(self.root, older_than_days=days, active=set(), now=NOW)
        with self.assertRaises(ValueError):
            cleanup.purge(self.root, older_than_days=7, active=set(),
                          now=dt.datetime(2026, 10, 7))
        with self.assertRaises(TypeError):
            cleanup.purge(self.root, older_than_days=7, active=self.recent.job_uid, now=NOW)
        self.assertEqual(self._remaining(), before)


class PurgeRetryTest(_RootCase):
    """``cleanup.purge`` con un fichero abierto por otro programa."""

    def setUp(self):
        super().setUp()
        self.held = _make_job(self.root, state="succeeded", ended=NOW - 10 * DAY)
        self.other = _make_job(self.root, state="failed", ended=NOW - 10 * DAY)
        self.handle = (self.held.outputs_dir / "resultado.bin").open("rb")
        self.addCleanup(self.handle.close)

    def test_open_file_is_retried_and_reported(self):
        """RF-004-17: si un fichero sigue abierto tras los reintentos, esa carpeta queda (con
        su ``state.json``, para la próxima limpieza) y consta como no borrada; las demás
        se borran y se cuenta lo que sí se liberó."""
        pauses = []
        with (mock.patch.object(cleanup, "_pause", side_effect=lambda: pauses.append(1)),
              self.assertLogs(LOGGER, "WARNING") as logs):
            report = cleanup.purge(self.root, older_than_days=7, active=set(), now=NOW)
        self.assertTrue(any(self.held.job_uid in line for line in logs.output))
        self.assertEqual(len(pauses), cleanup.REMOVE_RETRIES)
        self.assertEqual(report.removed, (self.other.job_uid,))
        self.assertEqual(report.failed, (self.held.job_uid,))
        self.assertTrue((self.held.path / records.RECORD_FILE).exists())
        self.assertTrue((self.held.outputs_dir / "resultado.bin").exists())
        self.assertFalse(self.held.inputs_dir.exists())
        self.assertGreater(report.freed_mb, 0.0)

    def test_file_closed_while_retrying(self):
        """RF-004-17: si el otro programa lo suelta durante los reintentos, se borra."""
        expected = _bytes(self.held.path) + _bytes(self.other.path)
        with mock.patch.object(cleanup, "_pause", side_effect=self.handle.close):
            report = cleanup.purge(self.root, older_than_days=7, active=set(), now=NOW)
        self.assertEqual(report.removed, tuple(sorted([self.held.job_uid,
                                                       self.other.job_uid])))
        self.assertEqual(report.failed, ())
        self.assertAlmostEqual(report.freed_mb, expected / 1_000_000, places=9)
        self.assertEqual(os.listdir(self.root), [])


class FolderSizeTest(_RootCase):
    """``cleanup.folder_size_mb``: el tamaño de la raíz de trabajos en el panel."""

    def test_size_of_the_jobs_root(self):
        """RF-004-17: la suma de todos los ficheros bajo la carpeta, en MB (10⁶ bytes); una
        que no existe ocupa 0."""
        _make_job(self.root, state="succeeded", ended=NOW)
        _make_job(self.root, state="failed", ended=NOW)
        expected = _bytes(self.root)
        self.assertAlmostEqual(cleanup.folder_size_mb(self.root), expected / 1_000_000,
                               places=9)
        self.assertEqual(cleanup.folder_size_mb(self.root / "no_existe"), 0.0)

    def test_read_only_inputs_count(self):
        """RF-004-17: las entradas de solo lectura cuentan como cualquier fichero."""
        folder = _make_job(self.root, state="succeeded", ended=NOW)
        entry = folder.inputs_dir / "datos.npy"
        self.assertFalse(os.stat(entry).st_mode & stat.S_IWRITE)
        self.assertAlmostEqual(cleanup.folder_size_mb(folder.inputs_dir),
                               entry.stat().st_size / 1_000_000, places=9)


if __name__ == "__main__":
    unittest.main()
