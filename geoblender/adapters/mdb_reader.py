# SPDX-License-Identifier: GPL-3.0-or-later
"""Extractor de bases de Access (MDB o ACCDB) en un ``powershell.exe`` aparte (spec 005, T16;
RF-005-03, RF-005-13, RF-005-14, RF-005-15; ADR-0018; plan 005 §5.3.4 y §5.6.12).

:class:`OleDbProcessMdbExtractor` implementa ``interop.ports.MdbExtractor``: lanza el
``powershell.exe`` de Windows (de 64 o de 32 bits, según el motor) con el guion
``mdb_reader.ps1`` de esta carpeta, que abre la base con un proveedor OLE DB del equipo (el
motor de Access, ACE 16 o 12, o Jet 4.0 de Windows) y deja el crudo en la carpeta de salida.
**Ningún proceso de Geoblender carga el motor**: ni Blender ni el worker (ADR-0002 §5).

- **Solo copias.** ``path`` es siempre la copia de la base en la carpeta de un trabajo
  (``JobDir.copy_input`` de la 004, o la de un lector con ``needs_copy``): el motor crea su
  ``.laccdb`` (o ``.ldb``) junto a la base mientras la tiene abierta. Si el hijo termina sin
  cerrarla (cancelación), el extractor borra el fichero de bloqueo que dejó junto a la copia.
- **Motor por el formato** (byte 0x14, ``interop.ports.read_format``): Jet 3 y Jet 4, con
  cualquiera de :data:`DEFAULT_ENGINES` (ACE 16 y 12 de 64 bits, ACE de 32 y Jet 4.0 de 32, en
  ese orden); ACE, nunca con Jet 4.0 (:func:`candidates`). Cada candidato se confirma con
  ``OleDbConnection.Open()`` sobre la copia: el ACE de un Office «Hacer clic y ejecutar» puede
  no verse desde otro proceso (``docs/trampas.md``). Ninguno: ``io.mdb_engine_missing`` con el
  formato detectado, qué instalar y la alternativa (RF-005-14), sin extraer nada.
- **Valores bit a bit**: Double y Single llegan como sus bits IEEE (``"d:"``, ``"f:"``) y se
  dan como ``float`` y ``numpy.float32``; fechas como ``datetime``; Decimal y Currency, como
  ``Decimal`` exacto (``interop.ports.RawTable``).
- **Avance y cancelación** (RNF-008-11 con la alineación de la 005): el hijo informa al empezar
  cada tabla y, dentro, cada :data:`PROGRESS_INTERVAL_S` s; mientras arranca o calla, se repite
  el último avance cada :data:`HEARTBEAT_S` s, y al descodificar el crudo, igual. ``cancelled()``
  se mira cada :data:`POLL_S` s: si es verdadero, el hijo se termina y sale
  :class:`~..interop.ports.MdbCancelled` (≤ 2 s). Dentro de un worker, el hijo está además en
  su *Job Object* (plan 004 §5.4.5). Un hijo que no dice nada en :data:`STALL_TIMEOUT_S` s se
  termina (``io.mdb_extract_failed``).

Este módulo solo importa ``core`` y ``interop.ports`` (ARQ-10); lo crea
``adapters.registry.mdb_extractor()``.
"""

from __future__ import annotations

import functools
import itertools
import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import numpy as np

from ..interop.ports import (
    DBTYPE_BOOL,
    DBTYPE_BYTES,
    DBTYPE_CY,
    DBTYPE_DATE,
    DBTYPE_DECIMAL,
    DBTYPE_I2,
    DBTYPE_I4,
    DBTYPE_NUMERIC,
    DBTYPE_R4,
    DBTYPE_R8,
    DBTYPE_UI1,
    DBTYPE_WSTR,
    LOCK_SUFFIXES,
    MDB_EXTRACT_FAILED,
    MDB_UNREADABLE,
    MdbCancelled,
    MdbEngine,
    MdbError,
    MdbFormat,
    MdbInfo,
    ProgressCallback,
    RawColumn,
    RawTable,
    engine_missing,
    read_format,
)

__all__ = [
    "ACE12_32",
    "ACE12_64",
    "ACE16_32",
    "ACE16_64",
    "DEFAULT_ENGINES",
    "JET4_32",
    "SCRIPT",
    "OleDbProcessMdbExtractor",
    "candidates",
    "powershell",
]

