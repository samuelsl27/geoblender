# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrato del extractor de bases de Access (spec 005, T16; HU-005-2; ADR-0018; plan 005
§5.3.4, §5.6.12 y §7): ``interop.ports`` (``MdbExtractor``, ``MdbInfo``, el formato y el
fichero de bloqueo), ``adapters/mdb_reader.py`` y ``adapters/mdb_reader.ps1``, con las bases
RecMin sintéticas Jet 4 y ACE que crea ``tests/data/dh/recmin/build_mdb.ps1`` en una carpeta
temporal (``tests.support.recmin.shared_bases``: una vez por guion y motor, y aquí su copia).

- **RF-005-13** (incorporar sin pérdida una base RecMin, MDB o ACCDB, Jet 4 o ACE, esquema 11
  o 12): cada tabla de usuario de las cuatro bases (los dos guiones con los dos motores) sale
  con sus columnas (nombre, tipo OLE DB y tamaño) y sus filas **bit a bit** iguales a las del
  guion (``recmin.raw_tables``: Single como ``numpy.float32``, Double como ``float``), leída
  con Jet 4.0 (``powershell.exe`` de 32 bits) y con ACE (64 bits); los motores se detectan
  abriendo la base con ``OleDbConnection.Open()``; el crudo queda en la carpeta de salida
  (``schema.json`` y un ``.jsonl`` por tabla). Con la alineación de la fase 1 (``plan.md``
  §5.6.12): avance cada ≤ 0,5 s también dentro de una tabla (fila a fila) y cancelación en
  ≤ 2 s con el ``powershell.exe`` hijo terminado (RNF-008-11); el extractor se obtiene con
  ``adapters.registry.mdb_extractor()``.
- **RF-005-03** (la fuente intacta): el sha256 y la lista de ficheros de la carpeta de la
  fuente no cambian; el motor solo abre la copia (como la de ``JobDir.copy_input``), que
  tampoco cambia, y junto a ella no queda ningún ``.laccdb`` ni ``.ldb``, tampoco al cancelar.
- **RF-005-14** (sin motor para el formato): una base ACE en un equipo con solo Jet 4.0, o con
  un motor que no está registrado, da ``io.mdb_engine_missing`` con el formato detectado, qué
  instalar (el motor nombrado de forma genérica, DP-70) y la alternativa (exportar a CSV), y
  no extrae nada.
- **RF-005-15** (base abierta por otro programa): su ``.ldb`` o ``.laccdb`` se detecta.
- ADR-0018: el proceso de la prueba no carga ``aceoledb.dll`` ni ``msjetoledb40.dll``, y los
  proveedores OLE DB y las bibliotecas de acceso a Access solo se nombran en
  ``adapters/mdb_reader.*``.

Sin el motor ACE de 64 bits, lo que lo necesita se omite con ``[ENTORNO] ace``; Jet 4.0 viene
con Windows. Los fallos del proceso hijo (cancelación con el hijo vivo, salida con error,
silencio) se prueban también con un hijo falso de Python, determinista.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import recmin
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR
from tests.support.resources import WINDOWS, WINDOWS_HINT, is_available, requires, skip_reason

ports = import_geoblender("interop.ports")
mdb_reader = import_geoblender("adapters.mdb_reader")
registry = import_geoblender("adapters.registry")

V11, V12 = "recmin_v11.sql", "recmin_v12.sql"
EXTENSION = EXTENSION_DIR
MAX_PROGRESS_GAP_S = 0.5  # RNF-008-11 con la alineación de la 005 (plan §5.6.12)
MAX_CANCEL_S = 2.0
ENGINE_DLLS = ("aceoledb.dll", "acecore.dll", "msjetoledb40.dll", "msjet40.dll")
JET4_32 = mdb_reader.JET4_32
ACE_64 = (mdb_reader.ACE16_64, mdb_reader.ACE12_64)

GHOST = ports.MdbEngine("Microsoft.ACE.OLEDB.99.0", 64)  # un motor que no está registrado

_tmp: Path | None = None
_source: Path | None = None  # la carpeta de la «fuente»: las bases tal como las crea el guion
_bases: dict[tuple[str, str], Path] = {}
_source_before: dict[str, tuple[int, str]] = {}
_copies = 0


@dataclasses.dataclass
class _Done:
    """Una detección o una extracción hecha al preparar el módulo: la copia que leyó, su
    carpeta de salida y lo que dio (o lo que lanzó)."""

    copy: Path
    out: Path
    value: object = None
    error: BaseException | None = None

    def get(self) -> object:
        if self.error is not None:
            raise self.error
        return self.value


_done: dict[str, _Done] = {}


def _fingerprint(folder: Path) -> dict[str, tuple[int, str]]:
    """Nombre → (tamaño, sha256) de cada fichero de ``folder``: su lista y su contenido."""
    return {
        p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(folder.iterdir())
    }


def _probe(done: _Done, engines: tuple[object, ...] | None) -> object:
    extractor = mdb_reader.OleDbProcessMdbExtractor(*(() if engines is None else (engines,)))
    return extractor.probe(done.copy)


