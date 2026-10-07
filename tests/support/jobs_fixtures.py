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
- :func:`make_wheel`: rueda sintética ``gbtestpkg`` ``py3-none-any`` construida con
  ``zipfile``, reproducible (la misma entrada da la misma huella), para la instalación del
  motor sin red (plan 004 §7.1).
- :func:`make_fake_interpreter`: intérprete falso, un ``.cmd`` que no ejecuta Python:
  ignora los argumentos, escribe lo que se le dio y termina con el código pedido (una
  versión 3.12, un Python sin numpy…).

Datos solo sintéticos (constitución, principio 7): ni rutas absolutas ni datos de un
expediente real (lo comprueba ``tests/unit/jobs/test_jobs_fixtures.py``).
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import time
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tests.support.package import import_geoblender

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
) -> SyntheticWheel:
    """Construye ``dest_dir/<name>-<version>-py3-none-any.whl`` con ``zipfile``: el paquete
    ``<name>/__init__.py`` (``__version__``), los ``extra_files`` (ruta del zip → texto
    UTF-8) y ``<name>-<version>.dist-info/`` con ``METADATA``, ``WHEEL`` y ``RECORD``.
    Reproducible: la misma entrada da la misma huella. Crea ``dest_dir`` si falta."""
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