SCRIPT = Path(__file__).with_name("mdb_reader.ps1")
SCHEMA_FILE = "schema.json"

ACE16_64 = MdbEngine("Microsoft.ACE.OLEDB.16.0", 64)
ACE12_64 = MdbEngine("Microsoft.ACE.OLEDB.12.0", 64)
ACE16_32 = MdbEngine("Microsoft.ACE.OLEDB.16.0", 32)
ACE12_32 = MdbEngine("Microsoft.ACE.OLEDB.12.0", 32)
JET4_32 = MdbEngine("Microsoft.Jet.OLEDB.4.0", 32)
DEFAULT_ENGINES: tuple[MdbEngine, ...] = (ACE16_64, ACE12_64, ACE16_32, ACE12_32, JET4_32)
"""Los motores que se prueban, en el orden en que se prefieren: el de Access de 64 bits (el
que IMGA pondrá en sus puestos), el de 32 (con un Office de 32 bits) y el de Windows."""
JET_ONLY: frozenset[str] = frozenset({JET4_32.provider})
"""Los proveedores que solo leen Jet 3 y Jet 4 («Unrecognized database format» con ACE)."""

PROGRESS_INTERVAL_S = 0.2
"""Cada cuánto informa el hijo dentro de una tabla (y el extractor al descodificarla)."""
HEARTBEAT_S = 0.25
"""Cada cuánto se repite el último avance mientras el hijo arranca (Add-Type) o calla."""
POLL_S = 0.05
"""Cada cuánto se mira ``cancelled()`` mientras se espera al hijo."""
STALL_TIMEOUT_S = 120.0
"""Tiempo máximo sin noticias del hijo: más, y se termina."""
KILL_WAIT_S = 1.0
"""Lo que se espera a que muera el hijo tras terminarlo."""
EXTRACT_SHARE = 0.8
"""La parte del avance que es la lectura con el motor; el resto, descodificar el crudo."""
CHUNK_ROWS = 8192
"""Filas del crudo que se descodifican de una vez (entre dos miradas al avance y a la
cancelación)."""
STDERR_LIMIT = 16_384
"""Lo que se guarda de la salida de errores del hijo (para el mensaje)."""

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_EMPTY = object()
_INT_TYPES = frozenset({DBTYPE_I2, DBTYPE_I4, DBTYPE_UI1, 16, 18, 19, 20, 21})
_TEXT_TYPES = frozenset({DBTYPE_WSTR, 129, 72})  # WSTR, STR, GUID
_DATE_TYPES = frozenset({DBTYPE_DATE, 133, 134, 135})
_DECIMAL_TYPES = frozenset({DBTYPE_CY, DBTYPE_DECIMAL, DBTYPE_NUMERIC})
_KIND_TEXT = {
    "not_registered": "no está instalado",
    "unrecognized": "no lee este formato",
}