def _extract(done: _Done, engines: tuple[object, ...] | None) -> object:
    extractor = (registry.mdb_extractor() if engines is None
                 else mdb_reader.OleDbProcessMdbExtractor(engines))
    return extractor.extract(done.copy, done.out, lambda f, m: None, lambda: False)


def setUpModule() -> None:
    """Copia una sola vez las bases de los dos guiones, Jet 4 y, si hay ACE, ACE, en la
    carpeta de la «fuente» (``recmin.shared_bases``), anota su huella y hace a la vez (un
    ``powershell.exe`` por motor y por base) las detecciones y extracciones que no miden
    tiempos, cada una sobre su copia: lo que dan lo comprueban las pruebas."""
    global _tmp, _source
    if os.name != "nt":
        raise unittest.SkipTest(skip_reason(WINDOWS, WINDOWS_HINT))
    _tmp = Path(tempfile.mkdtemp(prefix="gbmdb"))
    _source = _tmp / "fuente"
    _source.mkdir()
    ace = is_available(recmin.ACE)
    build = recmin.shared_bases(_source, ("jet4", "ace") if ace else ("jet4",))
    for (sql, engine), base in build.bases.items():
        _bases[(sql, engine)] = base.path
    _source_before.update(_fingerprint(_source))
    plan: dict[str, tuple[str, str, Callable[..., object], tuple[object, ...] | None]] = {
        "probe_jet4": (V12, "jet4", _probe, None),
        "jet4_v11": (V11, "jet4", _extract, (JET4_32,)),
        "ghost": (V12, "jet4", _extract, (GHOST,)),
    }
    if ace:
        plan |= {
            "probe_ace": (V12, "ace", _probe, None),
            "ace_v11": (V11, "ace", _extract, None),
            "ace_v12": (V12, "ace", _extract, None),
            "ace_on_jet4_v12": (V12, "jet4", _extract, None),
        }
    for key, (sql, engine, _action, _engines) in plan.items():
        copy = _job_copy(sql, engine)
        _done[key] = _Done(copy, _out_dir(copy))

    def run(key: str) -> None:
        _sql, _engine, action, engines = plan[key]
        try:
            _done[key].value = action(_done[key], engines)
        except Exception as exc:  # noqa: BLE001 - lo comprueba (o lo relanza) su prueba
            _done[key].error = exc

    with concurrent.futures.ThreadPoolExecutor(len(plan)) as pool:
        list(pool.map(run, plan))


def tearDownModule() -> None:
    if _tmp is not None:
        shutil.rmtree(_tmp, ignore_errors=True)


def _job_copy(sql: str, engine: str) -> Path:
    """Una copia de la base en la carpeta ``in/`` de un «trabajo» nuevo, como la que deja
    ``JobDir.copy_input`` de la 004: el extractor solo abre copias (ADR-0018 §4)."""
    global _copies
    assert _tmp is not None
    _copies += 1
    folder = _tmp / f"t{_copies}" / "in"
    folder.mkdir(parents=True)
    copy = folder / _bases[(sql, engine)].name
    shutil.copyfile(_bases[(sql, engine)], copy)
    return copy


def _out_dir(copy: Path) -> Path:
    """La carpeta de salida del «trabajo» de la copia (``out/mdb``), aún sin crear."""
    return copy.parent.parent / "out" / "mdb"


def _fake_base(folder: Path, name: str, version: int, magic: bytes) -> Path:
    """Un fichero con la cabecera de una base de Access (sin datos): bytes 0–3, la firma en el
    4 y el byte de versión en el 0x14 (plan §5.3.4)."""
    folder.mkdir(parents=True, exist_ok=True)
    data = bytearray(4096)
    data[0:4] = b"\x00\x01\x00\x00"
    data[4:4 + len(magic)] = magic
    data[0x14] = version
    path = folder / name
    path.write_bytes(bytes(data))
    return path


def _bits(value: object) -> tuple[object, ...]:
    """Un valor con su tipo y sus bits: para comparar bit a bit (``0.1`` en Single frente a
    ``0.1`` en Double, ``-0.0`` frente a ``0.0``)."""
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, np.float32):
        return ("f4", value.tobytes())
    if isinstance(value, float):
        return ("f8", struct.pack("<d", value))
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, Decimal):
        return ("decimal", value.as_tuple())
    if isinstance(value, dt.datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, str):
        return ("str", value)
    raise TypeError(f"valor inesperado: {value!r} ({type(value).__name__})")


def _snapshot(tables: object) -> dict[str, tuple[object, ...]]:
    """Las tablas por nombre: columnas (nombre, tipo, tamaño) y filas, bit a bit."""
    found: dict[str, tuple[object, ...]] = {}
    for table in tables:
        columns = tuple((c.name, c.type, c.size) for c in table.columns)
        rows = tuple(tuple(_bits(v) for v in row) for row in table.rows)
        found[table.name] = (columns, rows)
    return found


