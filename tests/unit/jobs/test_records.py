# SPDX-License-Identifier: GPL-3.0-or-later
"""Estado de los trabajos (spec 004, T04; RF-004-12, RF-004-15; plan 004 §5.2.4 y §5.3.1).

- RF-004-15: ``state.json`` (``geoblender.job_state/1``) guarda el registro del trabajo: tipo,
  nombre, dueño, estado, ejecutor, intérprete y versiones de Python, numpy y BLAS, proceso,
  horas de cola, inicio y fin en UTC, duración en s, código de salida, cancelación, resultados
  con su huella, último evento e incorporación. Se escribe de forma atómica (temporal y
  ``os.replace``: un corte deja el anterior intacto) y se lee idéntico.
- RF-004-12: un trabajo «Fallido» guarda su código, su ``msgid``, sus valores y su texto en
  español.
- ``state.json`` está dentro del proyecto: **sin rutas absolutas** (plan §5.2.4). Una ruta
  absoluta en un texto (un intérprete que no arranca, el nombre de un trabajo) queda en su
  último nombre.
- ``read_record`` y ``scan`` leen sin escribir; un ``state.json`` ilegible no cuenta.
"""

import dataclasses
import datetime as dt
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender

records = import_geoblender("jobs.records")
protocol = import_geoblender("jobs.protocol")
messages = import_geoblender("jobs.messages")

UID = "20261005_143012_3fa9c2"
SHA = "3fa9c2" * 10 + "0b1d"
LOGGER = "geoblender.jobs"

# Lo que sería una ruta absoluta de Windows en un texto: unidad con barra o red (UNC).
_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<![:\w\\/])[\\/]{2}[^\\/\s]")


def _record(**changes):
    """Un registro de un trabajo terminado bien, con todos los campos llenos."""
    record = records.JobRecord(
        job_uid=UID,
        worker="selftest",
        label="Autodiagnóstico: suma por trozos · «ñ»",
        owner="jobs",
        project_uid="5b0c-proyecto",
        operation_uid="op-1",
        state="succeeded",
        executor="subprocess",
        interpreter=records.InterpreterInfo(
            kind="blender", python="3.13.13", numpy="2.3.4", blas=None, lock_id=None
        ),
        pid=4120,
        queued_at="2026-10-05T14:30:12.345Z",
        started_at="2026-10-05T14:30:12.500Z",
        ended_at="2026-10-05T14:30:22.750Z",
        duration_s=10.25,
        exit_code=0,
        outputs=(protocol.OutputRef("out/sum.npy", SHA, 136, "sum"),),
        last_event_at="2026-10-05T14:30:22.700Z",
    )
    return dataclasses.replace(record, **changes) if changes else record