def powershell(bits: int) -> Path:
    """El ``powershell.exe`` de Windows (5.1) de 64 o de 32 bits, visto desde un proceso de
    64 bits (el de Blender). ``FileNotFoundError`` sin la carpeta de Windows (``SystemRoot``)."""
    root = os.environ.get("SystemRoot") or os.environ.get("windir")
    if not root:
        raise FileNotFoundError("no se sabe dónde está Windows (la variable SystemRoot no está "
                                "definida): no se encuentra powershell.exe")
    folder = {64: "System32", 32: "SysWOW64"}[bits]
    return Path(root) / folder / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _command(bits: int) -> list[str]:
    """La orden del guion, sin sus argumentos: la política de ejecución, solo para ese
    proceso (una directiva de grupo la anula, y entonces falla con su motivo)."""
    return [str(powershell(bits)), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-File", str(SCRIPT)]


def candidates(fmt: MdbFormat, engines: Iterable[MdbEngine]) -> tuple[MdbEngine, ...]:
    """Los motores de ``engines`` que pueden leer el formato ``fmt``, en su orden: Jet 4.0
    no lee ACE."""
    if fmt is MdbFormat.ACE:
        return tuple(e for e in engines if e.provider not in JET_ONLY)
    return tuple(engines)


def _groups(engines: Sequence[MdbEngine]) -> list[tuple[int, tuple[MdbEngine, ...]]]:
    """Los motores por bits (un ``powershell.exe`` para cada uno), en el orden del primero."""
    found: dict[int, list[MdbEngine]] = {}
    for engine in engines:
        found.setdefault(engine.bits, []).append(engine)
    return [(bits, tuple(group)) for bits, group in found.items()]


def _text(data: bytes) -> str:
    """La salida de errores del hijo: UTF-8 (la que pone el guion) o, si no lo es (un error de
    PowerShell antes de ejecutarlo), la página de códigos de la consola."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("oem" if os.name == "nt" else "latin-1", errors="replace")


class _Pacer:
    """Las llamadas a ``on_progress``: el avance nunca retrocede y, si nada nuevo llega, se
    repite cada :data:`HEARTBEAT_S` s."""

    def __init__(self, on_progress: ProgressCallback) -> None:
        self._on_progress = on_progress
        self._frac = 0.0
        self._msg = ""
        self._last = time.monotonic()

    def report(self, frac: float, msg: str) -> None:
        self._frac = max(self._frac, min(1.0, max(0.0, frac)))
        self._msg = msg
        self._call()

    def beat(self) -> None:
        if time.monotonic() - self._last >= HEARTBEAT_S:
            self._call()

    def due(self) -> bool:
        return time.monotonic() - self._last >= PROGRESS_INTERVAL_S

    def _call(self) -> None:
        self._last = time.monotonic()
        self._on_progress(self._frac, self._msg)


class _Child:
    """Un ``powershell.exe`` del guion: sus líneas de la salida estándar (en un hilo), su
    salida de errores (en otro) y su final."""

    def __init__(self, command: list[str]) -> None:
        self.process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=_CREATE_NO_WINDOW,
        )
        self._lines: queue.SimpleQueue[bytes | None] = queue.SimpleQueue()
        self._stderr = bytearray()
        self._threads = (
            threading.Thread(target=self._read_stdout, name="mdb-stdout", daemon=True),
            threading.Thread(target=self._read_stderr, name="mdb-stderr", daemon=True),
        )
        for thread in self._threads:
            thread.start()

    def _read_stdout(self) -> None:
        stream = self.process.stdout
        assert stream is not None
        try:
            for line in iter(stream.readline, b""):
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def _read_stderr(self) -> None:
        stream = self.process.stderr
        assert stream is not None
        for chunk in iter(lambda: stream.read(4096), b""):
            if len(self._stderr) < STDERR_LIMIT:
                self._stderr += chunk[:STDERR_LIMIT - len(self._stderr)]

    def line(self, timeout: float) -> object:
        """La siguiente línea (``bytes``), ``None`` al acabar la salida, o ``_EMPTY`` si no
        llegó nada en ``timeout`` s."""
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            return _EMPTY

    def close(self) -> int | None:
        """Termina el hijo si sigue vivo, espera a que acabe y cierra sus tuberías: su código
        de salida (``None`` si no murió a tiempo)."""
        if self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass
        try:
            code = self.process.wait(timeout=KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            code = None
        for thread in self._threads:
            thread.join(timeout=KILL_WAIT_S)
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()
        return code

    @property
    def stderr(self) -> str:
        return _text(bytes(self._stderr)).strip()


def _spawn(name: str, command: Callable[[], list[str]]) -> _Child:
    """Lanza el guion; si Windows no puede (sin ``powershell.exe``, un antivirus que lo
    impide), ``io.mdb_extract_failed`` con el motivo."""
    try:
        return _Child(command())
    except OSError as exc:
        raise _failed(name, f"no se pudo lanzar powershell.exe ({exc})") from exc


def _event(line: bytes) -> dict[str, Any] | None:
    """Un evento del guion, o ``None`` si la línea no lo es (texto suelto de PowerShell)."""
    try:
        event = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(event, dict) or event.get("v") != 1 or not isinstance(event.get("t"), str):
        return None
    return event


def _progress_message(event: Mapping[str, Any]) -> str:
    return (f"Tabla «{event.get('table', '')}» ({event.get('index', 0)} de "
            f"{event.get('tables', 0)}): fila {event.get('row', 0)} de {event.get('rows', 0)}")


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _attempts(event: Mapping[str, Any],
              engines: Sequence[MdbEngine]) -> list[tuple[MdbEngine, bool, str, str]]:
    """Los intentos de un evento del guion: (motor, abrió, clase, motivo), en su orden."""
    by_provider = {e.provider.casefold(): e for e in engines}
    found = []
    for item in event.get("attempts") or ():
        if not isinstance(item, dict):
            continue
        engine = by_provider.get(str(item.get("provider", "")).casefold())
        if engine is None:
            continue
        kind = str(item.get("kind") or "")
        found.append((engine, item.get("ok") is True, kind,
                      _KIND_TEXT.get(kind) or str(item.get("msg") or kind or "no la abre")))
    return found


def _failed(name: str, reason: str, **context: object) -> MdbError:
    return MdbError(MDB_EXTRACT_FAILED, reason, obj=name, field="extracción", value=None,
                    shown="fallida", context=context)


class _Run:
    """Lo que dijo un ``powershell.exe`` del guion: su resultado o su error, su código de
    salida, su salida de errores y las líneas que no eran eventos."""

    def __init__(self) -> None:
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.code: int | None = None
        self.stderr = ""
        self.noise: list[str] = []

    def detail(self) -> str:
        """Lo que explica un fallo sin evento de error: la salida de errores (o, si no hay,
        lo que no eran eventos) y el código de salida."""
        text = self.stderr or "\n".join(self.noise[-5:])
        code = "sin código" if self.code is None else f"código {self.code}"
        return f"{text} ({code})" if text else f"terminó sin decir por qué ({code})"


class OleDbProcessMdbExtractor:
    """``interop.ports.MdbExtractor`` con el motor de Access del equipo en un
    ``powershell.exe`` aparte (véase el módulo).

    ``engines``: los motores que se prueban, en orden (por defecto, :data:`DEFAULT_ENGINES`;
    otros, para probar uno concreto o simular que falta). ``progress_interval_s``: cada cuánto
    informa el hijo dentro de una tabla (0–0,5 s; 0, cada fila). ``stall_timeout_s``: lo que se
    espera sin noticias del hijo antes de terminarlo."""

    def __init__(
        self,
        engines: Sequence[MdbEngine] = DEFAULT_ENGINES,
        *,
        progress_interval_s: float = PROGRESS_INTERVAL_S,
        stall_timeout_s: float = STALL_TIMEOUT_S,
    ) -> None:
        engines = tuple(engines)
        if not engines or not all(isinstance(e, MdbEngine) for e in engines):
            raise ValueError(f"los motores son una lista no vacía de MdbEngine, no {engines!r}")
        if not 0.0 <= progress_interval_s <= 0.5:
            raise ValueError(f"el avance dentro de una tabla va cada 0–0,5 s, no "
                             f"{progress_interval_s!r}")
        if not stall_timeout_s > 0:
            raise ValueError(f"el plazo sin noticias es positivo, no {stall_timeout_s!r}")
        self.engines = engines
        self.progress_interval_s = float(progress_interval_s)
        self.stall_timeout_s = float(stall_timeout_s)

    def __repr__(self) -> str:
        return f"OleDbProcessMdbExtractor({', '.join(e.label for e in self.engines)})"

    # --- probe ------------------------------------------------------------------------------

    def probe(self, path: Path) -> MdbInfo:
        """El formato de la copia ``path`` y qué motores la abren (``Open()``): un
        ``powershell.exe`` por bits, a la vez. Un motor que no lee el formato no se prueba."""
        path = Path(path)
        fmt, version = read_format(path)
        engines = candidates(fmt, self.engines)
        if not engines:
            return MdbInfo(fmt, version)
        locks = self._locks(path)
        runs: list[tuple[tuple[MdbEngine, ...], _Child]] = []
        try:
            for bits, group in _groups(engines):
                runs.append((group, _spawn(
                    path.name, functools.partial(self._arguments, bits, "probe", path, group))))
            opened: set[MdbEngine] = set()
            failed: dict[MdbEngine, str] = {}
            deadline = time.monotonic() + self.stall_timeout_s
            for group, child in runs:
                run = self._collect(child, deadline)
                summary = run.result.get("summary") if run.result else None
                if not isinstance(summary, dict):
                    raise _failed(path.name, "no se pudo comprobar qué motores la abren: "
                                  + run.detail())
                for engine, ok, _kind, reason in _attempts(summary, group):
                    if ok:
                        opened.add(engine)
                    else:
                        failed[engine] = reason
        finally:
            for _group, child in runs:
                child.close()
            self._clean_locks(path, locks)
        return MdbInfo(
            fmt, version,
            tuple(e for e in engines if e in opened),
            tuple((e, failed[e]) for e in engines if e in failed),
        )

    def _collect(self, child: _Child, deadline: float) -> _Run:
        """Espera a que acabe un hijo de ``probe`` (como mucho hasta ``deadline``)."""
        run = _Run()
        while True:
            line = child.line(max(0.0, min(POLL_S * 4, deadline - time.monotonic())))
            if line is None:
                break
            if line is _EMPTY:
                if time.monotonic() >= deadline:
                    break
                continue
            self._note(run, line)
        run.code = child.close()
        run.stderr = child.stderr
        return run

    # --- extract ----------------------------------------------------------------------------

    def extract(self, path: Path, out_dir: Path, on_progress: ProgressCallback,
                cancelled: Callable[[], bool]) -> list[RawTable]:
        """Las tablas de usuario de la copia ``path``, con el crudo en ``out_dir`` (nueva o
        vacía; si no, ``ValueError``). Véase ``interop.ports.MdbExtractor``."""
        path = Path(path)
        out_dir = Path(out_dir)
        fmt, _version = read_format(path)
        if out_dir.exists() and any(out_dir.iterdir()):
            raise ValueError(f"la carpeta de salida {out_dir} no está vacía")
        engines = candidates(fmt, self.engines)
        if not engines:
            raise engine_missing(path.name, fmt, ())
        pacer = _Pacer(on_progress)
        pacer.report(0.0, f"Abriendo «{path.name}»")
        if cancelled():
            raise MdbCancelled()
        out_dir.mkdir(parents=True, exist_ok=True)
        tried: list[str] = []
        failure: str | None = None
        for bits, group in _groups(engines):
            run = self._extract_with(bits, group, path, out_dir, pacer, cancelled)
            if run.result is not None:
                break
            error = run.error or {}
            if error.get("code") not in ("engine_missing", "open_failed"):
                raise _failed(path.name, "el motor de Access no pudo leer la base: "
                              + (str(error.get("msg") or "") or run.detail()),
                              code=run.code)
            for engine, _ok, kind, reason in _attempts(error, group):
                tried.append(f"{engine.label}: {reason}")
                if kind == "failed" and failure is None:
                    failure = reason
        else:
            if failure is not None:
                raise MdbError(
                    MDB_UNREADABLE,
                    f"el motor de Access no puede abrirla ({failure}); compruebe que no tiene "
                    "contraseña y que se abre con RecMin o Access; no se ha importado nada",
                    obj=path.name, field="base", value=None, shown="no se abre",
                    context={"tried": tried},
                )
            raise engine_missing(path.name, fmt, tried)
        tables = self._decode(path.name, out_dir, pacer, cancelled)
        pacer.report(1.0, f"«{path.name}» leída: {len(tables)} tablas")
        return tables

    def _arguments(self, bits: int, mode: str, path: Path,
                   engines: Sequence[MdbEngine], out_dir: Path | None = None) -> list[str]:
        arguments = [*_command(bits), "-Mode", mode, "-Source", str(path.resolve()),
                     "-Providers", ";".join(e.provider for e in engines)]
        if out_dir is not None:
            arguments += ["-OutDir", str(out_dir.resolve()),
                          "-ProgressMs", str(round(self.progress_interval_s * 1000))]
        return arguments

    def _note(self, run: _Run, line: bytes) -> dict[str, Any] | None:
        """Anota un evento de resultado o de error (y lo devuelve); lo que no es un evento,
        como ruido."""
        event = _event(line)
        if event is None:
            text = _text(line).strip()
            if text:
                run.noise.append(text)
            return None
        if event["t"] == "result":
            run.result = event
        elif event["t"] == "error":
            run.error = event
        return event

    def _extract_with(self, bits: int, engines: Sequence[MdbEngine], path: Path,
                      out_dir: Path, pacer: _Pacer, cancelled: Callable[[], bool]) -> _Run:
        """Un ``powershell.exe`` de ``bits`` bits con los motores ``engines``: su
        :class:`_Run`. Lanza :class:`MdbCancelled` si se cancela, ``io.mdb_extract_failed``
        si el hijo calla demasiado, y lo que lance ``on_progress``; el hijo, siempre
        terminado."""
        run = _Run()
        locks = self._locks(path)
        child = _spawn(path.name, functools.partial(self._arguments, bits, "extract", path,
                                                    engines, out_dir))
        try:
            heard = time.monotonic()
            while True:
                if cancelled():
                    raise MdbCancelled()
                line = child.line(POLL_S)
                if line is None:
                    break
                if line is _EMPTY:
                    if time.monotonic() - heard > self.stall_timeout_s:
                        raise _failed(
                            path.name,
                            f"el proceso que lee la base no responde desde hace más de "
                            f"{self.stall_timeout_s:g} s y se ha terminado",
                        )
                    pacer.beat()
                    continue
                heard = time.monotonic()
                event = self._note(run, line)  # type: ignore[arg-type]
                if event is not None and event["t"] == "progress":
                    pacer.report(EXTRACT_SHARE * _number(event.get("frac")),
                                 _progress_message(event))
                else:
                    pacer.beat()
        finally:
            run.code = child.close()
            run.stderr = child.stderr
            self._clean_locks(path, locks)
        if cancelled():
            raise MdbCancelled()
        if run.result is not None and run.code != 0:
            run.result = None
        if run.result is None and run.error is None:
            raise _failed(path.name, "el proceso que lee la base falló: " + run.detail(),
                          code=run.code)
        return run

    # --- crudo → tablas ---------------------------------------------------------------------

    def _decode(self, name: str, out_dir: Path, pacer: _Pacer,
                cancelled: Callable[[], bool]) -> list[RawTable]:
        """Las tablas del crudo de ``out_dir`` (``schema.json`` y sus ``.jsonl``)."""
        try:
            schema = json.loads((out_dir / SCHEMA_FILE).read_text(encoding="utf-8"))
            entries = schema["tables"]
            total = sum(int(t["rows"]) for t in entries) or 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _failed(name, f"el crudo de la extracción no se entiende ({exc})") from exc
        tables: list[RawTable] = []
        done = 0
        for index, entry in enumerate(entries, 1):
            try:
                table_name = str(entry["name"])
                columns = tuple(RawColumn(str(c["name"]), int(c["type"]),
                                          _size(int(c["type"]), c["size"]))
                                for c in entry["columns"])
                expected = int(entry["rows"])
                source = out_dir / Path(str(entry["file"])).name
            except (KeyError, TypeError, ValueError) as exc:
                raise _failed(name, f"el crudo de la extracción no se entiende ({exc})") from exc
            message = f"Leyendo «{table_name}» ({index} de {len(entries)})"
            pacer.report(EXTRACT_SHARE + (1 - EXTRACT_SHARE) * done / total, message)
            rows: list[tuple[Any, ...]] = []
            try:
                with source.open("r", encoding="utf-8", newline="\n") as handle:
                    while chunk := _chunk(handle, len(rows), len(columns)):
                        for position, column in enumerate(columns):
                            _decode_column(name, table_name, column, chunk, position, len(rows))
                        rows.extend(map(tuple, chunk))
                        if cancelled():
                            raise MdbCancelled()
                        if pacer.due():
                            pacer.report(EXTRACT_SHARE + (1 - EXTRACT_SHARE)
                                         * (done + len(rows)) / total, message)
            except (OSError, ValueError) as exc:
                raise _failed(name, f"el crudo de «{table_name}» no se entiende ({exc})") from exc
            if len(rows) != expected:
                raise _failed(name, f"«{table_name}» tiene {len(rows)} filas en el crudo y "
                              f"{expected} según el motor")
            tables.append(RawTable(table_name, columns, rows))
            done += len(rows)
            if cancelled():
                raise MdbCancelled()
        return tables

    # --- ficheros de bloqueo ----------------------------------------------------------------

    @staticmethod
    def _locks(path: Path) -> set[Path]:
        """Los ficheros de bloqueo que ya había junto a la copia (no son del hijo)."""
        return {path.with_suffix(s) for s in LOCK_SUFFIXES if path.with_suffix(s).exists()}

    @staticmethod
    def _clean_locks(path: Path, before: set[Path]) -> None:
        """Borra el fichero de bloqueo que dejó el motor junto a la copia si el hijo terminó
        sin cerrarla (cancelado o muerto); los que ya estaban, no."""
        for suffix in LOCK_SUFFIXES:
            lock = path.with_suffix(suffix)
            if lock in before:
                continue
            for _attempt in range(5):
                try:
                    lock.unlink(missing_ok=True)
                    break
                except OSError:
                    time.sleep(0.05)


def _size(kind: int, size: object) -> int | None:
    """El tamaño de una columna para ``RawColumn``: el ``CHARACTER_MAXIMUM_LENGTH`` de las de
    texto (``TEXT(n)``: n; ``MEMO``: 0); ``None`` en las demás (el motor da 2 en las
    ``BIT``, que ``schema.json`` conserva)."""
    if kind not in _TEXT_TYPES or size is None:
        return None
    if isinstance(size, bool) or not isinstance(size, int):
        raise TypeError(f"tamaño de columna inesperado: {size!r}")
    return size


def _chunk(handle: Iterable[str], offset: int, width: int) -> list[list[Any]]:
    """Las siguientes :data:`CHUNK_ROWS` filas de un ``.jsonl`` del crudo (vacío al acabar),
    leídas de una vez; ``ValueError`` con su número (``offset`` filas antes) si una no es un
    array JSON de ``width`` valores."""
    lines = list(itertools.islice(handle, CHUNK_ROWS))
    if not lines:
        return []
    try:
        rows = json.loads("[" + ",".join(lines) + "]")
    except ValueError:
        rows = []
        for number, line in enumerate(lines, offset + 1):
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise ValueError(f"la fila {number} no es un array JSON ({exc})") from exc
    for number, row in enumerate(rows, offset + 1):
        if not isinstance(row, list) or len(row) != width:
            raise ValueError(f"la fila {number} no tiene {width} valores")
    return rows


def _decode_column(name: str, table: str, column: RawColumn, rows: list[list[Any]],
                   position: int, offset: int = 0) -> None:
    """Pasa los valores de una columna de un trozo del crudo (``offset`` filas antes) a su
    tipo de Python, en su sitio."""
    kind = column.type
    present = [k for k, row in enumerate(rows) if row[position] is not None]
    if not present:
        return

    def bad(k: int, why: str) -> MdbError:
        return _failed(name, f"valor inesperado en «{table}».«{column.name}», fila "
                       f"{offset + k + 1}: {rows[k][position]!r} ({why})")

    if kind in (DBTYPE_R8, DBTYPE_R4):
        prefix, digits, dtype = ("d:", 16, ">f8") if kind == DBTYPE_R8 else ("f:", 8, ">f4")
        texts = []
        for k in present:
            value = rows[k][position]
            if not (isinstance(value, str) and len(value) == digits + 2
                    and value.startswith(prefix)):
                raise bad(k, f"se esperaba «{prefix}» y {digits} cifras hexadecimales")
            texts.append(value[2:])
        try:
            data = bytes.fromhex("".join(texts))
        except ValueError as exc:
            raise bad(present[0], "no es hexadecimal") from exc
        array = np.frombuffer(data, dtype=dtype)
        values = array.astype(np.float64).tolist() if kind == DBTYPE_R8 else list(
            array.astype(np.float32))
        for k, value in zip(present, values, strict=True):
            rows[k][position] = value
    elif kind in _DATE_TYPES:
        for k in present:
            value = rows[k][position]
            try:
                if not (isinstance(value, str) and value.startswith("t:")):
                    raise ValueError("sin «t:»")
                rows[k][position] = datetime.fromisoformat(value[2:])
            except ValueError as exc:
                raise bad(k, "no es una fecha") from exc
    elif kind in _DECIMAL_TYPES:
        for k in present:
            value = rows[k][position]
            try:
                if not (isinstance(value, str) and value.startswith("n:")):
                    raise ValueError("sin «n:»")
                rows[k][position] = Decimal(value[2:])
            except (ValueError, InvalidOperation) as exc:
                raise bad(k, "no es un número decimal") from exc
    elif kind == DBTYPE_BOOL:
        for k in present:
            if not isinstance(rows[k][position], bool):
                raise bad(k, "no es sí o no")
    elif kind in _INT_TYPES:
        for k in present:
            value = rows[k][position]
            if isinstance(value, bool) or not isinstance(value, int):
                raise bad(k, "no es un entero")
    elif kind in _TEXT_TYPES:
        for k in present:
            if not isinstance(rows[k][position], str):
                raise bad(k, "no es un texto")
    elif kind == DBTYPE_BYTES:
        for k in present:
            rows[k][position] = None
