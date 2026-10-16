# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayudas de las pruebas de ``geoblender.jobs`` y ``geoblender.workers`` (spec 004, T01;
plan 004 §7 y §7.1).

El plan las llama ``tests/unit/jobs/_support.py``; están aquí porque TST-02 (spec 001,
T43) no admite en una carpeta de pruebas un ``.py`` que no case con ``test*.py`` y manda
las ayudas a ``tests/support/`` (como ``core_fixtures.py`` en la 002). Se importan con
``from tests.support import jobs_fixtures as _support``.

- :func:`jobs_tmp`: carpeta temporal nueva y de ruta corta en ``%TEMP%`` (nunca en el
  repositorio) que se borra al salir. :func:`temp_jobs_root`: la raíz de trabajos
  ``<temporal>/jobs``, ya creada; su madre admite el proyecto falso y los datos de usuario.
- :func:`make_fake_project`: proyecto falso con ``project.gpkg`` y ``blocks.duckdb`` de
  bytes aleatorios y sus huellas sha256 (escritor único, RF-004-14).
- :func:`pid_alive` y :func:`wait_until_dead`: si un proceso de este equipo sigue en
  ejecución, con ``OpenProcess`` + ``GetExitCodeProcess`` (``ctypes``). **Nunca**
  ``os.kill(pid, 0)``: en Windows termina el proceso (docs/trampas.md §2).
- :func:`processes` y :func:`descendants`: la foto de los procesos del equipo
  (``CreateToolhelp32Snapshot``) y, entre dos fotos, los nuevos que descienden de unos
  workers: lo que queda vivo de un trabajo (RNF-004-07; spec 005, T33: el ``powershell.exe``
  hijo de la lectura de una base de RecMin cancelada).
- :func:`make_wheel`: rueda sintética ``gbtestpkg`` ``py3-none-any`` construida con
  ``zipfile``, reproducible (la misma entrada da la misma huella), para la instalación del
  motor sin red (plan 004 §7.1).
- :func:`make_fake_interpreter`: intérprete falso, un ``.cmd`` que no ejecuta Python:
  ignora los argumentos, escribe lo que se le dio y termina con el código pedido (una
  versión 3.12, un Python sin numpy…).
- :func:`prepare_job` y :class:`LaunchedWorker` (T08): la carpeta de un trabajo con su
  ``request.json``, y el arranque ``workers/_bootstrap.py`` lanzado a mano con el Python de
  Blender como lo lanzará el lanzador (plan 004 §5.3.3); :meth:`LaunchedWorker.finish`
  devuelve lo que dejó (:class:`WorkerRun`: código, eventos del canal y ``job.log``).

Datos solo sintéticos (constitución, principio 7): ni rutas absolutas ni datos de un
expediente real (lo comprueba ``tests/unit/jobs/test_jobs_fixtures.py``).
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import importlib.metadata
import os
import subprocess
import sys
import sysconfig
import tempfile
import time
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

# Prefijo corto: las rutas de los trabajos y de ``pip --target`` se alargan dentro, y
# Blender 5.2.1 no admite más de 259 caracteres (docs/trampas.md).
TMP_PREFIX = "gb4-"
JOBS_FOLDER = "jobs"

PROJECT_FILES: tuple[str, str] = ("project.gpkg", "blocks.duckdb")
FAKE_PROJECT_SIZE = 64 * 1024

WHEEL_PACKAGE = "gbtestpkg"
WHEEL_VERSION = "1.0.0"
WHEEL_TAG = "py3-none-any"
# Fecha fija de las entradas del zip: la misma rueda da siempre la misma huella.
_ZIP_DATE = (2026, 1, 1, 0, 0, 0)

_POLL_S = 0.05

WORKER_FLAGS: tuple[str, ...] = ("-I", "-B", "-u")
"""Banderas del Python de Blender al lanzar un worker del entorno ``blender`` (plan 004
§5.3.3): aislado, sin ``__pycache__`` y sin búfer en el canal."""
BOOTSTRAP_PARTS: tuple[str, ...] = ("workers", "_bootstrap.py")
WORKER_KIND = "blender"
WORKER_TIMEOUT_S = 60.0
"""Plazo de seguridad de :meth:`LaunchedWorker.finish`: un worker colgado no cuelga la
prueba (falla y se termina)."""