def _files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _texts(value) -> list[str]:
    """Todos los textos de un JSON (claves y valores)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, inner in value.items() for text in [key, *_texts(inner)]]
    if isinstance(value, list):
        return [text for inner in value for text in _texts(inner)]
    return []


class JobRecordTest(unittest.TestCase):
    """``JobRecord``: el contenido de ``state.json``."""

    def test_record_from_request(self):
        """RF-004-15: el registro de un trabajo en cola copia de la petición el
        identificador, el tipo, el nombre, el dueño, el proyecto y la operación, y anota el
        ejecutor y la hora de entrada en la cola (UTC)."""
        request = protocol.new_request(
            "selftest", label="Suma", owner="jobs", environment="blender", timeout_s=60,
            project_uid="5b0c-proyecto", operation_uid="op-1",
        )
        moment = dt.datetime(2026, 10, 5, 14, 30, 12, 345678, tzinfo=dt.UTC)
        record = records.JobRecord.from_request(request, executor="inprocess", queued_at=moment)
        self.assertEqual(record.job_uid, request.job_uid)
        self.assertEqual((record.worker, record.label, record.owner),
                         ("selftest", "Suma", "jobs"))
        self.assertEqual((record.project_uid, record.operation_uid), ("5b0c-proyecto", "op-1"))
        self.assertEqual(record.state, "queued")
        self.assertEqual(record.executor, "inprocess")
        self.assertEqual(record.queued_at, "2026-10-05T14:30:12.345Z")
        self.assertIsNone(record.started_at)
        self.assertEqual(record.outputs, ())
        self.assertTrue(record.is_active)
        self.assertFalse(record.is_final)

    def test_json_has_every_field_of_the_plan(self):
        """RF-004-15: la forma JSON lleva el esquema y todos los campos de plan §5.2.4, con
        los resultados como ``OutputRef`` y el intérprete con sus versiones."""
        data = _record().to_json()
        self.assertEqual(list(data), [
            "schema", "job_uid", "worker", "label", "owner", "project_uid", "operation_uid",
            "state", "executor", "interpreter", "pid", "queued_at", "started_at", "ended_at",
            "duration_s", "exit_code", "error", "cancel", "outputs", "last_event_at",
            "ingested_at",
        ])
        self.assertEqual(data["schema"], "geoblender.job_state/1")
        self.assertEqual(data["interpreter"], {"kind": "blender", "python": "3.13.13",
                                               "numpy": "2.3.4", "blas": None, "lock_id": None})
        self.assertEqual(data["outputs"], [{"path": "out/sum.npy", "sha256": SHA, "size": 136,
                                            "role": "sum"}])
        self.assertEqual(records.JobRecord.from_json(json.loads(json.dumps(data))), _record())

    def test_failed_record_keeps_code_and_spanish_text(self):
        """RF-004-12: un trabajo «Fallido» guarda el código, el ``msgid``, los valores y el
        texto en español del §8; uno cancelado a la fuerza, la hora, el motivo y «forzada»."""
        error = records.ErrorInfo.from_job_error(
            messages.JobError("worker_crashed", job="Suma", exit_code=7)
        )
        self.assertEqual(error.code, "worker_crashed")
        self.assertEqual(error.msgid, messages.MESSAGES["worker_crashed"].msgid)
        self.assertEqual(error.values, {"job": "Suma", "exit_code": 7})
        self.assertEqual(
            error.text,
            "El cálculo «Suma» terminó de forma inesperada (código 7). Detalles en su registro.",
        )
        cancel = records.CancelInfo(requested_at="2026-10-05T14:30:20.000Z", reason="user",
                                    forced=True)
        record = _record(state="failed", exit_code=7, error=error, cancel=cancel, outputs=())
        back = records.JobRecord.from_json(json.loads(json.dumps(record.to_json())))
        self.assertEqual(back, record)
        self.assertEqual(back.to_json()["error"]["text"], error.text)
        self.assertEqual(back.to_json()["cancel"],
                         {"requested_at": "2026-10-05T14:30:20.000Z", "reason": "user",
                          "forced": True})

    def test_states(self):
        """RF-004-15: siete estados; activos «queued» y «running», finales los demás."""
        self.assertEqual(records.JOB_STATES, ("queued", "running", "succeeded", "failed",
                                              "cancelled", "timed_out", "interrupted"))
        for state in records.JOB_STATES:
            record = _record(state=state)
            with self.subTest(state=state):
                self.assertEqual(record.is_active, state in ("queued", "running"))
                self.assertEqual(record.is_final, not record.is_active)

    def test_invalid_records_are_rejected(self):
        """RF-004-15: un estado, ejecutor, motivo de cancelación o tipo de intérprete
        desconocidos, una hora que no es UTC ISO 8601, una duración negativa, un proceso o un
        código que no son enteros, o un identificador mal formado son ``ValueError``."""
        cases = (
            {"state": "done"}, {"executor": "gpu"}, {"queued_at": "05/10/2026"},
            {"started_at": "2026-10-05T14:30:12+02:00"}, {"duration_s": -1.0},
            {"duration_s": float("nan")}, {"pid": "4120"}, {"pid": True}, {"exit_code": 0.0},
            {"job_uid": "20261005"}, {"worker": "../selftest"}, {"label": ""},
            {"cancel": "user"}, {"interpreter": "blender"},
            {"outputs": ({"path": "out/x"},)}, {"schema": "geoblender.job_state/2"},
        )
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                _record(**change)
        with self.assertRaises(ValueError):
            records.CancelInfo(requested_at="2026-10-05T14:30:20.000Z", reason="aburrido")
        with self.assertRaises(ValueError):
            records.CancelInfo(requested_at="ayer", reason="user")
        with self.assertRaises(ValueError):
            records.InterpreterInfo(kind="conda")

    def test_invalid_json_is_rejected(self):
        """RF-004-15: un campo de más o de menos, o de otro tipo, en la forma JSON es
        ``ValueError``."""
        data = _record().to_json()
        broken = (
            {**data, "otro": 1},
            {key: value for key, value in data.items() if key != "state"},
            {**data, "outputs": "out/sum.npy"},
            {**data, "interpreter": "blender"},
            {**data, "error": {"code": "x"}},
            [1, 2],
        )
        for item in broken:
            with self.subTest(item=item), self.assertRaises(ValueError):
                records.JobRecord.from_json(item)


class WriteRecordTest(unittest.TestCase):
    """``write_record``: ``state.json`` atómico, en UTF-8 sin BOM y LF."""

    def setUp(self):
        context = _support.temp_jobs_root()
        self.root = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.folder = self.root / UID
        self.folder.mkdir()

    def test_record_is_read_back_identical(self):
        """RF-004-15: escrito y leído, el registro es el mismo; el fichero está en UTF-8 sin
        BOM con la «ñ» tal cual, con LF, y no deja temporales."""
        record = _record()
        records.write_record(self.folder, record)
        self.assertEqual(records.read_record(self.folder), record)
        holder = type("Holder", (), {"path": self.folder})()
        self.assertEqual(records.read_record(holder), record)
        self.assertEqual(_files(self.root), [UID, f"{UID}/state.json"])
        raw = (self.folder / "state.json").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        self.assertIn("«ñ»".encode(), raw)
        self.assertTrue(raw.endswith(b"\n"))

    def test_rewrite_replaces_the_previous_state(self):
        """RF-004-15: escribir otra vez sustituye el estado anterior entero."""
        records.write_record(self.folder, _record(state="queued", started_at=None,
                                                  ended_at=None, duration_s=None,
                                                  exit_code=None, outputs=()))
        records.write_record(self.folder, _record())
        self.assertEqual(records.read_record(self.folder).state, "succeeded")
        self.assertEqual(_files(self.root), [UID, f"{UID}/state.json"])

    def test_interrupted_write_keeps_the_previous_state(self):
        """RF-004-15: si la sustitución falla (un corte), queda el ``state.json`` anterior
        intacto, se borra el temporal y se lanza el error."""
        records.write_record(self.folder, _record(state="running", ended_at=None,
                                                  duration_s=None, exit_code=None, outputs=()))
        before = (self.folder / "state.json").read_bytes()
        with mock.patch.object(records.os, "replace", side_effect=OSError(28, "disco lleno")):
            with self.assertRaises(OSError):
                records.write_record(self.folder, _record())
        self.assertEqual((self.folder / "state.json").read_bytes(), before)
        self.assertEqual(_files(self.root), [UID, f"{UID}/state.json"])

    def test_state_held_open_by_another_program(self):
        """RF-004-15: con ``state.json`` abierto por otro programa (Windows no deja
        sustituirlo), la escritura reintenta y, si no puede, lanza el error sin cambiar el
        fichero ni dejar temporales."""
        records.write_record(self.folder, _record(state="running", ended_at=None,
                                                  duration_s=None, exit_code=None, outputs=()))
        before = (self.folder / "state.json").read_bytes()
        with (self.folder / "state.json").open("rb"), self.assertRaises(OSError):
            records.write_record(self.folder, _record())
        self.assertEqual((self.folder / "state.json").read_bytes(), before)
        self.assertEqual(_files(self.root), [UID, f"{UID}/state.json"])
        records.write_record(self.folder, _record())
        self.assertEqual(records.read_record(self.folder), _record())

    def test_record_is_not_written_to_another_folder(self):
        """RF-004-15: la carpeta del registro es la de su identificador; en otra, o en una
        que no existe, es un error del programa y no se crea nada."""
        other = self.root / "20261005_143012_000000"
        other.mkdir()
        with self.assertRaises(ValueError):
            records.write_record(other, _record())
        with self.assertRaises(OSError):
            records.write_record(self.root / "otra" / UID, _record())
        self.assertEqual(_files(self.root), sorted([UID, other.name]))


class AbsolutePathsTest(unittest.TestCase):
    """``state.json`` no contiene rutas absolutas (plan §5.2.4: está dentro del proyecto)."""

    def test_state_json_has_no_absolute_paths(self):
        """RF-004-12, RF-004-15: las rutas absolutas de un error (el intérprete que no arranca,
        con espacios; una de red; con ``\\\\?\\``; con «/»; la de la propia raíz de trabajos)
        y del nombre del trabajo quedan en su último nombre; las relativas, las URL y el resto
        del texto se conservan."""
        with _support.temp_jobs_root() as root:
            folder = root / UID
            folder.mkdir()
            exe = r"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"
            error = records.ErrorInfo.from_job_error(messages.JobError(
                "interpreter_failed", path=exe,
                detail=f"[WinError 2] no se encuentra «{folder / 'out' / 'x.npy'}» ni "
                       r"\\nas\cu\datos\collar.csv ni \\?\C:\datos\largo.csv ni "
                       "c:/temp/survey.csv (https://pypi.org/simple, file:///D:/w/a.whl)",
            ))
            record = _record(
                state="failed", exit_code=None, outputs=(), error=error,
                label=r"Importar D:\datos\sondeos\collar.csv",
            )
            records.write_record(folder, record)
            raw = (folder / "state.json").read_bytes()
            data = json.loads(raw.decode("utf-8"))
            back = records.read_record(folder)
        texts = _texts(data)
        for text in texts:
            with self.subTest(text=text):
                self.assertIsNone(_ABSOLUTE.search(text))
                self.assertNotIn(str(root).casefold(), text.casefold())
                self.assertNotIn(root.as_posix().casefold(), text.casefold())
        self.assertNotIn(os.fsencode(root.parent.name), raw)
        joined = "\n".join(texts)
        for kept in ("python.exe", "x.npy", "collar.csv", "largo.csv", "survey.csv",
                     "https://pypi.org/simple", "a.whl", "[WinError 2]",
                     "No se pudo arrancar el intérprete", "Importar"):
            self.assertIn(kept, joined)
        self.assertEqual(data["error"]["values"]["path"], "…\\python.exe")
        self.assertEqual(data["label"], "Importar …\\collar.csv")
        self.assertEqual(back.error.code, "interpreter_failed")
        self.assertEqual(back.state, "failed")

    def test_relative_texts_are_kept(self):
        """RF-004-15: lo que no es una ruta absoluta (relativas, fracciones, horas, el
        esquema) queda tal cual y el registro se lee idéntico."""
        error = records.ErrorInfo(
            code="output_missing", msgid=messages.MESSAGES["output_missing"].msgid,
            values={"path": "out/sum.npy", "job": "a/b 1/2 14:30:12"},
            text="El resultado out/sum.npy falta (geoblender.job/1; in\\x.npy; y/o).",
        )
        record = _record(state="failed", exit_code=0, error=error, outputs=())
        with _support.temp_jobs_root() as root:
            folder = root / UID
            folder.mkdir()
            records.write_record(folder, record)
            self.assertEqual(records.read_record(folder), record)


class ReadRecordTest(unittest.TestCase):
    """``read_record``: el registro de una carpeta, o ``None``; nunca escribe."""

    def setUp(self):
        context = _support.temp_jobs_root()
        self.root = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.folder = self.root / UID
        self.folder.mkdir()

    def test_missing_state_is_none(self):
        """RF-004-15: sin ``state.json`` (o sin la carpeta) no hay registro: ``None``."""
        self.assertIsNone(records.read_record(self.folder))
        self.assertIsNone(records.read_record(self.root / "20261005_143012_000000"))
        self.assertEqual(_files(self.root), [UID])

    def test_unreadable_state_is_none_with_a_warning(self):
        """RF-004-15: un ``state.json`` que no es JSON en UTF-8 sin BOM, con otro esquema, con
        un campo de más o de otro trabajo no cuenta (``None``) y deja un aviso en el registro;
        leer no crea ni cambia nada."""
        good = json.dumps(_record().to_json(), ensure_ascii=False).encode("utf-8")
        other = _record().to_json()
        other["job_uid"] = "20261005_143012_000000"
        cases = (
            b"{no es json", b"\xef\xbb\xbf" + good, b"[1, 2]",
            good.replace(b"geoblender.job_state/1", b"geoblender.job_state/2"),
            good.replace(b'"duration_s": 10.25', b'"duration_s": NaN'),
            json.dumps({**_record().to_json(), "otro": 1}).encode(),
            json.dumps(other).encode(),
        )
        for content in cases:
            (self.folder / "state.json").write_bytes(content)
            listing = _files(self.root)
            with self.subTest(content=content[:40]), self.assertLogs(LOGGER, "WARNING"):
                self.assertIsNone(records.read_record(self.folder))
            self.assertEqual(_files(self.root), listing)
            self.assertEqual((self.folder / "state.json").read_bytes(), content)


class ScanTest(unittest.TestCase):
    """``scan``: los registros de una raíz de trabajos, por orden de llegada."""

    def test_scan_lists_the_records_in_order(self):
        """RF-004-15: ``scan`` devuelve los registros de las carpetas de trabajos ordenados
        por identificador (fecha); se salta las carpetas sin ``state.json`` o con uno
        ilegible, las que no son de trabajos y los ficheros sueltos, y no escribe nada."""
        uids = ("20261006_090000_00000a", "20261005_143012_3fa9c2", "20261005_143012_0b1d2e")
        with _support.temp_jobs_root() as root:
            for uid in uids:
                (root / uid).mkdir()
                records.write_record(root / uid, _record(job_uid=uid))
            (root / "20261007_000000_0000ff").mkdir()
            broken = root / "20261007_000000_0000ee"
            broken.mkdir()
            (broken / "state.json").write_bytes(b"{")
            (root / "otra").mkdir()
            (root / "notas.txt").write_text("x", encoding="utf-8")
            (root / uids[0] / "state.json.tmp").write_bytes(b"{")
            listing = _files(root)
            with self.assertLogs(LOGGER, "WARNING"):
                found = records.scan(root)
            self.assertEqual(_files(root), listing)
        self.assertEqual([record.job_uid for record in found], sorted(uids))
        self.assertTrue(all(isinstance(record, records.JobRecord) for record in found))

    def test_scan_of_a_missing_root_is_empty(self):
        """RF-004-15: una raíz de trabajos que todavía no existe no tiene registros."""
        with _support.jobs_tmp() as base:
            self.assertEqual(records.scan(base / "jobs"), [])
            self.assertEqual(os.listdir(base), [])


if __name__ == "__main__":
    unittest.main()