def _expected(sql: str) -> dict[str, tuple[object, ...]]:
    """Lo que dice el guion (``recmin.raw_tables``), con los Single en ``numpy.float32``."""
    return _snapshot(recmin.raw_tables(recmin.RECMIN_DIR / sql).values())


def _locks(path: Path) -> list[str]:
    """Los ficheros de bloqueo de Access que hay junto a ``path``."""
    return sorted(p.name for p in path.parent.iterdir()
                  if p.suffix.lower() in (".ldb", ".laccdb"))


def _loaded(dll: str) -> bool:
    """Si este proceso tiene cargada la biblioteca ``dll`` (``GetModuleHandleW``)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = (ctypes.c_wchar_p,)
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    return bool(kernel32.GetModuleHandleW(dll))


class _Recorder:
    """Las llamadas a ``on_progress`` con su hora, y la cancelación que se pide."""

    def __init__(self, cancel_when: Callable[[float, str], bool] | None = None) -> None:
        self.calls: list[tuple[float, float, str]] = []
        self.cancel_at: float | None = None
        self._cancel_when = cancel_when

    def on_progress(self, frac: float, msg: str) -> None:
        now = time.perf_counter()
        self.calls.append((now, frac, msg))
        if self.cancel_at is None and self._cancel_when is not None and self._cancel_when(
                frac, msg):
            self.cancel_at = now

    def cancelled(self) -> bool:
        return self.cancel_at is not None


class _PopenSpy:
    """Los procesos que lanza el extractor (para ver que el hijo ya no vive)."""

    def __init__(self) -> None:
        self.processes: list[subprocess.Popen[bytes]] = []
        self._real = subprocess.Popen

    def __call__(self, *args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = self._real(*args, **kwargs)  # type: ignore[call-overload]
        self.processes.append(process)
        return process

    def patch(self) -> mock._patch[object]:
        return mock.patch.object(mdb_reader.subprocess, "Popen", side_effect=self)


class _SourceCheck(unittest.TestCase):
    """Comprobaciones comunes: la fuente intacta y nada junto a la copia."""

    def assertSourceUntouched(self) -> None:
        """La carpeta de la fuente tiene los mismos ficheros con el mismo sha256."""
        assert _source is not None
        self.assertEqual(_fingerprint(_source), _source_before)

    def assertCopyIntact(self, copy: Path) -> None:
        """La copia no cambió (``Mode=Read``) y el motor no dejó su fichero de bloqueo."""
        original = _source_before[copy.name][1]
        self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(), original)
        self.assertEqual(_locks(copy), [])
        self.assertEqual(sorted(p.name for p in copy.parent.iterdir()), [copy.name])

    def _check_extraction(self, done: _Done, tables: object, sql: str,
                          engines: tuple[object, ...]) -> None:
        """Bit a bit como el guion, con uno de ``engines``; el crudo en la salida (el
        ``schema.json`` y un ``.jsonl`` por tabla) y la copia intacta."""
        self.assertTrue(all(isinstance(t, ports.RawTable) for t in tables))
        self.assertEqual(_snapshot(tables), _expected(sql))
        schema = json.loads((done.out / "schema.json").read_text(encoding="utf-8"))
        self.assertIn(ports.MdbEngine(schema["provider"], schema["bits"]), engines)
        self.assertEqual([t["name"] for t in schema["tables"]], [t.name for t in tables])
        files = sorted(p.name for p in done.out.iterdir())
        self.assertEqual(files, sorted(["schema.json"] + [t["file"] for t in schema["tables"]]))
        self.assertCopyIntact(done.copy)


class PortsTest(unittest.TestCase):
    """``interop.ports``: formato por la cabecera, fichero de bloqueo, el puerto y su
    adaptador (sin motor)."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gbmdbp"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_format_from_header(self) -> None:
        """RF-005-14 (plan §5.3.4): el formato sale del byte 0x14 de la cabecera (0 Jet 3, 1
        Jet 4, ≥ 2 ACE, también con extensión ``.mdb``), con su texto para el usuario; lo que
        no es una base de Access o no se puede leer, con su código."""
        cases = {
            "j3.mdb": (0, b"Standard Jet DB", ports.MdbFormat.JET3),
            "j4.mdb": (1, b"Standard Jet DB", ports.MdbFormat.JET4),
            "ace.mdb": (2, b"Standard ACE DB", ports.MdbFormat.ACE),
            "ace5.accdb": (5, b"Standard ACE DB", ports.MdbFormat.ACE),
        }
        for name, (version, magic, expected) in cases.items():
            with self.subTest(base=name):
                path = _fake_base(self.folder, name, version, magic)
                self.assertEqual(ports.read_format(path), (expected, version))
        self.assertIn("Access 2007", ports.MdbFormat.ACE.label)
        self.assertIn("Jet 4", ports.MdbFormat.JET4.label)
        text = self.folder / "sondeos.mdb"
        text.write_text("Sondeo;X;Y\n", encoding="utf-8")
        with self.assertRaises(ports.MdbError) as caught:
            ports.read_format(text)
        self.assertEqual(caught.exception.code, ports.MDB_NOT_ACCESS)
        self.assertEqual(caught.exception.obj, "sondeos.mdb")
        with self.assertRaises(ports.MdbError) as caught:
            ports.read_format(self.folder / "no_existe.mdb")
        self.assertEqual(caught.exception.code, ports.MDB_UNREADABLE)

    def test_lock_file_detected(self) -> None:
        """RF-005-15: la base abierta por otro programa (su ``.ldb`` o ``.laccdb`` al lado,
        con el nombre de la base) se detecta; sin él, nada; el de otra base no cuenta."""
        base = _fake_base(self.folder, "proyecto.v2.mdb", 2, b"Standard ACE DB")
        self.assertIsNone(ports.lock_file(base))
        (self.folder / "otra.laccdb").write_bytes(b"")
        self.assertIsNone(ports.lock_file(base))
        for suffix in (".ldb", ".laccdb"):
            with self.subTest(bloqueo=suffix):
                lock = self.folder / f"proyecto.v2{suffix}"
                lock.write_bytes(b"")
                self.assertEqual(ports.lock_file(base), lock)
                lock.unlink()
        self.assertEqual(ports.LOCK_SUFFIXES, (".ldb", ".laccdb"))

    def test_registry_gives_the_extractor(self) -> None:
        """RF-005-13 (plan §5.6.12, ARQ-07): ``adapters.registry.mdb_extractor()`` da el
        extractor del adaptador, que cumple ``interop.ports.MdbExtractor``, con los motores
        por defecto en su orden de preferencia (ACE de 64 bits; Jet 4.0 de 32, el último)."""
        extractor = registry.mdb_extractor()
        self.assertIsInstance(extractor, mdb_reader.OleDbProcessMdbExtractor)
        self.assertIsInstance(extractor, ports.MdbExtractor)
        self.assertEqual(extractor.engines, mdb_reader.DEFAULT_ENGINES)
        self.assertEqual(mdb_reader.DEFAULT_ENGINES[:2], ACE_64)
        self.assertEqual(mdb_reader.DEFAULT_ENGINES[-1], JET4_32)
        self.assertEqual(JET4_32.label, "Microsoft.Jet.OLEDB.4.0 (32 bits)")

    def test_candidates_by_format(self) -> None:
        """RF-005-14 (plan §5.3.4): Jet 3 y Jet 4, con cualquier motor; ACE, nunca con Jet
        4.0 (no lo lee: «Unrecognized database format»)."""
        engines = mdb_reader.DEFAULT_ENGINES
        for fmt in (ports.MdbFormat.JET3, ports.MdbFormat.JET4):
            self.assertEqual(mdb_reader.candidates(fmt, engines), engines)
        ace = mdb_reader.candidates(ports.MdbFormat.ACE, engines)
        self.assertNotIn(JET4_32, ace)
        self.assertEqual(ace, tuple(e for e in engines if e != JET4_32))
        self.assertEqual(mdb_reader.candidates(ports.MdbFormat.ACE, (JET4_32,)), ())

    def test_engine_missing_message(self) -> None:
        """RF-005-14: el mensaje dice el formato detectado, qué instalar (el motor nombrado de
        forma genérica, en una constante, hasta que IMGA nombre el instalable: DP-70) y la
        alternativa, y que no se importa nada."""
        error = ports.engine_missing("default.mdb", ports.MdbFormat.ACE,
                                     ["Microsoft.Jet.OLEDB.4.0 (32 bits): no lee ACE"])
        self.assertIsInstance(error, ports.MdbError)
        self.assertEqual(error.code, ports.MDB_ENGINE_MISSING)
        self.assertEqual(error.obj, "default.mdb")
        self.assertEqual(error.value, ports.MdbFormat.ACE.label)
        text = str(error)
        self.assertIn(ports.ACCESS_ENGINE, text)
        self.assertIn("motor gratuito de bases de datos de Access de Microsoft", text)
        self.assertIn("CSV", text)
        self.assertIn("no se ha importado nada", text)
        self.assertIn("Microsoft.Jet.OLEDB.4.0 (32 bits)", text)

    def test_ace_base_without_ace_engine(self) -> None:
        """RF-005-14: una base ACE (RecMin Pro) en un equipo con solo el motor de Windows (Jet
        4.0) no se extrae: ``io.mdb_engine_missing`` con el formato, sin lanzar ningún
        proceso ni escribir nada."""
        base = _fake_base(self.folder / "in", "default.mdb", 2, b"Standard ACE DB")
        out = self.folder / "out"
        spy = _PopenSpy()
        extractor = mdb_reader.OleDbProcessMdbExtractor((JET4_32,))
        with spy.patch():
            with self.assertRaises(ports.MdbError) as caught:
                extractor.extract(base, out, lambda f, m: None, lambda: False)
            info = extractor.probe(base)
        self.assertEqual(caught.exception.code, ports.MDB_ENGINE_MISSING)
        self.assertEqual(caught.exception.value, ports.MdbFormat.ACE.label)
        self.assertEqual(spy.processes, [])
        self.assertFalse(out.exists() and any(out.iterdir()))
        self.assertEqual((info.format, info.version, info.engines, info.engine),
                         (ports.MdbFormat.ACE, 2, (), None))

    def test_out_dir_must_be_empty(self) -> None:
        """La carpeta de salida es nueva o está vacía: el crudo de otra extracción no se
        mezcla (``ValueError``, sin lanzar nada)."""
        base = _fake_base(self.folder / "in", "x.mdb", 1, b"Standard Jet DB")
        out = self.folder / "out"
        out.mkdir()
        (out / "schema.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            mdb_reader.OleDbProcessMdbExtractor().extract(base, out, lambda f, m: None,
                                                          lambda: False)