@contextmanager
def jobs_tmp(prefix: str = TMP_PREFIX) -> Iterator[Path]:
    """Carpeta temporal nueva y de ruta corta en ``%TEMP%``; al salir se borra entera (lo
    que no se pueda borrar, porque un proceso lo tiene abierto, se deja sin fallar)."""
    with tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


@contextmanager
def temp_jobs_root() -> Iterator[Path]:
    """Raíz de trabajos temporal: ``<carpeta temporal>/jobs``, creada y vacía. La carpeta
    temporal (``root.parent``) admite más cosas y se borra entera al salir."""
    with jobs_tmp() as base:
        root = base / JOBS_FOLDER
        root.mkdir()
        yield root


def sha256_file(path: Path) -> str:
    """Huella sha256 (hexadecimal) del fichero ``path``, leído por bloques."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FakeProject:
    """Proyecto falso: una carpeta con ``project.gpkg`` y ``blocks.duckdb`` de bytes
    aleatorios. No son una BD: solo sirven para comprobar que nadie los toca."""

    root: Path

    @property
    def gpkg(self) -> Path:
        return self.root / PROJECT_FILES[0]

    @property
    def duckdb(self) -> Path:
        return self.root / PROJECT_FILES[1]

    def files(self) -> tuple[Path, ...]:
        """Los dos ficheros del proyecto, en el orden de :data:`PROJECT_FILES`."""
        return tuple(self.root / name for name in PROJECT_FILES)

    def fingerprints(self) -> dict[str, str]:
        """Nombre del fichero → huella sha256 (iguales antes y después de un trabajo)."""
        return {path.name: sha256_file(path) for path in self.files()}


def make_fake_project(
    parent: Path, *, name: str = "proyecto", size: int = FAKE_PROJECT_SIZE
) -> FakeProject:
    """Crea ``parent/name`` con los dos ficheros del proyecto de ``size`` bytes aleatorios
    cada uno. Una carpeta que ya existe es un error de la prueba (``FileExistsError``)."""
    if size <= 0:
        raise ValueError(f"el proyecto falso necesita ficheros con bytes (size={size})")
    root = parent / name
    root.mkdir(parents=True)
    project = FakeProject(root)
    for path in project.files():
        path.write_bytes(os.urandom(size))
    return project


def pid_alive(pid: int) -> bool:
    """Verdadero si el proceso ``pid`` de este equipo sigue en ejecución.

    Usa ``core.sysinfo.pid_alive`` (spec 002), que en Windows llama a ``OpenProcess`` y
    ``GetExitCodeProcess`` con ``ctypes`` (vivo si el código es ``STILL_ACTIVE`` = 259) y
    nunca a ``os.kill(pid, 0)``, que lo terminaría. Límite conocido: un proceso que
    terminó con el código 259 parece vivo; las pruebas no usan ese código."""
    return bool(import_geoblender("core.sysinfo").pid_alive(pid))


def blender_numpy_version() -> str:
    """La versión del numpy del Python de Blender (el de su ``site-packages``): la que ven
    los workers ``blender`` y un externo que sea ese Python. Es la del numpy de las pruebas
    salvo en el paso «motor» de ``tools/check.py``, que las ejecuta con el del motor de
    cálculo (spec 004, RF-004-28: ``-S``, sin el ``site-packages`` de Blender)."""
    purelib = sysconfig.get_path("purelib")
    for distribution in importlib.metadata.distributions(name="numpy", path=[purelib]):
        return distribution.version
    raise RuntimeError(f"no hay numpy en el site-packages de este Python ({purelib})")


def wait_until_dead(pid: int, *, timeout_s: float = 5.0) -> bool:
    """Espera, mirando cada 50 ms, a que ``pid`` deje de existir; devuelve si lo hizo antes
    de ``timeout_s`` segundos (p. ej. «el nieto deja de existir en ≤ 5 s», T13)."""
    deadline = time.monotonic() + timeout_s
    while True:
        if not pid_alive(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_S)


_TH32CS_SNAPPROCESS = 0x00000002
_ERROR_NO_MORE_FILES = 18


def _process_entry() -> type:
    """``PROCESSENTRY32W`` de ``Process32FirstW``/``Process32NextW`` (``ctypes``)."""
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    return ProcessEntry


def processes() -> dict[int, tuple[int, str]]:
    """Los procesos de este equipo ahora (Windows, ``CreateToolhelp32Snapshot`` con
    ``ctypes``): pid → (pid del padre, nombre del ejecutable). Con :func:`descendants`, los
    que quedan vivos de un trabajo (spec 004, RNF-004-07; spec 005, RNF-005-05: el
    ``powershell.exe`` hijo de la lectura de una base de RecMin)."""
    import ctypes
    from ctypes import wintypes

    entry_type = _process_entry()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # propio, con sus firmas
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel32, name)
        function.argtypes = (wintypes.HANDLE, ctypes.POINTER(entry_type))
        function.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot is None or snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    found: dict[int, tuple[int, str]] = {}
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            found[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID),
                                               entry.szExeFile)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error not in (0, _ERROR_NO_MORE_FILES):
            raise ctypes.WinError(error)
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def descendants(
    before: Mapping[int, tuple[int, str]],
    after: Mapping[int, tuple[int, str]],
    roots: Iterable[int],
) -> dict[int, str]:
    """Los procesos de ``after`` (:func:`processes`) que no estaban en ``before`` (mismo pid y
    mismo padre) y descienden de algún pid de ``roots`` (también si ese ya terminó: su hijo
    huérfano sigue diciendo su padre): pid → ejecutable."""
    new = {pid: entry for pid, entry in after.items()
           if before.get(pid, (None,))[0] != entry[0]}
    ancestors = set(roots)
    found: dict[int, str] = {}
    grew = True
    while grew:
        grew = False
        for pid, (parent, exe) in new.items():
            if pid not in found and parent in ancestors:
                found[pid] = exe
                ancestors.add(pid)
                grew = True
    return found


@dataclass(frozen=True)
class SyntheticWheel:
    """Una rueda sintética construida por :func:`make_wheel`."""

    path: Path
    name: str
    version: str
    sha256: str
    size: int

    @property
    def filename(self) -> str:
        return self.path.name


def _record_hash(data: bytes) -> str:
    """Huella de una línea de ``RECORD``: sha256 en base64 «urlsafe» sin relleno."""
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_wheel(
    dest_dir: Path,
    *,
    name: str = WHEEL_PACKAGE,
    version: str = WHEEL_VERSION,
    extra_files: Mapping[str, str] | None = None,
    license_expression: str | None = None,
) -> SyntheticWheel:
    """Construye ``dest_dir/<name>-<version>-py3-none-any.whl`` con ``zipfile``: el paquete
    ``<name>/__init__.py`` (``__version__``), los ``extra_files`` (ruta del zip → texto
    UTF-8) y ``<name>-<version>.dist-info/`` con ``METADATA``, ``WHEEL`` y ``RECORD``.
    Con ``license_expression``, ``METADATA`` la declara en ``License-Expression`` (como
    las ruedas de PyPI que siguen PEP 639; T24). Reproducible: la misma entrada da la
    misma huella. Crea ``dest_dir`` si falta."""
    if not name.isidentifier() or not name.islower():
        raise ValueError(
            f"«{name}» no vale como nombre de la rueda sintética (a-z, 0-9 y «_»)"
        )
    info = f"{name}-{version}.dist-info"
    files: dict[str, bytes] = {
        f"{name}/__init__.py": (
            f'"""Paquete sintético de las pruebas de Geoblender."""\n\n'
            f'__version__ = "{version}"\n'
        ).encode("utf-8"),
    }
    for path, text in sorted((extra_files or {}).items()):
        files[path] = text.encode("utf-8")
    files[f"{info}/METADATA"] = (
        "Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        "Summary: Paquete sintético de las pruebas de Geoblender\n"
        + (
            f"License-Expression: {license_expression}\n"
            if license_expression is not None
            else ""
        )
    ).encode("utf-8")
    files[f"{info}/WHEEL"] = (
        "Wheel-Version: 1.0\n"
        "Generator: geoblender-tests\n"
        "Root-Is-Purelib: true\n"
        f"Tag: {WHEEL_TAG}\n"
    ).encode("utf-8")
    record = "".join(
        f"{path},{_record_hash(data)},{len(data)}\n" for path, data in files.items()
    )
    files[f"{info}/RECORD"] = (record + f"{info}/RECORD,,\n").encode("utf-8")

    dest_dir.mkdir(parents=True, exist_ok=True)
    wheel = dest_dir / f"{name}-{version}-{WHEEL_TAG}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, data in files.items():
            entry = zipfile.ZipInfo(path, date_time=_ZIP_DATE)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, data)
    return SyntheticWheel(wheel, name, version, sha256_file(wheel), wheel.stat().st_size)


def make_fake_interpreter(
    folder: Path,
    *,
    stdout: str,
    stderr: str = "",
    exit_code: int = 0,
    name: str = "python",
) -> Path:
    """Crea ``folder/<name>.cmd``, un intérprete falso: ignora los argumentos, escribe en
    la salida ``stdout`` y en la de errores ``stderr`` (UTF-8, tal cual: los textos van en
    ficheros aparte y se muestran con ``type``, sin que cmd los interprete) y termina con
    ``exit_code``. Devuelve la ruta del ``.cmd``; si ya existe, ``FileExistsError``."""
    script = folder / f"{name}.cmd"
    out = folder / f"{name}.out"
    err = folder / f"{name}.err"
    for path in (script, out, err):
        if path.exists():
            raise FileExistsError(f"el intérprete falso «{name}» ya existe ahí")
    folder.mkdir(parents=True, exist_ok=True)
    out.write_bytes(stdout.encode("utf-8"))
    err.write_bytes(stderr.encode("utf-8"))
    lines = [
        "@echo off",
        f'type "%~dp0{out.name}"',
        f'type "%~dp0{err.name}" 1>&2',
        f"exit {int(exit_code)}",
    ]
    script.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
    return script


def bootstrap_path(package_dir: Path = EXTENSION_DIR) -> Path:
    """``<paquete>/workers/_bootstrap.py``, el arranque de los workers en proceso aparte."""
    return Path(package_dir).joinpath(*BOOTSTRAP_PARTS)


def prepare_job(
    jobs_root: Path,
    worker: str = "selftest",
    *,
    params: Mapping[str, Any] | None = None,
    arrays: Mapping[str, Any] | None = None,
    label: str = "Autodiagnóstico de las pruebas",
    timeout_s: float = WORKER_TIMEOUT_S,
) -> Any:
    """Crea en ``jobs_root`` la carpeta de un trabajo ``worker`` (entorno ``blender``) con su
    ``request.json`` y, si se dan, sus entradas ``arrays`` (nombre → ``ndarray``, en
    ``in/<nombre>.npy`` con ``JobDir.write_array``). Devuelve su ``JobDir``. No comprueba el
    catálogo: admite un tipo de trabajo que no existe."""
    protocol = import_geoblender("jobs.protocol")
    paths = import_geoblender("jobs.paths")
    request = protocol.new_request(
        worker, label=label, owner="jobs", params=params, environment=WORKER_KIND,
        timeout_s=timeout_s,
    )
    folder = paths.job_dir(jobs_root, request.job_uid).create()
    inputs = {name: folder.write_array(name, array) for name, array in (arrays or {}).items()}
    if inputs:
        request = dataclasses.replace(request, inputs=inputs)
    protocol.write_request(folder, request)
    return folder


@dataclass(frozen=True)
class WorkerRun:
    """Lo que dejó un worker lanzado a mano: su pid, su código de salida, los bytes de su
    canal, lo que el decodificador del protocolo saca de ellos (``events``, los eventos en
    orden, e ``invalid``, las líneas que no lo son), ``job.log`` y los segundos que pasaron
    desde que se lanzó hasta que la prueba lo vio terminar (cota superior de su duración)."""

    pid: int
    returncode: int
    channel: bytes
    events: tuple[Any, ...]
    invalid: tuple[Any, ...]
    log_bytes: bytes
    elapsed_s: float

    @property
    def log(self) -> str:
        """``job.log`` como texto (UTF-8; un byte que no lo es, como «�»)."""
        return self.log_bytes.decode("utf-8", "replace")

    def types(self) -> list[str]:
        """Los tipos de los eventos, en orden de llegada."""
        return [event.type for event in self.events]

    def of_type(self, kind: str) -> list[Any]:
        """Los eventos del tipo ``kind``, en orden de llegada."""
        return [event for event in self.events if event.type == kind]


class LaunchedWorker:
    """Un worker lanzado a mano con el arranque, como lo lanzará el lanzador (plan 004
    §5.3.3): ``python.exe -I -B -u <paquete>/workers/_bootstrap.py --package-dir <paquete>
    --job-dir <carpeta> --kind blender`` con el Python de las pruebas (el de Blender), la
    carpeta del trabajo como carpeta de trabajo, la entrada estándar en una tubería que la
    prueba mantiene abierta (al cerrarla, :meth:`lose_parent`, el worker se queda sin padre),
    la salida estándar en otra (el canal de eventos) y la de error en ``job.log``.

    ``flags`` cambia las banderas del intérprete y ``args`` los argumentos del arranque
    (``None``: los de arriba). Se lanza al crearlo; :meth:`finish` espera y recoge;
    :meth:`close` lo termina si sigue vivo (para la limpieza de la prueba)."""

    def __init__(
        self,
        job_dir: Path,
        *,
        package_dir: Path = EXTENSION_DIR,
        flags: Sequence[str] = WORKER_FLAGS,
        args: Sequence[str] | None = None,
    ) -> None:
        self.job_dir = Path(job_dir)
        self._log_file = self.job_dir / import_geoblender("jobs.paths").LOG_FILE
        if args is None:
            args = ("--package-dir", str(package_dir), "--job-dir", str(self.job_dir),
                    "--kind", WORKER_KIND)
        command = [sys.executable, *flags, str(bootstrap_path(package_dir)), *args]
        read_end, self._parent = os.pipe()
        try:
            with self._log_file.open("ab") as log:
                self.started = time.monotonic()
                self.process = subprocess.Popen(
                    command, stdin=read_end, stdout=subprocess.PIPE, stderr=log,
                    cwd=self.job_dir,
                )
        except BaseException:
            self.lose_parent()
            raise
        finally:
            os.close(read_end)

    def lose_parent(self) -> None:
        """Cierra el extremo de la tubería de entrada que tiene la prueba: para el worker, el
        padre ha muerto (fin de la entrada estándar)."""
        parent, self._parent = self._parent, None
        if parent is not None:
            os.close(parent)

    def finish(self, timeout_s: float = WORKER_TIMEOUT_S) -> WorkerRun:
        """Espera a que el worker termine (como mucho ``timeout_s`` s: si no, lo termina y
        falla la prueba) leyendo su canal, y devuelve lo que dejó."""
        try:
            channel, _ = self.process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.close()
            raise AssertionError(f"el worker no terminó en {timeout_s} s") from None
        elapsed = time.monotonic() - self.started
        self.lose_parent()
        protocol = import_geoblender("jobs.protocol")
        decoder = protocol.EventDecoder()
        items = decoder.feed(channel) + decoder.close()
        invalid = tuple(item for item in items if isinstance(item, protocol.InvalidLine))
        events = tuple(item for item in items if isinstance(item, protocol.JobEvent))
        log = self._log_file.read_bytes() if self._log_file.exists() else b""
        return WorkerRun(self.process.pid, self.process.returncode, channel, events, invalid,
                         log, elapsed)

    def close(self) -> None:
        """Termina el worker si sigue vivo y cierra sus tuberías (idempotente)."""
        if self.process.poll() is None:
            self.process.kill()
            try:
                self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        elif self.process.stdout is not None and not self.process.stdout.closed:
            self.process.stdout.close()
        self.lose_parent()