class ScriptFileTest(unittest.TestCase):
    """``adapters/mdb_reader.ps1`` y ADR-0018 en el código."""

    def test_script_file(self) -> None:
        """Plan §2 y ADR-0018: el guion está junto al adaptador, en CRLF, sin BOM, solo ASCII
        (Windows PowerShell 5.1 lee un ``.ps1`` sin BOM como ANSI) y con su línea SPDX como
        comentario."""
        self.assertEqual(mdb_reader.SCRIPT, EXTENSION / "adapters" / "mdb_reader.ps1")
        data = mdb_reader.SCRIPT.read_bytes()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertTrue(data.isascii())
        self.assertEqual(data.decode("ascii").splitlines()[0],
                         "# SPDX-License-Identifier: GPL-3.0-or-later")

    def test_providers_only_in_the_adapter(self) -> None:
        """ADR-0018 («Cómo se verifica»): los proveedores ``Microsoft.ACE.OLEDB`` y
        ``Microsoft.Jet.OLEDB`` y las bibliotecas ``pyodbc``, ``win32com``, ``comtypes`` y
        ``adodbapi`` no aparecen en la extensión fuera de ``adapters/mdb_reader.*``."""
        pattern = re.compile(
            r"Microsoft\.(ACE|Jet)\.OLEDB|\b(import|from)\s+(pyodbc|win32com|comtypes|adodbapi)\b"
        )
        found = []
        for path in sorted(EXTENSION.rglob("*")):
            if (not path.is_file() or path.suffix not in (".py", ".ps1", ".toml")
                    or path.stem == "mdb_reader" and path.parent.name == "adapters"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            found += [f"{path.relative_to(EXTENSION)}: {m.group(0)}"
                      for m in pattern.finditer(text)]
        self.assertEqual(found, [])
        self.assertIn("Microsoft.ACE.OLEDB.16.0", ACE_64[0].provider)


class FakeChildTest(unittest.TestCase):
    """El proceso hijo, con un hijo falso de Python (determinista): cancelación con el hijo
    vivo, una excepción en ``on_progress``, salida con error y silencio."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gbmdbf"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.base = _fake_base(self.folder / "in", "x.mdb", 1, b"Standard Jet DB")
        self.out = self.folder / "out"

    def _child(self, code: str) -> mock._patch[object]:
        """El extractor lanza ``python -c code`` en vez de ``powershell.exe``."""
        command = [sys.executable, "-B", "-s", "-c", code]
        return mock.patch.object(mdb_reader, "_command", side_effect=lambda bits: command)

    PROGRESS_THEN_SLEEP = (
        "import json, sys, time\n"
        "event = {'v': 1, 't': 'progress', 'ts': time.time(), 'frac': 0.25, 'table': 't',"
        " 'index': 1, 'tables': 4, 'row': 3, 'rows': 10}\n"
        "sys.stdout.write(json.dumps(event) + '\\n'); sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )

    def test_cancel_kills_the_child(self) -> None:
        """RNF-008-11 (plan §5.6.12): pedida la cancelación con el hijo vivo, ``extract``
        termina en ≤ 2 s con ``MdbCancelled`` y el hijo ya no vive."""
        recorder = _Recorder(lambda frac, msg: "fila" in msg)
        spy = _PopenSpy()
        extractor = mdb_reader.OleDbProcessMdbExtractor((JET4_32,))
        with self._child(self.PROGRESS_THEN_SLEEP), spy.patch():
            with self.assertRaises(ports.MdbCancelled):
                extractor.extract(self.base, self.out, recorder.on_progress,
                                  recorder.cancelled)
        assert recorder.cancel_at is not None
        self.assertLessEqual(time.perf_counter() - recorder.cancel_at, MAX_CANCEL_S)
        self.assertEqual(len(spy.processes), 1)
        self.assertIsNotNone(spy.processes[0].poll())
        self.assertEqual(recorder.calls[0][1:], (0.0, "Abriendo «x.mdb»"))
        self.assertIn("Tabla «t» (1 de 4): fila 3 de 10", [c[2] for c in recorder.calls])

    def test_progress_exception_kills_the_child(self) -> None:
        """Si ``on_progress`` lanza con el hijo vivo (el ``JobCancelled`` de un worker), la
        excepción sale tal cual y el hijo ya no vive."""

        class Stop(Exception):
            pass

        def on_progress(frac: float, msg: str) -> None:
            if "fila" in msg:
                raise Stop

        spy = _PopenSpy()
        with self._child(self.PROGRESS_THEN_SLEEP), spy.patch():
            with self.assertRaises(Stop):
                mdb_reader.OleDbProcessMdbExtractor((JET4_32,)).extract(
                    self.base, self.out, on_progress, lambda: False)
        self.assertIsNotNone(spy.processes[0].poll())

    def test_child_failure(self) -> None:
        """Un hijo que acaba con error sin decir nada (una directiva que impide el guion)
        da ``io.mdb_extract_failed`` con lo que escribió en la salida de errores."""
        code = ("import sys\nsys.stderr.write('No se puede cargar el archivo: la ejecución "
                "de scripts está deshabilitada')\nsys.exit(1)\n")
        with self._child(code):
            with self.assertRaises(ports.MdbError) as caught:
                mdb_reader.OleDbProcessMdbExtractor((JET4_32,)).extract(
                    self.base, self.out, lambda f, m: None, lambda: False)
        self.assertEqual(caught.exception.code, ports.MDB_EXTRACT_FAILED)
        self.assertIn("la ejecución de scripts está deshabilitada", str(caught.exception))

    def _crudo(self, columns: list[tuple[str, int, int | None]],
               rows: list[list[object]]) -> mock._patch[object]:
        """Un hijo falso que deja en ``-OutDir`` el crudo de una tabla «t» con ``columns`` y
        ``rows`` (ya codificadas como las escribe el guion) y da su resultado."""
        schema = {"v": 1, "provider": JET4_32.provider, "bits": 32, "tables": [{
            "name": "t", "file": "1.jsonl", "rows": len(rows),
            "columns": [{"name": n, "type": t, "size": s} for n, t, s in columns]}]}
        lines = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        code = (
            "import json, os, sys, time\n"
            "out = sys.argv[sys.argv.index('-OutDir') + 1]\n"
            "os.makedirs(out, exist_ok=True)\n"
            f"open(os.path.join(out, '1.jsonl'), 'w', encoding='utf-8', newline='\\n')"
            f".write({lines!r})\n"
            f"open(os.path.join(out, 'schema.json'), 'w', encoding='utf-8')"
            f".write({json.dumps(schema)!r})\n"
            "event = {'v': 1, 't': 'result', 'ts': time.time(), 'summary': {}}\n"
            "sys.stdout.write(json.dumps(event) + '\\n')\n"
        )
        return self._child(code)

    def test_decodes_every_type(self) -> None:
        """RF-005-13, RF-005-02 (plan §5.3.4): el crudo de cada tipo vuelve a su valor exacto:
        Double y Single por sus bits (0,1; −0,0; 0,1 en Single), fecha con microsegundos,
        Currency y Decimal exactos, sí/no, enteros (también Byte y de 64 bits), textos con
        cualquier carácter, GUID, binarios como nulos; las filas, en su orden aunque se
        descodifiquen por trozos; el tamaño, solo en las columnas de texto."""
        columns = [("D", 5, None), ("S", 4, None), ("F", 7, None), ("C", 6, None),
                   ("N", 131, None), ("B", 11, 2), ("I", 2, None), ("U", 17, None),
                   ("L", 20, None), ("T", 130, 50), ("G", 72, None), ("X", 128, None)]
        rows = [
            ["d:3FB999999999999A", "f:3DCCCCCD", "t:2024-03-15T10:20:30.123456", "n:12.3400",
             "n:-1.5", True, -3, 255, 9007199254740993, "Ñandú «x» \u2028\t\"",
             "{6F9619FF-8B86-D011-B42D-00C04FC964FF}", None],
            ["d:8000000000000000", None, None, None, None, False, None, None, None, "", None,
             None],
            [None, "f:408B3333", None, None, None, None, None, None, None, None, None, None],
        ]
        with self._crudo(columns, rows), mock.patch.object(mdb_reader, "CHUNK_ROWS", 2):
            (table,) = mdb_reader.OleDbProcessMdbExtractor((JET4_32,)).extract(
                self.base, self.out, lambda f, m: None, lambda: False)
        self.assertEqual([(c.name, c.type, c.size) for c in table.columns],
                         [(n, t, s if t == 130 else None) for n, t, s in columns])
        first, second, third = table.rows
        self.assertEqual(_bits(first[0]), _bits(0.1))
        self.assertEqual(_bits(first[1]), _bits(np.float32(0.1)))
        self.assertEqual(first[2], dt.datetime(2024, 3, 15, 10, 20, 30, 123456))
        self.assertEqual(_bits(first[3]), _bits(Decimal("12.3400")))
        self.assertEqual(_bits(first[4]), _bits(Decimal("-1.5")))
        self.assertEqual(first[5:9], (True, -3, 255, 9007199254740993))
        self.assertEqual(first[9], "Ñandú «x» \u2028\t\"")
        self.assertEqual(first[10], "{6F9619FF-8B86-D011-B42D-00C04FC964FF}")
        self.assertEqual(_bits(second[0]), _bits(-0.0))
        self.assertEqual((second[5], second[9]), (False, ""))
        self.assertEqual(_bits(third[1]), _bits(np.float32(4.35)))
        self.assertEqual(third[0], None)

    def test_malformed_raw_value(self) -> None:
        """Un valor del crudo que no es de su tipo da ``io.mdb_extract_failed`` con la tabla,
        la columna y su fila (también en otro trozo)."""
        rows = [["d:3FB999999999999A"], ["d:3FB999999999999A"], ["f:3DCCCCCD"]]
        with self._crudo([("D", 5, None)], rows), mock.patch.object(mdb_reader, "CHUNK_ROWS", 2):
            with self.assertRaises(ports.MdbError) as caught:
                mdb_reader.OleDbProcessMdbExtractor((JET4_32,)).extract(
                    self.base, self.out, lambda f, m: None, lambda: False)
        self.assertEqual(caught.exception.code, ports.MDB_EXTRACT_FAILED)
        self.assertIn("«t».«D», fila 3", str(caught.exception))

    def test_powershell_missing(self) -> None:
        """Sin ``powershell.exe`` (o sin saber dónde está Windows), ``io.mdb_extract_failed``
        con el motivo, sin extraer nada."""
        missing = [str(self.folder / "no_existe" / "powershell.exe")]
        with mock.patch.object(mdb_reader, "_command", side_effect=lambda bits: missing):
            with self.assertRaises(ports.MdbError) as caught:
                mdb_reader.OleDbProcessMdbExtractor((JET4_32,)).extract(
                    self.base, self.out, lambda f, m: None, lambda: False)
        self.assertEqual(caught.exception.code, ports.MDB_EXTRACT_FAILED)
        self.assertIn("no se pudo lanzar powershell.exe", str(caught.exception))
        with mock.patch.dict(os.environ, {"SystemRoot": "", "windir": ""}):
            with self.assertRaises(FileNotFoundError):
                mdb_reader.powershell(64)

    def test_silent_child(self) -> None:
        """Un hijo que no dice nada durante el plazo se termina: ``io.mdb_extract_failed``,
        con el avance cada ≤ 0,5 s mientras tanto."""
        recorder = _Recorder()
        spy = _PopenSpy()
        extractor = mdb_reader.OleDbProcessMdbExtractor((JET4_32,), stall_timeout_s=0.6)
        start = time.perf_counter()
        with self._child("import time\ntime.sleep(30)\n"), spy.patch():
            with self.assertRaises(ports.MdbError) as caught:
                extractor.extract(self.base, self.out, recorder.on_progress,
                                  recorder.cancelled)
        self.assertEqual(caught.exception.code, ports.MDB_EXTRACT_FAILED)
        self.assertLess(time.perf_counter() - start, 0.6 + MAX_CANCEL_S)
        self.assertIsNotNone(spy.processes[0].poll())
        times = [start] + [c[0] for c in recorder.calls]
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), MAX_PROGRESS_GAP_S)


class JetExtractionTest(_SourceCheck):
    """Con el motor de Windows (Jet 4.0, ``powershell.exe`` de 32 bits): detección,
    extracción bit a bit, avance, cancelación y motor ausente."""

    def test_probe_detects_engines_with_open(self) -> None:
        """RF-005-13, RF-005-14 (ADR-0018 §5): ``probe`` dice el formato (Jet 4, versión 1) y
        qué motores abren la base con ``OleDbConnection.Open()``: Jet 4.0 de 32 bits, y ACE
        de 64 si está; los que no, con su motivo. La copia no cambia ni queda bloqueo."""
        done = _done["probe_jet4"]
        info = done.get()
        self.assertEqual((info.format, info.version), (ports.MdbFormat.JET4, 1))
        self.assertIn(JET4_32, info.engines)
        if is_available(recmin.ACE):
            self.assertIn(info.engine, ACE_64)
        tried = set(info.engines) | {e for e, _ in info.unavailable}
        self.assertEqual(tried, set(mdb_reader.DEFAULT_ENGINES))
        self.assertTrue(all(reason for _, reason in info.unavailable))
        self.assertCopyIntact(done.copy)
        self.assertSourceUntouched()

    def test_extract_bit_for_bit(self) -> None:
        """RF-005-13, RF-005-02, RF-005-03: la base Jet 4 del esquema 11, leída con Jet 4.0,
        da cada tabla de su guion bit a bit (Single como ``float32``: 0,1 y 4,35; Double;
        fechas; textos; nulos); el crudo queda en la carpeta de salida; la fuente y la copia,
        intactas (la del esquema 12, en la prueba del avance)."""
        done = _done["jet4_v11"]
        self._check_extraction(done, done.get(), V11, (JET4_32,))
        self.assertSourceUntouched()

    def test_progress_inside_tables(self) -> None:
        """RNF-008-11 (plan §5.6.12), RF-005-13: con el avance fila a fila, dentro de cada
        tabla se ven todas sus filas («fila k de n»), el avance no retrocede y acaba en 1, y
        entre dos avances (desde que empieza hasta que acaba) nunca pasan más de 0,5 s; la
        base Jet 4 del esquema 12 sale bit a bit."""
        copy = _job_copy(V12, "jet4")
        done = _Done(copy, _out_dir(copy))
        recorder = _Recorder()
        extractor = mdb_reader.OleDbProcessMdbExtractor((JET4_32,), progress_interval_s=0.0)
        start = time.perf_counter()
        tables = extractor.extract(copy, done.out, recorder.on_progress, recorder.cancelled)
        end = time.perf_counter()
        fracs = [c[1] for c in recorder.calls]
        self.assertEqual(fracs, sorted(fracs))
        self.assertEqual(fracs[-1], 1.0)
        self.assertTrue(all(0.0 <= f <= 1.0 for f in fracs))
        times = [start] + [c[0] for c in recorder.calls] + [end]
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), MAX_PROGRESS_GAP_S)
        seen = {
            int(m.group(1))
            for _, _, msg in recorder.calls
            if (m := re.search(r"«angulos» \(\d+ de 17\): fila (\d+) de 11$", msg))
        }
        self.assertEqual(seen, set(range(0, 12)))
        self._check_extraction(done, tables, V12, (JET4_32,))

    def test_cancel_during_extraction(self) -> None:
        """RNF-008-11, RF-005-03: cancelar durante la lectura termina en ≤ 2 s con
        ``MdbCancelled``, sin el ``powershell.exe`` hijo vivo y sin dejar el bloqueo del
        motor junto a la copia; la fuente, intacta."""
        copy = _job_copy(V12, "jet4")
        recorder = _Recorder(lambda frac, msg: "fila" in msg)
        spy = _PopenSpy()
        extractor = mdb_reader.OleDbProcessMdbExtractor((JET4_32,), progress_interval_s=0.0)
        with spy.patch():
            with self.assertRaises(ports.MdbCancelled):
                extractor.extract(copy, _out_dir(copy), recorder.on_progress,
                                  recorder.cancelled)
        assert recorder.cancel_at is not None
        self.assertLessEqual(time.perf_counter() - recorder.cancel_at, MAX_CANCEL_S)
        self.assertTrue(spy.processes)
        self.assertTrue(all(p.poll() is not None for p in spy.processes))
        self.assertEqual(_locks(copy), [])
        self.assertSourceUntouched()

    def test_unregistered_engine(self) -> None:
        """RF-005-14 (motor ausente simulado): con un proveedor que no está registrado, la
        base no se abre: ``io.mdb_engine_missing`` con el formato (Jet 4) y el motor probado;
        ninguna tabla extraída."""
        done = _done["ghost"]
        with self.assertRaises(ports.MdbError) as caught:
            done.get()
        self.assertEqual(caught.exception.code, ports.MDB_ENGINE_MISSING)
        self.assertEqual(caught.exception.value, ports.MdbFormat.JET4.label)
        self.assertIn(f"{GHOST.label}: no está instalado", str(caught.exception))
        self.assertFalse(done.out.exists() and any(done.out.iterdir()))
        self.assertCopyIntact(done.copy)

    def test_engine_dlls_not_loaded_here(self) -> None:
        """ADR-0018 §2: tras detectar y extraer (al preparar el módulo, con Jet 4.0 y, si
        está, ACE), este proceso no tiene cargado ningún motor de Access (``aceoledb.dll``,
        ``msjetoledb40.dll``…): solo los carga el ``powershell.exe`` hijo."""
        self.assertIsInstance(_done["jet4_v11"].get(), list)
        self.assertEqual([dll for dll in ENGINE_DLLS if _loaded(dll)], [])


@requires(recmin.ACE, recmin.ACE_HINT)
class AceExtractionTest(_SourceCheck):
    """Con el motor ACE de 64 bits (el de las bases de RecMin Pro)."""

    def test_probe_ace_base(self) -> None:
        """RF-005-13, RF-005-14: una base ACE (extensión ``.mdb``, byte 0x14 = 2) la abre
        ACE de 64 bits; Jet 4.0 ni se prueba."""
        done = _done["probe_ace"]
        info = done.get()
        self.assertEqual((info.format, info.version), (ports.MdbFormat.ACE, 2))
        self.assertTrue(info.engines)
        self.assertTrue(set(info.engines) <= set(ACE_64))
        self.assertNotIn(JET4_32, {e for e, _ in info.unavailable})
        self.assertCopyIntact(done.copy)

    def test_extract_bit_for_bit(self) -> None:
        """RF-005-13, RF-005-02, RF-005-03: las dos bases ACE y una Jet 4, con los motores por
        defecto (``adapters.registry.mdb_extractor()``: ACE de 64 bits), dan cada tabla de su
        guion bit a bit; fuente y copias intactas."""
        for key, sql in (("ace_v11", V11), ("ace_v12", V12), ("ace_on_jet4_v12", V12)):
            with self.subTest(extraccion=key):
                done = _done[key]
                self._check_extraction(done, done.get(), sql, ACE_64)
        self.assertSourceUntouched()


if __name__ == "__main__":
    unittest.main()
